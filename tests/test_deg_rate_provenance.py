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


@pytest.fixture(autouse=True)
def _needs_the_model_image():
    """EVERY test here unpickles sim_data, which needs the container — so the guard is autouse, not per-test.

    I wrote this guard into the `_bounds` helper and then twice wrote a test that called the reader DIRECTLY
    and skipped it: it passed alone with WCECOLI_DOCKER set and failed in the full suite without. Patching
    each offender leaves the next one exposed. An autouse fixture makes forgetting impossible, which is the
    same move as classifying identity axes or filtering tombstones inside the read rather than at each caller.
    """
    if not os.environ.get("WCECOLI_DOCKER"):
        pytest.skip("needs the model image to unpickle sim_data")


def _bounds(sim_path="cellarium", **kw):
    """The ONLY way to reach the reader from this file.

    `**kw` exists because the per-unit test used to call `reader.deg_rate_provenance` directly to pass
    `per_unit=True`, which put it back in exactly the hole the autouse fixture above was written to close: the
    fixture guards the WCECOLI_DOCKER axis, `_bounds` guards the "no knowledge base reachable" axis, and a
    direct call has neither. It passed alone and raised KeyError in the full suite as soon as an earlier test
    redirected CELLARIUM_OUT. Taking the keyword here removes the reason to bypass the guard.
    """
    if not Path(f"runs/{sim_path}/kb/simData.cPickle").is_file():
        pytest.skip(f"no knowledge base at runs/{sim_path}")
    r = reader.deg_rate_provenance(sim_path, **kw)
    if "error" in r:
        pytest.skip(r["error"])
    return r


def test_the_report_separates_a_fit_from_a_constraint():
    r = _bounds()
    assert r["n_mrna_units"] > 1000, "this looks like the wrong table — the guard exists so a shape change is loud"
    assert r["on_floor"]["n_units"] >= 1, (
        "no unit sits on the rate floor. Either ParCa stopped bounding the NNLS — in which case this whole "
        "finding is obsolete and the docstring above must be re-read — or the detector is looking at the "
        "wrong array and would report a clean fit for any input")
    assert 0 < r["rate_floor_as_half_life_min"] < 10000
    assert r["rate_ceiling_as_half_life_min"] < r["rate_floor_as_half_life_min"]


def test_it_reports_expression_not_just_a_count():
    """A count says how many units; only expression says whether it MATTERS. 245 obscure units and 245 that
    carry 5% of transcription are different findings, and the count alone cannot tell them apart."""
    r = _bounds()
    assert r["not_a_fit"]["pct_expression"] > 0
    assert r["most_expressed_not_a_fit"], "the report names no unit, so a reader cannot check any of it"
    for e in r["most_expressed_not_a_fit"]:
        assert e["id"] and e["pct_of_mrna_expression"] >= 0


def test_the_ribosomal_operons_are_on_the_bound():
    """The specific exposure, asserted because it is what makes this a live risk rather than a curiosity.

    The corpus's headline results are about ppGpp, ribosomes and the stringent response, and the two
    most-expressed bound-pinned units are ribosomal protein operons. If a future fit moves them OFF the bound
    that is a real improvement and this test should be re-read, not deleted.
    """
    r = _bounds()
    ids = " ".join(e["id"] for e in r["most_expressed_not_a_fit"]).lower()
    assert "rpm" in ids or "rpl" in ids or "rps" in ids, (
        "no ribosomal protein operon is among the most-expressed bound-pinned units any more: %s" % ids)


def test_the_coverage_filter_moves_the_bound_without_emptying_it():
    """The measured refutation of the obvious fix. Skipped unless the refit2 knowledge base is present."""
    base = _bounds("cellarium")
    filt = _bounds("refit2")
    assert filt["rate_floor_as_half_life_min"] < base["rate_floor_as_half_life_min"], (
        "the coverage filter did not move the bound at all — re-check that the filtered rna_half_lives.tsv "
        "was actually mounted for the rebuild")
    assert filt["on_floor"]["n_units"] >= base["on_floor"]["n_units"], (
        "the number of units pinned to the bound FELL, which would contradict the recorded finding that "
        "min() simply promotes the next-slowest measurement — re-read PARCA-4 before trusting this")
    assert filt["not_a_fit"]["pct_expression"] > base["not_a_fit"]["pct_expression"], (
        "the share of expression that is NOT a fit did not rise; the recorded 12.09%% -> 15.38%% is the "
        "reason the coverage filter was declined")


