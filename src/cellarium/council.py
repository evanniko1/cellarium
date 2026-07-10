"""The Socratic Council — the upstream front stage (docs/SOCRATIC_COUNCIL.md).

Turns a vague user question into ONE falsifiable, operationalized, instrumentally-testable Hypothesis before
the grounded Cellarium agent runs. Three roles debate:

  * PROPOSER (maieutic / Socratic midwifery): abduction -> a candidate hypothesis, operationalized onto real
    dial labels, with a falsifier, rivals, and auxiliary assumptions. Moves toward commitment.
  * SKEPTIC (docta ignorantia / Socratic ignorance): assumes nothing; emits typed objections (aporiai).
    Moves toward doubt.
  * JUDGE: a gate, not a scorer. Terminates iff the adequacy rubric (A) AND the convergence signal (B) hold,
    with a code-enforced quota of doubt and deterministic feasibility.

The Council sees only instrument.dial_labels() (capabilities, never readings — the D2/D4 quarantine). On an
irreducible construct ambiguity it asks the user (D3). Loop constants default to max_rounds=4, quota=3 (D5).

Each role receives only a COMPACT view (the previous candidate + the open objections), not the whole growing
transcript — this keeps structured outputs from truncating and makes the debate cheap. The Council returns the
BEST complete candidate it reached, not merely the last (a late round can degenerate).
"""

from __future__ import annotations

import json
import os
from typing import Callable

from . import instrument
from .hypothesis import Falsifier, Hypothesis, OperationalDef, Rival
from .model import Design

OBJECTION_TYPES = ["undefined_term", "hidden_auxiliary", "unfalsifiable", "conflated_construct",
                   "rival_not_excluded", "outruns_instrument", "construct_ambiguity"]


# --- role charters -----------------------------------------------------------------------------------------

_PROPOSER_SYS = (
    "You are the PROPOSER in a Socratic Council that turns a vague research question into ONE falsifiable, "
    "operationalized hypothesis testable on a whole-cell E. coli simulation. Your stance is maieutic (Socratic "
    "midwifery): construct the sharpest CURRENT candidate. You are usually REVISING a previous_candidate to "
    "address open_objections — preserve everything that already works and return a COMPLETE hypothesis EVERY "
    "time (never omit a required field, even mid-revision).\n"
    "Every candidate must:\n"
    "- ABDUCTION: infer the best candidate explanation worth testing.\n"
    "- OPERATIONALIZE every construct onto a REAL dial label (a channel name from the instrument, or a named "
    "species) — a construct means the operations that measure it (Bridgman). Never invent a channel.\n"
    "- State H1 (alternative) and H0 (null); the null is normally the reference design.\n"
    "- Fill predicted_effect with an explicit DIRECTION and a rough MAGNITUDE (a number: a CV, a fold-change, a "
    "slope, a %, a copy-number). Never leave it empty.\n"
    "- Give a FALSIFIER that is a risky prohibition able to FAIL (Popper). falsifier.target and "
    "falsifier.reference MUST be design LABELS of the form 'perturbation/condition' that correspond to entries "
    "in candidate_designs — NOT prose. falsifier.channel MUST be one of the instrument's summary channels. "
    "decision_rule names the statistic + threshold; refuting_result is the concrete outcome that would refute "
    "H1.\n"
    "- candidate_designs MUST be STRUCTURED objects (perturbation/condition/timeline/seeds/generations/params) "
    "expressible in the validated envelope (only listed perturbations; a mid-run carbon-source switch is NOT "
    "allowed). Put the experiment HERE, not in prose inside the falsifier.\n"
    "- Enumerate at least TWO rival hypotheses (Chamberlin/Platt), each with the distinguishing_result the sim "
    "would show if THAT rival were true.\n"
    "- List auxiliary (ceteris paribus) assumptions the test rides on (Duhem-Quine). For a concern the "
    "SIMULATOR cannot resolve (deterministic chaos vs stochastic noise; a mutant's confounded basal physiology; "
    "a readout the model does not compute), do NOT chase it forever — record it as an explicit "
    "auxiliary_assumption / scope caveat and move on.\n"
    "You have NOT run anything: never assume an experimental result or a corpus value. Emit via the tool."
)

