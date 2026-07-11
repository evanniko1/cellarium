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
    This is the credibility surface: the hypothesis was operationalized BEFORE the agent read any result."""
    if hyp is None:
        return {}
    view = {"brief": hyp.brief() if hasattr(hyp, "brief") else str(hyp)}
    for attr in ("claim", "falsifier", "rivals", "operational_def"):
        v = getattr(hyp, attr, None)
        if v:
            view[attr] = str(v)
    return view


def trace_view(trace: list) -> list:
    """Compact per-tool-call view for the reasoning trail: tool name, input, and its grounded output (JSON-safe)."""
    return [{"tool": n, "input": i, "output": json.loads(json.dumps(o, default=str))} for (n, i, o) in trace]
