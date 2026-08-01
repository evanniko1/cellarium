"""T3 — the amino-acid rate clamp must survive the 21 -> 85 resolution split.

THE GATING PRECONDITION THIS COVERS. `dcdt_jit` clamps the charging flux against the amino acid
actually available:

    if limit_v_rib:
        v_charging = np.fmin(v_charging, aa_rate_limit)     # polypeptide_elongation.py:1798
    ...
    aa_rate_limit = original_aa_conc / time_limit           # :1742, a PER-AMINO-ACID vector

At 21-amino-acid resolution `v_charging` and `aa_rate_limit` are both 21-vectors and the elementwise
`fmin` is exactly right. At 85-isoacceptor resolution `v_charging` becomes an 85-vector while the
limit stays per-family, and the obvious lift — broadcast `L_a` to every isoacceptor of family *a* and
`fmin` elementwise — is WRONG, because min does not commute with the family sum:

    sum_i min(v_i, L_a)  !=  min(sum_i v_i, L_a)

whenever the clamp binds. Worse than merely inexact: each of the family's n_a isoacceptors is
independently allowed the FULL family limit, so the family can consume up to n_a * L_a of an amino
acid that only had L_a. That is phantom capacity, it silently breaks the exact 85 -> 21 reduction,
and `limit_v_rib=True` is the PRODUCTION request path — so it would be wrong on the only path that
actually runs.

THE CORRECT FORM, which this file pins: clamp the family AGGREGATE, then rescale the family's
isoacceptors proportionally.

    V_a          = sum_{i in a} v_i
    V_a_clamped  = min(V_a, L_a)
    v_i_clamped  = v_i * V_a_clamped / V_a          (and 0 when V_a == 0)

which restores `sum_{i in a} v_i_clamped == min(sum_i v_i, L_a)` identically.

WHY THIS FILE EXISTS BEFORE THE RHS DOES. The 85-resolution right-hand side is not written yet. The
question it has to get right is pure algebra, so it is pinned first and the implementation is written
against a test that already fails for the wrong approach. Once the RHS lands, `_clamp_shared` here
should be replaced by an import of the real one — the assertions do not change.

NON-VACUITY IS THE POINT. `test_the_naive_elementwise_clamp_breaks_the_reduction` asserts the naive
form FAILS. Without it, every assertion below would pass for both implementations and the file would
certify nothing. Materiality is a separate question this file does NOT answer: how often the clamp
actually binds in production has not been measured.
"""

from __future__ import annotations

import numpy as np
import pytest

# n_a for the 20 charging-masked families, from sim_data.process.transcription.aa_from_trna
# (transcription.py:1256). The full 21-vector is [5,7,4,3,1,4,4,6,1,5,8,6,6,2,3,5,4,1,3,1,7] summing
# to 86; the SEL entry (value 1) is dropped by the charging mask, leaving 85 across 20 families.
N_PER_FAMILY = np.array([5, 7, 4, 3, 1, 4, 4, 6, 1, 5, 8, 6, 6, 2, 3, 5, 4, 1, 3, 7])
N_TRNA = int(N_PER_FAMILY.sum())          # 85
N_AA = len(N_PER_FAMILY)                  # 20

_RNG = np.random.RandomState(20260801)


def _family_matrix() -> np.ndarray:
    """(20, 85) 0/1 matrix mapping isoacceptors to families — the masked shape of aa_from_trna."""
    T2A = np.zeros((N_AA, N_TRNA))
    col = 0
    for a, n in enumerate(N_PER_FAMILY):
        T2A[a, col:col + n] = 1.0
        col += n
    assert col == N_TRNA
    return T2A


T2A = _family_matrix()


def _clamp_naive(v_trna: np.ndarray, limit_aa: np.ndarray) -> np.ndarray:
    """The WRONG lift: broadcast the family limit to each isoacceptor and fmin elementwise."""
    return np.fmin(v_trna, T2A.T @ limit_aa)


def _clamp_shared(v_trna: np.ndarray, limit_aa: np.ndarray) -> np.ndarray:
    """The correct form: clamp the family aggregate, rescale the family proportionally."""
    totals = T2A @ v_trna                                  # (20,) family sums
    clamped = np.fmin(totals, limit_aa)
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(totals > 0, clamped / totals, 0.0)
    return v_trna * (T2A.T @ scale)


