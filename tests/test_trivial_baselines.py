"""The trivial-answer probe (Agentic Benchmark Checklist R.13 and O.b.2): the answers it builds, what the Council's
own checks make of them without a model, and the paid scoring run with every model call faked."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "evals"):
    sys.path.insert(0, str(REPO / p))

import ablate  # noqa: E402
import audit  # noqa: E402
import shared_metric  # noqa: E402
import trivial_baselines as tb  # noqa: E402

Q = "Does knocking out argS lower ppGpp in minimal medium?"


def test_the_answers_use_nothing_about_the_case_but_its_question():
    other = "Is growth rate set by ribosome content?"
    for kind in tb.KINDS:
        a = json.dumps(tb.build(Q, kind)).replace(Q, "<q>")
        b = json.dumps(tb.build(other, kind)).replace(other, "<q>")
        assert a == b, kind


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        tb.build(Q, "clever")


def test_the_councils_own_score_gives_doing_nothing_its_maximum():
    """The free result. `council._score`, the rule best-of-N keeps a draft by, gives the restated answer and the
    hedge-everything answer 16 of 16 (every required field filled, and one generic wildtype design is usable),
    the score 27 of the 30 stored real single-shot drafts get. The empty answer gets 0."""
    assert [tb.free_checks(Q, k)["council_score"] for k in tb.KINDS] == [16, 16, 0]


def test_the_ab_minimum_bar_passes_the_hedge_and_fails_the_restatement():
    """The A/B's deterministic floor wants a dial-label observable, a direction, a baseline, a falsifier and a
    usable design. Hedging every direction satisfies 'a direction'; the restatement names no real channel."""
    assert tb.free_checks(Q, "hedge_all")["ab_minimum_bar"] is True
    restated = tb.free_checks(Q, "restated")
    assert restated["ab_minimum_bar"] is False
    assert restated["ab_checks"]["M1_observable_on_dial_label"] is False
    assert tb.free_checks(Q, "empty")["ab_minimum_bar"] is False


def test_the_dry_run_prints_the_free_checks_and_calls_nothing(monkeypatch, capsys):
    from cellarium import llm

    def no_client(**kw):
        raise AssertionError("a dry run made a client")
    monkeypatch.setattr(llm, "client", no_client)
    monkeypatch.setattr(sys, "argv", ["trivial_baselines.py", "--dry-run"])
    assert tb.main() == 0
    out = capsys.readouterr().out
    assert "hedge_all" in out and "16/16" in out and "dry run" in out


def test_a_held_out_case_is_refused(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["trivial_baselines.py", "4.3", "--dry-run"])
    with pytest.raises(SystemExit):
        tb.main()


@pytest.fixture
def scored(monkeypatch, tmp_path):
    """Every grader faked: the rubric says 6, the Claude auditor 2, the shared judge 0.75; GPT is off."""
    calls: list = []

    def fake_rubric(case, h, client, model):
        calls.append(("rubric", case["id"]))
        return {k: True for k in ablate.Q}

    def fake_audit(rec, client, model, hypothesis=None):
        calls.append(("audit", rec["id"]))
        return {"defects": [{"type": "t", "issue": "i"}] * 2, "stop_reason": "tool_use", "output_tokens": 10}

    def fake_shared(case, text, client, judge):
        calls.append(("shared", case["id"]))
        return {"quality_score": 0.75, "judged": True, "min_bar_pass": True}
    monkeypatch.setattr(ablate, "grade_claude", fake_rubric)
    monkeypatch.setattr(audit, "audit_claude", fake_audit)
    monkeypatch.setattr(shared_metric, "grade", fake_shared)
    return tmp_path, calls


def test_the_paid_run_scores_every_answer_with_every_instrument(scored):
    tmp, calls = scored
    out = tmp / "trivial.json"
    assert tb.run(["1.1", "2.1"], str(out), client=object(), oai=None, workers=1) == 0
    art = json.loads(out.read_text(encoding="utf-8"))
    assert len(art["results"]) == 6 and len(calls) == 18
    r = next(x for x in art["results"] if x["id"] == "1.1" and x["kind"] == "hedge_all")
    assert (r["rubric_claude"], r["defects_claude"], r["shared_quality"]) == (6, 2, 0.75)
    assert r["free"]["council_score"] == 16
    assert "full" in art["reference"] and "python" in art["environment"]


def test_each_reference_point_comes_from_the_instrument_it_is_compared_with():
    """FOUND 2026-11-24, before M4 ran: the shared judge's reference read `quality_score` from the A/B's Council
    rows, which have none. They predate the shared judge; their criteria come from grade.llm_grade, a different
    grader that sees the structured hypothesis. So the reference was None and the comparison would have printed
    blank. The A/B's Cellwright answers to the same ten cases were scored by the shared judge itself."""
    ref = tb.reference_points(ablate.EXPLORATORY_IDS)
    assert ref["ab_cellwright_shared_quality"] == 0.4875          # ab_ledger.json arm A, the ten exploratory cases
    assert "ab_council_shared_quality" not in ref
    assert "predate the shared judge" in ref["ab_council_shared_quality_absent"]
    assert ref["full"] == {"rubric_claude": 6.0, "defects_gpt": 3.8}
    assert ref["proposer_only"] == {"rubric_claude": 6.0, "defects_gpt": 4.77}
    one = tb.reference_points(["1.1"])                                 # only the cases asked for
    assert one["ab_cellwright_shared_quality"] == 0.625
    assert (one["full"]["defects_gpt"], one["proposer_only"]["defects_gpt"]) == (2.67, 4.67)


def test_the_rubric_reference_is_taken_over_the_cases_asked_for(monkeypatch):
    """Every stored rubric score is 6 of 6, so on the real files the case filter cannot show; a stand-in can."""
    import costs
    abl = {"results": [{"id": "1.1", "config": "full", "claude": {"score": 4}},
                       {"id": "2.1", "config": "full", "claude": {"score": 6}}]}
    monkeypatch.setattr(costs, "_stored", lambda name: abl if name == "ablation.json" else None)
    assert tb.reference_points(["1.1"])["full"]["rubric_claude"] == 4.0


def test_the_paid_run_stops_on_an_outage(scored, monkeypatch):
    tmp, calls = scored

    def down(*a, **kw):
        raise ConnectionError("down")
    monkeypatch.setattr(ablate, "grade_claude", down)
    out = tmp / "trivial.json"
    assert tb.run(["1.1", "2.1"], str(out), client=object(), oai=None, workers=1) == 3
    assert not out.exists()
    part = json.loads(out.with_name("trivial.partial.json").read_text(encoding="utf-8"))
    assert part["stopped_early"]["after_calls"] == 5 and all("error" in x for x in part["results"])


def test_a_cap_that_trips_on_the_last_record_is_not_a_stop(monkeypatch, tmp_path):
    """The cap trips once the third answer's cost is counted, and there is no fourth: nothing was skipped, so the
    run is complete (the false stop found in evals/audit.py on 2026-11-24 shared this code)."""
    import costs
    monkeypatch.setattr(costs, "estimate_trivial", lambda *a, **kw: {"per_record": {"high": 0.5}})
    monkeypatch.setattr(tb, "_score_one", lambda case, kind, *a: {"id": case["id"], "kind": kind,
                                                                   "llm": {"cost_usd": 1.0}})
    out = tmp_path / "trivial.json"
    assert tb.run(["1.1"], str(out), client=object(), oai=None, workers=1, max_usd=3.4) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))["results"]) == 3
