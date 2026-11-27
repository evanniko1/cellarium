"""CRIT tier 1: the registered rules applied by code to V3's scored numbers, not read off by eye.

evals/plans/crit_t1_v3.json registers A1 (continuity), A2 (no premature division), A3 (rate maintenance), the negative
control and the decision. The scorer reported the numbers and stopped; the verdict was a person's reading. `decide`
applies the rules. The thresholds below are written as literals on purpose: a test that compares the module's
constant with itself passes whatever the constant says.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))

import crit_t1  # noqa: E402

V1_PASS = {"basal": {"identical": True}, "acetate_fitted": {"identical": True}}


def _summary(relaxed_median=2733.5, medium_median=1841.5, relaxed_off_step=0.0445, relaxed_on_step=0.1011,
             medium_jump=384.975, relaxed_shortest=2649.0, relaxed_valid=3, medium_valid=3):
    def group(median, step, shortest, valid):
        ids = [f"r{i}" for i in range(valid)]
        return {"runs": ids, "valid": ids, "invalid": [], "median_post_shift_s": median,
                "shortest_generation_s": shortest, "largest_threshold_step_fg": step}
    return {"oxygen_off_relaxed": group(relaxed_median if relaxed_valid >= 2 else None, relaxed_off_step,
                                        relaxed_shortest, relaxed_valid),
            "oxygen_off_medium": group(medium_median if medium_valid >= 2 else None, medium_jump, 730.0, medium_valid),
            "oxygen_restored_relaxed": group(4180.5, relaxed_on_step, 3315.0, 3),
            "oxygen_restored_medium": group(4315.5, 384.975, 3868.0, 3)}


def test_tonights_numbers_fail_a3_and_grant_nothing():
    d = crit_t1.decide(V1_PASS, _summary())
    assert d["V1"] is True and d["A1"] is True and d["A2"] is True
    assert d["negative_control"] is True
    assert d["A3"] is False and d["A3_median_s"] == 2733.5 and d["A3_threshold_s"] == 2879.0
    assert d["holds_in_relaxed"] is False
    assert d["upshift"] == {"relaxed_median_s": 4180.5, "medium_median_s": 4315.5, "decided": False}


def test_a3_is_at_least_and_the_control_is_strictly_below():
    assert crit_t1.decide(V1_PASS, _summary(relaxed_median=2879.0))["A3"] is True
    assert crit_t1.decide(V1_PASS, _summary(relaxed_median=2878.5))["A3"] is False
    d = crit_t1.decide(V1_PASS, _summary(relaxed_median=3000.0, medium_median=2879.0))
    assert d["negative_control"] is False
    assert d["A3"] is None, "a control that cannot tell the rules apart leaves A3 undecided, not passed"
    assert d["holds_in_relaxed"] is False


def test_continuity_is_strictly_below_five_fg_and_the_control_shows_the_full_jump():
    assert crit_t1.decide(V1_PASS, _summary(relaxed_off_step=5.0))["A1"] is False
    assert crit_t1.decide(V1_PASS, _summary(relaxed_on_step=4.99))["A1"] is True
    assert crit_t1.decide(V1_PASS, _summary(medium_jump=200.0))["A1"] is False   # 975 -> 590 is 385 fg in one step


def test_a_generation_under_600_s_fails_a2():
    assert crit_t1.decide(V1_PASS, _summary(relaxed_shortest=599.0))["A2"] is False
    assert crit_t1.decide(V1_PASS, _summary(relaxed_shortest=600.0))["A2"] is True


def test_fewer_than_two_valid_runs_decides_nothing():
    d = crit_t1.decide(V1_PASS, _summary(relaxed_valid=1))
    assert d["A3"] is None and d["holds_in_relaxed"] is False
    d = crit_t1.decide(V1_PASS, _summary(medium_valid=1))
    assert d["negative_control"] is None and d["A3"] is None


def test_everything_passing_grants_holds_in_and_one_v1_difference_withdraws_it():
    assert crit_t1.decide(V1_PASS, _summary(relaxed_median=2900.0))["holds_in_relaxed"] is True
    v1_bad = {**V1_PASS, "no_oxygen_fitted": {"identical": False}}
    d = crit_t1.decide(v1_bad, _summary(relaxed_median=2900.0))
    assert d["V1"] is False and d["holds_in_relaxed"] is False
    assert crit_t1.decide({}, _summary(relaxed_median=2900.0))["V1"] is False   # no V1 read is not a pass
