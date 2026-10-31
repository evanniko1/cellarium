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
    """One heading, its own body, and the span of its whole subtree.

    TWO spans, because a markdown heading plays two roles and conflating them loses content. `start:end` is
    the heading's OWN body — up to the next heading of any level. `start:subtree_end` additionally covers
    every deeper heading beneath it, up to the next heading at this level or shallower.

    A CONTAINER heading has an empty own body and a non-empty subtree: its content lives in its children.
    Measured on the 33 development reports, 154 of 1,287 sections (12.0%) are in that state, 82 of them
    `claim` sections and 2 `plan`. Reading only the own body of those would report a plan that specified
    nothing and a prediction that predicted nothing — the silent-absence shape, inside the module written to
    end it. `is_container` separates "its content is elsewhere in this document" from "it says nothing",
    which are not the same fact."""

    heading: str        # exactly as written, without the leading hashes
    level: int
    start: int          # char offset of the '#' that opens it
    end: int            # where the next heading of ANY level starts, or len(text) — its own body
    subtree_end: int    # where the next heading of level <= this one starts, or len(text) — its subtree
    kind: str
    kind_basis: str     # "heading_words" | "inherited" | "default" — how `kind` was decided
    parent: int | None  # index of the nearest shallower heading, or None
    has_table: bool     # in its OWN body
    is_container: bool  # own body empty, subtree not


