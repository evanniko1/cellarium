"""Grounded tools exposed to the Claude agent.

Reads go through the unified `store` (DuckDB manifest, or the JSON demo cache). `list_species`/`read_species`
give the agent depth to ANY of the model's ~12,000 state variables via the public reader — as long as the
trajectory's full simOut is local (else deferred to HF sharing, DECISIONS D1). No tool invents numbers.
"""

from __future__ import annotations

from pathlib import Path

from . import envelope, store
from .model import Design

_SPECIES_KINDS = ["protein", "mrna", "metabolite", "reaction_flux", "exchange_flux"]


def list_results() -> dict:
    return {"results": store.list_results()}


def read_series(result_id: str, channel: str) -> dict:
    return store.read_channel(result_id, channel)


def check_feasibility(perturbation: str = "wildtype", condition: str | None = None,
                      timeline: str | None = None, seeds: int = 1, generations: int = 1,
                      params: dict | None = None) -> dict:
    v = envelope.check(Design(perturbation=perturbation, condition=condition, timeline=timeline,
                              seeds=seeds, generations=generations, params=params or {}))
    return {"in_envelope": v.in_envelope, "reason": v.reason, "suggestion": v.suggestion}


def run_experiment(perturbation: str = "wildtype", condition: str | None = None,
                   timeline: str | None = None, seeds: int = 1, generations: int = 1,
                   params: dict | None = None) -> dict:
    v = envelope.check(Design(perturbation=perturbation, condition=condition, timeline=timeline,
                              seeds=seeds, generations=generations, params=params or {}))
    if not v.in_envelope:
        return {"status": "refused", "reason": v.reason, "suggestion": v.suggestion,
                "note": "Out of the validated envelope — not run, no metric reported."}
    matches = [r for r in store.list_results()
               if r.get("perturbation") == perturbation and r.get("condition") == condition
               and r.get("timeline") == timeline]
    if matches:
        return {"status": "in_corpus", "results": matches[:8],
                "note": "Already generated. Ground via read_series / read_species."}
    return {"status": "in_envelope_uncached",
            "note": "Valid, but not yet in the corpus. Generation happens offline via a campaign, not per query."}


def _run_root(result_id: str) -> Path | None:
    root = store.simout_path(result_id)
    return Path(root) if root and Path(root).exists() else None


def list_species(result_id: str, kind: str = "protein", search: str = "") -> dict:
    from . import reader
    if kind not in _SPECIES_KINDS:
        return {"error": f"kind must be one of {_SPECIES_KINDS}"}
    root = _run_root(result_id)
    if root is None:
        return {"error": "full simOut not available locally for this trajectory (see DECISIONS D1 — HF sharing)."}
    return {"result_id": result_id, **reader.list_species(root, kind, search)}


def read_species(result_id: str, species_id: str, kind: str = "protein") -> dict:
    from . import reader
    if kind not in _SPECIES_KINDS:
        return {"error": f"kind must be one of {_SPECIES_KINDS}"}
    root = _run_root(result_id)
    if root is None:
        return {"error": "full simOut not available locally for this trajectory (see DECISIONS D1)."}
    return reader.read_species(root, kind, species_id)


_DESIGN_PROPS = {
    "perturbation": {"type": "string", "description": "variant type (wildtype, gene_knockout, ppgpp_conc, timeline, ...)"},
    "condition": {"type": "string", "description": "static media condition, e.g. basal, acetate"},
    "timeline": {"type": "string", "description": "media-shift events, e.g. '0 minimal, 1200 minimal_acetate'"},
    "seeds": {"type": "integer"}, "generations": {"type": "integer"},
}

TOOLS = [
    {"name": "list_results", "description": "List simulation results in the corpus (id, perturbation, condition, QC).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "read_series", "description": "Read one summary channel (growth_rate, ppgpp_conc, ...) for a result: overall mean PLUS its downsampled trajectory and per-media-segment means — use this to see transients (e.g. the ppGpp spike after a media downshift) that a single mean hides.",
     "input_schema": {"type": "object", "properties": {"result_id": {"type": "string"}, "channel": {"type": "string"}},
                      "required": ["result_id", "channel"]}},
    {"name": "list_species", "description": "Resolve real model IDs for a molecule kind (protein/mrna/metabolite/reaction_flux/exchange_flux) matching a search — grounding before read_species.",
     "input_schema": {"type": "object", "properties": {"result_id": {"type": "string"},
                      "kind": {"type": "string", "enum": _SPECIES_KINDS}, "search": {"type": "string"}},
                      "required": ["result_id", "kind"]}},
    {"name": "read_species", "description": "Read the time-series of ONE state variable (any protein/mRNA/metabolite/flux) from a result's full simOut.",
     "input_schema": {"type": "object", "properties": {"result_id": {"type": "string"},
                      "species_id": {"type": "string"}, "kind": {"type": "string", "enum": _SPECIES_KINDS}},
                      "required": ["result_id", "species_id"]}},
    {"name": "check_feasibility", "description": "Check whether a proposed experiment is inside the model's validated envelope. ALWAYS call before proposing to run anything.",
     "input_schema": {"type": "object", "properties": _DESIGN_PROPS}},
    {"name": "run_experiment", "description": "Envelope-check a design and report whether it's already in the corpus. Enforces the guardrails; does not launch heavy sims per query.",
     "input_schema": {"type": "object", "properties": _DESIGN_PROPS}},
]

_DISPATCH = {"list_results": list_results, "read_series": read_series, "list_species": list_species,
             "read_species": read_species, "check_feasibility": check_feasibility, "run_experiment": run_experiment}


def dispatch(name: str, args: dict) -> dict:
    fn = _DISPATCH.get(name)
    if not fn:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(**(args or {}))
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
