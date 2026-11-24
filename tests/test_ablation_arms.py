"""The ablation's new arms and controls, before any of them is paid for (validation items 3 and 5(d)).

  * best-of-N at the Council's budget: drafts are drawn until they have spent what `full` spent on the case, and
    one is kept by a rule that calls no model. The spec's rule (`council._score`) ties on 27 of the 30 stored
    single-shot drafts, so a second rule (word-overlap consensus, MBR) is computed beside it;
  * the noise skeptic: objections `full` raised on a different case, replayed in this case's shape;
  * the stopping-rule log: `full` runs to the round cap, recording where it would have stopped;
  * the guards around a paid sweep: held-out cases need asking for, a dry run calls nothing, the spend cap stops
    the run and leaves the artefact alone.

Every model call is faked; nothing leaves the machine. Expectations are literals.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "evals"):
    sys.path.insert(0, str(REPO / p))

import ablate  # noqa: E402
import costs  # noqa: E402

from cellarium import council, llm, observability  # noqa: E402

STORED = REPO / "evals" / "results" / "ablation.json"


def _cand(claim="claim", designs=True, **over) -> dict:
    c = {"claim": claim, "h1": "h1", "h0": "h0",
         "operational_defs": [{"construct": "c", "observable": "protein_mass", "measure": "cv"}],
         "predicted_effect": "positive; CV above baseline",
         "falsifier": {"target": "wildtype/basal", "reference": "wildtype/basal", "channel": "protein_mass",
                       "decision_rule": "welch_t >= 2", "refuting_result": "welch_t < 2"},
         "rivals": [{"claim": "noise", "distinguishing_result": "cv == baseline"},
                    {"claim": "extrinsic", "distinguishing_result": "tracks mass"}],
         "candidate_designs": [{"perturbation": "wildtype", "condition": "basal", "seeds": 8}] if designs else []}
    c.update(over)
    return c


def _hyp(claim="claim", designs=True, ledger=None, **over):
    return council._assemble("q", _cand(claim, designs, **over), residual=[], converged=True, rounds_used=1,
                             ledger=ledger)


# --- cases -----------------------------------------------------------------------------------------------

def test_the_default_cases_are_the_ten_the_stored_ablation_ran_on():
    stored = {r["id"] for r in json.loads(STORED.read_text(encoding="utf-8"))["results"]}
    assert set(ablate.EXPLORATORY_IDS) == stored
    assert len(ablate.EXPLORATORY_IDS) == 10


def test_a_held_out_case_has_to_be_asked_for(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ablate.py", "4.3", "--dry-run"])
    with pytest.raises(SystemExit) as e:
        ablate.main()
    assert e.value.code == 2 and "held out" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["ablate.py", "4.3", "--include-held-out", "--dry-run"])
    assert ablate.main() == 0


def test_a_dry_run_prices_the_plan_and_calls_nothing(monkeypatch, capsys):
    def no_client(**kw):
        raise AssertionError("a dry run made a client")
    monkeypatch.setattr(llm, "client", no_client)
    monkeypatch.setattr(sys, "argv", ["ablate.py", "--configs", "full,proposer_bestofN", "--no-rubric", "--dry-run"])
    assert ablate.main() == 0
    out = capsys.readouterr().out
    assert "proposer_bestofN" in out and "dry run" in out and "audit.py" in out


def test_an_unknown_arm_is_refused_before_anything_runs(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ablate.py", "--configs", "full,best_of_n", "--dry-run"])
    with pytest.raises(SystemExit):
        ablate.main()


# --- best-of-N: the selection rules ----------------------------------------------------------------------

def test_the_specs_rule_scores_27_of_the_30_stored_single_shot_drafts_at_its_maximum():
    """Why a second rule exists: `council._score` without a judge separates a draft only by completeness, a usable
    design and four structural flags. 27 stored drafts score 16; the other 3 have no usable design (12)."""
    recs = [r for r in json.loads(STORED.read_text(encoding="utf-8"))["results"] if r["config"] == "proposer_only"]
    scores = [ablate.draft_score(r["hypothesis"]) for r in recs]
    assert (len(scores), scores.count(16), scores.count(12)) == (30, 27, 3)


def test_the_score_rule_keeps_the_first_top_draft_and_never_a_lower_one():
    drafts = [_hyp("a", designs=False), _hyp("b"), _hyp("c")]
    assert [ablate.draft_score(d) for d in drafts] == [12, 16, 16]
    assert ablate.select(drafts, "score") == 1


def test_the_mbr_rule_keeps_the_draft_that_agrees_most_with_the_others():
    """All three drafts score 16 and differ only in the claim. B and C share two claim words; A shares none with
    either. B and C tie on agreement, so the earlier one, B. The spec's rule takes the first, A."""
    drafts = [_hyp("alpha beta gamma"), _hyp("ribosome growth slows"), _hyp("ribosome growth stalls")]
    assert [ablate.draft_score(d) for d in drafts] == [16, 16, 16]
    assert ablate.select(drafts, "score") == 0
    assert ablate.select(drafts, "mbr") == 1


