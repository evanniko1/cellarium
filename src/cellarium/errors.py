"""One closed taxonomy for every tool error, so an agent can branch on the CAUSE instead of reading prose.

WHY. The option-A discovery leg failed four times in one day by treating a fault in the environment as a fact
about the biology: an unreadable store became "n = 0, genuinely absent"; an empty gene map became "INVALID"; a
test with three seeds became "no response". Each tool had said something true in English — "corpus unreadable",
"no local raw simOut", "need >= 3 generations" — and the model, facing 140 distinct sentences of that kind
across 223 error sites in 31 modules, had nothing to branch on. The four conformance families (`conformance.py`) catch the cases where a tool reports
absence as a measurement. This module is the other half: when a tool DOES refuse, the refusal has to say what
KIND of refusal it is.

The contract. Every error result carries three machine-readable fields beside its message:

  reason      one of REASONS: what went wrong, from a closed set.
  about       `request` | `corpus` | `environment` | `policy` — WHOSE fault it is. This is the field that
              answers the question the discovery leg got wrong. `corpus` means the corpus genuinely does not
              contain this; `environment` means this machine could not look. Only the first is evidence.
  next_step   what would make the call work: fix the argument, run more, use another tool, or nothing.

Published practice this follows, and where it goes further:
  - MCP's tools specification gives two error mechanisms: a PROTOCOL error (unknown tool, invalid arguments,
    server error) and a TOOL EXECUTION error, carried inside the result as `isError: true` so the model can read
    and act on it, with `structuredContent` beside the prose. `reason` here is that structured payload.
  - MCP's split is by WHERE the failure happened. It does not distinguish "the corpus genuinely lacks this" from
    "this machine could not look" — both are execution errors. That distinction is the one four discovery-leg
    failures turned on, so `about` is Cellarium's own refinement, not a quotation.
  - Anthropic, "Writing effective tools for agents": an error should steer the agent to the correct call. That is
    `next_step`, and it is why `did_you_mean` accompanies an argument error.
  - Anthropic, "Demystifying evals for AI agents": an environment fault must not be scored as a model answer.
    `about == "environment"` is the machine-readable form of that rule.
  - TRAJECT-Bench (He et al., ICLR 2026) makes argument correctness a first-class evaluation axis and names
    "parameter-blind selection" as a failure mode; an unresolvable argument therefore has to come back as an
    argument error, distinct from an empty result.

A RETROFIT, AND HONEST ABOUT IT. There are 223 error sites across 31 modules. Rather than edit all of them,
the taxonomy is applied at one boundary (`tools.dispatch` calls `annotate`) from a registered pattern table, and
new code calls `fail()` to set the reason directly. A message no pattern matches is reported as
`reason: "unclassified"`, and the conformance sweep FAILS on it — so the table cannot fall behind the code.
"""
from __future__ import annotations

import re

# reason -> (about, next_step). `about` is the field that decides whether a refusal is evidence.
REASONS: dict[str, tuple[str, str]] = {
    # the caller asked for something that does not exist, or asked wrongly
    "unknown_design": ("request", "fix_argument"),
    "unknown_reference": ("request", "fix_argument"),
    "unknown_result_id": ("request", "fix_argument"),
    "ambiguous_result_id": ("request", "fix_argument"),
    "unknown_gene": ("request", "fix_argument"),
    "unknown_entity": ("request", "fix_argument"),   # a named reaction, metabolite, regulon, skill, capability
    "unknown_tool": ("request", "fix_argument"),
    "bad_argument": ("request", "fix_argument"),
    # Separate from `bad_argument` on purpose: the remedy differs in kind. `bad_argument` means "the value you
    # sent cannot be used" -- change it. `missing_argument` means "you sent no value for a field the contract
    # declares required" -- supply one. Both are `request`, which is the half that matters; the reason code is
    # what tells the agent which of the two it is without parsing the message.
    "missing_argument": ("request", "fix_argument"),
    # A fact the tool needs IS recorded somewhere, but not in the one place the tool reads. The caller can fix
    # it by supplying the value, so it is a `request` fault with a caller-side remedy -- and emphatically NOT
    # `corpus`, because "the design has no shift" was the wrong half of what the old message said.
    "shift_time_not_declared": ("request", "fix_argument"),
    # the corpus is readable and genuinely does not carry what was asked for. THIS is the only kind that is
    # evidence about the model, and even then only about coverage.
    "channel_not_recorded": ("corpus", "use_another_channel"),
    "not_applicable_to_design": ("corpus", "use_another_design"),
    "insufficient_data": ("corpus", "run_more"),
    # this machine could not look. Never evidence.
    "store_unreadable": ("environment", "repair_environment"),
    "no_local_raw": ("environment", "use_another_tool_or_download"),
    "missing_artifact": ("environment", "build_artifact"),
    "missing_dependency": ("environment", "install_dependency"),
    "runtime_fault": ("environment", "report_defect"),
    # a deliberate refusal: a guard did its job. Not a fault at all.
    "refused_by_policy": ("policy", "none"),
    # the table does not yet cover this message. A sweep failure, not a usable answer.
    "unclassified": ("environment", "register_the_reason"),
}

