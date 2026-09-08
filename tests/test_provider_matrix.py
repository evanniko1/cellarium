"""LLM-7c — the mocked provider matrix: every supported provider exercised on every CI run.

WHY THIS EXISTS. `tests/test_openai_compat.py` verifies the adapter's translation in isolation and
`tests/test_llm_seam.py` verifies that nothing constructs a client around the seam. Neither one asks the
question that actually rots: **do the CALL SITES still work on both providers?** Today the suite exercises
the Anthropic path for real (`council._emit`, `agent.converse`) and the OpenAI path only through hand-built
payloads, so a change to `council._emit` or the agent loop leaves the Anthropic tests green while the
translation quietly stops carrying the thing that changed. That failure is invisible until someone with no
Claude key runs the app — which is the whole reason LLM-7a exists.

WHAT THIS MODULE DOES. It runs the SAME three core interactions — a plain completion, the forced-tool emit
`council._emit` depends on, and a tool-use turn the agent loop consumes — against EVERY provider in
`llm.SUPPORTED`, with a mocked client per provider: no key, no network, deterministic. Each backend speaks
its own wire shape (Anthropic request kwargs on one side, Chat Completions kwargs on the other) and exposes
the same small set of normalisers, so one shared assertion body can say "the forced tool name survived" or
"the tool result references its call id" without knowing which provider served it.

WHY IT IS PARAMETRISED OVER `llm.SUPPORTED` RATHER THAN A LIST HERE. A matrix you have to remember to extend
is the thing that rots. Adding a provider to the seam adds it to every test below, and
`test_the_matrix_covers_every_supported_provider` fails loudly (with instructions) until a fake exists for it.

TWO PACKAGING FACTS THIS FILE IS BUILT AROUND, both verified rather than assumed:

  * `.github/workflows/ci.yml` installs `pip install -e ".[dev,hf,surrogate]"`. **`openai` is not in any of
    those extras**, so the OpenAI leg must never import it. It doesn't: the client is built with
    `OpenAICompatClient.__new__` (the idiom `tests/test_openai_compat.py` already uses) and
    `test_the_openai_leg_needs_no_openai_package` proves it by blocking the import and re-running the leg.
  * `anthropic` IS a core dependency (pyproject `[project].dependencies`), so the Anthropic leg builds
    **real `anthropic.types` objects** rather than look-alikes. That is deliberate: on that path there is no
    adapter — the SDK's own models are what `agent._to_dict` and `observability.usage_record` read — so a
    stand-in would be testing the stand-in. The real `TextBlock.model_dump()` carries `citations` and
    `ToolUseBlock.model_dump()` carries `caller`, which is exactly the output-only noise `_INPUT_FIELDS`
    exists to whitelist away.

Run: python -m pytest tests/test_provider_matrix.py
"""
from __future__ import annotations

import importlib
import json
import sys
from types import SimpleNamespace

import pytest

from cellarium import _openai_compat as oc
from cellarium import llm, observability

# The one place the fakes lie about the model's answer, so every leg is compared against the same numbers.
_IN_TOKENS, _OUT_TOKENS = 11, 7


def reply(text=None, tool_calls=(), stop=None):
    """A provider-NEUTRAL description of one model turn, which each backend renders into its own wire shape.

    Keeping the script neutral is what makes the matrix meaningful: the test says "the model answers with a
    tool call", and the two backends disagree about everything else — object types, argument encoding,
    whether the tool name arrives once or in fragments — which is precisely the surface being compared.
    """
    return {"text": text,
            "tool_calls": [{"id": i, "name": n, "input": a} for i, n, a in tool_calls],
            "stop": stop or ("tool_use" if tool_calls else "end_turn")}


# ======================================================================================================
# the Anthropic leg — no adapter, so the fake returns the SDK's own response models
# ======================================================================================================
def _ant_message(spec, model):
    from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

    content = []
    if spec["text"]:
        content.append(TextBlock(type="text", text=spec["text"]))
    for c in spec["tool_calls"]:
        content.append(ToolUseBlock(type="tool_use", id=c["id"], name=c["name"], input=c["input"]))
    return Message(id="msg_fake", content=content, model=model or "m", role="assistant",
                   stop_reason=spec["stop"], type="message",
                   usage=Usage(input_tokens=_IN_TOKENS, output_tokens=_OUT_TOKENS))


