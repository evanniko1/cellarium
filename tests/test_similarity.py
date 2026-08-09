"""species_similarity — the response-profile similarity metric (D8/D9): double-centered cosine over the
199-species panel, with the two mandatory ship-guards.

The metric was ADJUDICATED before it was built (WELL-6z4, 32-agent audit/test/adversarial/literature): the
severity/growth axis is removed by double-centering (NOT PC1 removal, NOT a graph), verified to cut
`corr(growth, cos-to-WT)` from +0.61 to ~0 while keeping the mechanism clusters. These pin that guarantee AND
the two guards that must travel with every result, on the live corpus.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")
os.environ.setdefault("CELLARIUM_OUT", "runs")

import pytest  # noqa: E402


def _corpus():
    from cellarium import store
    if not store.has_manifest():
        pytest.skip("no local manifest")


def test_the_metric_passes_its_own_acceptance_test():
    """The load-bearing guarantee (WELL-6z4/D9), recomputed on the live corpus: the severity confound is removed
    AND the mechanism cluster survives. These are the two corpus-robust gates.

    RE-ESTABLISHED 2026-08-08. This carried `xfail(strict=True)` whose stated purpose was that a genuine
    re-establishment would XPASS, turn CI red, and force someone to delete the marker and re-read the claim.
    That is what happened, so the marker is gone and the claim is re-read here.

    WHAT WAS ACTUALLY WRONG — the cluster SELECTOR, not the metric. `acceptance()` chose the envelope cluster
    with `any(x in d for x in ("fabI","lpxC","murA","glmS"))`, a substring match, which re-admitted
    `graded_gene_knockout/KO:murA` after `gene_knockout/KO:murA` had been excluded on the merits as a verified
    no-op. A substring cannot tell one perturbation type from another. Since GRADED-1 gave each dose its own
    identity the substring matched THREE murA designs rather than one, including `#expr:0.9` — a knockdown
    that leaves the protein at ~90% of wild type, sitting inside a cluster whose claim is that severe lesions
    in one mechanism resemble each other.

    NOTHING WAS RELAXED. Both thresholds are still 0.15 and 0.30. Measured across the three candidate rules:
        substring (6 members, 3 graded murA)          delta +0.105   FAIL
        full knockouts (fabI, lpxC, glmS)             delta +0.419   PASS
        full knockouts + the STRONGEST graded murA    delta +0.133   FAIL
    The third line rules out the convenient story: admitting only the 90%-knockdown dose still collapses the
    cluster, so this is not "the weak doses dragged it down". Graded knockdowns do not sit with full
    knockouts — a statement about perturbation TYPE, not dose.

    WHAT `passes=True` DOES NOT MEAN, and why `strength` is asserted below rather than just the booleans. Both
    thresholds are weak at this corpus size, measured exhaustively rather than argued: 6.1% of ALL 19,600
    arbitrary 3-design subsets clear the +0.30 cluster gate, and at n=49 the Fisher-z SE is 0.147, so |r|<0.15
    asks a point estimate to be smaller than ~1 standard error of itself. The durable claims are the cluster's
    p-value (0.021 against the exhaustive null) and the confound REDUCTION (|r| 0.635 -> 0.082), not the two
    booleans. A future reader quoting `passes` without `strength` would overstate this.
    """
    _corpus()
    from cellarium import similarity
    a = similarity.acceptance()
    if "error" in a:
        pytest.skip(a["error"])
    assert abs(a["corr_growth_cos_to_wt"]) < 0.15, f"severity confound {a['corr_growth_cos_to_wt']} not removed"
    assert a["envelope_within_minus_overall"] > 0.30, "the envelope mechanism cluster did not survive"
    assert a["passes"] is True, a

    # The cluster must be VERIFIED knockouts. Re-admitting a no-op or a different perturbation type to keep
    # this green is the exact failure that made the original pass worthless.
    assert [d.split("/")[-1] for d in a["envelope_members"]] == ["KO:fabI", "KO:glmS", "KO:lpxC"], (
        "the envelope cluster is not the verified full knockouts: %s" % a["envelope_members"])

    # And the pass must carry its own strength, or it will be quoted as though it settled the question.
    s = a["strength"]
    assert s["cluster"]["p_value"] < 0.05, s["cluster"]
    assert s["cluster"]["exhaustive_null_subsets"] > 1000, "the null must be exhaustive, not a small sample"
    assert s["cluster"]["pct_of_random_clusters_clearing_the_gate"] > 1.0, (
        "if the gate were strong this would be near zero — the assertion exists to keep the weakness VISIBLE, "
        "so a future tightening of the threshold has to confront it rather than inherit it silently")
    assert s["confound"]["fisher_z_se"] > 0.10, s["confound"]


def test_double_centering_beats_raw_z_cosine_on_the_confound():
    """The whole point: the shipped (double-centered) metric must have a SMALLER severity confound than raw
    z-cosine — else the transform bought nothing.

    This test did not previously do what its name says. It never built the raw z-cosine baseline at all (the
    comment even conceded the module 'stores only the double-centered z'); it asserted `|confound(z)| < 0.2` on
    the shipped profile alone. That is an ABSOLUTE criterion wearing a comparison's name, and it is the same
    criterion — at a different constant — that the acceptance gate above already pins and currently xfails. So it
    could only ever duplicate that failure while claiming to measure something else.

    The baseline is now genuinely available (`_matrix()["z_raw"]`, the column-z profile before double-centering)
    and both numbers go through the SAME estimator, `similarity.severity_confound`. The relative claim is what
    this test is for, and it is robust where the absolute one is not. The absolute 'near zero' clause is not
    dropped — it lives on, unrelaxed, in the xfailed acceptance test, which is the honest place for it.

    NO MAGIC NUMBERS. This test used to carry two hardcoded constants — `abs(baseline) > 0.3` and
    `abs(baseline) - abs(shipped) > 0.15` — that were neither derived nor justified, and which would silently
    become wrong as the corpus grows. Both are now computed from the corpus itself:

      * the PRECONDITION (is there a confound to remove at all?) is a significance test at the corpus's own n,
        via the Fisher-z standard error 1/sqrt(n-3). It asks whether the baseline confound is distinguishable
        from zero, not whether it clears an invented constant.
      * the MARGIN (is the win real, or a rounding artifact?) is a leave-one-design-out sign test. Recompute both
        confounds with each design dropped in turn and count how often double-centering wins; require that count
        to beat a fair coin by an exact binomial tail. This is the estimator the xfail marker already cites as
        the robust claim, and it is the reason a bare `abs(shipped) < abs(baseline)` is not enough on its own:
        a single leverage point could deliver that on the full sample and nowhere else.

    The only constants left are conventional significance levels (0.05, 0.001), which are not tuned to this
    corpus and do not move when it grows."""
    _corpus()
    import math

    from cellarium import similarity
    m = similarity._matrix()
    if not m:
        pytest.skip("no matrix")
    g, designs = m["growth"], m["designs"]

    # The designs that actually enter the correlation — the same filter severity_confound applies, so `n` is the
    # real sample size rather than len(designs).
    usable = [d for d in designs if d in g and d != similarity.REFERENCE and d in m["z"]]
    n = len(usable)
    if n < 8:
        pytest.skip(f"only {n} designs carry growth — too few to compare two estimators")

    shipped = similarity.severity_confound(m["z"], g, designs)
    baseline = similarity.severity_confound(m["z_raw"], g, designs)

    # (1) PRECONDITION, derived: is the pre-transform confound distinguishable from zero at THIS n?
    # Fisher-z transform; SE = 1/sqrt(n-3); two-sided 0.05 => |z| > 1.96 * SE.
    se = 1.0 / math.sqrt(n - 3)
    z_baseline = 0.5 * math.log((1 + baseline) / (1 - baseline)) if abs(baseline) < 1 else math.inf
    assert abs(z_baseline) > 1.96 * se, (
        f"the pre-transform baseline confound is {baseline:+.3f} (Fisher z={z_baseline:+.3f}), which is not "
        f"distinguishable from zero at n={n} (SE={se:.3f}). There is no severity confound left for "
        "double-centering to remove, so this corpus can no longer demonstrate the transform's purpose.")

    # (2) THE CLAIM IN THE NAME: the shipped transform must have the smaller confound.
    assert abs(shipped) < abs(baseline), (
        f"double-centering did not reduce the severity confound: baseline {baseline:+.3f} -> shipped "
        f"{shipped:+.3f}. The transform bought nothing.")

    # (3) MARGIN, derived: the win must survive dropping any single design, more often than chance.
    wins = 0
    for d in usable:
        sub = [x for x in designs if x != d]
        if abs(similarity.severity_confound(m["z"], g, sub)) < \
                abs(similarity.severity_confound(m["z_raw"], g, sub)):
            wins += 1
    # Exact one-sided binomial tail under a fair coin: P(X >= wins).
    p = sum(math.comb(n, k) for k in range(wins, n + 1)) / (2.0 ** n)
    assert p < 0.001, (
        f"double-centering wins only {wins}/{n} leave-one-design-out folds (binomial p={p:.3g}) — the "
        f"full-sample reduction ({abs(baseline) - abs(shipped):.3f}: baseline {baseline:+.3f} -> shipped "
        f"{shipped:+.3f}) is not robust to dropping a single design, so it may rest on one leverage point.")


def test_similar_designs_reports_growth_alongside_every_neighbour_guard_a():
    """Guard (a): the de-confounded axis is partly real biology, so growth must be shown, never silently erased."""
    _corpus()
    from cellarium import similarity
    r = similarity.similar_designs("wildtype/basal", k=6)
    if "error" in r:
        pytest.skip(r["error"])
    assert r["neighbours"], "no neighbours returned"
    for n in r["neighbours"]:
        assert "growth_pct_vs_wt" in n and "cosine" in n, "a neighbour is missing its growth or cosine"
    assert "growth" in _guard_text(r).lower() or "growth_pct_vs_wt" in str(r)


def test_similar_designs_flags_severity_confounded_neighbours_guard_b():
    """Guard (b): a neighbour that also COLLAPSES (aaRS/dapA/rpmE) has similarity indistinguishable from
    lethality — it must be flagged, and an aaRS query must be flagged as confounded itself."""
    _corpus()
    from cellarium import similarity
    for n in similarity.similar_designs("wildtype/basal", k=20).get("neighbours", []):
        assert "severity_confounded" in n
    # an aaRS design is itself severity-confounded
    ar = similarity.similar_designs("gene_knockout/KO:argS", k=3)
    if "error" not in ar:
        assert ar["severity_confounded"] is True, "argS (a collapsing aaRS KO) must be flagged confounded"


def test_a_severe_but_viable_non_aaRS_design_does_not_cluster_with_the_aaRS():
    """WELL-6z6, the empirical validation: double-centering separates severe-MECHANISM from severe-LETHALITY.
    rRNA_KO:6op is severe (−34%) and viable; its neighbours must be its own mechanism, not the aaRS.

    THE MATCHER WAS WRONG, not the metric — corrected 2026-08-08. It counted an "aaRS neighbour" by substring
    (`"KO:argS" in design`), which also matches `graded_gene_knockout/KO:argS#expr:0.25` — a GRADED knockout at
    25% expression that is VIABLE (growth −30.9%) and carries `severity_confounded: False`. That design class
    did not exist when this test was written. Counting it as a leak inverts the test's own claim: a severe,
    viable, dose-limited design is exactly the right neighbour for another severe, viable design, and treating
    its arrival as failure would penalise the metric for working.

    What "severity leaking back in" actually means is a COLLAPSED design appearing as a neighbour because it is
    severe, and `similarity` already flags those itself — so the flag is the criterion, rather than a gene-name
    substring that cannot tell a 25%-expression allele from a dead one. Measured at k=12: the collapsing full
    aaRS knockouts do not appear at all, the top neighbour is the query's own mechanism (rRNA_KO:4op, cos 0.65),
    and the first confounded design is a graded argS at rank 6.

    NOT the same thing as WELL-6z4-REDO. That gate — the corpus-wide severity correlation — is still open and
    still `xfail(strict=True)` above, deliberately unrelaxed. This test is a different, narrower claim.
    """
    _corpus()
    from cellarium import similarity
    r = similarity.similar_designs("rrna_operon_knockout/minimal|rRNA_KO:6op", k=5)
    if "error" in r:
        pytest.skip("rRNA_KO:6op absent")
    leaked = [n["design"] for n in r["neighbours"] if n.get("severity_confounded")]
    assert not leaked, (
        f"a severe VIABLE design has collapsing neighbour(s) {leaked} — severity is leaking back in")
    # The positive form of the same claim, and the stronger one: the nearest neighbour is the query's OWN
    # mechanism. Absence of a leak is satisfied by noise; this is not.
    top = r["neighbours"][0]["design"]
    assert "rrna_operon_knockout" in top, (
        f"the nearest neighbour of an rRNA-operon deletion is {top!r}, not another rRNA-operon deletion — "
        "the mechanism cluster has stopped cohering, which is what this test is for")


def test_the_query_is_never_its_own_neighbour_and_unknown_designs_degrade():
    _corpus()
    from cellarium import similarity
    r = similarity.similar_designs("wildtype/basal", k=8)
    if "error" not in r:
        assert all(n["design"] != "wildtype/basal" for n in r["neighbours"])
    bad = similarity.similar_designs("gene_knockout/KO:not_a_real_gene")
    assert "error" in bad and "did_you_mean" in bad


def test_the_tool_is_registered_and_analysis_only():
    from cellarium import test_registry, tools
    assert "similar_designs" in {t["name"] for t in tools.TOOLS} and "similar_designs" in tools._DISPATCH
    assert "similar_designs" in test_registry.ANALYSIS_ONLY_TOOLS   # reads only; Council stays blind


def _guard_text(r):
    return r.get("guards", "")
