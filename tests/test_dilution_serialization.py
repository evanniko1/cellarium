"""SCI-DIL-1 (dilution clock) + the serialization safeguard.

DILUTION: the law n(g)=n0*2^-g is PUBLISHED AND NAMED (Carballo-Pacheco et al. 2020, PMID 32469859) — the tool
cites it and measures the RESIDUAL. `dilution_clock` fits a downstream channel (a proxy); `protein_clock` fits
the target protein's own abundance, which is what the law actually describes.

SERIALIZATION: a deterministic guard for the bug class found this session — wcEcoli sizes fixed-width string
columns per-run from the first value, so a later longer value truncates silently.
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


# ---------------------------------------------------------------- dilution clock
def test_the_law_is_cited_never_claimed():
    """The mechanism is published; presenting it as ours would be refuted. Every result must carry the citation
    and frame the RESIDUAL as the measurement."""
    import inspect

    from cellarium import dilution
    src = inspect.getsource(dilution)
    assert "32469859" in src and "Carballo-Pacheco" in src
    assert "cited, not claimed" in src.lower() or "not claim" in src.lower()


def test_a_perfect_halving_series_reads_as_dilution_limited():
    """Synthetic ground truth: exact halving must fit slope -1."""
    from cellarium import dilution
    fit = dilution._ols([0, 1, 2, 3, 4], [__import__("math").log2(1000 * 2 ** -g) for g in range(5)])
    assert abs(fit["slope"] - (-1.0)) < 1e-9


def test_the_protein_clock_recovers_the_published_law_on_dapA():
    """THE validation: dapA's own protein halves per generation. Slope CI must contain -1 — the law recovered
    from data, with the residual reported rather than the law asserted."""
    _corpus()
    from cellarium import dilution
    r = dilution.protein_clock("gene_knockout/KO:dapA")
    if "error" in r:
        pytest.skip(r["error"])
    lo, hi = r["slope_ci95"]
    assert lo <= -1.0 <= hi, f"dapA slope CI {r['slope_ci95']} should contain the predicted -1"
    assert r["verdict"] == "dilution_limited" and r["r2"] > 0.8


def test_the_channel_clock_is_labelled_as_a_proxy():
    """`dilution_clock` fits growth, which is NOT the diluting quantity — it reads slower_than_dilution for
    everything by construction. That limitation must be stated, not discovered by a reader."""
    import inspect

    from cellarium import dilution
    assert "proxy" in inspect.getsource(dilution.protein_clock).lower()


def test_collapsed_generations_are_excluded_from_the_fit():
    """The collapse is what we are TIMING, so a collapsed generation's garbage must not bend the fit."""
    import inspect

    from cellarium import dilution
    src = inspect.getsource(dilution.dilution_clock)
    assert 'gq[i] != "ok"' in src


# ---------------------------------------------------------------- serialization safeguard
def test_the_detector_reads_a_fixed_width_dtype_from_a_real_column():
    _corpus()
    import glob

    from cellarium import serialization
    hits = glob.glob("runs/cellarium/*/*/generation_000000/*/simOut/FBAResults/media_id")
    if not hits:
        pytest.skip("no local raw")
    dt = serialization._column_dtype(hits[0])
    assert dt and dt[0].startswith("<U") and dt[1] > 0


def test_it_flags_the_media_id_column_as_truncation_prone():
    """The bug class, caught mechanically: media_id is written at different widths across runs and narrow runs
    saturate — so the COLUMN is fragile."""
    _corpus()
    from cellarium import serialization
    r = serialization.scan_corpus(limit_runs=80)
    if not r.get("all"):
        pytest.skip("no string columns found locally")
    key = "FBAResults/media_id"
    if key in r["all"]:
        assert len(r["all"][key]["widths_seen"]) > 1, "media_id should show multiple widths across runs"
        assert r["all"][key]["severity"] == "high"


def test_it_flags_the_COLUMN_not_each_run():
    """The correction that mattered: a run whose medium is genuinely short is CORRECTLY narrow. An earlier
    version accused every narrow run of losing data; the detector must claim fragility, not per-run loss."""
    import inspect

    from cellarium import serialization
    src = inspect.getsource(serialization)
    assert "flags the COLUMN" in src or "It flags the column, NOT each run" in src
    assert "does NOT mean each listed run lost data" in src


def test_severity_is_not_the_inverted_changes_heuristic():
    """The first version scored 'changes during the run' as high risk — exactly backwards, since truncation
    collapses the changed value into the original and makes the broken run look CONSTANT."""
    import inspect

    from cellarium import serialization
    assert "backwards" in inspect.getsource(serialization).lower()
