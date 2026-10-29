"""Stage 2 of the claim adjudicator: find WHERE the claims are before reading any.

This is built first, and deliberately before the quantity registry, because it is the fix for all three
errors that produced a wrong headline about an outside document:

  * a regex over the whole document counted the word `kcat` inside a CITATION as a demand to change kcat,
    which is how "47 of 48 reports need a parameter rebuild" happened when the real figure is 0 of 45;
  * a pattern matching three spellings of one heading found 18 plan sections where there are 123 across 45
    reports, so a table describing 40% of the evidence was presented as the evidence;
  * matches inside WET-LAB validation legs ("stalling must be monitored via ribosome profiling and acid-urea
    Northern blotting") were filed as demands on the simulator, which has no such readout and never could.

All three are the same defect: a claim judged without knowing which section it came from. So every section
this module returns carries its heading as written and an exact span, and a document whose plan sections
cannot be found reports `located: False` rather than zero claims. Zero claims and "I could not find the
plan" are the two sentences this project has confused most often.

Every fixture here is synthetic. The real archive is local-only and is not a test dependency; the heading
spellings below are written in as DATA so this file states what it believes the shapes are, and a local
script runs the finished tool over the archive itself.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import adjudicate  # noqa: E402

# The heading spellings this module claims to recognise, written out rather than left implicit in a regex.
PLAN_HEADINGS = [
    "## Factorial Simulation Matrix",
    "### Mechanistic Module Configuration Matrix",
    "## Simulation Architecture and Factorial Matrix",
    "# Simulation Design in wcEcoli",
    "## Whole-Cell Modeling Simulation Design",
    "## Core Model Architecture, Module Flags, and Boundary Constraints",
    "## Proposed Simulation Experiments",
    "#### Computational Design",
]

REPORT = """# An idea about synthetase levels

Some framing prose that mentions kcat because Choi & Covert fitted the kcat values, which is a citation
and not a demand.

## Factorial Simulation Matrix

| Factor | Levels |
| --- | --- |
| ppGpp module | on, off |
| AA supply module | medium-clamped, enzyme-aware |
| Target charging | 0.55, 0.85 |

The prose here says the target charging is 0.70, which contradicts the table above.

## Experimental Validation Plan

Wet-lab translation stalling must be monitored via ribosome profiling and acid-urea Northern blotting.

## Expected Outcomes

