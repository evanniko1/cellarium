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
