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

# The parameters whose values are HANDLES INTO THE CORPUS OR INTO THE MODEL — the ones an agent cannot
# legitimately invent. Named here rather than inferred, because the distinction is semantic: `title`, `claim` and
# `rationale` are the agent's own prose and are SUPPOSED to be new, while `design` and `result_id` must have been
# read somewhere.
#
# THE SET WAS TOO NARROW ON ITS FIRST WRITING (corrected 2026-10-28 after auditing the model's own taxonomy).
# wcEcoli does not only represent genes. Its knowledge base declares 21 molecule groups (amino acids, codons,
# elongator and initiator tRNAs, ribosomal proteins, rRNA operons, the two ribosomal subunits' proteins,
# replisome subunits, lipids, polyamines, NTPs/dNTPs/NMPs and their polymerized forms) and 11 classes of
# individually tracked object (`gene`, `RNA`, `promoter`, `DnaA_box`, `chromosomal_segment`, `chromosome_domain`,
# `full_chromosome`, `oriC`, `active_RNAP`, `active_ribosome`, and the replisome), over 16 processes and
# 19 listeners. Reaction fluxes alone span 9,612 reactions.
#
# So a handle is any name that points INTO that world, and the first version missed five classes of them. The one
# that matters most is `condition`: the Council has already invented media names (`minimal_minus_one_aa`,
# `rich_EZ_aa`) that passed the envelope check, which is W4C-10 in BACKLOG — exactly the failure grounding exists
# to catch, and the check was blind to it.
HANDLE_PARAMS = {
    # runs and designs
    "design", "design_a", "design_b", "design_or_id", "designs", "target", "reference", "result_id", "results",
    "request_id",
    # the model's own entities
    "gene", "genes", "symbol", "species_id", "metabolite", "reactions", "regulon", "operons",
    "retype_cistrons",
    # the experiment's configuration: media, schedules, variant types, comparability arms
    "condition", "timeline", "medium", "perturbation", "arm", "capability", "block_by", "sim_path",
    # readouts
    "channel", "channels", "x_channel", "y_channel", "unit",
}

# Parameters whose values come from a CLOSED set declared in the schema AT EVERY SITE. `validate_arguments`
# already fails a value outside the enum and names it, so grounding would repeat that check less precisely.
# Listed so the exclusion is a decision rather than an oversight, and tested: a name only belongs here while
# every tool that takes it declares an enum for it.
ENUM_GUARDED = {"kind", "mode", "objective", "elongation_model"}

# The agent's own output: prose it is supposed to compose, and an address it is supposed to choose.
AGENT_AUTHORED = {"claim", "rationale", "title", "question", "reason", "name", "url", "contains"}

# `search` is in none of the three on purpose. It is a free substring filter on `list_species` (the agent's own)
# and a search STRATEGY with an enum on `generate_designs` (closed) — one name, two roles, the same trap as
# `kind`. A set keyed by the name cannot hold both, so neither group claims it.
ROLE_DIFFERS_BY_TOOL = {"search"}

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


def _strings_in(value: Any) -> list[str]:
    """Every string leaf of a handle's value. `reactions` is a list, `medium` and `retype_cistrons` are objects
    whose KEYS are the ids, so a scalar-only reader would check nothing at all on three of the FBA tools."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in _strings_in(v)]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in ([k] if isinstance(k, str) else []) + _strings_in(v)]
    return []


def _timeline_media(spec: str) -> list[str]:
    """A timeline is '0 minimal, 1200 minimal_acetate' — the medium NAMES are the handles, not the string. The
    whole string never appears in an earlier output, so checking it whole would flag every legitimate timeline."""
    out = []
    for part in str(spec).split(","):
        tokens = part.strip().split()
        out.extend(t for t in tokens[1:] if not t.lstrip("-").replace(".", "", 1).isdigit())
    return out


def _handle_values(args: dict) -> list[tuple[str, str]]:
    out = []
    for key, value in (args or {}).items():
        if key not in HANDLE_PARAMS:
            continue
        values = _timeline_media(value) if key == "timeline" and isinstance(value, str) else _strings_in(value)
        for v in values:
            if len(v) >= MIN_HANDLE_LEN:
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

        # Grounding: against the question, every EARLIER output, and the parameter's OWN declared enum. The enum
        # is a legitimate source — the model is shown it with every call — so without that third source a
        # schema-declared channel name counts as invented, which is a false finding about the agent and the
        # same mistake one layer up.
        props = ((specs.get(name) or {}).get("input_schema") or {}).get("properties") or {}
        missing = [f"{k}={v}" for k, v in _handle_values(args)
                   if v not in ((props.get(k) or {}).get("enum") or ())
                   and not any(v in s for s in seen_text)]
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
