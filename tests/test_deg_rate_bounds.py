"""A degradation rate on the BOUND is not a fitted value, and sim_data cannot tell you which is which (PARCA-4).

ParCa infers a half-life for every transcription unit it cannot measure, by NNLS from per-gene measurements,
under a lower bound on the rate set to the slowest single measured mRNA cistron:

    min_deg_rates[is_mRNA] = mRNA_cistron_deg_rates.min()

A unit whose solution hits that wall stops there, and what is reported for it is the wall's value. On disk the
two are the same float in the same array. MEASURED on the corpus fit: 245 of 3,133 mRNA units sit bit-exactly
on it, carrying 4.59% of mRNA expression, and the two most-expressed are RIBOSOMAL PROTEIN operons — the
transcripts a ppGpp or stringent-response result leans on hardest.

WHY THIS IS A DIAGNOSTIC AND NOT AN ASSERTION. 245 units on the bound is the state of every knowledge base in
the corpus, so a test that failed on it would fail every build and be switched off within a week. A number
that travels with the fit is something a reader can weigh; a red suite nobody can green is not.

WHAT THE COVERAGE FILTER DOES AND DOES NOT FIX. The obvious repair is to stop a single-fragment measurement
setting the bound — `shoB` has one fragment and StdDev 0, and supplies 91.2 min. Applied as a pre-registered
cut (`total fragments >= 2`, the minimum n for a standard deviation to exist) and rebuilt as `refit2`, it
lands the bound on `ompA` at 32.4 min, matching what deleting shoB outright produced. It improves the bound's
PROVENANCE and does not fix the defect:

    cellarium  floor 91.2 min   245 pinned (7.8%)   4.59% of mRNA expression
    refit1     floor 32.4 min   247 pinned (7.9%)   6.57%   (shoB retyped away)
    refit2     floor 32.4 min   247 pinned (7.9%)   6.57%   (coverage filter)

Two unrelated perturbations converge on the same state, the count does not fall, and the share of expression
resting on a placeholder RISES. `min()` does not care which value is minimal; remove the one supplying it and
the next is promoted. The ribosomal operons stay pinned in all three.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import reader  # noqa: E402


def _bounds(sim_path="cellarium"):
    if not os.environ.get("WCECOLI_DOCKER"):
        pytest.skip("needs the model image to unpickle sim_data")
    if not Path(f"runs/{sim_path}/kb/simData.cPickle").is_file():
        pytest.skip(f"no knowledge base at runs/{sim_path}")
    r = reader.deg_rate_bounds(sim_path)
    if "error" in r:
        pytest.skip(r["error"])
    return r


def test_the_report_separates_a_fit_from_a_constraint():
    r = _bounds()
    assert r["n_mrna_units"] > 1000, "this looks like the wrong table — the guard exists so a shape change is loud"
    assert r["n_on_floor"] >= 1, (
        "no unit sits on the rate floor. Either ParCa stopped bounding the NNLS — in which case this whole "
        "finding is obsolete and the docstring above must be re-read — or the detector is looking at the "
        "wrong array and would report a clean fit for any input")
    assert 0 < r["rate_floor_as_half_life_min"] < 10000
    assert r["rate_ceiling_as_half_life_min"] < r["rate_floor_as_half_life_min"]


def test_it_reports_expression_not_just_a_count():
    """A count says how many units; only expression says whether it MATTERS. 245 obscure units and 245 that
    carry 5% of transcription are different findings, and the count alone cannot tell them apart."""
    r = _bounds()
    assert r["pct_expression_on_floor"] > 0
    assert r["most_expressed_on_floor"], "the report names no unit, so a reader cannot check any of it"
    for e in r["most_expressed_on_floor"]:
        assert e["id"] and e["pct_of_mrna_expression"] >= 0


def test_the_ribosomal_operons_are_on_the_bound():
    """The specific exposure, asserted because it is what makes this a live risk rather than a curiosity.

    The corpus's headline results are about ppGpp, ribosomes and the stringent response, and the two
    most-expressed bound-pinned units are ribosomal protein operons. If a future fit moves them OFF the bound
    that is a real improvement and this test should be re-read, not deleted.
    """
    r = _bounds()
    ids = " ".join(e["id"] for e in r["most_expressed_on_floor"]).lower()
    assert "rpm" in ids or "rpl" in ids or "rps" in ids, (
        "no ribosomal protein operon is among the most-expressed bound-pinned units any more: %s" % ids)


def test_the_coverage_filter_moves_the_bound_without_emptying_it():
    """The measured refutation of the obvious fix. Skipped unless the refit2 knowledge base is present."""
    base = _bounds("cellarium")
    filt = _bounds("refit2")
    assert filt["rate_floor_as_half_life_min"] < base["rate_floor_as_half_life_min"], (
        "the coverage filter did not move the bound at all — re-check that the filtered rna_half_lives.tsv "
        "was actually mounted for the rebuild")
    assert filt["n_on_floor"] >= base["n_on_floor"], (
        "the number of units pinned to the bound FELL, which would contradict the recorded finding that "
        "min() simply promotes the next-slowest measurement — re-read PARCA-4 before trusting this")
    assert filt["pct_expression_on_floor"] > base["pct_expression_on_floor"], (
        "the share of expression resting on a placeholder did not rise; the recorded 4.59%% -> 6.57%% is the "
        "reason the filter is necessary-but-not-sufficient")
