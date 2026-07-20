"""H-6: the reader worker's pure aggregation, extracted host-side (numpy-only, no wholecell) so it's unit-testable
off the sim — the exact seam the SCI-2c review flagged as untestable (a mock stood in for it and hid a real bug)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import _reader_agg  # noqa: E402


def test_gene_lfc_map_full_distribution_floor_and_counts():
    t = [{"g1": 200, "g2": 100, "lowg": 3}, {"g1": 220, "g2": 90, "lowg": 4}]
    r = [{"g1": 100, "g2": 100, "lowg": 5}, {"g1": 100, "g2": 110, "lowg": 3}]
    out = _reader_agg.gene_lfc_map(t, r, floor=20)
    assert set(out) == {"g1", "g2"}                          # lowg (mean < 20) dropped by the count floor
    assert 0.9 < out["g1"]["log2fc"] < 1.1                    # ~2x up -> ~+1 log2
    assert abs(out["g2"]["log2fc"]) < 0.2                     # ~flat
    assert out["g1"]["n_target"] == 2 and out["g1"]["n_reference"] == 2


def test_gene_lfc_map_requires_both_sides_and_handles_empty():
    assert _reader_agg.gene_lfc_map([], [{"g": 100}], floor=1) == {}     # no target runs -> empty, no crash
    out = _reader_agg.gene_lfc_map([{"g1": 100, "tonly": 100}], [{"g1": 100, "ronly": 100}], floor=1)
    assert set(out) == {"g1"}                                # a gene present on only one side has no ratio -> excluded