class _AntStream:
    """The streaming surface `agent._run_turn` uses: a context manager, `text_stream`, `get_final_message`.

    Text is delivered in TWO deltas even when it is short. A consumer that assumed one delta per turn would
    pass against a single-chunk fake and drop text against a real endpoint.
    """

    def __init__(self, final):
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        for b in self._final.content:
            if getattr(b, "type", None) == "text":
                yield b.text[:3]
                yield b.text[3:]

    def until_done(self):
        return None

    def get_final_message(self):
        return self._final


class _AntMessages:
    def __init__(self, backend):
        self._b = backend

    def create(self, **kw):
        return _ant_message(self._b._pop(kw), kw.get("model"))

    def stream(self, **kw):
        return _AntStream(_ant_message(self._b._pop(kw), kw.get("model")))

    def count_tokens(self, **kw):
        return SimpleNamespace(input_tokens=len(json.dumps(kw, default=str)) // 4)


class _AnthropicBackend:
    """Records ANTHROPIC request kwargs; the normalisers below read that shape."""

    provider = "anthropic"

    def __init__(self):
        self.sent: list[dict] = []
        self._queue: list[dict] = []
        self.messages = _AntMessages(self)

    # --- scripting -------------------------------------------------------------------------------
    def program(self, *specs):
        self._queue.extend(specs)
        return self

    def client(self):
        return self

    def _pop(self, kw) -> dict:
        self.sent.append(kw)
        assert self._queue, f"the fake ran out of scripted responses at call #{len(self.sent)}"
        return self._queue.pop(0)

    # --- constructing the REAL client, with no key and no network ---------------------------------
    @staticmethod
    def install_sdk(monkeypatch):
        # A deliberately inert placeholder: CI's secret scan greps for the real key prefix, so a
        # realistic-looking string here would fail the build before a single test ran.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "provider-matrix-placeholder")

    @staticmethod
    def retries_of(client):
        return client.max_retries

    # --- wire normalisers: Anthropic request kwargs -> neutral facts -------------------------------
    @staticmethod
    def system_text(req) -> str:
        s = req.get("system")
        if isinstance(s, str):
            return s
        return "\n".join((b.get("text") or "") for b in (s or []))

    @staticmethod
    def tools_view(req) -> dict:
        return {t["name"]: {"description": t.get("description", ""), "schema": t.get("input_schema") or {}}
                for t in (req.get("tools") or [])}

    @staticmethod
    def forced_tool(req):
        tc = req.get("tool_choice") or {}
        return tc.get("name") if tc.get("type") == "tool" else None

    @staticmethod
    def last_user_text(req) -> str:
        for m in reversed(req.get("messages") or []):
            if m.get("role") != "user":
                continue
            c = m.get("content")
            if isinstance(c, str):
                return c
            return "\n".join((b.get("text") or "") for b in (c or [])
                             if isinstance(b, dict) and b.get("type") == "text")
        return ""

    @staticmethod
    def tool_link(req):
        """(ids the assistant's tool calls carry, ids the tool results point back at)."""
        calls, results = [], []
        for m in req.get("messages") or []:
            c = m.get("content")
            for b in (c if isinstance(c, list) else []):
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    calls.append(b.get("id"))
                elif b.get("type") == "tool_result":
                    results.append(b.get("tool_use_id"))
        return calls, results


# ======================================================================================================
# the OpenAI-compatible leg — the REAL adapter over a fake /v1/chat/completions
# ======================================================================================================
_FINISH = {"end_turn": "stop", "tool_use": "tool_calls", "max_tokens": "length"}


def _chat_completion(spec, model):
    tcs = [SimpleNamespace(id=c["id"], type="function",
                           function=SimpleNamespace(name=c["name"], arguments=json.dumps(c["input"])))
           for c in spec["tool_calls"]]
    msg = SimpleNamespace(content=spec["text"], tool_calls=tcs or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=_FINISH[spec["stop"]])],
                           usage=SimpleNamespace(prompt_tokens=_IN_TOKENS, completion_tokens=_OUT_TOKENS),
                           model=model, id="chatcmpl-fake")


