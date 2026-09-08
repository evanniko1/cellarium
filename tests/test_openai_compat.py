"""LLM-7b — the OpenAI-compatible adapter, verified against a fake endpoint.

A translation layer is exactly the kind of code that looks right and is wrong in one direction only, so
every claim the adapter makes is checked here rather than at a live endpoint: no key, no network, and the
failures are deterministic. What is NOT checked here is whether a real server accepts the payload — that is
the live smoke in LLM-7c.

The shapes that matter are the two the seam's docstring calls out: tool calls (arguments are an object on
one side and a JSON string on the other) and the forced-tool emit that `council._emit` depends on.

Run: python -m pytest tests/test_openai_compat.py
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from cellarium import _openai_compat as oc


# ---------------------------------------------------------------------------------------------------
# request translation
# ---------------------------------------------------------------------------------------------------
def test_system_blocks_collapse_to_a_leading_system_message():
    """Anthropic takes a top-level system, optionally as blocks with cache_control. Chat Completions takes
    a leading system message and has nowhere to put cache_control, so it is dropped rather than sent."""
    system = [{"type": "text", "text": "You are Cellwright."},
              {"type": "text", "text": "Rules follow.", "cache_control": {"type": "ephemeral"}}]
    out = oc.to_chat_messages([{"role": "user", "content": "hi"}], system)
    assert out[0] == {"role": "system", "content": "You are Cellwright.\nRules follow."}
    assert "cache_control" not in json.dumps(out)
    assert out[1] == {"role": "user", "content": "hi"}


def test_a_tool_use_turn_becomes_tool_calls_with_stringified_arguments():
    """The single most error-prone direction: Anthropic sends `input` as an object, OpenAI wants a JSON
    string under `function.arguments`."""
    messages = [{"role": "user", "content": "check argS"},
                {"role": "assistant", "content": [
                    {"type": "text", "text": "Looking."},
                    {"type": "tool_use", "id": "tu_1", "name": "survey_corpus", "input": {"gene": "argS"}}]}]
    out = oc.to_chat_messages(messages)
    asst = out[-1]
    assert asst["role"] == "assistant" and asst["content"] == "Looking."
    call = asst["tool_calls"][0]
    assert call["id"] == "tu_1" and call["type"] == "function"
    assert call["function"]["name"] == "survey_corpus"
    assert json.loads(call["function"]["arguments"]) == {"gene": "argS"}, "arguments must be a JSON STRING"


def test_a_tool_result_turn_becomes_role_tool_messages():
    """Anthropic carries tool results in a USER message; Chat Completions wants one `tool` message each,
    keyed by the call id, and they must follow the assistant turn that requested them."""
    messages = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu_1", "content": {"n": 3}},
        {"type": "tool_result", "tool_use_id": "tu_2", "content": "plain"}]}]
    out = oc.to_chat_messages(messages)
    assert [m["role"] for m in out] == ["tool", "tool"]
    assert out[0]["tool_call_id"] == "tu_1" and json.loads(out[0]["content"]) == {"n": 3}
    assert out[1]["tool_call_id"] == "tu_2" and out[1]["content"] == "plain"


def test_tool_choice_none_survives_translation():
    """`{"type":"none"}` is how the agent forbids further tool calls WITHOUT dropping the definitions --
    dropping them 400s once the history contains tool_use blocks. If this degraded to auto, the forced
    final synthesis would be free to call more tools and the budget guard would silently stop working."""
    assert oc.to_chat_tool_choice({"type": "none"}) == "none"
    assert oc.to_chat_tool_choice({"type": "auto"}) == "auto"
    assert oc.to_chat_tool_choice({"type": "any"}) == "required"
    assert oc.to_chat_tool_choice({"type": "tool", "name": "verdict"}) == {
        "type": "function", "function": {"name": "verdict"}}
    assert oc.to_chat_tool_choice(None) is None


def test_tools_translate_schema_and_name():
    tools = [{"name": "verdict", "description": "emit a verdict",
              "input_schema": {"type": "object", "properties": {"verdict": {"type": "string"}}}}]
    fn = oc.to_chat_tools(tools)[0]
    assert fn["type"] == "function"
    assert fn["function"]["name"] == "verdict"
    assert fn["function"]["parameters"]["properties"]["verdict"]["type"] == "string"


# ---------------------------------------------------------------------------------------------------
# response translation
# ---------------------------------------------------------------------------------------------------
def _raw(content=None, tool_calls=None, finish="stop", prompt=11, completion=7):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)],
                           usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
                           model="gpt-4o-mini", id="chatcmpl-1")


def test_a_text_response_becomes_a_text_block_the_agent_can_read():
    r = oc.from_chat_response(_raw(content="ppGpp rose 18%."))
    assert r.stop_reason == "end_turn"
    assert [b.type for b in r.content] == ["text"]
    assert "".join(b.text for b in r.content if b.type == "text") == "ppGpp rose 18%."
    assert r.usage.input_tokens == 11 and r.usage.output_tokens == 7


def test_a_tool_call_response_becomes_a_tool_use_block_with_a_PARSED_input():
    """`agent.converse` does `tools.dispatch(tu.name, tu.input)` -- input must be a dict, not a string."""
    tc = SimpleNamespace(id="call_9", function=SimpleNamespace(name="trajectory",
                                                              arguments='{"design":"wildtype/basal"}'))
    r = oc.from_chat_response(_raw(content=None, tool_calls=[tc], finish="tool_calls"))
    assert r.stop_reason == "tool_use", "the agent loops on stop_reason == 'tool_use'"
    (block,) = r.content
    assert block.type == "tool_use" and block.id == "call_9" and block.name == "trajectory"
    assert block.input == {"design": "wildtype/basal"}


def test_malformed_tool_arguments_become_a_bad_call_not_an_exception():
    """A model emitting invalid JSON should surface as a tool call dispatch can reject, with the raw text
    preserved. Raising inside the adapter would present a model error as a Cellarium stack trace."""
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="trajectory", arguments="{not json"))
    r = oc.from_chat_response(_raw(tool_calls=[tc], finish="tool_calls"))
    assert r.content[0].input == {"_raw": "{not json"}


def test_blocks_serialise_the_way_the_history_writer_expects():
    """agent._to_dict calls model_dump() and re-sends the result to the API, so the dict has to be
    input-valid -- a block that cannot round-trip corrupts the next turn's history."""
    r = oc.from_chat_response(_raw(
        content="hi", tool_calls=[SimpleNamespace(id="c1", function=SimpleNamespace(
            name="t", arguments='{"a":1}'))], finish="tool_calls"))
    dumps = [b.model_dump() for b in r.content]
    assert dumps[0] == {"type": "text", "text": "hi"}
    assert dumps[1] == {"type": "tool_use", "id": "c1", "name": "t", "input": {"a": 1}}
    json.dumps(dumps)   # must be JSON-serialisable for the session store