def _classify(heading: str) -> str | None:
    """Which kind of section a heading's OWN WORDS announce, or None when they announce nothing.

    Order is the claim: bench beats plan. `validation_wetlab` is tested FIRST because "Experimental
    Validation Plan" matches a plan word and is not a plan for this simulator — and filing a bench leg as a
    simulator demand is a measured past error, six reports' worth. `claim` is tested before `plan` for the
    same reason in miniature: "Predicted Simulation Outcomes" states a result, not a layout.

    None rather than "other", so the caller can tell "this heading says it is miscellaneous" from "this
    heading says nothing, ask its parent". Only the second is eligible for inheritance."""
    h = heading.lower()
    for words, kind in ((WETLAB_HEADING_WORDS, "validation_wetlab"),
                        (CLAIM_HEADING_WORDS, "claim"),
                        (PLAN_HEADING_WORDS, "plan"),
                        (CITATION_HEADING_WORDS, "citation_context")):
        if any(w in h for w in words):
            return kind
    return None


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
    levels = [len(m.group(1)) for m in marks]
    out: list[Section] = []
    for i, m in enumerate(marks):
        start = m.start()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        # The subtree runs to the next heading at this level or SHALLOWER; everything between is beneath it.
        nxt = next((j for j in range(i + 1, len(marks)) if levels[j] <= levels[i]), None)
        subtree_end = marks[nxt].start() if nxt is not None else len(text)
        # The nearest preceding heading that is shallower than this one.
        parent = next((j for j in range(i - 1, -1, -1) if levels[j] < levels[i]), None)
        heading = m.group(2).strip()
        body = text[m.end():end]
        table, _ = _parse_table(body)
        own = _classify(heading)
        if own is not None:
            kind, basis = own, "heading_words"
        elif parent is not None and out[parent].kind != "other":
            # INHERITANCE, and only in this direction. An uninformative heading takes its parent's kind, so
            # `Protocol Architecture` under a bench parent is bench and `Step One` under a plan is plan. An
            # informative heading never takes its parent's: that would file a nested assay as a simulator
            # demand through its container, which is the error this field exists to prevent.
            kind, basis = out[parent].kind, "inherited"
        else:
            kind, basis = "other", "default"
        out.append(Section(heading=heading, level=levels[i], start=start, end=end, subtree_end=subtree_end,
                           kind=kind, kind_basis=basis, parent=parent, has_table=table is not None,
                           is_container=(not body.strip()) and subtree_end > end))
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

    def render(i: int, s: Section) -> dict:
        body = text[s.start:s.end]
        after_heading = body.split("\n", 1)[1] if "\n" in body else ""
        table, tail = _parse_table(after_heading)
        # A container's own body is empty, so a table may live in a CHILD. Look in the subtree too, and say
        # where it was found, because "this plan declares a table" and "a child of this plan declares one"
        # license the same extraction but not the same sentence about the document.
        sub_table = table
        if table is None and s.is_container:
            sub_table, _ = _parse_table(text[s.end:s.subtree_end])
        descendants = [t for j, t in enumerate(secs) if s.start < t.start < s.subtree_end]
        return {
            "heading": s.heading, "level": s.level, "start": s.start, "end": s.end,
            "subtree_end": s.subtree_end, "kind": s.kind, "kind_basis": s.kind_basis,
            "parent_heading": secs[s.parent].heading if s.parent is not None else None,
            "has_table": s.has_table, "is_container": s.is_container,
            # What an extractor must read. For a container this is WIDER than the own body, which is the
            # whole point: reading `start:end` of a plan container reads nothing.
            "read_span": [s.start, s.subtree_end],
            "source": "declared_table" if table else ("declared_table_in_child" if sub_table else "prose"),
            "table": sub_table,
            "prose_after_table": tail if table else after_heading,
            # Descendants whose own words put them in a different kind — a bench step nested inside a plan.
            # The subtree span includes their text, so an extractor reading the span must subtract them, and
            # cannot do that unless it is told which they are.
            "excluded_descendants": [t.heading for t in descendants if t.kind != s.kind],
        }

    rendered = [render(i, s) for i, s in enumerate(secs)]
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
        "n_containers": sum(1 for r in rendered if r["is_container"]),
        "n_inherited_kinds": sum(1 for r in rendered if r["kind_basis"] == "inherited"),
    }
    if plans:
        out["reason"] = ""
        out["note"] = (f"{len(plans)} plan section(s) of {len(rendered)}, of which "
                       f"{sum(1 for p in plans if p['is_container'])} are CONTAINERS whose own body is "
                       f"empty. An extractor must read `read_span` (the subtree), not start:end — reading "
                       f"the own body of a container reads nothing and would report a plan that specified "
                       f"nothing. It must also read ONLY plan spans and subtract `excluded_descendants`: a "
                       f"parameter named in a citation or a wet-lab leg is not a demand on the simulator, "
                       f"and counting it as one is a measured past error. Where a section carries a declared "
                       f"table, `source` says whether it was in that section or in a child, and the prose "
                       f"that followed it sits beside it unmerged so a contradiction stays visible.")
    else:
        out["reason"] = ("unlocated: this document has headings but none of them is a plan heading, so its "
                         "plan sections could NOT be found. This is not the same as a document that states "
                         "no plan, and it must not be counted as zero.")
        out["note"] = ("Read `headings_seen` and decide which it is: a plan spelled a way "
                       "PLAN_HEADING_WORDS does not know (the pattern's fault — and widening it after "
                       "reading a held-out document is forbidden, the miss is counted instead), or a "
                       "document that genuinely proposes no simulation.")
    return out


# --- stage 1: which quantity a claim names, and whether this corpus records it ------------------------
#
# The MEASURABLE half is derived from `instrument.CHANNELS`, the one declared channel namespace -- the same
# list the tool schemas take their `channel` enums from -- so a channel added there becomes adjudicable with
# no edit here.
#
# The VOCABULARY half is hand-written, and saying so is the point. Deriving a namespace does not derive a
# vocabulary: "does ppGpp rise on starvation" has to be connected to `ppgpp_conc` by somebody, and calling
# that derived would move the hand-typing one layer down and dress it as automatic. So it is declared here,
# `quantity_coverage()` reports which channels have no words at all, and a test fails on an entry pointing
# at a channel that does not exist -- a dead entry can never fire, and its silence reads as the document not
# having mentioned the quantity.
#
# THREE VALUES, NOT TWO, and this is the whole reason the stage exists separately. `recorded` means a
# channel carries it. `not_recorded` means the quantity is a real thing this corpus has no channel for, and
# that IS evidence -- about coverage, which is why it carries `about: corpus`. `unresolved` means nothing
# matched, so the registry has no opinion, and that is a statement about the REQUEST. Collapsing the last
# two is how "the model cannot do this" gets reported about a quantity nobody ever mapped.