def test_an_unknown_rule_is_refused():
    with pytest.raises(ValueError):
        ablate.select([_hyp()], "judge")


# --- best-of-N: the budget -------------------------------------------------------------------------------

@pytest.fixture
def drafting(monkeypatch):
    """council.deliberate faked: each single-shot draft emits one call of 1,000 tokens costing $0.01."""
    calls = []

    def fake(question, **kw):
        assert kw.get("use_skeptic") is False and kw.get("use_judge") is False
        calls.append(kw)
        observability.emit({"role": "proposer", "model": "claude-sonnet-5", "input_tokens": 600,
                            "output_tokens": 400, "cache_read_tokens": 0, "cache_creation_tokens": 0,
                            "latency_ms": 1, "cost_usd": 0.01})
        return _hyp(f"draft {len(calls)}")
    monkeypatch.setattr(council, "deliberate", fake)
    return calls


def test_best_of_n_draws_until_it_has_spent_the_budget(drafting):
    rec: dict = {}
    case = {"id": "1.1", "question": "q"}
    ablate._best_of_n(rec, case, 0.7, object(), {"unit": "tokens", "budgets": {"1.1": 3500.0}}, "score")
    b = rec["best_of_n"]
    assert (b["n_drafts"], b["spent"]["tokens"], b["budget_reached"]) == (4, 4000.0, True)
    assert len(rec["drafts"]) == 4


def test_best_of_n_stops_at_twelve_drafts_whatever_the_budget(drafting):
    rec: dict = {}
    ablate._best_of_n(rec, {"id": "1.1", "question": "q"}, 0.7, object(),
                      {"unit": "tokens", "budgets": {"1.1": 1e9}}, "score")
    assert rec["best_of_n"]["n_drafts"] == 12 and rec["best_of_n"]["budget_reached"] is False


def test_best_of_n_without_a_budget_is_an_error_not_a_single_draft(drafting):
    rec = ablate._one_cell({"id": "1.1", "question": "q"}, "proposer_bestofN", 0, 0.7, object(), None, "gpt-4o",
                           "claude-opus-4-8", rubric=False, derived={"unit": "tokens", "budgets": {}})
    assert "no budget" in rec["error"] and "hypothesis" not in rec and drafting == []


def test_the_budget_is_what_a_normal_full_run_spent_averaged_over_its_reps():
    full = [{"id": "1.1", "rep": 0, "llm": {"input_tokens": 900, "output_tokens": 100}},
            {"id": "1.1", "rep": 1, "llm": {"input_tokens": 9000, "output_tokens": 1000},
             "llm_at_stop": {"input_tokens": 2700, "output_tokens": 300}},
            {"id": "2.1", "rep": 0, "llm": {"input_tokens": 500, "output_tokens": 500}}]
    d = ablate.derive(full, ["1.1", "2.1"], "tokens")
    assert d["budgets"] == {"1.1": 2000.0, "2.1": 1000.0}      # (1,000 + 3,000) / 2; a logged run counts to its stop


# --- the noise skeptic -----------------------------------------------------------------------------------

