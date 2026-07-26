"""What a `gene_knockout` ACTUALLY does — measured, with predictions kept clearly separate.

MECHANISM (code-traced). `gene_knockout.py` calls `sim_data.adjust_final_expression([i],[0])`; that zeroes
`rna_synth_prob[i]`/`rna_expression[i]`, indexed over `rna_data`, whose rows are TRANSCRIPTION UNITS. One TU is
zeroed. This depends on the corpus being built operons-ON — it was.

EVIDENCE, and the honesty this file exists to enforce. An earlier version of this module asserted "a gene is
silenced iff n_tu == 1" and claimed 27/27 validation. That was OVERFIT to three genes. Across 41 measurements
it is 40/41, and the one failure is the informative half:

  * `n_tu == 1` -> silenced: no counterexample (0 false positives in 41). Safe as a SUFFICIENT condition.
  * `n_tu > 1`  -> survives: FALSE. `KO:dapA` fully silenced `bamC` (n_tu=2), measured 0.0 vs 2.6.

So the cache must never present a prediction as a finding. These tests pin the measurements as ground truth and
pin the separation between `measured_*` and `unverified`.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")

import pytest  # noqa: E402

from cellarium import scope  # noqa: E402

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "ko_footprint.json")
pytestmark = pytest.mark.skipif(not os.path.exists(CACHE), reason="ko_footprint cache not built")

# MEASURED from real simOut (mean mRNA counts, KO vs wildtype/basal). The empirical anchor for the rule.
MEASURED = {   # from real simOut: (KO mean, wildtype mean) mRNA cistron counts
    ("flgB", "flgB"): (0.0, 5.8), ("flgB", "flgJ"): (0.0, 5.8),
    ("rpoB", "rpoB"): (10.4, 8.4), ("rpoB", "rpoC"): (10.4, 8.4),
    ("rpmJ", "rpmJ"): (50.1, 69.5), ("rpmJ", "secY"): (0.0, 15.8),
    ("dapA", "dapA"): (0.0, 2.6), ("dapA", "bamC"): (0.0, 2.6),
}


def test_the_cache_reproduces_every_measurement():
    """Ground truth is the simulation, not the rule. If the cache disagrees with a measured count, it is wrong."""
    for (ko, gene), (ko_mean, wt_mean) in MEASURED.items():
        fp = scope.ko_footprint(ko)
        assert fp, f"{ko} should have a footprint"
        m = (fp.get("measured") or {}).get(gene)
        assert m, f"KO:{ko} / {gene} should carry a measurement"
        assert m["ko_mean"] == ko_mean and m["wt_mean"] == wt_mean
        assert m["silenced"] == (ko_mean == 0.0)


def test_the_n_tu_rule_is_recorded_as_a_prior_not_a_law():
    """THE counterexample. bamC has two TUs and was fully silenced anyway, so 'n_tu > 1 means it survives' is
    false. The cache must classify bamC from the MEASUREMENT, not from n_tu."""
    fp = scope.ko_footprint("dapA")
    assert fp["measured"]["bamC"]["silenced"] is True
    assert "bamC" in fp["measured_silenced"] and "bamC" not in fp.get("unverified", [])


def test_flgB_is_a_nine_gene_operon_deletion_measured():
    fp = scope.ko_footprint("flgB")
    assert fp["target_silenced"] is True and fp["target_evidence"] == "measured"
    assert set(fp["measured_silenced"]) == {"flgC", "flgD", "flgE", "flgF", "flgG", "flgH", "flgI", "flgJ"}


def test_rpoB_measured_not_knocked_out():
    """The corpus explains rpoB survival by a 'large inherited RNAP reserve'. Measured: rpoB mRNA does not fall."""
    fp = scope.ko_footprint("rpoB")
    assert fp["target_silenced"] is False and fp["target_evidence"] == "measured"
    assert fp["measured"]["rpoB"]["ko_mean"] > fp["measured"]["rpoB"]["wt_mean"] * 0.9


def test_rpmJ_silences_secY_instead():
    fp = scope.ko_footprint("rpmJ")
    assert fp["target_silenced"] is False and fp["measured_silenced"] == ["secY"]


def test_an_unmeasured_design_is_labelled_unverified_not_asserted():
    """rplB's run has no simOut. An earlier BACKLOG row implied it was measured; it was not."""
    fp = scope.ko_footprint("rplB")
    assert fp["target_evidence"] == "predicted_from_n_tu"
    assert fp["unverified"] and not fp["measured_silenced"]
    w = scope.classify_gene("rplB")["ko_footprint"]["warning"]
    assert "unverified" in w and "does NOT guarantee survival" in w


def test_a_clean_single_gene_knockout_reports_nothing():
    for clean in ("pfkA", "argS", "gltX", "tpiA"):
        assert scope.ko_footprint(clean) is None, f"{clean} should be clean"


def test_warnings_distinguish_measured_from_predicted():
    w_meas = scope.classify_gene("rpoB")["ko_footprint"]["warning"]
    assert "MEASURED" in w_meas
    w_pred = scope.classify_gene("rplB")["ko_footprint"]["warning"]
    assert "MEASURED fully silenced" not in w_pred


def test_the_five_corpus_designs_that_may_not_be_knockouts_stay_flagged():
    for g in ("dnaN", "murA", "pheS", "rpmJ", "rpoB"):
        fp = scope.ko_footprint(g)
        assert fp and fp["target_silenced"] is False, f"{g} should be flagged"


def test_cache_shape_is_sane():
    data = json.load(open(CACHE, encoding="utf-8"))
    assert 2200 < len(data) < 3200
    assert all("co_members" in v and "target_evidence" in v for v in data.values())
    assert sum(1 for v in data.values() if v["target_evidence"] == "measured") >= 8
