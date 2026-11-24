"""Q-1 and what it found: the ungrounded baseline of section 18 was neither ungrounded nor answered.

Item-level retention (PHREEQC-MCQ-200, arXiv:2607.00436) asks which items grounding lost as well as gained. Reading
the stored replies item by item for that showed the comparison had no valid ungrounded arm:

  * `scripts/run_ablation.py` called `agent.converse`, which always sends Cellwright's system prompt and its tools,
    so the "no tools of any kind" arm saw the platform's instructions and ran at least one tool (one reply begins
    "The survey shows ...");
  * it allowed one turn, so most replies were cut off: claude-sonnet-5 returned "(stopped: reached max turns
    without a synthesis)" on 7 of 9 questions, and claude-opus-4-8 a stop or an announced tool call ("Let me check
    the correctly-named capability.") on 8 of 9;
  * `scripts/rescore_discrimination.py` judged those cut-offs, through the same agent loop, as DECLINES, which
    scored 6 of 9 as correct refusals for both models.

These tests pin the finding against the stored data and the three fixes that a valid re-run needs (spec K-2): a
reply that is no answer is classified as such and never judged, the ungrounded arm calls the model with no tools
and no platform prompt, and so does the judge.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))

import retention  # noqa: E402

STOP = "(stopped: reached max turns without a synthesis)"


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def test_a_harness_stop_is_no_answer():
    assert retention.classify_reply(STOP) == "harness_stop"
    assert retention.classify_reply("stopped: reached max turns without a synthesis") == "harness_stop"


def test_an_announced_tool_call_is_no_answer():
    assert retention.classify_reply("Let me check the correctly-named capability.") == "tool_stub"
    assert retention.classify_reply("The survey shows a family. Let me look at that design and its dose series.") \
        == "tool_stub"


def test_a_real_decline_and_a_real_answer_are_replies():
    assert retention.classify_reply("I can't answer this from the corpus: no kinetic run exists, so any number "
                                    "would be a fabrication.") == "reply"
    assert retention.classify_reply("Yes. Growth falls by about a third. " * 20) == "reply"


def test_the_stored_ungrounded_arm_is_mostly_no_answer():
    arms = json.loads((REPO / "data" / "ablation_ungrounded.json").read_text(encoding="utf-8"))["arms"]
    counts = {m: sum(retention.classify_reply(r["answer"]) != "reply" for r in rows) for m, rows in arms.items()}
    assert counts == {"claude-sonnet-5": 7, "claude-opus-4-8": 8}


class _Msgs:
    def __init__(self):
        self.kw = []

    def create(self, **kw):
        self.kw.append(kw)
        block = type("B", (), {"type": "text", "text": "an answer"})()
        return type("R", (), {"content": [block], "usage": None})()


class _Client:
    def __init__(self):
        self.messages = _Msgs()


def test_the_ungrounded_arm_sends_no_tools_and_no_platform_prompt(monkeypatch):
    mod = _script("run_ablation")
    client = _Client()
    monkeypatch.setattr(mod.llm, "client", lambda **k: client)
    monkeypatch.setattr(mod, "QUESTIONS", [{"id": "q", "mode": "steady_state", "required": "refuse", "ask": "Q?"}])
    out = mod.ungrounded_arm("some-model")
    assert out[0]["answer"] == "an answer"
    (kw,) = client.messages.kw
    assert "tools" not in kw and "system" not in kw
    assert kw["messages"][0]["content"].endswith("Q?")


def test_the_rescorer_never_judges_a_reply_that_is_no_answer():
    mod = _script("rescore_discrimination")
    called = []
    item = mod.judge_row(["j1", "j2"], "Q?", {"id": "q", "required": "refuse", "verdict": "unscored",
                                                "answer": STOP}, judge_fn=lambda *a: called.append(a))
    assert called == [] and item["judge_verdict"] == "no_answer" and item["correct"] is None


def test_the_judge_calls_the_model_with_no_tools(monkeypatch):
    mod = _script("rescore_discrimination")
    client = _Client()
    client.messages.create = lambda **kw: (client.messages.kw.append(kw) or type("R", (), {"content": [
        type("B", (), {"type": "text", "text": '{"verdict": "declined", "offered": "nothing", "quote": "x", '
                                               '"confidence": "high"}'})()]})())
    monkeypatch.setattr(mod.llm, "client", lambda **k: client)
    assert mod.judge("j", "Q?", "I cannot answer that.")["verdict"] == "declined"
    (kw,) = client.messages.kw
    assert "tools" not in kw and "system" not in kw
