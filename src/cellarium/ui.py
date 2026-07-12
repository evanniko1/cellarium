"""Pure view-helpers for the Cellarium interface — no UI framework, so they're testable and reusable.

The glass box shows three things per question: the Council's Hypothesis (formed BLIND to the data), the agent's
grounded tool trace (every number from a real run), and a trust strip (provenance / rigor / safety). These helpers
turn the raw objects (Hypothesis, the on_tool trace) into render-ready dicts; the Streamlit app — or a CLI, or a
web frontend — draws them. No LLM, no I/O here.
"""

from __future__ import annotations

import json

# tool name -> (trust-strip label, verdict extractor): the "can I trust this number?" signals lifted from the trace
_TRUST = {
    "provenance": ("Provenance", lambda o: o.get("provenance") or o.get("note", "checked")),
    "power_check": ("Power", lambda o: "under-powered" if o.get("adequately_powered") is False else "powered"),
    "disconfirm": ("Disconfirmation", lambda o: o.get("verdict") or "challenged"),
    "model_validation": ("Model trust", lambda o: str(o.get("summary") or "checked")[:40]),
    "mechanistic_scope": ("Scope", lambda o: o.get("class") or o.get("role") or "checked"),
    "screen_design": ("Biosecurity", lambda o: "FLAGGED" if o.get("flags") else "clear"),
    "screen_phenotype": ("Biosecurity", lambda o: "FLAGGED" if o.get("flags") else "clear"),
}


def trust_signals(trace: list) -> dict:
    """Extract the trust strip (provenance / rigor / safety) from the agent's tool trace. Later calls win. The
    point: these signals ride ALONGSIDE the answer, never buried — a claim that wasn't powered or disconfirmed
    should say so."""
    sig: dict = {}
    for name, _inp, out in trace:
        spec = _TRUST.get(name)
        if spec and isinstance(out, dict):
            label, fn = spec
            try:
                sig[label] = fn(out)
            except Exception:
                sig[label] = "checked"
    return sig


def hypothesis_view(hyp) -> dict:
    """Render-ready fields of a converged Hypothesis (safe on any shape). Empty dict on the direct path (no council).
    This is the credibility surface: the hypothesis was operationalized BEFORE the agent read any result. Exposes
    the FULL structured brief (H1/H0, predicted effect, operational defs, assumptions) so the interface can show it
    as readable sections in the Council drawer instead of the raw brief() blob."""
    if hyp is None:
        return {}
    view = {"brief": hyp.brief() if hasattr(hyp, "brief") else str(hyp)}
    for attr in ("claim", "h1", "h0", "predicted_effect"):
        v = getattr(hyp, attr, None)
        if v:
            view[attr] = str(v)
    # falsifier + rivals as STRUCTURED objects, not str() — the interface renders the decisive test as human prose
    # (measured channel, reference, decision rule), never the disconfirm() call signature it used to stringify to.
    fals = getattr(hyp, "falsifier", None)
    if fals:
        view["falsifier"] = fals if isinstance(fals, str) else {
            "target": getattr(fals, "target", ""), "reference": getattr(fals, "reference", ""),
            "channel": getattr(fals, "channel", ""), "decision_rule": getattr(fals, "decision_rule", ""),
            "refuting_result": getattr(fals, "refuting_result", "")}
    rivals = getattr(hyp, "rivals", None) or []
    if rivals:
        view["rivals"] = rivals if isinstance(rivals, str) else [
            {"claim": getattr(r, "claim", ""), "distinguishing_result": getattr(r, "distinguishing_result", "")}
            for r in rivals]
    ods = getattr(hyp, "operational_defs", None) or []
    if ods:
        view["operational_defs"] = [{"term": getattr(o, "term", ""), "observable": getattr(o, "observable", ""),
                                     "measure": getattr(o, "measure", "")} for o in ods]
    aux = getattr(hyp, "auxiliary_assumptions", None) or []
    if aux:
        view["assumptions"] = [str(a) for a in aux]
    for attr in ("rounds_used", "substantive_objections"):
        v = getattr(hyp, attr, None)
        if v:
            view[attr] = v
    return view


def trace_view(trace: list) -> list:
    """Compact per-tool-call view for the reasoning trail: tool name, input, and its grounded output (JSON-safe)."""
    return [{"tool": n, "input": i, "output": json.loads(json.dumps(o, default=str))} for (n, i, o) in trace]


def design_view(design) -> dict:
    """Render-ready view of a candidate Design — the runnable experiment the Council proposed to test its
    hypothesis. Accepts a Design model or a plain dict (the queue stores designs as dicts)."""
    def g(attr, default=None):
        return design.get(attr, default) if isinstance(design, dict) else getattr(design, attr, default)
    params = g("params", {}) or {}
    genes = list(params.get("target_genes") or ([params["gene"]] if params.get("gene") else []))
    return {
        "perturbation": g("perturbation", "wildtype"),
        "condition": g("condition"),
        "timeline": g("timeline"),
        "seeds": int(g("seeds", 1) or 1),
        "generations": int(g("generations", 1) or 1),
        "params": params,
        "genes": genes,
    }


def vet_summary(vet) -> dict:
    """Distill a vet_hypothesis result into the approval gate's signals. SAFETY is the only hard block; feasibility
    and provenance are advisory — out-of-sample / boundary probes are ENCOURAGED (they are where the model can be
    wrong), never gated. This is what the human reads before approving a run."""
    if not isinstance(vet, dict):
        return {}
    safety = vet.get("safety") or {}
    feas = vet.get("feasibility") or {}
    prov = vet.get("provenance") or {}
    return {
        "runnable": bool(vet.get("runnable")),
        "safety": "FLAGGED — human review required" if safety.get("flagged") else "clear",
        "feasibility": "in the validated envelope" if feas.get("in_envelope") else "boundary probe (out-of-envelope)",
        "provenance": prov.get("provenance") or "—",
        "why": (prov.get("value") or feas.get("advisory") or "").strip(),
    }
