"""Grounded tools exposed to the Claude agent.

Every tool returns real data from the result cache (or a guardrail verdict). No tool invents numbers; the
agent is instructed to ground every claim through these, and to run `check_feasibility` before any experiment.
"""

from __future__ import annotations

from . import envelope, qc
from .model import Design, ResultStore, run_live

_store = ResultStore()


def list_results() -> dict:
    return {
        "results": [
            {"id": r.id, "label": r.label, "perturbation": r.design.perturbation,
             "condition": r.design.condition, "timeline": r.design.timeline}
            for r in _store.list()
        ]
    }


def read_series(result_id: str, channel: str) -> dict:
    r = _store.get(result_id)
    if not r:
        return {"error": f"No result '{result_id}'. Call list_results first."}
    if channel not in r.channels:
        return {"error": f"Channel '{channel}' not available for {result_id}.",
                "available": sorted(r.channels)}
    overall, _ = qc.check_result(r)
    return {
        "result_id": result_id, "channel": channel,
        "value": r.channels[channel], "unit": r.units.get(channel, ""),
        "qc": overall.value, "grounded_from": f"simOut::{result_id}",
    }


def check_feasibility(perturbation: str = "wildtype", condition: str | None = None,
                      timeline: str | None = None, seeds: int = 1, generations: int = 1,
                      params: dict | None = None) -> dict:
    d = Design(perturbation=perturbation, condition=condition, timeline=timeline,
               seeds=seeds, generations=generations, params=params or {})
    v = envelope.check(d)
    return {"in_envelope": v.in_envelope, "reason": v.reason, "suggestion": v.suggestion}


def run_experiment(perturbation: str = "wildtype", condition: str | None = None,
                   timeline: str | None = None, seeds: int = 1, generations: int = 1,
                   params: dict | None = None) -> dict:
    d = Design(perturbation=perturbation, condition=condition, timeline=timeline,
               seeds=seeds, generations=generations, params=params or {})
    v = envelope.check(d)
    if not v.in_envelope:
        return {"status": "refused", "reason": v.reason, "suggestion": v.suggestion,
                "note": "Out of the model's validated envelope — not run. No metric reported."}

    match = next((r for r in _store.list()
                  if r.design.perturbation == d.perturbation
                  and r.design.condition == d.condition
                  and r.design.timeline == d.timeline), None)
    if match is None:
        try:
            match = run_live(d)
        except NotImplementedError as exc:
            return {"status": "not_cached", "note": str(exc)}

    overall, per = qc.check_result(match)
    out = {"status": "ran", "result_id": match.id, "qc": overall.value,
           "generation_qc": [s.value for s in per]}
    if qc.is_reportable(match):
        out["channels"] = match.channels
        out["units"] = match.units
    else:
        out["note"] = (f"QC = {overall.value}; metric withheld. A non-ok run is treated as evidence-absent, "
                       f"not reported as a doubling time.")
    return out


# ---- Anthropic tool schemas -------------------------------------------------

_DESIGN_PROPS = {
    "perturbation": {"type": "string", "description": "variant type (wildtype, gene_knockout, ppgpp_conc, timeline, ...)"},
    "condition": {"type": "string", "description": "static media condition, e.g. basal, acetate"},
    "timeline": {"type": "string", "description": "media-shift events, e.g. '0 minimal, 1200 minimal_acetate'"},
    "seeds": {"type": "integer"}, "generations": {"type": "integer"},
}

TOOLS = [
    {"name": "list_results", "description": "List available completed simulation results (id, perturbation, condition).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "read_series", "description": "Read one grounded output channel (e.g. growth_rate, ppgpp_conc, ribosome_elongation_rate) for a result.",
     "input_schema": {"type": "object", "properties": {
         "result_id": {"type": "string"}, "channel": {"type": "string"}}, "required": ["result_id", "channel"]}},
    {"name": "check_feasibility", "description": "Check whether a proposed experiment is inside the model's validated envelope. ALWAYS call before proposing to run anything.",
     "input_schema": {"type": "object", "properties": _DESIGN_PROPS}},
    {"name": "run_experiment", "description": "Run (or look up) an experiment. Enforces the envelope + output QC; withholds metrics from non-ok runs.",
     "input_schema": {"type": "object", "properties": _DESIGN_PROPS}},
]

_DISPATCH = {"list_results": list_results, "read_series": read_series,
             "check_feasibility": check_feasibility, "run_experiment": run_experiment}


def dispatch(name: str, args: dict) -> dict:
    fn = _DISPATCH.get(name)
    if not fn:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(**(args or {}))
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
