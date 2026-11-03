"""Measure how the tRNA charged fraction RESPONDS to the anchor weight and the bounds penalty.

THE QUESTION. EXT-PORT-11 added a charged-fraction anchor to the refit objective, and the campaign's
Phase 5 assumed that anchoring at 0.55 and at 0.85 would produce two visibly different cells. Measured
on the cluster (kinetic campaign v2, Phase 1): the no-anchor build lands at 0.754, the 0.55 build at
0.688, the 0.85 build at 0.774. Both moved the right way, but only a little, and 3.3x further down than
up at the same weight. Nobody has measured the RESPONSE CURVE -- what the achieved fraction does as the
weight rises -- or the reachable ceiling, so there is nothing to choose a weight from.

WHAT THIS DOES, AND WHAT IT IS NOT. For one synthetase it starts from the SHIPPED argmin and re-runs
Powell at each (w_a, w_b) it is given, with the same method, bounds and options the real fit uses, and
reports where the optimum moves to. Two consequences worth being explicit about:

  * It is a LOCAL re-optimisation from one starting point, not a random-restart search. The real fit
    runs >= 8080 restarts and explores globally. This measures the direction and size of the response
    to a weight, which is what choosing a weight needs; it does NOT produce constants, and its output
    must never be adopted as a knowledge base.
  * It does NOT apply the hard feasibility filter (max|v_charge - v_usage| <= 1e-3) that the real fit
    applies as an accept/reject AFTER minimising. The steady-state residual is reported at every point
    so an infeasible excursion is visible rather than silent.

WHY THE DEGENERACY COLUMN IS THE POINT. The steady-state condition identifies only the product
k_cat * f / K_T; k_cat, K_T and f are jointly degenerate. The simulation consumes k_cat, K_A and K_T
and never reads f. So an anchor on f can be satisfied by trading k_cat against K_T along the degenerate
direction, leaving the product -- and therefore the simulated cell -- untouched. `k_cat/K_T` and
`k_cat*f/K_T` are printed at every point: if they hold still while f moves, the anchor is acting on a
gauge choice the simulation cannot see, and no weight will ever change a simulated charged fraction.

Runs against a built knowledge base inside the model image:

  export MSYS_NO_PATHCONV=1
  docker run --rm -v "C:/dev/wcEcoli/out:/wcEcoli/out:ro" \
    -v "<repo>/scripts:/tmp/s:ro" \
    -v "<repo>/model_overlay/files/reconstruction/ecoli/dataclasses/relation.py:\
/wcEcoli/reconstruction/ecoli/dataclasses/relation.py:ro" \
    -e PYTHONPATH=/wcEcoli -w /wcEcoli wcecoli-sim:ep11 \
    python -u /tmp/s/scout_anchor_weight.py --kb /wcEcoli/out/refit_shipped/kb/simData.cPickle
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys

import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Inserted here as well as inside verify_trna_objective, so the imports below do not depend on that
# module having been imported first.
sys.path.insert(0, os.environ.get('WCECOLI_DIR', '/wcEcoli'))

# `verify_trna_objective` shares the per-synthetase assembly with this script deliberately: its two
# extracted functions are evaluated against every shipped solution row by that script's own objective
# regression, so a parameter-layout mistake fails there rather than producing plausible numbers here.
import verify_trna_objective as V  # noqa: E402
from reconstruction.ecoli.dataclasses.relation import (  # noqa: E402
    resolve_charged_fraction_target,
    trna_charging_objective,
)
from reconstruction.spreadsheets import read_tsv  # noqa: E402
from wholecell.utils import units  # noqa: E402

# relation.py's own optimiser settings, restated so a drift shows up as disagreement, not agreement.
F_LOWER, F_UPPER = 0.051, 0.949
K_CAT_BOUND = (-2, 10)
POWELL = {'maxiter': 1000, 'ftol': 1e-5}


def decompose(x_log, common, w_r, w_b, w_a, anchor_targets, anchor_min_f):
    """The five terms, each isolated by zeroing the other weights -- as verify_trna_objective does."""
    none = np.array([], dtype=np.float64)
    residual = trna_charging_objective(x_log, *common, 0.0, 0.0, 0.0, none, False)
    reg = trna_charging_objective(x_log, *common, w_r, 0.0, 0.0, none, False) - residual
    barrier = trna_charging_objective(x_log, *common, 0.0, w_b, 0.0, none, False) - residual
    anchor = (trna_charging_objective(
        x_log, *common, 0.0, 0.0, w_a, anchor_targets, anchor_min_f) - residual
        if len(anchor_targets) else 0.0)
    total = trna_charging_objective(
        x_log, *common, w_r, w_b, w_a, anchor_targets, anchor_min_f)
    return total, residual, reg, barrier, anchor


def charged_aggregate(x_log, s):
    """Abundance-weighted charged fraction per condition, exactly as the anchor term forms it."""
    x = np.power(10, x_log)
    f = x[s['indexes']['f_slice']]
    charged = 1 - (s['maps']['f_to_cases'] @ f)
    num = s['maps']['cases_to_trna_sum'] @ (charged * s['c_trnas'])
    den = s['maps']['cases_to_trna_sum'] @ s['c_trnas']
    agg = num / den
    # one row per case; the distinct values are the per-condition aggregates
    return np.asarray(agg).ravel()


def charged_at_anchored(x_log, s):
    """One charged fraction per ANCHORED condition, in `anchored` order.

    Uses `cases_to_anchored_conditions` -- the anchor term's own selector -- rather than indexing the
    per-case aggregate by hand. `cases` is condition-major, so a hand-rolled index is off by a
    multiple of len(trnas) for every condition after the first; this cannot be.
    """
    x = np.power(10, x_log)
    f = x[s['indexes']['f_slice']]
    charged = 1 - (s['maps']['f_to_cases'] @ f)
    sel = s['maps']['cases_to_anchored_conditions']
    pool = sel @ s['c_trnas']
    return np.asarray((sel @ (charged * s['c_trnas'])) / pool).ravel()


def gauge(x_log, s):
    """(k_cat, median K_T, k_cat/K_T, k_cat*f/K_T) -- the degenerate product and its factors."""
    x = np.power(10, x_log)
    k_cat = float(x[s['indexes']['k_cat_index']])
    K_T = x[s['indexes']['K_T_slice']]
    f = x[s['indexes']['f_slice']]
    return k_cat, float(np.median(K_T)), k_cat / float(np.median(K_T)), \
        k_cat * float(np.median(f)) / float(np.median(K_T))


def build_bounds(s):
    """bounds_2 from relation.py: k_cat, K_A and every K_T in (-2, 10); f and min_f in the box."""
    idx = s['indexes']
    b = [None] * idx['n_parameters']
    b[idx['k_cat_index']] = K_CAT_BOUND
    b[idx['K_A_index']] = K_CAT_BOUND
    for i in range(*idx['K_T_slice'].indices(idx['n_parameters'])):
        b[i] = K_CAT_BOUND
    for sl in (idx['f_slice'], idx['min_f_slice']):
        for i in range(*sl.indices(idx['n_parameters'])):
            b[i] = (float(np.log10(F_LOWER)), float(np.log10(F_UPPER)))
    assert all(x is not None for x in b), 'a parameter was left unbounded'
    return b


def anchored_f_positions(s, anchored):
    """The f-slice positions belonging to the ANCHORED condition only.

    `f` is laid out as (condition, K_T group) with conditions in V.CONDITIONS order, so condition ci
    owns [ci*n_K_T, (ci+1)*n_K_T). Scaling the whole slice would drag the unanchored condition along
    too, which the anchor term itself never does -- it is formed only over the anchored conditions.
    """
    idx = s['indexes']
    start = idx['f_slice'].indices(idx['n_parameters'])[0]
    out = []
    for condition in anchored:
        ci = V.CONDITIONS.index(condition)
        out += list(range(start + ci * s['n_K_T'], start + (ci + 1) * s['n_K_T']))
    return out


def reachability(s, x0, common, anchored, targets):
    """Is the anchor target reachable at a FEASIBLE steady-state balance, for this synthetase?

    Three measurements, no anchor term involved in any of them -- this asks about the geometry of the
    constraint, not about a weight:

      start   the shipped argmin: its residual and its charged fraction.
      f_only  `f` for the anchored condition scaled so the fraction lands on the target, nothing else
              touched. Isolates what the fraction alone costs.
      refit   the fraction HELD there (equal bounds, the device relation.py uses to pin K_A) while
              k_cat, K_A, every K_T and min_f are re-fitted freely to minimise the residual. This is
              the question Phase 5 rests on: can some OTHER chemistry support the target?

    A `refit` residual near the shipped one means the target is reachable and only the anchor's
    weight is in question. A `refit` residual orders above it means the target is unreachable by
    construction, and no weight will ever produce it.
    """
    idx = s['indexes']
    none = np.array([], dtype=np.float64)
    out = {}

    def resid(x_log):
        return float(trna_charging_objective(x_log, *common, 0.0, 0.0, 0.0, none, False))

    start_charged = charged_at_anchored(x0, s)[0]
    target = float(targets[anchored[0]])
    out['start_residual'] = resid(x0)
    out['start_charged'] = start_charged
    out['target'] = target

    # charged = 1 - f, so landing on the target needs f scaled by (1-target)/(1-charged)
    pos = anchored_f_positions(s, anchored)
    scale = (1.0 - target) / (1.0 - start_charged)
    xa = x0.copy()
    xa[pos] = np.log10(np.clip(np.power(10, x0[pos]) * scale, F_LOWER, F_UPPER))
    out['scale'] = scale
    out['f_only_residual'] = resid(xa)
    out['f_only_charged'] = float(charged_at_anchored(xa, s)[0])

    # Hold f at the target; free everything else, including min_f -- a fairer test than pinning it,
    # because min_f is not anchored and the min-synthetase balance should be free to re-satisfy.
    bd = build_bounds(s)
    for i in pos:
        bd[i] = (float(xa[i]), float(xa[i]))
    res = minimize(trna_charging_objective, xa, method='Powell', bounds=bd,
        args=(*common, 0.0, V.W_B, 0.0, none, False),
        options={'maxiter': 20000, 'ftol': 1e-10})
    out['refit_residual'] = resid(res.x)
    out['refit_charged'] = float(charged_at_anchored(res.x, s)[0])
    out['refit_nfev'] = int(res.nfev)
    out['refit_ok'] = bool(res.success)
    out['refit_dx'] = float(np.linalg.norm(res.x - xa))
    out['k_cat_before'] = float(np.power(10, x0[idx['k_cat_index']]))
    out['k_cat_after'] = float(np.power(10, res.x[idx['k_cat_index']]))
    out['K_T_before'] = float(np.median(np.power(10, x0[idx['K_T_slice']])))
    out['K_T_after'] = float(np.median(np.power(10, res.x[idx['K_T_slice']])))
    return out


def reach_report(a, prepare, solutions, synth_to_aa, anchored, targets):
    """Per synthetase: is the anchor target reachable at a feasible steady-state balance?

    The feasibility yardstick is EMPIRICAL rather than asserted. Every row in the shipped solutions
    file was accepted by the real fit's hard filter (max|v_charge - v_usage| <= 1e-3, applied after
    minimising), so the largest residual among those rows is an observed upper bound on what the fit
    will accept. Comparing against the residual at a single optimum would understate it.
    """
    none = np.array([], dtype=np.float64)
    target = float(targets[anchored[0]])
    names = sorted(synth_to_aa)

    # The accepted-residual ceiling, measured across every shipped row at this sweep level.
    ceiling, n_rows_total = 0.0, 0
    prepared = {}
    for name in names:
        p = prepare(name)
        if p is None:
            continue
        prepared[name] = p
        s_ = p[0]
        for r in (r for r in solutions if r['synthetase_id'] == name
                  and int(r['sweep_level']) == a.sweep_level):
            xr, _c, cm, _f = V.reassemble_argmin(r, s_, s_['trnas'], a.sweep_level,
                units.umol / units.L)
            ceiling = max(ceiling, float(
                trna_charging_objective(xr, *cm, 0.0, 0.0, 0.0, none, False)))
            n_rows_total += 1

    print(f'anchor target        {a.target} -> {anchored[0]}={target}')
    print(f'sweep level          {a.sweep_level}')
    print(f'synthetases          {len(prepared)} of {len(names)} have a shipped row at this level')
    print(f'accepted-residual    {ceiling:.3e}  (the LARGEST residual among all {n_rows_total} '
          f'shipped rows at this level;')
    print('  ceiling            every one passed the real fit\'s feasibility filter, so this is an '
          'observed bound)')
    print()
    print('`f_only` scales f for the anchored condition onto the target and touches nothing else.')
    print('`refit` holds it there and re-fits k_cat, K_A, every K_T and min_f freely.')
    print('A refit residual at or below the ceiling means REACHABLE: only the weight is in question.')
    print()

    hdr = (f'{"synthetase":<18} {"charged":>8} {"->":>2} {"scale":>6} | {"residual":>10} '
           f'{"f_only":>10} {"refit":>10} | {"x ceiling":>10} | {"k_cat":>18} {"med K_T":>18} '
           f'{"nfev":>6} {"ok":>3}  verdict')
    print(hdr)
    print('-' * len(hdr))

    reachable, unreachable, skipped = [], [], []
    for name in names:
        if name not in prepared:
            skipped.append(name)
            continue
        s_, x0_, common_, _n = prepared[name]
        r = reachability(s_, x0_, common_, anchored, targets)
        over = r['refit_residual'] / ceiling if ceiling else float('inf')
        ok = r['refit_residual'] <= ceiling
        (reachable if ok else unreachable).append((name, over))
        print(f'{name:<18} {r["start_charged"]:>8.4f} {"->":>2} {r["scale"]:>6.3f} | '
              f'{r["start_residual"]:>10.3e} {r["f_only_residual"]:>10.3e} '
              f'{r["refit_residual"]:>10.3e} | {over:>10.3g} | '
              f'{r["k_cat_before"]:>8.3g}->{r["k_cat_after"]:<9.3g} '
              f'{r["K_T_before"]:>8.3g}->{r["K_T_after"]:<9.3g} {r["refit_nfev"]:>6} '
              f'{"y" if r["refit_ok"] else "N":>3}  '
              f'{"REACHABLE" if ok else "unreachable"}')

    print()
    print(f'reachable at the target: {len(reachable)} of {len(prepared)}'
          + (f'  ({", ".join(n for n, _ in reachable)})' if reachable else ''))
    if unreachable:
        worst = max(o for _, o in unreachable)
        best = min(o for _, o in unreachable)
        print(f'unreachable: {len(unreachable)}, between {best:.3g}x and {worst:.3g}x the accepted '
              f'residual ceiling')
    if skipped:
        print(f'no shipped row at this level: {len(skipped)} ({", ".join(skipped)})')
    print()
    print('LIMITS. One starting point per synthetase (its best shipped row) and a local Powell '
          'search. A synthetase marked unreachable here is one this search could not bring to the '
          'target at a feasible residual; it is not a proof that no such solution exists anywhere.')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--kb', required=True, help='path to simData.cPickle')
    ap.add_argument('--flat', default=None, help='flat dir holding optimization/*.tsv')
    ap.add_argument('--mode', choices=('sweep', 'reach'), default='sweep',
        help="'sweep' re-minimises one synthetase across a w_a x w_b grid. 'reach' asks, for every "
             'synthetase, whether the target is reachable at a feasible residual at all -- which is '
             'the prior question, and the one Phase 5 rests on')
    ap.add_argument('--synthetase', default='LEUS-MONOMER[c]',
        help="LeuRS by default for 'sweep': 20 of its 27 free parameters are f and min_f, so it is "
             "the most degenerate and most sensitive instrument available. 'all' runs every "
             'synthetase (implied by --mode reach)')
    ap.add_argument('--target', default='avcilar_kucukgoze_2016')
    ap.add_argument('--weights', default='0,1e-6,1e-5,1e-4,1e-3',
        help='w_a values to sweep. 0 is the no-anchor control')
    ap.add_argument('--bounds-penalty-weights', default='1e-9,1e-11,0',
        help="w_b values. 1e-9 is shipped; the lower ones test Fit 1's question")
    ap.add_argument('--sweep-level', type=int, default=5,
        help='synthetase-abundance sweep level (relation.py runs 2..5); 5 is the basal level the '
             'campaign reports')
    a = ap.parse_args(argv)

    wcecoli = os.environ.get('WCECOLI_DIR', '/wcEcoli')
    flat = a.flat or os.path.join(wcecoli, 'reconstruction', 'ecoli', 'flat')

    with open(a.kb, 'rb') as f:
        sim_data = pickle.load(f)
    relation = sim_data.relation
    conc_unit = units.umol / units.L

    solutions = read_tsv(os.path.join(flat, 'optimization',
        'trna_charging_kinetics_solutions.tsv'))
    constants = read_tsv(os.path.join(flat, 'optimization',
        'trna_charging_kinetics_constants.tsv'))
    dynamic_range = read_tsv(os.path.join(flat, 'optimization',
        'trna_synthetase_dynamic_range.tsv'))
    constants_by_key = {r['synthetase_id__condition']: r for r in constants}
    mins_by_key = {r['synthetase_condition']: r['min'].asNumber(conc_unit) for r in dynamic_range}

    targets = resolve_charged_fraction_target(a.target)
    anchored = [c for c in V.CONDITIONS if targets.get(c) is not None]
    anchor_targets = np.array([targets[c] for c in anchored], dtype=np.float64)
    assert len(anchor_targets), f'target {a.target!r} anchors no condition; nothing to sweep'

    synth_to_aa = {v: k for k, v in relation.amino_acid_to_synthetase.items()}

    def prepare(synthetase):
        """(s, x0, common, n_rows) for one synthetase at the chosen sweep level, or None."""
        aa_ = synth_to_aa.get(synthetase)
        if aa_ is None:
            return None
        rows_ = [r for r in solutions if r['synthetase_id'] == synthetase
                 and int(r['sweep_level']) == a.sweep_level]
        if not rows_:
            return None
        s_ = V.assemble_synthetase(relation, synthetase, aa_, constants_by_key, mins_by_key,
            conc_unit, anchored)
        best = min(rows_, key=lambda r: float(r['objective']))
        x0_, _c, common_, _f = V.reassemble_argmin(best, s_, s_['trnas'], a.sweep_level, conc_unit)
        return s_, x0_, common_, len(rows_)

    if a.mode == 'reach':
        return reach_report(a, prepare, solutions, synth_to_aa, anchored, targets)

    amino_acid = synth_to_aa.get(a.synthetase)
    if amino_acid is None:
        raise SystemExit(f'{a.synthetase} is not in relation.amino_acid_to_synthetase. Known: '
                         f'{sorted(synth_to_aa)}')
    prepared = prepare(a.synthetase)
    if prepared is None:
        raise SystemExit(f'no shipped solution row for {a.synthetase} at sweep level '
                         f'{a.sweep_level}')
    s, x0, common, n_rows = prepared
    row = min((r for r in solutions if r['synthetase_id'] == a.synthetase
               and int(r['sweep_level']) == a.sweep_level), key=lambda r: float(r['objective']))
    rows = [r for r in solutions if r['synthetase_id'] == a.synthetase
            and int(r['sweep_level']) == a.sweep_level]
    bounds = build_bounds(s)

    print(f'synthetase     {a.synthetase}  ({amino_acid})')
    print(f'knowledge base {a.kb}')
    print(f'start          shipped argmin, sweep level {a.sweep_level}, objective '
          f'{float(row["objective"]):.4e} of {len(rows)} rows')
    print(f'anchor target  {a.target} -> ' + ', '.join(
        f'{c}={targets[c]}' for c in anchored))
    print(f'parameters     {s["indexes"]["n_parameters"]} '
          f'({len(s["trnas"])} tRNAs, {s["n_K_T"]} K_T groups)')
    print()
    print('A LOCAL re-optimisation from one point, with no feasibility filter. Not a fit; these '
          'constants are not adoptable.')
    print()

    hdr = (f'{"w_b":>7} {"w_a":>7} | {"objective":>11} {"residual":>10} {"w_r*sumK_T":>11} '
           f'{"w_b*barr":>10} {"w_a*anch":>10} | {"charged":>18} | {"k_cat":>9} {"K_T":>9} '
           f'{"k_cat/K_T":>10} {"k_cat*f/K_T":>12} | {"|dx|":>8} {"nfev":>6} {"ok":>3}')
    print(hdr)
    print('-' * len(hdr))

    stuck = 0
    for w_b in [float(x) for x in a.bounds_penalty_weights.split(',')]:
        for w_a in [float(x) for x in a.weights.split(',')]:
            at = anchor_targets if w_a else np.array([], dtype=np.float64)
            res = minimize(trna_charging_objective, x0, method='Powell', bounds=bounds,
                args=(*common, V.W_R, w_b, w_a, at, False), options=POWELL)
            total, residual, reg, barrier, anchor = decompose(
                res.x, common, V.W_R, w_b, w_a, at, False)
            agg = charged_aggregate(res.x, s)
            k_cat, K_T, ratio, product = gauge(res.x, s)
            uniq = sorted({round(float(v), 4) for v in agg})
            shown = ', '.join(f'{v:.3f}' for v in uniq[:2])
            # |dx| IS THE INSTRUMENT CHECK, not decoration. An optimiser that returns its starting
            # point at every weight produces a table of identical rows, which reads exactly like
            # "the anchor does nothing" and is in fact "nothing was minimised". Measured: that is
            # what happened the first time this was run.
            dx = float(np.linalg.norm(res.x - x0))
            if dx < 1e-12:
                stuck += 1
            print(f'{w_b:>7.0e} {w_a:>7.0e} | {total:>11.4e} {residual:>10.3e} {reg:>11.3e} '
                  f'{barrier:>10.3e} {anchor:>10.3e} | {shown:>18} | {k_cat:>9.3g} {K_T:>9.3g} '
                  f'{ratio:>10.4g} {product:>12.4g} | {dx:>8.2e} {res.nfev:>6} '
                  f'{"y" if res.success else "N":>3}')

    if stuck:
        print()
        print(f'*** {stuck} of the points above did not move at all (|dx| = 0). The optimiser '
              f'returned its starting vector, so those rows say nothing about the anchor. Do not '
              f'read this table as a response curve until every |dx| is non-zero. ***')

    print()
    print('READING IT. `charged` against the target says whether the anchor reaches its goal at that '
          'weight. `k_cat/K_T` and `k_cat*f/K_T` say whether it got there by changing the chemistry '
          'the simulation reads, or by sliding along the degeneracy it cannot see. A `residual` that '
          'climbs means the excursion is leaving the feasible region the real fit would reject.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
