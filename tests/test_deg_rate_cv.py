"""PARCA-4 Stage 3 — scoring a candidate estimator on measurements it never saw.

The protocol is pre-registered in BACKLOG.md and was committed BEFORE the first variant was scored, so the
tests here are not about whether the numbers came out well. They are about the two ways a cross-validation
harness lies:

  1. LEAKAGE. If a held-out measurement reaches the fit by any route, the score is meaningless and it will
     look excellent. The route that matters here is indirect: the global floor is `min(measured mRNA cistron
     rates)` and the imputation constant is the MEAN of the measured half-lives, so a fold that removes a
     cistron from `b` but leaves those two derived quantities alone has leaked.
     `test_holding_out_a_fold_is_not_a_formality` asserts the PROPERTY a leak would break — that held-out
     error stays comparable to the error of just predicting the population mean. It was verified by
     injection rather than by inspection: leave the true measurements in `b`, and it fails.
  2. UNSTABLE FOLDS. If the fold assignment moves between variants, they are scored on different data. The
     assignment is a hash of the cistron id rather than a seeded shuffle for that reason, and it is pinned.

Everything that needs sim_data is image-gated; the rest runs anywhere.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import deg_estimator as de  # noqa: E402
from src.cellarium import reader  # noqa: E402


def _needs_image():
    import os
    if not (os.environ.get("WCECOLI_DOCKER") or os.environ.get("WCECOLI_DIR")):
        pytest.skip("no model image configured")


_CV: dict = {}


@pytest.fixture(scope="module")
def cv():
    _needs_image()
    if not _CV:
        _CV.update(reader.deg_rate_cv(variant="baseline", k=10))
    if _CV.get("error"):
        pytest.skip(_CV["error"])
    return _CV


# ---------------------------------------------------------------------------------------------------------
# Folds.
# ---------------------------------------------------------------------------------------------------------

def test_folds_come_from_the_id_not_from_a_seed():
    """A seeded shuffle needs the seed AND the array order preserved to reproduce, and the array order is a
    property of the fit — rebuild the knowledge base and it can move. A hash of the identifier survives all
    of that, which is what makes 'the same folds for every variant' true by construction instead of by
    remembering."""
    ids = [f"EG{i}_RNA" for i in range(500)]
    a = de.fold_of(ids, 10)
    b = de.fold_of(list(reversed(ids)), 10)[::-1]
    assert (a == b).all(), "fold assignment depends on the order the ids arrive in"
    assert (de.fold_of(ids, 10) == a).all(), "fold assignment is not deterministic across calls"


def test_every_fold_gets_used_and_none_swallows_the_set():
    ids = [f"EG{i}_RNA" for i in range(3000)]
    f = de.fold_of(ids, 10)
    counts = np.bincount(f, minlength=10)
    assert (counts > 0).all(), f"an empty fold means one tenth of the data is never held out: {counts}"
    assert counts.max() / counts.min() < 1.3, f"folds are badly unbalanced: {counts}"


# ---------------------------------------------------------------------------------------------------------
# Metrics.
# ---------------------------------------------------------------------------------------------------------

def test_the_metric_is_symmetric_in_fold_error():
    """log2 is used precisely so that predicting 2x too fast and 2x too slow are the same size of mistake.
    On a raw 1/s scale they are not, and the fastest transcripts would dominate every summary."""
    m = de.cv_metrics([1.0, -1.0])
    assert m["median_abs_log2"] == 1.0 and m["signed_median_log2"] == 0.0


def test_a_systematic_bias_is_visible_and_not_absorbed():
    """An estimator that is reliably 2x too slow is a different failure from one that is noisy by 2x in both
    directions, and a magnitude-only summary reports them identically."""
    biased = de.cv_metrics([1.0, 1.0, 1.0, 1.0])
    noisy = de.cv_metrics([1.0, -1.0, 1.0, -1.0])
    assert biased["median_abs_log2"] == noisy["median_abs_log2"] == 1.0
    assert biased["signed_median_log2"] == 1.0 and noisy["signed_median_log2"] == 0.0


def test_within_2fold_counts_a_factor_of_two_as_inside():
    m = de.cv_metrics([0.99, 1.0, 1.01])
    # cv_metrics rounds to 4 dp for readability in the payload, so compare at that resolution.
    assert m["frac_within_2fold"] == pytest.approx(2 / 3, abs=1e-4), (
        "the boundary is |log2| <= 1, i.e. exactly 2-fold")


def test_paired_delta_signs_point_at_the_variant():
    """A negative delta must mean the VARIANT is closer to the measurement. Getting this backwards would
    invert every conclusion in the Stage 3 table, and nothing else would look wrong."""
    d = de.paired_delta(variant_err=[0.1, 0.1, 0.1], baseline_err=[1.0, 1.0, 1.0])
    assert d["median_delta_abs_log2"] < 0 and d["n_better"] == 3 and d["n_worse"] == 0


def test_paired_delta_ignores_pairs_where_nothing_changed():
    """Most held-out cistrons are predicted identically by two variants — 1,428 of 3,246 for the baseline
    against the imputation alone. Counting those as agreement would swamp the sign test with ties that
    carry no evidence either way."""
    d = de.paired_delta([1.0, 0.5, 1.0], [1.0, 1.0, 1.0])
    assert d["n_better"] == 1 and d["n_worse"] == 0, d


# ---------------------------------------------------------------------------------------------------------
# The host wrapper.
# ---------------------------------------------------------------------------------------------------------

def test_an_unknown_variant_is_refused_before_a_container_starts():
    out = reader.deg_rate_cv(variant="wishful_thinking")
    assert "error" in out and "baseline" in out["error"]


# ---------------------------------------------------------------------------------------------------------
# Integration — including the leak the whole design depends on not happening.
# ---------------------------------------------------------------------------------------------------------

def test_every_measured_cistron_is_predicted_exactly_once(cv):
    """k folds partition the measured set; a cistron scored twice would be double-counted in every median,
    and one scored never would be silently dropped from the evidence."""
    assert cv["n_held_out_scored"] + cv["n_dropped_zero_prediction"] == 3246, cv["n_held_out_scored"]
    assert cv["k_folds"] == 10


def test_the_baseline_is_scored_on_the_same_folds_as_the_variant(cv):
    """The pairing is the point. If the baseline were scored on its own folds the comparison would be two
    summaries put side by side, which is what the pre-registered rule does and why the paired block exists
    to supplement it."""
    assert cv["baseline_scores_same_folds"]["overall"]["n"] == cv["variant_scores"]["overall"]["n"]


def test_the_imputation_alone_is_scored_too(cv):
    """The number the 1,100 genuinely unmeasured cistrons carry with nothing marking it. It is a property of
    the data, not of any variant, and until Stage 3 nothing had ever measured it."""
    imp = cv["imputation_only_scores"]["overall"]
    assert imp["n"] > 3000 and 0 < imp["median_abs_log2"] < 3
    assert cv["imputation_note"]


def test_holding_out_a_fold_is_not_a_formality(cv):
    """THE test. A held-out cistron must be unmeasured EVERYWHERE, not merely absent from one array.

    Two indirect routes matter: the global floor is `min` over the measured mRNA cistron rates, and the
    imputation constant is the MEAN of the measured half-lives. Leave either at its full-data value and the
    fold's own measurements are back in the fit — the score improves and nothing looks wrong.

    Asserted as a PROPERTY rather than by re-deriving the arithmetic: the estimator's held-out error must be
    comparable to the error of predicting the population mean. If a fold leaked, held-out prediction would
    become near-perfect and the ratio would collapse. Measured: 0.4726 against 0.4927, a 4% edge — the
    estimator barely beats the mean, which is the Stage 3 finding and is the opposite of a leak.
    """
    est = cv["variant_scores"]["overall"]["median_abs_log2"]
    imp = cv["imputation_only_scores"]["overall"]["median_abs_log2"]
    assert est > 0.05, (
        f"held-out error of {est} is implausibly small — a fold's own measurements are reaching the fit")
    assert est / imp > 0.5, (
        f"the estimator beats the population mean by more than 2x on held-out data ({est} vs {imp}). That "
        f"would be a remarkable result for a rank-deficient system; check for leakage before believing it.")


def test_the_payload_carries_the_rule_and_its_limits(cv):
    """The decision rule and what cross-validation cannot decide both travel WITH the numbers. Separated,
    the numbers get quoted and the limits do not."""
    assert "decision_rule" in cv and "floor" in cv["decision_rule"]
    assert "cannot_decide" in cv and "209" in cv["cannot_decide"]
    assert "Pre-registered" in cv["protocol"]


def test_the_imputation_constant_is_rebuilt_per_fold(cv):
    """The leak an end-to-end score check CANNOT see, which is why it is asserted directly.

    The imputation constant is the mean of the reported half-lives, so it must move when a tenth of the
    measurements is removed. Leave it at its full-data value and the held-out fold is informing the number
    used to predict itself — but removing a tenth moves the mean by well under 1%, so every score-based
    assertion still passes. Verified by injection: computing the mean over all measurements instead of the
    training set leaves `test_holding_out_a_fold_is_not_a_formality` green and only this test red.
    """
    per_fold = cv["imputed_half_life_min_per_fold"]
    assert len(per_fold) == cv["k_folds"]
    assert len(set(per_fold)) > 1, (
        f"the imputation constant is identical in every fold ({per_fold[0]}), so it was not rebuilt from the "
        f"training measurements — the held-out fold is informing the value used to predict it")


# ---------------------------------------------------------------------------------------------------------
# Stage 3b — nested CV. Tuning is where optimism gets in, so the tuner must never see the scoring data.
# ---------------------------------------------------------------------------------------------------------

def test_the_no_pooling_null_stays_in_the_grid():
    """kappa = infinity IS no pooling. Without it in the grid the tuner cannot return "pooling does not
    help", and a search that can only choose among ways of pooling will always report that pooling won."""
    assert float("inf") in de.KAPPA_GRID
    assert min(g for g in de.KAPPA_GRID if g != float("inf")) <= 1.0, (
        "the grid must reach small kappa (strong pooling) or the search is one-sided")


