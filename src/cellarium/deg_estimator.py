"""The degradation-rate estimator's mathematics, separated from the knowledge base it reads (PARCA-4 Stage 2).

wcEcoli fits one degradation rate per transcription unit by nonnegative least squares: the cistron x TU
relative-abundancy matrix A times the per-TU rates x should reproduce the per-cistron rates b
(`transcription.py:701-737`). This module holds the parts of that solve which are pure linear algebra —
the block decomposition, the regularized solve, and the two candidate input changes — so they can be
imported, unit-tested and reasoned about WITHOUT a model image. `_reader_worker.py` supplies the
sim_data-dependent half and runs inside the container.

The separation is not tidiness. These are the pieces a re-implementation gets silently wrong, and one did:
an early version walked block columns in index order instead of the shipped solver's DFS order, and since
`scipy.optimize.nnls` is an active-set method whose answer on a rank-deficient block depends on column
order, it reported 17 units differing from the shipped fit where the true number is 6. Eleven of the
seventeen were an artefact of the measuring instrument. Hence `solve_nnls` DELEGATES the unregularized case
to the model's own solver rather than reproducing it.
"""

from __future__ import annotations

DEG_VARIANTS = ("baseline", "ridge", "per_unit_bound", "hierarchical")


def nnls_blocks(A):
    """Connected components of A's bipartite (row, column) graph — the blocks `fast_nnls` decomposes into.

    Determinacy is a property of the BLOCK, not of the column. A single-cistron transcription unit looks
    determined until you notice its cistron also sits on two other units, and the three-way split among them
    is what is actually unconstrained. Returns [(row_indexes, column_indexes), ...]; a component with NO rows
    is a column no equation mentions at all.

    Callers must `A.eliminate_zeros()` first. A cistron split across two units where one has zero expression
    stores an EXPLICIT 0.0, and the shipped solver partitions on `A.nonzero()`, which drops it. A census that
    keeps it sees an edge the solver does not — measured on the corpus fit, that was the difference between
    reporting 0 zero-information units and the true 209.
    """
    import numpy as np
    from scipy.sparse import bmat, csr_matrix
    from scipy.sparse.csgraph import connected_components

    m, k = A.shape
    big = bmat([[csr_matrix((m, m)), A], [A.T, csr_matrix((k, k))]], format="csr")
    _n, labels = connected_components(big, directed=False)
    row_lab, col_lab = labels[:m], labels[m:]
    return [(np.where(row_lab == lab)[0], np.where(col_lab == lab)[0]) for lab in np.unique(col_lab)]


def solve_nnls(A, b, prior=None, lam=0.0):
    """NNLS over A's blocks, optionally with a Tikhonov pull toward `prior`.

    lam=0 CALLS THE SHIPPED SOLVER (`wholecell.utils.fast_nonnegative_least_squares.fast_nnls`), it does not
    re-implement it — see the module docstring for what re-implementing it cost. Every floor-shift variant
    therefore runs through the model's own code and the only thing that changes between variants is the
    input.

    lam>0 solves min ||Ax-b||^2 + lam||x-prior||^2 subject to x>=0 by stacking sqrt(lam)*I under A. Each
    added row touches exactly one column, so the block decomposition is unchanged — and every block gains
    full column rank, so the ridge solution is UNIQUE and no longer depends on the solver's column order.
    That is not a side benefit: the null space is the defect, and this removes it by construction.

    What it does NOT remove: a column no equation touches keeps the prior exactly, at every lam. An
    estimator that must return a number for a unit it knows nothing about will always produce a point mass
    somewhere; the only escape is an explicit unknown.
    """
    import numpy as np
    from scipy.optimize import nnls

    if lam == 0.0:
        from wholecell.utils.fast_nonnegative_least_squares import fast_nnls
        return fast_nnls(A, b)[0]

    x = np.array(prior, dtype=float) if prior is not None else np.zeros(A.shape[1])
    rt = float(np.sqrt(lam))
    for rows, cols in nnls_blocks(A):
        if len(rows) == 0:
            continue
        sub = np.vstack([np.asarray(A[rows][:, cols].todense()), rt * np.eye(len(cols))])
        rhs = np.concatenate([b[rows], rt * np.asarray(x[cols], dtype=float)])
        x[cols], _ = nnls(sub, rhs)
    return x


def fold_of(ids, k=10):
    """Assign each id to one of k cross-validation folds by a STABLE HASH of the id, not a seeded shuffle.

    A shuffle needs its seed AND the array order preserved to be reproducible, and the array order is a
    property of the fit — rebuild the knowledge base and it can move. A hash of the identifier survives a
    rebuild, a reordering and a library version, and gives every variant bit-identical folds by construction
    rather than by remembering to pass the same seed.
    """
    import hashlib

    import numpy as np
    return np.array([int(hashlib.sha1(str(i).encode()).hexdigest(), 16) % k for i in ids], dtype=int)


def cv_metrics(log2_err):
    """Score a set of held-out predictions on the log2 scale, pre-registered in BACKLOG.md.

    Half-lives span more than two orders of magnitude, so an absolute error in 1/s is dominated by the
    fastest transcripts and says nothing about the rest. The SIGNED median is reported alongside the
    magnitude because an estimator that is reliably too slow is a different failure from one that is noisy,
    and a magnitude-only summary absorbs the difference.
    """
    import numpy as np

    e = np.asarray(log2_err, dtype=float)
    e = e[np.isfinite(e)]
    if e.size == 0:
        return {"n": 0}
    return {"n": int(e.size),
            "median_abs_log2": round(float(np.median(np.abs(e))), 4),
            "signed_median_log2": round(float(np.median(e)), 4),
            "frac_within_2fold": round(float((np.abs(e) <= 1.0).mean()), 4),
            "frac_within_4fold": round(float((np.abs(e) <= 2.0).mean()), 4)}