Growth rate should fall by at least 20% in the knockout arm.
"""


# --- sections ----------------------------------------------------------------------------------------

def test_every_heading_level_is_found_and_the_heading_is_returned_as_written():
    secs = adjudicate.sections(REPORT)
    headings = [s.heading for s in secs]
    assert "An idea about synthetase levels" in headings
    assert "Factorial Simulation Matrix" in headings
    assert "Experimental Validation Plan" in headings
    # Levels are kept, because a level-4 heading is a subsection of a plan and not a document of its own.
    assert {s.level for s in secs} == {1, 2}


def test_a_span_is_exact_and_sections_do_not_overlap():
    secs = adjudicate.sections(REPORT)
    for s in secs:
        assert REPORT[s.start:s.end].lstrip("#").strip().startswith(s.heading)
    for a, b in zip(secs, secs[1:]):
        assert a.end == b.start, (a.heading, b.heading)
    assert secs[-1].end == len(REPORT)


@pytest.mark.parametrize("heading", PLAN_HEADINGS)
def test_each_declared_plan_spelling_is_recognised(heading):
    doc = f"# Title\n\nprose\n\n{heading}\n\nsome plan body\n"
    out = adjudicate.locate(doc)
    assert out["located"] is True, heading
    assert [s["heading"] for s in out["plan_sections"]] == [heading.lstrip("#").strip()]


def test_a_wet_lab_validation_section_is_classified_as_not_a_simulation():
    out = adjudicate.locate(REPORT)
    kinds = {s["heading"]: s["kind"] for s in out["sections"]}
    assert kinds["Experimental Validation Plan"] == "validation_wetlab"
    assert kinds["Factorial Simulation Matrix"] == "plan"
    # And it is kept OUT of the plan set, which is the half that matters: its contents are demands on a
    # bench, not on the simulator, and counting them as the latter is a measured past error.
    assert "Experimental Validation Plan" not in [s["heading"] for s in out["plan_sections"]]
    assert "Experimental Validation Plan" in [s["heading"] for s in out["validation_sections"]]


def test_a_declared_table_is_preferred_and_the_tool_says_which_it_read():
    out = adjudicate.locate(REPORT)
    plan = out["plan_sections"][0]
    assert plan["has_table"] is True and plan["source"] == "declared_table"
    assert plan["table"]["headers"] == ["Factor", "Levels"]
    assert ["ppGpp module", "on, off"] in plan["table"]["rows"]
    # The contradicting prose is still available, flagged, never silently merged with the table.
    assert plan["prose_after_table"].strip().startswith("The prose here says")


def test_a_plan_section_with_no_table_reads_prose_and_says_so():
    doc = "# T\n\n## Proposed Simulation Experiments\n\nRun the knockout at three seeds.\n"
    plan = adjudicate.locate(doc)["plan_sections"][0]
    assert plan["has_table"] is False and plan["source"] == "prose"


# --- the absent branch, which is the whole point -----------------------------------------------------

def test_a_document_with_no_plan_section_is_unlocated_not_empty():
    doc = "# An idea\n\n## Background\n\nSome reading of the literature.\n\n## Discussion\n\nMore prose.\n"
    out = adjudicate.locate(doc)
    assert out["located"] is False
    assert out["plan_sections"] == []
    assert "unlocated" in out["reason"] or "no plan" in out["reason"].lower()
    # The distinction this module exists for: never a count that reads as a finding.
    assert "n_claims" not in out


def test_a_document_with_no_headings_at_all_is_unlocated_with_a_different_reason():
    out = adjudicate.locate("Just prose about a factorial simulation matrix, with no headings anywhere.\n")
    assert out["located"] is False and out["sections"] == []
    assert "no heading" in out["reason"].lower()


def test_empty_input_is_an_argument_error_not_an_unlocated_document():
    for bad in ("", "   \n\n", None):
        out = adjudicate.locate(bad)
        assert "error" in out, bad


# --- forcing the instrument to fail ------------------------------------------------------------------

def test_a_mis_spelled_plan_heading_is_reported_as_unlocated_rather_than_silently_skipped():
    """The exact defect that produced the 18-of-48 undercount. A heading the pattern does not know must make
    the document UNLOCATED, so the miss is loud, instead of leaving a document that quietly contributes no
    plan sections to a total."""
    doc = "# T\n\n## Simulation Blueprint Grid\n\n| A | B |\n| - | - |\n| 1 | 2 |\n"
    out = adjudicate.locate(doc)
    assert out["located"] is False
    # And it must name what it saw, so a human can decide whether the pattern or the document is wrong.
    assert "Simulation Blueprint Grid" in out["headings_seen"]


def test_a_citation_mentioning_a_parameter_is_not_a_plan_section():
    """The saturation error: `kcat` appears in the framing prose as a citation. Outside a plan section it
    must not be reachable by the extractor at all."""
    out = adjudicate.locate(REPORT)
    plan_text = "".join(REPORT[s["start"]:s["end"]] for s in out["plan_sections"])
    assert "kcat" not in plan_text
    assert "kcat" in REPORT                                  # it is in the document, just not in the plan


def test_locating_is_deterministic_and_order_preserving():
    a, b = adjudicate.locate(REPORT), adjudicate.locate(REPORT)
    assert a == b
    offs = [s["start"] for s in a["sections"]]
    assert offs == sorted(offs)


# --- the declared vocabulary --------------------------------------------------------------------------

def test_the_section_kinds_are_a_closed_set_and_every_one_is_reachable():
    doc = REPORT + "\n## Background\n\nprose\n"
    kinds = {s["kind"] for s in adjudicate.locate(doc)["sections"]}
    assert kinds <= set(adjudicate.SECTION_KINDS)
    assert {"plan", "validation_wetlab", "other"} <= kinds


def test_the_heading_features_are_declared_rather_than_a_bare_regex():
    """A reader must be able to see what makes a heading a plan heading, and disagree with it."""
    assert adjudicate.PLAN_HEADING_WORDS and adjudicate.WETLAB_HEADING_WORDS
    assert "matrix" in adjudicate.PLAN_HEADING_WORDS
    assert not (set(adjudicate.PLAN_HEADING_WORDS) & set(adjudicate.WETLAB_HEADING_WORDS))


# --- widenings the DEVELOPMENT set forced, each one recorded with the heading that forced it ----------
#
# Found by auditing what landed in `other` over the 33 development reports, which is what a development set
# is for. None of these was a live defect — a bench leg in `other` is still outside `plan_sections`, because
# `plan` needs a plan word — but the whole point of the kind field is that an exclusion is STATED rather
# than accidental. A section excluded by luck is excluded until someone adds a plan word to its heading.
#
# The held-out twelve are untouched, and a heading they spell differently will be COUNTED as a miss rather
# than added here.

@pytest.mark.parametrize("heading,kind", [
    # 16 reports: a bench leg whose heading has no "validation plan" in it.
    ("## Downstream Laboratory Validation Experiment", "validation_wetlab"),
    # 8 reports: microfluidic single-cell work, named by the device.
    ("## 2. Single-Cell Lineage Tracking in Mother Machine Devices", "validation_wetlab"),
    # 7 reports: a claim section. "hypothesis" does not occur in "Hypotheses", which is how it was missed.
    ("## 2. Testable Hypotheses in the Whole-Cell Model", "claim"),
])
def test_headings_the_development_set_showed_were_misfiled(heading, kind):
    doc = f"# T\n\n{heading}\n\nbody\n"
    assert adjudicate.locate(doc)["sections"][1]["kind"] == kind


def test_the_report_envelope_stays_other():
    """The stable wrapper every report in that archive carries. These are correctly NOT plan sections, and a
    widening that swallowed them would be worse than the misses above."""
    for h in ("## Abstract", "## Critical Flaws", "## Executive Verdict", "## Conclusion", "## References",
              "## Attributes", "## Goal Alignment & Novelty", "## Fragility Assessment"):
        doc = f"# T\n\n{h}\n\nbody\n"
        assert adjudicate.locate(doc)["sections"][1]["kind"] == "other", h


def test_an_ambiguous_heading_is_left_in_other_rather_than_guessed():
    """`Protocol Architecture` could be a simulation protocol or a bench protocol; the archive does not say
    in its heading. It stays `other`, because a wrong confident class is worse than an honest unknown, and
    `other` is reported with its heading so a human can look."""
    out = adjudicate.locate("# T\n\n## Protocol Architecture\n\nbody\n")
    assert out["sections"][1]["kind"] == "other"
    assert out["located"] is False and "Protocol Architecture" in out["headings_seen"]
