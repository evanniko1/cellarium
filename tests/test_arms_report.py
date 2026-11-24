"""The report a paid sweep with the new arms will be read through (evals/arms_report.py), checked on a small
synthetic sweep whose every number is worked out by hand in the comments. No model call."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))

import arms_report  # noqa: E402

H = {"claim": "returned"}
H2 = {"claim": "after four rounds"}
D0, D1 = {"claim": "draft 0"}, {"claim": "draft 1"}

ABLATION = {"results": [
    {"id": "1.1", "config": "full", "rep": 0, "rounds_used": 3, "llm": {"cost_usd": 0.2, "input_tokens": 1000},
     "hypothesis": H, "stop_log": {"round": 2, "branch": "stability"}, "variants": {"all_rounds": H2}},
    {"id": "1.1", "config": "full", "rep": 1, "rounds_used": 2, "llm": {"cost_usd": 0.4, "input_tokens": 3000},
     "hypothesis": H, "stop_log": {"round": 2, "branch": "quota"}, "variants": {"all_rounds": H}},
    {"id": "2.1", "config": "full", "rep": 0, "rounds_used": 4, "llm": {"cost_usd": 0.3, "input_tokens": 2000},
     "hypothesis": H, "stop_log": {"round": None, "branch": None}, "variants": {"all_rounds": H2}},
    {"id": "1.1", "config": "noise_skeptic", "rep": 0, "rounds_used": 2, "llm": {"cost_usd": 0.1}, "hypothesis": H},
    {"id": "2.1", "config": "noise_skeptic", "rep": 0, "rounds_used": 2, "llm": {"cost_usd": 0.1}, "hypothesis": H},
    {"id": "1.1", "config": "proposer_bestofN", "rep": 0, "llm": {"cost_usd": 0.25}, "hypothesis": D1,
     "best_of_n": {"n_drafts": 3, "budget_reached": True, "selected": {"score": 0, "mbr": 1}},
     "variants": {"select_score": D0, "first_draft": D0}},
    {"id": "2.1", "config": "proposer_only", "rep": 0, "error": "APIConnectionError: down"},
]}
AUDITED = {"results": [
    {"id": "1.1", "config": "full", "rep": 0, "claude_defects": 8, "gpt_defects": 4,
     "variants": {"all_rounds": {"claude_defects": 7, "gpt_defects": 3}}},
    {"id": "1.1", "config": "full", "rep": 1, "claude_defects": 10, "gpt_defects": 4,
     "variants": {"all_rounds": {"same_as": "hypothesis"}}},
    {"id": "2.1", "config": "full", "rep": 0, "error": "UnreadableAudit: cut off",
     "variants": {"all_rounds": {"claude_defects": 9, "gpt_defects": 5}}},
    {"id": "1.1", "config": "noise_skeptic", "rep": 0, "claude_defects": 9, "gpt_defects": 5},
    {"id": "2.1", "config": "noise_skeptic", "rep": 0, "claude_defects": 6, "gpt_defects": 2},
    {"id": "1.1", "config": "proposer_bestofN", "rep": 0, "claude_defects": 8, "gpt_defects": 3,
     "variants": {"select_score": {"claude_defects": 9, "gpt_defects": 4}, "first_draft": {"same_as": "select_score"}}},
]}


def report():
    return arms_report.build(ABLATION, AUDITED)


def test_an_unreadable_audit_is_left_out_of_the_mean_and_counted():
    """full: case 1.1 averages 8 and 10 to 9; case 2.1's only audit failed, so it has no Claude mean at all, and
    the arm's mean is 9.0, not (9 + 0) / 2 = 4.5."""
    full = report()["arms"]["full"]
    assert (full["n"], full["defects_claude"], full["defects_gpt"], full["unreadable_audits"]) == (3, 9.0, 4.0, 1)


def test_every_arm_carries_its_cost_beside_its_defects():
    full = report()["arms"]["full"]
    assert (full["usd_per_record"], full["tokens_per_record"], full["mean_rounds"]) == (0.3, 2000.0, 3.0)


def test_an_errored_ablation_record_is_not_an_arm_record():
    assert "proposer_only" not in report()["arms"]


def test_case_clustering_weights_cases_not_records():
    """noise_skeptic: one record per case, 9 and 6 -> 7.5; GPT 5 and 2 -> 3.5."""
    n = report()["arms"]["noise_skeptic"]
    assert (n["defects_claude"], n["defects_gpt"]) == (7.5, 3.5)


def test_best_of_n_compares_the_reported_pick_with_the_others_inside_the_record():
    """Reported 8; the score rule's pick (draft 0) 9, and the first draft is that same draft: 8 - 9 = -1."""
    b = report()["best_of_n"]
    assert (b["n_records"], b["mean_drafts"], b["budget_reached"], b["same_pick_both_rules"]) == (1, 3.0, 1, 0)
    assert b["claude_reported_minus_select_score"] == -1.0 and b["claude_reported_minus_first_draft"] == -1.0
    assert b["gpt_reported_minus_first_draft"] == -1.0


def test_regret_is_split_by_the_branch_that_stopped_the_run():
    """Stability: four rounds gave 7 against the returned 8 (-1). Quota: the round-cap result is the returned
    hypothesis itself (0). The run whose rule never fired belongs to neither branch."""
    r = report()["regret"]
    assert (r["n_records"], r["never_fired"]) == (3, 1)
    assert r["claude_stability"] == {"n": 1, "all_rounds_minus_returned": -1.0}
    assert r["claude_quota"] == {"n": 1, "all_rounds_minus_returned": 0.0}
    assert "claude_both" not in r


def test_one_paired_case_is_reported_as_too_few_not_as_a_result():
    noise = report()["noise"]["claude"]
    assert noise["n_paired_cases"] == 1 and noise["mde"] is None