CHANNEL_VOCABULARY: dict[str, tuple[str, ...]] = {
    "growth_rate": ("growth rate", "growth-rate", "doubling time", "specific growth", "growth defect"),
    "ppgpp_conc": ("ppgpp", "alarmone", "stringent response"),
    "ribosome_conc": ("ribosome concentration", "ribosome content", "ribosome abundance"),
    "fraction_trna_charged": ("charged fraction", "fraction charged", "charging level", "aminoacylation",
                              "charged trna", "trna charging"),
    "rela_conc": ("rela level", "rela concentration", "rela abundance", "rela"),
    "dry_mass": ("dry mass", "dry weight", "cell mass"),
    "protein_mass": ("protein mass", "total protein", "proteome mass"),
    "rna_mass": ("rna mass", "total rna", "rna content"),
    "division_rate": ("division rate", "division time", "cell cycle time"),
    "fba_objective": ("flux balance objective", "fba objective", "homeostatic objective"),
}

# Quantities a document may genuinely name that this corpus records NO channel for. Declared POSITIVELY
# rather than left to fall through, because "we have no channel for polysome occupancy" is a fact about our
# coverage and "nothing in the table matched these words" is not. Six reports were once filed as needing a
# model-code change on the strength of these words appearing; they are bench readouts.
NOT_RECORDED_QUANTITIES: tuple[str, ...] = (
    "ribosome profiling", "polysome", "pause", "stalling", "ribosome occupancy", "a-site",
    "northern blot", "acid-urea", "footprint", "codon occupancy",
    "mass spectrometry", "metabolomics", "proteomics",
)


def channels() -> dict:
    """The declared channel namespace, as the registry sees it. Derived, never restated."""
    from . import instrument
    return dict(instrument.CHANNELS)


def _hits(phrase: str) -> list[dict]:
    """Every vocabulary match in `phrase`, longest first so a longer phrase never loses to a substring."""
    low = phrase.lower()
    out: list[dict] = []
    for channel, words in CHANNEL_VOCABULARY.items():
        for w in words:
            if w in low:
                out.append({"status": "recorded", "channel": channel, "matched": w})
    for q in NOT_RECORDED_QUANTITIES:
        if q in low:
            out.append({"status": "not_recorded", "channel": None, "matched": q})
    out.sort(key=lambda h: (-len(h["matched"]), h["matched"]))
    # A shorter match wholly inside a longer one is the same mention, not a second quantity: "rela" inside
    # "rela level", "pause" inside "elongation pause duration". Dropping it is what keeps `ambiguous`
    # meaning two QUANTITIES rather than two spellings of one.
    kept: list[dict] = []
    for h in out:
        if not any(h["matched"] in k["matched"] and h["channel"] == k["channel"] for k in kept):
            kept.append(h)
    return kept


def resolve_quantity(phrase) -> dict:
    """Which declared quantity a phrase names: recorded, not_recorded, unresolved, ambiguous, or error.

    `ambiguous` exists so the registry does not choose on the adjudicator's behalf. A sentence naming two
    quantities is a claim the adjudicator must refuse as unspecific, and it cannot refuse what has already
    been silently reduced to the first match."""
    if not isinstance(phrase, str) or not phrase.strip():
        return {"status": "error", "channel": None, "matched": None, "candidates": [],
                "reason": "bad_argument", "about": "request",
                "note": f"resolve_quantity() needs a non-empty string; got {type(phrase).__name__}."}
    hits = _hits(phrase)
    if not hits:
        return {"status": "unresolved", "channel": None, "matched": None, "candidates": [],
                "reason": "bad_argument", "about": "request",
                "note": "unresolved: no declared quantity is named in this phrase, so the registry has NO "
                        "OPINION about it. This is NOT `not_recorded` -- a quantity nobody mapped is not a "
                        "quantity the corpus lacks, and reporting it as one invents an absence."}
    distinct = {(h["status"], h["channel"]) for h in hits}
    if len(distinct) > 1:
        return {"status": "ambiguous", "channel": None, "matched": None, "candidates": hits,
                "reason": "bad_argument", "about": "request",
                "note": "this phrase names more than one declared quantity, so it does not identify the "
                        "one a verdict would be about. Narrow the claim; the registry will not choose."}
    h = hits[0]
    if h["status"] == "not_recorded":
        return {"status": "not_recorded", "channel": None, "matched": h["matched"], "candidates": hits,
                "reason": "channel_not_recorded", "about": "corpus",
                "note": "this names a real quantity that THIS corpus records no channel for. That IS "
                        "evidence -- about coverage -- so it is about: corpus, and no number can be "
                        "reported for it however the question is asked."}
    return {"status": "recorded", "channel": h["channel"], "matched": h["matched"], "candidates": hits,
            "reason": "", "about": "",
            "note": f"resolves to the declared channel {h['channel']}."}


