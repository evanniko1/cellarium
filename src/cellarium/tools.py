"""Grounded tools exposed to the Claude agent.

Reads go through the unified `store` (DuckDB manifest, or the JSON demo cache). `list_species`/`read_species`
give the agent depth to ANY of the model's ~12,000 state variables via the public reader — as long as the
trajectory's full simOut is local (else deferred to HF sharing, DECISIONS D1). No tool invents numbers.
"""

from __future__ import annotations

from pathlib import Path

from . import biosecurity, differential as _diff, envelope, rigor, store, survey
from .model import Design

_SPECIES_KINDS = ["protein", "mrna", "metabolite", "reaction_flux", "exchange_flux"]


def list_results() -> dict:
    return {"results": store.list_results()}


def survey_corpus() -> dict:
    """Deterministic, ranked, whole-corpus survey — call FIRST, before forming any hypothesis."""
    return survey.survey_corpus()


def differential(target: str, reference: str = "wildtype/basal") -> dict:
    """Rank channels + pathways by fold-change of one design vs a reference — what moved most."""
    rigor.note_design(target)
    rigor.note_design(reference)
    return _diff.summary(target, reference)


def top_movers(result_id: str, reference_id: str, kind: str = "protein", top: int = 12) -> dict:
    """Individual species (proteins/mRNAs/...) that moved most between two runs' simOut (protein = symbol-annotated)."""
    if kind not in _SPECIES_KINDS:
        return {"error": f"kind must be one of {_SPECIES_KINDS}"}
    rigor.note_result(result_id)
    rigor.note_result(reference_id)
    return _diff.top_movers(result_id, reference_id, kind, top)


def screen_design(perturbation: str = "wildtype", condition: str | None = None,
                  timeline: str | None = None, params: dict | None = None) -> dict:
    v = biosecurity.screen(Design(perturbation=perturbation, condition=condition, timeline=timeline,
                                  params=params or {}))
    return {"flagged": v.flagged, "signature": v.signature, "matched": v.matched,
            "severity": v.severity, "reason": v.reason}


def screen_phenotype(target: str, reference: str = "wildtype/basal") -> dict:
    """Phenotype-grounded biosecurity: does a design's simulated proteome up-regulate a misuse signature?"""
    v = biosecurity.screen_result(target, reference)
    return {"flagged": v.flagged, "signature": v.signature, "log2fc": v.log2fc,
            "severity": v.severity, "reason": v.reason}


def read_series(result_id: str, channel: str) -> dict:
    rigor.note_result(result_id)
    return store.read_channel(result_id, channel)


def coverage_check() -> dict:
    """How much of the corpus you have deep-read this session — call before generalising a conclusion."""
    return rigor.coverage()


def disconfirm(target: str, reference: str, channel: str) -> dict:
    """Challenge a claimed target-vs-reference effect on a channel (per-seed spread, noise, corpus z)."""
    rigor.note_design(target)
    rigor.note_design(reference)
    return rigor.disconfirm(target, reference, channel)


def check_feasibility(perturbation: str = "wildtype", condition: str | None = None,
                      timeline: str | None = None, seeds: int = 1, generations: int = 1,
                      params: dict | None = None) -> dict:
    v = envelope.check(Design(perturbation=perturbation, condition=condition, timeline=timeline,
                              seeds=seeds, generations=generations, params=params or {}))
    return {"in_envelope": v.in_envelope, "reason": v.reason, "suggestion": v.suggestion}