def test_the_imputed_class_is_reported_and_is_the_larger_one():
    """THE reason this was extended. `deg_rate_bounds` asked "which units sit on a bound" and answered 245
    units / 4.59% of expression — reassuringly, and about a third of the truth.

    A unit whose cistrons were never measured does not sit on a bound at all: it is assigned
    `average_mRNA_cistron_half_life`, the MEAN of the reported half-lives (`transcription.py:339`). That class
    is BIGGER than the bound class, so a report that omits it understates the exposure by ~3x while looking
    complete.
    """
    r = _bounds()
    imp, floor = r["imputed_average"], r["on_floor"]
    assert imp["n_units"] > 0, (
        "no unit carries the imputation constant. Either ParCa stopped defaulting unmeasured cistrons to the "
        "population mean — in which case this finding is obsolete — or the detector is not reading "
        "`average_mRNA_cistron_half_life` and would report a clean table for any input")
    assert imp["pct_expression"] > floor["pct_expression"], (
        "the imputed class is no longer the larger one (%.3f%% vs %.3f%% on the bound). That may be a real "
        "improvement, but the recorded finding — that reporting bounds alone understates by ~3x — must be "
        "re-read rather than left standing"
        % (imp["pct_expression"], floor["pct_expression"]))
    assert r["not_a_fit"]["pct_expression"] >= imp["pct_expression"] + floor["pct_expression"] - 1e-6


def test_the_imputation_constant_is_read_from_sim_data_not_hardcoded():
    """It changes when the fit changes — measured: 5.1907 min on the corpus fit, 5.3418 on refit2, because
    filtering the input moved the mean. A hardcoded value would silently stop matching and report zero."""
    r = _bounds()
    assert 0 < r["imputation_constant_min"] < 1000
    other = _bounds("refit2")
    assert other["imputation_constant_min"] != r["imputation_constant_min"], (
        "the imputation constant is identical across two different fits, which suggests it is not being read "
        "from each knowledge base")


def test_rounding_collisions_are_not_counted_as_defects():
    """The flat file stores half-lives to ONE decimal (`ROUND_N_DECIMALS = 1`), so ~40 units legitimately
    share 1.5 min. Those are measured values, verified present verbatim in rna_half_lives.tsv — a naive
    'point mass' detector flags them and reports the table as far worse than it is."""
    r = _bounds()
    res = r["resolution"]
    assert res["distinct_half_lives"] < r["n_mrna_units"], "expected repeated values; the input is rounded"
    assert "not a defect measure" in res["caveat"].lower()
    # the three named classes are the claim; resolution is context and must not be summed into them
    named = r["on_floor"]["n_units"] + r["on_ceiling"]["n_units"] + r["imputed_average"]["n_units"]
    assert r["not_a_fit"]["n_units"] == named, (
        "not_a_fit must be exactly the three structural classes, not everything that repeats")


def test_the_per_unit_array_is_opt_in_and_complete():
    """Aggregate counts cannot SCORE a candidate estimator; identities can."""
    default = _bounds()
    assert "units_not_a_fit" not in default, (
        "the id list is in the DEFAULT payload — the summary is what a human reads, and 854 ids inside it is "
        "not a summary")
    r = _bounds("cellarium", per_unit=True)
    u = r["units_not_a_fit"]
    for cls in ("floor", "ceiling", "imputed"):
        assert len(u[cls]) == r["on_floor" if cls == "floor" else
                                "on_ceiling" if cls == "ceiling" else "imputed_average"]["n_units"], cls
    total = sum(len(u[c]) for c in ("floor", "ceiling", "imputed"))
    assert total == r["not_a_fit"]["n_units"], "the listed ids do not add up to the reported not-a-fit count"
    assert u["determined_is_the_complement"] == r["n_mrna_units"] - total
    assert not (set(u["floor"]) & set(u["imputed"])), "a unit is in two classes at once"