def quantity_coverage() -> dict:
    """How much of the declared namespace the vocabulary reaches.

    Reported rather than left implicit so that "the document never mentioned it" and "we have no words for
    it" stay distinguishable -- the second is a gap in this registry, not in the model."""
    chans = channels()
    missing = sorted(set(chans) - set(CHANNEL_VOCABULARY))
    return {"n_channels": len(chans), "n_with_vocabulary": len(CHANNEL_VOCABULARY),
            "channels_without_vocabulary": missing,
            "n_not_recorded_quantities": len(NOT_RECORDED_QUANTITIES),
            "note": ("A channel with no vocabulary can never be resolved FROM a document, so a claim about "
                     "it reads as `unresolved`. That is a gap in this table, not an absence in the model, "
                     "and it is listed here so the two are never confused."
                     if missing else "Every declared channel has vocabulary.")}


# --- the two record types the later stages consume ---------------------------------------------------
#
# WHY TWO, which is the decision behind this whole file. A section count was never the quantity of interest.
# A plan section is dense in REQUIREMENTS -- configurations the simulator must support -- and sparse in
# claims; a prediction section is the reverse, but not exclusively, which is why filtering by section kind
# produced two different headline numbers for one archive and neither was interpretable. So the section
# kind stops being a filter and becomes PROVENANCE on a record, and the two kinds of thing a document
# demands are counted separately because they are consumed by different stages: a requirement goes to the
# cost classifier, a claim goes to the per-arm adjudicator.
#
# Both carry `quote` and `section`, so every verdict is auditable back to the words that produced it. That
# is stage 2's rule carried forward: no field without a span.

@dataclass(frozen=True)
class Requirement:
    """A configuration an outside document says the simulator must support."""

    text: str
    quote: str
    section: str
    section_kind: str


@dataclass(frozen=True)
class Claim:
    """A testable statement: a quantity, a target, a reference, and where it was written."""

    quantity: str
    target: str
    reference: str
    quote: str = ""
    section: str = ""
    section_kind: str = ""
    direction: str = ""
    threshold_pct: float | None = None


# Every reason this module's verdicts can carry. Listed so a test can assert each is registered in
# `errors.REASONS`, and raised through `errors.fail` so `about` and `next_step` come from that one registry
# rather than from a second copy here.
ADJUDICATION_REASONS = (
    "channel_not_recorded", "bad_argument", "design_not_in_corpus", "no_shared_arm",
    "insufficient_data", "not_applicable_to_design", "store_unreadable",
)

MIN_REPLICATE_SEEDS = 2   # below this there is no within-design spread, so no comparison is possible


# --- stage 3: can this corpus settle the claim, and in which arm -------------------------------------

def _arm_of(row: dict) -> tuple:
    from . import corpus_schema
    return corpus_schema.arm_of(row)


def _arm_dict(row: dict) -> dict:
    from . import corpus_schema
    return {k: row.get(k) for k in corpus_schema.ARM_KEYS}


