"""Scipy-free stats helpers: the Student-t two-sided p-value (incomplete beta) used by fit_relation's slope
inference (DS-1), and the shape statistics + Sarle bimodality coefficient behind the bimodality tool (M-1)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import stats  # noqa: E402


def test_t_two_sided_p_matches_the_table():
    # t(4)=2.776 is the two-sided 5% critical value -> p ~ 0.05; t(9)=2.262 likewise.
    assert abs(stats.t_two_sided_p(2.776, 4) - 0.05) < 0.005
    assert abs(stats.t_two_sided_p(2.262, 9) - 0.05) < 0.005
    assert stats.t_two_sided_p(0.0, 5) == 1.0            # zero t -> the whole mass
    assert stats.t_two_sided_p(3.0, 10) < stats.t_two_sided_p(1.0, 10)   # monotone in |t|
    assert stats.t_two_sided_p(None, 5) is None and stats.t_two_sided_p(2.0, 0) is None


def test_skewness_and_kurtosis_signs():
    sym = [1, 2, 3, 4, 5, 6, 7]
    assert abs(stats.skewness(sym)) < 1e-9                # symmetric -> ~0 skew
    right = [1, 1, 1, 1, 2, 2, 3, 9]
    assert stats.skewness(right) > 0                      # long right tail -> positive
    assert stats.skewness([1, 2]) is None                # n<3 undefined
    assert stats.kurtosis_excess([1, 2, 3]) is None       # n<4 undefined


def test_bimodality_coefficient_separates_uni_from_bimodal():
    bimodal = [0, 0, 0, 0, 10, 10, 10, 10]               # two tight clusters
    unimodal = [1, 2, 2, 3, 3, 3, 4, 4, 5]               # single peaked, symmetric
    bc_bi = stats.bimodality_coefficient(bimodal)
    bc_uni = stats.bimodality_coefficient(unimodal)
    assert bc_bi > stats.BC_BIMODAL_THRESHOLD > bc_uni
    assert 0.0 < bc_uni <= 1.0 and 0.0 < bc_bi <= 1.0
    assert stats.bimodality_coefficient([1, 2, 3]) is None          # n<4
    assert stats.bimodality_coefficient([5, 5, 5, 5]) is None       # zero variance
