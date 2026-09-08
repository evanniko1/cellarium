"""LLM-7b — an OpenAI-compatible adapter behind the `llm` seam.

WHY THIS SHAPE. Twelve call sites already speak the Anthropic request/response shape, and that shape is the
more expressive of the two (typed content blocks, an explicit `system`, `tool_use`/`tool_result` as first-
class blocks). Re-writing those call sites to a lowest-common-denominator interface would touch every
caller and lose information. So the adapter presents the **incumbent** shape and translates inward: a
caller keeps writing `client.messages.create(system=…, tools=…)` and gets back something with `.content`
blocks, `.stop_reason` and `.usage`, whichever provider actually served it.

WHAT "OpenAI-compatible" BUYS. One adapter covers OpenAI, most hosted endpoints, and local vLLM / Ollama /
LM Studio, because they all expose `/v1/chat/completions`. `OPENAI_BASE_URL` is what points it at a local
server, so running Cellarium with no external API at all is a base-URL change rather than new code.

WHAT IS FAITHFUL, AND WHAT CANNOT BE.

  * `system` — Anthropic takes a top-level system (optionally a list of blocks with `cache_control`).
    Chat Completions takes a leading `system` message. Text is joined; `cache_control` is DROPPED, because
    OpenAI-style endpoints cache automatically and there is nothing to hand them. Prompt-cache *savings*
    therefore do not transfer, and `usage_record` will report 0 cache tokens rather than pretending.
  * `tool_use` / `tool_result` blocks map onto `tool_calls` and `role:"tool"` messages. Anthropic sends
    tool arguments as an object; OpenAI sends a JSON *string*, so arguments are parsed on the way back. A
    model emitting malformed JSON yields `{}` with the raw string preserved under `_raw`, rather than
    raising -- the tool dispatcher already reports an unknown/invalid call clearly, and a parse error here
    would surface as a stack trace instead of a bad tool call.
  * `count_tokens` — Anthropic has an endpoint for it; Chat Completions has none. `tiktoken` is used when
    installed, else a chars//4 estimate. `agent._context_tokens` already treats this as best-effort and
    falls back, so an approximate answer degrades compaction timing rather than correctness.
  * `stop_reason` — `tool_calls` -> `tool_use`, `stop` -> `end_turn`, `length` -> `max_tokens`.

THINKING / REASONING is not translated. A caller passing `thinking=` gets it dropped with the rest of the
unknown kwargs; `temperature_for` already returns None whenever thinking is on, so the sampling policy
stays correct either way. Reasoning-effort parameters differ enough per endpoint that guessing would be
worse than omitting.
"""
from __future__ import annotations

import json
import os
from typing import Any

_STOP = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens",
         "content_filter": "stop_sequence", "function_call": "tool_use"}


class Block:
    """Duck-types an Anthropic content block, including `model_dump()` — `agent._to_dict` calls it."""

    __slots__ = ("type", "text", "id", "name", "input")

    def __init__(self, type: str, *, text=None, id=None, name=None, input=None):  # noqa: A002
        self.type, self.text, self.id, self.name, self.input = type, text, id, name, input

    def model_dump(self) -> dict:
        if self.type == "text":
            return {"type": "text", "text": self.text or ""}
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input or {}}

    def __repr__(self) -> str:
        return f"Block({self.type!r}, name={self.name!r})"


class Usage:
    """Anthropic field names, because `observability.usage_record` reads exactly these."""

    __slots__ = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")

    def __init__(self, input_tokens=0, output_tokens=0):
        self.input_tokens = int(input_tokens or 0)
        self.output_tokens = int(output_tokens or 0)
        # Not pretended: OpenAI-style endpoints do not report cache tokens in these terms.
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0


class Response:
    __slots__ = ("content", "stop_reason", "usage", "model", "id", "_request_id")

    def __init__(self, content, stop_reason, usage, model, id=None):  # noqa: A002
        self.content, self.stop_reason, self.usage = content, stop_reason, usage
        self.model, self.id, self._request_id = model, id, id