def _chat_chunks(spec, model):
    """A streamed answer, FRAGMENTED the way a real endpoint fragments it: text across two chunks, and tool
    arguments split mid-JSON, keyed by index with the id and name only on the first fragment."""
    def chunk(content=None, tcs=None, finish=None):
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tcs),
                                     finish_reason=finish)],
            usage=SimpleNamespace(prompt_tokens=_IN_TOKENS, completion_tokens=_OUT_TOKENS),
            model=model, id="chatcmpl-fake")

    out = []
    text = spec["text"] or ""
    if text:
        out += [chunk(text[:3]), chunk(text[3:])]
    for i, c in enumerate(spec["tool_calls"]):
        args = json.dumps(c["input"])
        cut = max(1, len(args) // 2)
        out.append(chunk(tcs=[SimpleNamespace(index=i, id=c["id"], function=SimpleNamespace(
            name=c["name"], arguments=args[:cut]))]))
        out.append(chunk(tcs=[SimpleNamespace(index=i, id=None, function=SimpleNamespace(
            name=None, arguments=args[cut:]))]))
    out.append(chunk(finish=_FINISH[spec["stop"]]))
    return iter(out)


class _OpenAIBackend:
    """Records CHAT COMPLETIONS request kwargs — i.e. what the adapter actually put on the wire."""

    provider = "openai"

    def __init__(self):
        self.sent: list[dict] = []
        self._queue: list[dict] = []
        # __new__, not __init__: the real constructor imports `openai`, which CI does not install.
        c = oc.OpenAICompatClient.__new__(oc.OpenAICompatClient)
        c._raw = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create)))
        c.messages = oc._Messages(c._raw)
        self._client = c

    def program(self, *specs):
        self._queue.extend(specs)
        return self

    def client(self):
        return self._client

    def _create(self, **kw):
        self.sent.append(kw)
        assert self._queue, f"the fake ran out of scripted responses at call #{len(self.sent)}"
        spec = self._queue.pop(0)
        return (_chat_chunks if kw.get("stream") else _chat_completion)(spec, kw.get("model"))

    @staticmethod
    def install_sdk(monkeypatch):
        """Stub the `openai` module so `llm.client()` can be built here EXACTLY as it is in CI, where the
        package is absent. Stubbing even when the real package is installed keeps the two environments from
        testing different things."""
        monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
            OpenAI=lambda **kw: SimpleNamespace(_ctor_kwargs=kw, chat=None)))

    @staticmethod
    def retries_of(client):
        return client._raw._ctor_kwargs["max_retries"]

    # --- wire normalisers: Chat Completions kwargs -> the same neutral facts -----------------------
    @staticmethod
    def system_text(req) -> str:
        return "\n".join(m.get("content") or "" for m in req["messages"] if m.get("role") == "system")

    @staticmethod
    def tools_view(req) -> dict:
        return {t["function"]["name"]: {"description": t["function"].get("description", ""),
                                        "schema": t["function"].get("parameters") or {}}
                for t in (req.get("tools") or [])}

    @staticmethod
    def forced_tool(req):
        tc = req.get("tool_choice")
        return tc["function"]["name"] if isinstance(tc, dict) else None

    @staticmethod
    def last_user_text(req) -> str:
        for m in reversed(req["messages"]):
            if m.get("role") == "user":
                return m.get("content") or ""
        return ""

    @staticmethod
    def tool_link(req):
        calls = [c["id"] for m in req["messages"] for c in (m.get("tool_calls") or [])]
        results = [m["tool_call_id"] for m in req["messages"] if m.get("role") == "tool"]
        return calls, results


_BACKENDS = {"anthropic": _AnthropicBackend, "openai": _OpenAIBackend}


@pytest.fixture
def matrix(request, monkeypatch):
    """One provider leg: `llm.PROVIDER` pinned to it and a mocked client that speaks its wire shape.

    PROVIDER is pinned even though the client is injected directly, so a call site that ever branches on the
    provider is exercised on the branch it claims to test. (conftest's `_isolate_the_persisted_provider`
    pins it to the default first; this overrides for the duration of the test and is restored after.)
    """
    provider = request.param
    if provider not in _BACKENDS:
        pytest.fail(f"llm.SUPPORTED lists {provider!r} but this matrix has no fake for it. Add one to "
                    "_BACKENDS in tests/test_provider_matrix.py — a provider that is not exercised here is "
                    "a provider CI cannot tell is broken.")
    monkeypatch.setattr(llm, "PROVIDER", provider)
    return _BACKENDS[provider]()


