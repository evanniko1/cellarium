"""AG-5 — `converse` must never hand its caller an empty string as though it were an answer.

THE DEFECT, and how it was found. The AG-2b tool probe recorded a case that made eight successful tool calls
and returned **zero characters**. Nothing errored; the agent enumerated the corpus sensibly and then produced
nothing. Every surface renders that the same way a real empty answer would: the app shows a blank reply, the
eval scores a 0-character response, and neither can tell *"it had nothing to say"* from *"it was never
asked"*. That is the silent-absence class this repository keeps finding — an absence reported as a fact.

WHERE IT LIVED. `converse` has two exits. The forced-synthesis path (budget exhausted, tools disabled) has
always ended with `... or "(stopped: reached max turns without a synthesis)"`. The NORMAL path — the model
stops requesting tools, so the turn is over — returned `reconcile.check_and_annotate(...)` directly, with no
guard. A turn that ends with `stop_reason="end_turn"` and no text blocks therefore returned `""`.

WHY THESE TESTS FAKE THE CLIENT RATHER THAN CALL A MODEL. The condition is a specific SHAPE of API response —
a final turn carrying no text — which a live model produces only occasionally (the probe saw it once in three
runs of the same question, and an instrumented re-run of that same question called seventeen tools and ended
on the other exit). Reproducing it by asking a real model would be paying for a coin flip. Constructing the
response is exact, free, and deterministic.

WHAT IS DELIBERATELY NOT ASSERTED: any particular wording. The tests require a non-empty answer that names the
`stop_reason`, because that is what makes the outcome diagnosable rather than merely non-blank.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class _Block:
    def __init__(self, type_, text=None):
        self.type = type_
        if text is not None:
            self.text = text

    def model_dump(self):
        d = {"type": self.type}
        if hasattr(self, "text"):
            d["text"] = self.text
        return d


class _Usage:
    input_tokens = output_tokens = 0
    cache_read_input_tokens = cache_creation_input_tokens = 0


class _Resp:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Usage()
        self.model = "fake"


class _Stream:
    """`agent._run_turn` consumes the STREAMING surface, so the fake has to present that shape."""

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter(getattr(b, "text", "") for b in self._resp.content if getattr(b, "type", None) == "text")

    def until_done(self):
        return None

    def get_final_message(self):
        return self._resp


class _Messages:
    def __init__(self, resp):
        self._resp = resp
        self.calls = 0

    def stream(self, **kw):
        self.calls += 1
        return _Stream(self._resp)

    def create(self, **kw):
        self.calls += 1
        return self._resp


class _Client:
    def __init__(self, resp):
        self.messages = _Messages(resp)


@pytest.fixture()
def agent_mod(monkeypatch):
    from cellarium import agent, llm, reconcile

    # `converse` constructs its own client through the LLM-7a seam (`llm.client`), which is exactly the seam's
    # purpose — so the fake is injected THERE rather than through a parameter converse does not have.
    monkeypatch.setattr(agent, "_fake_client_for_tests", None, raising=False)
    monkeypatch.setattr(llm, "client", lambda *a, **k: _CURRENT["client"])
    # Patch the MODULE, not an attribute of `agent`: `converse` does `from . import reconcile` inside the
    # function body, so it resolves the name at call time and an `agent.reconcile` attribute never exists.
    # The annotator is a no-op here — PLAT-1's reconciliation is a separate concern and must not be able to
    # turn a non-empty answer empty (or vice versa) while this property is under test.
    monkeypatch.setattr(reconcile, "check_and_annotate", lambda t, *a, **k: t)
    return agent


_CURRENT: dict = {"client": None}


def _converse(agent, resp):
    _CURRENT["client"] = _Client(resp)
    return agent.converse([{"role": "user", "content": "anything"}], max_turns=4)


def test_a_turn_that_ends_with_no_text_and_no_tools_is_not_returned_as_an_empty_answer(agent_mod):
    """The exact shape the probe caught: the model just stops. THE regression test for AG-5."""
    out = _converse(agent_mod, _Resp([], stop_reason="end_turn"))
    assert out, "converse returned a falsy answer — the caller cannot distinguish this from a real empty reply"
    assert out.strip(), f"converse returned whitespace only: {out!r}"


def test_the_explanation_names_the_stop_reason_so_the_cause_is_diagnosable(agent_mod):
    """Non-blank is not enough. 'Something went wrong' that does not say WHAT is the same defect, politer."""
    out = _converse(agent_mod, _Resp([], stop_reason="max_tokens"))
    assert "max_tokens" in out, (
        f"the fallback must name the stop_reason that produced it; got {out!r}. Without it, an empty answer "
        "caused by a token cap looks identical to one caused by a refusal or a filtered response.")


def test_a_turn_carrying_only_non_text_blocks_also_gets_an_explanation(agent_mod):
    """Thinking-only or tool-result-only content is text-empty too, and must not slip through as ''."""
    out = _converse(agent_mod, _Resp([_Block("thinking")], stop_reason="end_turn"))
    assert out and out.strip(), f"a thinking-only final turn returned {out!r}"


def test_a_real_answer_is_returned_completely_unchanged(agent_mod):
    """The guard must be invisible when there IS an answer — no prefix, no suffix, no marker."""
    answer = "Nine designs up-regulate the efflux signature; the largest is KO:acrR at +38%."
    out = _converse(agent_mod, _Resp([_Block("text", answer)], stop_reason="end_turn"))
    assert out == answer, f"the guard altered a genuine answer: {out!r}"


def test_whitespace_only_text_counts_as_no_answer(agent_mod):
    """`"   ".strip()` is falsy, so this takes the same branch — pinned so a refactor cannot let it through."""
    out = _converse(agent_mod, _Resp([_Block("text", "   \n  ")], stop_reason="end_turn"))
    assert out.strip() and "stop_reason" in out, f"whitespace-only text returned {out!r}"


def test_both_exit_paths_guard_against_an_empty_answer():
    """The asymmetry IS the bug: one exit guarded and the other did not, for the same failure.

    Read from the source rather than exercised, because the forced-synthesis path needs a budget-exhausting
    conversation to reach. If a future refactor removes either guard, this fails and names which one.
    """
    src = (ROOT / "src" / "cellarium" / "agent.py").read_text(encoding="utf-8")
    assert 'or "(stopped: reached max turns without a synthesis)"' in src, (
        "the forced-synthesis exit lost its empty-answer guard")
    assert "return said or (" in src, (
        "the NORMAL exit lost its empty-answer guard — this is the AG-5 regression: a turn that ends with no "
        "text and no tool call would again return '' to the caller")
