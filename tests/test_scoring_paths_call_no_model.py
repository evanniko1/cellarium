"""L-2: no model call in a deterministic scoring path.

A score the paper reports should be arithmetic over stored records. If a scoring path reached a language model, a
re-run could change the number, and the number would carry a model's judgement under the name of a computation.
LLM-IDEA (arXiv:2610.11253) fails its pipeline when a model call appears in a scoring path; this is the same guard,
made at run time rather than by searching text, so an indirect call through an import is caught too.

`llm.client` is the one place in the tree that constructs a provider client, and the provider SDKs' constructors
sit behind it; all of them are replaced with a function that fails the test. Each scoring path then runs on the
stored records it scores in practice.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "evals", "scripts"):
    sys.path.insert(0, str(REPO / p))

from cellarium import gate, llm  # noqa: E402

RESULTS = REPO / "evals" / "results"


class ModelCallInScoringPath(AssertionError):
    pass


def _refuse(*a, **k):
    raise ModelCallInScoringPath("a scoring path tried to construct a model client")


@pytest.fixture()
def no_model(monkeypatch):
    monkeypatch.setattr(llm, "client", _refuse)
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _refuse)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", _refuse)
    try:
        import openai
        monkeypatch.setattr(openai, "OpenAI", _refuse, raising=False)
    except ImportError:          # CI installs no openai; nothing to construct there
        pass


def _load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_the_gate_evals_report_is_arithmetic(no_model):
    import run_gate_eval as ev
    for name in ("gate_eval_8framings.json", "gate_eval_heldout.json"):
        recs = _load(name)["records"]
        assert ev._report(recs)["n"] == len(recs)
    assert ev._heldout_report(_load("gate_eval_heldout.json")["records"])


def test_the_gates_decision_is_arithmetic(no_model):
    req = gate.Requirement(observable="trna_charging", granularity="per_isoacceptor", parser="manual")
    assert gate.decide(req, mode="steady_state").verdict == "refuse"


def test_the_m1m2_report_is_arithmetic(no_model):
    import arms_report
    rep = arms_report.build(_load("ablation_m1m2.json"), _load("audited_m1m2.json"))
    assert set(rep["arms"]) >= {"full", "proposer_only"}


def test_the_july_aggregation_is_arithmetic(no_model):
    import aggregate
    recs = [r for r in _load("ablation.json")["results"] if "error" not in r]
    assert aggregate.summarise(recs)["configs"]


def test_the_interface_comparison_is_arithmetic(no_model):
    import interface_only
    assert interface_only.score(_load("gate_eval_heldout.json")["records"])["n"] == 60


def test_the_guard_fails_a_path_that_reaches_a_model(no_model):
    def scoring_path_with_a_judge():
        return llm.client().messages.create(model="x", max_tokens=1, messages=[])
    with pytest.raises(ModelCallInScoringPath):
        scoring_path_with_a_judge()
