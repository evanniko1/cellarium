"""EXT-PORT-11 REFIT step 3: compare fitted constants across targets, against the shipped fit.

Reads one or more solutions TSVs (the shipped one plus each refit), applies the SAME selection the
model applies -- `Relation._build_trna_charging_kinetics` keeps, per (synthetase, sweep level), the
row with the lowest objective, and the default sweep level is 4 -- and reports:

  * K_T per tRNA, and the log10 shift against the shipped fit;
  * the abundance-weighted charged fraction each fit implies per synthetase per condition, using
    the tRNA abundances from that fit's OWN constants file (they are the current KB's abundances,
    which is the whole reason for refitting);
  * the aggregate charged fraction over all tRNAs, abundance-weighted, which is the quantity the
    anchor targets;
  * the four-way objective decomposition is NOT recomputed here -- the optimiser prints it per
    (synthetase, sweep level) and those lines are in the shard logs.

The charged fraction reported here is what the FIT implies at its own optimum. It is not what the
simulation does: the simulation integrates the kinetics forward and lands somewhere else. Both
numbers matter and they must not be conflated.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys

import numpy as np

DEFAULT_SWEEP_LEVEL = 4


def read_solutions(path, sweep_level=DEFAULT_SWEEP_LEVEL):
	"""Best (lowest-objective) row per synthetase at one sweep level."""
	with io.open(path, encoding='utf-8') as f:
		body = [ln for ln in f.read().splitlines() if not ln.startswith('#')]
	header = [h.strip('"').split(' (')[0] for h in body[0].split('\t')]
	best = {}
	for line in body[1:]:
		row = dict(zip(header, line.split('\t')))
		if int(row['sweep_level']) != sweep_level:
			continue
		synthetase = row['synthetase_id'].strip('"')
		objective = float(row['objective'])
		if synthetase not in best or objective < best[synthetase]['objective']:
			best[synthetase] = dict(
				objective=objective,
				k_cat=float(row['k_cat']),
				K_A=float(row['K_M_amino_acid']),
				K_T=json.loads(row['K_M_trna']),
				f_free=json.loads(row['f_free']),
				)
	return best


def read_constants(path):
	with io.open(path, encoding='utf-8') as f:
		body = [ln for ln in f.read().splitlines() if not ln.startswith('#')]
	header = [h.strip('"').split(' (')[0] for h in body[0].split('\t')]
	out = {}
	for line in body[1:]:
		row = dict(zip(header, line.split('\t')))
		out[row['synthetase_id__condition'].strip('"')] = json.loads(row['trnas'])
	return out


def summarise(name, solutions, constants, conditions=('basal', 'with_aa')):
	per_synthetase = {}
	totals = {c: [0.0, 0.0] for c in conditions}
	for synthetase, sol in solutions.items():
		per_synthetase[synthetase] = {}
		for condition in conditions:
			key = f'{synthetase}__{condition}'
			if key not in constants:
				continue
			conc = constants[key]
			num = den = 0.0
			for trna, c in conc.items():
				free = sol['f_free'][f'{trna}__{condition}']
				num += (1.0 - free) * c
				den += c
			per_synthetase[synthetase][condition] = num / den if den else float('nan')
			totals[condition][0] += num
			totals[condition][1] += den
	aggregate = {c: (totals[c][0] / totals[c][1] if totals[c][1] else float('nan'))
		for c in conditions}
	return dict(name=name, aggregate=aggregate, per_synthetase=per_synthetase)


def main(argv=None):
	ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
	ap.add_argument('--fit', action='append', required=True, metavar='NAME=DIR',
		help='NAME=<dir containing optimization/trna_charging_kinetics_*.tsv>. The FIRST is the '
			 'reference that K_T shifts are measured against.')
	ap.add_argument('--sweep-level', type=int, default=DEFAULT_SWEEP_LEVEL)
	ap.add_argument('--exclude', action='append', default=[],
		help='synthetase to drop from EVERY fit including the reference. Use when one system is '
			 'backfilled rather than refitted, so the aggregate stays comparable across arms.')
	ap.add_argument('--json-out', default=None)
	a = ap.parse_args(argv)

	fits = []
	for spec in a.fit:
		name, _, directory = spec.partition('=')
		sol = read_solutions(
			os.path.join(directory, 'optimization', 'trna_charging_kinetics_solutions.tsv'),
			a.sweep_level)
		con = read_constants(
			os.path.join(directory, 'optimization', 'trna_charging_kinetics_constants.tsv'))
		for synthetase in a.exclude:
			sol.pop(synthetase, None)
		fits.append((name, sol, con))
	if a.exclude:
		print(f'EXCLUDED from every fit including the reference: {a.exclude}')

	ref_name, ref_sol, ref_con = fits[0]

	print(f'sweep level {a.sweep_level}; reference = {ref_name}\n')
	print(f'{"fit":14s} {"agg f basal":>12s} {"agg f with_aa":>14s} {"K_T median":>11s} '
		f'{"K_T IQR":>16s} {"median |dlog10 K_T|":>20s} {"median dlog10 k_cat":>20s}')
	summary = []
	for name, sol, con in fits:
		s = summarise(name, sol, con)
		K_T_all, dlog, dkcat = [], [], []
		for synthetase, entry in sol.items():
			for trna, v in entry['K_T'].items():
				K_T_all.append(v)
				if synthetase in ref_sol and trna in ref_sol[synthetase]['K_T']:
					r = ref_sol[synthetase]['K_T'][trna]
					if v > 0 and r > 0:
						dlog.append(math.log10(v / r))
			if synthetase in ref_sol:
				dkcat.append(math.log10(entry['k_cat'] / ref_sol[synthetase]['k_cat']))
		K_T_all = np.array(K_T_all)
		q1, q3 = np.percentile(K_T_all, [25, 75])
		s['K_T'] = dict(n=int(K_T_all.size), median=float(np.median(K_T_all)),
			q1=float(q1), q3=float(q3), min=float(K_T_all.min()), max=float(K_T_all.max()))
		s['dlog10_K_T_median_abs'] = float(np.median(np.abs(dlog))) if dlog else 0.0
		s['dlog10_K_T_median'] = float(np.median(dlog)) if dlog else 0.0
		s['dlog10_k_cat_median'] = float(np.median(dkcat)) if dkcat else 0.0
		s['objective_sum'] = float(sum(e['objective'] for e in sol.values()))
		summary.append(s)
		print(f'{name:14s} {s["aggregate"]["basal"]:12.4f} {s["aggregate"]["with_aa"]:14.4f} '
			f'{s["K_T"]["median"]:11.3f} [{q1:7.3f},{q3:7.3f}] '
			f'{s["dlog10_K_T_median_abs"]:20.4f} {s["dlog10_k_cat_median"]:20.4f}')

	print(f'\nper-synthetase abundance-weighted charged fraction, basal:')
	names = [s['name'] for s in summary]
	print(f'{"synthetase":22s} ' + ' '.join(f'{n:>10s}' for n in names))
	for synthetase in sorted(ref_sol):
		cells = []
		for s in summary:
			v = s['per_synthetase'].get(synthetase, {}).get('basal')
			cells.append(f'{v:10.4f}' if v is not None else f'{"-":>10s}')
		print(f'{synthetase:22s} ' + ' '.join(cells))

	if a.json_out:
		with open(a.json_out, 'w') as f:
			json.dump(summary, f, indent=2)
		print(f'\nwrote {a.json_out}')
	return 0


if __name__ == '__main__':
	sys.exit(main())