def test_usage_does_not_invent_cache_numbers():
    """observability prices cache_read/cache_creation. OpenAI-style endpoints do not report them in these
    terms, so they must read 0 rather than being back-filled from prompt_tokens and priced as savings."""
    r = oc.from_chat_response(_raw(content="x"))
    assert r.usage.cache_read_input_tokens == 0
    assert r.usage.cache_creation_input_tokens == 0


@pytest.mark.parametrize(("finish", "expected"), [
    ("tool_calls", "tool_use"), ("stop", "end_turn"), ("length", "max_tokens")])
def test_finish_reasons_map_onto_the_stop_reasons_the_loop_branches_on(finish, expected):
    assert oc.from_chat_response(_raw(content="x", finish=finish)).stop_reason == expected


# ---------------------------------------------------------------------------------------------------
# the client surface, against a fake endpoint
# ---------------------------------------------------------------------------------------------------
class _FakeCompletions:
    def __init__(self, result):
        self.result, self.seen = result, {}

    def create(self, **kw):
        self.seen = kw
        return self.result


def _fake_client(result):
    c = oc.OpenAICompatClient.__new__(oc.OpenAICompatClient)   # skip __init__: no openai package needed
    comp = _FakeCompletions(result)
    c._raw = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    c.messages = oc._Messages(c._raw)
    return c, comp


def test_create_sends_a_chat_payload_and_returns_the_anthropic_shape():
    client, comp = _fake_client(_raw(content="done"))
    r = client.messages.create(model="gpt-4o-mini", max_tokens=64, system="be terse",
                               messages=[{"role": "user", "content": "hi"}], temperature=0.0)
    assert comp.seen["model"] == "gpt-4o-mini" and comp.seen["max_tokens"] == 64
    assert comp.seen["messages"][0] == {"role": "system", "content": "be terse"}
    assert comp.seen["temperature"] == 0.0
    assert r.content[0].text == "done"


def test_an_omitted_temperature_is_not_sent():
    """temperature_for returns None for models that reject an explicit value; None must mean OMIT, not 0."""
    client, comp = _fake_client(_raw(content="x"))
    client.messages.create(model="m", messages=[{"role": "user", "content": "hi"}], temperature=None)
    assert "temperature" not in comp.seen


def test_the_forced_tool_emit_council_depends_on_round_trips():
    """council._emit is the single forced-tool call site: it pins tool_choice to one tool and reads the
    resulting input as the structured output. If either half of that breaks, every Council round breaks."""
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(
        name="verdict", arguments='{"verdict":"supported","rationale":"n=8"}'))
    client, comp = _fake_client(_raw(tool_calls=[tc], finish="tool_calls"))
    tool = {"name": "verdict", "description": "", "input_schema": {"type": "object", "properties": {}}}
    r = client.messages.create(model="m", max_tokens=256, system="judge",
                               messages=[{"role": "user", "content": "decide"}],
                               tools=[tool], tool_choice={"type": "tool", "name": "verdict"})
    assert comp.seen["tool_choice"] == {"type": "function", "function": {"name": "verdict"}}
    assert r.content[0].input["verdict"] == "supported"


