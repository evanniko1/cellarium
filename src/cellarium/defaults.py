"""J-1: the defaults that shaped a tool result, named on the result rather than left silent.

Section 17 of the Platform Map is a default that shaped an answer without anyone seeing it. Two kinds are named here:

  tool       a parameter the call left out, filled by the tool function's own signature. The signature is what
             runs, so it is read there and not from the description's prose (which says "default ..." for some
             parameters and nothing for others).
  simulator  what a design's label leaves unsaid: the elongation model when no label carries an `#elong:` tag, the
             medium a design that is not a condition runs in, and the one knowledge-base fit every corpus row shares.

`tools.dispatch` puts both on every successful result as `defaults_applied`, so the model reads them with the
numbers, the tool trace shows them, and the session store and the evidence ledger keep them. The answer's prose is
left alone: a ledger in every answer is noise, and the open list would keep growing.

LIMITS. A default inside a tool body (a threshold that is not a parameter) is invisible to the signature; the
simulator list is the three the Map's audits found shaping answers, not every configuration flag.
"""
from __future__ import annotations

import inspect
import re

from .capability import DEFAULT_MODE

_DESIGN_ARGS = ("design", "design_a", "design_b", "design_or_id", "target", "reference")
_DESIGN_LIST_ARGS = ("designs", "results")
_LABEL = re.compile(r"^[a-z][a-z_]*/\S")

SIMULATOR = {
    "elongation_model": f"{DEFAULT_MODE} (the default; no label carries an #elong: tag)",
    "medium": "minimal: glucose minimal medium with oxygen (MIX0-57), the medium every non-condition design runs in",
    "fit": "the single knowledge-base fit (ParCa) every corpus row shares; no run in the corpus used another",
}


def _designs(args: dict) -> list[str]:
    out = [str(args[k]) for k in _DESIGN_ARGS if args.get(k)]
    for k in _DESIGN_LIST_ARGS:
        v = args.get(k)
        out += [str(x) for x in (v if isinstance(v, (list, tuple)) else [v]) if x]
    return [d for d in out if _LABEL.match(d)]


def tool_defaults(fn, args: dict) -> dict:
    """{parameter: value} for every parameter with a default that the call did not pass."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return {}
    return {p.name: p.default for p in params
            if p.default is not inspect.Parameter.empty and p.name not in args
            and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}


def simulator_defaults(args: dict) -> dict:
    designs = _designs(args)
    if not designs:
        return {}
    out = {}
    if not args.get("elongation_model") and not any("#elong:" in d for d in designs):
        out["elongation_model"] = SIMULATOR["elongation_model"]
    if any(d.split("/", 1)[0] not in ("condition", "timeline") for d in designs):
        out["medium"] = SIMULATOR["medium"]
    out["fit"] = SIMULATOR["fit"]
    return out


def applied(name: str, args: dict, fn) -> dict:
    return {"tool": tool_defaults(fn, args or {}), "simulator": simulator_defaults(args or {})}
