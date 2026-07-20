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


    tv, rv = series(target), series(reference)
    if not tv:
        return {"error": f"no '{channel}' values for design '{target}'"}
    if not rv:
        return {"error": f"no '{channel}' values for reference '{reference}'"}
    tm, rm = statistics.fmean(tv), statistics.fmean(rv)

    def ci95(x):
        return stats.t95_halfwidth(x)  # t-distribution 95% CI (audit M2)

    # Welch's t (unequal variance) with a df-AWARE significance threshold (DD-MTH-1): the flat |welch_t|>=2 cutoff was
    # wrong at small df (t-crit at df=2 is ~4.3) and contradicted the t-distribution CIs computed just below.
    # stats.welch_t returns the Welch–Satterthwaite df + a two-sided p; significance is p<0.05, consistent with the CIs.
    welch_t, welch_df, welch_p, significant = None, None, None, None
    wt = stats.welch_t(tv, rv)
    if wt:
        welch_t, welch_df, welch_p = wt["t"], wt["df"], wt["p"]
        significant = (welch_p is not None and welch_p < 0.05)
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
        # DS-2: this positions the target within the corpus's BETWEEN-DESIGN spread (which mixes real differences
        # with replicate noise) — descriptive only, NOT a significance test. Use welch_t / CIs for significance.
        "z_vs_corpus_spread": round((tm - mu) / sd, 2),
        # significant=False => within noise; needs n>=2 both sides. welch_p is the two-sided p at the Welch df.
        "welch_t": welch_t, "welch_df": welch_df, "welch_p": welch_p, "significant": significant,
        "checklist": [
            "Is the effect significant (welch_p < 0.05 at the Welch–Satterthwaite df, CIs non-overlapping)? "
            "n<2 => underpowered.",
            "z_vs_corpus_spread is descriptive positioning, NOT significance — never read it as a p-value.",
            "Does another design contradict the implied relationship?",
            "Is the mechanism channel consistent (e.g. ppGpp up AND ribosome_conc down)?",
            "Are all contributing runs qc=ok?",
        ],
        "note": "Disconfirmation aid — challenge the claimed effect with statistics (welch_t/CIs) before concluding.",
    }


def fit_relation(designs: list, x_channel: str, y_channel: str) -> dict:
    """OLS fit of y_channel on x_channel ACROSS designs — each design contributes its cross-seed mean as one point.
    This is how a growth LAW is stated (ribosome ∝ growth; RNA/protein ∝ growth): slope + R² across designs, not a
    per-design effect. Grounded (means from the manifest, no fabricated spread). CRITICAL: every point is tagged
    in_sample / out_of_sample, and the fit is split so a caller can see whether the law holds on GENUINE predictions
    (out_of_sample) vs merely reproduces fitted conditions (in_sample) — the distinction the provenance guard exists
    for. designs: ['perturbation/condition', ...]. Needs >=3 designs carrying BOTH channels."""

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
        r2 = r * r
        out = {"n": n, "slope": round(slope, 4), "intercept": round(intercept, 4),
               "r_squared": round(r2, 3), "pearson_r": round(r, 3)}
        # DS-1: INFERENCE on the slope, not just R². Residual-based SE -> t, two-sided p, and a 95% CI, so a
        # "law" is only asserted when the slope CI excludes 0 (the Council's decision rule, now executable).
        df = n - 2
        if df >= 1 and sxx > 0:
            sse = max(0.0, syy - slope * sxy)              # residual SS = Syy - slope*Sxy
            se_slope = math.sqrt((sse / df) / sxx)
            adj_r2 = round(1 - (1 - r2) * (n - 1) / df, 3)
            if se_slope > 0:
                t = slope / se_slope
                hw = stats.t_critical_95(df) * se_slope
                lo, hi = slope - hw, slope + hw
                p = stats.t_two_sided_p(t, df)
                out.update({"slope_se": round(se_slope, 4), "slope_t": round(t, 2),
                            "slope_p_value": (round(p, 4) if p is not None else None),
                            "slope_ci95": [round(lo, 4), round(hi, 4)],
                            "slope_ci_excludes_0": bool(lo > 0 or hi < 0),
                            "adj_r_squared": adj_r2})
            else:   # perfect fit (zero residual): slope is exact, CI collapses to the point
                out.update({"slope_se": 0.0, "slope_t": None, "slope_p_value": 0.0,
                            "slope_ci95": [round(slope, 4), round(slope, 4)],
                            "slope_ci_excludes_0": bool(slope != 0), "adj_r_squared": adj_r2})
        else:   # n==2: slope is determined but has 0 residual df -> no inference possible
            out.update({"slope_se": None, "slope_t": None, "slope_p_value": None,
                        "slope_ci95": None, "slope_ci_excludes_0": None, "adj_r_squared": None})
        return out

    oos = [p for p in pts if p["provenance"] == "out_of_sample"]
    return {"x_channel": x_channel, "y_channel": y_channel, "n_designs": len(pts),
            "fit_all": _ols(pts),
            "fit_out_of_sample_only": _ols(oos),   # the honest test: does the law hold on genuine predictions?
            "n_out_of_sample": len(oos), "n_in_sample": len(pts) - len(oos),
            "points": pts,
            "note": ("A law fitted ACROSS designs. `fit_out_of_sample_only` is the predictive test; `fit_all` mixes "
                     "fitted (in_sample) and predicted points. A high R² driven mainly by in_sample points is "
                     "CONSISTENCY, not prediction — check n_out_of_sample and the out-of-sample fit before crediting. "
                     "Assert a relationship only when `slope_ci_excludes_0` is true (slope 95% CI clears 0) and "
                     "`slope_p_value` is small — R² alone at small n over-claims. `adj_r_squared` penalises the fit "
                     "for n; n=2 gives no residual df, so inference fields are null there.")}