def adjudicate_claim(claim, rows=None) -> dict:
    """Is there an arm of this corpus in which `claim` could be tested, and on which channel?

    DECIDABILITY, not truth. No statistic is computed here on purpose: `rigor.disconfirm` and the survey
    already answer "what is the effect", and a second implementation would be a second answer to one
    question -- conformance family 9, which this project has already paid for four times over.

    The load-bearing refusal is the ARM boundary. Two designs can both exist and still not be comparable,
    because rows from different fitted parameter sets describe different instruments; the verdict names both
    arms rather than pooling them, and `corpus_schema.same_arm` is the authority."""
    from . import errors
    if not isinstance(claim, Claim):
        return {"decidable": False, **errors.fail(
            "bad_argument", f"adjudicate_claim() needs a Claim; got {type(claim).__name__}.")}
    # A bench readout is not a weak claim about the simulator. Checked FIRST, before the quantity, because
    # a wet-lab claim may well name a recorded channel and still not be ours to settle.
    if claim.section_kind == "validation_wetlab":
        return {"decidable": False, **errors.fail(
            "not_applicable_to_design",
            f"this claim comes from a wet-lab section ({claim.section!r}): it states what a bench would "
            f"measure, not what this simulator computes. Six reports were once filed as needing a model "
            f"change on the strength of such a sentence.")}
    q = resolve_quantity(claim.quantity)
    if q["status"] != "recorded":
        # Stage 1's verdict is final, and no row is read. Looking for rows first would let a row count stand
        # in for an answer about a quantity no channel carries.
        return {"decidable": False, "quantity_status": q["status"], "quantity_note": q["note"],
                **errors.fail(q["reason"] or "bad_argument", q["note"], candidates=q.get("candidates", []))}
    channel = q["channel"]
    rows = list(rows if rows is not None else _corpus_rows())
    if not rows:
        return {"decidable": False, "channel": channel, **errors.fail(
            "store_unreadable", "no corpus rows are readable, so nothing about this claim follows. This "
            "says the store could not be read, not that the claim is unsupported.")}
    tgt = [r for r in rows if r.get("design") == claim.target]
    ref = [r for r in rows if r.get("design") == claim.reference]
    missing = [d for d, got in ((claim.target, tgt), (claim.reference, ref)) if not got]
    if missing:
        return {"decidable": False, "channel": channel, **errors.fail(
            "design_not_in_corpus",
            f"the document names design(s) {missing} that this corpus holds no rows for. That is a fact "
            f"about OUR coverage, not a mistake by the document -- which is why it is not "
            f"`unknown_design`, whose contract calls a missing design the caller's error.")}
    shared = {_arm_of(a) for a in tgt} & {_arm_of(b) for b in ref}
    if not shared:
        arms = [_arm_dict(r) for r in tgt[:1] + ref[:1]]
        return {"decidable": False, "channel": channel, "arms_available": arms, **errors.fail(
            "no_shared_arm",
            f"{claim.target!r} and {claim.reference!r} both exist but share no comparability arm: "
            f"{arms[0]} against {arms[1]}. Rows from different fitted parameter sets describe different "
            f"instruments, so the difference between them is not an effect. Run the missing comparator in "
            f"one arm.")}
    arm = sorted(shared)[0]
    in_arm_t = [r for r in tgt if _arm_of(r) == arm]
    in_arm_r = [r for r in ref if _arm_of(r) == arm]
    if min(len(in_arm_t), len(in_arm_r)) < MIN_REPLICATE_SEEDS:
        return {"decidable": False, "channel": channel, "arm": _arm_dict(in_arm_t[0]),
                "n_target_rows": len(in_arm_t), "n_reference_rows": len(in_arm_r), **errors.fail(
                    "insufficient_data",
                    f"the shared arm holds {len(in_arm_t)} row(s) of {claim.target!r} and "
                    f"{len(in_arm_r)} of {claim.reference!r}; a comparison needs at least "
                    f"{MIN_REPLICATE_SEEDS} replicate seeds each, because with one there is no within-design "
                    f"spread to compare the difference against.")}
    return {"decidable": True, "channel": channel, "quantity_matched": q["matched"],
            "arm": _arm_dict(in_arm_t[0]), "n_target_rows": len(in_arm_t),
            "n_reference_rows": len(in_arm_r), "target": claim.target, "reference": claim.reference,
            "quote": claim.quote, "section": claim.section,
            "note": (f"this claim is DECIDABLE in one arm on channel {channel}. What the effect IS, and "
                     f"whether it is bigger than replicate noise, is not answered here -- pass the target, "
                     f"the reference and the channel to `disconfirm`/`compare_at_generation`, which are the "
                     f"one implementation of that question.")}


