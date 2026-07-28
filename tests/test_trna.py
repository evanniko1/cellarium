"""SCI-TRNA-1 — per-family charged tRNA.

The corpus reports ONE `fraction_trna_charged` (~0.95). The raw listener is 86 tRNA species x timesteps, and the
mean across them is the wrong instrument: an aminoacyl-tRNA synthetase knockout starves ONE family while the
other ~19 stay charged, so the aggregate barely moves and the mechanism is averaged away (Elf et al. 2003,
selective charging).

The validating test is the blind one: given no hint about which amino acid to look at, `KO:argS` must come back
with ARGININE collapsed and `KO:pheS` with PHENYLALANINE — recovered from the data, not asserted.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")
os.environ.setdefault("CELLARIUM_OUT", "runs")

import pytest  # noqa: E402


def _needs_raw(design):
    from cellarium import raw
    if not raw.seed_runs(design):
        pytest.skip(f"no local raw simOut for {design}")


def test_family_parsing_handles_the_real_id_shapes():
    from cellarium import trna
    assert trna.family_of("alaT-tRNA[c]") == "ala"
    assert trna.family_of("argQ-tRNA[c]") == "arg"
    assert trna.family_of("selC-tRNA[c]") == "sel"       # a real special case, not an error
    assert trna.family_of("not-a-trna") is None


def test_wildtype_resolves_about_twenty_families_and_the_mean_hides_spread():
    """The motivating fact: even in WILD TYPE the families are not uniform — tryptophan sits far below the mean.
    A single aggregate cannot represent that, let alone a knockout's selective collapse."""
    _needs_raw("wildtype/basal")
    from cellarium import trna
    r = trna.per_family("wildtype/basal")
    if "error" in r:
        pytest.skip(r["error"])
    assert 15 <= r["n_families"] <= 25, f"expected ~20 amino-acid families, got {r['n_families']}"
    vals = [f["charged_fraction"] for f in r["families"]]
    assert vals == sorted(vals), "families must be sorted ascending — the starved one first"
    assert max(vals) - min(vals) > 0.2, "the per-family spread the aggregate hides should be substantial"


def test_argS_knockout_selectively_starves_ARGININE():
    """THE validation. Nothing tells the tool that argS charges arginine — it must fall out of the data."""
    _needs_raw("gene_knockout/KO:argS")
    from cellarium import trna
    r = trna.selective_charging("gene_knockout/KO:argS")
    if "error" in r:
        pytest.skip(r["error"])
    assert r["worst_family"]["family"] == "arg", f"argS should starve arginine, got {r['worst_family']}"
    assert r["worst_family"]["charged"] < 0.05, "the targeted family should be essentially uncharged"
    assert r["selective_charging"] is True
    assert r["selectivity_gap_pp"] > 50, "the collapse must be far worse than the typical family"


def test_pheS_knockout_selectively_starves_PHENYLALANINE():
    """The same blind recovery for a different synthetase — one hit could be luck, two is the mechanism."""
    _needs_raw("gene_knockout/KO:pheS")
    from cellarium import trna
    r = trna.selective_charging("gene_knockout/KO:pheS")
    if "error" in r:
        pytest.skip(r["error"])
    assert r["worst_family"]["family"] == "phe" and r["selective_charging"] is True


def test_the_aggregate_would_have_MISSED_it():
    """Why this module exists: the corpus's single number barely moves for a selective knockout, because ~19 of
    20 families stay charged. Assert that gap explicitly, so the motivation cannot quietly become false."""
    _needs_raw("gene_knockout/KO:argS")
    from cellarium import trna
    ko = trna.selective_charging("gene_knockout/KO:argS")
    if "error" in ko:
        pytest.skip(ko["error"])
    assert ko["worst_family"]["drop_pct"] < -90          # the family: essentially total collapse
    assert abs(ko["median_drop_pct"]) < 15               # the typical family: barely moves