def test_a_tie_goes_to_less_model_freedom():
    """Pre-registered tie-break. The kappa curve turned out to be nearly flat (0.4564-0.4660 across a 40x
    range), so ties are not hypothetical — and a tie resolved toward MORE pooling would hand the variant
    flexibility the inner scores never justified."""
    assert de.pick_param([(0.5, 0.40), (5.0, 0.40), (20.0, 0.41)]) == 5.0
    assert de.pick_param([(0.5, 0.39), (5.0, 0.40)]) == 0.5, "a real win must still beat a larger value"


def test_inner_folds_are_not_a_reslicing_of_the_outer_ones():
    """The inner split uses a SEPARATE hash (`id + ':inner'`). Reusing the outer hash would make the inner
    folds a deterministic function of the outer ones, so the parameter would be selected on a partition
    aligned with the one it is scored against."""
    ids = [f"EG{i}_RNA" for i in range(2000)]
    outer = de.fold_of(ids, 10)
    inner = de.fold_of([i + ":inner" for i in ids], 5)
    agree = np.mean(inner == (outer % 5))
    assert agree < 0.30, f"inner folds track the outer partition ({agree:.2f} agreement)"


_NESTED: dict = {}


@pytest.fixture(scope="module")
def nested():
    _needs_image()
    if not _NESTED:
        _NESTED.update(reader.deg_rate_nested_cv(variant="hierarchical", k=10, k_inner=5))
    if _NESTED.get("error"):
        pytest.skip(_NESTED["error"])
    return _NESTED