def _corpus_rows():
    """Manifest rows, when the caller supplies none. Imported late so the module stays importable with no
    corpus present and the tests need none."""
    try:
        from . import manifest
        return manifest.rows()
    except Exception:
        return []


# --- stage 4: what the demand would cost -------------------------------------------------------------
#
# ONE BUCKET produced the wrong headline: "47 of 48 reports need a parameter rebuild", against a real figure
# of 0 of 45 for a changed kcat. The fix is not a better pattern, it is having classes at all -- and the
# class that six reports actually needed was `not_a_simulation`.
#
# Every class resolves against an authority that already exists, named in the verdict. No list is copied
# here: conformance family 7 fails any two views of one capability that disagree without declaring it, and a
# classifier carrying its own set of runnable variants is precisely that pair.

# Demands the archive makes that NO variant module performs. Declared, because a refusal must name an
# authority rather than a word shape -- see `_cost_candidates`. Measured: 7 of 45 reports ask for a
# switch-off at a chosen generation, and 57 of 394 development design rows carry one.
KNOWN_UNAVAILABLE_PERTURBATIONS = ("generation_timed_knockout",)

# The one sentence every summary appends when its input was incomplete. Declared once: three summaries
# wording partiality differently is how one of them ends up not saying it.
PARTIAL_NOTE = (
    " A partial extraction makes every count here a LOWER BOUND, not a count: "
    "{n} section(s) were not read, so a class with zero members may simply be in one of them. "
    "\"4 rebuilds\" and \"at least 4 rebuilds, {n} sections unread\" license different decisions, which is "
    "why the flag travels rather than being left in span_failures for a caller to remember.")

# ADJ-W8. The sentence every summary appends when it was never TOLD. The defect was not the mechanism --
# all three summaries accepted `partial` and appended PARTIAL_NOTE when told -- it was the DEFAULT:
# `partial=False` answers the question with a confident no on behalf of a caller who was never asked, and
# span failures are real on live traffic, so the forgetting path is reachable. Three states, not two.
UNSTATED_COMPLETENESS_NOTE = (
    " COMPLETENESS NOT STATED: this summary was not told whether its input was a complete reading, so "
    "every count here may be a LOWER BOUND and nothing in this result can tell you which. Pass "
    "`partial=` and `n_unread=` from the extraction that produced the input -- `span_failures` is where "
    "that fact lives. This used to default to `partial=False`, which is the same silence with a confident "
    "answer written over it.")


# Every summary that must carry the three-state flag, NAMED, so a new one cannot quietly join without it
# and a test can enumerate them instead of a reader remembering. The rule it encodes: a function returning
# a COUNT or a RATE over an extraction has to say whether that extraction was complete, and "nobody said"
# is one of the three answers. A test asserts each of these takes `partial` and defaults it to None, and
# that NOTHING in either module defaults it to False again.
COMPLETENESS_AWARE = ("adjudicate.cost_summary", "extraction.cost_breakdown",
                      "extraction.row_cost_summary", "extraction.normalisation_coverage",
                      "extraction.dedupe",
                      # Added 2026-10-31 BY THE TEST, not by remembering: `mapping_review_sheet` arrived
                      # with a `partial` parameter and the enumeration below failed until it was declared
                      # here. That is the whole point of naming them -- a new summary cannot join quietly.
                      "extraction.mapping_review_sheet")


def completeness_of(partial) -> str:
    """`partial` as one of three states. Told apart by what was PASSED, never by truthiness: a truthiness
    test reads `None` and `False` the same way, which is the defect itself."""
    return "unstated" if partial is None else ("partial" if partial else "complete")


COST_CLASSES = ("run", "flag", "patch_then_run", "rebuild", "refused_by_gate", "not_a_simulation",
                "ambiguous", "unresolved")