def _led(oid, sev, issue, resolved=None, t="undefined_term"):
    return {"id": oid, "round": int(oid[1]), "type": t, "severity": sev, "issue": issue, "resolved_round": resolved}


def test_the_noise_plan_keeps_this_cases_shape_and_takes_another_cases_content():
    a = {"id": "1.1", "rep": 0, "hypothesis": {"objection_ledger": [
        _led("r1.1", "substantive", "x" * 50, resolved=2), _led("r1.2", "minor", "x" * 10),
        _led("r2.1", "substantive", "x" * 80, resolved=3)]}}
    b = {"id": "2.1", "rep": 0, "hypothesis": {"objection_ledger": [
        _led("r1.1", "substantive", "b" * 48, t="hidden_auxiliary"), _led("r1.2", "substantive", "c" * 85),
        _led("r1.3", "minor", "d" * 12, t="rival_not_excluded")]}}
    plan = ablate.noise_plans([a, b], ["1.1", "2.1"])[("1.1", 0)]
    assert plan["donor"] == "2.1" and plan["n"] == 3
    r1, r2 = plan["rounds"][1], plan["rounds"][2]
    assert [(o["severity"], o["issue"]) for o in r1["objections"]] == [("substantive", "b" * 48), ("minor", "d" * 12)]
    assert [(o["severity"], o["issue"]) for o in r2["objections"]] == [("substantive", "c" * 85)]
    assert r2["resolved"] == ["r1.1"] and plan["rounds"][3]["resolved"] == ["r2.1"]
    assert r1["objections"][0]["type"] == "hidden_auxiliary"         # the donor's content, this case's severity


def test_a_slot_takes_a_donor_objection_of_its_own_severity_before_a_closer_length():
    """Severity is part of the shape and length only orders the candidates within it: a minor slot of 50
    characters takes the minor donor objection of 120, not the substantive one of 48. (Added when the first
    version of these tests let the severity filter be deleted unnoticed: there, length alone made the same picks.)"""
    a = {"id": "1.1", "rep": 0, "hypothesis": {"objection_ledger": [_led("r1.1", "minor", "x" * 50)]}}
    b = {"id": "2.1", "rep": 0, "hypothesis": {"objection_ledger": [_led("r1.1", "substantive", "s" * 48),
                                                                    _led("r1.2", "minor", "m" * 120)]}}
    plan = ablate.noise_plans([a, b], ["1.1", "2.1"])[("1.1", 0)]
    assert plan["rounds"][1]["objections"] == [{"type": "undefined_term", "severity": "minor", "issue": "m" * 120}]


def test_a_donor_that_raised_nothing_is_skipped_for_the_next_case_that_did():
    recs = [{"id": "1.1", "rep": 0, "hypothesis": {"objection_ledger": [_led("r1.1", "substantive", "a")]}},
            {"id": "2.1", "rep": 0, "hypothesis": {"objection_ledger": []}},
            {"id": "3.1", "rep": 0, "hypothesis": {"objection_ledger": [_led("r1.1", "substantive", "z")]}}]
    plans = ablate.noise_plans(recs, ["1.1", "2.1", "3.1"])
    assert plans[("1.1", 0)]["donor"] == "3.1"
    assert plans[("3.1", 0)]["donor"] == "1.1"                     # wraps round, never its own case
    assert plans[("2.1", 0)]["n"] == 0                              # a run with no objections replays none


def test_the_noise_arm_needs_a_second_question():
    with pytest.raises(ValueError, match="different question"):
        ablate.noise_plans([], ["1.1"])


def test_the_noise_arm_hands_deliberate_the_replay_and_records_its_donor(monkeypatch):
    seen = {}

    def fake(question, **kw):
        seen["objs"] = kw["objection_source"](1, {}, [])
        return _hyp()
    monkeypatch.setattr(council, "deliberate", fake)
    plan = {"donor": "2.1", "n": 1, "rounds": {1: {"objections": [{"type": "t", "severity": "substantive",
                                                                     "issue": "elsewhere"}], "resolved": []}}}
    rec = ablate._one_cell({"id": "1.1", "question": "q"}, "noise_skeptic", 0, 0.7, object(), None, "gpt-4o",
                           "claude-opus-4-8", rubric=False, derived={"noise": {("1.1", 0): plan}})
    assert "error" not in rec and rec["noise"] == {"donor": "2.1", "n_objections": 1}
    assert seen["objs"]["objections"][0]["issue"] == "elsewhere"