_SKEPTIC_SYS = (
    "You are the SKEPTIC in a Socratic Council. Your stance is Socratic ignorance (docta ignorantia): assume "
    "NOTHING. You do not propose hypotheses — you produce objections (aporiai) that expose why the candidate is "
    "not yet a rigorous, testable hypothesis. Objection types:\n"
    "- undefined_term: an equivocal word ('identical', 'behave', 'different', 'better').\n"
    "- hidden_auxiliary: an unstated ceteris paribus / Duhem-Quine assumption.\n"
    "- unfalsifiable: no risky prohibition, or a falsifier that cannot actually fail.\n"
    "- conflated_construct: two distinct things merged into one.\n"
    "- rival_not_excluded: an alternative explanation the decisive test would NOT distinguish (Platt).\n"
    "- outruns_instrument: the claim references something the dial labels cannot measure or the envelope cannot "
    "run.\n"
    "- construct_ambiguity: a genuine choice about WHICH observable/reading the user meant that you cannot "
    "resolve from the question alone — set irreducible=true and give a crisp user_question.\n"
    "DISCIPLINE (critical): raise AT MOST 3 objections — the most decisive. Do NOT re-raise anything already "
    "addressed in previous_candidate, already parked as a stated auxiliary_assumption, or already answered in "
    "resolved_ambiguities. A concern the instrument genuinely cannot resolve is type outruns_instrument, raised "
    "AT MOST ONCE as 'minor' with the suggestion to state it as an auxiliary assumption — never re-raise it as "
    "substantive across rounds. If the candidate satisfies the rubric, return an EMPTY objections list: silence "
    "is the correct output for an adequate hypothesis. Mark each objection severity 'substantive' (blocks "
    "convergence) or 'minor'. Emit via the tool."
)

_JUDGE_SYS = (
    "You are the JUDGE in a Socratic Council. You do NOT score who won; you apply a gate. Given the candidate "
    "hypothesis and the skeptic's objections, rule each item STRICTLY true/false:\n"
    "- falsifiable: names an observable outcome it forbids, and the falsifier could actually fail.\n"
    "- specified: independent variable (perturbation), dependent variable (observable), predicted direction AND "
    "magnitude are all present.\n"
    "- operationalized: every construct is bound to a real dial label and the falsifier is a usable "
    "disconfirm(target, reference, channel) with a decision rule.\n"
    "- discriminating: the predicted result separates the hypothesis from its named rivals (Platt).\n"
    "The 'feasible' fact is computed deterministically and given to you — do not re-derive it.\n"
    "Convergence: an objection is RESOLVED if the proposer either FIXED it OR explicitly parked it as a stated "
    "auxiliary_assumption / scope limitation. open_objections_resolved = true when EVERY open objection is "
    "resolved in one of those two senses (an instrument-exceeding concern acknowledged as an auxiliary "
    "assumption counts as resolved). new_substantive_objection_this_round = true only if the skeptic raised a "
    "NEW substantive objection this round that is neither addressed nor parked. Be strict on the rubric but do "
    "not demand the impossible: a hypothesis that is falsifiable, specified, operationalized, discriminating, "
    "feasible, and whose remaining objections are all parked as stated assumptions SHOULD converge. Emit via "
    "the tool."
)


# --- structured-output tool schemas ------------------------------------------------------------------------

_OD = {"type": "object", "properties": {
    "construct": {"type": "string"}, "observable": {"type": "string"}, "measure": {"type": "string"}},
    "required": ["construct", "observable", "measure"]}
_RIVAL = {"type": "object", "properties": {
    "claim": {"type": "string"}, "distinguishing_result": {"type": "string"}},
    "required": ["claim", "distinguishing_result"]}
