"""Epistemic-discipline tools — coverage (P2.4) and disconfirmation (P2.5).

Two structural defences against the biases survey_corpus already fights:
  - **Coverage** tracks which designs the agent has actually *deep-read* this session (vs the whole corpus),
    so a conclusion can be checked against the grid it rests on rather than the few runs that caught attention.
  - **Disconfirmation** turns "seek falsifying evidence" from a prompt wish into a callable step: it exposes
    the per-seed spread behind a claimed effect (is it bigger than replicate noise?), the corpus z-score, and a
    checklist — the data needed to *challenge* a claim before committing to it.
"""

from __future__ import annotations

import json
import math
import statistics

from . import stats

# session state — the designs deep-read via the reading tools (reset at the start of an agent run)
_examined_results: set[str] = set()
_examined_designs: set[str] = set()


def reset() -> None:
    _examined_results.clear()
    _examined_designs.clear()


def note_result(result_id: str) -> None:
    if result_id:
        _examined_results.add(result_id)


def note_design(label: str) -> None:
    if label:
        _examined_designs.add(label)


def coverage() -> dict:
    """Designs deep-read this session vs all designs in the corpus — the grid a conclusion should cover."""
    from . import store

    id2label = {r["id"]: f'{r.get("perturbation")}/{r.get("condition")}' for r in store.list_results()}
    all_designs = set(id2label.values())
    examined = (set(_examined_designs) | {id2label[r] for r in _examined_results if r in id2label}) & all_designs
    return {
        "n_examined": len(examined), "n_total": len(all_designs),
        "fraction": round(len(examined) / len(all_designs), 2) if all_designs else 0.0,
        "examined": sorted(examined), "unexamined": sorted(all_designs - examined),
        "note": ("Designs deep-read this session (read_series/species, differential, top_movers) vs all designs. "
                 "Do NOT generalise a conclusion beyond the examined set — examine the rest (survey_corpus lists "
                 "them) or explicitly scope the claim to what you read."),
    }


def disconfirm(target: str, reference: str, channel: str) -> dict:
    """Challenge a claimed target-vs-reference effect on `channel`: per-seed spread, noise check, corpus z."""
    from . import survey

    rows = survey._deduped_rows(survey.CHANNELS)
    if not rows or "__error__" in rows[0]:
        return {"error": "corpus unreadable or empty"}
    for r in rows:
        try:
            r["_pw"] = json.loads(r.get("pathways") or "{}")
        except Exception:
            r["_pw"] = {}

    def val(r):
        return r["_pw"].get(channel[3:]) if channel.startswith("pw:") else r.get(channel)

    def series(label):
        return [val(r) for r in rows
                if f'{r.get("perturbation")}/{r.get("condition")}' == label and val(r) is not None]

    import math

    tv, rv = series(target), series(reference)
    if not tv:
        return {"error": f"no '{channel}' values for design '{target}'"}
    if not rv:
        return {"error": f"no '{channel}' values for reference '{reference}'"}
    tm, rm = statistics.fmean(tv), statistics.fmean(rv)

    def ci95(x):
        return stats.t95_halfwidth(x)  # t-distribution 95% CI (audit M2)

    # Welch's t (unequal variance) — the proper 2-sample test the audit demanded, replacing the noise heuristic
    welch_t, significant = None, None
    if len(tv) > 1 and len(rv) > 1:
        va, vb = statistics.variance(tv), statistics.variance(rv)
        se = math.sqrt(va / len(tv) + vb / len(rv)) or 1e-12
        welch_t = round((tm - rm) / se, 2)
        significant = abs(welch_t) >= 2.0
    allv = [val(r) for r in rows if val(r) is not None]
    mu, sd = statistics.fmean(allv), (statistics.pstdev(allv) or 1e-12)
    tci, rci = ci95(tv), ci95(rv)
    return {
        "channel": channel,
        "target": {"design": target, "mean": round(tm, 6), "ci95": (round(tci, 6) if tci else None),
                   "n_seeds": len(tv), "values": [round(x, 6) for x in tv]},
        "reference": {"design": reference, "mean": round(rm, 6), "ci95": (round(rci, 6) if rci else None),
                      "n_seeds": len(rv), "values": [round(x, 6) for x in rv]},
        "effect_pct": (round(100 * (tm - rm) / rm, 1) if rm else None),
        "effect_z_vs_corpus": round((tm - mu) / sd, 2),
        "welch_t": welch_t, "significant": significant,   # significant=False => within noise; needs n>=2 both sides
        "checklist": [
            "Is the effect significant (welch_t magnitude >= 2, CIs non-overlapping)? n<2 => underpowered.",
            "Does another design contradict the implied relationship?",
            "Is the mechanism channel consistent (e.g. ppGpp up AND ribosome_conc down)?",
            "Are all contributing runs qc=ok?",
        ],
        "note": "Disconfirmation aid — challenge the claimed effect with statistics before concluding.",
    }


