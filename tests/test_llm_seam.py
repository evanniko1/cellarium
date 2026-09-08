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
        llm.PROVIDER = "openai"
        with pytest.raises(NotImplementedError) as e:
            llm.client()
        assert "openai" in str(e.value) and "anthropic" in str(e.value), str(e.value)
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