# --- the stopping-rule log -------------------------------------------------------------------------------

def test_a_logged_full_run_keeps_what_a_normal_run_returns_and_stores_the_round_cap_result(monkeypatch):
    def fake(question, **kw):
        for r in range(1, 5):                                       # four rounds, 1,000 tokens each
            observability.emit({"role": "proposer", "model": "claude-sonnet-5", "input_tokens": 1000,
                                "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0,
                                "latency_ms": 1, "cost_usd": 0.01})
            kw["on_round"]({"round": r})
        kw["log_stop"].update(round=2, branch="stability", quota_met=False, stable=True,
                              hypothesis=_hyp("stopped at two"), rounds=[])
        return _hyp("ran to four")
    monkeypatch.setattr(council, "deliberate", fake)
    rec = ablate._one_cell({"id": "1.1", "question": "q"}, "full", 0, 0.7, object(), None, "gpt-4o",
                           "claude-opus-4-8", rubric=False, log_stop=True)
    assert rec["hypothesis"]["claim"] == "stopped at two"
    assert rec["variants"]["all_rounds"]["claim"] == "ran to four"
    assert (rec["stop_log"]["round"], rec["stop_log"]["branch"]) == (2, "stability")
    assert rec["llm_at_stop"]["input_tokens"] == 2000 and rec["llm"]["input_tokens"] == 4000


def test_log_mode_leaves_the_other_arms_alone(monkeypatch):
    def fake(question, **kw):
        assert "log_stop" not in kw
        return _hyp()
    monkeypatch.setattr(council, "deliberate", fake)
    rec = ablate._one_cell({"id": "1.1", "question": "q"}, "no_skeptic", 0, 0.7, object(), None, "gpt-4o",
                           "claude-opus-4-8", rubric=False, log_stop=True)
    assert "stop_log" not in rec and "variants" not in rec


# --- the sweep: two phases, and the spend cap ------------------------------------------------------------

@pytest.fixture
def sweep(monkeypatch, tmp_path):
    monkeypatch.setattr(ablate, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "client", lambda **kw: object())
    monkeypatch.setattr(costs, "estimate_ablation", lambda *a, **kw: {"max_per_record_usd": 0.5})
    calls: list = []

    def fake_cell(case, cfg, rep, temperature, client, oai, gpt_model, claude_grader, **kw):
        calls.append((cfg, case["id"], kw.get("derived")))
        return {"id": case["id"], "config": cfg, "rep": rep, "llm": {"cost_usd": 1.0, "input_tokens": 100},
                "hypothesis": {"objection_ledger": [_led("r1.1", "substantive", case["id"] * 5)]}}
    monkeypatch.setattr(ablate, "_one_cell", fake_cell)
    return tmp_path, calls


def test_the_derived_arms_run_after_full_and_get_its_budgets(sweep):
    tmp, calls = sweep
    code = ablate.run(["1.1", "2.1"], ["proposer_bestofN", "full"], 1, 0.7, str(tmp / "a.json"), "gpt-4o",
                      "claude-opus-4-8", workers=1)
    assert code == 0
    assert [c[0] for c in calls] == ["full", "full", "proposer_bestofN", "proposer_bestofN"]
    assert calls[2][2]["budgets"] == {"1.1": 100.0, "2.1": 100.0}
    meta = json.loads((tmp / "a.json").read_text(encoding="utf-8"))
    assert meta["spent_usd"] == 4.0 and meta["derived_from"] == "this sweep"


def test_a_derived_arm_without_full_records_is_refused(sweep):
    tmp, calls = sweep
    with pytest.raises(ValueError, match="finished `full` records"):
        ablate.run(["1.1", "2.1"], ["proposer_bestofN"], 1, 0.7, str(tmp / "a.json"), "gpt-4o", "claude-opus-4-8",
                   workers=1)


