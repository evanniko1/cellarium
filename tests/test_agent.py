"""Agent rate-limit contract.

Main handles Anthropic rate limits (and transient 5xx) via the SDK's own retry: it constructs the client with
`anthropic.Anthropic(max_retries=...)`, which does exponential backoff, and lets a terminal failure propagate to
the caller (the server surfaces a hint). This test guards that contract — that the retry config isn't silently
dropped in a refactor.

(Adapted from the fix-anthropic-rate-limit-handling branch, which asserted an older, hand-rolled contract where
the agent CAUGHT the error and returned a friendly "rate limit / retry" string. Main doesn't do that — the SDK
retries and the exception propagates — so the assertion is rewritten to main's actual behavior.)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import agent  # noqa: E402


def test_converse_configures_sdk_retry_backoff(monkeypatch):
    """The Anthropic client must be built with max_retries so 429/5xx get exponential backoff."""
    captured = {}

    class _StopBeforeAPICall(Exception):
        pass

    def _fake_anthropic(**kwargs):
        captured.update(kwargs)          # we only care about the construction kwargs
        raise _StopBeforeAPICall()        # stop before any real network call

    monkeypatch.setattr(agent.anthropic, "Anthropic", _fake_anthropic)

    with pytest.raises(_StopBeforeAPICall):
        agent.converse([{"role": "user", "content": "hi"}], model="claude-haiku-4-5-20251001")

    assert captured.get("max_retries", 0) >= 1, \
        "converse must construct anthropic.Anthropic(max_retries=...) for 429/5xx backoff"


# --- max-turns forced synthesis: a turn must ALWAYS end with an answer, never a dangling tool_result ----------

class _Blk:
    def __init__(self, **kw): self.__dict__.update(kw)
    def model_dump(self): return dict(self.__dict__)


class _Msg:
    def __init__(self, content, stop_reason): self.content, self.stop_reason = content, stop_reason


class _Stream:
    def __init__(self, msg): self._msg = msg; self.text_stream = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def until_done(self): pass
    def get_final_message(self): return self._msg


class _Messages:
    def __init__(self): self.calls, self.saw_tools = 0, []
    def stream(self, **kw):
        self.calls += 1
        self.saw_tools.append(bool(kw.get("tools")))
        if kw.get("tools"):                                   # in-loop turn: keep asking for a tool -> exhaust budget
            return _Stream(_Msg([_Blk(type="tool_use", name="survey_corpus", input={}, id=f"tu{self.calls}")], "tool_use"))
        return _Stream(_Msg([_Blk(type="text", text="FINAL SYNTHESIS from partial evidence.")], "end_turn"))   # wrap call


class _Client:
    def __init__(self, **kw): self.messages = _Messages()


def test_converse_forces_final_synthesis_when_tool_budget_exhausted(monkeypatch):
    """If the agent is still calling tools when max_turns runs out, converse must make ONE final NO-TOOLS call so the
    session ends with a real answer — not a dangling tool_result (the eval Arm A truncation)."""
    client = _Client()
    monkeypatch.setattr(agent.anthropic, "Anthropic", lambda **kw: client)
    monkeypatch.setattr(agent.tools, "dispatch", lambda name, inp: {"ok": True})   # don't run real tools

    messages = [{"role": "user", "content": "a hard, broad question"}]
    out = agent.converse(messages, model="claude-haiku-4-5-20251001", max_turns=3)

    assert out == "FINAL SYNTHESIS from partial evidence."        # returned the forced synthesis, not "(stopped…)"
    assert messages[-1]["role"] == "assistant"                    # ends on an assistant answer, NOT a tool_result
    assert any(b.get("type") == "text" for b in messages[-1]["content"])
    assert client.messages.saw_tools == [True, True, True, False]  # 3 in-loop turns WITH tools, then 1 wrap WITHOUT