def test_the_chosen_parameter_is_reported_per_fold_not_just_summarised(nested):
    """Pre-registered: if the tuner picks a different kappa in every fold then "the best kappa" is not a
    stable quantity and no single value should be carried forward, whatever the score says. Measured: it
    picks 0.5, 0.5, 5, 2, 5, 1, 2, 1, 1, 10 — a 20x spread — which is what a flat objective looks like."""
    assert len(nested["chosen_per_outer_fold"]) == nested["k_outer"]
    assert "chosen_is_stable" in nested


def test_the_nested_score_is_not_better_than_the_un_nested_one_by_a_suspicious_margin(nested):
    """The leak guard for a TUNING harness. If the inner loop can see the outer fold, kappa is chosen to fit
    the data it is about to be scored on and the nested score becomes better than any honest procedure could
    reach. Nesting normally costs a little accuracy; here it gained 0.0032 because kappa is chosen per fold,
    which is a more adaptive predictor than any single global value. A LARGE gain is the alarm."""
    gain = nested["selection_optimism"]          # naive_best - nested; positive means nested scored better
    assert gain < 0.05, (
        f"nested CV beat the best un-nested kappa by {gain} — that is backwards by more than per-fold "
        f"adaptivity explains, so check whether the outer fold is reaching the inner selection")


