"""S2-5: a quality number is reported with what it cost, or with the statement that it was not metered.

ScientistTwo reports its cost per problem beside its quality; I.18 reports the Council's $0.50 a question beside its
defect counts. The gate evaluation and the July ablation reported accuracy with no cost at all. From now on the gate
evaluation meters every question, and a report over records that carry no cost says so instead of leaving a blank.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "scripts", "evals"):
    sys.path.insert(0, str(REPO / p))

import aggregate  # noqa: E402
import run_gate_eval as ev  # noqa: E402

from cellarium import gate, observability  # noqa: E402


def _rec(i, usd=None):
    r = {"id": f"c{i}__direct", "capability": "c", "mode": "steady_state", "framing": "direct", "kind": "k",
         "required": "refuse", "got": "refuse", "correct": True, "required_principled": "refuse",
         "correct_principled": True, "observable": "", "granularity": "", "parser_failed": False}
    if usd is not None:
        r["usd"] = usd
    return r


def test_a_metered_run_reports_its_cost_per_question():
    rep = ev._report([_rec(0, 0.002), _rec(1, 0.004)])
    assert rep["cost"] == {"metered": True, "n_metered": 2, "usd_per_question": 0.003, "usd_total": 0.006}


def test_an_unmetered_run_says_so():
    rep = ev._report([_rec(0), _rec(1)])
    assert rep["cost"]["metered"] is False and rep["cost"]["usd_per_question"] is None
    assert "not metered" in rep["cost"]["note"]


class _Usage:
    input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens = 1000, 100, 0, 0


class _Resp:
    usage, model, _request_id = _Usage(), "claude-sonnet-5", None


def test_each_question_records_what_its_parse_cost(monkeypatch):
    # gate.parse publishes one usage record per call (gate.py, role "gate_parse"); the stub publishes the same
    def parse(ask, model=None):
        observability.emit(observability.usage_record("gate_parse", model, _Resp(), 1.0))
        return gate.Requirement(observable="trna_charging", granularity="per_isoacceptor", parser="stub")
    monkeypatch.setattr(ev.gate, "parse", parse)
    rec = ev._one({"id": "x", "capability": "per_isoacceptor_trna_charging", "mode": "steady_state",
                   "framing": "direct", "kind": "resolution", "required": "refuse", "ask": "q?"}, "claude-sonnet-5")
    # 1000 input and 100 output tokens at Sonnet 5's list price (observability._PRICES)
    assert rec["usd"] == round(observability.estimate_cost_usd("claude-sonnet-5", 1000, 100), 6) > 0


def test_a_question_whose_parse_made_no_call_is_not_metered(monkeypatch):
    # the keyword fallback makes no model call: its cost is unknown to the meter, not zero
    monkeypatch.setattr(ev.gate, "parse", lambda ask, model=None: gate.Requirement(parser="keyword"))
    rec = ev._one({"id": "x", "capability": "c", "mode": "steady_state", "framing": "direct", "kind": "k",
                   "required": "refuse", "ask": "q?"}, "claude-sonnet-5")
    assert rec["usd"] is None


def test_the_july_aggregation_states_it_was_not_metered():
    rec = {"id": "1.1", "config": "full", "rep": 0, "converged": True, "feasible": True, "rounds_used": 2,
           "claude": {"score": 6}, "gpt": {"score": 5}}
    e = aggregate.summarise([rec])["configs"]["full"]
    assert e["usd_per_record"] is None and "not metered" in e["cost_note"]
