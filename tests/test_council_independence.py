"""L-3: a Council record carries nothing from the record before it.

LLM-IDEA (arXiv:2610.11253) reports, as its own limitation, that its seeds shared a memory, so its p-values were
optimistic. Every M1+M2 comparison here treats Council records as independent: the paired differences, the
detectable-difference floors and the per-question means all assume it. These tests check the assumption where it
could fail, in `council.deliberate`, which produces every record: a second record's prompts contain nothing of the
first record, whatever the arm, and a run leaves no module-level state behind.

Two cross-record inputs are DECLARED rather than hidden, and are out of scope here: the noise arm replays
objections raised against another question (that is its purpose), and best-of-N's budget is the full arm's
measured spend. Both are named in evals/ablate.py.

Every model call is scripted; nothing leaves the machine.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import council  # noqa: E402


class _Block:
    def __init__(self, data):
        self.type = "tool_use"
        self.input = data


class _Resp:
    def __init__(self, data):
        self.content = [_Block(data)]


class _Messages:
    def __init__(self, scripts):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.seen: list[str] = []          # everything each call was shown: system prompt and messages

    def create(self, **kw):
        self.seen.append(json.dumps({"system": kw.get("system"), "messages": kw.get("messages")}, default=str))
        queue = self.scripts.get(kw["tool_choice"]["name"])
        assert queue, f"no scripted response left for {kw['tool_choice']['name']!r}"
        return _Resp(copy.deepcopy(queue.pop(0)))


class _Client:
    def __init__(self, scripts):
        self.messages = _Messages(scripts)


def _cand(tag: str, i: int) -> dict:
    return {
        "claim": f"claim {tag}{i}", "h1": f"h1 {tag}", "h0": f"h0 {tag}",
        "operational_defs": [{"construct": f"construct {tag}", "observable": "protein_mass", "measure": "cv"}],
        "predicted_effect": f"positive {tag}",
        "falsifier": {"target": "wildtype/basal", "reference": "wildtype/basal", "channel": "protein_mass",
                      "decision_rule": "reject H0 if welch_t >= 2", "refuting_result": "welch_t < 2"},
        "rivals": [{"claim": f"noise {tag}", "distinguishing_result": "cv == baseline"},
                   {"claim": f"extrinsic {tag}", "distinguishing_result": "tracks mass"}],
        "auxiliary_assumptions": [f"same medium {tag}"],
        "candidate_designs": [{"perturbation": "wildtype", "condition": "basal", "seeds": 8}],
    }


def _verdict(**over):
    v = {"falsifiable": True, "specified": True, "operationalized": True, "discriminating": True,
         "new_substantive_objection_this_round": False, "open_objections_resolved": True}
    v.update(over)
    return v


def _scripts(tag: str) -> dict:
    return {
        "propose_hypothesis": [_cand(tag, i) for i in range(4)],
        "raise_objections": [{"objections": [{"type": "undefined_term", "issue": f"objection {tag}",
                                              "severity": "substantive"}]},
                             {"objections": [], "resolved": ["r1.1"]}, {"objections": []}, {"objections": []}],
        "rule": [_verdict(new_substantive_objection_this_round=True, open_objections_resolved=False),
                 _verdict(), _verdict(), _verdict()],
    }


def _run(question: str, tag: str, **arm) -> _Client:
    client = _Client(_scripts(tag))
    council.deliberate(question, client=client, verbose=False, temperature=0.0, **arm)
    return client


ARMS = [{}, {"use_judge": False}, {"use_skeptic": False}, {"use_skeptic": False, "use_judge": False}]


def test_a_second_record_sees_nothing_of_the_first_whatever_the_arm():
    for first in ARMS:
        for second in ARMS:
            _run("ALPHAQ: does protein mass vary across seeds?", "alphatag", **first)
            seen = " ".join(_run("BETAQ: does ppGpp rise on starvation?", "betatag", **second).messages.seen)
            # The question reaches every call; a candidate reaches a prompt only when a later round revises it,
            # so the proposer-only arm (one call) never shows its own tag. The question is the positive control.
            assert "BETAQ" in seen, "the check must see the record's own content"
            assert "ALPHAQ" not in seen and "alphatag" not in seen, (first, second)


def test_a_run_changes_no_module_level_state():
    def snapshot():
        return {k: copy.deepcopy(v) for k, v in vars(council).items()
                if not k.startswith("__") and isinstance(v, (dict, list, set))}
    before = snapshot()
    _run("ALPHAQ: does protein mass vary across seeds?", "alphatag")
    assert snapshot() == before


def test_the_check_fails_when_a_record_is_shown_another_records_content():
    seen = " ".join(_run("BETAQ: does ppGpp rise? (context: ALPHAQ alphatag)", "betatag").messages.seen)
    assert "ALPHAQ" in seen and "alphatag" in seen