def _names(needle: str, haystack: str) -> bool:
    """Does `haystack` NAME `needle` — as its own word, not as a fragment inside another?

    Measured necessity, not caution. With a bare substring test the declared refit lever `arm` matched the
    word "Arm" at the head of a markdown table header and classified a column label as a demand for a ParCa
    rebuild; `kb` would match inside "kbp" the same way. That is `kcat`-inside-a-citation one stage later: a
    word present is not a thing demanded.

    Underscores count as word characters, so `trna_charged_fraction_target` matches itself and not a
    fragment, and a hyphenated flag like `--kinetic-ppgpp` is still found because `-` is a boundary."""
    return re.search(rf"(?<![\w-]){re.escape(needle)}(?![\w-])", haystack) is not None


def _cost_candidates(text: str) -> list[dict]:
    """Every cost class `text` resolves to, each naming the authority that decided it."""
    from . import capability, doe, envelope
    low = text.lower()
    found: list[dict] = []
    # A drafted patch first: it names a flag that does NOT exist in the checkout yet, so matching it as a
    # plain flag would promise a switch nobody can pass today.
    for pid, patch in capability.DRAFT_PATCHES.items():
        if (_names(patch.flag.lower(), low) or _names(patch.name.lower(), low)
                or _names(pid.lower(), low)):
            found.append({"cost": "patch_then_run", "matched": patch.flag,
                          "authority": f"capability.DRAFT_PATCHES[{pid!r}]",
                          "note": f"{pid} is DRAFTED and not applied in the checkout, so this is a patch "
                                  f"then a run, not a flag. Prerequisites: {list(patch.requires)}."})
    # A mode named only INSIDE a matched patch's own flag is not a second demand. `--kinetic-ppgpp` contains
    # "kinetic" because the patch REQUIRES the kinetic model; reporting that as an independent flag demand
    # would make every patch request `ambiguous` between patch_then_run and flag, which is the registry
    # choosing by spelling rather than by meaning.
    patch_spellings = " ".join(f"{c['matched']} {c['note']}".lower() for c in found)
    for mode in capability.ELONGATION_MODES:
        if _names(mode, low) and mode not in patch_spellings:
            found.append({"cost": "flag", "matched": mode,
                          "authority": f"capability.MODE_FLAGS[{mode!r}]",
                          "note": f"an elongation model is a runSim flag, not a refit: "
                                  f"{capability.MODE_FLAGS[mode]}."})
    for lever in doe.REFIT_FACTORS:
        if _names(lever, low):
            found.append({"cost": "rebuild", "matched": lever,
                          "authority": "doe.REFIT_FACTORS",
                          "note": "this lever's levels are FITTED parameters: each needs its own ParCa "
                                  "build, and its rows are not poolable with the corpus. A rebuild mints a "
                                  "new arm."})
    for variant in sorted(capability.LAUNCHED_VARIANT_MODULES):
        if _names(variant, low):
            found.append({"cost": "run", "matched": variant,
                          "authority": "capability.LAUNCHED_VARIANT_MODULES",
                          "note": "a launched variant module: this is a run to queue, in an arm we have."})
    for pert in sorted(envelope.VALIDATED_PERTURBATIONS):
        if _names(pert, low) and not any(f["matched"] == pert for f in found):
            found.append({"cost": "run", "matched": pert,
                          "authority": "envelope.VALIDATED_PERTURBATIONS",
                          "note": "inside the validated envelope, so it is a run rather than a change to "
                                  "the model."})
    # A DEMAND WE KNOW WE CANNOT MEET, named. Only these, and only when nothing else matched.
    #
    # This replaced a token-SHAPE heuristic that fired on any snake_case word ending in "knockout",
    # "shift" or "_conc", and probing it showed the heuristic was both over- and under-reaching:
    # "a nutrient_downshift to acetate" was refused because the word ends in "shift" -- right, but by
    # accident -- while "a carbon_source_switch mid-run" came back `unresolved` even though the envelope
    # genuinely refuses a carbon switch. A verdict that is correct because a word ended in the right four
    # letters is the proxy error this project has withdrawn findings for, and a FALSE refusal is the
    # expensive direction: it tells a collaborator to drop a row of their own plan.
    #
    # So a cell-level refusal now needs a declared identifier. Everything else is undecidable at cell level
    # and decided at ROW level, where a timeline and a medium exist for the envelope to actually check.
    if not found:
        for ident in KNOWN_UNAVAILABLE_PERTURBATIONS:
            if _names(ident, low):
                found.append({"cost": "refused_by_gate", "matched": ident,
                              "authority": "adjudicate.KNOWN_UNAVAILABLE_PERTURBATIONS, against "
                                           "envelope.VALIDATED_PERTURBATIONS",
                              "note": f"{ident!r} is a demand we have measured and cannot meet: no variant "
                                      f"module performs it, so the feasibility gate refuses it before "
                                      f"anything runs. Validated variants: "
                                      f"{sorted(envelope.VALIDATED_PERTURBATIONS)}."})
                break
    return found


