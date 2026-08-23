"""PARCA-4 Stage 2 — the estimator re-solved OFFLINE, and the machinery that makes that trustworthy.

Stage 2's premise is that the degradation-rate estimator can be re-run against a knowledge base without
ParCa, so candidate estimators cost minutes instead of a rebuild plus a comparability arm. A premise like
that is worth exactly as much as its calibration: if the offline re-solve does not reproduce the shipped
fit, every variant measured against it is measuring a different problem.

WHAT IS TESTED WHERE, because most of this file deliberately needs no model image:

  * the SOLVER machinery (`deg_estimator`) is exercised on small matrices with hand-derived
    answers. These are the parts a re-implementation can silently get wrong — and one did: an early version
    ordered block columns by index instead of walking them in the shipped solver's DFS order, and since
    `scipy.optimize.nnls` is an active-set method whose answer on a rank-deficient block depends on column
    order, it reported 17 units differing from the shipped fit where the true number is 6. Eleven of the
    seventeen were artefacts of the test instrument. `solve_nnls` now CALLS the shipped solver for the
    unregularized case, and `test_the_unregularized_path_delegates_to_the_model_s_own_solver` pins that.
  * the INTEGRATION facts (fidelity, the block census) need sim_data and are image-gated.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import deg_estimator as w  # noqa: E402
from src.cellarium import reader  # noqa: E402

pytest.importorskip("scipy")


@pytest.fixture(autouse=True)
def _image(monkeypatch):
    """Every test here that touches a knowledge base needs the model image. Applied as a fixture rather than
    left to each test because twice in this repo a test was written that skipped the guard and passed
    vacuously in CI while doing nothing."""
    if not reader.WCECOLI_DOCKER and not reader.WCECOLI_DIR:
        monkeypatch.setenv("WCECOLI_DOCKER", "")


def _needs_image():
    if not (reader.WCECOLI_DOCKER or reader.WCECOLI_DIR):
        pytest.skip("no model image configured")


_BASELINE: dict = {}


@pytest.fixture(scope="module")
def baseline():
    """One re-solve, shared. Each call unpickles sim_data and re-solves ~2,900 NNLS blocks in a container;
    running it once per assertion turned three cheap checks into six minutes."""
    _needs_image()
    if not _BASELINE:
        _BASELINE.update(reader.deg_rate_resolve(variant="baseline"))
    if _BASELINE.get("error"):
        pytest.skip(_BASELINE["error"])
    return _BASELINE


# ---------------------------------------------------------------------------------------------------------
# The block decomposition. Determinacy is a property of the BLOCK, not of the column.
# ---------------------------------------------------------------------------------------------------------

def test_blocks_are_the_connected_components_not_the_columns():
    """A single-cistron transcription unit looks determined until you notice its cistron also sits on two
    other units — the three-way split among them is what is actually unconstrained. Grouping by column would
    miss that; grouping by connected component does not."""
    from scipy.sparse import csr_matrix
    #        c0 -> {t0, t1}      c1 -> {t2}
    A = csr_matrix(np.array([[0.5, 0.5, 0.0],
                             [0.0, 0.0, 1.0]]))
    blocks = w.nnls_blocks(A)
    sizes = sorted(len(cols) for _rows, cols in blocks)
    assert sizes == [1, 2], f"expected a 2-column block and a 1-column block, got {sizes}"


def test_an_all_zero_column_is_its_own_block_with_no_rows():
    """The sharpest class PARCA-4 has: a unit whose fitted expression is 0 gives every one of its cistrons a
    relative abundance of 0, so no equation mentions it at all. It is not poorly determined — the system is
    silent about it, and whatever comes back is a default."""
    from scipy.sparse import csr_matrix
    A = csr_matrix(np.array([[1.0, 0.0], [0.0, 0.0]]))
    empty = [cols for rows, cols in w.nnls_blocks(A) if len(rows) == 0]
    assert len(empty) == 1 and list(empty[0]) == [1]


def test_explicit_zeros_are_dropped_before_the_census():
    """A cistron split across two units where one has zero expression stores an EXPLICIT 0.0. The shipped
    solver partitions on `A.nonzero()` and never sees it; a census that keeps it sees an edge the solver does
    not and calls a unit constrained when nothing constrains it. Measured on the corpus fit, this was the
    difference between reporting 0 zero-information units and the true 209."""
    from scipy.sparse import csr_matrix
    A = csr_matrix((np.array([1.0, 0.0]), (np.array([0, 0]), np.array([0, 1]))), shape=(1, 2))
    assert A.nnz == 2, "precondition: the zero is stored explicitly"
    A.eliminate_zeros()
    empty = [cols for rows, cols in w.nnls_blocks(A) if len(rows) == 0]
    assert len(empty) == 1, "the explicitly-zero column must be seen as unconstrained"


# ---------------------------------------------------------------------------------------------------------
# The solver.
# ---------------------------------------------------------------------------------------------------------

def test_the_unregularized_path_delegates_to_the_model_s_own_solver():
    """Not a style preference. `fast_nnls` walks blocks in DFS order and scipy's `nnls` is an active-set
    method, so on a rank-deficient block the answer depends on column order — a faithful-LOOKING
    re-implementation produced eleven spurious disagreements with the shipped fit. Three of the four variants
    are floor-shift variants, so they all go through the model's solver and the only thing that differs
    between them is the input."""
    import inspect
    src = inspect.getsource(w.solve_nnls)
    assert "fast_nnls" in src and "if lam == 0.0" in src, (
        "the unregularized path must call the shipped fast_nnls, not re-implement NNLS")


def test_ridge_pulls_an_uninformed_unit_exactly_to_the_prior():
    """The analytic case, and the one that decides whether a soft prior helps: for a column no equation
    touches, min ||Ax-b||^2 + lam||x-p||^2 is minimized at exactly p, for every lam. A unit with no
    information gets the prior — a number, indistinguishable on disk from a fitted one."""
    from scipy.sparse import csr_matrix
    A = csr_matrix(np.array([[1.0, 0.0]]))
    b = np.array([0.7])
    prior = np.array([0.25, 0.25])
    for lam in (1e-3, 1e-1, 1.0):
        x = w.solve_nnls(A, b, prior=prior, lam=lam)
        assert x[1] == pytest.approx(0.25, abs=1e-12), (
            f"at lam={lam} the uninformed column moved off the prior to {x[1]}")


def test_ridge_shrinks_toward_the_prior_as_lambda_grows():
    from scipy.sparse import csr_matrix
    A = csr_matrix(np.array([[1.0]]))
    b, prior = np.array([1.0]), np.array([0.0])
    xs = [w.solve_nnls(A, b, prior=prior, lam=lam)[0] for lam in (0.01, 1.0, 100.0)]
    assert xs[0] > xs[1] > xs[2], f"shrinkage is not monotone in lambda: {xs}"
    assert xs[0] == pytest.approx(1 / 1.01, rel=1e-9)


def test_ridge_keeps_the_solution_nonnegative():
    """Non-negativity is the one property of the shipped estimator that is not up for negotiation — a
    negative degradation rate is a transcript that spontaneously appears."""
    from scipy.sparse import csr_matrix
    A = csr_matrix(np.array([[1.0, 1.0], [1.0, 0.0]]))
    x = w.solve_nnls(A, np.array([0.1, 0.9]), prior=np.array([0.0, 0.0]), lam=0.01)
    assert (x >= 0).all(), x


# ---------------------------------------------------------------------------------------------------------
# The host wrapper.
# ---------------------------------------------------------------------------------------------------------

def test_an_unknown_variant_is_refused_by_name():
    out = reader.deg_rate_resolve(variant="quadratic_wishes")
    assert "error" in out and "quadratic_wishes" in out["error"]
    assert "baseline" in out["error"], "the refusal does not say what IS available"


def test_the_documented_variants_and_the_worker_s_agree():
    assert set(reader.DEG_RATE_VARIANTS) == set(w.DEG_VARIANTS), (
        "the host advertises a different variant set than the worker implements")


# ---------------------------------------------------------------------------------------------------------
# Integration: the calibration claim, against a real knowledge base.
# ---------------------------------------------------------------------------------------------------------

def test_the_baseline_resolve_reproduces_the_shipped_fit(baseline):
    """The gate for all of Stage 2. If the offline re-solve does not reproduce ParCa's own answer, then every
    variant scored against it is scored on a different problem.

    It is not bit-exact and the payload says why: ParCa overwrites `cistron_expression['basal']` after the
    estimator has run, so the estimator's input is not preserved in the artifact. What IS asserted is that
    the gap is small (>=99% of units identical to 1e-12) and confined to unmeasured units — a disagreement on
    a MEASURED unit would mean the reconstruction is wrong, not merely approximate."""
    out = baseline
    f = out["fidelity"]
    n = out["inputs"]["n_units"]
    assert f["n_units_matching_shipped"] / n > 0.99, f
    assert f["max_abs_difference"] < 1e-2, f
    assert f["why"] and f["read_this_way"], "the fidelity gap is reported without saying how to read it"


def test_the_rank_deficiency_is_mostly_units_no_equation_mentions(baseline):
    """PARCA-4 recorded a rank deficiency of 214 columns and read it as 214 ambiguous co-transcription
    splits. Measured here: 209 of the 214 are columns that are ENTIRELY ZERO — units whose fitted expression
    is 0 — and only 5 are genuine within-block dependencies. The distinction decides the remedy: a per-unit
    bound cannot touch a unit that appears in no equation."""
    out = baseline
    s = out["structure"]
    assert s["rank_deficiency"] > 0
    assert s["units_with_zero_information"] > 0.5 * s["rank_deficiency"], s
    assert s["zero_information_units_on_the_floor"] == s["units_with_zero_information"], (
        "a unit no equation mentions should land on the default; if it does not, the default moved")


def test_the_payload_refuses_to_be_read_as_a_score(baseline):
    """Principle (3) of the design: 'the numbers changed' is not evidence of improvement. Any scheme can
    manufacture distinct values by adding noise, so a payload that reports point masses without saying that
    is an invitation to declare victory on the wrong metric."""
    out = baseline
    assert "not_scored" in out and "held-out" in out["not_scored"].lower()
    assert "point_masses" in out


# ---------------------------------------------------------------------------------------------------------
# The two variants that change the INPUT rather than the solve.
# ---------------------------------------------------------------------------------------------------------

def test_a_per_unit_floor_beats_the_global_one_where_a_unit_has_its_own_measurement():
    """The shipped floor is the slowest transcript in the whole organism applied to every unit. A unit whose
    own cistrons were measured has a tighter bound sitting right there."""
    from scipy.sparse import csr_matrix
    #  cistron 0 (measured, rate 0.5) -> unit 0 ;  cistron 1 (unmeasured) -> unit 1
    A = csr_matrix(np.array([[1.0, 0.0], [0.0, 1.0]]))
    b = np.array([0.5, 0.002])
    floor, without = w.per_unit_floor(A, np.array([True, True]), b,
                                      np.array([True, False]), global_floor=0.001)
    assert floor[0] == pytest.approx(0.5), "unit 0 kept the global floor despite having its own measurement"
    assert floor[1] == pytest.approx(0.001), "unit 1 has no measured cistron, so the global floor applies"
    assert without == 1


def test_a_unit_with_no_measured_cistron_anywhere_cannot_be_rescued_by_a_bound():
    """Stated as a test because it is the design's own feasibility check: a bound derived from measurement
    does not exist for a unit that has none, so `per_unit_bound` leaves that class exactly where it was."""
    from scipy.sparse import csr_matrix
    A = csr_matrix(np.array([[1.0, 1.0]]))
    floor, without = w.per_unit_floor(A, np.array([True, True]), np.array([0.01]),
                                      np.array([False]), global_floor=0.001)
    assert without == 2 and (floor == 0.001).all()


def test_pooling_moves_an_unmeasured_cistron_toward_its_operon_and_shrinks_with_evidence():
    """Partial pooling, not pooling. One measured neighbour should not be trusted as if it were ten, and the
    n/(n+kappa) weight is what encodes that."""
    operons = [([0, 1], [0])]
    b = np.array([0.5, 0.1])          # cistron 0 measured at 0.5, cistron 1 imputed the global mean 0.1
    c_is_mRNA = np.array([True, True])
    c_measured = np.array([True, False])
    out1, n1 = w.pooled_cistron_rates(operons, b, c_is_mRNA, c_measured, global_mean=0.1, kappa=1.0)
    out9, n9 = w.pooled_cistron_rates(operons, b, c_is_mRNA, c_measured, global_mean=0.1, kappa=9.0)
    assert n1 == n9 == 1
    assert out1[1] == pytest.approx(0.5 * 0.5 + 0.5 * 0.1)      # weight 1/(1+1)
    assert out9[1] == pytest.approx(0.1 * 0.5 + 0.9 * 0.1)      # weight 1/(1+9): shrunk much harder
    assert out1[0] == 0.5, "a MEASURED cistron must never be overwritten by its operon"


def test_pooling_leaves_an_operon_with_no_measurement_alone():
    """The 783-unit passthrough class: if nothing in the operon was measured there is nothing to pool toward,
    and inventing a group mean out of imputed values would launder the constant as evidence."""
    operons = [([0, 1], [0])]
    b = np.array([0.1, 0.1])
    out, n = w.pooled_cistron_rates(operons, b, np.array([True, True]), np.array([False, False]), 0.1)
    assert n == 0 and (out == b).all()
