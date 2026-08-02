"""TASK B Q5 -- is K_T identified by the steady-state condition, or only by the regulariser?

WHAT THIS ANSWERS. `optimize_trna_charging_kinetics` fits k_cat, K_A, K_T, f and min_f by minimising
(i) two steady-state residual sums, (ii) w_r * sum(K_T), (iii) a barrier on f. Nothing measured
enters. The question this script settles NUMERICALLY, rather than by reading the algebra, is how much
of K_T -- and specifically the WITHIN-FAMILY structure of K_T -- is pinned by the steady-state
condition at all.

METHOD. At each synthetase's shipped optimum, build the residual VECTOR the objective squares and
sums:

    r  = [ 1 - v_charge / v_usage  ,  1 - v_charge_min / v_usage_min ]     (2 * n_cases long)

and take its Jacobian J = dr/d(log10 x) over the same parameter vector the optimiser searches.
rank(J) is the number of parameter directions the steady-state condition can see; the null space is
the set of directions along which the parameters can be moved with the residual unchanged to first
order -- i.e. the gauge. For every null direction we report how much of its norm sits in the K_T
coordinates.

Then a FINITE, non-infinitesimal check, because a null space is only a local statement: rescale one
K_T group by a factor lambda, re-minimise the residual over f and min_f ONLY (K_T, k_cat, K_A held),
and report the residual actually achieved. If the residual returns to the feasibility threshold
(1e-3, relation.py:1646-1650) across orders of magnitude in lambda, then that K_T was never
determined by the data -- the shipped value is whatever the regulariser and the f-bounds happened to
select.

Run inside the model image (needs the KB for the structural maps):

  export MSYS_NO_PATHCONV=1
  docker run --rm -v "C:/dev/wcEcoli/out:/wcEcoli/out" \
    -v "C:/dev/anthropic_hackathon/scripts/trna_kt_identifiability.py:/tmp/kt.py" \
    -e PYTHONPATH=/wcEcoli -w /wcEcoli wcecoli-sim:kinetic \
    python /tmp/kt.py --kb /wcEcoli/out/kinetic_parca/kb/simData.cPickle
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.environ.get('WCECOLI_DIR', '/wcEcoli'))

import pickle  # noqa: E402
from scipy.optimize import least_squares, minimize  # noqa: E402

from reconstruction.spreadsheets import read_tsv  # noqa: E402
from wholecell.utils import units  # noqa: E402

CONDITIONS = ['basal', 'with_aa']
N_INCREMENTS = 5
FEASIBILITY = 1e-3  # relation.py:1646-1650


def bare(v):
    """read_tsv strips units off column NAMES and attaches them to the values, so some of these
    cells arrive as Unum and some as plain floats depending on the column. Strip whatever unit is
    present rather than assuming -- a silent unit mismatch here would rescale a whole synthetase's
    constants and still produce numbers."""
    try:
        return float(v)
    except (TypeError, ValueError):
        pass
    try:
        return float(v.asNumber())
    except AttributeError:
        raise


def build_case_maps(relation, trnas, codons):
    """Same layout loops as optimize_trna_charging_kinetics; grouping via relation.assign_K_T."""
    n_conditions = len(CONDITIONS)
    n_K_T, K_T_indexes, codons_to_trnas = relation.assign_K_T(trnas, codons)

    cases = []
    for condition in CONDITIONS:
        for trna in trnas:
            cases.append('{}__{}'.format(trna, condition))
    n_cases = len(cases)

    f_to_cases = np.zeros((n_cases, n_K_T * n_conditions), dtype=np.int64)
    for row, case in enumerate(cases):
        trna, condition = case.split('__')
        f_to_cases[row, (CONDITIONS.index(condition) * n_K_T)
                   + K_T_indexes[trnas.index(trna)]] = 1

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

    maps = {
        'f_to_cases': f_to_cases,
        'K_T_to_cases': K_T_to_cases,
        'cases_to_trna_sum': cases_to_trna_sum,
        'codon_cases_to_trna_cases': codon_cases_to_trna_cases,
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


def residual_vector(log_x, indexes, maps, v_codons, c_synthetase, c_synthetase_min,
                    c_amino_acid, c_trnas):
    """The vector the objective squares and sums (relation.py:246-307), not the scalar."""
    x = np.power(10, log_x)
    k_cat = x[indexes['k_cat_index']]
    K_A = x[indexes['K_A_index']]
    K_T = x[indexes['K_T_slice']]
    f = x[indexes['f_slice']]
    min_f = x[indexes['min_f_slice']]

    saturation_amino_acid = c_amino_acid / (K_A + c_amino_acid)
    out = []
    for ff, c_syn in ((f, c_synthetase), (min_f, c_synthetase_min)):
        relative_trnas = (maps['f_to_cases'] @ ff) * c_trnas / (maps['K_T_to_cases'] @ K_T)
        trna_sum = maps['cases_to_trna_sum'] @ relative_trnas
        saturation_trnas = relative_trnas / (1 + trna_sum)
        v_charge = k_cat * c_syn * saturation_amino_acid * saturation_trnas

        c_trnas_charged = (1 - (maps['f_to_cases'] @ ff)) * c_trnas
        tile = np.tile(c_trnas_charged, (len(v_codons), 1)).T
        codons_to_trnas = np.where(maps['codon_cases_to_trna_cases'], tile, 0)
        denom = codons_to_trnas.sum(axis=0)
        denom[denom == 0] = 1
        codons_to_trnas = np.divide(codons_to_trnas, denom)
        v_usage = codons_to_trnas @ v_codons
        out.append(1 - (v_charge / v_usage))
    return np.concatenate(out)


def abs_gap(log_x, indexes, maps, v_codons, c_synthetase, c_synthetase_min,
            c_amino_acid, c_trnas):
    """max |v_charge - v_usage| -- the quantity the feasibility filter thresholds."""
    x = np.power(10, log_x)
    k_cat = x[indexes['k_cat_index']]
    K_A = x[indexes['K_A_index']]
    K_T = x[indexes['K_T_slice']]
    worst = 0.0
    saturation_amino_acid = c_amino_acid / (K_A + c_amino_acid)
    for key, c_syn in (('f_slice', c_synthetase), ('min_f_slice', c_synthetase_min)):
        ff = x[indexes[key]]
        relative_trnas = (maps['f_to_cases'] @ ff) * c_trnas / (maps['K_T_to_cases'] @ K_T)
        trna_sum = maps['cases_to_trna_sum'] @ relative_trnas
        v_charge = k_cat * c_syn * saturation_amino_acid * (relative_trnas / (1 + trna_sum))
        c_trnas_charged = (1 - (maps['f_to_cases'] @ ff)) * c_trnas
        tile = np.tile(c_trnas_charged, (len(v_codons), 1)).T
        cc = np.where(maps['codon_cases_to_trna_cases'], tile, 0)
        d = cc.sum(axis=0)
        d[d == 0] = 1
        v_usage = np.divide(cc, d) @ v_codons
        worst = max(worst, float(np.max(np.abs(v_charge - v_usage))))
    return worst


def jacobian(log_x, args, eps=1e-6):
    r0 = residual_vector(log_x, *args)
    J = np.zeros((r0.size, log_x.size))
    for j in range(log_x.size):
        h = np.zeros_like(log_x)
        h[j] = eps
        J[:, j] = (residual_vector(log_x + h, *args)
                   - residual_vector(log_x - h, *args)) / (2 * eps)
    return r0, J


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--kb', required=True)
    ap.add_argument('--flat', default=None)
    ap.add_argument('--sweep-level', type=int, default=4)
    ap.add_argument('--lambdas', default='0.01,0.1,0.5,2,10,100')
    a = ap.parse_args(argv)

    wcecoli = os.environ.get('WCECOLI_DIR', '/wcEcoli')
    flat = a.flat or os.path.join(wcecoli, 'reconstruction', 'ecoli', 'flat')

    with open(a.kb, 'rb') as fh:
        sim_data = pickle.load(fh)
    relation = sim_data.relation
    conc_unit = units.umol / units.L

    solutions = read_tsv(os.path.join(flat, 'optimization',
                                      'trna_charging_kinetics_solutions.tsv'))
    constants = read_tsv(os.path.join(flat, 'optimization',
                                      'trna_charging_kinetics_constants.tsv'))
    dynamic_range = read_tsv(os.path.join(flat, 'optimization',
                                          'trna_synthetase_dynamic_range.tsv'))
    constants_by_key = {r['synthetase_id__condition']: r for r in constants}
    mins_by_key = {r['synthetase_condition']: r['min'].asNumber(conc_unit)
                   for r in dynamic_range}
    synth_to_aa = {v: k for k, v in relation.amino_acid_to_synthetase.items()}

    # best shipped row per synthetase at the requested sweep level
    best = {}
    for row in solutions:
        if int(bare(row['sweep_level'])) != a.sweep_level:
            continue
        s = row['synthetase_id']
        if s not in best or bare(row['objective']) < bare(best[s]['objective']):
            best[s] = row

    lambdas = [float(v) for v in a.lambdas.split(',')]
    totals = {'n_syn': 0, 'n_K_T': 0, 'null_KT': 0, 'feasible_lambda': 0,
              'tried_lambda': 0, 'feasible_global': 0, 'tried_global': 0}

    print('=' * 100)
    print('PER-SYNTHETASE IDENTIFIABILITY OF K_T UNDER THE STEADY-STATE CONDITION')
    print('=' * 100)

    for synthetase in sorted(best):
        row = best[synthetase]
        amino_acid = synth_to_aa.get(synthetase)
        if amino_acid is None:
            print('SKIP {}: not in relation.amino_acid_to_synthetase'.format(synthetase))
            continue
        trnas = relation.amino_acid_to_trnas[amino_acid]
        codons = relation.amino_acid_to_codons[amino_acid]
        maps, indexes, cases, n_K_T, K_T_indexes = build_case_maps(relation, trnas, codons)

        c_syn, c_aa, c_trnas, v_codons = [], [], [], []
        for condition in CONDITIONS:
            c = constants_by_key['{}__{}'.format(synthetase, condition)]
            for trna in trnas:
                c_syn.append(bare(c['synthetase']))
                c_aa.append(bare(c['amino_acid']))
                c_trnas.append(bare(c['trnas'][trna]))
            for codon in codons:
                v_codons.append(bare(c['codons'][codon]))
        c_syn = np.array(c_syn)
        c_aa = np.array(c_aa)
        c_trnas = np.array(c_trnas)
        v_codons = np.array(v_codons)

        c_syn_min = []
        for condition in CONDITIONS:
            m = (a.sweep_level / N_INCREMENTS
                 * mins_by_key['{}__{}'.format(synthetase, condition)])
            c_syn_min.extend([m] * len(trnas))
        c_syn_min = np.array(c_syn_min)

        x = np.zeros(indexes['n_parameters'])
        x[indexes['k_cat_index']] = bare(row['k_cat'])
        x[indexes['K_A_index']] = bare(row['K_M_amino_acid'])
        K_T_by_group = np.zeros(n_K_T)
        for i, trna in enumerate(trnas):
            K_T_by_group[K_T_indexes[i]] = bare(row['K_M_trna'][trna])
        x[indexes['K_T_slice']] = K_T_by_group
        for ci, condition in enumerate(CONDITIONS):
            for i, trna in enumerate(trnas):
                g = K_T_indexes[i]
                x[indexes['f_slice'].start + ci * n_K_T + g] = bare(row['f_free'][cases[
                    ci * len(trnas) + i]])
                x[indexes['min_f_slice'].start + ci * n_K_T + g] = bare(
                    row['f_free_at_min'][cases[ci * len(trnas) + i]])
        log_x = np.log10(x)

        args = (indexes, maps, v_codons, c_syn, c_syn_min, c_aa, c_trnas)
        r0, J = jacobian(log_x, args)
        U, S, Vt = np.linalg.svd(J)
        tol = max(J.shape) * (S[0] if S.size else 0) * 1e-10
        rank = int((S > tol).sum())
        n_par = log_x.size
        nullity = n_par - rank
        kt = np.zeros(n_par, dtype=bool)
        kt[indexes['K_T_slice']] = True

        # how much of the null space lies along K_T
        null = Vt[rank:] if nullity else np.zeros((0, n_par))
        kt_in_null = [float(np.linalg.norm(v[kt])) for v in null]
        # projection of each K_T axis onto the null space -- 1.0 means fully unidentified
        proj = []
        for j in np.where(kt)[0]:
            e = np.zeros(n_par)
            e[j] = 1.0
            proj.append(float(np.linalg.norm(null @ e)) if nullity else 0.0)

        totals['n_syn'] += 1
        totals['n_K_T'] += n_K_T
        totals['null_KT'] += int(sum(p > 0.99 for p in proj))

        print('')
        print('{}  ({} tRNAs, {} K_T groups, {} conditions)'.format(
            synthetase, len(trnas), n_K_T, len(CONDITIONS)))
        print('  parameters = {}  (1 k_cat + 1 K_A + {} K_T + {} f + {} min_f)'.format(
            n_par, n_K_T, n_K_T * len(CONDITIONS), n_K_T * len(CONDITIONS)))
        print('  residual entries = {}   rank(J) = {}   nullity = {}'.format(
            r0.size, rank, nullity))
        print('  |residual|_inf at shipped optimum = {:.2e} ; max|v_charge-v_usage| = {:.2e}'
              .format(float(np.max(np.abs(r0))), abs_gap(log_x, *args)))
        print('  fraction of each K_T axis inside the null space: {}'.format(
            ' '.join('{:.3f}'.format(p) for p in proj)))
        print('  shipped K_T per group (uM): {}'.format(
            ' '.join('{:.3g}'.format(v) for v in K_T_by_group)))

        # ------------------------------------------------------------------
        # FINITE RESCALE TESTS.
        #
        # The claimed degeneracy is in the PRODUCT k_cat * f / K_T, so a rescale test that holds
        # k_cat fixed is not a test of it -- it is a test of "K_T alone at fixed k_cat", which is a
        # different and much tighter question. Both k_cat and K_A are therefore re-fitted here
        # alongside f and min_f, over the SAME box bounds the optimiser uses
        # (relation.py:1413-1426), and with least_squares on the residual VECTOR rather than Powell
        # on its sum, because the target is a root and not a minimum.
        #
        # TEST A (global scale): multiply EVERY K_T group by lambda. Tests whether the overall
        #   magnitude of K_T is pinned by the steady-state condition.
        # TEST B (within-family structure): multiply ONE group by lambda, leaving the others.
        #   Tests whether the RELATIVE K_T structure inside a family -- the 35% spread -- is pinned.
        lo_f, hi_f = np.log10(0.051), np.log10(0.949)
        lo_r, hi_r = -2.0, 10.0

        def refit(y, free):
            """Drive the residual vector to zero over `free`, starting from the shipped point and
            from three log-spaced restarts, and return the best max|v_charge - v_usage|."""
            lb = np.array([lo_f if (indexes['f_slice'].start <= j < indexes['min_f_slice'].stop)
                           else lo_r for j in free])
            ub = np.array([hi_f if (indexes['f_slice'].start <= j < indexes['min_f_slice'].stop)
                           else hi_r for j in free])
            best_gap = np.inf
            starts = [np.clip(y[free], lb, ub)]
            rng = np.random.RandomState(0)
            for _ in range(3):
                starts.append(lb + rng.rand(free.size) * (ub - lb))
            for z0 in starts:
                def fun(z, y=y, free=free):
                    yy = y.copy()
                    yy[free] = z
                    return residual_vector(yy, *args)
                try:
                    res = least_squares(fun, z0, bounds=(lb, ub), xtol=1e-14, ftol=1e-14,
                                        gtol=1e-14, max_nfev=20000)
                except Exception:
                    continue
                yy = y.copy()
                yy[free] = res.x
                best_gap = min(best_gap, abs_gap(yy, *args))
            return best_gap

        free_all = np.r_[indexes['k_cat_index'], indexes['K_A_index'],
                         np.arange(indexes['f_slice'].start, indexes['min_f_slice'].stop)]

        line = []
        for lam in lambdas:
            y = log_x.copy()
            y[indexes['K_T_slice']] += np.log10(lam)
            gap = refit(y, free_all)
            ok = gap <= FEASIBILITY
            totals['tried_global'] += 1
            totals['feasible_global'] += int(ok)
            line.append('{}x:{}({:.1e})'.format(lam, 'FEASIBLE' if ok else 'no', gap))
        print('    ALL K_T x lambda, refit k_cat/K_A/f/min_f: {}'.format('  '.join(line)))

        if n_K_T > 1:
            for g in range(n_K_T):
                line = []
                for lam in lambdas:
                    y = log_x.copy()
                    y[indexes['K_T_slice'].start + g] += np.log10(lam)
                    gap = refit(y, free_all)
                    ok = gap <= FEASIBILITY
                    totals['tried_lambda'] += 1
                    totals['feasible_lambda'] += int(ok)
                    line.append('{}x:{}({:.1e})'.format(lam, 'FEASIBLE' if ok else 'no', gap))
                print('    group {} K_T x lambda only, refit k_cat/K_A/f/min_f: {}'.format(
                    g, '  '.join(line)))
        else:
            print('    (single K_T group -- no within-family structure to test)')

    print('')
    print('=' * 100)
    print('TOTALS: {} synthetases, {} K_T groups; {} K_T axes lie (>0.99) inside the '
          'steady-state null space'.format(totals['n_syn'], totals['n_K_T'], totals['null_KT']))
    print('GLOBAL K_T RESCALE: {} / {} remained FEASIBLE (max|v_charge-v_usage| <= {:g}) '
          'after re-fitting k_cat, K_A, f, min_f'.format(
              totals['feasible_global'], totals['tried_global'], FEASIBILITY))
    print('SINGLE-GROUP K_T RESCALE (within-family structure): {} / {} remained FEASIBLE'.format(
              totals['feasible_lambda'], totals['tried_lambda']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