# ----------------------------------------------------------------------------------------------------
# request translation
# ----------------------------------------------------------------------------------------------------
def _text_of(content) -> str:
    """Anthropic content (str | list of blocks) -> plain text."""
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        d = b if isinstance(b, dict) else getattr(b, "model_dump", lambda: {})()
        if d.get("type") == "text":
            out.append(d.get("text") or "")
    return "\n".join(x for x in out if x)


def to_chat_messages(messages: list, system=None) -> list[dict]:
    """Anthropic messages (+ system) -> Chat Completions messages."""
    out: list[dict] = []
    sys_text = _text_of(system) if system is not None else ""
    if sys_text:
        out.append({"role": "system", "content": sys_text})

    for m in messages or []:
        role, content = m.get("role"), m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        texts, tool_calls, tool_results = [], [], []
        for b in content or []:
            d = b if isinstance(b, dict) else getattr(b, "model_dump", lambda: {})()
            t = d.get("type")
            if t == "text":
                texts.append(d.get("text") or "")
            elif t == "tool_use":
                tool_calls.append({"id": d.get("id"), "type": "function",
                                   "function": {"name": d.get("name"),
                                                "arguments": json.dumps(d.get("input") or {}, default=str)}})
            elif t == "tool_result":
                c = d.get("content")
                tool_results.append({"role": "tool", "tool_call_id": d.get("tool_use_id"),
                                     "content": c if isinstance(c, str) else json.dumps(c, default=str)})

        if role == "assistant" and tool_calls:
            msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(texts) or None}
            msg["tool_calls"] = tool_calls
            out.append(msg)
        elif tool_results:
            # A tool_result turn is Anthropic-side a USER message; Chat Completions wants one `tool`
            # message per result, and they must follow the assistant turn that requested them.
            out.extend(tool_results)
            if texts and any(texts):
                out.append({"role": "user", "content": "\n".join(texts)})
        else:
            out.append({"role": role, "content": "\n".join(texts)})
    return out


def to_chat_tools(tools) -> list[dict] | None:
    if not tools:
        return None
    return [{"type": "function",
             "function": {"name": t["name"], "description": t.get("description", ""),
                          "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}}
            for t in tools]


def to_chat_tool_choice(tc):
    """Anthropic tool_choice -> Chat Completions. `{"type":"none"}` is how the agent forbids further tool
    calls WITHOUT dropping the definitions, so it must survive the translation intact."""
    if tc is None:
        return None
    t = tc.get("type")
    if t == "tool" and tc.get("name"):
        return {"type": "function", "function": {"name": tc["name"]}}
    return {"any": "required", "auto": "auto", "none": "none"}.get(t)


def from_chat_response(raw) -> Response:
    """Chat Completions response -> the Anthropic-shaped object the call sites consume."""
    choice = (raw.choices or [None])[0]
    msg = getattr(choice, "message", None)
    blocks: list[Block] = []
    text = getattr(msg, "content", None)
    if text:
        blocks.append(Block("text", text=text))
    for tc in (getattr(msg, "tool_calls", None) or []):
        fn = getattr(tc, "function", None)
        args = getattr(fn, "arguments", "") or "{}"
        try:
            parsed = json.loads(args)
            if not isinstance(parsed, dict):
                parsed = {"_raw": args}
        except (ValueError, TypeError):
            # A malformed emit becomes a bad tool CALL, which dispatch reports clearly, rather than a
            # stack trace from inside the adapter.
            parsed = {"_raw": args}
        blocks.append(Block("tool_use", id=getattr(tc, "id", None),
                            name=getattr(fn, "name", None), input=parsed))
    u = getattr(raw, "usage", None)
    usage = Usage(getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))
    finish = getattr(choice, "finish_reason", None)
    return Response(blocks, _STOP.get(finish, finish or "end_turn"), usage,
                    getattr(raw, "model", None), getattr(raw, "id", None))


# ----------------------------------------------------------------------------------------------------
# the client
# ----------------------------------------------------------------------------------------------------
def _estimate_tokens(messages, system, tools) -> int:
    blob = json.dumps([messages, system, tools], default=str)
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(blob))
    except Exception:
        return len(blob) // 4