matrix_over_providers = pytest.mark.parametrize("matrix", llm.SUPPORTED, indirect=True)


# ======================================================================================================
# coverage of the matrix itself
# ======================================================================================================
def test_the_matrix_covers_every_supported_provider():
    """The guard that keeps this file honest as the seam grows.

    Without it, adding a provider to `llm.SUPPORTED` would make the parametrised tests below fail one at a
    time from inside a fixture, with no single place saying what is missing. The seam's promise is that a
    provider swap is one adapter; that promise is only checkable while every supported provider has a leg
    here, so the gap is reported once, by name, with the fix.
    """
    assert set(_BACKENDS) == set(llm.SUPPORTED), (
        f"matrix legs {sorted(_BACKENDS)} vs llm.SUPPORTED {sorted(llm.SUPPORTED)} — add a fake backend for "
        "any new provider (and delete the leg for a removed one).")
    for name, cls in _BACKENDS.items():
        assert cls.provider == name


# ======================================================================================================
# interaction 1 — a plain completion
# ======================================================================================================
@matrix_over_providers
def test_a_plain_completion_reads_identically_through_every_provider(matrix):
    """The floor: text in, text out, on every provider.

    The three things asserted are the three every caller downstream depends on — `.content` blocks with
    `.type`/`.text`, a `stop_reason` of "end_turn" (the agent loop's exit branch, agent.py:604), and a
    `.usage` that `observability.usage_record` can price. The usage check is not decoration: the Anthropic
    SDK leaves `cache_read_input_tokens` as None while the adapter sets 0, and both must reach the cost
    meter as 0 rather than as None (which would make the cost arithmetic raise mid-turn).
    """
    b = matrix.program(reply(text="ppGpp rose 18%."))
    r = b.client().messages.create(model="m", max_tokens=64, system="be terse",
                                   messages=[{"role": "user", "content": "hi"}], temperature=0.0)

    assert [x.type for x in r.content] == ["text"]
    assert "".join(x.text for x in r.content) == "ppGpp rose 18%."
    assert r.stop_reason == "end_turn"

    rec = observability.usage_record("agent", "m", r, 12.0, temperature=0.0)
    assert set(rec) >= {"role", "model", "input_tokens", "output_tokens", "cache_read_tokens",
                        "cache_creation_tokens", "latency_ms", "cost_usd"}, (
        "the cost-meter record is the LLM-2 seam's contract and must be the same dict on every provider")
    assert rec["model"] == "m", "the record resolves the model from the RESPONSE, so every provider must set it"
    assert rec["input_tokens"] == _IN_TOKENS and rec["output_tokens"] == _OUT_TOKENS
    assert rec["cache_read_tokens"] == 0 and rec["cache_creation_tokens"] == 0

    (req,) = b.sent
    assert b.system_text(req) == "be terse", "the system prompt must reach the wire on every provider"
    assert b.last_user_text(req) == "hi"


# ======================================================================================================
# interaction 2 — the forced-tool emit (council._emit)
# ======================================================================================================
_VERDICT_TOOL = {"name": "verdict", "description": "emit the judge's verdict",
                 "input_schema": {"type": "object",
                                  "properties": {"falsifiable": {"type": "boolean"},
                                                 "rationale": {"type": "string"}},
                                  "required": ["falsifiable"]}}