KAPPA_GRID = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, float("inf"))
"""Pre-registered in BACKLOG.md (Stage 3b) before the nested run.

kappa is in units of "measured neighbours needed before the operon mean is trusted at half weight", so this
spans "one neighbour is nearly enough" to "twenty are not". INFINITY is in the grid deliberately: it is
exactly no pooling, so if the tuner picks it, the inner loop has said on its own that operon pooling does
not help — a result, not a failure to converge.
"""


def pick_param(scores, tie_tol=0.0):
    """Choose the grid value with the lowest inner score; ties go to the LARGER value.

    `scores` is [(value, score), ...]. Ties resolving upward means toward LESS pooling (larger kappa) and
    LESS regularization freedom, so a tie never quietly buys the variant extra flexibility it did not earn.
    Written as its own function because a tie-break rule buried in an argmin is a rule nobody can find and
    nobody tests.
    """
    best = min(s for _v, s in scores)
    return max(v for v, s in scores if s <= best + tie_tol)


def paired_delta(variant_err, baseline_err):
    """Compare a variant to the baseline on the SAME held-out cistrons, pair by pair.

    The pre-registered rule compares two medians, which is correct but weak: it throws away the pairing, and
    every held-out cistron is scored by both estimators, so the pairing is free. A median-of-differences and
    a sign test say whether a gap of 0.02 log2 units is a real shift or the two summaries wobbling. This
    SUPPLEMENTS the pre-registered rule; it does not replace it, and the rule is applied as written.
    """
    import numpy as np

    v, b = np.abs(np.asarray(variant_err)), np.abs(np.asarray(baseline_err))
    ok = np.isfinite(v) & np.isfinite(b)
    v, b = v[ok], b[ok]
    if v.size == 0:
        return {"n": 0}
    d = v - b                                     # negative => the variant is closer to the measurement
    better, worse = int((d < 0).sum()), int((d > 0).sum())
    n = better + worse
    z = (better - n / 2.0) / np.sqrt(n / 4.0) if n else 0.0
    # Two-sided normal-approximation sign test. Stated as an approximation rather than dressed up as exact.
    from math import erfc
    p = float(erfc(abs(z) / np.sqrt(2))) if n else 1.0
    return {"n": int(v.size), "n_better": better, "n_worse": worse,
            "median_delta_abs_log2": round(float(np.median(d)), 4),
            "mean_delta_abs_log2": round(float(d.mean()), 4),
            "sign_test_z": round(float(z), 3), "sign_test_p_normal_approx": round(p, 5)}


def per_unit_floor(A, is_mRNA, b, c_measured, global_floor):
    """A floor from each unit's OWN measured cistrons instead of one global minimum over all of them.

    The shipped floor is `min(all measured mRNA cistron rates)` — the slowest transcript in the organism,
    applied to every unit as a lower bound. A unit whose own cistrons were measured has a far tighter and
    better justified bound available. Returns (floor_vector, n_units_without_one); the units without one
    have no measured cistron anywhere in them, so no bound derived from measurement exists for them and
    they keep the global floor.
    """
    import numpy as np

    n = A.shape[1]
    floor = np.zeros(n)
    have = np.zeros(n, dtype=bool)
    cols = (A > 0).tocsc()
    for j in np.where(is_mRNA)[0]:
        rows = cols.indices[cols.indptr[j]:cols.indptr[j + 1]]
        rows = rows[c_measured[rows]]
        if len(rows):
            floor[j] = float(b[rows].min())
            have[j] = True
    without = is_mRNA & ~have
    floor[without] = float(global_floor)
    return floor, int(without.sum())


def pooled_cistron_rates(operons, b, c_is_mRNA, c_measured, global_mean, kappa=5.0):
    """Partial pooling: impute an unmeasured mRNA cistron from ITS OPERON's measured cistrons, shrunk toward
    the global mean by n/(n+kappa).

    The global mean is the flat end of this family (kappa -> infinity). Co-transcribed genes share a
    degradation environment far more than two random genes do, so an operon mean is the more informative
    prior — but an operon with one measured neighbour should not be trusted as if it had ten, which is what
    the shrinkage weight encodes.

    THIS IS THE ONLY LEVER THAT TOUCHES THE LARGER HALF OF THE DEFECT. 783 units sit in blocks whose entire
    right-hand side is the imputation constant, so every solver — bounded, ridged, anything — returns that
    constant for them. That mass is upstream of the solve, in b; changing the estimator cannot move it.

    Returns (b_modified, n_cistrons_pooled).
    """
    import numpy as np

    b = np.array(b, dtype=float, copy=True)
    n_pooled = 0
    for cistron_idx, _rna_idx in operons:
        idx = np.asarray(cistron_idx, dtype=int)
        idx = idx[c_is_mRNA[idx]]
        if len(idx) == 0:
            continue
        meas, unmeas = idx[c_measured[idx]], idx[~c_measured[idx]]
        if len(unmeas) == 0 or len(meas) == 0:
            continue
        wt = len(meas) / (len(meas) + kappa)
        b[unmeas] = wt * float(b[meas].mean()) + (1.0 - wt) * float(global_mean)
        n_pooled += len(unmeas)
    return b, n_pooled