class _Stream:
    """Context manager matching the Anthropic streaming surface `_run_turn` uses."""

    def __init__(self, raw_stream):
        self._raw, self._blocks, self._deltas = raw_stream, [], []
        self._finish, self._model, self._id = None, None, None
        self._tools: dict[int, dict] = {}
        self._usage = Usage()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        for chunk in self._raw:
            self._absorb(chunk)
            for ch in (chunk.choices or []):
                piece = getattr(getattr(ch, "delta", None), "content", None)
                if piece:
                    yield piece

    def _absorb(self, chunk) -> None:
        self._model = getattr(chunk, "model", None) or self._model
        self._id = getattr(chunk, "id", None) or self._id
        u = getattr(chunk, "usage", None)
        if u is not None:
            self._usage = Usage(getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))
        for ch in (chunk.choices or []):
            self._finish = getattr(ch, "finish_reason", None) or self._finish
            delta = getattr(ch, "delta", None)
            if delta is None:
                continue
            if getattr(delta, "content", None):
                self._deltas.append(delta.content)
            for tc in (getattr(delta, "tool_calls", None) or []):
                # Tool calls arrive fragmented across chunks and are keyed by index, not id.
                slot = self._tools.setdefault(getattr(tc, "index", 0), {"id": None, "name": None, "args": ""})
                slot["id"] = getattr(tc, "id", None) or slot["id"]
                fn = getattr(tc, "function", None)
                if fn is not None:
                    slot["name"] = getattr(fn, "name", None) or slot["name"]
                    slot["args"] += getattr(fn, "arguments", None) or ""

    def until_done(self) -> None:
        for chunk in self._raw:
            self._absorb(chunk)

    def get_final_message(self) -> Response:
        blocks: list[Block] = []
        text = "".join(self._deltas)
        if text:
            blocks.append(Block("text", text=text))
        for _i, slot in sorted(self._tools.items()):
            try:
                parsed = json.loads(slot["args"] or "{}")
                if not isinstance(parsed, dict):
                    parsed = {"_raw": slot["args"]}
            except (ValueError, TypeError):
                parsed = {"_raw": slot["args"]}
            blocks.append(Block("tool_use", id=slot["id"], name=slot["name"], input=parsed))
        return Response(blocks, _STOP.get(self._finish, self._finish or "end_turn"),
                        self._usage, self._model, self._id)


class _Messages:
    def __init__(self, raw):
        self._raw = raw

    def _kw(self, *, model, max_tokens=None, messages=None, system=None, tools=None,
            tool_choice=None, temperature=None, **_ignored) -> dict:
        kw: dict[str, Any] = {"model": model, "messages": to_chat_messages(messages, system)}
        if max_tokens:
            kw["max_tokens"] = max_tokens
        if temperature is not None:
            kw["temperature"] = temperature
        t = to_chat_tools(tools)
        if t:
            kw["tools"] = t
            tc = to_chat_tool_choice(tool_choice)
            if tc is not None:
                kw["tool_choice"] = tc
        return kw

    def create(self, **kwargs) -> Response:
        return from_chat_response(self._raw.chat.completions.create(**self._kw(**kwargs)))

    def stream(self, **kwargs) -> _Stream:
        kw = self._kw(**kwargs)
        kw["stream"] = True
        kw["stream_options"] = {"include_usage": True}
        return _Stream(self._raw.chat.completions.create(**kw))

    def count_tokens(self, *, model=None, messages=None, system=None, tools=None, **_):
        class _Count:
            def __init__(self, n):
                self.input_tokens = n
        return _Count(_estimate_tokens(to_chat_messages(messages, system), None, to_chat_tools(tools)))


class OpenAICompatClient:
    """`llm.client()` returns this when CELLARIUM_LLM_PROVIDER selects an OpenAI-compatible endpoint."""

    def __init__(self, max_retries: int = 4, **kwargs):
        try:
            import openai
        except ImportError as e:                                     # noqa: F841
            raise ImportError(
                "the OpenAI-compatible provider needs the `openai` package: pip install 'cellarium[openai]'"
            ) from None
        base_url = kwargs.pop("base_url", None) or os.environ.get("OPENAI_BASE_URL") or None
        self._raw = openai.OpenAI(max_retries=max_retries, base_url=base_url, **kwargs)
        self.messages = _Messages(self._raw)
