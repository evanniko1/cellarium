"""EXT-PORT-11 smoke test: run the REAL tRNA charging optimiser on ONE synthetase.

The full fit is 20 synthetases x 4 sweep levels x >= 100 random restarts, order hours. This runs the
identical code path on a single amino-acid system, which is enough to prove the three things a
"does it run at all" check has to prove and which no amount of reading can:

  1. `Relation.optimize_trna_charging_kinetics` executes end to end -- `self.conditions` is set,
     `print_optimization` is defined, `sim_data.codon_read_rate` is populated, and
     `cell_specs[condition]['bulkAverageContainer']` is reachable.
  2. Accepted solutions actually satisfy the hard feasibility filter, so the numbers are usable.
  3. The charged-fraction ANCHOR moves `f`. Run twice, once with `--target none` and once with a
     named target, and compare the fitted charged fraction. If those two agree, the anchor is
     wired but inert and saying "the anchor works" would be false.

It needs a Parca that was run with --save-intermediates, because the optimiser consumes
cell_specs -- it cannot be run against a finished simData.cPickle alone.

  export MSYS_NO_PATHCONV=1
  docker run --rm -v "C:/dev/wcEcoli/out:/wcEcoli/out" \
    -v "<repo>/scripts/smoke_trna_refit.py:/tmp/s.py" \
    -e PYTHONPATH=/wcEcoli -w /wcEcoli wcecoli-sim:kinetic \
    python /tmp/s.py --kb /wcEcoli/out/ep11_parca/kb --amino-acid TRP[c] --target none
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time

import numpy as np

sys.path.insert(0, os.environ.get('WCECOLI_DIR', '/wcEcoli'))

from reconstruction.ecoli.dataclasses import relation as relation_module   # noqa: E402


def main(argv=None):
	ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
	ap.add_argument('--kb', required=True,
		help='Parca kb dir containing sim_data_final_adjustments.cPickle and '
			 'cell_specs_final_adjustments.cPickle (run the Parca with --save-intermediates)')
	ap.add_argument('--amino-acid', default='TRP[c]',
		help='the single amino-acid system to fit. TRP[c] is the cheapest (1 tRNA, 1 codon).')
	ap.add_argument('--target', default='none', help='charged-fraction anchor')
	ap.add_argument('--weight', type=float, default=None, help='w_a')
	ap.add_argument('--anchor-min-f', action='store_true')
	ap.add_argument('--bounds-weight', type=float, default=1e-9,
		help='w_b. Set 0 to let the anchor act on f without the barrier also pulling toward 0.5.')
	ap.add_argument('--seed', type=int, default=0, help='numpy seed; the restarts are random')
	ap.add_argument('--iterations', type=int, default=100,
		help='random restarts per (synthetase, sweep level). SHIPPED value is 100. Lower it only '
			 'to prove the machinery runs -- a 3-restart result is NOT a fit and must never be '
			 'adopted as constants.')
	ap.add_argument('--viable-solutions', type=int, default=10,
		help='minimum accepted solutions per group before the restart loop may stop. Shipped 10.')
	ap.add_argument('--json-out', default=None, help='write the fitted rows here')
	a = ap.parse_args(argv)

	with open(os.path.join(a.kb, 'sim_data_final_adjustments.cPickle'), 'rb') as f:
		sim_data = pickle.load(f)
	with open(os.path.join(a.kb, 'cell_specs_final_adjustments.cPickle'), 'rb') as f:
		cell_specs = pickle.load(f)

	if not sim_data.codon_read_rate:
		raise SystemExit(
			'sim_data.codon_read_rate is EMPTY. This kb predates the EXT-PORT-11 producer in '
			'fit_sim_data_1.calculateTranslationSupply; the optimiser cannot run against it.')

	# The optimiser loops over sim_data.molecule_groups.amino_acids. Restricting THAT list is how a
	# single system is selected without touching the optimiser -- the code under test is unmodified.
	all_amino_acids = list(sim_data.molecule_groups.amino_acids)
	if a.amino_acid not in all_amino_acids:
		raise SystemExit(f'{a.amino_acid} not in molecule_groups.amino_acids: {all_amino_acids}')
	sim_data.molecule_groups.amino_acids = [a.amino_acid]

	# fit_sim_data_1.optimize_trna_charging_kinetics normally sets this; set it here because this
	# harness bypasses that step function.
	sim_data.relation.conditions = ['basal', 'with_aa']

	np.random.seed(a.seed)
	t0 = time.time()
	solutions, constants = sim_data.relation.optimize_trna_charging_kinetics(
		sim_data, cell_specs,
		charged_fraction_target=a.target,
		charged_fraction_weight=a.weight,
		anchor_min_f=a.anchor_min_f,
		bounds_penalty_weight=a.bounds_weight,
		iterations=a.iterations,
		viable_solutions=a.viable_solutions,
		)
	elapsed = time.time() - t0

	# Column names carry their units, e.g. '"k_cat (1/units.s)"'. read_tsv strips both on the
	# way back in; do the same here so the two views of this file agree.
	def _name(h):
		return h.strip('"').split(' (')[0]
	header = [_name(h) for h in solutions[0]]
	rows = [dict(zip(header, r)) for r in solutions[1:]]
	print(f'\nran {a.amino_acid} in {elapsed:.0f} s; {len(rows)} accepted solutions')
	if a.iterations < 100 or a.viable_solutions < 10:
		print(f'  *** SCOUTING RUN (iterations={a.iterations}, viable_solutions='
			f'{a.viable_solutions}; shipped 100/10). This proves the machinery runs. It is NOT a '
			f'fit and these constants must not be adopted. ***')

	if not rows:
		raise SystemExit('NO accepted solutions -- the feasibility filter rejected every restart.')

	# Report the best solution per sweep level, and the charged fraction it implies. c_trnas comes
	# from the constants rows the optimiser itself just wrote, so the weighting matches the fit.
	trnas = sim_data.relation.amino_acid_to_trnas[a.amino_acid]
	c_header = [_name(h) for h in constants[0]]
	c_rows = {dict(zip(c_header, r))['synthetase_id__condition'].strip('"'):
		dict(zip(c_header, r)) for r in constants[1:]}

	best = {}
	for row in rows:
		lvl = int(row['sweep_level'])
		if lvl not in best or float(row['objective']) < float(best[lvl]['objective']):
			best[lvl] = row

	out = []
	print(f'{"lvl":>3s} {"objective":>11s} {"k_cat":>10s} {"K_A":>10s} '
		f'{"charged basal":>14s} {"charged with_aa":>16s}')
	for lvl in sorted(best):
		row = best[lvl]
		f_free = json.loads(row['f_free'])
		charged = {}
		for condition in ['basal', 'with_aa']:
			conc = json.loads(c_rows[f'{row["synthetase_id"].strip(chr(34))}__{condition}']['trnas'])
			num = sum((1 - f_free[f'{t}__{condition}']) * conc[t] for t in trnas)
			charged[condition] = num / sum(conc[t] for t in trnas)
		print(f'{lvl:3d} {float(row["objective"]):11.4e} {float(row["k_cat"]):10.3f} '
			f'{float(row["K_M_amino_acid"]):10.3f} {charged["basal"]:14.4f} '
			f'{charged["with_aa"]:16.4f}')
		out.append(dict(sweep_level=lvl, objective=float(row['objective']),
			k_cat=float(row['k_cat']), K_A=float(row['K_M_amino_acid']),
			K_T=json.loads(row['K_M_trna']), charged=charged))

	if a.json_out:
		with open(a.json_out, 'w') as f:
			json.dump(dict(amino_acid=a.amino_acid, target=a.target, weight=a.weight,
				bounds_weight=a.bounds_weight, seed=a.seed, elapsed_s=elapsed,
				n_accepted=len(rows), best=out), f, indent=2)
		print(f'wrote {a.json_out}')
	return 0


if __name__ == '__main__':
	sys.exit(main())
