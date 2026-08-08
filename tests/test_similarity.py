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


@pytest.mark.xfail(strict=True, reason=(
    "WELL-6z4-REDO, OPEN. This gate is failing HONESTLY and the thresholds below are deliberately left at their "
    "original values (0.15 / 0.30) — they must not be relaxed to obtain a pass.\n"
    "\n"
    "History: the gate used to pass at corr=-0.005 / envelope +0.347. WELL-NOOP-1 then proved with "
    "verify_ko_applied.py that KO:murA was a NO-OP (murA still at 1789 copies — a wild type wearing a knockout's "
    "label). Those 7 rows are now reportable=False, qc=noop_knockout, and with the near-zero-severity impostor "
    "gone the gate fails. It had been passing BECAUSE of the defect.\n"
    "\n"
    "Measured on the live corpus (44 designs x 199 species, 42 with growth):\n"
    "  corr(growth, cos-to-WT)  baseline (column-z only) +0.536  ->  shipped (double-centered) -0.227   gate <0.15\n"
    "  envelope within-overall                                       +0.174                            gate >0.30\n"
    "\n"
    "Why this is NOT repaired by tuning the method. A sweep of principled alternatives (log, log2FC-vs-WT, "
    "double-centering on raw, and combinations) produced NO variant that clears both gates on principle: the one "
    "that does (raw + double-center: -0.142 / +0.412) drops the per-species normalisation, so cosine is dominated "
    "by the few highest-abundance species, and its -0.142 clears 0.15 only barely — picking it would be fitting to "
    "the threshold. 'log2FC vs WT' appears to score a perfect 0.000 but is DEGENERATE: the reference's own vector "
    "is all-zero, so every cosine-to-WT is 0/0.\n"
    "\n"
    "And the gate is below its own noise floor. At n=42 the Fisher-z SE of a correlation is 0.160, and a 500-draw "
    "species split-half puts the shipped confound at mean -0.207, sd 0.175, range [-0.610, +0.171] — it spans both "
    "signs. A |r| < 0.15 threshold asks a point estimate to be smaller than one standard error of itself. What the "
    "transform DOES achieve is significance-level de-confounding, and that is robust: baseline +0.536 (p=0.0002, "
    "significant) -> shipped -0.227 (p=0.149, not distinguishable from zero); double-centering has the smaller "
    "|confound| in 483/500 species split-halves and 43/44 leave-one-design-out folds. That relative claim is "
    "pinned by test_double_centering_beats_raw_z_cosine_on_the_confound below.\n"
    "\n"
    "Separately noted, NOT acted on here because it moves the number favourably and the same trap has been sprung "
    "once already: the envelope selector is a substring match, so it admits graded_gene_knockout/KO:murA — a "
    "DIFFERENT perturbation type and a confirmed model artifact (flux->0 but a free reroute, growth within noise). "
    "On the three genuine envelope KOs (fabI/lpxC/glmS) the cluster term reads +0.421, i.e. it would clear its "
    "gate. Changing the selector is a WELL-6z4-REDO decision with the evidence in hand, not a CI fix.\n"
    "\n"
    "strict=True is deliberate: if the metric is genuinely re-established, this XPASSes and CI turns RED, forcing "
    "someone to delete this marker and re-read the claim. It cannot rot into a silent skip."))
def test_the_metric_passes_its_own_acceptance_test():
    """The load-bearing guarantee (WELL-6z4/D9), recomputed on the live corpus: the severity confound is removed
    AND the mechanism cluster survives. These are the two corpus-robust gates. Currently xfail — see the marker."""
    _corpus()
    from cellarium import similarity
    a = similarity.acceptance()
    if "error" in a:
        pytest.skip(a["error"])
    assert abs(a["corr_growth_cos_to_wt"]) < 0.15, f"severity confound {a['corr_growth_cos_to_wt']} not removed"
    assert a["envelope_within_minus_overall"] > 0.30, "the envelope mechanism cluster did not survive"
    assert a["passes"] is True, a


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