def classify_cost(requirement) -> dict:
    """What a demand would cost us: run, flag, patch_then_run, rebuild, refused_by_gate, not_a_simulation.

    `ambiguous` and `unresolved` are first-class, and both matter. A demand matching two classes is not
    resolved by table order -- "run the kinetic model with operons off" is a flag AND a rebuild, and a
    classifier that picked one would hide an arm boundary. A demand matching nothing is `unresolved`, never
    the single bucket that produced the wrong headline."""
    from . import errors
    if not isinstance(requirement, Requirement):
        return {"cost": "unresolved", "authority": "", "candidates": [], **errors.fail(
            "bad_argument", f"classify_cost() needs a Requirement; got {type(requirement).__name__}.")}
    # The locator's section kind is the authority here, and it is checked first: a bench readout is not a
    # cheap simulation, it is not a simulation.
    if requirement.section_kind == "validation_wetlab":
        return {"cost": "not_a_simulation", "matched": requirement.section,
                "authority": "adjudicate.locate -> section_kind == 'validation_wetlab'",
                "candidates": [],
                "note": "this demand comes from a wet-lab section: it asks for a bench measurement, and no "
                        "configuration of this simulator produces one. Six reports were once filed as "
                        "needing a model-code change on exactly this evidence."}
    cands = _cost_candidates(requirement.text)
    classes = {c["cost"] for c in cands}
    if not cands:
        return {"cost": "unresolved", "matched": None, "authority": "", "candidates": [],
                "note": "no declared authority recognises anything in this demand, so its cost is UNKNOWN. "
                        "That is deliberately not a rebuild: assigning every unrecognised demand to one "
                        "bucket is what produced '47 of 48 need a parameter rebuild' against a real 0 of 45."}
    if len(classes) > 1:
        return {"cost": "ambiguous", "matched": None,
                "authority": ", ".join(sorted({c["authority"] for c in cands})),
                "candidates": cands,
                "note": "this demand resolves to more than one cost class, and both are reported rather "
                        "than one being chosen by table order -- a demand that is a flag AND a rebuild "
                        "spans arms, which is the expensive half and the easy half to lose."}
    c = cands[0]
    return {"cost": c["cost"], "matched": c["matched"], "authority": c["authority"],
            "candidates": cands, "note": c["note"]}


def cost_summary(requirements, partial: bool | None = None, n_unread: int = 0) -> dict:
    """The cost table for a set of demands, with EVERY class counted including the empty ones.

    "Only 4 of 45 reports need nothing but a rebuild" is a readable sentence only because the other classes
    were counted too. A summary that omits its zeros cannot be read as a distribution."""
    counts = {c: 0 for c in COST_CLASSES}
    rows = []
    for r in requirements or []:
        v = classify_cost(r)
        counts[v["cost"]] = counts.get(v["cost"], 0) + 1
        rows.append({"quote": getattr(r, "quote", ""), "section": getattr(r, "section", ""),
                     "cost": v["cost"], "authority": v["authority"], "matched": v.get("matched")})
    note = ("Every class is present with its count, zeros included. A demand's cost is a fact "
            "about THIS platform resolved against its own authorities, not a property of the "
            "document -- so the same sentence costs differently once a patch lands.")
    if partial is None:
        note += UNSTATED_COMPLETENESS_NOTE
    elif partial:
        note += PARTIAL_NOTE.format(n=n_unread)
    return {"n": len(rows), "by_cost": counts, "items": rows,
            "partial": None if partial is None else bool(partial),
            "completeness": completeness_of(partial),
            "n_unread_sections": int(n_unread), "note": note}
