"""TRAJ-1 — scoring a RECORDED TOOL TRAJECTORY, not the answer at the end of it.

WHY. Final-answer scoring cannot see the two failures that matter most in a tool-using agent: it picked a
plausible-looking wrong tool, or it filled a parameter it had no basis for. TRAJECT-Bench (He et al., ICLR 2026,
OpenReview TZWnWvsQ0X) names those "similar tool confusion" and "parameter-blind selection" and shows they are
invisible to a correctness check on the answer. Cellarium already guards the first at the SCHEMA level (family 6,
name confusability) and the second at the DESCRIPTION level (the parameter glossary, tools.py). Neither tells you
what the agent actually did on a real question. This does.

WHAT THIS IS NOT. TRAJECT-Bench's own metrics compare a trajectory against a GOLD trajectory for the task. There
are no gold trajectories for Cellarium's questions, and writing them now — after reading these traces — would be
scoring the instrument against a target drawn around the shot. So this implements the REFERENCE-FREE subset:
properties of a trajectory that are facts about the trace itself, each one checkable without anybody deciding in
advance what the right sequence was.

    1. SELECTION VALIDITY  — every called tool exists in the declared surface.
    2. ARGUMENT VALIDITY   — every call satisfies its own input_schema: required present, no unknown property,
                             right type, enum respected. This is "parameter-blind selection" made mechanical.
    3. ARGUMENT FAULTS     — calls the surface itself refused with `about == "request"`. By the error contract
                             (errors.py) that is the agent's fault; `corpus` and `environment` are not.
    4. GROUNDING           — a corpus handle (a design label, a result_id, a gene) must have come from somewhere:
                             the question, or an earlier call's OUTPUT. An argument that appears in neither was
                             invented, and a plausible invented label is the failure that looks like success.
    5. DECLARED ORDER      — a tool whose own description declares itself the FIRST STEP was called first. The
                             declaration is read out of the description, so it predates the trace and is not a
                             rule written to fit it.
    6. REDUNDANCY          — the same (tool, arguments) called twice, and retries of a tool that just errored.

Every count is reported per trace and over the set. Nothing here is a pass/fail verdict on the agent: a high
redundancy count on a hard question may be correct behaviour. The scores are measurements, and the report says
which ones are faults by the contract (2, 3, 5 in its ungrounded form) and which are descriptive (6).

TWO LIMITS, STATED SO A CLEAN SCORE IS NOT OVERSOLD.
  - Measure 2 is a WEAK signal on traces produced through a schema-carrying API: the model is shown the schema
    with every call, so a wrong type or an unknown property is already rare. It earns its place on records that
    did NOT come through that path — a hand-transcribed hypothesis, a replayed trajectory, a tool surface whose
    schema changed after the trace was recorded.
  - Measure 3 needs the error contract. A trace recorded before errors.py (2026-10-28) has no `about` field, so
    it cannot say whose fault a refusal was. The set report returns None and says so, rather than 0.0.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# The parameters whose values are HANDLES INTO THE CORPUS — the ones an agent cannot legitimately invent. Named
# here rather than inferred, because the distinction is semantic: `title` and `claim` are the agent's own prose
# and are SUPPOSED to be new, while `design` and `result_id` must have been read somewhere.
HANDLE_PARAMS = {
    "design", "design_a", "design_b", "design_or_id", "target", "reference", "result_id", "gene", "symbol",
    "species_id", "regulon", "metabolite", "unit", "designs", "genes", "channels", "channel", "x_channel",
    "y_channel",
}

# Below this length a substring match is meaningless ("s0", "ok", a seed index).
MIN_HANDLE_LEN = 4


def load(path: str | Path) -> dict:
    """One trace file -> {question, tool_calls}. Accepts the Cellwright/Council trace shape."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    calls = d.get("tool_calls") or []
    return {"id": Path(path).stem, "question": d.get("question") or "", "seconds": d.get("seconds"),
            "calls": [{"t": c.get("t"), "tool": c.get("tool"), "input": c.get("input") or {},
                       "output": c.get("output")} for c in calls]}


def _specs() -> dict[str, dict]:
    from . import tools
    return {t["name"]: t for t in tools.TOOLS}


def _declared_first_steps() -> set[str]:
    """Tools that call themselves the first step, read from their own descriptions."""
    return {name for name, t in _specs().items() if "FIRST STEP" in (t.get("description") or "")}


def validate_arguments(name: str, args: dict, specs: dict[str, dict]) -> list[str]:
    """The call against its own schema. Returns a list of fault strings — empty is a clean call."""
    spec = specs.get(name)
    if spec is None:
        return [f"unknown_tool:{name}"]
    schema = spec.get("input_schema") or {}
    props = schema.get("properties") or {}
    faults = []
    for req in schema.get("required") or []:
        if req not in args:
            faults.append(f"missing_required:{req}")
    # `anyOf` branches of required keys (chart) — satisfied if ANY branch is complete.
    branches = [set(b.get("required") or []) for b in (schema.get("anyOf") or [])]
    if branches and not any(b <= set(args) for b in branches):
        faults.append("no_anyOf_branch_satisfied:" + "|".join(",".join(sorted(b)) for b in branches))
    for key, value in args.items():
        meta = props.get(key)
        if meta is None:
            faults.append(f"unknown_property:{key}")
            continue
        want = meta.get("type")
        kinds = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list,
                 "object": dict}
        py = kinds.get(want)
        if py and not isinstance(value, py):
            faults.append(f"wrong_type:{key}={type(value).__name__}!={want}")
            continue
        if meta.get("enum") and value not in meta["enum"]:
            faults.append(f"not_in_enum:{key}={value!r}")
    return faults


