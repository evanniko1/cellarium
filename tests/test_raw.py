"""Raw simOut drill-down: the host-side COLM reader + cross-seed variance band.

These exercise the real local raw simOut (numpy-only reader, no Docker). They SKIP cleanly when no design has raw
on local disk (e.g. CI without the corpus), so they protect the feature locally without breaking a corpus-less run.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")

from cellarium import raw, store  # noqa: E402
from cellarium import tools  # noqa: E402


def _a_design_with_local_raw():
    """A design label that has >=2 seeds of raw simOut on local disk, or None."""
    seen = {}
    for r in store.list_results():
        pert, cond = r.get("perturbation"), r.get("condition")
        label = f"{pert}/{cond}" if cond else pert
        seen.setdefault(label, 0)
    for label in seen:
        if len(raw.seed_runs(label)) >= 2:
            return label
    return None


def _a_single_gen_design_with_local_raw():
    """A design whose local seeds are SINGLE-generation — so 'raw mean over all timesteps' is apples-to-apples with
    the manifest per-seed value (which means over the last generation). Multi-gen designs legitimately differ."""
    for r in store.list_results():
        pert, cond = r.get("perturbation"), r.get("condition")
        label = f"{pert}/{cond}" if cond else pert
        runs = raw.seed_runs(label)
        if runs and all(x["n_gens"] == 1 for x in runs):
            return label
    return None


def test_read_column_matches_manifest_mean():
    """The self-contained COLM reader must agree with the grounded manifest: a seed's raw growth_rate mean should
    match that seed's manifest growth_rate value (the manifest was built from the same column)."""
    design = _a_single_gen_design_with_local_raw()
    if not design:
        pytest.skip("no local single-generation design available")
    r0 = raw.seed_runs(design)[0]
    t, v = raw.seed_channel(r0["root"], "growth_rate")
    assert t.size > 10 and v.size == t.size
    manifest_mean = store.read_channel(r0["result_id"], "growth_rate").get("value")
    if manifest_mean is not None:
        # nan at t=0 is dropped in raw; on a single-gen design the means agree to a few %%
        assert abs(float(v.mean()) - float(manifest_mean)) <= 0.15 * abs(float(manifest_mean)) + 1e-9


def test_cross_seed_band_is_grounded_and_json_safe():
    design = _a_design_with_local_raw()
    if not design:
        pytest.skip("no local raw simOut available")
    band = raw.cross_seed_band(design, "growth_rate", n_points=12)
    assert "error" not in band, band
    assert band["n_seeds"] >= 2
    assert 4 <= len(band["series"]) <= 12
    for p in band["series"]:
        assert p["hi"] is None or p["lo"] is None or p["hi"] >= p["lo"]  # band bounds ordered
    import json
    json.dumps(band)  # no numpy leaks


def test_variance_band_needs_two_seeds():
    """A single result_id (not a design) can't yield a cross-seed band."""
    design = _a_design_with_local_raw()
    if not design:
        pytest.skip("no local raw simOut available")
    rid = raw.seed_runs(design)[0]["result_id"]
    out = raw.cross_seed_band(rid, "growth_rate")
    assert "error" in out and "seed" in out["error"].lower()


def test_chart_band_builds_layered_spec():
    design = _a_design_with_local_raw()
    if not design:
        pytest.skip("no local raw simOut available")
    out = tools.chart(kind="band", channel="growth_rate", result_id=design, rationale="test")
    assert "spec" in out, out
    assert len(out["spec"]["layer"]) == 2  # area ribbon + mean line
    assert out["provenance"]["n_seeds"] >= 2
    import json
    json.dumps(out)


def test_raw_tools_registered():
    names = {s["name"] for s in tools.TOOLS}
    for n in ("read_raw_series", "variance_band", "raw_available", "download_raw"):
        assert n in names and n in tools._DISPATCH


def test_chart_design_alias():
    """chart(kind='band', design=...) must work (the agent naturally uses `design`, matching variance_band)."""
    design = _a_design_with_local_raw()
    if not design:
        pytest.skip("no local raw simOut available")
    out = tools.chart(kind="band", design=design, channel="growth_rate", rationale="alias")
    assert "spec" in out and len(out["spec"]["layer"]) == 2


def test_download_gate_never_downloads_without_confirm():
    """The size gate's core safety property: confirm=False must NEVER download — no 'downloaded' key, ever. Holds
    with or without network (no network -> nothing resolves as on-HF -> still no download)."""
    for design in ("condition/no_oxygen", "gene_knockout/KO:rpoB", "wildtype/basal"):
        out = tools.download_raw(design)  # confirm defaults False
        assert not out.get("downloaded"), (design, out)   # nothing actually pulled
        # if there IS something to pull, it must be gated behind an explicit confirmation
        if out.get("n_to_pull", 0) > 0:
            assert out.get("needs_confirmation") is True
            assert "est_gb" in out and "GB" in out.get("message", "")


def test_list_results_filter_answers_are_there_results_for_gene():
    """Regression for the 'Are there results for pfkA?' failure: the full list is long and gets truncated in
    context, so a targeted gene filter must return just that KO's runs (never conclude absence from a dump), and
    read_series must accept the design-label form, not only a raw result id."""
    ko_genes = sorted({(r.get("condition") or "").replace("KO:", "") for r in tools.list_results()["results"]
                       if r.get("perturbation") == "gene_knockout" and "KO:" in (r.get("condition") or "")})
    if not ko_genes:
        pytest.skip("no gene_knockout runs in the manifest")
    g = ko_genes[0]
    hit = tools.list_results(gene=g)
    assert hit["n"] >= 1 and all(g.lower() in (r.get("label") or "").lower() for r in hit["results"])
    assert tools.list_results(gene="zzz_not_a_gene")["n"] == 0            # genuinely absent -> n=0, not a blob
    rs = tools.read_series(f"gene_knockout/KO:{g}", "growth_rate")        # design-label form must resolve
    assert "error" not in rs or "did_you_mean" in rs