# Ordered: the first pattern that matches wins, so narrow phrasings come before broad ones.
PATTERNS: list[tuple[re.Pattern, str]] = [(re.compile(p, re.I), r) for p, r in [
    # --- first, because it is the narrowest phrasing in the table and the only one raised BEFORE the tool ran.
    # Its message interpolates argument names, and an argument could be called anything ("raw_path", "no_cache"),
    # so leaving it lower down would let a pattern written for the environment match on a field name. A fault
    # detected by the schema pre-check cannot be anything but the caller's. ---
    (r"missing required argument", "missing_argument"),
    # --- deliberate refusals, next: several of them contain the word "no" or "not" ---
    (r"safety-?blocked|refus(ing|ed) to|needs a reason|only a pending draft|not pending_approval"
     r"|biosecurity|is (not available|write-gated) over MCP|only in unattended mode"
     r"|not listed on this surface|is not fetchable|are not permitted", "refused_by_policy"),
    # --- the environment ---
    (r"corpus (is )?(unreadable|empty)|no manifest\b|store unreadable|manifest .*unreadable"
     r"|corpus query failed", "store_unreadable"),
    (r"no (local )?raw( simOut)?|no simOut|missing simOut|no readable .* trajectory"
     r"|full simOut not available|needs the run director|could not be read \(no "
     r"|reachable by the reader container", "no_local_raw"),
    (r"not installed", "missing_dependency"),
    (r"no sim_data|no (frozen )?(degradation|invariant)|no kb found|catalogue is unreadable"
     r"|baseline unreadable|baseline at |alias map (at|unreadable)|carries no aliases|no .* shards"
     r"|cache missing|needs the Parquet manifest|no viability columns|to backfill", "missing_artifact"),
    (r"^\w+ failed: |internal_defect|^\w*(Error|Exception|Warning): |produced no JSON|^HTTP \d"
     r"|did not land \d", "runtime_fault"),
    # --- the request ---
    (r"unknown tool", "unknown_tool"),
    (r"unknown (argument|variant|mode|normalise|regulon|skill)|bad arguments for|must be (one of|'|a |non|>=)"
     r"|expected one of|^need \w+=|, got |give result_id|use 'median'|needs a (design label|non-empty)"
     r"|takes no hyper-parameter|has no hyper-parameter|invalid channel name|matches 0 arms"
     r"|no perturbation '", "bad_argument"),
    (r"maps to \d+ distinct runs", "ambiguous_result_id"),
    (r"no result '|no run with id|no request '|is neither a result_id nor a design", "unknown_result_id"),
    (r"no reference '|no local runs for reference", "unknown_reference"),
    (r"is not a design in the corpus|no design '|no local runs for (design|target)|no runs match|no runs for"
     r"|has no species profile|no seeds for this design|could not resolve any of", "unknown_design"),
    (r"names no gene|no iML1515 gene matched|are iML1515 reactions|resolvable iML1515 genes"
     r"|could not infer the target gene|not in the scope map|has no monomer in the model", "unknown_gene"),
    (r"no exchange reaction matched|is not a declared (capability|elongation model)", "unknown_entity"),
    # --- the corpus, read successfully, does not carry it ---
    (r"not stored per generation|no raw mapping|not a manifest column|not recorded"
     r"|channel '[^']*' unavailable|no .* trajectory for those runs", "channel_not_recorded"),
    (r"declares no nutrient shift|does not apply to|not in the arm currently selected",
     "not_applicable_to_design"),
    (r"need (>=|at least)|fewer than|at least \d|^pool has|could not (fit|characterise)"
     r"|cannot estimate noise|no shared generation depth|no .* values for|do not overlap enough"
     r"|folds did not align|underpowered|no comparable wild-type pairs|no shared families"
     r"|has <\d+ replicates", "insufficient_data"),
    (r"not found in ", "channel_not_recorded"),
]]


def classify(message: str) -> str:
    """The reason code for one error message, or 'unclassified'."""
    for pat, reason in PATTERNS:
        if pat.search(message or ""):
            return reason
    return "unclassified"


def fail(reason: str, message: str, **extra) -> dict:
    """Build an error result with the contract attached. Preferred over a bare {"error": ...} in new code."""
    if reason not in REASONS:
        raise KeyError(f"unregistered error reason {reason!r}; add it to errors.REASONS with its `about`")
    about, nxt = REASONS[reason]
    return {"error": message, "reason": reason, "about": about, "next_step": nxt, **extra}


def annotate(out):
    """Attach the contract to any result that carries an `error`, in place of nothing. Results that already name
    a reason keep it; everything else is classified from its message. Non-dict and error-free results pass
    through untouched, so this is safe to put on the dispatch path for all 73 tools."""
    # A STRING under `error` is a refusal. A number is a statistic (a standard error, a residual), and
    # classifying one would attach a cause to a measurement — the inverse of the mistake this module prevents.
    if not isinstance(out, dict) or not isinstance(out.get("error"), str):
        return out
    reason = out.get("reason")
    if reason not in REASONS:
        # A tool may legitimately use `reason` for prose (check_feasibility explains its verdict there). Keep the
        # prose under `reason_note` rather than dropping it, and classify as usual.
        if reason is not None:
            out = {**out, "reason_note": reason}
        reason = classify(str(out.get("error", "")))
    about, nxt = REASONS[reason]
    return {**out, "reason": reason, "about": about, "next_step": out.get("next_step", nxt)}
