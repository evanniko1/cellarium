"""PUB-A1: aggregate the REPLICATED A/B ledger into a powered, error-barred comparison.

`run_ab.py --reps N` writes N replicate rows per case per arm (ledger keys `cid#r{rep}`, each tagged `_case`/`_rep`).
This turns those into the paper-ready numbers, replacing the n=1 headline:
  * per (case, arm): mean ± 95% CI over the reps (the within-case sampling spread — the thing n=1 hid);
  * a CASE-CLUSTERED paired comparison of the two arms — paired at the CASE level because reps within a case are not
    independent of the case — with the effect size + 95% CI + a paired-t p-value.
Pure stats (scipy-free, reuses cellarium.stats); the aggregation is unit-testable with synthetic rows (no API key).
`--metric` names the numeric field to compare (the shared both-arm graded endpoint from the plan; PUB-A1).

Run: python evals/aggregate_ab.py evals/results/ab_rep.json --metric quality_score
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def _flatten(ledger: dict, metric: str) -> list:
    """Ledger {key: {_case, _rep, a:{...}, b:{...}}} (or a flat n=1 ledger) -> [{case, rep, arm, value}] for the
    numeric `metric` field present on an arm's row. Bools count as 0/1 (a pass-rate metric)."""
    rows = []
    for key, slot in (ledger or {}).items():
        if not isinstance(slot, dict):
            continue
        case = slot.get("_case") or str(key).split("#", 1)[0]
        rep = slot.get("_rep", 0)
        for arm in ("a", "b"):
            r = slot.get(arm)
            if isinstance(r, dict) and isinstance(r.get(metric), (int, float, bool)):
                rows.append({"case": case, "rep": rep, "arm": arm, "value": float(r[metric])})
    return rows


def _paired_t(diffs: list) -> dict:
    """Paired t on the per-case (arm_b - arm_a) differences: mean diff + 95% CI + two-sided p (df = n_cases - 1)."""
    from cellarium import stats
    n = len(diffs)
    if n < 2:
        return {"n_pairs": n, "note": "need >=2 paired cases for a paired test"}
    md = statistics.fmean(diffs)
    se = (statistics.stdev(diffs) / math.sqrt(n)) or 1e-12
    t = md / se
    df = n - 1
    p = stats.t_two_sided_p(t, df)
    hw = stats.t_critical_95(df) * se
    return {"n_pairs": n, "mean_diff_b_minus_a": round(md, 4), "ci95": [round(md - hw, 4), round(md + hw, 4)],
            "t": round(t, 3), "df": df, "p_value": (round(p, 4) if p is not None else None),
            "significant": bool(p is not None and p < 0.05)}


def aggregate(ledger: dict, metric: str = "quality_score") -> dict:
    """Per (case, arm) mean±CI over reps + the case-clustered paired arm comparison. The honest replacement for n=1."""
    from cellarium import stats
    rows = _flatten(ledger, metric)
    by: dict = defaultdict(list)
    for r in rows:
        by[(r["case"], r["arm"])].append(r["value"])
    if not by:
        return {"metric": metric, "error": "no numeric rows for this metric — is --metric right + were reps run?"}

    per_cell = {f"{c}/{a}": {"mean": round(statistics.fmean(v), 4), "n_reps": len(v),
                             "ci95_halfwidth": (round(stats.t95_halfwidth(v), 4) if len(v) > 1 else None)}
                for (c, a), v in sorted(by.items())}
    cases = sorted({c for (c, _a) in by})
    paired = []
    for c in cases:
        av, bv = by.get((c, "a")), by.get((c, "b"))
        if av and bv:
            ma, mb = statistics.fmean(av), statistics.fmean(bv)
            paired.append({"case": c, "arm_a_mean": round(ma, 4), "arm_b_mean": round(mb, 4),
                           "diff_b_minus_a": round(mb - ma, 4)})
    arm_means = {arm: round(statistics.fmean([statistics.fmean(by[(c, arm)]) for c in cases if (c, arm) in by]), 4)
                 for arm in ("a", "b") if any((c, arm) in by for c in cases)}
    return {
        "metric": metric, "n_cases": len(cases), "n_paired_cases": len(paired),
        "reps_per_cell": sorted({len(v) for v in by.values()}),
        "arm_means_case_clustered": arm_means,   # mean of per-case arm means (case-clustered, not rep-weighted)
        "paired_test": _paired_t([p["diff_b_minus_a"] for p in paired]),
        "per_case_paired": paired, "per_cell": per_cell,
        "note": ("Case-clustered: each case contributes its per-rep MEAN (reps within a case aren't independent), then "
                 "the two arms are compared PAIRED across cases. Read the effect size + CI, not just p. This is the "
                 "powered replacement for the n=1 headline — report reps_per_cell + n_paired_cases as the design."),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ledger", help="path to the run_ab results ledger JSON (e.g. evals/results/ab_rep.json)")
    p.add_argument("--metric", default="quality_score", help="the numeric arm-row field to compare")
    p.add_argument("--out", default=None)
    a = p.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    ledger = json.loads(Path(a.ledger).read_text(encoding="utf-8"))
    if isinstance(ledger, dict) and "results" in ledger:   # some writers wrap in {meta, results}
        ledger = {r.get("id", i): r for i, r in enumerate(ledger["results"])}
    agg = aggregate(ledger, a.metric)
    out = json.dumps(agg, indent=2)
    if a.out:
        Path(a.out).write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
