"""EXT-PORT-11 regression test: does the ported optimiser reproduce the SHIPPED constants?

The full fit is stochastic (>= 8080 random-restart Powell minimisations) and takes hours, so
"reproduces the shipped constants" cannot mean "rerun it and diff". What it CAN mean, exactly and
in seconds, is this:

    Re-evaluate the ported objective at every solution vector v3.0.1 recorded, using the constants
    v3.0.1 recorded alongside them, and check that it returns the objective value v3.0.1 recorded.

That is a complete test of the term the port could have got wrong. Each row of
`flat/optimization/trna_charging_kinetics_solutions.tsv` carries the full argmin (k_cat, K_A, K_T
per tRNA, f_free per case, f_free_at_min per case) AND the scalar `objective` the 2022 optimiser
computed for it. Each row of `flat/optimization/trna_charging_kinetics_constants.tsv` carries the
four constants that objective was evaluated against (c_synthetase, c_amino_acid, c_trnas per tRNA,
v_codons per codon). Nothing is reconstructed and nothing is assumed: the only things taken from the
current knowledge base are the STRUCTURAL maps (which tRNA reads which codon, which tRNAs share a
K_T), and those are asserted to be consistent with the shipped files rather than trusted.

It also does the thing the port is FOR: with `--target`, it reports what the charged-fraction anchor
would add at those same optima, so the weight can be judged against the ~1e-7 the rest of the
objective actually is, before anyone spends hours on a refit.

Runs against a built knowledge base (out/<parca>/kb/simData.cPickle) inside the model image:

  export MSYS_NO_PATHCONV=1
  docker run --rm -v "C:/dev/wcEcoli/out:/wcEcoli/out" \
    -v "<repo>/scripts/verify_trna_objective.py:/tmp/v.py" \
    -e PYTHONPATH=/wcEcoli -w /wcEcoli wcecoli-sim:kinetic \
    python /tmp/v.py --kb /wcEcoli/out/kinetic_parca/kb/simData.cPickle

Exit status is 0 only if every shipped row is reproduced within tolerance.
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys

import numpy as np

sys.path.insert(0, os.environ.get('WCECOLI_DIR', '/wcEcoli'))

from reconstruction.ecoli.dataclasses.relation import (  # noqa: E402
    TRNA_CHARGED_FRACTION_TARGETS,
    TRNA_CHARGED_FRACTION_WEIGHT_DEFAULT,
    resolve_charged_fraction_target,
    trna_charging_objective,
)

# The SAME reader the Parca uses. Not a hand-rolled TSV parse: these files carry units in their
# column names ("min (units.umol / units.L)"), JSON dict values, and multi-line '#' preambles, and
# a second parser would be a second thing to keep in step with the first.
from reconstruction.spreadsheets import read_tsv  # noqa: E402
from wholecell.utils import units  # noqa: E402

# The optimiser's own constants, restated here so a drift in either copy shows up as a failure
# rather than as agreement. (relation.py: w_b, w_r, n_increments)
W_R = 1e-9
W_B = 1e-9
N_INCREMENTS = 5
CONDITIONS = ['basal', 'with_aa']


def build_case_maps(relation, synthetase, amino_acid, trnas, codons, anchored_conditions):
    """Reproduce the `maps`/`indexes` structures optimize_trna_charging_kinetics builds.

	Uses the SAME method (relation.assign_K_T) the optimiser uses, so this is not a reimplementation
	of the grouping -- only of the loops that lay it out.
	"""
    n_conditions = len(CONDITIONS)
    n_K_T, K_T_indexes, codons_to_trnas = relation.assign_K_T(trnas, codons)

    cases = []
    for condition in CONDITIONS:
        for trna in trnas:
            cases.append(f'{trna}__{condition}')
    n_cases = len(cases)

    f_to_cases = np.zeros((n_cases, n_K_T * n_conditions), dtype=np.int64)
    for row, case in enumerate(cases):
        trna, condition = case.split('__')
        f_to_cases[row, (CONDITIONS.index(condition) * n_K_T) + K_T_indexes[trnas.index(trna)]] = 1

    K_T_to_cases = np.zeros((n_cases, n_K_T), dtype=np.int64)
    for row, case in enumerate(cases):
        trna, condition = case.split('__')
        K_T_to_cases[row, K_T_indexes[trnas.index(trna)]] = 1

    cases_to_trna_sum = np.zeros((n_cases, n_cases), dtype=np.int64)
    for row, case in enumerate(cases):
        trna, condition = case.split('__')
        cases_to_trna_sum[row, [condition in c for c in cases]] = 1

    codon_cases_to_trna_cases = np.zeros(
        (n_cases, len(codons) * n_conditions), dtype=np.bool_)
    for i in range(n_conditions):
        codon_cases_to_trna_cases[
            slice(i * len(trnas), (i + 1) * len(trnas)),
            slice(i * len(codons), (i + 1) * len(codons))] = codons_to_trnas

    cases_to_anchored_conditions = np.zeros((len(anchored_conditions), n_cases), dtype=np.int64)
    for row, condition in enumerate(anchored_conditions):
        for col, case in enumerate(cases):
            if case.split('__')[1] == condition:
                cases_to_anchored_conditions[row, col] = 1

    maps = {
        'f_to_cases': f_to_cases,
        'K_T_to_cases': K_T_to_cases,
        'cases_to_trna_sum': cases_to_trna_sum,
        'codon_cases_to_trna_cases': codon_cases_to_trna_cases,
        'cases_to_anchored_conditions': cases_to_anchored_conditions,
        }

    n_f = n_conditions * n_K_T
    K_T_slice = slice(2, 2 + n_K_T)
    f_slice = slice(K_T_slice.stop, K_T_slice.stop + n_f)
    min_f_slice = slice(f_slice.stop, f_slice.stop + n_f)
    indexes = {
        'k_cat_index': 0,
        'K_A_index': 1,
        'K_T_slice': K_T_slice,
        'f_slice': f_slice,
        'min_f_slice': min_f_slice,
        'n_parameters': min_f_slice.stop,
        }
    return maps, indexes, cases, n_K_T, K_T_indexes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--kb', required=True, help='path to simData.cPickle')
    ap.add_argument('--flat', default=None,
        help='flat dir holding optimization/*.tsv (default: the checkout the KB was built from)')
    ap.add_argument('--target', default='none',
        help='charged-fraction anchor to REPORT (does not change the pass/fail test)')
    ap.add_argument('--weight', type=float, default=None, help='w_a for that report')
    ap.add_argument('--rtol', type=float, default=1e-9,
        help='relative tolerance on the reproduced objective')
    ap.add_argument('--limit', type=int, default=0, help='only check the first N rows (0 = all)')
    a = ap.parse_args(argv)

    wcecoli = os.environ.get('WCECOLI_DIR', '/wcEcoli')
    flat = a.flat or os.path.join(wcecoli, 'reconstruction', 'ecoli', 'flat')

    with open(a.kb, 'rb') as f:
        sim_data = pickle.load(f)
    relation = sim_data.relation

    conc_unit = units.umol / units.L
    solutions = read_tsv(os.path.join(
        flat, 'optimization', 'trna_charging_kinetics_solutions.tsv'))
    constants = read_tsv(os.path.join(
        flat, 'optimization', 'trna_charging_kinetics_constants.tsv'))
    dynamic_range = read_tsv(os.path.join(
        flat, 'optimization', 'trna_synthetase_dynamic_range.tsv'))

    constants_by_key = {r['synthetase_id__condition']: r for r in constants}
    # read_tsv strips the unit off the column name and attaches it to the value, so 'min' is a Unum
    # here -- exactly what relation.py:optimize_trna_charging_kinetics reads and converts the same
    # way (`self.trna_synthetase_samples[key]['min'].asNumber(self.conc_unit)`).
    mins_by_key = {r['synthetase_condition']: r['min'].asNumber(conc_unit)
        for r in dynamic_range}

    targets = resolve_charged_fraction_target(a.target)
    anchored = [c for c in CONDITIONS if targets.get(c) is not None]
    anchor_targets = np.array([targets[c] for c in anchored], dtype=np.float64)
    w_a = TRNA_CHARGED_FRACTION_WEIGHT_DEFAULT if a.weight is None else a.weight

    # Group solution rows by synthetase, and resolve each synthetase's tRNA/codon lists from the
    # knowledge base -- then CHECK those lists against the shipped files instead of trusting them.
    synth_to_aa = {v: k for k, v in relation.amino_acid_to_synthetase.items()}

    n_checked = 0
    n_failed = 0
    worst = (0.0, None)
    per_synthetase = {}
    cache = {}

    for row in solutions:
        if a.limit and n_checked >= a.limit:
            break
        synthetase = row['synthetase_id']
        amino_acid = synth_to_aa.get(synthetase)
        if amino_acid is None:
            print(f'SKIP {synthetase}: not in relation.amino_acid_to_synthetase')
            continue

        if synthetase not in cache:
            trnas = relation.amino_acid_to_trnas[amino_acid]
            codons = relation.amino_acid_to_codons[amino_acid]
            maps, indexes, cases, n_K_T, K_T_indexes = build_case_maps(
                relation, synthetase, amino_acid, trnas, codons, anchored)

            # The shipped constants file is the authority on what the 2022 fit saw. If the
            # knowledge base's tRNA or codon list for this synthetase has drifted, the vectors
            # below would be assembled in a different order and the comparison would be
            # meaningless while still producing numbers. Fail instead.
            c_syn, c_aa, c_trnas, v_codons, v_total = [], [], [], [], []
            for condition in CONDITIONS:
                c = constants_by_key[f'{synthetase}__{condition}']
                # read_tsv already JSON-decodes these columns (no unit in the name, so they come back
                # as plain dicts, not Unums).
                trna_conc = c['trnas']
                codon_rate = c['codons']
                assert list(trna_conc) == list(trnas), (
                    f'{synthetase}/{condition}: shipped tRNA list {list(trna_conc)} != knowledge '
                    f'base list {list(trnas)}')
                assert list(codon_rate) == list(codons), (
                    f'{synthetase}/{condition}: shipped codon list {list(codon_rate)} != knowledge '
                    f'base list {list(codons)}')
                for trna in trnas:
                    c_trnas.append(trna_conc[trna])
                    c_syn.append(c['synthetase'].asNumber(conc_unit))
                    c_aa.append(c['amino_acid'].asNumber(conc_unit))
                v = [codon_rate[codon] for codon in codons]
                v_codons += v
                v_total.append(sum(v))
            cache[synthetase] = dict(
                trnas=trnas, codons=codons, maps=maps, indexes=indexes, cases=cases,
                n_K_T=n_K_T, K_T_indexes=K_T_indexes,
                c_syn=np.array(c_syn), c_aa=np.array(c_aa),
                c_trnas=np.array(c_trnas), v_codons=np.array(v_codons),
                mins=np.array([mins_by_key[f'{synthetase}__{c}'] for c in CONDITIONS]))

        s = cache[synthetase]
        trnas = s['trnas']
        sweep_level = int(row['sweep_level'])

        # c_synthetase_min, exactly as relation.py builds it for this sweep level.
        c_syn_min = []
        for estimated_minimum in (sweep_level / N_INCREMENTS * s['mins']):
            c_syn_min += [estimated_minimum] * len(trnas)
        c_syn_min = np.array(c_syn_min)

        # Reassemble the argmin in the optimiser's own parameter layout, then take log10 because
        # the objective pre-conditions with 10**x.
        K_T_by_trna = row['K_M_trna']
        f_by_case = row['f_free']
        min_f_by_case = row['f_free_at_min']

        # K_T is stored per tRNA but is one value per K_T GROUP; recover the group vector.
        n_K_T = s['n_K_T']
        K_T_vec = np.zeros(n_K_T)
        for i, trna in enumerate(trnas):
            K_T_vec[s['K_T_indexes'][i]] = K_T_by_trna[trna]
        # Same for f: one value per (condition, K_T group).
        f_vec = np.zeros(n_K_T * len(CONDITIONS))
        min_f_vec = np.zeros(n_K_T * len(CONDITIONS))
        for ci, condition in enumerate(CONDITIONS):
            for i, trna in enumerate(trnas):
                col = ci * n_K_T + s['K_T_indexes'][i]
                f_vec[col] = f_by_case[f'{trna}__{condition}']
                min_f_vec[col] = min_f_by_case[f'{trna}__{condition}']

        x = np.zeros(s['indexes']['n_parameters'])
        x[s['indexes']['k_cat_index']] = row['k_cat'].asNumber(1 / units.s)
        x[s['indexes']['K_A_index']] = row['K_M_amino_acid'].asNumber(conc_unit)
        x[s['indexes']['K_T_slice']] = K_T_vec
        x[s['indexes']['f_slice']] = f_vec
        x[s['indexes']['min_f_slice']] = min_f_vec
        x_log = np.log10(x)

        common = (s['indexes'], s['maps'], s['v_codons'], s['c_syn'], c_syn_min,
            s['c_aa'], s['c_trnas'])

        got = trna_charging_objective(
            x_log, *common, W_R, W_B, 0.0, np.array([], dtype=np.float64), False)
        want = float(row['objective'])
        rel = abs(got - want) / max(abs(want), 1e-300)

        n_checked += 1
        if rel > a.rtol:
            n_failed += 1
            if n_failed <= 10:
                print(f'MISMATCH {synthetase} level {sweep_level} iter {row["iteration"]}: '
                    f'shipped {want:.12e}, reproduced {got:.12e}, rel {rel:.3e}')
        if rel > worst[0]:
            worst = (rel, f'{synthetase} level {sweep_level} iter {row["iteration"]}')

        # Decomposition + anchor report, on the BEST row per (synthetase, sweep level) only.
        key = (synthetase, sweep_level)
        if key not in per_synthetase or want < per_synthetase[key]['objective']:
            none_targets = np.array([], dtype=np.float64)
            residual = trna_charging_objective(x_log, *common, 0.0, 0.0, 0.0, none_targets, False)
            term_r = trna_charging_objective(
                x_log, *common, W_R, 0.0, 0.0, none_targets, False) - residual
            term_b = trna_charging_objective(
                x_log, *common, 0.0, W_B, 0.0, none_targets, False) - residual
            term_a = (trna_charging_objective(
                x_log, *common, 0.0, 0.0, w_a, anchor_targets, False) - residual
                if len(anchor_targets) else 0.0)
            charged = 1 - (s['maps']['f_to_cases'] @ f_vec)
            agg = ((s['maps']['cases_to_trna_sum'] @ (charged * s['c_trnas']))
                / (s['maps']['cases_to_trna_sum'] @ s['c_trnas']))
            per_synthetase[key] = dict(
                objective=want, residual=residual, term_r=term_r, term_b=term_b, term_a=term_a,
                charged={c: float(agg[i * len(trnas)]) for i, c in enumerate(CONDITIONS)})

    print()
    print('=' * 100)
    print(f'OBJECTIVE REGRESSION: {n_checked - n_failed}/{n_checked} shipped solution rows '
        f'reproduced within rtol={a.rtol:g}')
    print(f'worst relative error: {worst[0]:.3e} at {worst[1]}')
    print('=' * 100)

    print()
    print(f'DECOMPOSITION at the best row per (synthetase, sweep level), anchor target '
        f'{a.target!r} -> {targets}, w_a={w_a:g}')
    print(f'{"synthetase":22s} {"lvl":>3s} {"objective":>11s} {"residual":>11s} '
        f'{"w_r*sumK_T":>11s} {"w_b*barrier":>11s} {"w_a*anchor":>11s}  charged(basal,with_aa)')
    for (synthetase, level) in sorted(per_synthetase):
        d = per_synthetase[(synthetase, level)]
        print(f'{synthetase:22s} {level:3d} {d["objective"]:11.3e} {d["residual"]:11.3e} '
            f'{d["term_r"]:11.3e} {d["term_b"]:11.3e} {d["term_a"]:11.3e}  '
            f'{d["charged"]["basal"]:.3f}, {d["charged"]["with_aa"]:.3f}')

    if len(anchor_targets):
        ratios = [d['term_a'] / max(d['term_r'], 1e-300) for d in per_synthetase.values()]
        print()
        print(f'anchor / regulariser ratio across the {len(ratios)} groups: '
            f'min {min(ratios):.2f}, median {float(np.median(ratios)):.2f}, max {max(ratios):.2f}')
        print('  <0.1 means the anchor is invisible; >10 means it dominates K_T selection.')

    print()
    print('known target names:', ', '.join(sorted(TRNA_CHARGED_FRACTION_TARGETS)))
    return 1 if n_failed else 0


if __name__ == '__main__':
    sys.exit(main())