def _best_split(vals: list[float]) -> tuple[float, float, float, int, int] | None:
    """Cheapest 1-D two-cluster split (minimise within-cluster SS over the sorted cut points) — an
    interpretable companion to the bimodality coefficient: WHERE the two putative modes sit and how big each is."""
    s = sorted(vals)
    n = len(s)
    if n < 2:
        return None
    best = None
    for k in range(1, n):
        lo, hi = s[:k], s[k:]
        wss = (sum((x - statistics.fmean(lo)) ** 2 for x in lo)
               + sum((x - statistics.fmean(hi)) ** 2 for x in hi))
        if best is None or wss < best[0]:
            best = (wss, statistics.fmean(lo), statistics.fmean(hi), len(lo), len(hi))
    return best


def bimodality(channel: str, designs: list | None = None) -> dict:
    """Is the distribution of `channel` bimodal? Pools the per-seed values (across `designs`, or ALL designs if
    None) and reports Sarle's bimodality coefficient (BC > 5/9 ~ two modes) plus the best two-cluster split —
    the executable form of the Council's "test for bimodality" falsifier (audit M-1). A stdlib, small-n-honest
    heuristic: NOT Hartigan's dip test (which needs a bootstrap null), so treat BC as indicative and corroborate
    with the split separation. Grounded — values come straight from the manifest, no fabricated spread."""
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

    want = set(designs) if designs else None
    vals = []
    for r in rows:
        label = f'{r.get("perturbation")}/{r.get("condition")}'
        if want is not None and label not in want:
            continue
        v = val(r)
        if v is not None:
            vals.append(v)
    for d in (designs or []):
        note_design(d)
    scope = sorted(want) if want else "all designs"
    if len(vals) < 4:
        return {"error": f"need >=4 '{channel}' values to test bimodality; got {len(vals)}",
                "channel": channel, "n": len(vals), "scope": scope}

    bc = stats.bimodality_coefficient(vals)
    skew = stats.skewness(vals)
    kurt = stats.kurtosis_excess(vals)
    split = _best_split(vals)
    pooled_sd = statistics.pstdev(vals) or 1e-12
    sep = ((split[2] - split[1]) / pooled_sd) if split else None
    return {
        "channel": channel, "scope": scope, "n": len(vals),
        "bimodality_coefficient": (round(bc, 3) if bc is not None else None),
        "bc_threshold": round(stats.BC_BIMODAL_THRESHOLD, 3),
        "bimodal_suggested": bool(bc is not None and bc > stats.BC_BIMODAL_THRESHOLD),
        "skewness": (round(skew, 3) if skew is not None else None),
        "excess_kurtosis": (round(kurt, 3) if kurt is not None else None),
        "best_split": ({"low_mean": round(split[1], 6), "high_mean": round(split[2], 6),
                        "n_low": split[3], "n_high": split[4],
                        "separation_sd": (round(sep, 2) if sep is not None else None)} if split else None),
        "note": ("Sarle's bimodality coefficient: BC>0.555 suggests two modes (uniform=0.555, normal~0.33). A "
                 "heuristic, NOT Hartigan's dip test — at small n treat as indicative and read best_split.separation_sd "
                 "(gap between the two cluster means in pooled SDs). Pools per-seed values across scope."),
    }
