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
    "midwifery): construct the sharpest CURRENT candidate.\n"
    "Requirements for every candidate:\n"
    "- ABDUCTION: infer the best candidate explanation worth testing.\n"
    "- OPERATIONALIZE every construct onto a REAL dial label from the instrument (a channel name or species) — "
    "a construct means the operations that measure it (Bridgman). Never invent a channel.\n"
    "- State H1 (alternative) and H0 (null); the null is normally the reference design.\n"
    "- State the predicted effect with DIRECTION and rough MAGNITUDE.\n"
    "- Give a FALSIFIER as a disconfirm(target, reference, channel) spec plus a decision_rule and the concrete "
    "refuting_result — a risky prohibition that COULD fail (Popper). If no result could refute it, it is not a "
    "hypothesis.\n"
    "- Enumerate at least TWO rival hypotheses (Chamberlin/Platt), each with the distinguishing_result the sim "
    "would show if THAT rival were true.\n"
    "- List auxiliary (ceteris paribus) assumptions the test rides on (Duhem-Quine).\n"
    "- Propose at least ONE candidate Design expressible in the validated envelope (use only listed "
    "perturbations; a mid-run carbon-source switch is NOT allowed).\n"
    "You have NOT run anything: never assume an experimental result or a corpus value. Address each open "
    "objection from the skeptic explicitly (list them in addressed_objections) and revise. Emit via the tool."
)

_SKEPTIC_SYS = (
    "You are the SKEPTIC in a Socratic Council. Your stance is Socratic ignorance (docta ignorantia): assume "
    "NOTHING. You do not propose hypotheses — you produce objections (aporiai) that expose why the current "
    "candidate is not yet a rigorous, testable hypothesis. Objection types:\n"
    "- undefined_term: an equivocal word ('identical', 'behave', 'different', 'better').\n"
    "- hidden_auxiliary: an unstated ceteris paribus / Duhem-Quine assumption.\n"
    "- unfalsifiable: no risky prohibition, or a falsifier that cannot actually fail.\n"
    "- conflated_construct: two distinct things merged into one.\n"
    "- rival_not_excluded: an alternative explanation the decisive test would NOT distinguish (Platt).\n"
    "- outruns_instrument: the claim references something the dial labels cannot measure or the envelope cannot "
    "run.\n"
    "- construct_ambiguity: a genuine choice about WHICH observable/reading the user meant that you cannot "
    "resolve from the question alone — set irreducible=true and give a crisp user_question.\n"
    "Mark each objection severity 'substantive' (blocks convergence) or 'minor'. Be adversarial but fair — only "
    "objections a rigorous reviewer would raise. If the candidate is genuinely airtight, say so with no "
    "substantive objections. Emit via the tool."
)

_JUDGE_SYS = (
    "You are the JUDGE in a Socratic Council. You do NOT score who won; you apply a gate. Given the candidate "
    "hypothesis and the skeptic's objections, rule each item STRICTLY true/false:\n"
    "- falsifiable: names an observable outcome it forbids, and the falsifier could actually fail.\n"
    "- specified: independent variable (perturbation), dependent variable (observable), predicted direction AND "
    "magnitude are all present.\n"
    "- operationalized: every construct is bound to a real dial label and the falsifier is a usable "
    "disconfirm(target, reference, channel) with a decision rule.\n"
    "- discriminating: the predicted result separates the hypothesis from its named rivals (Platt strong "
    "inference).\n"
    "The 'feasible' fact is computed deterministically and given to you — do not re-derive it.\n"
    "Convergence: new_substantive_objection_this_round = did the skeptic raise a NEW substantive objection not "
    "already resolved? open_objections_resolved = are all open objections resolved or explicitly parked as "
    "stated auxiliary assumptions? Be strict: if a construct is still equivocal or the falsifier cannot fail, "
    "falsifiable/operationalized must be false. Emit via the tool."
)


# --- structured-output tool schemas ------------------------------------------------------------------------

_OD = {"type": "object", "properties": {
    "construct": {"type": "string"}, "observable": {"type": "string"}, "measure": {"type": "string"}},
    "required": ["construct", "observable", "measure"]}
_RIVAL = {"type": "object", "properties": {
    "claim": {"type": "string"}, "distinguishing_result": {"type": "string"}},
    "required": ["claim", "distinguishing_result"]}
_FALSIFIER = {"type": "object", "properties": {
    "target": {"type": "string"}, "reference": {"type": "string"}, "channel": {"type": "string"},
    "decision_rule": {"type": "string"}, "refuting_result": {"type": "string"}},
    "required": ["target", "reference", "channel", "decision_rule", "refuting_result"]}
_DESIGN = {"type": "object", "properties": {
    "perturbation": {"type": "string"}, "condition": {"type": "string"}, "timeline": {"type": "string"},
    "seeds": {"type": "integer"}, "generations": {"type": "integer"}, "params": {"type": "object"}},
    "required": ["perturbation"]}

