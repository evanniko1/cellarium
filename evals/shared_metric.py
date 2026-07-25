"""PUB-A1: the ONE metric both arms are scored on.

The problem this fixes. `run_ab.py` ran two arms and graded only one of them. Arm B (the blind Socratic Council)
was scored against each case's literature rubric by an independent judge; Arm A (grounded Cellwright) got
`corpus_reads`, `answer_chars` and tool-error counts — useful process telemetry, but nothing comparable. So the
headline "Council vs Cellwright" comparison had no shared quality axis at all: the two arms were never scored on
the same thing. Everything here exists to make one number, `quality_score`, that means the same for both.

Three properties it has to have, and how each is enforced:

  1. SAME RUBRIC. Both arms are judged against the identical per-case `min_criteria` + `stringent_criteria` from
     evals/cases.py, by the same judge model, with the same system prompt.

  2. BLIND TO THE ARM. The payload carries a single `candidate_answer` string and nothing that identifies its
     origin — no arm label, no structured Hypothesis JSON, no field whose presence implies a producer. This is
     the load-bearing property. Arm B emits a structured artifact and Arm A emits prose; a judge that could tell
     them apart would be free to reward the FORMAT rather than the science, and the whole comparison would
     measure presentation. `payload()` is pure and tested for exactly this.

  3. FORMAT-NEUTRAL PROMPT. The judge is asked about "a candidate answer", never "a hypothesis" — the wording the
     Arm-B-only grader in evals/grade.py uses. Grading Arm A's prose with a hypothesis-shaped prompt would import
     the same bias through the back door.

WHAT THIS METRIC DOES NOT FIX — read before quoting a number from it. The two arms are given DIFFERENT TASK
FRAMINGS: the Council is asked to produce a falsifiable hypothesis, Cellwright is asked to answer the question.
The rubric is hypothesis-shaped (named observable, direction, baseline, falsifier), so an unmatched run partly
measures framing rather than capability. `run_ab.py --matched-framing` gives Arm A the same instruction and is
the comparison to quote; the unmatched run is the honest, framing-confounded baseline. Say which one a reported
number came from.

Also NOT shared: `grade.deterministic()` — those are structural checks on a `Hypothesis` OBJECT, which Arm A
never produces. It stays an Arm-B-only diagnostic and is deliberately excluded from `quality_score`. Folding it
in would be the exact unfairness this module exists to remove.
"""

from __future__ import annotations

import json

# The instruction that makes the two arms comparable when --matched-framing is on: it asks Cellwright for the
# same ARTIFACT SHAPE the Council is asked for, without telling it anything about the rubric or the answer.
MATCHED_FRAMING = (
    "\n\nState your conclusion as a falsifiable hypothesis: name the specific observable you would measure, the "
    "direction you expect it to move, the baseline or reference condition you would compare against, and the "
    "result that would REFUTE you. Also name at least one rival explanation."
)

_JUDGE_TOOL = {
    "name": "grade",
    "description": "Grade the candidate answer against each rubric criterion.",
    "input_schema": {"type": "object", "properties": {
        "min_criteria": {"type": "array", "items": {"type": "object", "properties": {
            "criterion": {"type": "string"}, "passed": {"type": "boolean"}, "rationale": {"type": "string"}},
            "required": ["criterion", "passed", "rationale"]}},
        "stringent_criteria": {"type": "array", "items": {"type": "object", "properties": {
            "criterion": {"type": "string"}, "passed": {"type": "boolean"}, "rationale": {"type": "string"}},
            "required": ["criterion", "passed", "rationale"]}},
        "comment": {"type": "string"},
    }, "required": ["min_criteria", "stringent_criteria"]},
}

