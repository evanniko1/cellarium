"""Validation-layer item 4: a minimum detectable effect beside every null in the Council ablation.

On the STORED summary (`evals/results/ablation_summary.json`), so no model call is made. Expectations are
LITERALS recomputed by hand from the per-case residual-defect means, not derived from `paired_mde` itself.

What these pin is the number behind a reading the Platform Map (section 19) already gives in words: "The
measure is under-powered, and the defect column has to be read per auditor." Under the Claude auditor the null
is UNINFORMATIVE -- the design could not have detected a difference of the size observed. The GPT auditor,
about nine times less noisy, detects
the effect of removing the skeptic and of removing all critique (proposer only), but NOT the effect of the
judge's falsifiability rubric: `generic_judge` keeps the skeptic and swaps in a plain quality judge, and that
comparison is underpowered under both auditors, with GPT's observed direction favouring the generic judge.
(Corrected 2026-11-21: this docstring and a test name first said the GPT auditor detects "the skeptic and
judge roles" -- the proposer-only comparison had been read as a test of the judge -- and attributed to "the
paper" a phrase found nowhere in the tree.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))

import aggregate as agg  # noqa: E402

SUMMARY = REPO / "evals" / "results" / "ablation_summary.json"


@pytest.fixture(scope="module")
def defects():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))["residual_defects"]


def _mde(defects, auditor, other):
    return agg.paired_mde(defects["full"][auditor]["per_case"], defects[other][auditor]["per_case"])


def test_under_the_claude_auditor_every_comparison_is_underpowered(defects):
    """Observed differences of 1.1-1.5 defects against MDEs of 3.5-4.4. The null cannot be read as "no effect"."""
    for other, mde in (("no_skeptic", 3.524), ("proposer_only", 4.360), ("generic_judge", 3.713)):
        r = _mde(defects, "defects_claude", other)
        assert r["mde"] == pytest.approx(mde, abs=2e-3), other
        assert r["verdict"].startswith("underpowered"), other


def test_under_the_gpt_auditor_removing_critique_is_detectable(defects):
    """Two comparisons the Claude auditor could not resolve, resolved by a quieter instrument: dropping the
    skeptic (proposer + judge) and dropping skeptic and judge together (proposer only). Both remove CRITIQUE;
    neither isolates the judge."""
    r = _mde(defects, "defects_gpt", "no_skeptic")
    assert r["observed_diff"] == pytest.approx(-0.867, abs=2e-3)
    assert r["mde"] == pytest.approx(0.356, abs=2e-3)
    assert r["verdict"].startswith("detectable")
    r = _mde(defects, "defects_gpt", "proposer_only")
    assert r["observed_diff"] == pytest.approx(-0.967, abs=2e-3)
    assert r["mde"] == pytest.approx(0.480, abs=2e-3)
    assert r["verdict"].startswith("detectable")


def test_the_judges_rubric_is_not_detectable_under_either_auditor(defects):
    """`generic_judge` is the only arm that isolates the judge: skeptic kept, falsifiability rubric replaced
    by a plain quality judge. Under GPT the full system has 0.500 MORE residual defects than it, against an
    MDE of 0.801 -- underpowered, and pointing the other way. Pinned so the judge cannot again be reported
    as a detected role."""
    r = _mde(defects, "defects_gpt", "generic_judge")
    assert r["observed_diff"] == pytest.approx(0.500, abs=2e-3)
    assert r["mde"] == pytest.approx(0.801, abs=2e-3)
    assert r["verdict"].startswith("underpowered")
    assert _mde(defects, "defects_claude", "generic_judge")["verdict"].startswith("underpowered")


def test_the_two_auditors_differ_about_ninefold_in_noise(defects):
    """Why reporting one auditor alone is not neutral: per-case SD of the paired difference, full vs
    proposer_only, is 4.383 under Claude and 0.483 under GPT."""
    c = _mde(defects, "defects_claude", "proposer_only")["sd_diff"]
    g = _mde(defects, "defects_gpt", "proposer_only")["sd_diff"]
    assert c == pytest.approx(4.383, abs=2e-3) and g == pytest.approx(0.483, abs=2e-3)
    assert 8 < c / g < 10


def test_a_saturated_measure_reports_no_mde_rather_than_zero():
    """PUB-A3: the quality rubric scores 6/6 in every arm, so every paired difference is 0. An MDE of 0 would
    claim the design could detect ANY difference; the truth is it has no variance to power against."""
    same = {str(i): 6.0 for i in range(10)}
    r = agg.paired_mde(same, dict(same))
    assert r["mde"] is None
    assert "saturated" in r["why"]


def test_the_t_critical_value_is_used_not_the_normal_one():
    """With 10 paired cases the normal 2.80 would understate the MDE by ~11%. Pinned with literal inputs:
    differences alternating 0 and 2 over n = 10 have SD 1.0541, giving MDE = 3.1456 x 1.0541 / sqrt(10) =
    1.0485 under t(9), where the normal approximation would give 0.9339."""
    a = {str(i): float(i % 2) * 2 for i in range(10)}      # diffs alternate 0, 2 -> SD = 1.0541
    b = {str(i): 0.0 for i in range(10)}
    r = agg.paired_mde(a, b)
    assert r["critical_value"] == "t(9)"
    assert r["mde"] == pytest.approx(1.0485, abs=1e-3)       # 3.1456 x 1.0541 / sqrt(10)
