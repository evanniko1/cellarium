"""P-1: effect verification. An answer cannot be wider than its admission.

The gate admits a question with a Decision: the capabilities it requires, under one elongation model. The agent then
calls tools, and a tool can read more than that: a question admitted at per-amino-acid resolution answered from a
per-isoacceptor read, or a ppGpp question admitted under steady state answered from a kinetic design, where ppGpp is
not represented. PACE (arXiv:2511.03862) finds that checking an action's effect against what was authorised carries
most of an agent's protection; here the effect is what a tool result reads.

What a tool reads is declared once, by the raw-tool gate (P-2: `mcp.READS_SIMULATED_QUANTITIES` and the capability
tables its `_required` consults), so the two checks cannot drift apart. A result that reads a capability the admission
did not require is marked `wider_than_admitted`, naming the capability, whether the model represents it in the modes
read, and what was admitted. It is a note, not a refusal: the read was made, and the agent and the reader see what it
was. Outside an admission (no gate ran) nothing changes.

LIMITS. A tool whose output depends on nothing the capability tables name is never wider, whatever it returns; and the
admission is per thread, so work handed to another thread runs outside it.
"""
from __future__ import annotations

import contextlib
import threading

_state = threading.local()


@contextlib.contextmanager
def admitted(decision):
    """The gate's admission, active for the calls made inside the block on this thread."""
    prev = getattr(_state, "decision", None)
    _state.decision = decision
    try:
        yield decision
    finally:
        _state.decision = prev


def current():
    return getattr(_state, "decision", None)


def verify(name: str, args: dict, out):
    d = current()
    if d is None or not isinstance(out, dict) or out.get("error"):
        return out
    from . import gate, mcp
    if name not in mcp.READS_SIMULATED_QUANTITIES:
        return out
    needed = mcp._required(name, args or {})
    admitted_keys = list(getattr(d, "required_capabilities", ()) or ())
    modes = mcp._modes_of(args or {}) if mcp._designs_of(args or {}) or (args or {}).get("elongation_model") \
        else [d.mode]
    wider = [k for k in needed if k not in admitted_keys]
    off_mode = [m for m in modes if m != d.mode]
    if not wider and not off_mode:
        return out
    keys = wider or needed
    if not keys:
        return out
    return {**out, "wider_than_admitted": {
        "not_admitted": wider,
        "admitted": admitted_keys,
        "elongation_model": d.mode,
        "modes_read": modes,
        "represented_here": {k: all(gate.representable(k, m) is not False for m in modes) for k in keys},
        "read_this_before_the_numbers": ("this result reads beyond what the gate admitted for the question; a "
                                         "capability not represented in the modes read gives a number that does "
                                         "not mean what its name says"),
    }}