def test_the_payload_says_which_rule_it_is_being_judged_by(nested):
    assert "decision_rule" in nested and "floor" in nested["decision_rule"]
    assert "optimism_note" in nested and "naive" in nested["optimism_note"]


def test_the_outer_fold_is_invisible_while_the_parameter_is_chosen(nested):
    """THE tuning leak, asserted structurally because the score cannot see it.

    If the inner loop scores kappa with the outer fold still measured, the parameter is selected using the
    data it is about to be graded on. A score-based guard misses this: the kappa curve is nearly flat
    (0.4564-0.4660 across a 40x range), so the leak barely changes which kappa wins or what it scores.

    The count is exact — and it is read off the SAME mask the solver receives. A first version of this test
    computed the diagnostic from its own expression alongside the real one; injecting the leak changed both
    together and the test stayed green. A diagnostic that does not share the object it polices proves
    nothing. Verified by injection on the corrected version: drop the outer fold from the selection mask and
    only this test fails.
    """
    for t in nested["inner_selection_tables"]:
        assert t["outer_cistrons_visible_at_selection"] == 0, (
            f"outer fold {t['fold']}: {t['outer_cistrons_visible_at_selection']} of its own measurements "
            f"were visible while kappa was chosen — the fold being scored is informing its own "
            f"hyper-parameter")


# ---------------------------------------------------------------------------------------------------------
# Stage 3c — the same treatment for ridge's lambda, so "no variant ships" is measured for every variant
# rather than measured for one and argued for another.
# ---------------------------------------------------------------------------------------------------------

def test_each_tunable_variant_has_its_own_grid_and_the_others_have_none():
    """`baseline` and `per_unit_bound` take no hyper-parameter. Handing them to the tuner would silently
    score the same estimator seven times and report the luckiest fold split as a win."""
    assert set(de.PARAM_GRIDS) == {"ridge", "hierarchical"}
    assert de.PARAM_GRIDS["hierarchical"] is de.KAPPA_GRID
    assert de.PARAM_GRIDS["ridge"] is de.LAMBDA_GRID


def test_the_lambda_grid_contains_a_do_not_regularize_null():
    """Same reason kappa=inf is in its grid: a search that can only choose among strengths of shrinkage will
    always report that shrinkage won. It is 1e-6 rather than 0 because lam=0 changes the CODE PATH —
    `solve_nnls` delegates to `fast_nnls` and ignores the prior, so a column no equation touches returns 0
    (an infinite half-life, a dropped prediction) instead of taking the prior. That is a different
    estimator, not this one's limit, and the two do not belong in one grid under one name."""
    assert min(de.LAMBDA_GRID) <= 1e-6 and 0.0 not in de.LAMBDA_GRID
    assert max(de.LAMBDA_GRID) / min(de.LAMBDA_GRID) >= 1e6, "the grid does not span enough to find an edge"


def test_an_untunable_variant_is_refused_before_a_container_starts():
    out = reader.deg_rate_nested_cv(variant="baseline")
    assert "error" in out and "no hyper-parameter" in out["error"]
    assert reader.TUNABLE_VARIANTS == tuple(de.PARAM_GRIDS)


def test_the_run_used_the_grid_that_belongs_to_its_variant(nested):
    """A generic tuner that reached for the wrong grid would score `hierarchical` at kappa = 1e-6 .. 100 and
    report a clean-looking table of nonsense."""
    assert nested["variant"] == "hierarchical"
    assert nested["grid"] == ["inf" if g == float("inf") else g for g in de.KAPPA_GRID]
