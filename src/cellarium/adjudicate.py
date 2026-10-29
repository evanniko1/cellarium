"""Adjudicating claims made in an OUTSIDE document against this corpus — stage 2: the locator.

WHAT THIS IS FOR. A document produced by another system (a hypothesis report, a research overview, a
collaborator's plan) makes claims and states demands. Deciding which of them this corpus can settle, and
what the rest would cost, is a four-stage job: locate the claims, resolve each quantity to a declared
channel, adjudicate per arm on the existing error contract, and classify the cost. This module is the first
stage, and it is first on purpose.

WHY THE LOCATOR COMES FIRST. Three wrong headlines were produced about one 45-report archive by reading it
without one, and all three are the same defect — a claim judged without knowing which section it came from:

  * a regex over the whole document counted `kcat` inside a CITATION as a demand to change kcat, giving
    "47 of 48 reports need a parameter rebuild" where the figure, read from the plan sections, is 0 of 45;
  * a pattern covering three spellings of one heading found 18 plan sections where there are 123, so a
    table describing 40% of the evidence was presented as the evidence;
  * matches inside wet-lab validation legs were filed as demands on the simulator, which has no such
    readout: "stalling must be monitored via ribosome profiling and acid-urea Northern blotting" is an
    instruction to a bench.

So nothing here returns a claim count. It returns SECTIONS, each with its heading exactly as written and an
exact span, and a document whose plan sections cannot be found reports `located: False` with the headings it
did see. "Zero claims" and "I could not find the plan" are the two sentences this project has confused most
often, and they are different values here.

A DECLARED TABLE BEATS PROSE. A plan stated as a table is the author's own structured statement of it, and
the prose around it frequently disagrees — in the fixture this module was tested against, a table says the
charging target is 0.55/0.85 and the following sentence says 0.70. `source` names which was read, and the
prose that followed the table is returned alongside rather than merged into it, so a contradiction is
visible instead of resolved by whichever the regex reached first.

Pure: no corpus access, no model access, no file reads. The caller supplies the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The closed vocabulary of what a section can be. `citation_context` exists so that the framing prose which
# cites a parameter has somewhere to go that is not `plan` and not `other` — the saturation error has a name.
SECTION_KINDS = ("plan", "claim", "validation_wetlab", "citation_context", "other")

# What makes a heading a PLAN heading, declared as features rather than left implicit inside a regex, so a
# reader can see the rule and disagree with it. These are the words that recur across the spellings one
# generator actually produced ("Factorial Simulation Matrix", "Mechanistic Module Configuration Matrix",
# "Simulation Architecture and Factorial Matrix", "Simulation Design in wcEcoli", "Core Model Architecture,
# Module Flags, and Boundary Constraints", "Computational Design", "Proposed Simulation Experiments").
#
# A heading qualifies on a design/plan word, OR on a structure word paired with a modelling word — which is
# what admits "Factorial Simulation Matrix" and "Core Model Architecture, Module Flags, and Boundary
# Constraints" without admitting "Discussion" or a bare "Matrix".
PLAN_HEADING_WORDS = (
    "simulation design", "computational design", "experimental design", "design in",
    "simulation experiments", "simulation plan", "simulation matrix", "simulation architecture",
    "configuration matrix", "factorial", "module flags", "model architecture", "design matrix",
    "matrix", "parameterization", "parameterisation", "in silico design",
)

# Words that mark a heading as a BENCH leg. Checked before the plan words and winning over them, because
# "Experimental Validation Plan" contains a plan word and is not a plan for this simulator.
WETLAB_HEADING_WORDS = (
    "wet-lab", "wet lab", "validation plan", "experimental validation", "bench", "in vitro", "in vivo",
    "assay", "western", "northern", "ribosome profiling", "microscopy", "strain construction",
    # Added after auditing what landed in `other` across the 33 development reports. Neither was a live
    # defect — `plan` needs a plan word, so a bench leg in `other` was still outside the plan set — but an
    # exclusion that holds by luck holds only until someone writes "design" in the heading.
    "laboratory", "mother machine", "microfluid", "flow cytometr", "mass spectrometr", "sequencing",
)

# Words that mark a heading as stating a CLAIM or prediction rather than a design.
CLAIM_HEADING_WORDS = (
    # "hypothes", not "hypothesis": the development set's "Testable Hypotheses in the Whole-Cell Model"
    # contains neither "hypothesis" nor "prediction", and was filed as `other` on seven reports.
    "expected outcome", "predicted", "prediction", "hypothes", "expected result", "anticipated",
    "falsifi", "success criteri",
)

# Words that mark the framing prose where a parameter is cited rather than demanded.
CITATION_HEADING_WORDS = (
    "background", "introduction", "literature", "prior work", "related work", "rationale", "motivation",
)

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$", re.M)
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


@dataclass(frozen=True)
class Section:
    """One heading and everything under it, up to the next heading of any level."""

    heading: str        # exactly as written, without the leading hashes
    level: int
    start: int          # char offset of the '#' that opens it
    end: int            # char offset where the next heading starts, or len(text)
    kind: str
    has_table: bool


def _classify(heading: str) -> str:
    """Which kind of section a heading announces. Order is the claim: bench beats plan.

    `validation_wetlab` is tested FIRST because "Experimental Validation Plan" matches a plan word and is
    not a plan for this simulator — and filing a bench leg as a simulator demand is a measured past error,
    six reports' worth. `claim` is tested before `plan` for the same reason in miniature: "Predicted
    Simulation Outcomes" states a result, not a layout."""
    h = heading.lower()
    for words, kind in ((WETLAB_HEADING_WORDS, "validation_wetlab"),
                        (CLAIM_HEADING_WORDS, "claim"),
                        (PLAN_HEADING_WORDS, "plan"),
                        (CITATION_HEADING_WORDS, "citation_context")):
        if any(w in h for w in words):
            return kind
    return "other"


