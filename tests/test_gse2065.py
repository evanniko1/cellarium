"""Artifact check for the GSE2065 reanalysis: every number the manuscript prints, re-derived here.

WHY THIS TEST EXISTS. Section 4's error floors are the paper's only empirical result, and they are
quoted to three decimals. Nothing else in the suite would notice if the derived tables drifted -- a
changed probe grouping, a median tie broken differently, a re-deposited GEO record. This pins the
published values so drift fails loudly rather than silently invalidating a printed claim.

The default tests read the COMMITTED derived tables and need no network, so CI stays hermetic.
test_full_chain_from_geo re-fetches the raw record and reruns the whole pipeline; it is skipped
without network, because an offline machine must not report a download failure as a data problem.

Run: python -m pytest tests/test_gse2065.py
"""
from __future__ import annotations

import csv
import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "gse2065"
GROUPS = ["LeuPQVT", "LeuU", "LeuW", "LeuX", "LeuZ"]

# Section 4 and Appendix B, as printed. Keep these literal: the point is to compare against the
# manuscript, so reading them from the artifact they check would defeat the test.
PAPER_TABLE = {                       # Appendix B, Table 3
    0:  [1.000, 1.000, 1.000, 1.000, 1.000],
    2:  [0.080, 0.042, 0.068, 0.310, 0.249],
    7:  [0.089, 0.047, 0.054, 0.234, 0.272],
    17: [0.099, 0.075, 0.081, 0.272, 0.266],   # manuscript prints 0.267 for LeuZ; deposited is 0.26641
    32: [0.066, 0.041, 0.042, 0.188, 0.222],
}
PAPER_RMSE = {2: 0.108, 7: 0.095, 17: 0.090, 32: 0.077}
PAPER_LINF = {2: 0.134, 7: 0.112, 17: 0.098, 32: 0.091}
PAPER_RANGE = {2: 0.267, 32: 0.181}
PAPER_LOCI_WEIGHTED = (0.065, 0.092)                       # stated as a range across the four times
PAPER_LOSO = {2: (0.107, 0.110), 7: (0.093, 0.096),
              17: (0.087, 0.095), 32: (0.076, 0.079)}


def _rows(name):
    with (OUT / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def floors():
    return {int(r["time_min"]): r for r in _rows("error_floors.csv")}


def test_derived_table_matches_the_manuscript():
    """Every cell of Table 3, to the 3 decimals it is printed at."""
    for r in _rows("table_rg.csv"):
        t = int(r["time_min"])
        got = [round(float(r[g]), 3) for g in GROUPS]
        assert got == PAPER_TABLE[t], f"t={t}: derived {got} != manuscript {PAPER_TABLE[t]}"


def test_error_floors_match_the_manuscript(floors):
    """The RMSE and L-infinity floors, and the two ranges quoted in the text."""
    for t, want in PAPER_RMSE.items():
        assert round(float(floors[t]["rmse_floor"]), 3) == want
    for t, want in PAPER_LINF.items():
        assert round(float(floors[t]["linf_floor"]), 3) == want
    for t, want in PAPER_RANGE.items():
        assert round(float(floors[t]["range"]), 3) == want


def test_both_sensitivity_checks_match(floors):
    """Loci weighting and leave-one-spot-out -- the two checks that corroborate the conclusion."""
    lw = [float(floors[t]["rmse_loci_weighted"]) for t in (2, 7, 17, 32)]
    lo, hi = PAPER_LOCI_WEIGHTED
    assert (round(min(lw), 3), round(max(lw), 3)) == (lo, hi)
    for t, (want_lo, want_hi) in PAPER_LOSO.items():
        got = (round(float(floors[t]["rmse_leave_one_spot_min"]), 3),
               round(float(floors[t]["rmse_leave_one_spot_max"]), 3))
        assert got == (want_lo, want_hi), f"t={t}: LOSO {got} != {(want_lo, want_hi)}"


def test_ordering_holds_under_every_spot_exclusion():
    """LeuX and LeuZ above the other three in EVERY leave-one-spot refit -- 18 spots x 4 times.

    The manuscript makes this claim about the exclusions, not about the pooled table, so checking
    only the pooled table would leave the stated claim untested while looking like it covered it.
    18 spots by 4 post-withdrawal times is 72 comparisons; anything less than 72 is a real failure.
    """
    o = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))["ordering_under_spot_exclusions"]
    assert o["comparisons"] == 72, f"expected 18 spots x 4 times, got {o['comparisons']}"
    assert o["held"] == 72, f"separation inverts in {72 - o['held']} of 72 refits"
    assert o["min_margin"] > 0