def _state(bind_families: int = 3):
    """A charging state in which the clamp BINDS for at least `bind_families` families.

    An unbound state would satisfy every assertion below under both implementations, since the two
    forms coincide exactly when nothing is clamped — so the binding is what gives the test content.
    """
    v_trna = _RNG.uniform(0.05, 2.0, N_TRNA)
    totals = T2A @ v_trna
    # Start with limits comfortably above the family totals, then pull a few below.
    limit_aa = totals * 10.0
    binding = _RNG.choice(N_AA, size=bind_families, replace=False)
    limit_aa[binding] = totals[binding] * _RNG.uniform(0.2, 0.8, bind_families)
    return v_trna, limit_aa, binding


def test_the_state_actually_binds_the_clamp():
    """Guard the guard: if the fixture stopped binding, every other test here would go vacuous."""
    v_trna, limit_aa, binding = _state()
    totals = T2A @ v_trna
    assert (totals[binding] > limit_aa[binding]).all(), "fixture does not bind the clamp"
    unbound = np.setdiff1d(np.arange(N_AA), binding)
    assert (totals[unbound] <= limit_aa[unbound]).all(), "fixture binds families it should not"


def test_shared_clamp_preserves_the_family_aggregate_exactly():
    """sum_{i in a} v_i_clamped == min(sum_i v_i, L_a), which is the 21-resolution answer."""
    v_trna, limit_aa, _ = _state()
    expected = np.fmin(T2A @ v_trna, limit_aa)
    got = T2A @ _clamp_shared(v_trna, limit_aa)
    np.testing.assert_allclose(got, expected, rtol=0, atol=1e-14)


def test_the_naive_elementwise_clamp_breaks_the_reduction():
    """NON-VACUITY. The naive lift must FAIL — otherwise this file certifies nothing.

    It also over-delivers rather than under-delivers: each isoacceptor is independently granted the
    whole family limit, so the clamped family total can exceed the limit it was clamped to.
    """
    v_trna, limit_aa, binding = _state()
    expected = np.fmin(T2A @ v_trna, limit_aa)
    got = T2A @ _clamp_naive(v_trna, limit_aa)
    assert not np.allclose(got, expected, rtol=0, atol=1e-14), \
        "the naive clamp agreed with the aggregate — the test has lost its content"
    # Phantom capacity: strictly MORE than the limit allowed, on at least one bound family.
    assert (got[binding] > expected[binding] + 1e-12).any(), \
        "expected the naive form to grant more than the family limit"


def test_the_two_forms_agree_when_the_clamp_does_not_bind():
    """The distinction is specifically about binding: with slack limits both forms are the identity."""
    v_trna = _RNG.uniform(0.05, 2.0, N_TRNA)
    limit_aa = (T2A @ v_trna) * 10.0
    np.testing.assert_allclose(_clamp_shared(v_trna, limit_aa), v_trna, rtol=0, atol=1e-14)
    np.testing.assert_allclose(_clamp_naive(v_trna, limit_aa), v_trna, rtol=0, atol=1e-14)


def test_shared_clamp_preserves_within_family_shares():
    """Rescaling must not redistribute demand between isoacceptors — only scale the family down."""
    v_trna, limit_aa, binding = _state()
    out = _clamp_shared(v_trna, limit_aa)
    col = 0
    for a, n in enumerate(N_PER_FAMILY):
        sl = slice(col, col + n)
        if (T2A @ v_trna)[a] > 0:
            before = v_trna[sl] / v_trna[sl].sum()
            after = out[sl] / out[sl].sum() if out[sl].sum() > 0 else before
            np.testing.assert_allclose(after, before, rtol=0, atol=1e-14)
        col += n


@pytest.mark.parametrize("family", [0, 7, 19])
def test_a_zero_pool_family_stays_finite(family):
    """VALINE has seven identically-zero uncharged counts at row 0 in both ParCa trees, so V_a == 0
    is a real state, not a synthetic edge case. It must yield exactly 0, never NaN."""
    v_trna, limit_aa, _ = _state()
    col = int(N_PER_FAMILY[:family].sum())
    v_trna[col:col + N_PER_FAMILY[family]] = 0.0
    out = _clamp_shared(v_trna, limit_aa)
    assert np.isfinite(out).all(), "zero-pool family produced a non-finite charging flux"
    assert (out[col:col + N_PER_FAMILY[family]] == 0.0).all()
    np.testing.assert_allclose(T2A @ out, np.fmin(T2A @ v_trna, limit_aa), rtol=0, atol=1e-14)


def test_clamp_never_exceeds_the_limit_over_random_states():
    """The invariant that matters physically: a family can never consume more than it had."""
    for _ in range(200):
        v_trna, limit_aa, _ = _state(bind_families=int(_RNG.randint(1, 8)))
        totals = T2A @ _clamp_shared(v_trna, limit_aa)
        assert (totals <= limit_aa + 1e-12).all(), "shared clamp exceeded the amino-acid limit"
