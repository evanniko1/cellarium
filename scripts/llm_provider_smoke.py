"""LLM-7c — live smoke of a provider endpoint. Complements the fake-endpoint suite; needs a real server.

tests/test_openai_compat.py proves the TRANSLATION. It cannot prove a real server accepts the payload,
which is the other half and the one that catches schema quibbles: a tool schema an endpoint rejects, a
tool_choice it will not honour, a role:"tool" message it refuses to sequence. This drives four things
against a live endpoint — a plain completion, the forced-tool emit the Council depends on, a streamed
tool call, and the agent loop dispatching a REAL Cellarium tool.

    OPENAI_BASE_URL=http://localhost:11434/v1 SMOKE_MODEL=llama3.1:8b python scripts/llm_provider_smoke.py

Ollama needs no key and costs nothing, so this is repeatable. MEASURED against local Ollama: 4/4 for
llama3.1:8b, mistral-nemo, hermes3:8b and llama3.2:3b.

Two results worth keeping, because they are about the MODELS and not the adapter — which is the
distinction this script exists to keep visible:

  * qwen3:8b scored 2/4. Both failures were `stop=max_tokens` with EMPTY content: it is a reasoning model
    and spent the 64/256-token budget thinking before emitting anything. The two tests with larger budgets
    passed. That is the documented "thinking is not translated" caveat showing up in practice, not a
    translation bug.
  * hermes3:8b emitted the forced tool with arguments that ignore the schema ({"n": 8, "+": 66}), and
    mistral-nemo answered the science question without calling the tool at all — and got it wrong. The
    plumbing carried both faithfully. A small model can drive the adapter and still be useless for the
    science, so a green smoke is a statement about transport, never about capability.
"""
from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, "src")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ["CELLARIUM_LLM_PROVIDER"] = "openai"
os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"
os.environ.setdefault("OPENAI_API_KEY", "ollama-local-no-key-required")

MODEL = os.environ.get("SMOKE_MODEL", "llama3.1:8b")

from cellarium import llm  # noqa: E402

results: dict[str, str] = {}


def check(name, fn):
    try:
        detail = fn()
        results[name] = f"OK   {detail}"
    except Exception as e:                                    # noqa: BLE001
        results[name] = f"FAIL {type(e).__name__}: {str(e)[:160]}"
        traceback.print_exc()
    print(f"[{name}] {results[name]}", flush=True)


print(f"provider={llm.PROVIDER}  base_url={os.environ['OPENAI_BASE_URL']}  model={MODEL}\n", flush=True)
client = llm.client(max_retries=2)
print(f"client: {type(client).__name__}\n", flush=True)


# 1. plain completion -------------------------------------------------------------------------------
def plain():
    r = client.messages.create(model=MODEL, max_tokens=64, system="Answer in exactly one short sentence.",
                               messages=[{"role": "user", "content": "What is E. coli?"}], temperature=0.0)
    text = "".join(b.text for b in r.content if b.type == "text")
    assert text.strip(), "no text came back"
    assert r.stop_reason in ("end_turn", "max_tokens"), r.stop_reason
    assert r.usage.input_tokens > 0, "no usage reported"
    return f'stop={r.stop_reason} in={r.usage.input_tokens} out={r.usage.output_tokens} "{text.strip()[:60]}"'


# 2. the forced-tool emit council._emit depends on --------------------------------------------------
def forced_tool():
    tool = {"name": "verdict", "description": "Emit the verdict for the claim.",
            "input_schema": {"type": "object",
                             "properties": {"verdict": {"type": "string",
                                                        "enum": ["supported", "refuted", "underpowered"]},
                                            "rationale": {"type": "string"}},
                             "required": ["verdict"]}}
    r = client.messages.create(
        model=MODEL, max_tokens=256, system="You are a juror. Emit the verdict tool.",
        messages=[{"role": "user", "content":
                   "Claim: argS knockout raises ppGpp. Evidence: n=8, +66%, p<0.01. Emit the verdict tool."}],
        tools=[tool], tool_choice={"type": "tool", "name": "verdict"}, temperature=0.0)
    tus = [b for b in r.content if b.type == "tool_use"]
    assert tus, f"no tool_use block; stop={r.stop_reason} content={[b.type for b in r.content]}"
    assert tus[0].name == "verdict", tus[0].name
    assert isinstance(tus[0].input, dict), type(tus[0].input)
    return f"stop={r.stop_reason} verdict={json.dumps(tus[0].input)[:80]}"


# 3. streaming, with a tool call --------------------------------------------------------------------
def streamed_tool():
    tool = {"name": "get_growth_rate", "description": "Growth rate for a design.",
            "input_schema": {"type": "object", "properties": {"design": {"type": "string"}},
                             "required": ["design"]}}
    deltas = []
    with client.messages.stream(model=MODEL, max_tokens=256,
                                system="Use the tool when asked about a design.",
                                messages=[{"role": "user",
                                           "content": "What is the growth rate of wildtype/basal? Use the tool."}],
                                tools=[tool], temperature=0.0) as st:
        for d in st.text_stream:
            deltas.append(d)
        final = st.get_final_message()
    tus = [b for b in final.content if b.type == "tool_use"]
    kinds = [b.type for b in final.content]
    if not tus:
        return f"(model answered without a tool) stop={final.stop_reason} blocks={kinds} text={len(''.join(deltas))}ch"
    assert isinstance(tus[0].input, dict), "fragmented arguments did not reassemble into a dict"
    return f"stop={final.stop_reason} tool={tus[0].name} input={json.dumps(tus[0].input)[:60]}"


# 4. the real agent loop, real Cellarium tools ------------------------------------------------------
def agent_loop():
    from cellarium import agent
    seen = []
    out = agent.converse(
        [{"role": "user", "content":
          "Use the model_capabilities tool to check whether 'ppgpp_stringent_response' is represented, "
          "then state the answer in one sentence."}],
        model=MODEL, max_turns=4, on_tool=lambda n, a, r: seen.append(n))
    return f"tools={seen or 'none'} answer={(out or '')[:110]!r}"


check("1 plain completion", plain)
check("2 forced-tool emit", forced_tool)
check("3 streamed tool call", streamed_tool)
check("4 agent tool loop", agent_loop)

print("\n" + "=" * 70)
ok = sum(1 for v in results.values() if v.startswith("OK"))
print(f"SMOKE: {ok}/{len(results)} passed against {MODEL} @ {os.environ['OPENAI_BASE_URL']}")
for k, v in results.items():
    print(f"  {k:24} {v[:150]}")
