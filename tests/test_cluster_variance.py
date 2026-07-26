"""Runs of different GENERATION DEPTH are not exchangeable — and the first diagnosis of this was wrong.

Three `wildtype/basal` seed-0 runs gave different numbers, and because two of them came from different
contributors the difference was attributed to the MACHINE. It was not. Those runs have `generations` 1, 4 and 7,
and a channel mean is taken over the WHOLE trajectory, so depth moves it systematically — same contributor:

    gens=1   growth 0.000248   ppGpp 60.4
    gens=4   growth 0.000222   ppGpp 65.5
    gens=7   growth 0.000220   ppGpp 70.6

Hold generations constant and the machine effect is **exactly zero**: ICC 0.0 on every channel, for both
multi-contributor designs (`wildtype/basal` n=28, `condition/acetate` n=13). Cluster on depth instead and the
ICC is 0.28-0.85 on `wildtype/basal` — the reference for EVERY comparison, whose ribosome_conc interval is
**6.6x** too narrow — and 0.83-0.99 on the `rRNA_KO:4op` dose arm.

So the corpus's real error is pooling a 1-generation run with a 7-generation one as "replicates". The machinery
here is unchanged and was always correct; only the cluster VARIABLE was wrong. These tests pin both halves —
that depth clusters, and that machine does not — so the misattribution cannot come back.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")
os.environ.setdefault("CELLARIUM_OUT", "runs")

import pytest  # noqa: E402

from cellarium import stats  # noqa: E402


# ---------------------------------------------------------------- the decomposition (pure)
def test_no_cluster_effect_leaves_the_interval_untouched():
    """The correction must not fire when it is not needed, or it becomes noise nobody reads."""
    # cluster MEANS must match for there to be no effect — spread within each may differ freely
    vals = [1.0, 1.1, 0.9,   0.95, 1.05, 1.0]
    clusters = ["a", "a", "a", "b", "b", "b"]          # both means 1.0: the cluster explains nothing
    de = stats.design_effect(vals, clusters)
    assert de["icc"] == 0.0, de
    hw, _ = stats.t95_halfwidth_clustered(vals, clusters)
    assert hw == stats.t95_halfwidth(vals), "an absent cluster effect must leave the interval alone"


def test_a_strong_cluster_effect_widens_the_interval_and_shrinks_effective_n():
    """Two tight clusters far apart: nominal n is 8, but there are really only two independent observations."""
    vals = [1.00, 1.01, 0.99, 1.00, 5.00, 5.01, 4.99, 5.00]
    clusters = ["a"] * 4 + ["b"] * 4
    de = stats.design_effect(vals, clusters)
    assert de["icc"] > 0.9 and de["n_eff"] < 3, de
    hw, info = stats.t95_halfwidth_clustered(vals, clusters)
    assert hw > stats.t95_halfwidth(vals), "a clustered interval must be WIDER, never narrower"
    assert info["unreliable"] is True, "two clusters means 1 df — the estimate must be marked unreliable"


def test_a_single_cluster_is_exactly_the_plain_interval():
    """A depth-matched design must be unchanged, or this correction silently rewrites history."""
    vals = [1.0, 1.2, 0.8, 1.1]
    hw, info = stats.t95_halfwidth_clustered(vals, ["gens=4"] * 4)
    assert hw == stats.t95_halfwidth(vals) and info is None or info["deff"] <= 1.0


def test_negative_variance_components_clamp_to_zero():
    """When between-cluster MS < within, the estimator goes negative; that means 'no cluster effect', not a
    negative variance."""
    vals = [1.0, 5.0, 1.0, 5.0, 1.0, 5.0]
    de = stats.design_effect(vals, ["a", "a", "b", "b", "c", "c"])
    assert de["icc"] == 0.0 and de["sd_between"] == 0.0


def test_it_degrades_rather_than_raising():
    assert stats.design_effect([1.0], ["a"]) is None
    assert stats.design_effect([1.0, 2.0], ["a", "b"]) is None      # 1 point per cluster: undecomposable
    assert stats.t95_halfwidth_clustered([1.0], ["a"]) == (None, None)


# ---------------------------------------------------------------- wired into the corpus
def _corpus():
    from cellarium import store
    if not store.has_manifest():
        pytest.skip("no local manifest")


def _basal(channel):
    from cellarium import survey
    return [r for r in survey._deduped_rows(survey.CHANNELS)
            if survey.design_key(r) == "wildtype/basal" and r.get("reportable")
            and r.get(channel) is not None]


def test_the_replicate_cluster_is_recoverable_for_every_row():
    """Without `generations` in the projection the correction silently does nothing — the same silent no-op that
    happened with `simout_path` back when the cluster was believed to be the machine."""
    _corpus()
    from cellarium import survey
    rows = survey._deduped_rows(survey.CHANNELS)
    clusters = {survey._replicate_cluster(r) for r in rows}
    assert len(clusters) > 1, (
        f"only found clusters {clusters} — the projection has dropped `generations`, "
        "and the cluster correction is a no-op")


def test_generation_depth_actually_shifts_the_mean():
    """The premise of the whole correction, asserted against real data rather than argued: deeper runs give
    systematically different channel means, so pooling depths is not replication."""
    _corpus()
    import statistics
    from collections import defaultdict
    byg = defaultdict(list)
    for r in _basal("ppgpp_conc"):
        byg[r.get("generations")].append(r["ppgpp_conc"])
    means = {g: statistics.fmean(v) for g, v in byg.items() if len(v) >= 2}
    if len(means) < 2:
        pytest.skip("this corpus runs wildtype/basal at a single depth")
    assert max(means.values()) - min(means.values()) > 2.0, (
        f"ppGpp means by depth {means} — if depth has stopped mattering, revisit the clustering")


def test_machine_is_NOT_the_cluster_because_its_effect_is_zero():
    """The correction that itself had to be corrected. At a FIXED depth the contributor explains nothing, so
    clustering on it would widen intervals for no reason while hiding the real driver."""
    _corpus()
    from cellarium import survey
    rows = [r for r in _basal("growth_rate") if r.get("generations") == 1]
    if len({survey._machine(r) for r in rows}) < 2 or len(rows) < 6:
        pytest.skip("no depth-matched multi-contributor subset here")
    for ch in ("growth_rate", "ppgpp_conc", "ribosome_conc"):
        v = [r[ch] for r in rows if r.get(ch) is not None]
        c = [survey._machine(r) for r in rows if r.get(ch) is not None]
        de = stats.design_effect(v, c)
        assert de is None or de["icc"] < 0.05, f"machine ICC on {ch} is {de['icc']} — re-examine the diagnosis"


def test_the_reference_designs_interval_is_actually_widened():
    """wildtype/basal is the reference for every comparison, and it pools depths 1, 4 and 7 — leaving its
    ribosome_conc interval 6.6x too narrow."""
    _corpus()
    from cellarium import survey
    rows = _basal("ribosome_conc")
    vals = [r["ribosome_conc"] for r in rows]
    clus = [survey._replicate_cluster(r) for r in rows]
    if len(set(clus)) < 2:
        pytest.skip("this corpus runs every design at one depth")
    naive = stats.t95_halfwidth(vals)
    clustered, info = stats.t95_halfwidth_clustered(vals, clus)
    assert clustered > naive, "a depth-mixed interval must widen"
    assert info["widened_by"] > 2 and info["icc"] > 0.5, info


def test_survey_reports_the_cluster_structure_it_corrected_for():
    """A widened interval that does not say why is not auditable.

    Asserted on `coverage`, not on the ranked entries, because the ranking is truncated to the top |z| and the
    design that most needs the warning — `wildtype/basal` — sits at z~0 BY CONSTRUCTION (it is the reference).
    This test skipped silently for exactly that reason while the per-entry block was the only disclosure."""
    _corpus()
    from cellarium import survey
    s = survey.survey_corpus()
    mixed = s["coverage"]["designs_mixing_generation_depth"]
    assert "wildtype/basal" in mixed, f"the reference pools depths 1/4/7 and must say so: {mixed}"
    assert "generation depth" in s["coverage"]["note"]
    flagged = [e for d in s["by_channel"].values() for e in d["ranked"] if e.get("cluster")]
    if flagged:
        assert {"n_clusters", "icc", "deff", "n_eff", "unreliable"} <= set(flagged[0]["cluster"])


def test_differential_flags_an_anti_conservative_p_value():
    """The Welch t over pooled seeds is anti-conservative when either side mixes depths. It must say so — and
    must name DEPTH, because naming the machine is what sent the first fix to the wrong place."""
    _corpus()
    from cellarium import differential
    r = differential.summary("condition/acetate", "wildtype/basal")
    tested = [m for m in r["ranked"] if m.get("p_value") is not None]
    if not tested:
        pytest.skip("no tested movers")
    caveats = [m.get("clustered_caveat") or "" for m in tested]
    assert any("ANTI-CONSERVATIVE" in c for c in caveats)
    assert any("generation depths" in c for c in caveats), "the caveat must name depth, not machine"
