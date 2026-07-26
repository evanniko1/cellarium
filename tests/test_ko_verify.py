"""The standardized knockout-verification harness — multi-level, control-anchored.

WHY IT IS BUILT THIS WAY. Three verdicts in this investigation were wrong because they were reasoned rather than
measured, and the last one was wrong in a subtle way worth encoding permanently: a knocked-out cell grows
differently, so its WHOLE proteome shifts. In `KO:rpoB`, rpoB protein sits at 85% of wildtype, which reads as a
partial knockdown until you notice `rpoA` — which the design cannot touch — is at 81%. A raw ratio is therefore
uninterpretable on its own.

So every verdict here is made against a NULL DISTRIBUTION built from the genes the design does not target.
"Silenced" means *far below what happened to everything else*, not merely "lower than wildtype".

These tests use synthetic ratio distributions so they run in CI without local raw simOut, and pin the two
failure modes that matter: a global shift must NOT read as silencing, and real silencing must survive a
collapsed proteome (in `KO:dapA` the null median is 0.08 — nearly everything fell — and 0.0 must still register).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")

from cellarium import ko_verify as KV  # noqa: E402


def _null(median, sd, n=3000):
    return {"n": n, "median": median, "sd": sd}


def test_a_global_proteome_shift_is_not_reported_as_silencing():
    """THE rpoB case. Everything fell to ~0.81; the target at 0.846 is ABOVE the crowd, so it is not silenced."""
    null = _null(0.8151, 1.0812)
    assert KV._classify(0.846, null) == "expressed"
    assert KV._classify(0.8224, null) == "expressed"     # rplA, same TU, also merely riding the shift


def test_real_silencing_survives_a_collapsed_proteome():
    """THE dapA case. The KO is catastrophic so the null median is 0.08 — a naive 'ratio < 0.5' rule would call
    the entire proteome silenced. Zero must still be distinguishable from the collapse."""
    null = _null(0.0803, 0.0367)
    assert KV._classify(0.0, null) == "silenced"
    assert KV._classify(0.08, null) == "expressed"        # at the crowd median: that is the collapse, not the KO


def test_zero_is_silenced_regardless_of_the_null():
    for null in (_null(1.0, 0.1), _null(0.08, 0.04), {"n": 0, "median": None, "sd": None}):
        assert KV._classify(0.0, null) == "silenced"


def test_a_specific_reduction_is_distinguished_from_the_crowd():
    """Between 'gone' and 'riding the shift' there is a real category: measurably below the null."""
    null = _null(1.0, 0.05)
    assert KV._classify(0.5, null) == "specifically_reduced"   # 10 sd below the crowd
    assert KV._classify(0.97, null) == "expressed"             # within the crowd's own spread


def test_no_null_means_no_claim():
    """With too few untargeted genes to build a baseline, the harness must not invent a verdict."""
    thin = {"n": 3, "median": None, "sd": None}
    assert KV._classify(0.5, thin) == "expressed"              # not 'specifically_reduced' on no evidence
    assert KV._classify(None, thin) == "no_data"


def test_the_null_excludes_the_targeted_genes():
    """The baseline is meaningless if the genes under test are inside it."""
    ratios = {f"g{i}": 1.0 for i in range(50)}
    ratios["target"] = 0.0
    ratios["partner"] = 0.0
    n = KV._null(ratios, exclude={"target", "partner"})
    assert n["n"] == 50 and n["median"] == 1.0                 # the two zeros did not drag the baseline down


def test_the_null_needs_enough_genes_to_be_trusted():
    assert KV._null({f"g{i}": 1.0 for i in range(5)}, exclude=set())["median"] is None


def test_verify_reports_a_clean_error_without_local_raw():
    out = KV.verify("__nonexistent_gene__")
    assert "error" in out and "no local raw" in out["error"]