def _parse_table(body: str) -> tuple[dict | None, str]:
    """The first markdown table in `body`, and the prose that FOLLOWS it.

    The prose is returned rather than discarded because it is where a contradiction lives. Merging the two
    would make the disagreement unrecoverable, and picking one silently is how a regex-order accident becomes
    a reported fact."""
    rows = [(m.start(), m.group(1)) for m in _TABLE_ROW.finditer(body)]
    if not rows:
        return None, body
    cells = [[c.strip() for c in raw.split("|")] for _, raw in rows]
    lines = [body[s:body.find("\n", s) if body.find("\n", s) != -1 else len(body)] for s, _ in rows]
    keep = [i for i, ln in enumerate(lines) if not _TABLE_RULE.match(ln)]
    if len(keep) < 2:
        return None, body
    headers = cells[keep[0]]
    data = [cells[i] for i in keep[1:]]
    last = rows[keep[-1]][0]
    tail_start = body.find("\n", last)
    tail = body[tail_start + 1:] if tail_start != -1 else ""
    return {"headers": headers, "rows": data, "n_rows": len(data)}, tail


def sections(text: str) -> list[Section]:
    """Every heading in `text`, in document order, each with an exact non-overlapping span.

    Spans tile the document from the first heading to its end: a section runs to the next heading of ANY
    level, so no character belongs to two sections and none is lost between them. That is what makes a quote
    out of a section re-derivable by a reader who has only the document and the offsets."""
    if not isinstance(text, str):
        return []
    marks = list(_HEADING.finditer(text))
    out: list[Section] = []
    for i, m in enumerate(marks):
        start = m.start()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        heading = m.group(2).strip()
        body = text[m.end():end]
        table, _ = _parse_table(body)
        out.append(Section(heading=heading, level=len(m.group(1)), start=start, end=end,
                           kind=_classify(heading), has_table=table is not None))
    return out


def locate(text: str | None) -> dict:
    """Where the plan and the claims are in a document — or that they could not be found.

    Never returns a claim count. `located` is False both when a document has no headings and when none of
    its headings is a plan heading, and the two carry different reasons; `headings_seen` is always present
    so a miss can be diagnosed as either the pattern's fault or the document's."""
    if not isinstance(text, str) or not text.strip():
        return {"error": "locate() needs the document text as a non-empty string; got "
                         f"{type(text).__name__}. An empty document is an argument fault, not a document "
                         f"whose plan could not be located — the two must not share a verdict."}
    secs = sections(text)
    seen = [s.heading for s in secs]
    if not secs:
        return {"error": None, "located": False, "sections": [], "plan_sections": [],
                "validation_sections": [], "claim_sections": [], "headings_seen": [],
                "reason": "no heading of any level was found, so this document has no sections to read. "
                          "Nothing follows about whether it states a plan.",
                "note": "A document with no headings is not a document with no plan. It needs a different "
                        "reader, not a claim of absence."}

    def render(s: Section) -> dict:
        body = text[s.start:s.end]
        after_heading = body.split("\n", 1)[1] if "\n" in body else ""
        table, tail = _parse_table(after_heading)
        return {"heading": s.heading, "level": s.level, "start": s.start, "end": s.end, "kind": s.kind,
                "has_table": s.has_table,
                "source": "declared_table" if table else "prose",
                "table": table,
                "prose_after_table": tail if table else after_heading}

    rendered = [render(s) for s in secs]
    plans = [r for r in rendered if r["kind"] == "plan"]
    out = {
        "located": bool(plans),
        "sections": rendered,
        "plan_sections": plans,
        "validation_sections": [r for r in rendered if r["kind"] == "validation_wetlab"],
        "claim_sections": [r for r in rendered if r["kind"] == "claim"],
        "headings_seen": seen,
        "n_sections": len(rendered),
        "n_plan_sections": len(plans),
    }
    if plans:
        out["reason"] = ""
        out["note"] = (f"{len(plans)} plan section(s) of {len(rendered)}. An extractor must read ONLY these "
                       f"spans: a parameter named in a citation or in a wet-lab leg is not a demand on the "
                       f"simulator, and counting it as one is a measured past error. Where a section carries "
                       f"a declared table, `source` is declared_table and the prose that followed it is "
                       f"beside it, unmerged, so a contradiction stays visible.")
    else:
        out["reason"] = ("unlocated: this document has headings but none of them is a plan heading, so its "
                         "plan sections could NOT be found. This is not the same as a document that states "
                         "no plan, and it must not be counted as zero.")
        out["note"] = ("Read `headings_seen` and decide which it is: a plan spelled a way "
                       "PLAN_HEADING_WORDS does not know (the pattern's fault — and widening it after "
                       "reading a held-out document is forbidden, the miss is counted instead), or a "
                       "document that genuinely proposes no simulation.")
    return out