_FALSIFIER = {"type": "object", "properties": {
    "target": {"type": "string", "description": "a design label 'perturbation/condition' in candidate_designs"},
    "reference": {"type": "string", "description": "the null/baseline design label"},
    "channel": {"type": "string", "description": "one instrument summary channel"},
    "decision_rule": {"type": "string"}, "refuting_result": {"type": "string"}},
    "required": ["target", "reference", "channel", "decision_rule", "refuting_result"]}
_DESIGN = {"type": "object", "properties": {
    "perturbation": {"type": "string"}, "condition": {"type": "string"}, "timeline": {"type": "string"},
    "seeds": {"type": "integer"}, "generations": {"type": "integer"}, "params": {"type": "object"}},
    "required": ["perturbation"]}

_PROPOSE_TOOL = {
    "name": "propose_hypothesis",
    "description": "Emit the sharpest current candidate hypothesis — always complete.",
    "input_schema": {"type": "object", "properties": {
        "claim": {"type": "string", "description": "natural-language H1"},
        "h1": {"type": "string"}, "h0": {"type": "string"},
        "operational_defs": {"type": "array", "items": _OD},
        "predicted_effect": {"type": "string", "description": "explicit direction + rough magnitude (a number)"},
        "falsifier": _FALSIFIER,
        "rivals": {"type": "array", "items": _RIVAL},
        "auxiliary_assumptions": {"type": "array", "items": {"type": "string"}},
        "candidate_designs": {"type": "array", "items": _DESIGN},
        "addressed_objections": {"type": "array", "items": {"type": "string"}},
    }, "required": ["claim", "h1", "h0", "operational_defs", "predicted_effect", "falsifier", "rivals",
                    "candidate_designs"]},
}

_SKEPTIC_TOOL = {
    "name": "raise_objections",
    "description": "Emit at most 3 typed objections (or none if the candidate is adequate).",
    "input_schema": {"type": "object", "properties": {
        "objections": {"type": "array", "items": {"type": "object", "properties": {
            "type": {"type": "string", "enum": OBJECTION_TYPES},
            "issue": {"type": "string"},
            "severity": {"type": "string", "enum": ["substantive", "minor"]},
            "irreducible": {"type": "boolean"},
            "user_question": {"type": "string"},
        }, "required": ["type", "issue", "severity"]}},
        "assessment": {"type": "string"},
    }, "required": ["objections"]},
}

_JUDGE_TOOL = {
    "name": "rule",
    "description": "Rule on the adequacy rubric and the convergence signal.",
    "input_schema": {"type": "object", "properties": {
        "falsifiable": {"type": "boolean"}, "specified": {"type": "boolean"},
        "operationalized": {"type": "boolean"}, "discriminating": {"type": "boolean"},
        "new_substantive_objection_this_round": {"type": "boolean"},
        "open_objections_resolved": {"type": "boolean"},
        "rationale": {"type": "string"},
    }, "required": ["falsifiable", "specified", "operationalized", "discriminating",
                    "new_substantive_objection_this_round", "open_objections_resolved"]},
}


# --- LLM plumbing ------------------------------------------------------------------------------------------

def _default_models() -> dict:
    base = os.environ.get("CELLARIUM_MODEL") or "claude-sonnet-4-5"
    return {"proposer": os.environ.get("CELLARIUM_PROPOSER_MODEL") or base,
            "skeptic": os.environ.get("CELLARIUM_SKEPTIC_MODEL") or base,
            "judge": os.environ.get("CELLARIUM_JUDGE_MODEL") or base}


def _emit(client, model: str, system: str, tool: dict, payload: dict, *, max_tokens: int = 3072) -> dict:
    """One forced-tool call -> the validated structured input dict. Retries once if the tool input comes back
    empty (a rare truncation/degenerate emit)."""
    for _ in range(2):
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.input:
                return dict(block.input)
    return {}


# --- role calls (compact payloads — no growing transcript) --------------------------------------------------