def test_the_per_unit_entries_carry_expression_weights():
    """Ids alone count UNITS; the acceptance criteria are written in EXPRESSION.

    Measured, the coverage filter regresses 45 units and 3.3007% of mRNA expression while rescuing 1 unit
    worth 0.0037% — roughly 900:1 by mass against 45:1 by count. From ids alone you cannot tell those apart.
    """
    r = _bounds("cellarium", per_unit=True)
    u = r["units_not_a_fit"]
    for cls in ("floor", "ceiling", "imputed"):
        assert isinstance(u[cls], dict), f"{cls} is a bare list — the weights are gone"
        for uid, pct in u[cls].items():
            assert isinstance(uid, str) and isinstance(pct, (int, float)) and pct >= 0
    mass = sum(sum(u[c].values()) for c in ("floor", "ceiling", "imputed"))
    assert abs(mass - r["not_a_fit"]["pct_expression"]) < 0.05, (
        "per-unit weights (%.3f%%) do not add up to the reported class mass (%.3f%%)"
        % (mass, r["not_a_fit"]["pct_expression"]))


def test_two_fits_can_be_scored_against_each_other():
    """THE reason the array exists — and on its first use it settled the coverage-filter question sharply.

    Aggregate mass said the filter costs 12.087% -> 15.382% of expression. Per unit it says: 1 unit rescued,
    45 regressed. A ratio like that is not visible in a total, and it is the shape Stage 3 has to measure for
    every candidate estimator.
    """
    # BOTH guards, not just the file. Unpickling sim_data needs the model image, so checking only that the kb
    # exists let this run in an environment where it cannot work — it passed alone with WCECOLI_DOCKER set and
    # failed in the full suite without it. `_bounds` already guards both; this test called the reader directly
    # and skipped that.
    _bounds("cellarium")
    if not Path("runs/refit2/kb/simData.cPickle").is_file():
        pytest.skip("refit2 knowledge base not present")
    a = _bounds("cellarium", per_unit=True)["units_not_a_fit"]
    b = _bounds("refit2", per_unit=True)["units_not_a_fit"]
    A = set(a["floor"]) | set(a["ceiling"]) | set(a["imputed"])
    B = set(b["floor"]) | set(b["ceiling"]) | set(b["imputed"])
    assert A and B, "an empty class set makes the comparison below vacuous"
    rescued, regressed = A - B, B - A
    assert len(regressed) > len(rescued), (
        "the coverage filter now rescues more units than it regresses (%d vs %d). That would be a real "
        "improvement and the DECLINE decision in the backlog must be re-read, not left standing"
        % (len(rescued), len(regressed)))


def test_provenance_delta_is_one_function_not_a_pattern():
    """Stage 3 scores every candidate estimator with this question, so it lives in ONE place.

    Two hand-rolled set intersections that differ by a class — forgetting `ceiling`, say — would score two
    candidates under different rules with nothing saying so. It reports counts AND expression because they
    disagree: on the declined coverage filter, 45:1 by unit and ~900:1 by mass.
    """
    _bounds("cellarium")
    if not Path("runs/refit2/kb/simData.cPickle").is_file():
        pytest.skip("refit2 knowledge base not present")
    d = reader.provenance_delta("cellarium", "refit2")
    assert "error" not in d, d
    assert d["rescued"]["n"] + d["not_a_fit_in_both"]["n"] == d["totals"]["not_a_fit_a"]
    assert d["regressed"]["n"] + d["not_a_fit_in_both"]["n"] == d["totals"]["not_a_fit_b"]
    # both views must be present, or a caller will quote whichever suits
    assert d["rescued"]["pct_expression_in_a"] >= 0 and d["regressed"]["pct_expression_in_b"] >= 0
    assert d["regressed"]["pct_expression_in_b"] > d["rescued"]["pct_expression_in_a"], (
        "the coverage filter now rescues more transcription than it regresses — that would be a real "
        "improvement and the DECLINE decision must be re-read, not left standing")
    assert "MORE units" in d["verdict"]


def test_a_fit_scored_against_itself_is_a_no_op():
    """The guard against a delta that reports change where there is none."""
    _bounds("cellarium")
    d = reader.provenance_delta("cellarium", "cellarium")
    assert d["rescued"]["n"] == 0 and d["regressed"]["n"] == 0
    assert d["totals"]["net_units"] == 0 and abs(d["totals"]["net_pct_expression"]) < 1e-9
