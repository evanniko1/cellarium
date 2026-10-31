"""LLM-7a — the provider seam holds only if nothing goes around it.

A seam is a claim about where a dependency lives, and a claim nobody checks is a comment. `llm.py` exists
so that swapping providers is one adapter rather than an audit of the tree; that is only true while every
client construction goes through it. These tests are the mechanical half of that guarantee.

Run: python -m pytest tests/test_llm_seam.py
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEAM = ROOT / "src" / "cellarium" / "llm.py"

# The runtime AND the eval harnesses. evals/ was migrated in the same LLM-7a thread; including it here is
# the point -- the sweeps are exactly where a second provider has to work for LLM-7d to mean anything, and a
# seam that the harnesses bypass would let the ablation silently run on the wrong backbone.
RUNTIME = [ROOT / "src" / "cellarium", ROOT / "apps", ROOT / "evals"]


def _py_files():
    for base in RUNTIME:
        for p in sorted(base.rglob("*.py")):
            if p.resolve() != SEAM.resolve():
                yield p


def _imports(path: Path) -> set[str]:
    """Top-level module names imported by this file, from the syntax tree rather than a text grep.

    A grep would match the word in a docstring -- credentials.py and llm.py both discuss `anthropic` in
    prose -- and would miss `__import__("anthropic")`. Parsing asks the question that is actually meant.
    """
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_no_runtime_module_imports_the_provider_sdk_directly():
    """The invariant LLM-7a buys. `llm.py` is the only module allowed to know the vendor."""
    offenders = [str(p.relative_to(ROOT)) for p in _py_files() if "anthropic" in _imports(p)]
    assert not offenders, (
        "these modules import the provider SDK directly, so a provider swap would have to edit them: "
        + ", ".join(offenders) + ". Construct clients via `llm.client(max_retries=...)` instead.")


def test_no_runtime_module_constructs_a_client_itself():
    """Belt and braces: catch `anthropic.Anthropic(...)` even if the import were obtained some other way."""
    offenders = []
    for p in _py_files():
        src = p.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            if "Anthropic(" in line and not line.lstrip().startswith("#"):
                offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert not offenders, "direct client construction outside the seam: " + ", ".join(offenders)


def test_the_seam_refuses_an_unimplemented_provider_by_name():
    """A silent fallback to Anthropic would run an entire eval on a model the operator did not ask for and
    report it under the requested name. The failure has to be loud and has to say what is supported."""
    from cellarium import llm

    real = llm.PROVIDER
    try:
        llm.PROVIDER = "gemini"          # genuinely unimplemented; "openai" landed with LLM-7b
        with pytest.raises(NotImplementedError) as e:
            llm.client()
        msg = str(e.value)
        assert "gemini" in msg, msg
        for supported in llm.SUPPORTED:
            assert supported in msg, f"the error must name what IS supported; missing {supported}: {msg}"
    finally:
        llm.PROVIDER = real


def test_the_sampling_policy_moved_without_changing_behaviour():
    """`agent.temperature_for` is public surface -- apps/server.py, robustness.py and tests all use that
    name. Moving the definition into the seam must not move the name or the answers."""
    from cellarium import agent, llm

    assert agent.temperature_for is llm.temperature_for
    assert agent.TEMPERATURE == llm.TEMPERATURE
    for model in ("claude-sonnet-5", "claude-opus-4-8", "claude-fable-5", "claude-mythos-5"):
        assert llm.temperature_for(model) is None, f"{model} rejects an explicit temperature"
    assert llm.temperature_for("claude-haiku-4-5-20251001") == llm.TEMPERATURE
    assert llm.temperature_for(None) == llm.TEMPERATURE
    assert llm.temperature_for("claude-haiku-4-5-20251001", thinking=True) is None


def test_a_non_claude_model_is_pinned_rather_than_silently_unpinned():
    """The family list is Claude-specific by nature. Under another provider it must simply not match, so an
    unknown model gets the pinned temperature -- and the caller's retry-without-it path covers a refusal.
    Defaulting the other way would silently unpin sampling for every non-Claude model.
    """
    from cellarium import llm

    for model in ("gpt-4o", "llama-3.1-70b", "mistral-large", "qwen2.5-72b-instruct"):
        assert llm.temperature_for(model) == llm.TEMPERATURE, model


# --- LLM-8: no call site may pin a temperature behind the policy's back ------------------------------
#
# The failure this comes from: `robustness.consistency_panel` passed a literal `temperature=0.0` to
# `council._emit`, whose default judge is claude-sonnet-5, which answers 400 -- so EVERY juror panel died
# before a single vote while the Council (which passes None) ran fine. `agent.py`'s own header records the
# same failure hitting every Cellwright call once already. Both were fixed by hand, and nothing stopped the
# next one, which is what this test is for.

def _temperature_literals(path: Path) -> list[str]:
    """Call sites that hand a CONSTANT temperature to a model call, from the syntax tree.

    Two shapes, because the second is the obvious way round the first: `create(temperature=0.0)` and
    `create(**{"temperature": 0.0})`. A NAME (`temperature=temp`) is fine -- that is the policy's answer
    being passed along, which is the whole point of having one."""
    out = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = (fn.attr if isinstance(fn, ast.Attribute) else
                fn.id if isinstance(fn, ast.Name) else "")
        owner = (fn.value.attr if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Attribute)
                 else fn.value.id if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                 else "")
        is_model_call = name in ("_emit", "emit") or (name == "create" and owner == "messages")
        if not is_model_call:
            continue
        for kw in node.keywords:
            if kw.arg == "temperature" and isinstance(kw.value, ast.Constant):
                out.append(f"{path.name}:{node.lineno} {name}(temperature={kw.value.value!r})")
            if kw.arg is None and isinstance(kw.value, ast.Dict):      # **{"temperature": 0.0}
                for k, v in zip(kw.value.keys, kw.value.values):
                    if (isinstance(k, ast.Constant) and k.value == "temperature"
                            and isinstance(v, ast.Constant)):
                        out.append(f"{path.name}:{node.lineno} {name}(**{{'temperature': "
                                   f"{v.value!r}}})")
    return out


def test_no_call_site_pins_a_LITERAL_temperature_outside_the_policy_module():
    """LLM-8. Which temperature a path wants is its own decision; whether the model will ACCEPT it is
    provider policy, and a literal at the call site answers the second question without asking."""
    offenders = [o for p in _py_files() for o in _temperature_literals(p)]
    assert not offenders, (
        "these model calls pin a temperature without consulting the policy, so they break on any model "
        "that refuses that value: " + "; ".join(offenders)
        + ". Pass `llm.sendable_temperature(model, YOUR_VALUE)` instead -- it answers with None when the "
          "model will not take that value, and omitting the parameter is what keeps the call alive.")


def test_the_policy_knows_WHICH_VALUES_a_reasoning_model_takes_not_just_whether():
    """MEASURED against the live API on 2026-10-30, because the error message is misleading. On
    claude-sonnet-5: `temperature=1.0` is ACCEPTED (stop_reason end_turn, a text block); `0.3` and `0.0`
    both come back 400 "`temperature` is deprecated for this model". So that family does not refuse the
    PARAMETER, it refuses any value but the one the API forces -- and the forced value is 1.0.

    The distinction is not academic: the Council pins 1.0 and the extractor pins 0.0, one of those is
    sendable to a reasoning model and the other is not, and before this they were decided by two different
    family lists in two different modules."""
    from cellarium import llm

    assert llm.sendable_temperature("claude-sonnet-5", 1.0) == 1.0
    for want in (0.0, 0.3, 0.7, 1.5):
        assert llm.sendable_temperature("claude-sonnet-5", want) is None, want
    assert llm.sendable_temperature("claude-haiku-4-5-20251001", 0.3) == 0.3
    assert llm.sendable_temperature("claude-haiku-4-5-20251001", 1.0) == 1.0
    # Thinking forces temperature=1 whatever the model, so only 1.0 survives it.
    assert llm.sendable_temperature("claude-haiku-4-5-20251001", 0.0, thinking=True) is None
    assert llm.sendable_temperature("claude-sonnet-5", 1.0, thinking=True) == 1.0
    # ... and the old entry point is the same question with the global value, so it cannot drift from it.
    assert llm.temperature_for("claude-sonnet-5") is llm.sendable_temperature("claude-sonnet-5",
                                                                             llm.TEMPERATURE)