def _propose(client, models, question, labels, previous_candidate, open_objections, answered) -> dict:
    payload = {"question": question, "dial_labels": labels,
               "resolved_ambiguities": [{"question": q, "answer": a} for q, a in answered],
               "previous_candidate": previous_candidate, "open_objections": open_objections,
               "instruction": "Revise previous_candidate to resolve open_objections; keep what already works; "
                              "return a COMPLETE hypothesis."}
    return _emit(client, models["proposer"], _PROPOSER_SYS, _PROPOSE_TOOL, payload, max_tokens=4096)


def _skeptic(client, models, question, labels, candidate, answered) -> dict:
    payload = {"question": question, "channels": instrument.channel_names(),
               "perturbations": sorted(labels.get("perturbations", {})),
               "resolved_ambiguities": [{"question": q, "answer": a} for q, a in answered],
               "candidate": candidate}
    return _emit(client, models["skeptic"], _SKEPTIC_SYS, _SKEPTIC_TOOL, payload, max_tokens=2048)


def _judge(client, models, question, candidate, objections, feasible_code) -> dict:
    payload = {"question": question, "candidate": candidate, "objections": objections,
               "feasible": feasible_code, "channels": instrument.channel_names()}
    return _emit(client, models["judge"], _JUDGE_SYS, _JUDGE_TOOL, payload, max_tokens=1536)


# --- assembly + gates --------------------------------------------------------------------------------------

_DESIGN_KEYS = {"perturbation", "condition", "timeline", "seeds", "generations", "params"}


def _to_design(d: dict) -> Design | None:
    if not isinstance(d, dict):
        return None  # a proposer sometimes emits a design as a bare string — not usable
    clean = {k: v for k, v in d.items() if k in _DESIGN_KEYS and v is not None}
    if "params" in clean and not isinstance(clean["params"], dict):
        clean.pop("params")
    try:
        return Design(**clean)
    except Exception:
        return None


def _complete(cand: dict) -> bool:
    """A structurally usable candidate — used to guard against degenerate/truncated emits and to score 'best'."""
    if not cand:
        return False
    f = cand.get("falsifier") or {}
    return bool(cand.get("claim") and cand.get("h1") and cand.get("h0") and cand.get("predicted_effect")
                and cand.get("operational_defs") and len(cand.get("rivals") or []) >= 2
                and f.get("target") and f.get("reference") and f.get("channel") and f.get("refuting_result"))


def _structural_ok(cand: dict) -> bool:
    f = cand.get("falsifier") or {}
    return bool(cand.get("claim") and cand.get("h1") and cand.get("h0")
                and cand.get("operational_defs") and cand.get("rivals")
                and f.get("target") and f.get("reference") and f.get("channel"))


def _feasible(cand: dict) -> bool:
    designs = [d for d in (_to_design(x) for x in cand.get("candidate_designs", [])) if d]
    return any(instrument.check_design(d)["usable"] for d in designs)


def _assemble(question: str, cand: dict, residual: list[str], converged: bool) -> Hypothesis:
    cand = cand or {}
    ods = [OperationalDef(**o) for o in cand.get("operational_defs", []) if isinstance(o, dict)]
    rivals = [Rival(**r) for r in cand.get("rivals", []) if isinstance(r, dict)]
    fal = cand.get("falsifier")
    falsifier = None
    if isinstance(fal, dict):
        try:
            falsifier = Falsifier(**{k: fal.get(k, "") for k in
                                     ("target", "reference", "channel", "decision_rule", "refuting_result")})
        except Exception:
            falsifier = None
    designs = [d for d in (_to_design(x) for x in cand.get("candidate_designs", [])) if d]
    return Hypothesis(
        question=question, claim=cand.get("claim", ""), h1=cand.get("h1", ""), h0=cand.get("h0", ""),
        operational_defs=ods, predicted_effect=cand.get("predicted_effect", ""), falsifier=falsifier,
        rivals=rivals, auxiliary_assumptions=list(cand.get("auxiliary_assumptions", []) or []),
        candidate_designs=designs, residual_ambiguities=residual, converged=converged,
    )


