"""Agent rate-limit contract.

Main handles Anthropic rate limits (and transient 5xx) via the SDK's own retry: it constructs the client with
`anthropic.Anthropic(max_retries=...)`, which does exponential backoff, and lets a terminal failure propagate to
the caller (the server surfaces a hint). This test guards that contract — that the retry config isn't silently
dropped in a refactor.

(Adapted from the fix-anthropic-rate-limit-handling branch, which asserted an older, hand-rolled contract where
the agent CAUGHT the error and returned a friendly "rate limit / retry" string. Main doesn't do that — the SDK
retries and the exception propagates — so the assertion is rewritten to main's actual behavior.)
"""

import json
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


def test_context_tokens_prefilters_then_counts_exact():
    """LLM-4: below the pre-filter band -> the cheap char estimate (count_tokens NOT called); above the band -> the
    API's exact count_tokens; a count_tokens failure falls back to the estimate so a turn is never blocked."""
    small = [{"role": "user", "content": "hi"}]

    class _NoCount:                                    # count_tokens must NOT be reached below the band
        class messages:
            @staticmethod
            def count_tokens(**kw):
                raise AssertionError("count_tokens called below the pre-filter band")

    below = agent._estimate_tokens(small) + agent._prompt_overhead_est("sys", [])
    assert agent._context_tokens(_NoCount(), "m", "sys", [], small) == below   # whole-prompt estimate, no API call

    big = [{"role": "user", "content": "x" * 200_000}]   # est ~50k >> 0.75*trigger -> the exact-count path

    class _Count:
        class messages:
            @staticmethod
            def count_tokens(**kw):
                class _R:
                    input_tokens = 12345
                return _R()

    assert agent._context_tokens(_Count(), "m", "sys", [], big) == 12345   # uses the exact API count

    class _Boom:
        class messages:
            @staticmethod
            def count_tokens(**kw):
                raise RuntimeError("no network")

    fallback = agent._estimate_tokens(big) + agent._prompt_overhead_est("sys", [])
    assert agent._context_tokens(_Boom(), "m", "sys", [], big) == fallback   # safe fallback to the whole-prompt est


def test_temperature_for_pins_except_reasoning_and_thinking():
    """M-2/LLM-3: pin temperature for models that accept it with thinking off; omit for reasoning models / thinking."""
    assert agent.temperature_for("claude-sonnet-5") == agent.TEMPERATURE
    assert agent.temperature_for("claude-haiku-4-5-20251001") == agent.TEMPERATURE
    assert agent.temperature_for(None) == agent.TEMPERATURE                     # Auto default -> non-opus -> pinned
    assert agent.temperature_for("claude-opus-4-8") is None                     # reasoning model rejects it
    assert agent.temperature_for("claude-sonnet-5", thinking=True) is None      # thinking forces temperature=1


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
    def __init__(self): self.calls, self.tool_choices = 0, []
    def stream(self, **kw):
        self.calls += 1
        self.tool_choices.append((kw.get("tool_choice") or {}).get("type"))
        # the wrap call forbids tools via tool_choice=none (tools stay DEFINED so the tool_use history is valid)
        if (kw.get("tool_choice") or {}).get("type") == "none":
            return _Stream(_Msg([_Blk(type="text", text="FINAL SYNTHESIS from partial evidence.")], "end_turn"))
        return _Stream(_Msg([_Blk(type="tool_use", name="survey_corpus", input={}, id=f"tu{self.calls}")], "tool_use"))


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
    # 3 in-loop turns leave tool_choice unset, then ONE wrap call forbids tools via tool_choice=none
    assert client.messages.tool_choices == [None, None, None, "none"]


def test_truncate_tool_result_shrinks_lists_and_stays_valid_json():
    """DD-ENG-2: a bulky tool result is trimmed by dropping list ROWS (keeping scalars + provenance), not by a blind
    char-slice that would cut JSON mid-structure. The result must still parse and carry an honest drop-marker."""
    big = {"channel": "growth_rate", "provenance": "manifest",
           "rows": [{"i": i, "v": round(i * 1.5, 2)} for i in range(400)]}
    s = agent._truncate_tool_result(big, 800)
    assert len(s) <= 800
    parsed = json.loads(s)                                  # still VALID json (not severed) — the whole point
    assert parsed["channel"] == "growth_rate" and parsed["provenance"] == "manifest"   # scalars/provenance survive
    assert len(parsed["rows"]) < 400 and "dropped to fit context" in json.dumps(parsed["rows"][-1])


def test_truncate_tool_result_passes_small_and_falls_back_on_non_dict():
    small = {"ok": True, "n": 3}
    assert json.loads(agent._truncate_tool_result(small, 800)) == small     # small -> unchanged
    big_list = list(range(5000))                                            # non-dict -> char-slice fallback, bounded
    out = agent._truncate_tool_result(big_list, 200)
    assert len(out) <= 200 + len(" …[truncated]") and out.endswith("…[truncated]")


def test_converse_circuit_breaker_stops_on_repeated_identical_tool_call(monkeypatch):
    """DD-ENG-3: an identical (tool, args) call repeated _REPEAT_CAP times means the agent is stuck — converse must
    break out and force a synthesis instead of burning all max_turns spinning on the same call."""
    from cellarium import tools

    class _Blk:
        type = "tool_use"; id = "t1"; name = "viability"; input = {"perturbation": "gene_knockout"}

        def model_dump(self):
            return {"type": "tool_use", "id": "t1", "name": "viability", "input": {"perturbation": "gene_knockout"}}

    class _Resp:
        stop_reason = "tool_use"; content = [_Blk()]

    calls = {"n": 0}

    def fake_run_turn(client, kw, on_text, role="agent"):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(agent, "_run_turn", fake_run_turn)
    monkeypatch.setattr(agent.anthropic, "Anthropic", lambda **k: object())
    monkeypatch.setattr(tools, "dispatch", lambda n, a: {"value": 1})     # always succeeds, always identical
    agent.converse([{"role": "user", "content": "hi"}], model="claude-haiku-4-5-20251001", max_turns=30)
    # 3 identical rounds trip the breaker, then ONE forced-synthesis call — far below the 30-turn budget
    assert calls["n"] <= agent._REPEAT_CAP + 2
