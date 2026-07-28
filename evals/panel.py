"""PUB-A2: the cross-family judge panel — validating the ruler before trusting what it measured.

Every number in the A/B comparison is produced by asking a model to grade. That model is currently ONE Claude
Opus, ONE sample, at temperature 1 (reasoning models pin it — determinism is not available), from the SAME
family as some of what it grades, and it sees the answer key. Three defects, none hypothetical:

  * **self-preference** — a same-family judge can reward family affinity rather than science;
  * **unmeasured noise** — a single sample at temperature 1 has unknown run-to-run variance, so if the grader
    wobbles more than the arms differ, the sweep measures the grader. This corpus has already seen it: the one
    significant ablation cell rides a temp-0 GPT-4o grader and **flips** under `generic_judge`;
  * **answer-key leakage** — tolerable on textbook cases, corrosive on the out-of-sample ones (argS), which are
    the only cases the paper's claim should be scoped to.

The panel addresses the first two. It re-grades a **fixed** set of artifacts — `shared_metric.grade()` stores
`graded_text`, so nothing is re-run and no arm is re-rolled — with several judges from different families,
several samples each, and reports three things the single-judge number cannot:

  1. **α (Krippendorff)** between judges. Thakur et al. (arXiv:2406.12624): no LLM-judge endpoint is publishable
     without a reported agreement statistic. Low α means the rubric is underspecified and NO judge's number
     means anything — including the one already collected.
  2. **within-judge SD**, the grader's own noise, measured by repeated sampling of the same artifact.
  3. **decision stability** — the actual deliverable. Re-run the headline paired test once per judge. A result
     that holds under one family and not another is a property of the judge, not of the system.

The comparison that decides whether the sweep is interpretable at all is (2) against the arm difference: if
grader noise is the same size as the effect, more replicates buy precision on an axis that cannot be read.

Everything except `regrade()` is pure and unit-tested with no API key — the reliability machinery must be
checkable without spending money, or nobody re-checks it.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- agreement (pure)
def _delta2(level: str):
    """The difference function δ². `quality_score` is a fraction on a fixed rubric, so INTERVAL is the honest
    default: 0.4 vs 0.6 is genuinely closer than 0.0 vs 0.6, which `nominal` would score as equally wrong.
    `ratio` is offered but is wrong here — it treats a difference near zero as enormous, and a zeroed artifact
    (a crashed arm) is a legitimate value."""
    if level == "nominal":
        return lambda a, b: 0.0 if a == b else 1.0
    if level == "ratio":
        return lambda a, b: 0.0 if (a + b) == 0 else ((a - b) / (a + b)) ** 2
    if level == "interval":
        return lambda a, b: (a - b) ** 2
    raise ValueError(f"unknown level {level!r}")


def krippendorff_alpha(ratings: dict, level: str = "interval") -> dict:
    """Krippendorff's α over `{unit_id: {rater_id: value}}`. Returns α plus the pieces behind it.

    α = 1 − D_o/D_e, where D_o is the observed disagreement and D_e the disagreement expected by chance from the
    same marginal distribution. α = 1 is perfect agreement, 0 is chance, and **negative is systematic
    disagreement** — raters disagreeing more than random assignment would produce, which is a real and
    diagnostic outcome rather than an error.

    Chosen over Cohen's/Fleiss' κ because it handles any number of raters, MISSING ratings (a judge that
    refuses or errors on one artifact does not invalidate the row), and an interval-scaled score. The
    coincidence-matrix form is used, which is what makes missing data fall out naturally: a unit rated by m
    raters contributes each of its m(m−1) ordered pairs with weight 1/(m−1), so units carry equal weight
    regardless of how many raters reached them.

    Units rated by fewer than two raters carry no pairwise information and are dropped — reported as
    `n_units_dropped` rather than silently.
    """
    d2 = _delta2(level)
    usable = {u: {r: float(v) for r, v in rs.items() if v is not None}
              for u, rs in (ratings or {}).items()}
    dropped = [u for u, rs in usable.items() if len(rs) < 2]
    usable = {u: rs for u, rs in usable.items() if len(rs) >= 2}
    if not usable:
        return {"alpha": None, "n_units": 0, "n_units_dropped": len(dropped), "level": level,
                "note": "fewer than two raters on every unit — no pairwise information exists"}

    # The coincidence matrix, as a flat weighted bag of ORDERED value pairs. A unit rated by m raters
    # contributes each of its m(m-1) ordered pairs with weight 1/(m-1), so every unit carries the same total
    # weight m regardless of how many raters reached it — which is precisely what makes missing data harmless.
    pairs: list[tuple[float, float, float]] = []          # (value_i, value_j, weight)
    for rs in usable.values():
        vals = list(rs.values())
        m = len(vals)
        w = 1.0 / (m - 1)
        for i, a in enumerate(vals):
            for j, b in enumerate(vals):
                if i != j:
                    pairs.append((a, b, w))

    # n_c, the coincidence marginals, derived FROM the pairs rather than counted separately — computing them
    # independently is exactly how a weighting error slips in and makes D_o and D_e quietly inconsistent.
    marginal: dict[float, float] = defaultdict(float)
    for a, _b, w in pairs:
        marginal[a] += w
    n = sum(marginal.values())
    if n <= 1:
        return {"alpha": None, "n_units": len(usable), "n_units_dropped": len(dropped), "level": level,
                "note": "not enough coincidences to estimate chance disagreement"}

    d_o = sum(w * d2(a, b) for a, b, w in pairs) / n
    vals = list(marginal)
    d_e = sum(marginal[a] * marginal[b] * d2(a, b) for a in vals for b in vals) / (n * (n - 1))
    if d_e == 0:
        # Every rating identical: no chance disagreement is possible, so α is undefined rather than 1.0.
        return {"alpha": None, "d_o": d_o, "d_e": d_e, "n_units": len(usable),
                "n_units_dropped": len(dropped), "level": level,
                "note": ("all ratings identical — D_e = 0 and α is undefined (not 1.0). Perfect agreement on a "
                         "constant is also perfect agreement with a broken judge that always says the same "
                         "thing, and the statistic cannot tell those apart.")}
    alpha = 1.0 - d_o / d_e
    return {"alpha": round(alpha, 4), "d_o": round(d_o, 6), "d_e": round(d_e, 6),
            "n_units": len(usable), "n_units_dropped": len(dropped), "n_coincidences": round(n, 2),
            "level": level,
            "interpretation": _read_alpha(alpha)}


def _read_alpha(a: float) -> str:
    """Krippendorff's own thresholds, stated so a number does not get quoted without its meaning.

    The 0.800 / 0.667 convention is from Krippendorff's content-analysis work, where a conclusion resting on
    α < 0.667 is conventionally not reported at all. It is a convention, not a law — but adopting a stricter
    private threshold after seeing the number is exactly the move it exists to prevent."""
    if a >= 0.800:
        return "acceptable for drawing conclusions (Krippendorff's >=0.800)"
    if a >= 0.667:
        return "tentative conclusions only (0.667-0.800) — report alongside every score"
    if a > 0:
        return "BELOW the conventional floor (<0.667): the rubric is underspecified; no single judge's number is interpretable"
    return "AT OR BELOW CHANCE: judges disagree as much as (or more than) random assignment — the endpoint is not measuring a shared construct"


# ---------------------------------------------------------------- panel arithmetic (pure)
def artifacts(ledger: dict) -> list[dict]:
    """Every gradeable artifact in a run_ab ledger, with the exact text that was graded.

    Returns one row per (case, rep, arm). Rows whose `graded_text` is absent are returned with `text=None` and
    flagged — an older ledger written before `shared_metric.grade` retained the text CANNOT be re-graded, and
    that has to surface as a refusal rather than as a quietly smaller panel.
    """
    out = []
    for key, slot in (ledger or {}).items():
        if not isinstance(slot, dict):
            continue
        case = slot.get("_case") or str(key).split("#", 1)[0]
        rep = slot.get("_rep", 0)
        for arm in ("a", "b"):
            r = slot.get(arm)
            if not isinstance(r, dict):
                continue
            shared = r.get("shared") if isinstance(r.get("shared"), dict) else {}
            out.append({"unit": f"{case}#r{rep}#{arm}", "case": case, "rep": rep, "arm": arm,
                        "text": shared.get("graded_text"),
                        "original_score": shared.get("quality_score", r.get("quality_score")),
                        "original_judge": shared.get("judge_model")})
    return out


def summarise(panel: dict, level: str = "interval") -> dict:
    """Turn `{unit: {judge: [sample scores]}}` into the reliability report.

    Three separate numbers, because they answer three separate questions and collapsing them is how a panel
    becomes theatre: BETWEEN-judge α (do different families measure the same thing?), WITHIN-judge SD (how noisy
    is one judge on a fixed artifact?), and the two compared against the arm difference (is the effect bigger
    than the ruler's wobble?).
    """
    per_judge_mean: dict = defaultdict(dict)          # unit -> judge -> mean over that judge's samples
    within: dict = defaultdict(list)                  # judge -> [sd over samples, per unit]
    for unit, judges in (panel or {}).items():
        for judge, samples in (judges or {}).items():
            vals = [float(s) for s in (samples or []) if isinstance(s, (int, float))]
            if not vals:
                continue
            per_judge_mean[unit][judge] = statistics.fmean(vals)
            if len(vals) > 1:
                within[judge].append(statistics.stdev(vals))

    judges = sorted({j for u in per_judge_mean.values() for j in u})
    alpha = krippendorff_alpha(dict(per_judge_mean), level=level)

    judge_means = {j: round(statistics.fmean([u[j] for u in per_judge_mean.values() if j in u]), 4)
                   for j in judges if any(j in u for u in per_judge_mean.values())}
    # Leniency spread: judges can agree perfectly on RANKING while differing on absolute level. α is
    # sensitive to both; this separates them, because only the ranking matters for an A-vs-B comparison.
    leniency = (round(max(judge_means.values()) - min(judge_means.values()), 4)
                if len(judge_means) > 1 else None)
    within_sd = {j: round(statistics.fmean(v), 4) for j, v in within.items() if v}

    # Pairwise mean absolute difference — interpretable in the metric's own units, unlike α.
    pairwise = {}
    for i, ja in enumerate(judges):
        for jb in judges[i + 1:]:
            d = [abs(u[ja] - u[jb]) for u in per_judge_mean.values() if ja in u and jb in u]
            if d:
                pairwise[f"{ja} vs {jb}"] = {"mean_abs_diff": round(statistics.fmean(d), 4), "n": len(d)}

    return {"n_units": len(per_judge_mean), "judges": judges,
            "alpha_between_judges": alpha,
            "judge_means": judge_means, "leniency_spread": leniency,
            "within_judge_sd": within_sd, "pairwise": pairwise,
            "note": ("alpha asks whether the judges measure the same construct; within_judge_sd is one judge's "
                     "own noise on a FIXED artifact; leniency_spread is how differently they are calibrated. "
                     "A panel can have high leniency_spread and still be usable for an A-vs-B comparison — "
                     "constant offsets cancel in a paired test — but high within_judge_sd cannot be corrected "
                     "by anything except more samples.")}


def decision_stability(panel: dict, units: list[dict], metric_name: str = "quality_score") -> dict:
    """THE deliverable: does the headline conclusion survive a change of judge?

    Re-runs the case-clustered paired A/B test once per judge, on the same artifacts, and reports whether the
    sign and the significance agree. A result that holds under one family and not another is a property of the
    grader — which is not a hypothetical failure mode here: the one significant ablation cell in this project
    already flips under a different judge.
    """
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "evals"))
    import aggregate_ab

    by_unit = {u["unit"]: u for u in units}
    judges = sorted({j for jj in (panel or {}).values() for j in jj})
    per_judge = {}
    for j in judges:
        ledger: dict = {}
        for unit, jj in (panel or {}).items():
            vals = [float(s) for s in (jj.get(j) or []) if isinstance(s, (int, float))]
            meta = by_unit.get(unit)
            if not vals or not meta:
                continue
            key = f"{meta['case']}#r{meta['rep']}"
            slot = ledger.setdefault(key, {"_case": meta["case"], "_rep": meta["rep"]})
            slot[meta["arm"]] = {metric_name: statistics.fmean(vals)}
        per_judge[j] = aggregate_ab.aggregate(ledger, metric_name)

    signs, sigs = set(), set()
    for r in per_judge.values():
        t = r.get("paired_test") or {}
        d = t.get("mean_diff_b_minus_a")
        if d is not None:
            signs.add(0 if d == 0 else (1 if d > 0 else -1))
        if "significant" in t:
            sigs.add(bool(t["significant"]))
    stable = len(signs) <= 1 and len(sigs) <= 1
    return {"per_judge": per_judge, "sign_agrees": len(signs) <= 1, "significance_agrees": len(sigs) <= 1,
            "stable": stable,
            "verdict": ("the conclusion is invariant to the judge across this panel" if stable else
                        "⚠️ THE CONCLUSION DEPENDS ON THE JUDGE — it is a property of the grader, not of the "
                        "system under test, and must not be reported as the latter")}


def noise_vs_effect(summary: dict, stability: dict) -> dict:
    """Is the effect bigger than the ruler's wobble? The question that decides whether the sweep is readable.

    Buying tighter error bars on an axis whose own noise exceeds the effect is precision that cannot be
    interpreted, which is the whole argument for validating the judge BEFORE spending on replicates."""
    sd = (summary or {}).get("within_judge_sd") or {}
    worst = max(sd.values()) if sd else None
    diffs = [abs((r.get("paired_test") or {}).get("mean_diff_b_minus_a") or 0.0)
             for r in ((stability or {}).get("per_judge") or {}).values()]
    effect = min(diffs) if diffs else None
    if worst is None or effect is None:
        return {"comparable": False, "note": "need >=2 samples per judge AND a paired test to compare"}
    ratio = (effect / worst) if worst else None
    return {"smallest_effect": round(effect, 4), "largest_within_judge_sd": round(worst, 4),
            "effect_to_noise": (round(ratio, 2) if ratio is not None else None),
            "readable": bool(ratio is not None and ratio >= 1.0),
            "note": ("effect_to_noise < 1 means one judge re-grading the SAME artifact moves the score more "
                     "than the arms differ. More replicates cannot fix that — only a better rubric or a "
                     "multi-sample judge mean can.")}


# ---------------------------------------------------------------- the billable part
def regrade(ledger: dict, judges: list[str], samples: int, client, cases_by_id: dict,
            on_progress=None) -> dict:
    """Grade every stored artifact with every judge, `samples` times. The ONLY function here that costs money.

    Nothing is re-run and no arm is re-rolled: it reads `graded_text` off the ledger, so every judge scores
    byte-identical items — which is what an inter-rater statistic requires and what re-running the sweep could
    never provide."""
    sys.path.insert(0, str(ROOT / "evals"))
    import shared_metric

    out: dict = {}
    missing = []
    for a in artifacts(ledger):
        if not (a["text"] or "").strip():
            missing.append(a["unit"])
            continue
        case = cases_by_id.get(a["case"])
        if not case:
            missing.append(a["unit"])
            continue
        for j in judges:
            for s in range(samples):
                g = shared_metric.grade(case, a["text"], client, j)
                out.setdefault(a["unit"], {}).setdefault(j, []).append(g.get("quality_score"))
                if on_progress:
                    on_progress(a["unit"], j, s, g.get("quality_score"))
    if missing:
        out["_missing"] = missing        # surfaced, never silently a smaller panel
    return out


def main():
    p = argparse.ArgumentParser(description="PUB-A2: cross-family judge panel over a stored A/B ledger.")
    p.add_argument("ledger", help="an evals/results/*.json written by run_ab.py")
    p.add_argument("--judges", default="claude-opus-4-8",
                   help="comma-separated judge models. A single-family panel measures nothing about "
                        "self-preference — use >=2 families for the PUB-A2 claim.")
    p.add_argument("--samples", type=int, default=2, help="samples per judge per artifact (>=2 for noise)")
    p.add_argument("--panel-out", default=None, help="write/reuse raw panel scores here (resumable)")
    p.add_argument("--report-out", default=None)
    p.add_argument("--dry-run", action="store_true", help="report what WOULD be graded, and spend nothing")
    a = p.parse_args()

    ledger = json.loads(Path(a.ledger).read_text(encoding="utf-8"))
    units = artifacts(ledger)
    gradeable = [u for u in units if (u["text"] or "").strip()]
    stale = [u["unit"] for u in units if not (u["text"] or "").strip()]
    judges = [j.strip() for j in a.judges.split(",") if j.strip()]

    print(f"{len(units)} artifact(s); {len(gradeable)} re-gradable; {len(stale)} without stored text")
    if stale:
        print("  ⚠️ these predate `graded_text` and CANNOT be re-graded without re-running their arm:")
        for u in stale[:10]:
            print(f"     {u}")
    print(f"panel: {len(judges)} judge(s) x {a.samples} sample(s) = {len(gradeable) * len(judges) * a.samples} calls")
    if len({j.split('-')[0] for j in judges}) < 2:
        print("  ⚠️ every judge is from one family — this measures NOISE but not SELF-PREFERENCE (PUB-A2 needs both)")
    if a.dry_run:
        return

    panel_path = Path(a.panel_out) if a.panel_out else None
    if panel_path and panel_path.exists():
        panel = json.loads(panel_path.read_text(encoding="utf-8"))
        print(f"resuming from {panel_path} ({len(panel)} unit(s) already scored)")
    else:
        # ONE resolver shared with run_ab, so the app's Settings tab (OS keychain) reaches the panel too — a key
        # saved the securest way must not be the one the billable runs cannot see.
        sys.path.insert(0, str(ROOT / "evals"))
        from run_ab import _resolve_api_key
        _resolve_api_key()
        import anthropic
        sys.path.insert(0, str(ROOT / "evals"))
        import cases as cases_mod
        client = anthropic.Anthropic(max_retries=4)
        by_id = {c["id"]: c for c in cases_mod.by_id(None)}
        panel = regrade(ledger, judges, a.samples, client, by_id,
                        on_progress=lambda u, j, s, q: print(f"  {u}  {j}  #{s}  q={q}"))
        if panel_path:
            panel_path.write_text(json.dumps(panel, indent=2), encoding="utf-8")

    scores = {k: v for k, v in panel.items() if not k.startswith("_")}
    summary = summarise(scores)
    stability = decision_stability(scores, units)
    report = {"summary": summary, "stability": stability,
              "noise_vs_effect": noise_vs_effect(summary, stability),
              "not_regradable": panel.get("_missing") or stale}
    out = json.dumps(report, indent=2)
    if a.report_out:
        Path(a.report_out).write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