def run_experiment(perturbation: str = "wildtype", condition: str | None = None,
                   timeline: str | None = None, seeds: int = 1, generations: int = 1,
                   params: dict | None = None) -> dict:
    design = Design(perturbation=perturbation, condition=condition, timeline=timeline,
                    seeds=seeds, generations=generations, params=params or {})
    v = envelope.check(design)
    if not v.in_envelope:
        return {"status": "refused", "reason": v.reason, "suggestion": v.suggestion,
                "note": "Out of the validated envelope — not run, no metric reported."}
    b = biosecurity.screen(design)
    if b.flagged:
        return {"status": "biosecurity_hold", "signature": b.signature, "matched": b.matched,
                "severity": b.severity, "reason": b.reason,
                "note": "Flagged by the biosecurity screen — not run; "
                        + ("refused." if b.severity == "block" else "requires review before running.")}
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
    rigor.note_result(result_id)
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
    {"name": "survey_corpus", "description": "FIRST STEP for any results question. Deterministic, ranked, whole-corpus survey: every design vs a reference per channel, ranked by effect size (|z|), a cross-channel notable set, and coverage. Ground your reasoning in this WHOLE view before drilling in — do not anchor on individual runs or prior conversation.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "differential", "description": "Rank channels + pathways by fold-change of a design (e.g. 'gene_knockout/KO:acrB') vs a reference (default 'wildtype/basal') — what moved most. Use to interpret a KO/perturbation without pre-declaring which molecules to look at.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string", "description": "design label 'perturbation/condition' (from survey_corpus/list_results)"},
                      "reference": {"type": "string"}}, "required": ["target"]}},
    {"name": "top_movers", "description": "Individual species (proteins by default) that moved most between two specific runs' simOut, ranked by fold-change; proteins are gene-symbol-annotated. The drill-down after differential.",
     "input_schema": {"type": "object", "properties": {"result_id": {"type": "string"}, "reference_id": {"type": "string"},
                      "kind": {"type": "string", "enum": _SPECIES_KINDS}, "top": {"type": "integer"}},
                      "required": ["result_id", "reference_id"]}},
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
    {"name": "disconfirm", "description": "Before committing to a causal claim, challenge it: given a claimed effect (target vs reference on a channel), returns the per-seed spread (is the effect bigger than replicate noise?), the corpus z-score, and a falsification checklist. Call this on your main claim before concluding.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string"}, "reference": {"type": "string"},
                      "channel": {"type": "string"}}, "required": ["target", "reference", "channel"]}},
    {"name": "coverage_check", "description": "How much of the corpus you have deep-read this session vs the full design grid. Call before generalising a conclusion; do not claim beyond the examined set.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "check_feasibility", "description": "Check whether a proposed experiment is inside the model's validated envelope. ALWAYS call before proposing to run anything.",
     "input_schema": {"type": "object", "properties": _DESIGN_PROPS}},
    {"name": "screen_design", "description": "Biosecurity screen for a proposed design (INTENT): flags engineering toward a misuse signature (AMR efflux up-regulation, toxin over-expression, virulence). ALWAYS call together with check_feasibility before proposing to run anything; do not run a flagged design.",
     "input_schema": {"type": "object", "properties": {"perturbation": {"type": "string"}, "condition": {"type": "string"},
                      "timeline": {"type": "string"}, "params": {"type": "object"}}}},
    {"name": "screen_phenotype", "description": "Phenotype-grounded biosecurity screen of a design's RESULTS (label 'perturbation/condition'): flags when the simulated proteome up-regulates a misuse signature (AMR efflux) vs a reference — catches an emergent AMR phenotype even if the design never named an efflux gene.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string"}, "reference": {"type": "string"}},
                      "required": ["target"]}},
    {"name": "run_experiment", "description": "Envelope- AND biosecurity-check a design and report whether it's already in the corpus. Enforces the guardrails; does not launch heavy sims per query.",
     "input_schema": {"type": "object", "properties": _DESIGN_PROPS}},
]

_DISPATCH = {"survey_corpus": survey_corpus, "differential": differential, "top_movers": top_movers,
             "disconfirm": disconfirm, "coverage_check": coverage_check,
             "list_results": list_results, "read_series": read_series, "list_species": list_species,
             "read_species": read_species, "screen_design": screen_design,
             "screen_phenotype": screen_phenotype,
             "check_feasibility": check_feasibility, "run_experiment": run_experiment}


def dispatch(name: str, args: dict) -> dict:
    fn = _DISPATCH.get(name)
    if not fn:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(**(args or {}))
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
