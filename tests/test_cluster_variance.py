"""Seeds are NOT exchangeable across machines — the corpus pools contributors.

`wildtype/basal` seed 0 exists three times, from three run paths, and the values DIFFER: growth 0.000244 on one
contributor's machine vs 0.000226 on ours; ppGpp 65.13 vs 64.05. So the model is not bit-deterministic across
environments. Those are genuine independent replicates (not one run counted thrice) — but they are CLUSTERED,
and `s/sqrt(n)` over the pooled set treats correlated observations as independent.

Measured on this corpus the effect is large, not academic:

  * `wildtype/basal` — the reference for EVERY comparison — ICC 0.09-0.29, n 34 -> n_eff 6-14, and the 95%
    interval on growth_rate is **2.67x wider** once corrected;
  * `rRNA_KO:4op` — a headline dose arm — ICC 0.70-0.79, n 10 -> n_eff 2.5.

Understating the reference's uncertainty propagates into every differential, which is why this is fixed before
the write-up rather than footnoted in it.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")
os.environ.setdefault("CELLARIUM_OUT", "runs")

import pytest  # noqa: E402

from cellarium import stats  # noqa: E402


# ---------------------------------------------------------------- the decomposition (pure)
def test_no_machine_effect_leaves_the_interval_untouched():
    """The correction must not fire when it is not needed, or it becomes noise nobody reads."""
    # cluster MEANS must match for there to be no effect — spread within each may differ freely
    vals = [1.0, 1.1, 0.9,   0.95, 1.05, 1.0]
    clusters = ["a", "a", "a", "b", "b", "b"]          # both means 1.0: machine explains nothing
    de = stats.design_effect(vals, clusters)
    assert de["icc"] == 0.0, de
    hw, _ = stats.t95_halfwidth_clustered(vals, clusters)
    assert hw == stats.t95_halfwidth(vals), "an absent cluster effect must leave the interval alone"


def test_a_strong_machine_effect_widens_the_interval_and_shrinks_effective_n():
    """Two tight clusters far apart: nominal n is 8, but there are really only two independent observations."""
    vals = [1.00, 1.01, 0.99, 1.00, 5.00, 5.01, 4.99, 5.00]
    clusters = ["a"] * 4 + ["b"] * 4
    de = stats.design_effect(vals, clusters)
    assert de["icc"] > 0.9 and de["n_eff"] < 3, de
    hw, info = stats.t95_halfwidth_clustered(vals, clusters)
    assert hw > stats.t95_halfwidth(vals), "a clustered interval must be WIDER, never narrower"
    assert info["unreliable"] is True, "two clusters means 1 df — the estimate must be marked unreliable"


def test_a_single_machine_is_exactly_the_plain_interval():
    """Single-contributor results must be unchanged, or this correction silently rewrites history."""
    vals = [1.0, 1.2, 0.8, 1.1]
    hw, info = stats.t95_halfwidth_clustered(vals, ["local"] * 4)
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


def test_the_machine_is_recoverable_for_every_row():
    """Without this the correction silently does nothing — which is exactly what happened until `simout_path`
    was added to the survey projection."""
    _corpus()
    from cellarium import survey
    rows = survey._deduped_rows(survey.CHANNELS)
    machines = {survey._machine(r) for r in rows}
    assert machines and machines != {"local"}, (
        f"only found machines {machines} — the projection has dropped simout_path/machine again, "
        "and the cluster correction is a no-op")


def test_the_reference_designs_interval_is_actually_widened():
    """wildtype/basal is the reference for every comparison; its naive interval was ~2.7x too narrow."""
    _corpus()
    from cellarium import survey
    rows = [r for r in survey._deduped_rows(survey.CHANNELS)
            if survey.design_key(r) == "wildtype/basal" and r.get("reportable")]
    vals = [r["growth_rate"] for r in rows if r.get("growth_rate") is not None]
    mach = [survey._machine(r) for r in rows if r.get("growth_rate") is not None]
    if len(set(mach)) < 2:
        pytest.skip("this corpus has a single contributor")
    naive = stats.t95_halfwidth(vals)
    clustered, info = stats.t95_halfwidth_clustered(vals, mach)
    assert clustered > naive, "the reference's interval must widen once clustering is accounted for"
    assert info["widened_by"] > 1.5 and info["icc"] > 0.1


def test_survey_reports_the_cluster_structure_it_corrected_for():
    """A widened interval that does not say why is not auditable."""
    _corpus()
    from cellarium import survey
    s = survey.survey_corpus()
    flagged = [e for d in s["by_channel"].values() for e in d["ranked"] if e.get("cluster")]
    if not flagged:
        pytest.skip("no multi-machine design in the ranked view")
    c = flagged[0]["cluster"]
    assert {"n_clusters", "icc", "deff", "n_eff", "unreliable"} <= set(c)


def test_differential_flags_an_anti_conservative_p_value():
    """The Welch t over pooled seeds is anti-conservative when either side spans machines. It must say so."""
    _corpus()
    from cellarium import differential
    r = differential.summary("condition/acetate", "wildtype/basal")
    tested = [m for m in r["ranked"] if m.get("p_value") is not None]
    if not tested:
        pytest.skip("no tested movers")
    assert any("ANTI-CONSERVATIVE" in (m.get("clustered_caveat") or "") for m in tested)