# Arm-agnostic by construction: "candidate answer", never "hypothesis". The explicit instruction to ignore form
# is there because the two arms genuinely differ in presentation and we are measuring the science, not the shape.
_JUDGE_SYS = (
    "You are a rigorous peer reviewer grading whether a candidate answer to a scientific question meets a rubric "
    "derived from the seminal literature. You SEE the canonical answer and the expected observables/rivals; the "
    "system that produced the candidate did NOT. Grade each listed criterion strictly true/false with a one-line "
    "rationale. A criterion passes only if the candidate genuinely satisfies it — do not give credit for vague "
    "gestures. Judge CONTENT, not presentation: a criterion is satisfied whether the candidate states it in prose "
    "or in a structured form, and a well-formatted answer that does not actually meet the criterion fails it. "
    "Reward operationalization onto the whole-cell E. coli simulation's real observables; a readout the base "
    "model cannot execute (flagged in scope_note) is acceptable only if the candidate maps the construct to an "
    "in-model proxy. Emit via the grade tool, echoing each criterion string verbatim."
)


# ---------------------------------------------------------------- normalization (pure)
def from_council(h) -> str:
    """Arm B's artifact as plain text. `brief()` is the Council's own prose rendering, so nothing is added or
    summarized here — using the structured model_dump instead would hand the judge a format tell."""
    if h is None:
        return ""
    brief = getattr(h, "brief", None)
    if callable(brief):
        return str(brief() or "")
    if isinstance(h, dict):                      # a persisted hypothesis_view (ui.hypothesis_view)
        parts = [str(h.get(k) or "") for k in ("claim", "predicted_effect", "rationale")]
        rivals = h.get("rivals") or []
        if rivals:
            parts.append("Rivals: " + "; ".join(str(r) for r in rivals))
        return "\n".join(p for p in parts if p)
    return str(h)


def from_agent(answer: str | None) -> str:
    """Arm A's artifact as plain text — its final synthesis, verbatim."""
    return str(answer or "")


# ---------------------------------------------------------------- the judge payload (pure, and blind)
def payload(case: dict, candidate_answer: str) -> dict:
    """Exactly what the judge sees. No arm label, no producer-identifying field — see property 2 in the module
    docstring. Kept pure so a test can assert the blinding without spending an API call."""
    return {
        "question": case["question"],
        "canonical_answer": case["canonical"],
        "expected_observables": case["expected_observables"],
        "expected_rivals": case["expected_rivals"],
        "scope_note": case.get("scope_note", ""),
        "minimum_criteria": case["min_criteria"],
        "stringent_criteria": case["stringent_criteria"],
        "candidate_answer": candidate_answer,
    }


# ---------------------------------------------------------------- scoring (pure)
def score_from(min_c: list, str_c: list) -> dict:
    """Turn per-criterion verdicts into the shared numbers. Pure, so the arithmetic is tested without a model.

    `quality_score` is the fraction of ALL criteria passed — a graded 0..1 axis rather than a bar, because with
    ~25 cases the binary bars are too coarse to show a difference and would waste the replication's power. The
    two bars are kept alongside it: they are what the paper's pass/fail language means.
    """
    min_c, str_c = list(min_c or []), list(str_c or [])
    allc = min_c + str_c
    n = len(allc)
    passed = sum(1 for c in allc if c.get("passed"))
    min_pass = bool(min_c) and all(c.get("passed") for c in min_c)
    return {
        "quality_score": round(passed / n, 4) if n else None,   # the shared metric aggregate_ab.py reads
        "n_criteria": n, "n_passed": passed,
        "min_bar_pass": min_pass,
        "stringent_bar_pass": min_pass and bool(str_c) and all(c.get("passed") for c in str_c),
        "min_criteria": min_c, "stringent_criteria": str_c,
    }


# ---------------------------------------------------------------- the graded call
def grade(case: dict, candidate_answer: str, client, judge_model: str) -> dict:
    """Score one arm's artifact. Returns score_from(...) plus the judge's comment; on an empty artifact or a judge
    that emits nothing, returns a zeroed row rather than raising — a crashed arm must not abort the sweep."""
    if not (candidate_answer or "").strip():
        return dict(score_from([], []), comment="empty artifact", judged=False)
    resp = client.messages.create(
        model=judge_model, max_tokens=2048, system=_JUDGE_SYS, tools=[_JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "grade"},
        messages=[{"role": "user", "content": json.dumps(payload(case, candidate_answer))}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            g = dict(block.input)
            return dict(score_from(g.get("min_criteria"), g.get("stringent_criteria")),
                        comment=g.get("comment", ""), judged=True)
    return dict(score_from([], []), comment="judge emitted no verdict", judged=False)
