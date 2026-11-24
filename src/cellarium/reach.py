"""L-1: a reachability check behind a proposal. Before a run is proposed to separate hypotheses, can any run of the
proposed kind resolve the quantity that separates them, and if not, which kind could?

This is not identifiability, and must not be called it: a stochastic model with thousands of parameters admits no
tractable identifiability analysis. It asks a narrower question with an exact answer: does the model REPRESENT the
quantity at the resolution needed, under the proposed elongation model, by the registry the gate reads. A proposal
that cannot resolve what it is for is the isoacceptor case: a steady-state run writes 86 isoacceptor columns with at
most 21 distinct values, so no steady-state design separates two isoacceptors.
"""
from __future__ import annotations

from . import capability as C
from . import gate


def reach(observable: str, granularity: str, dependencies=(), mode: str | None = None) -> dict:
    mode = mode or C.DEFAULT_MODE
    req = gate.Requirement(observable=observable, granularity=granularity,
                           regulatory_dependencies=tuple(dependencies or ())).normalised()
    keys = gate.required_capabilities(req)
    if not keys:
        return {"verdict": "undeclared", "mode": mode, "modes_that_resolve": [],
                "why": "no registry record covers this quantity at this resolution; that is not evidence either way"}
    modes = list(gate._modes_representing_all(keys))
    blocking = [k for k in keys if gate.representable(k, mode) is False]
    if not blocking:
        return {"verdict": "resolvable", "mode": mode, "capabilities": list(keys), "modes_that_resolve": modes}
    return {"verdict": "exhausted", "mode": mode, "blocking": blocking, "modes_that_resolve": modes,
            "why": [str(C.check(k, mode).get("refusal") or "") for k in blocking],
            "what_would": (f"a run under elongation_model={modes[0]}" if modes else
                           "no elongation model in this checkout resolves it, so no run would")}
