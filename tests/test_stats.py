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


def test_t_critical_95_pins_table_and_cornish_fisher():
    """DS-4: pin the two-sided 95% t critical values — the exact small-n table (our seed-count regime, where 1.96
    is far too narrow) and the Cornish-Fisher branch above df=30 (accurate, converging to the normal quantile)."""
    import math

    assert stats.t_critical_95(1) == 12.706          # exact table
    assert stats.t_critical_95(3) == 3.182           # n=4 seeds -> 3.18, NOT 1.96
    assert stats.t_critical_95(8) == 2.306
    assert stats.t_critical_95(30) == 2.042
    assert abs(stats.t_critical_95(60) - 2.000) < 0.005     # Cornish-Fisher vs true t(60)=2.000
    assert abs(stats.t_critical_95(120) - 1.980) < 0.005    # vs true t(120)=1.980
    assert abs(stats.t_critical_95(10**7) - stats._Z975) < 1e-3   # -> the normal quantile
    seq = [stats.t_critical_95(d) for d in (1, 2, 5, 10, 30, 60, 120, 1000)]
    assert all(a > b for a, b in zip(seq, seq[1:]))  # strictly decreasing in df
    assert stats.t_critical_95(10**9) >= stats._Z975 - 1e-6   # never below the normal quantile
    assert math.isnan(stats.t_critical_95(0))        # df<=0 undefined