@matrix_over_providers
def test_the_council_forced_tool_emit_round_trips_through_every_provider(matrix):
    """`council._emit` (council.py:301) is the SINGLE forced-tool call site — every proposer, skeptic, judge,
    gate and librarian round goes through it — so it is the one function whose provider-portability decides
    whether the Council runs at all off Anthropic.

    This calls the real `_emit` rather than re-building its request, which is the point: a change to how it
    pins `tool_choice`, wraps `system` in cache-control blocks, attaches the tool schema or serialises the
    payload is caught HERE, on both legs, instead of passing on Anthropic and breaking silently on the
    translation. The wire assertions are the four things the emit depends on arriving intact: the forced tool
    NAME, its schema (`input_schema` on one side, `function.parameters` on the other), the role's system
    prompt, and the JSON payload.
    """
    from cellarium import council

    b = matrix.program(reply(tool_calls=[("tu_1", "verdict", {"falsifiable": True, "rationale": "n=8 seeds"})]))
    out = council._emit(b.client(), "m", "You are the judge.", _VERDICT_TOOL,
                        {"question": "does argS knockdown slow elongation?"}, max_tokens=256)

    assert out == {"falsifiable": True, "rationale": "n=8 seeds"}, "the emit must return a plain input dict"
    assert len(b.sent) == 1, "a well-formed emit must not trip _emit's empty-input retry"

    (req,) = b.sent
    assert b.forced_tool(req) == "verdict", (
        "the tool_choice that FORCES this one tool did not survive translation; a degraded choice lets the "
        "model answer in prose and every Council round returns {}")
    view = b.tools_view(req)
    assert set(view) == {"verdict"}
    assert view["verdict"]["description"] == "emit the judge's verdict"
    assert view["verdict"]["schema"]["properties"]["falsifiable"]["type"] == "boolean", (
        "the tool SCHEMA must reach the wire, or the model emits an unvalidated shape")
    assert "You are the judge." in b.system_text(req)
    assert json.loads(b.last_user_text(req))["question"].startswith("does argS")


@matrix_over_providers
def test_an_empty_emit_is_retried_on_every_provider(matrix):
    """`_emit` retries once when the tool input comes back empty (a truncated or degenerate emit) and gives
    up with {} rather than raising. That recovery is written against the Anthropic response shape — `for
    block in resp.content: if block.type == "tool_use" and block.input` — so it only works elsewhere if the
    adapter reports an empty tool call as a tool_use block with a falsy `input`, not as text or an exception.
    """
    from cellarium import council

    b = matrix.program(reply(tool_calls=[("tu_1", "verdict", {})]),
                       reply(tool_calls=[("tu_2", "verdict", {"falsifiable": False})]))
    out = council._emit(b.client(), "m", "judge", _VERDICT_TOOL, {"question": "q"}, max_tokens=256)
    assert out == {"falsifiable": False}
    assert len(b.sent) == 2, "the empty first emit must have been retried, not returned"


# ======================================================================================================
# interaction 3 — a tool-use turn the agent loop consumes
# ======================================================================================================
@matrix_over_providers
def test_the_agent_tool_loop_completes_through_every_provider(matrix, monkeypatch):
    """The interaction no per-hop unit test can cover, run on every provider.

    The loop reads `.stop_reason`, dispatches `tu.name(tu.input)`, writes `_to_dict(block)` back into the
    history, re-sends that history and branches on the SECOND response. A shape that survives one hop and
    corrupts the next passes every translation test in tests/test_openai_compat.py. Streaming is part of it:
    `agent._run_turn` always streams, so both fakes serve fragmented chunks.

    The load-bearing assertion is the last one. Every provider requires the tool RESULT to reference the id
    of the call that produced it (Anthropic: `tool_result.tool_use_id`; Chat Completions: a `role:"tool"`
    message's `tool_call_id`). If that link breaks, turn two 400s at a live endpoint and never here — the
    error only exists on the wire — so it is checked from the recorded request instead.
    """
    from cellarium import agent, tools

    b = matrix.program(
        reply(text="Checking.", tool_calls=[("tu_1", "model_capabilities",
                                             {"capability": "ppgpp_stringent_response"})]),
        reply(text="ppGpp is represented under steady_state."))
    dispatched = []
    monkeypatch.setattr(agent.llm, "client", lambda **kw: b.client())
    monkeypatch.setattr(tools, "dispatch",
                        lambda name, args: (dispatched.append((name, args)), {"known": True})[1])

    history = [{"role": "user", "content": "is ppGpp represented?"}]
    out = agent.converse(history, model="m", max_turns=3)

    assert "ppGpp is represented" in out, f"the loop did not reach a synthesis: {out!r}"
    assert dispatched == [("model_capabilities", {"capability": "ppgpp_stringent_response"})], (
        "tools.dispatch takes a DICT — a provider whose arguments arrive as a JSON string breaks every tool")
    assert len(b.sent) == 2, f"the loop must come back for a second turn after the tool result: {len(b.sent)}"

    first = b.sent[0]
    assert b.system_text(first) == agent.SYSTEM, "the whole Cellwright system prompt must reach every provider"
    assert "model_capabilities" in b.tools_view(first), "the tool definitions must reach every provider"

    calls, results = b.tool_link(b.sent[1])
    assert calls == ["tu_1"], f"the assistant's tool call is missing from turn two's history: {calls}"
    assert results == ["tu_1"], (
        f"the tool result does not reference its call id ({results} vs {calls}) — a live endpoint 400s here")


