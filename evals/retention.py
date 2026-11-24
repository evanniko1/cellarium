"""Q-1: item-level retention for a grounded-against-ungrounded comparison, and what counts as a reply at all.

PHREEQC-MCQ-200 (arXiv:2607.00436) found that giving an agent the simulator raised its accuracy overall while losing
items it had answered correctly without it, which an average hides; it recommends reporting retention item by item.
Doing that for section 18's nine questions first requires deciding which stored replies are replies. A harness that
stops before the model has answered, or a reply that announces a tool call and ends, is no answer, and must never be
scored as a decision to decline (Anthropic, "Demystifying evals for AI agents": a harness or environment fault must
not be scored as a model answer).
"""
from __future__ import annotations

import re

HARNESS_STOP = re.compile(r"stopped: reached max turns without a synthesis", re.I)
# "Let me check ...", "Let me look at that design ..." -- an announced next step, with nothing after it.
ANNOUNCED_STEP = re.compile(r"\bLet me (check|look|read|run|see|pull|query|survey|compare|examine|find)\b", re.I)
STUB_MAX_CHARS = 400


def classify_reply(answer: str) -> str:
    """'harness_stop', 'tool_stub' (a short reply that ends on an announced step), or 'reply'."""
    text = (answer or "").strip()
    if HARNESS_STOP.search(text):
        return "harness_stop"
    if len(text) <= STUB_MAX_CHARS and ANNOUNCED_STEP.search(text):
        return "tool_stub"
    return "reply"


def retention(grounded: dict, ungrounded: dict, answers: dict) -> dict:
    """Per item: whether each arm was correct, and whether the ungrounded reply was a reply at all.

    `grounded` and `ungrounded` map item id to `correct` (True / False / None for disputed); `answers` maps item id
    to the ungrounded arm's stored reply. Items whose ungrounded reply is no answer are excluded from lost and gained
    and counted, because a comparison against no answer measures the harness, not grounding."""
    rows, lost, gained, invalid = [], [], [], []
    for iid in sorted(grounded):
        kind = classify_reply(answers.get(iid, ""))
        g, u = grounded.get(iid), ungrounded.get(iid)
        rows.append({"id": iid, "grounded_correct": g, "ungrounded_correct": u, "ungrounded_reply": kind})
        if kind != "reply":
            invalid.append(iid)
        elif u is True and g is False:
            lost.append(iid)
        elif g is True and u is False:
            gained.append(iid)
    return {"items": rows, "n": len(rows), "ungrounded_no_answer": invalid, "lost_by_grounding": lost,
            "gained_by_grounding": gained, "comparable": len(rows) - len(invalid)}
