"""EXT-PORT-11 smoke test: run the whole Parca STEP FUNCTION, not just the optimiser method.

Its companion smoke test proved that `Relation.optimize_trna_charging_kinetics` runs. (That was
scripts/smoke_trna_refit.py; it belonged to the ROUTE1 isoacceptor exploration and now lives in
https://github.com/evanniko1/wcecoli-extension-tRNA-isoacceptors, not here.) This proves the
layer above it runs: `fit_sim_data_1.optimize_trna_charging_kinetics`, which is what
--optimize-trna-charging-kinetics actually invokes. That layer does four things the method does not,
and each of them can fail on its own:

  1. writes optimization/trna_charging_kinetics_solutions.tsv and ..._constants.tsv, with the
     charged-fraction anchor recorded in the '#' header;
  2. reloads both through `raw_data._load_tsv`, which is where the flat-file namespace
     (`raw_data.optimization.*`) is derived from the output path;
  3. re-runs `_build_trna_charging_kinetics` off what it just wrote;
  4. exports flat/trna_charging_kinetics.tsv, which iterates ALL 20 synthetases and will KeyError on
     any the fit did not produce a solution for.

It runs with a SCOUTING restart budget so it finishes in minutes. The result is NOT a fit and its
TSVs must not be adopted -- it writes into a scratch directory, never into the checkout.

  export MSYS_NO_PATHCONV=1
  docker run --rm -v "C:/dev/wcEcoli/out:/wcEcoli/out" \
    -v "<repo>/scripts/smoke_trna_parca_step.py:/tmp/p.py" \
    -e PYTHONPATH=/wcEcoli -w /wcEcoli wcecoli-sim:kinetic \
    python -u /tmp/p.py --kb /wcEcoli/out/ep11_parca_final/kb --out /tmp/ep11_out --iterations 2
"""

from __future__ import annotations

import argparse
import functools
import os
import pickle
import sys
import time

import numpy as np

sys.path.insert(0, os.environ.get('WCECOLI_DIR', '/wcEcoli'))

from reconstruction.ecoli import fit_sim_data_1 as F   # noqa: E402
from reconstruction.ecoli.dataclasses.relation import Relation   # noqa: E402


def main(argv=None):
	ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
	ap.add_argument('--kb', required=True, help='Parca kb dir with --save-intermediates output')
	ap.add_argument('--out', required=True, help='scratch dir for the three TSVs; NEVER the checkout')
	ap.add_argument('--target', default='none')
	ap.add_argument('--weight', type=float, default=None)
	ap.add_argument('--iterations', type=int, default=2,
		help='SCOUTING budget. Shipped is 100. The output of this script is not a fit.')
	ap.add_argument('--viable-solutions', type=int, default=1)
	ap.add_argument('--seed', type=int, default=0)
	a = ap.parse_args(argv)

	flat = os.path.join(os.environ.get('WCECOLI_DIR', '/wcEcoli'),
		'reconstruction', 'ecoli', 'flat')
	if os.path.abspath(a.out) == os.path.abspath(flat):
		raise SystemExit('refusing to write a scouting result into the checkout flat/ directory')

	with open(os.path.join(a.kb, 'sim_data_final_adjustments.cPickle'), 'rb') as f:
		sim_data = pickle.load(f)
	with open(os.path.join(a.kb, 'cell_specs_final_adjustments.cPickle'), 'rb') as f:
		cell_specs = pickle.load(f)
	with open(os.path.join(a.kb, 'rawData.cPickle'), 'rb') as f:
		raw_data = pickle.load(f)

	# Scouting budget, injected by wrapping the real method rather than by editing it: the code under
	# test stays exactly what a real run would execute.
	real = Relation.optimize_trna_charging_kinetics

	@functools.wraps(real)
	def _scouting(self, *args, **kw):
		kw.setdefault('iterations', a.iterations)
		kw.setdefault('viable_solutions', a.viable_solutions)
		return real(self, *args, **kw)

	Relation.optimize_trna_charging_kinetics = _scouting

	np.random.seed(a.seed)
	t0 = time.time()
	sim_data, cell_specs = F.optimize_trna_charging_kinetics(
		sim_data, cell_specs, raw_data=raw_data,
		optimize_trna_charging_kinetics=True,
		trna_charged_fraction_target=a.target,
		trna_charged_fraction_weight=a.weight,
		trna_charging_kinetics_out=a.out,
		save_intermediates=False, intermediates_directory='', load_intermediate=None,
		)
	print(f'\nstep function completed in {time.time() - t0:.0f} s')
	print(f'*** SCOUTING RUN (iterations={a.iterations}). NOT a fit; do not adopt these TSVs. ***')

	for rel in (os.path.join('optimization', 'trna_charging_kinetics_solutions.tsv'),
			os.path.join('optimization', 'trna_charging_kinetics_constants.tsv'),
			'trna_charging_kinetics.tsv'):
		path = os.path.join(a.out, rel)
		with open(path) as f:
			lines = f.read().splitlines()
		print(f'\n{rel}: {len(lines)} lines')
		print(f'  header: {lines[0][:200]}')
		if rel.endswith('trna_charging_kinetics.tsv'):
			print(f'  columns: {lines[1]}')
			print(f'  first row: {lines[2][:160]}...')

	rel_obj = sim_data.relation
	print(f'\nrebuilt sim_data.relation from the files just written:')
	print(f'  synthetase_to_k_cat : {len(rel_obj.synthetase_to_k_cat)} synthetases')
	print(f'  trna_to_K_T         : {len(rel_obj.trna_to_K_T)} tRNAs')
	print(f'  free fractions      : {len(rel_obj.trna_condition_to_free_fraction)} (tRNA, condition)')
	return 0


if __name__ == '__main__':
	sys.exit(main())