# ======================================================================================================
# the seam itself: every provider constructible, no key and no network
# ======================================================================================================
@matrix_over_providers
def test_every_supported_provider_is_constructible_through_the_seam(matrix, monkeypatch):
    """`llm.client()` must return a working client for every name in `llm.SUPPORTED`, not just the default.

    tests/test_llm_seam.py checks the negative (an UNsupported provider raises by name); this is the positive,
    and it is the check that catches a provider being listed as supported while its branch is missing or its
    constructor signature has drifted. `max_retries` is asserted because LLM-5's values are deliberate (4 in
    the runtime, 6 in the eval sweeps, 1 on the fast router and the credential probe) and a client that
    silently used the SDK default of 2 would change eval behaviour under load with no visible symptom.
    """
    matrix.install_sdk(monkeypatch)
    c = llm.client(max_retries=6)
    assert hasattr(c, "messages"), f"{llm.PROVIDER} client exposes no `messages` surface"
    for method in ("create", "stream", "count_tokens"):
        assert hasattr(c.messages, method), f"{llm.PROVIDER} client cannot {method}"
    assert matrix.retries_of(c) == 6, "the caller's deliberate retry count must reach the provider's client"


@pytest.mark.parametrize("alias", sorted(llm._PROVIDER_ALIASES))
def test_an_openai_compatible_alias_reaches_the_adapter_rather_than_an_error(alias, monkeypatch):
    """vllm / ollama / local / openai_compatible are how "run Cellarium with no external API" is spelled, so
    they are provider names a user actually types. `set_active_provider` normalises them, but `client()` also
    accepts a raw alias (an operator's `CELLARIUM_LLM_PROVIDER=vllm` export) — both doors must open onto the
    same adapter, and neither may fall through to the NotImplementedError branch.
    """
    _OpenAIBackend.install_sdk(monkeypatch)
    assert llm.set_active_provider(alias) == "openai", "the alias must normalise to a SUPPORTED name"

    monkeypatch.setattr(llm, "PROVIDER", alias)          # as a raw operator export leaves it
    assert isinstance(llm.client(), oc.OpenAICompatClient)


def test_the_openai_leg_needs_no_openai_package(monkeypatch):
    """CI installs `.[dev,hf,surrogate]` and `openai` is in none of them, so the OpenAI leg above would be a
    silent no-op — or a red build — if anything in it imported the package.

    Rather than trust that, this blocks the import outright (a None entry in sys.modules is what CPython
    treats as "halted") and re-runs the core interactions through the adapter. It also pins the OTHER half:
    `llm.client()` under the openai provider DOES construct the real SDK, and must fail with a message naming
    the package and the extra that installs it — the difference between a two-second fix and a stack trace.
    """
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ImportError):
        importlib.import_module("openai")   # proves the block is in force BEFORE anything below is claimed

    b = _OpenAIBackend().program(
        reply(text="ok"),
        reply(tool_calls=[("tu_1", "verdict", {"falsifiable": True})]))
    r = b.client().messages.create(model="m", messages=[{"role": "user", "content": "hi"}])
    assert r.content[0].text == "ok"
    with b.client().messages.stream(model="m", messages=[{"role": "user", "content": "hi"}]) as st:
        st.until_done()
    assert st.get_final_message().stop_reason == "tool_use"

    monkeypatch.setattr(llm, "PROVIDER", "openai")
    with pytest.raises(ImportError) as e:
        llm.client()
    assert "openai" in str(e.value) and "install" in str(e.value).lower(), str(e.value)