def _residual(open_objections: list, parked: set) -> list[str]:
    out = list(parked)
    for o in open_objections or []:
        if o.get("severity") == "substantive":
            out.append(f"[{o.get('type')}] {o.get('issue')}")
    return out


def _score(cand: dict, feasible: bool, verdict: dict) -> int:
    """Rank complete candidates so the round-cap fallback returns the best one, not the last."""
    rubric = sum(bool(verdict.get(k)) for k in ("falsifiable", "specified", "operationalized", "discriminating"))
    return (8 if _complete(cand) else 0) + (4 if feasible else 0) + rubric


# --- the loop ----------------------------------------------------------------------------------------------

def deliberate(question: str, *, max_rounds: int = 4, quota: int = 3,
               ask_user: Callable[[str], str] | None = None, client=None, models: dict | None = None,
               labels: dict | None = None, verbose: bool = True) -> Hypothesis:
    """Run the elenchus and return a justification-ready Hypothesis (see module docstring)."""
    labels = labels if labels is not None else instrument.dial_labels()
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    models = models or _default_models()

    answered: list[tuple[str, str]] = []
    parked: set[str] = set()
    open_objections: list[dict] = []
    total_substantive = 0
    previous_candidate: dict | None = None
    best: dict = {}
    best_score = -1

    for rnd in range(max_rounds):
        cand = _propose(client, models, question, labels, previous_candidate, open_objections, answered)
        if not _complete(cand) and _complete(previous_candidate or {}):
            cand = previous_candidate  # guard: never regress to a degenerate/truncated emit
        previous_candidate = cand
        feasible_code = _feasible(cand)
        if verbose:
            print(f"  · round {rnd + 1}: proposer -> {cand.get('claim', '')[:90]}")

        objs = _skeptic(client, models, question, labels, cand, answered)
        objections = objs.get("objections", []) or []
        substantive = [o for o in objections if o.get("severity") == "substantive"]
        total_substantive += len(substantive)
        if verbose:
            print(f"    skeptic -> {len(objections)} objections ({len(substantive)} substantive, "
                  f"{total_substantive} cumulative)")

        # D3 escalation: an irreducible construct ambiguity we haven't already resolved
        asked_qs = {q for q, _ in answered}
        amb = next((o for o in objections if o.get("type") == "construct_ambiguity" and o.get("irreducible")
                    and (o.get("user_question") or o.get("issue")) not in asked_qs), None)
        if amb is not None:
            q = amb.get("user_question") or amb.get("issue")
            if ask_user is not None:
                ans = ask_user(q)
                answered.append((q, ans))
                open_objections = objections
                continue
            parked.add(f"[construct_ambiguity] {q}")  # non-interactive: cannot resolve, park it

        verdict = _judge(client, models, question, cand, objections, feasible_code)
        adequate = all([verdict.get("falsifiable"), verdict.get("specified"),
                        verdict.get("operationalized"), verdict.get("discriminating"), feasible_code])
        converged_signal = (not verdict.get("new_substantive_objection_this_round")
                            and verdict.get("open_objections_resolved"))
        structural = _structural_ok(cand)
        if verbose:
            print(f"    judge -> adequate={adequate} converged={converged_signal} "
                  f"quota={total_substantive}/{quota} feasible={feasible_code}")

        open_objections = objections
        score = _score(cand, feasible_code, verdict)
        if score > best_score:
            best, best_score = cand, score

        if adequate and converged_signal and structural and not parked and total_substantive >= quota:
            return _assemble(question, cand, residual=[], converged=True)

    # Round cap — return the BEST complete candidate reached (not a possibly-degenerate last one), flagged as
    # not-cleanly-converged with the residual substantive objections / parked ambiguities.
    final = best if best else (previous_candidate or {})
    residual = _residual(open_objections, parked) or ["reached round cap without full convergence"]
    return _assemble(question, final, residual=residual, converged=False)