def test_count_tokens_returns_a_number_rather_than_raising():
    """Chat Completions has no count endpoint. agent._context_tokens treats this as best-effort and falls
    back on exception, so an approximation degrades compaction timing; raising would break the turn."""
    client, _ = _fake_client(_raw(content="x"))
    n = client.messages.count_tokens(model="m", messages=[{"role": "user", "content": "hello " * 50}],
                                     system="sys").input_tokens
    assert isinstance(n, int) and n > 0


def test_streaming_accumulates_text_and_fragmented_tool_calls():
    """Tool calls arrive split across chunks and keyed by index, not id -- the fragments have to be
    reassembled or the agent receives truncated JSON and every streamed tool call fails."""
    def chunk(content=None, tcs=None, finish=None):
        delta = SimpleNamespace(content=content, tool_calls=tcs)
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)],
                               usage=None, model="m", id="c1")

    def frag(idx, cid=None, name=None, args=""):
        return SimpleNamespace(index=idx, id=cid, function=SimpleNamespace(name=name, arguments=args))

    chunks = [chunk("Look"), chunk("ing."),
              chunk(tcs=[frag(0, "c9", "trajectory", '{"des')]),
              chunk(tcs=[frag(0, None, None, 'ign":"wt"}')]),
              chunk(finish="tool_calls")]
    client, _ = _fake_client(None)
    client._raw.chat.completions.result = iter(chunks)
    client._raw.chat.completions.create = lambda **kw: iter(chunks)

    with client.messages.stream(model="m", messages=[{"role": "user", "content": "go"}]) as st:
        text = "".join(st.text_stream)
    final = st.get_final_message()
    assert text == "Looking."
    assert final.stop_reason == "tool_use"
    tu = [b for b in final.content if b.type == "tool_use"][0]
    assert tu.id == "c9" and tu.name == "trajectory" and tu.input == {"design": "wt"}


# ---------------------------------------------------------------------------------------------------
# the whole loop, through the adapter
# ---------------------------------------------------------------------------------------------------
def test_the_agent_tool_loop_runs_end_to_end_through_the_adapter(monkeypatch):
    """The claim LLM-7b actually makes, exercised rather than asserted piecewise.

    Unit-testing each translation leaves the interesting failure uncovered: the loop reads `.stop_reason`,
    dispatches `tu.name(tu.input)`, writes `_to_dict(block)` back into history, re-sends that history, and
    branches on the SECOND response. A shape that survives one hop and corrupts the next passes every test
    above. The agent STREAMS its turns, so the fake serves chunks when stream=True and a plain completion
    otherwise -- both paths through the adapter, in the order the real loop uses them.
    """
    from cellarium import agent, tools

    calls = {"n": 0, "sent": []}

    def _chunk(content=None, tcs=None, finish=None):
        delta = SimpleNamespace(content=content, tool_calls=tcs)
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)],
                               usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
                               model="gpt-4o-mini", id="c1")

    def fake_create(**kw):
        calls["n"] += 1
        calls["sent"].append(kw)
        if calls["n"] == 1:                       # turn 1: ask for a tool
            tc = SimpleNamespace(index=0, id="c1", function=SimpleNamespace(
                name="model_capabilities", arguments='{"capability":"ppgpp_stringent_response"}'))
            chunks = [_chunk(tcs=[tc]), _chunk(finish="tool_calls")]
        else:                                     # turn 2: answer from the tool result
            chunks = [_chunk("ppGpp is represented under steady_state."), _chunk(finish="stop")]
        return iter(chunks) if kw.get("stream") else _raw(content="".join(
            c.choices[0].delta.content or "" for c in chunks), finish="stop")

    client, _ = _fake_client(None)
    client._raw.chat.completions.create = fake_create
    monkeypatch.setattr(agent.llm, "client", lambda **kw: client)
    monkeypatch.setattr(tools, "dispatch", lambda name, args: {"capability": name, "known": True})

    out = agent.converse([{"role": "user", "content": "is ppGpp represented?"}],
                         model="gpt-4o-mini", max_turns=3)

    assert calls["n"] >= 2, "the loop must come back for a second turn after the tool result"
    assert "ppGpp is represented" in out

    # The second request must carry the first turn's assistant tool_call AND a matching `tool` message.
    # This is the round trip a per-hop unit test cannot see.
    second = calls["sent"][1]["messages"]
    roles = [m["role"] for m in second]
    assert "tool" in roles, f"the tool result never reached the second request: {roles}"
    asst = next(m for m in second if m["role"] == "assistant" and m.get("tool_calls"))
    tool_msg = next(m for m in second if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == asst["tool_calls"][0]["id"], "tool result must reference its call id"
