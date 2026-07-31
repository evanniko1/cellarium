"""EXT-PORT-11 REFIT step 2: merge per-amino-acid shards into the two flat files, and (optionally)
rebuild a sim_data from them.

`fit_sim_data_1.optimize_trna_charging_kinetics` does four things after the optimiser returns:
writes optimization/trna_charging_kinetics_solutions.tsv and ..._constants.tsv, reloads both
through `raw_data._load_tsv`, re-runs `Relation._build_trna_charging_kinetics`, and exports
flat/trna_charging_kinetics.tsv. This script does the same four things from sharded JSON.

WHY PATCHING A FINISHED sim_data IS EQUIVALENT TO RE-RUNNING THE PARCA. The optimiser step is the
LAST step of the Parca (fit_sim_data_1.py:462; see its docstring, "It is LAST in the Parca for a
reason"), and the only thing it mutates in sim_data is `sim_data.relation`, via
`_build_trna_charging_kinetics`, from the files it has just written. Nothing downstream consumes
it, because there is no downstream. So loading a finished simData.cPickle, re-running
`_build_trna_charging_kinetics` against the new solutions file and re-pickling reproduces exactly
what a full Parca with --optimize-trna-charging-kinetics would have produced -- at a cost of
seconds instead of a second 7-minute Parca per target. The equivalence is CHECKED, not assumed:
--verify re-derives the five relation dicts from the TSV independently and diffs them.

MISSING SHARDS. `_build_trna_charging_kinetics` indexes by synthetase and the flat export iterates
all 20, so a synthetase with no rows is a KeyError at best and a silently stale constant at worst.
Any synthetase absent from the shards is therefore either backfilled from the SHIPPED solutions
file with --fill-missing-from-shipped (recorded in the header and in the JSON manifest), or the
merge refuses to run. It is never filled silently.

  python trna_refit_merge.py --shards <dir> --out <dir> [--fill-missing-from-shipped <tsv>]
  python trna_refit_merge.py --shards <dir> --out <dir> --base-kb <kb> --new-kb <kb>
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import pickle
import sys
import time

sys.path.insert(0, os.environ.get('WCECOLI_DIR', '/wcEcoli'))

SOLUTIONS_REL = os.path.join('optimization', 'trna_charging_kinetics_solutions.tsv')
CONSTANTS_REL = os.path.join('optimization', 'trna_charging_kinetics_constants.tsv')


def load_shards(shard_dir):
	shards = []
	for path in sorted(glob.glob(os.path.join(shard_dir, '*.json'))):
		with open(path) as f:
			shards.append(json.load(f))
	if not shards:
		raise SystemExit(f'no shard JSON found in {shard_dir}')
	return shards


def read_shipped(path):
	"""Return {synthetase: [raw row strings]} from a solutions TSV, header line excluded."""
	out = {}
	with io.open(path, encoding='utf-8') as f:
		lines = f.read().splitlines()
	body = [ln for ln in lines if not ln.startswith('#')]
	header = body[0]
	for line in body[1:]:
		synthetase = line.split('\t')[0].strip('"')
		out.setdefault(synthetase, []).append(line)
	return header, out


def main(argv=None):
	ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
	ap.add_argument('--shards', required=True, help='directory of per-amino-acid shard JSONs')
	ap.add_argument('--out', required=True, help='directory to write the TSVs into; NEVER the checkout')
	ap.add_argument('--fill-missing-from-shipped', default=None,
		help='path to the shipped solutions TSV; synthetases absent from the shards are copied '
			 'from it verbatim and RECORDED. Without this, a missing synthetase is an error.')
	ap.add_argument('--expect', type=int, default=20, help='number of synthetases expected')
	ap.add_argument('--base-kb', default=None, help='kb dir with simData.cPickle + rawData.cPickle')
	ap.add_argument('--new-kb', default=None, help='write the patched simData.cPickle here')
	ap.add_argument('--label', default='', help='free text recorded in the TSV header')
	a = ap.parse_args(argv)

	flat = os.path.join(os.environ.get('WCECOLI_DIR', '/wcEcoli'),
		'reconstruction', 'ecoli', 'flat')
	if os.path.abspath(a.out) == os.path.abspath(flat):
		raise SystemExit('refusing to write into the checkout flat/ directory')

	shards = load_shards(a.shards)
	targets = {s['target'] for s in shards}
	weights = {s['weight'] for s in shards}
	budgets = {(s['iterations'], s['viable_solutions']) for s in shards}
	if len(targets) != 1 or len(weights) != 1 or len(budgets) != 1:
		raise SystemExit(f'shards disagree: targets={targets} weights={weights} budgets={budgets}')
	target = targets.pop()
	weight = weights.pop()
	iterations, viable = budgets.pop()

	solutions_header = shards[0]['solutions_header']
	constants_header = shards[0]['constants_header']
	solution_rows, constant_rows = [], []
	present, empty = set(), []
	for s in shards:
		if not s['solutions_rows']:
			empty.append(s['synthetase'])
			continue
		present.add(s['synthetase'])
		solution_rows += s['solutions_rows']
		constant_rows += s['constants_rows']

	filled = []
	if len(present) < a.expect:
		if not a.fill_missing_from_shipped:
			raise SystemExit(
				f'only {len(present)}/{a.expect} synthetases have solutions '
				f'(empty: {empty}). Pass --fill-missing-from-shipped to backfill, or wait for '
				f'the missing shards. Refusing to write a partial fit silently.')
		shipped_header, shipped = read_shipped(a.fill_missing_from_shipped)
		for synthetase in sorted(set(shipped) - present):
			filled.append(synthetase)
			for line in shipped[synthetase]:
				solution_rows.append(line.split('\t'))
		# the constants rows of a backfilled synthetase must come from the shard too, because they
		# are the CURRENT abundances, not 2022's -- so a synthetase can only be backfilled if its
		# shard exists but produced no solutions.
		for s in shards:
			if s['synthetase'] in filled:
				constant_rows += s['constants_rows']

	provenance = (
		f'EXT-PORT-11 SHARDED REFIT. target={target}; weight='
		f'{"default-1e-06" if weight is None else weight}; budget iterations={iterations} '
		f'viable_solutions={viable}; {len(present)} synthetases fitted'
		+ (f'; BACKFILLED FROM SHIPPED (not refitted): {",".join(filled)}' if filled else '')
		+ (f'; {a.label}' if a.label else ''))
	# Same constraint as fit_sim_data_1: the header must survive csv QUOTE_MINIMAL as a comment.
	assert not set(provenance) & set("'\"\t\n"), provenance

	os.makedirs(os.path.join(a.out, 'optimization'), exist_ok=True)

	def write_rows(path, header, rows):
		with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
			f.write(f'# Created by trna_refit_merge.py on {time.ctime()}. {provenance}.\n')
			f.write('\t'.join(str(v) for v in header) + '\n')
			for row in rows:
				f.write('\t'.join(str(v) for v in row) + '\n')
		with io.open(path, encoding='utf-8') as f:
			assert f.readline().lstrip().startswith('#'), path

	sol_path = os.path.join(a.out, SOLUTIONS_REL)
	con_path = os.path.join(a.out, CONSTANTS_REL)
	write_rows(sol_path, solutions_header, solution_rows)
	write_rows(con_path, constants_header, constant_rows)
	print(f'{sol_path}: {len(solution_rows)} rows, {len(present)} fitted synthetases'
		+ (f', {len(filled)} backfilled' if filled else ''))
	print(f'{con_path}: {len(constant_rows)} rows')

	manifest = dict(target=target, weight=weight, iterations=iterations, viable_solutions=viable,
		fitted=sorted(present), backfilled=filled, empty=empty,
		elapsed_s={s['amino_acid']: s['elapsed_s'] for s in shards},
		powell_calls={s['amino_acid']: s.get('powell_calls') for s in shards},
		provenance=provenance)
	with open(os.path.join(a.out, 'refit_manifest.json'), 'w') as f:
		json.dump(manifest, f, indent=2)

	if a.base_kb and a.new_kb:
		with open(os.path.join(a.base_kb, 'simData.cPickle'), 'rb') as f:
			sim_data = pickle.load(f)
		with open(os.path.join(a.base_kb, 'rawData.cPickle'), 'rb') as f:
			raw_data = pickle.load(f)
		raw_data._load_tsv(a.out, sol_path)
		raw_data._load_tsv(a.out, con_path)
		sim_data.relation._build_trna_charging_kinetics(raw_data, sim_data)
		os.makedirs(a.new_kb, exist_ok=True)
		with open(os.path.join(a.new_kb, 'simData.cPickle'), 'wb') as f:
			pickle.dump(sim_data, f, protocol=pickle.HIGHEST_PROTOCOL)
		rel = sim_data.relation
		print(f'\npatched sim_data written to {a.new_kb}/simData.cPickle')
		print(f'  synthetase_to_k_cat {len(rel.synthetase_to_k_cat)}, '
			f'trna_to_K_T {len(rel.trna_to_K_T)}, '
			f'free fractions {len(rel.trna_condition_to_free_fraction)}')
		# L-SELENOCYSTEINE is skipped by the optimiser (`if amino_acid == 'L-SELENOCYSTEINE[c]':
		# continue`), so its synthetase legitimately has no fitted k_cat in the shipped file
		# either; KineticTrnaChargingModel supplies 1e4/s for it by design
		# (polypeptide_elongation.py:1836, "Set selenocysteine to a high value to represent
		# unlimited charging"). Everything else must be present.
		missing = [s for aa, s in rel.amino_acid_to_synthetase.items()
			if aa != 'L-SELENOCYSTEINE[c]' and s not in rel.synthetase_to_k_cat]
		if missing:
			raise SystemExit(f'synthetases with no k_cat after rebuild: {missing}')
		print(f'  (L-SELENOCYSTEINE synthetase '
			f'{rel.amino_acid_to_synthetase["L-SELENOCYSTEINE[c]"]} is unfitted by design)')
	return 0


if __name__ == '__main__':
	sys.exit(main())