def fit_relation(designs: list, x_channel: str, y_channel: str) -> dict:
    """OLS fit of y_channel on x_channel ACROSS designs — each design contributes its cross-seed mean as one point.
    This is how a growth LAW is stated (ribosome ∝ growth; RNA/protein ∝ growth): slope + R² across designs, not a
    per-design effect. Grounded (means from the manifest, no fabricated spread). CRITICAL: every point is tagged
    in_sample / out_of_sample, and the fit is split so a caller can see whether the law holds on GENUINE predictions
    (out_of_sample) vs merely reproduces fitted conditions (in_sample) — the distinction the provenance guard exists
    for. designs: ['perturbation/condition', ...]. Needs >=3 designs carrying BOTH channels."""
    import math

    from . import provenance, survey

    rows = survey._deduped_rows(survey.CHANNELS)
    if not rows or "__error__" in rows[0]:
        return {"error": "corpus unreadable or empty"}
    for r in rows:
        try:
            r["_pw"] = json.loads(r.get("pathways") or "{}")
        except Exception:
            r["_pw"] = {}

    def val(r, ch):
        return r["_pw"].get(ch[3:]) if ch.startswith("pw:") else r.get(ch)

    def mean_for(label, ch):
        vs = [val(r, ch) for r in rows
              if f'{r.get("perturbation")}/{r.get("condition")}' == label and val(r, ch) is not None]
        return statistics.fmean(vs) if vs else None

    pts = []
    for d in designs:
        pert, _, cond = str(d).partition("/")
        x, y = mean_for(d, x_channel), mean_for(d, y_channel)
        if x is not None and y is not None:
            pts.append({"design": d, "x": round(x, 6), "y": round(y, 6),
                        "provenance": provenance.tag(pert, cond or None)})
    if len(pts) < 3:
        return {"error": f"need >=3 designs carrying both '{x_channel}' and '{y_channel}'; got {len(pts)}",
                "points": pts}

    def _ols(points):
        n = len(points)
        if n < 2:
            return None
        xs = [p["x"] for p in points]
        ys = [p["y"] for p in points]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        syy = sum((y - my) ** 2 for y in ys)
        if sxx == 0 or syy == 0:
            return {"n": n, "slope": None, "intercept": None, "r_squared": None, "pearson_r": None}
        slope = sxy / sxx
        intercept = my - slope * mx
        r = sxy / math.sqrt(sxx * syy)
        return {"n": n, "slope": round(slope, 4), "intercept": round(intercept, 4),
                "r_squared": round(r * r, 3), "pearson_r": round(r, 3)}

    oos = [p for p in pts if p["provenance"] == "out_of_sample"]
    return {"x_channel": x_channel, "y_channel": y_channel, "n_designs": len(pts),
            "fit_all": _ols(pts),
            "fit_out_of_sample_only": _ols(oos),   # the honest test: does the law hold on genuine predictions?
            "n_out_of_sample": len(oos), "n_in_sample": len(pts) - len(oos),
            "points": pts,
            "note": ("A law fitted ACROSS designs. `fit_out_of_sample_only` is the predictive test; `fit_all` mixes "
                     "fitted (in_sample) and predicted points. A high R² driven mainly by in_sample points is "
                     "CONSISTENCY, not prediction — check n_out_of_sample and the out-of-sample fit before crediting.")}