def test_six_shared_inequalities_hold_in_both_assays():
    """The array and the blot disagree on magnitude; the ordering is what both support.

    The Northern vector is transcribed from Dittmar et al. rather than derived here, so this checks
    a derived result against a literature constant -- not two constants against each other.
    """
    a = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))["assay_agreement"]
    ineq = a["shared_high_vs_low"]
    pairs = {k: v for k, v in ineq.items() if k != "all_six_hold_in_both"}
    assert len(pairs) == 6, f"expected 2 high x 3 low = 6 inequalities, got {len(pairs)}"
    for name, v in pairs.items():
        assert v["array_all_times"], f"{name} fails in the derived array data"
        assert v["northern"], f"{name} fails in the transcribed Northern vector"
    assert ineq["all_six_hold_in_both"]
    assert "not derived here" in a["northern_source"], "the blot must stay labelled as transcribed"


def test_spot_iqrs_are_reported_and_bracket_the_median():
    """The figure plots technical spot IQRs as whiskers, so they have to exist and be well-formed."""
    for r in _rows("table_rg.csv"):
        if int(r["time_min"]) == 0:
            continue
        for g in GROUPS:
            lo, mid, hi = float(r[f"{g}_iqr_lo"]), float(r[g]), float(r[f"{g}_iqr_hi"])
            assert lo <= mid <= hi, f"t={r['time_min']} {g}: IQR [{lo}, {hi}] does not bracket {mid}"


def test_groups_come_from_the_ecoli_probes_not_the_paper_labels():
    """GPL1746 is multi-species and the paper's group labels collide with its probe names.

    Dittmar et al. call their five E. coli leucine groups Leu-1..Leu-5. On the platform, Leu-1..Leu-5
    are BACILLUS SUBTILIS tRNA-Leu probes; the E. coli ones are Leu-6..Leu-10. Mapping the paper's
    labels onto the deposit by name reads B. subtilis and reports it as E. coli leucine charging --
    silently, with plausible numbers. This pins the GeneID-derived correspondence so that a later
    "fix" aligning the probe names with the manuscript fails loudly instead.
    """
    p2g = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))["probe_to_group"]
    assert p2g == {"Leu-7": "LeuPQVT", "Leu-8": "LeuU", "Leu-10": "LeuW",
                   "Leu-6": "LeuX", "Leu-9": "LeuZ"}, f"probe grouping changed: {p2g}"
    for foreign in ("Leu-1", "Leu-2", "Leu-3", "Leu-4", "Leu-5", "Leu-11", "Leu-14"):
        assert foreign not in p2g, f"{foreign} is not an E. coli probe and must not be grouped"


def test_provenance_is_recorded():
    """The summary must carry the input hash and the probe grouping, or the tables are unfalsifiable."""
    s = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    assert len(s["input_sha256"]) == 64
    assert "ftp.ncbi.nlm.nih.gov" in s["source"]
    assert set(s["spots_per_group"]) == set(GROUPS)
    assert set(s["spots_per_group"].values()) == {18}, "18 technical spots per group is the assay design"


def _online() -> bool:
    try:
        socket.create_connection(("ftp.ncbi.nlm.nih.gov", 443), timeout=5).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _online(), reason="no network: cannot re-fetch the GEO record")
def test_full_chain_from_geo(tmp_path):
    """Re-fetch GSE2065, verify the pinned hash, and rebuild the tables from the raw record."""
    spec = importlib.util.spec_from_file_location("gse", ROOT / "scripts" / "gse2065_reanalysis.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gse"] = mod
    spec.loader.exec_module(mod)

    mod.CACHE = tmp_path / "GSE2065_family.soft.gz"          # force a real download, not the cache
    probe_to_group, by_time = mod.parse(mod.fetch(verify_download=True).decode("utf-8", "replace"))

    assert sorted(set(probe_to_group.values())) == sorted(GROUPS)
    pooled = [p for p, g in probe_to_group.items() if g == "LeuPQVT"]
    assert len(pooled) == 1, "exactly one probe should pool four leucine loci"

    R = mod.ratios(by_time, GROUPS)
    for t, want in PAPER_TABLE.items():
        assert [round(R[t][g], 3) for g in GROUPS] == want, f"t={t} differs when rebuilt from GEO"
