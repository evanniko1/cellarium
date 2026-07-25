"""PUB-A1: the A/B replication aggregator — the pure stats that turn replicated rows into a powered, error-barred,
case-clustered paired comparison. No API key needed; synthetic ledger rows."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "evals"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import aggregate_ab as agg  # noqa: E402


def _ledger(a_by_case, b_by_case, metric="quality_score"):
    """Build a replicated ledger: {cid#r{rep}: {_case, _rep, a:{metric:v}, b:{metric:v}}}."""
    led = {}
    for cid, a_vals in a_by_case.items():
        b_vals = b_by_case[cid]
        for rep, (av, bv) in enumerate(zip(a_vals, b_vals)):
            led[f"{cid}#r{rep}"] = {"_case": cid, "_rep": rep,
                                    "a": {metric: av}, "b": {metric: bv}}
    return led


def test_per_cell_mean_and_ci_over_reps():
    led = _ledger({"c1": [4, 4, 4]}, {"c1": [5, 6, 4]})
    out = agg.aggregate(led)
    assert out["per_cell"]["c1/a"]["mean"] == 4.0 and out["per_cell"]["c1/a"]["n_reps"] == 3
    assert out["per_cell"]["c1/a"]["ci95_halfwidth"] == 0.0        # a has no spread
    assert out["per_cell"]["c1/b"]["ci95_halfwidth"] > 0           # b does
    assert out["reps_per_cell"] == [3]


def test_paired_comparison_detects_a_real_arm_difference():
    # arm B beats arm A by ~2 on every case -> a paired difference that should be significant
    a = {f"c{i}": [3, 3, 3] for i in range(6)}
    b = {f"c{i}": [5, 5, 5] for i in range(6)}
    out = agg.aggregate(_ledger(a, b))
    assert out["n_paired_cases"] == 6
    assert out["arm_means_case_clustered"] == {"a": 3.0, "b": 5.0}
    pt = out["paired_test"]
    assert pt["mean_diff_b_minus_a"] == 2.0 and pt["significant"] is True and pt["p_value"] < 0.05


def test_a_uniform_difference_falls_back_to_a_sign_test_instead_of_faking_infinite_significance():
    """quality_score is a fraction over ~3-6 criteria, so "arm B passes exactly one more criterion on every case"
    is a REACHABLE outcome — and it has zero variance, which makes the paired t undefined. The old `or 1e-12`
    epsilon would have reported p≈0 (infinite confidence from a degenerate sample); the exact sign test reports
    the most those data can honestly support."""
    a = {f"c{i}": [3, 3, 3] for i in range(6)}
    b = {f"c{i}": [4, 4, 4] for i in range(6)}       # every case differs by exactly +1
    pt = agg.aggregate(_ledger(a, b))["paired_test"]
    assert "sign test" in pt["test"] and "t" not in pt
    assert pt["mean_diff_b_minus_a"] == 1.0
    assert pt["p_value"] == round(2 * 0.5 ** 6, 4) and pt["significant"] is True   # ~0.031, not ~0
    # with too few cases the same uniform difference must NOT reach significance
    few = agg.aggregate(_ledger({f"c{i}": [3] for i in range(3)}, {f"c{i}": [4] for i in range(3)}))["paired_test"]
    assert few["p_value"] == 0.25 and few["significant"] is False


def test_paired_comparison_null_when_arms_equal():
    a = {f"c{i}": [4, 5, 3] for i in range(6)}
    b = {f"c{i}": [4, 5, 3] for i in range(6)}      # identical -> zero difference
    pt = agg.aggregate(_ledger(a, b))["paired_test"]
    assert pt["mean_diff_b_minus_a"] == 0.0 and pt["significant"] is False


def test_flatten_handles_flat_n1_ledger_and_missing_metric():
    flat = {"c1": {"a": {"quality_score": 4}, "b": {"quality_score": 5}},
            "c2": {"a": {"status": "error"}, "b": {"quality_score": 6}}}   # c2/a has no metric -> skipped
    out = agg.aggregate(flat)
    assert out["per_cell"].get("c1/a") and out["per_cell"].get("c2/b")
    assert "c2/a" not in out["per_cell"]                              # unscored arm dropped, no crash
    # a metric absent everywhere -> a clean error, not a crash
    assert "error" in agg.aggregate(flat, metric="nope")