def _text_of(x: Any) -> str:
    return json.dumps(x, default=str) if not isinstance(x, str) else x


def _handle_values(args: dict) -> list[tuple[str, str]]:
    out = []
    for key, value in (args or {}).items():
        if key not in HANDLE_PARAMS:
            continue
        for v in (value if isinstance(value, list) else [value]):
            if isinstance(v, str) and len(v) >= MIN_HANDLE_LEN:
                out.append((key, v))
    return out


def score(trace: dict) -> dict:
    """Every measure above, for one trace."""
    specs = _specs()
    first_steps = _declared_first_steps()
    seen_text = [_text_of(trace.get("question") or "")]
    rows, ungrounded, arg_faults, refusals, unknown, repeats, retries, errors = [], [], [], [], [], [], [], []
    seen_calls: set[tuple] = set()
    prev_error_tool = None

    for i, c in enumerate(trace["calls"]):
        name, args, out = c["tool"], c["input"], c["output"]
        faults = validate_arguments(name, args, specs)
        if any(f.startswith("unknown_tool") for f in faults):
            unknown.append(name)
        elif faults:
            arg_faults.append({"i": i, "tool": name, "faults": faults})

        # grounding: against the question and every EARLIER output, never this call's own output
        missing = [f"{k}={v}" for k, v in _handle_values(args)
                   if not any(v in s for s in seen_text)]
        if missing:
            ungrounded.append({"i": i, "tool": name, "args": missing})

        key = (name, json.dumps(args, sort_keys=True, default=str))
        if key in seen_calls:
            repeats.append({"i": i, "tool": name})
        seen_calls.add(key)

        about = (out or {}).get("about") if isinstance(out, dict) else None
        err = (out or {}).get("error") if isinstance(out, dict) else None
        if err:
            errors.append({"i": i, "tool": name, "about": about, "reason": (out or {}).get("reason")})
        if about == "request":
            refusals.append({"i": i, "tool": name, "reason": (out or {}).get("reason")})
        if err and prev_error_tool == name:
            retries.append({"i": i, "tool": name})
        prev_error_tool = name if err else None

        seen_text.append(_text_of(out))
        rows.append({"i": i, "tool": name, "clean": not faults, "grounded": not missing})

    called = [c["tool"] for c in trace["calls"]]
    declared = sorted(first_steps)
    first_ok = (not declared) or (not called) or (called[0] in first_steps)
    n = len(called)
    return {
        "id": trace["id"], "n_calls": n, "seconds": trace.get("seconds"),
        "distinct_tools": len(set(called)),
        "selection_validity": 1.0 if not n else (n - len(unknown)) / n,
        "unknown_tools": sorted(set(unknown)),
        "argument_validity": 1.0 if not n else (n - len(arg_faults) - len(unknown)) / n,
        "argument_faults": arg_faults,
        "errors": errors,
        "errors_without_about": [e for e in errors if e["about"] is None],
        "request_refusals": refusals,
        "grounding": 1.0 if not n else (n - len(ungrounded)) / n,
        "ungrounded": ungrounded,
        "declared_first_steps": declared,
        "first_call": called[0] if called else None,
        "first_call_is_a_declared_first_step": first_ok,
        "redundant_calls": repeats,
        "retries_after_an_error": retries,
        "calls": rows,
    }


def score_set(paths: list[str | Path]) -> dict:
    """The set-level view. `pass^k`-style: the share of traces with NO fault on the three contract measures."""
    scored = [score(load(p)) for p in paths]
    k = len(scored) or 1
    clean = [s for s in scored
             if not s["unknown_tools"] and not s["argument_faults"] and not s["ungrounded"]
             and s["first_call_is_a_declared_first_step"]]
    total = sum(s["n_calls"] for s in scored)

    def rate(field):
        return sum(len(s[field]) for s in scored) / total if total else 0.0

    # A trace recorded before errors.py (2026-10-28) carries no `about`, so whose fault an error was CANNOT be
    # read off it. Reporting 0.0 there would be an absence in the trace format presented as a fact about the
    # agent — the failure this project keeps catching in its own instruments. So the measure is three-valued.
    n_err = sum(len(s["errors"]) for s in scored)
    n_blind = sum(len(s["errors_without_about"]) for s in scored)
    return {
        "n_traces": len(scored), "n_calls": total,
        "clean_trajectories": len(clean), "pass_k": len(clean) / k,
        "per_call_argument_fault_rate": rate("argument_faults"),
        "per_call_ungrounded_rate": rate("ungrounded"),
        "n_errors": n_err, "n_errors_without_about": n_blind,
        "per_call_request_refusal_rate": None if n_blind else rate("request_refusals"),
        "request_refusal_basis": (
            f"not measurable: {n_blind} of {n_err} errors carry no `about`, so the trace cannot say whether the "
            f"refusal was the agent's fault (request) or the corpus's" if n_blind else
            f"all {n_err} errors carry `about`"),
        "per_call_redundancy_rate": rate("redundant_calls"),
        "traces_starting_on_a_declared_first_step":
            sum(1 for s in scored if s["first_call_is_a_declared_first_step"]),
        "traces": scored,
    }
