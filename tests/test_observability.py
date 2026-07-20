"""LLM-2 — the observability seam. The record builder, the list-price cost estimate, and the publish/subscribe
meter are pure and run everywhere. Two integration checks confirm the two real call sites (council._emit and
agent.converse) actually publish role-tagged records that the meter aggregates — without touching the network."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import agent, council, observability  # noqa: E402

# --- fakes: an Anthropic response carries .usage / .model / ._request_id ------------------------------------

class _Usage:
    def __init__(self, i=0, o=0, cr=0, cc=0):
        self.input_tokens, self.output_tokens = i, o
        self.cache_read_input_tokens, self.cache_creation_input_tokens = cr, cc


class _Resp:
    def __init__(self, content, *, usage=None, model=None, request_id=None):
        self.content, self.usage, self.model, self._request_id = content, usage, model, request_id


class _Blk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# --- the record --------------------------------------------------------------------------------------------

def test_usage_record_shape_and_fields():
    resp = _Resp([], usage=_Usage(i=100, o=50, cr=200, cc=10), model="claude-opus-4-8", request_id="req_abc")
    rec = observability.usage_record("proposer", "claude-opus-4-8", resp, 1234.6, temperature=0.0)
    assert rec["role"] == "proposer" and rec["model"] == "claude-opus-4-8" and rec["request_id"] == "req_abc"
    assert rec["input_tokens"] == 100 and rec["output_tokens"] == 50
    assert rec["cache_read_tokens"] == 200 and rec["cache_creation_tokens"] == 10
    assert rec["latency_ms"] == 1234 and rec["temperature"] == 0.0          # latency is int-ms; temperature recorded
    assert rec["cost_usd"] is not None and rec["cost_usd"] > 0


def test_usage_record_degrades_without_usage_or_request_id():
    """A partial/mocked response (no .usage, no ._request_id) must never raise — tokens go to 0, model falls back."""
    rec = observability.usage_record("agent", "claude-haiku-4-5-20251001", _Resp([]), 5.0)
    assert rec["input_tokens"] == 0 and rec["output_tokens"] == 0 and rec["request_id"] is None
    assert rec["model"] == "claude-haiku-4-5-20251001"       # fell back to the passed model when resp.model is None
    assert rec["cost_usd"] == 0.0                            # priced model, zero tokens -> zero, not None


# --- cost estimate -----------------------------------------------------------------------------------------

def test_cost_estimate_math_and_cache_multipliers():
    # opus 4.8 = ($5 in / $25 out per 1M). 1M input tokens -> exactly $5.00.
    assert observability.estimate_cost_usd("claude-opus-4-8", 1_000_000, 0) == 5.0
    assert observability.estimate_cost_usd("claude-opus-4-8", 0, 1_000_000) == 25.0
    assert observability.estimate_cost_usd("claude-opus-4-8", 0, 0, cache_read_tokens=1_000_000) == 0.5   # 0.1x input
    assert observability.estimate_cost_usd("claude-opus-4-8", 0, 0, cache_creation_tokens=1_000_000) == 6.25  # 1.25x


def test_pricing_prefix_match_and_unknown_model():
    assert observability._price("claude-haiku-4-5-20251001") == (1.0, 5.0)   # date-suffixed id resolves by prefix
    assert observability._price("claude-sonnet-4-6") == (3.0, 15.0)          # longest-prefix wins over 'claude-sonnet-4'
    assert observability._price("claude-sonnet-4-20250514") == (3.0, 15.0)   # sonnet-4.0 id
    assert observability._price("some-other-model") is None
    assert observability.estimate_cost_usd("some-other-model", 10, 10) is None   # unknown -> unpriced, not a wrong $


# --- publish / subscribe + meter ---------------------------------------------------------------------------

def test_meter_scopes_and_unsubscribes():
    with observability.meter() as m:
        observability.emit(observability.usage_record("proposer", "claude-opus-4-8", _Resp([], usage=_Usage(i=10, o=5)), 100))
        observability.emit(observability.usage_record("judge", "claude-haiku-4-5", _Resp([], usage=_Usage(i=20, o=8)), 200))
        s = m.summary()
    # after the scope, further emits must NOT reach this meter (subscription was released)
    observability.emit(observability.usage_record("agent", "claude-opus-4-8", _Resp([], usage=_Usage(i=999, o=999)), 999))
    assert m.summary()["n_calls"] == 2                      # frozen at scope exit — the post-scope emit is not counted
    assert s["n_calls"] == 2 and s["input_tokens"] == 30 and s["output_tokens"] == 13 and s["latency_ms"] == 300
    assert s["by_role"] == {"proposer": 1, "judge": 1}
    assert s["cost_usd"] is not None and s["cost_partial"] is False


def test_meter_cost_partial_when_a_call_is_unpriced():
    with observability.meter() as m:
        observability.emit(observability.usage_record("proposer", "claude-opus-4-8", _Resp([], usage=_Usage(i=10, o=5)), 1))
        observability.emit(observability.usage_record("skeptic", "mystery-model", _Resp([], usage=_Usage(i=10, o=5)), 1))
    s = m.summary()
    assert s["n_calls"] == 2 and s["cost_partial"] is True   # one call unpriced -> aggregate cost is a lower bound
    assert s["cost_usd"] is not None                          # ...but the priced call still contributes


def test_emit_isolates_a_faulty_subscriber():
    """A consumer that raises must never break a live model call — emit swallows it and still feeds good sinks."""
    seen = []
    unsub_bad = observability.subscribe(lambda rec: (_ for _ in ()).throw(RuntimeError("boom")))
    unsub_good = observability.subscribe(seen.append)
    try:
        observability.emit({"role": "agent", "model": "x"})   # must not raise despite the faulty subscriber
    finally:
        unsub_bad()
        unsub_good()
    assert seen == [{"role": "agent", "model": "x"}]


# --- integration: the two real call sites publish role-tagged records ---------------------------------------

class _FakeMessages:
    def create(self, **kw):
        return _Resp([_Blk(type="tool_use", input={"claim": "ok"})],
                     usage=_Usage(i=120, o=40, cr=300), model=kw.get("model"), request_id="req_1")


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def test_council_emit_publishes_a_role_tagged_record():
    tool = {"name": "propose", "input_schema": {"type": "object", "properties": {}}}
    with observability.meter() as m:
        out = council._emit(_FakeClient(), "claude-sonnet-5", "sys", tool, {}, role="proposer")
    assert out == {"claim": "ok"}                            # still returns the validated tool input
    s = m.summary()
    assert s["n_calls"] == 1 and s["by_role"] == {"proposer": 1}
    assert s["input_tokens"] == 120 and s["cache_read_tokens"] == 300 and s["by_model"] == {"claude-sonnet-5": 1}


# streamed-response fakes for converse (mirror test_agent.py's shape, plus usage so the meter aggregates real numbers)

class _StreamMsg:
    def __init__(self, content, stop_reason, usage):
        self.content, self.stop_reason, self.usage, self.model, self._request_id = content, stop_reason, usage, "m", "r"


class _Stream:
    def __init__(self, msg):
        self._msg = msg
        self.text_stream = [b.text for b in msg.content if getattr(b, "type", None) == "text"]

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def until_done(self): pass
    def get_final_message(self): return self._msg


class _StreamMessages:
    def __init__(self): self.calls = 0
    def stream(self, **kw):
        self.calls += 1
        if (kw.get("tool_choice") or {}).get("type") == "none":   # the forced final synthesis
            return _Stream(_StreamMsg([_Blk(type="text", text="done")], "end_turn", _Usage(i=5, o=3)))
        return _Stream(_StreamMsg([_Blk(type="tool_use", name="survey_corpus", input={}, id=f"t{self.calls}")],
                                  "tool_use", _Usage(i=10, o=4)))


class _StreamClient:
    def __init__(self, **kw): self.messages = _StreamMessages()


def test_converse_on_usage_aggregates_the_turn(monkeypatch):
    """The per-agent-turn aggregate: converse hands on_usage a summary covering every model call it made — the
    tool-loop turns ('agent') plus the forced final synthesis ('summary')."""
    monkeypatch.setattr(agent.anthropic, "Anthropic", lambda **kw: _StreamClient())
    monkeypatch.setattr(agent.tools, "dispatch", lambda name, inp: {"ok": True})
    captured = {}
    out = agent.converse([{"role": "user", "content": "q"}], model="claude-haiku-4-5-20251001",
                         max_turns=2, on_usage=captured.update)
    assert out == "done"
    assert captured["n_calls"] == 3                          # 2 tool-loop turns + 1 forced synthesis
    assert captured["by_role"] == {"agent": 2, "summary": 1}
    assert captured["input_tokens"] == 25 and captured["output_tokens"] == 11   # 10+10+5, 4+4+3
