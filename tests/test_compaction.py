"""Context compaction — turn-boundary summarization that keeps the message history bounded and API-valid.

The compactor must never break the user/assistant alternation or tool_use/tool_result pairing: it summarizes
OLD whole turns into a user(summary)->assistant(ack) head and keeps recent turns verbatim.
"""

from cellarium import agent


def _turn(i, with_tool=False):
    msgs = [{"role": "user", "content": f"question {i}"}]
    if with_tool:
        msgs.append({"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "survey", "input": {}}]})
        msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": f"PAYLOAD{i}_" + "X" * 300}]})
    msgs.append({"role": "assistant", "content": [{"type": "text", "text": f"answer {i}"}]})
    return msgs


def _convo(n):
    out = []
    for i in range(n):
        out += _turn(i, with_tool=(i % 2 == 0))
    return out


def test_split_turns_groups_at_user_string_boundaries():
    msgs = _convo(3)
    turns = agent._split_turns(msgs)
    assert len(turns) == 3
    assert all(t[0]["role"] == "user" and isinstance(t[0]["content"], str) for t in turns)  # each starts clean


def test_compact_noop_when_few_turns():
    msgs = _convo(3)
    assert agent.compact_history(msgs, keep_recent_turns=3) is msgs   # nothing to compact


def test_compact_summarizes_old_keeps_recent_and_stays_alternation_valid(monkeypatch):
    monkeypatch.setattr(agent, "_summarize", lambda old, model: "COMPACT SUMMARY")
    msgs = _convo(6)
    out = agent.compact_history(msgs, keep_recent_turns=3)
    # head is user(summary) -> assistant(ack); then recent turns start with a user(str)
    assert out[0]["role"] == "user" and "COMPACT SUMMARY" in out[0]["content"]
    assert out[1]["role"] == "assistant"
    assert out[2]["role"] == "user" and isinstance(out[2]["content"], str)
    # fewer messages than we started with, and the very last turn is preserved verbatim
    assert len(out) < len(msgs)
    assert out[-1] == msgs[-1]
    # the three most recent questions survive verbatim
    recent_qs = [m["content"] for m in out if m["role"] == "user" and isinstance(m["content"], str)]
    assert "question 5" in recent_qs and "question 3" in recent_qs and "question 2" not in recent_qs


def test_compact_falls_back_to_stubbing_tool_results_when_summary_fails(monkeypatch):
    def boom(old, model):
        raise RuntimeError("no api key")
    monkeypatch.setattr(agent, "_summarize", boom)
    msgs = _convo(6)
    out = agent.compact_history(msgs, keep_recent_turns=3)
    flat = str(out)
    assert "elided in compaction" in flat            # old tool_results stubbed
    assert "PAYLOAD0" not in flat and "PAYLOAD2" not in flat   # bulky OLD payloads gone
    assert "PAYLOAD4" in flat                          # a RECENT turn's payload is kept verbatim
    assert out[-1] == msgs[-1]                         # recent turn intact


def test_estimate_tokens_grows_with_content():
    small = _convo(1)
    big = _convo(20)
    assert agent._estimate_tokens(big) > agent._estimate_tokens(small) > 0


def test_to_dict_whitelists_input_fields():
    # a text block's output-only parsed_output / citations must be dropped (the 400 "Extra inputs" bug)
    assert agent._to_dict({"type": "text", "text": "hi", "parsed_output": {"x": 1}, "citations": None}) == {"type": "text", "text": "hi"}
    assert agent._to_dict({"type": "tool_use", "id": "t", "name": "survey", "input": {}, "extra": 9}) == {"type": "tool_use", "id": "t", "name": "survey", "input": {}}
    tr = {"type": "tool_result", "tool_use_id": "t", "content": "x"}   # unknown types pass through untouched
    assert agent._to_dict(tr) == tr


def test_sanitize_repairs_existing_messages():
    msgs = [{"role": "user", "content": "q"},
            {"role": "assistant", "content": [{"type": "text", "text": "a", "parsed_output": {"bad": 1}}]}]
    agent._sanitize(msgs)
    assert msgs[1]["content"] == [{"type": "text", "text": "a"}]
