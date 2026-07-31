"""EXT-PORT-11 REFIT, sharded by amino-acid system.

`Relation.optimize_trna_charging_kinetics` is a SERIAL loop over
`sim_data.molecule_groups.amino_acids`; there is no multiprocessing in it, which is why
`runParca.py --cpus N` does not speed the step up and why a full fit is order 9-10 h.

The loop body is, however, INDEPENDENT per amino acid: each iteration reads only that amino
acid's synthetase / tRNAs / codons and appends its own rows. So the fit shards exactly, and
this script runs ONE shard by restricting `molecule_groups.amino_acids` to a single entry --
the same mechanism scripts/smoke_trna_refit.py uses. The optimiser source is NOT modified.

WHAT SHARDING CHANGES, and it is not nothing: v3.0.1 draws every random restart of every
amino acid from ONE numpy global stream seeded once. Sharding gives each amino acid its own
stream. The restarts are i.i.d. draws from the same distributions either way, so the fit is
statistically equivalent, but it is NOT bit-identical to a serial run and must not be
described as one.

Output is JSON rather than TSV so that shards can be merged without any of them having to
know about the others' header rows; scripts/trna_refit_merge.py writes the two TSVs.

  export MSYS_NO_PATHCONV=1
  docker run --rm -v "C:/dev/wcEcoli/out:/wcEcoli/out" -v "<shard dir>:/shards" \
    -v "<repo>/scripts/trna_refit_shard.py:/tmp/s.py" \
    -e PYTHONPATH=/wcEcoli -w /wcEcoli wcecoli-sim:kinetic \
    python -u /tmp/s.py --kb /wcEcoli/out/ep11_parca_final/kb --amino-acid TRP[c] \
        --target avcilar_kucukgoze_2016 --out /shards/A__TRP.json
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


def main(argv=None):
	ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
	ap.add_argument('--kb', required=True,
		help='Parca kb dir written with --save-intermediates (needs '
			 'sim_data_final_adjustments.cPickle and cell_specs_final_adjustments.cPickle)')
	ap.add_argument('--amino-acid', required=True)
	ap.add_argument('--target', default='none')
	ap.add_argument('--weight', type=float, default=None, help='w_a; None -> shipped default 1e-6')
	ap.add_argument('--bounds-weight', type=float, default=1e-9, help='w_b; shipped 1e-9')
	ap.add_argument('--regularization-weight', type=float, default=1e-9, help='w_r; shipped 1e-9')
	ap.add_argument('--anchor-min-f', action='store_true')
	ap.add_argument('--iterations', type=int, default=100, help='SHIPPED budget is 100')
	ap.add_argument('--viable-solutions', type=int, default=10, help='SHIPPED budget is 10')
	ap.add_argument('--seed', type=int, default=0)
	ap.add_argument('--out', required=True)
	a = ap.parse_args(argv)

	with open(os.path.join(a.kb, 'sim_data_final_adjustments.cPickle'), 'rb') as f:
		sim_data = pickle.load(f)
	with open(os.path.join(a.kb, 'cell_specs_final_adjustments.cPickle'), 'rb') as f:
		cell_specs = pickle.load(f)

	if not sim_data.codon_read_rate:
		raise SystemExit('sim_data.codon_read_rate is EMPTY; this kb predates the EXT-PORT-11 '
			'producer in fit_sim_data_1.calculateTranslationSupply.')

	all_amino_acids = list(sim_data.molecule_groups.amino_acids)
	if a.amino_acid not in all_amino_acids:
		raise SystemExit(f'{a.amino_acid} not in molecule_groups.amino_acids')
	sim_data.molecule_groups.amino_acids = [a.amino_acid]

	# fit_sim_data_1.optimize_trna_charging_kinetics sets this unconditionally; this harness
	# bypasses that step function, so set it to the same value.
	sim_data.relation.conditions = ['basal', 'with_aa']

	# PROGRESS INSTRUMENTATION, harness-side only. The restart loop is
	# `while (iteration < iterations) or (viable_solution < viable_solutions)`, so a system whose
	# feasibility-filter acceptance rate is near zero runs unboundedly and is indistinguishable
	# from a hang by looking at the process. Counting Powell calls from outside makes the
	# difference visible without editing the model source. `relation` does a module-level
	# `from scipy.optimize import minimize`, so rebinding that name is enough.
	from reconstruction.ecoli.dataclasses import relation as _relation
	_real_minimize = _relation.minimize
	_state = {'n': 0, 't': time.time()}

	def _counting_minimize(*args, **kw):
		_state['n'] += 1
		if _state['n'] % 100 == 0:
			print(f'  ... {_state["n"]} Powell calls, {time.time() - _state["t"]:.0f} s elapsed',
				flush=True)
		return _real_minimize(*args, **kw)

	_relation.minimize = _counting_minimize

	np.random.seed(a.seed)
	t0 = time.time()
	solutions, constants = sim_data.relation.optimize_trna_charging_kinetics(
		sim_data, cell_specs,
		charged_fraction_target=a.target,
		charged_fraction_weight=a.weight,
		anchor_min_f=a.anchor_min_f,
		regularization_weight=a.regularization_weight,
		bounds_penalty_weight=a.bounds_weight,
		iterations=a.iterations,
		viable_solutions=a.viable_solutions,
		)
	elapsed = time.time() - t0

	# `sweep_level` comes off np.arange and is np.int64, which json cannot serialise; the rest of
	# the row is str/float. Cast rather than reach for a custom encoder, so what lands in the JSON
	# is exactly what tsv.writer would have written.
	def _plain(rows):
		return [[int(v) if isinstance(v, np.integer)
			else float(v) if isinstance(v, np.floating) else v for v in row] for row in rows]

	payload = dict(
		amino_acid=a.amino_acid,
		synthetase=sim_data.relation.amino_acid_to_synthetase[a.amino_acid],
		trnas=list(sim_data.relation.amino_acid_to_trnas[a.amino_acid]),
		target=a.target,
		weight=a.weight,
		bounds_weight=a.bounds_weight,
		regularization_weight=a.regularization_weight,
		anchor_min_f=a.anchor_min_f,
		iterations=a.iterations,
		viable_solutions=a.viable_solutions,
		seed=a.seed,
		elapsed_s=elapsed,
		powell_calls=_state['n'],
		solutions_header=solutions[0],
		solutions_rows=_plain(solutions[1:]),
		constants_header=constants[0],
		constants_rows=_plain(constants[1:]),
		)
	os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
	with open(a.out, 'w') as f:
		json.dump(payload, f)
	print(f'SHARD DONE {a.amino_acid} target={a.target} '
		f'{len(payload["solutions_rows"])} solutions in {elapsed:.0f} s -> {a.out}')
	return 0


if __name__ == '__main__':
	sys.exit(main())
