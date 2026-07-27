"""WELL-1x: per-generation reporting — read a channel AT a generation, compare two designs at one generation,
and inspect a design's per-generation arc.

The summary channel is the LAST generation's mean, so the ordinary tools compare designs at whatever depth each
reached. These operations read a specific generation instead — which is what makes a COLLAPSING run's valid
early generations usable (reportability is whole-run; QC is per-generation) and lets a lethal KO be compared to
WT at the generation before it collapses.
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


def test_read_at_generation_uses_a_collapsing_runs_valid_early_generations():
    """The point of per-generation reporting: argS collapses at gen 2, but its gen-0 is valid on every seed, so
    reading at generation 0 must give n>1 — the power we would otherwise have launched new sims for."""
    _corpus()
    from cellarium import survey
    r = survey.read_at_generation("gene_knockout/KO:argS", "ppgpp_conc", 0)
    if "error" in r or r.get("n", 0) == 0:
        pytest.skip("argS not present here")
    assert r["n"] >= 2, f"argS gen-0 ppGpp is n={r['n']} — the collapsed runs' valid gen-0 is not being used"
    assert r["mean"] is not None


def test_read_at_generation_refuses_channels_not_stored_per_generation():
    """Only growth/ppGpp are per-generation. Asking for another must be an explicit refusal, not a silent empty
    result an agent could misread as 'no effect'."""
    _corpus()
    from cellarium import survey
    r = survey.read_at_generation("wildtype/basal", "ribosome_conc", 0)
    assert "error" in r and "per generation" in r["error"]


def test_trajectory_makes_a_collapse_visible_as_a_qc_transition():
    """Inspecting a lethality case: the arc must show good early generations, then the generation where QC turns
    bad — the collapse, made legible instead of hidden."""
    _corpus()
    from cellarium import survey
    t = survey.trajectory("gene_knockout/KO:dapA", "growth_rate")
    if "error" in t:
        pytest.skip("dapA not present here")
    assert t["collapses_at_generation"] is not None and t["collapses_at_generation"] >= 1
    early = t["arc"][0]
    assert early["qc"].get("ok", 0) >= 1 and early["mean"] is not None, "the first generation should be usable"
    collapsed = t["arc"][t["collapses_at_generation"]]
    assert collapsed["mean"] is None and any(k != "ok" for k in collapsed["qc"]), (
        "the collapse generation must read as its QC verdict, never a garbage mean")


def test_trajectory_shows_dapAs_stringent_then_arrest_signature():
    """The concrete inspection: dapA's ppGpp is hugely elevated over its early generations, then it arrests."""
    _corpus()
    from cellarium import survey
    t = survey.trajectory("gene_knockout/KO:dapA", "ppgpp_conc")
    if "error" in t:
        pytest.skip("dapA not present here")
    pre = [a["mean"] for a in t["arc"] if a["mean"] is not None]
    assert pre and max(pre) > 200, f"dapA pre-collapse ppGpp maxes at {max(pre) if pre else None} — expected >200"


def test_compare_at_generation_is_like_for_like_and_has_no_depth_mismatch():
    """The 1-to-1 operation: argS vs WT at generation 0. It must return a diff without any depth-mismatch note,
    because both sides are read at ONE generation."""
    _corpus()
    from cellarium import survey
    c = survey.compare_at_generation("gene_knockout/KO:argS", "wildtype/basal", "ppgpp_conc", 0)
    if "error" in c or not c.get("a", {}).get("n") or not c.get("b", {}).get("n"):
        pytest.skip("argS/WT gen-0 not both present")
    assert "pct_a_vs_b" in c and "depth_note" not in c and "depth_mismatch" not in c
    # argS ppGpp is NOT elevated vs WT even at gen 0 — the honest, depth-matched read
    assert c["pct_a_vs_b"] < 0, f"argS gen-0 ppGpp reads {c['pct_a_vs_b']}% vs WT — expected lower, not elevated"


def test_the_per_generation_tools_are_registered():
    from cellarium import tools
    names = {t["name"] for t in tools.TOOLS}
    for n in ("trajectory", "compare_at_generation"):
        assert n in names and n in tools._DISPATCH


def test_it_degrades_rather_than_raising(monkeypatch):
    from cellarium import survey
    monkeypatch.setattr(survey, "_leth_rows", lambda: [{"__error__": "boom"}])
    assert "error" in survey.trajectory("x/y", "growth_rate")
    assert "error" in survey.read_at_generation("x/y", "growth_rate", 0)