_PROPOSE_TOOL = {
    "name": "propose_hypothesis",
    "description": "Emit the sharpest current candidate hypothesis.",
    "input_schema": {"type": "object", "properties": {
        "claim": {"type": "string", "description": "natural-language H1"},
        "h1": {"type": "string"}, "h0": {"type": "string"},
        "operational_defs": {"type": "array", "items": _OD},
        "predicted_effect": {"type": "string", "description": "direction + rough magnitude"},
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
    "description": "Emit typed objections to the candidate hypothesis.",
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


def _emit(client, model: str, system: str, tool: dict, payload: dict, *, max_tokens: int = 2048) -> dict:
    """One forced-tool call -> the validated structured input dict."""
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system, tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    return {}


# --- role calls --------------------------------------------------------------------------------------------

def _propose(client, models, question, labels, dialogue, answered, open_objections) -> dict:
    payload = {"question": question, "dial_labels": labels,
               "resolved_ambiguities": [{"question": q, "answer": a} for q, a in answered],
               "open_objections": open_objections, "prior_rounds": dialogue}
    return _emit(client, models["proposer"], _PROPOSER_SYS, _PROPOSE_TOOL, payload)


def _skeptic(client, models, question, labels, candidate, dialogue, answered) -> dict:
    payload = {"question": question, "channels": instrument.channel_names(),
               "perturbations": sorted(labels.get("perturbations", {})),
               "resolved_ambiguities": [{"question": q, "answer": a} for q, a in answered],
               "candidate": candidate, "prior_rounds": dialogue}
    return _emit(client, models["skeptic"], _SKEPTIC_SYS, _SKEPTIC_TOOL, payload)


def _judge(client, models, question, labels, candidate, objections, feasible_code, dialogue) -> dict:
    payload = {"question": question, "candidate": candidate, "objections": objections,
               "feasible": feasible_code, "channels": instrument.channel_names(), "prior_rounds": dialogue}
    return _emit(client, models["judge"], _JUDGE_SYS, _JUDGE_TOOL, payload)


# --- assembly + gates --------------------------------------------------------------------------------------

_DESIGN_KEYS = {"perturbation", "condition", "timeline", "seeds", "generations", "params"}


def _to_design(d: dict) -> Design | None:
    clean = {k: v for k, v in (d or {}).items() if k in _DESIGN_KEYS and v is not None}
    if "params" in clean and not isinstance(clean["params"], dict):
        clean.pop("params")
    try:
        return Design(**clean)
    except Exception:
        return None


def _structural_ok(cand: dict) -> bool:
    """Deterministic structural floor, independent of the judge's semantic call."""
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

    dialogue: list[dict] = []
    answered: list[tuple[str, str]] = []
    parked: set[str] = set()
    open_objections: list[dict] = []
    total_substantive = 0
    last: dict = {}

    for rnd in range(max_rounds):
        cand = _propose(client, models, question, labels, dialogue, answered, open_objections)
        feasible_code = _feasible(cand)
        if verbose:
            print(f"  · round {rnd + 1}: proposer -> {cand.get('claim', '')[:90]}")

        objs = _skeptic(client, models, question, labels, cand, dialogue, answered)
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
                dialogue.append({"round": rnd, "candidate": cand, "objections": objections, "asked": [q, ans]})
                open_objections = objections
                continue
            parked.add(f"[construct_ambiguity] {q}")  # non-interactive: cannot resolve, park it

        verdict = _judge(client, models, question, labels, cand, objections, feasible_code, dialogue)
        adequate = all([verdict.get("falsifiable"), verdict.get("specified"),
                        verdict.get("operationalized"), verdict.get("discriminating"), feasible_code])
        converged_signal = (not verdict.get("new_substantive_objection_this_round")
                            and verdict.get("open_objections_resolved"))
        structural = _structural_ok(cand)
        if verbose:
            print(f"    judge -> adequate={adequate} converged={converged_signal} "
                  f"quota={total_substantive}/{quota} feasible={feasible_code}")

        dialogue.append({"round": rnd, "candidate": cand, "objections": objections, "verdict": verdict})
        open_objections = objections
        last = {"cand": cand, "adequate": adequate, "structural": structural,
                "converged_signal": converged_signal}

        if adequate and converged_signal and structural and not parked and total_substantive >= quota:
            return _assemble(question, cand, residual=[], converged=True)

    # Round cap — return best-effort. Treat it as clean only if the LAST round was itself adequate, structurally
    # sound, and quiet (the convergence signal held) with nothing parked; the only thing unmet is then the quota
    # of doubt — i.e. the skeptic simply could not surface N substantive objections against a hypothesis that
    # withstood the full debate. If the skeptic was still objecting at the cap, it is NOT clean.
    residual = _residual(open_objections, parked)
    clean = bool(last.get("adequate") and last.get("structural") and last.get("converged_signal")) and not parked
    return _assemble(question, last.get("cand", {}),
                     residual=([] if clean else (residual or ["reached round cap without full convergence"])),
                     converged=clean)