def test_the_spend_cap_stops_the_sweep_and_leaves_the_artefact_alone(sweep):
    """$1.00 a record, a $3.50 cap and $0.50 held back for the one record in flight: the third record brings the
    spend to $3.00, the cap trips, nothing else starts, and the run exits 4."""
    tmp, calls = sweep
    out = tmp / "ablation.json"
    code = ablate.run(["1.1", "2.1", "3.1"], ["full", "proposer_only"], 1, 0.7, str(out), "gpt-4o",
                      "claude-opus-4-8", workers=1, max_usd=3.5)
    assert code == costs.EXIT_SPEND_CAP == 4
    assert len(calls) == 3 and not out.exists()
    stop = json.loads(out.with_name("ablation.partial.json").read_text(encoding="utf-8"))["stopped_early"]
    assert (stop["reason"], stop["spent_usd"], stop["after_records"], stop["of"]) == ("spend cap", 3.0, 3, 6)


# --- resuming a stopped sweep --------------------------------------------------------------------------------

def test_a_stopped_sweep_resumes_from_its_partial_and_its_cap_counts_what_was_spent(sweep):
    """A capped run keeps its records. Re-run with the same plan, it does only what is missing, and the cap starts
    from the spend already made, so --max-usd stays the budget for the whole sweep: a $7.00 cap after $3.00 spent
    leaves room for the three remaining $1.00 records (it trips at $6.50, and they bring the total to $6.00)."""
    tmp, calls = sweep
    out = tmp / "ablation.json"
    args = (["1.1", "2.1", "3.1"], ["full", "proposer_only"], 1, 0.7, str(out), "gpt-4o", "claude-opus-4-8")
    assert ablate.run(*args, workers=1, max_usd=3.5) == 4 and len(calls) == 3
    assert ablate.run(*args, workers=1, max_usd=7.0) == 0
    assert len(calls) == 6 and len({(c[0], c[1]) for c in calls}) == 6          # nothing done twice
    art = json.loads(out.read_text(encoding="utf-8"))
    assert (len(art["results"]), art["spent_usd"], art["resumed_records"]) == (6, 6.0, 3)
    assert not out.with_name("ablation.partial.json").exists()


def test_resuming_under_the_cap_that_stopped_it_stops_again_without_a_call(sweep):
    tmp, calls = sweep
    out = tmp / "ablation.json"
    args = (["1.1", "2.1", "3.1"], ["full", "proposer_only"], 1, 0.7, str(out), "gpt-4o", "claude-opus-4-8")
    ablate.run(*args, workers=1, max_usd=3.5)
    assert ablate.run(*args, workers=1, max_usd=3.5) == 4 and len(calls) == 3


def test_a_partial_from_a_different_plan_is_refused_not_mixed_in(sweep):
    tmp, calls = sweep
    out = tmp / "ablation.json"
    ablate.run(["1.1", "2.1", "3.1"], ["full", "proposer_only"], 1, 0.7, str(out), "gpt-4o", "claude-opus-4-8",
               workers=1, max_usd=3.5)
    with pytest.raises(ValueError, match="different plan"):
        ablate.run(["1.1", "2.1", "3.1"], ["full"], 1, 0.7, str(out), "gpt-4o", "claude-opus-4-8", workers=1)


def test_an_errored_record_in_the_partial_is_done_again(sweep, monkeypatch):
    tmp, calls = sweep
    out = tmp / "ablation.json"
    out.with_name("ablation.partial.json").write_text(json.dumps({
        "configs": ["full"], "reps": 1, "temperature": 0.7, "case_ids": ["1.1"], "rubric": True,
        "log_stop_rule": False, "select_primary": "score", "budget_unit": "tokens",
        "results": [{"id": "1.1", "config": "full", "rep": 0, "error": "APIConnectionError: down"}]}),
        encoding="utf-8")
    assert ablate.run(["1.1"], ["full"], 1, 0.7, str(out), "gpt-4o", "claude-opus-4-8", workers=1) == 0
    assert [c[:2] for c in calls] == [("full", "1.1")]
    assert json.loads(out.read_text(encoding="utf-8"))["resumed_records"] == 0
