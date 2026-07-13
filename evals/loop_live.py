"""Closed-loop verdict engine (paper Workstream A1/D1).

Turns a Council `Hypothesis` into an EXECUTED test on fresh simulation output and returns confirm/refute plus a
severity assessment. Two steps:
  1. compile_falsifier() — an LLM translates the natural-language falsifier into a small structured, executable
     spec: {statistic, channel, target, reference, threshold, refute_if}. (A thin, auditable compile step; the
     hypothesis's own operational_defs already name the observable + measure.)
  2. execute() — computes the ACTUAL statistic from per-seed channel values (via rigor.disconfirm, which reads
     the manifest corpus incl. fresh run_live runs), applies the decision rule, and reports the effect size and
     whether it exceeds a pre-registered smallest-effect-size-of-interest (SESOI) — a severity-flavoured verdict
     (NOT post-hoc power).

Scored target-vs-reference from the runs themselves; the corpus z-score is deliberately NOT used as ground
truth. Supported statistics: dispersion_cv, mean_difference (Welch t). Regression-slope and within-run
transient/bimodality are v2 (a hypothesis needing them is returned status='unsupported_statistic').
"""
from __future__ import annotations

import json
import math
import statistics

from cellarium import rigor
from cellarium.hypothesis import Hypothesis

_COMPILE_TOOL = {
    "name": "compile_falsifier",
    "description": "Translate the hypothesis's falsifier into a structured, executable test spec.",
    "input_schema": {"type": "object", "properties": {
        "statistic": {"type": "string", "enum": ["dispersion_cv", "mean_difference", "regression_slope",
                                                 "bimodality", "transient"]},
        "channel": {"type": "string", "description": "the summary channel the test reads"},
        "target": {"type": "string", "description": "design label 'perturbation/condition'"},
        "reference": {"type": "string", "description": "the null/baseline design label"},
        "threshold": {"type": "number", "description": "the numeric decision threshold in the falsifier"},
        "refute_if": {"type": "string", "enum": ["below_threshold", "above_threshold", "not_significant"],
                      "description": "condition on the statistic that REFUTES H1"},
    }, "required": ["statistic", "channel", "target", "reference", "threshold", "refute_if"]},
}

_COMPILE_SYS = (
    "You translate a scientific hypothesis's falsifier into a structured executable test spec. Read the "
    "falsifier's channel, target/reference designs, decision_rule and refuting_result, and the operational "
    "definitions. Choose the statistic the decision rule actually uses (dispersion_cv for a CV/coefficient-of-"
    "variation test; mean_difference for a target-vs-reference difference / Welch-t; regression_slope for a "
    "slope-across-conditions test; bimodality for a distribution-shape test; transient for a within-run pre/post "
    "test). Extract the numeric threshold and whether the statistic being BELOW/ABOVE it, or NOT being "
    "significant, is what refutes H1. Emit via the tool.")


def compile_falsifier(h: Hypothesis, client, model: str = "claude-sonnet-4-5") -> dict:
    if h.falsifier is None:
        return {}
    payload = {"falsifier": h.falsifier.model_dump(), "predicted_effect": h.predicted_effect,
               "operational_defs": [o.model_dump(by_alias=True) for o in h.operational_defs]}
    resp = client.messages.create(model=model, max_tokens=512, system=_COMPILE_SYS, tools=[_COMPILE_TOOL],
                                  tool_choice={"type": "tool", "name": "compile_falsifier"},
                                  messages=[{"role": "user", "content": json.dumps(payload)}])
    for b in resp.content:
        if getattr(b, "type", None) == "tool_use":
            return dict(b.input)
    return {}


def _cv(xs):
    if len(xs) < 2:
        return None
    m = statistics.fmean(xs)
    return (statistics.stdev(xs) / m) if m else None


def execute(spec: dict, *, sesoi: float | None = None) -> dict:
    """Run the compiled falsifier against the manifest corpus (incl. fresh runs). Returns confirm/refute +
    effect + severity-vs-SESOI. `sesoi` = the pre-registered smallest effect size of interest for this test."""
    stat = spec.get("statistic")
    ch, tgt, ref = spec.get("channel"), spec.get("target"), spec.get("reference")
    thr, refute_if = spec.get("threshold"), spec.get("refute_if")
    if stat in ("regression_slope", "bimodality", "transient"):
        return {"status": "unsupported_statistic", "statistic": stat,
                "note": "v1 executes dispersion_cv and mean_difference; this needs the series/segment scorer (v2)."}

    d = rigor.disconfirm(tgt, ref, ch)
    if "error" in d:
        return {"status": "no_data", "detail": d["error"], "spec": spec}
    tv = d.get("target", {}).get("values", []) or []
    rv = d.get("reference", {}).get("values", []) or []

    if stat == "dispersion_cv":
        cv = _cv(tv)
        if cv is None:
            return {"status": "no_data", "detail": "need >=2 seeds", "n": len(tv)}
        refuted = (cv < thr) if refute_if == "below_threshold" else (cv > thr)
        out = {"status": "executed", "statistic": "dispersion_cv", "channel": ch, "n_seeds": len(tv),
               "cv": round(cv, 4), "threshold": thr, "refute_if": refute_if,
               "H1_refuted": bool(refuted), "verdict": "REFUTED" if refuted else "SUPPORTED"}
        if sesoi is not None:  # severity flavour: is the observed CV beyond the pre-registered SESOI?
            out["sesoi"] = sesoi
            out["exceeds_sesoi"] = bool(cv >= sesoi)
        return out

    # mean_difference: use the Welch t disconfirm already computed
    t = d.get("welch_t")
    sig = d.get("significant")
    eff = d.get("effect_pct")
    if t is None:
        return {"status": "underpowered", "detail": "need >=2 seeds per design", "n_target": len(tv), "n_ref": len(rv)}
    if refute_if == "not_significant":
        refuted = not sig
    elif refute_if == "below_threshold":
        refuted = abs(t) < thr
    else:
        refuted = abs(t) > thr
    out = {"status": "executed", "statistic": "mean_difference", "channel": ch, "welch_t": t,
           "significant": sig, "effect_pct": eff, "n_target": len(tv), "n_ref": len(rv),
           "threshold": thr, "refute_if": refute_if, "H1_refuted": bool(refuted),
           "verdict": "REFUTED" if refuted else "SUPPORTED"}
    if sesoi is not None:
        out["sesoi_pct"] = sesoi
        out["exceeds_sesoi"] = bool(eff is not None and abs(eff) >= sesoi)
    return out


def run_verdict(h: Hypothesis, client, *, sesoi: float | None = None, model: str = "claude-sonnet-4-5") -> dict:
    spec = compile_falsifier(h, client, model)
    if not spec:
        return {"status": "no_falsifier"}
    return {"spec": spec, **execute(spec, sesoi=sesoi)}


if __name__ == "__main__":  # quick manual check on a live Council hypothesis for the flagship question
    from pathlib import Path

    from dotenv import load_dotenv
    load_dotenv(str(Path(__file__).resolve().parents[1] / ".env"))   # .env at the repo root (was a hardcoded mac path)
    import anthropic
    from cellarium import council
    cl = anthropic.Anthropic()
    hyp = council.deliberate("Do genetically identical E. coli cells behave differently, and why?",
                             temperature=0.7, client=cl, verbose=False)
    print("falsifier channel:", hyp.falsifier.channel if hyp.falsifier else None)
    print(json.dumps(run_verdict(hyp, cl, sesoi=0.05), indent=2))
