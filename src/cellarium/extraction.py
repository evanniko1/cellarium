"""Extraction from an outside document, by TWO independent calculations that are then compared.

WHY TWO, AND WHY NOT MORE CARE. This project has exactly one method that has ever caught an extraction
error, and it is not diligence: two independent calculations of one quantity, compared. The isoleucine
contamination in the option-A analysis surfaced that way — a hand-written script and Cellarium's own
family-grouping tool disagreed about one number, and the script was wrong. Every other instance in this
repository was found the same way or not at all.

The methodological literature on data extraction says the same in blunter terms. Reviews of the practice
report extraction error rates up to 50%, a later analysis up to 63%, single extraction producing roughly
22% more errors than double extraction in a randomised comparison, and single screeners missing a median 5%
of eligible studies (range 0-58%) with findings changing substantially in 3 of 7 meta-analyses. The standard
mitigation is dual independent extraction with the disagreements resolved explicitly. One extractor,
however careful, is the configuration that literature warns about.

THE TWO PATHS SHARE NO MECHANISM AND BARELY SHARE AN INPUT.

  * STRUCTURAL reads the DECLARED TABLES and nothing else. Measured over the 33 development reports, the
    plan tables are factorial design matrices: 33 tables, 277 data rows, 6-8 columns whose headers name our
    own factors ("ppGpp Module" 27 times, "Target Setpoint" 16, "Amino-Acid Mode" 16, "Perturbation" 8). A
    column is a factor and a cell is its level, so this path needs no vocabulary over prose at all.
  * LEXICAL reads the PROSE and nothing else, for authority identifiers and declared quantities.

If either path read the other's input, agreement between them would measure nothing. The structural path
therefore skips every table line; the lexical path is given the prose with the tables removed.

Where the two agree, a record carries two independent provenances. Where they disagree, that IS the finding
and it is reported per path. Nothing here prefers a path, because neither is a reference standard — and for
the same reason the statistic reported is AGREEMENT, never accuracy.

THE MECHANICAL GATE, which is what makes a third path safe to add. Every record must carry a quote that is a
verbatim span of the source. That is rule R1 of the hypothesis hand-off made checkable by a machine rather
than kept by discipline: a language model can propose fields, and a field it invented has no verbatim span,
so it cannot survive `verify_quotes`. `AGENT_PATH_CONTRACT` states what such a path must satisfy, and it is
written before any of it exists.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from . import adjudicate

# Declared roles a plan-table column can play. A header word maps to a role; a role tells the later stages
# what the cell means. Derived from the development set's own headers (printed above), which is why the
# synonyms are as blunt as they are — "Amino-Acid Mode", "Endogenous AA Module" and "Amino Acid Supply
# Module" are the same column under three spellings in one archive.
#
# `id` and `note` columns are declared on purpose rather than left to fall through: a run identifier is not
# a factor, and silently treating one as a level would put "R1" in the design space.
COLUMN_ROLES: dict[str, tuple[str, ...]] = {
    "factor:ppgpp_module": ("ppgpp module", "ppgpp regulation", "ppgpp"),
    "factor:aa_supply": ("amino-acid mode", "amino acid mode", "endogenous aa module",
                         "amino acid supply module", "amino-acid module", "aa supply module",
                         "aa module"),
    "factor:target_charging": ("target setpoint", "target charging", "target charging setpoint",
                               "charging setpoint", "charged fraction target"),
    "factor:medium": ("medium / carbon source", "carbon source", "medium carbon", "medium",
                      "carbon & electron regime", "carbon regime"),
    "factor:perturbation": ("perturbation", "perturbation target", "perturbation (gen 1)",
                            "perturbation target (gen 1)", "genotype"),
    "factor:shift": ("nutritional shift", "shift perturbation", "carbon transition", "shift"),
    "factor:elongation_model": ("elongation model", "charging model", "simulation module",
                                "wcecoli simulation module matrix", "simulation module matrix"),
    "readout": ("primary readouts evaluated", "primary readouts", "readouts", "readout",
                "analytical focus", "primary readout"),
    "id": ("run id", "sim id", "experiment id", "simulation set", "arm", "id"),
    "note": ("addressed hypothesis", "predicted terminal generation", "rationale", "notes", "note"),
}

_ROLE_OF_HEADER = {w: role for role, words in COLUMN_ROLES.items() for w in words}

# The two paths MUST emit the same role for the same fact, or agreement between them is impossible by
# construction. That is not a hypothetical: the first run of this module had the structural path emitting
# `factor:elongation_model` for a column and the lexical path `mode:elongation_model` for the same mode
# named in prose, and they agreed on NOTHING. The comparison found it, which is the argument for the
# comparison.
#
# The lexical path discovers levers by their authority identifier, so it needs the inverse map.
REFIT_LEVER_ROLES: dict[str, str] = {
    "trna_charged_fraction_target": "factor:target_charging",
    "charged_fraction_target": "factor:target_charging",
    "operons": "factor:operons",
    "retype_cistrons": "factor:retype_cistrons",
}

# What identifier each role carries in the AUTHORITIES stage 4 resolves against. Without this, a role name
# is handed to the cost classifier as prose -- `factor:target_charging 0.55` matches no declared lever, and
# a rebuild reads as `unresolved`. A test asserts every identifier here is recognised by some authority, so
# a role that stops resolving fails loudly instead of silently costing nothing.
ROLE_IDENTIFIERS: dict[str, str] = {
    "factor:target_charging": "charged_fraction_target",
    "factor:operons": "operons",
    "factor:retype_cistrons": "retype_cistrons",
    "factor:elongation_model": "",          # the VALUE is the identifier (steady_state / kinetic / ...)
    "factor:perturbation": "",              # the value is the variant name
    "factor:ppgpp_module": "",              # resolved from the value, which may name a patch flag
    "factor:aa_supply": "",
    "factor:medium": "",
    "factor:shift": "",
}

# A cell that states nothing. Kept as a declared list so an empty cell is skipped for a stated reason rather
# than by a truthiness test that would also drop a legitimate "0".
_EMPTY_CELLS = ("", "-", "--", "n/a", "na", "none", "tbd", "—", "–")

_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.M)

# What a language-model extraction path would have to satisfy. Written BEFORE any of it exists, because a
# contract added after reading a path's output is fitted to that output — the same rule the hypothesis
# hand-off applies to its alias table.
AGENT_PATH_CONTRACT = {
    "implemented": False,
    "why_not_here": "A language-model path is the plausible THIRD independent calculation, and the two "
                    "mechanical paths had to exist first: without them there is nothing to compare an "
                    "agent against except a reference standard this project does not have.",
    "temperature": 0.0,
    "gate": "every record passes extraction.verify_quotes against the source document; a field with no "
            "verbatim span is rejected, not repaired",
    "must": (
        "quote a verbatim span for every field it fills",
        "record why a field was left empty, in its own words, naming what the prose said instead",
        "run at temperature 0 — this is justification-side work, not generation",
        "read only the spans the locator marks plan or claim, and subtract excluded_descendants",
    ),
    "may_not": (
        "infer, complete or correct a field from the goal, the corpus, or what the text obviously meant",
        "widen any declared vocabulary after reading a document — an untranscribable field is COUNTED",
        "adjudicate its own output: the mechanical verifier is the gate, and a second model judging a "
        "first is a reviewer that can be wrong in the same way as the thing it reviews",
    ),
    "third_path_must_be_mechanical": "If two agent paths are run, the adjudicator between them stays "
                                     "deterministic. An LLM judging an LLM is the architecture this "
                                     "project's own comparison with MechAInistic argues against.",
}


@dataclass(frozen=True)
class Record:
    """One extracted field, with the span that evidences it and the path that found it."""

    kind: str            # "requirement" | "claim"
    role: str            # a COLUMN_ROLES key, or "mode:*" / "lever:*" / "readout:*" from the prose
    value: str           # the level, as written
    quote: str           # a VERBATIM span of the source document
    section: str
    section_kind: str
    path: str            # "structural" | "lexical" | "agent"
    start: int = 0
    end: int = 0

    def key(self) -> tuple:
        """What counts as the same record across paths: the role and the normalised value.

        The quote is deliberately NOT part of the key. Two paths that found one fact in two places is the
        agreement worth having; requiring them to have found the same characters would reduce agreement to
        a test of whether both read the same line, which is the thing the two paths are built not to do."""
        return (self.kind, self.role, re.sub(r"\s+", " ", self.value).strip().lower())


# --- the mechanical gate ------------------------------------------------------------------------------

def verify_quotes(records, source: str) -> dict:
    """Keep the records whose quote is a verbatim span of `source`; report the rest with a reason.

    An EMPTY quote is rejected rather than treated as trivially present: "" is a substring of every
    document, so accepting it would let a field with no evidence pass the only check that asks for any.

    Rejections are returned, never dropped. A silently shortened list is the empty-success shape: the count
    looks clean and the missing records are the finding."""
    kept, rejected = [], []
    for r in records or []:
        if not isinstance(r, Record):
            rejected.append({"record": str(r)[:120], "quote": "", "reason": "not_a_record"})
        elif not (r.quote or "").strip():
            rejected.append({**asdict(r), "reason": "quote_empty"})
        elif r.quote not in source:
            rejected.append({**asdict(r), "reason": "quote_not_in_source"})
        else:
            kept.append(r)
    return {"n_kept": len(kept), "n_rejected": len(rejected), "kept": kept, "rejected": rejected,
            "reason": "bad_argument" if rejected else "", "about": "request" if rejected else "",
            "note": (f"{len(rejected)} record(s) carry a quote that is not a verbatim span of the source "
                     f"and are REJECTED, not repaired. A field without a span has no evidence, and this is "
                     f"the only check that asks for any."
                     if rejected else
                     "every record's quote is a verbatim span of the source.")}


# --- path A: structural, the declared tables only -----------------------------------------------------

def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_rule(cells) -> bool:
    return all(set(c) <= set("-: ") and c for c in cells)


def extract_structural(text: str) -> list[Record]:
    """Records from the DECLARED TABLES of plan sections: a column is a factor, a cell is its level.

    Reads no prose at all, which is what makes agreement with the lexical path informative. A HEADER is
    never emitted as a record — measured last turn, feeding plan sections to the cost classifier line by
    line put column labels into the `run` and `rebuild` classes, because a label is not a demand."""
    out: list[Record] = []
    loc = adjudicate.locate(text)
    if "error" in loc and loc.get("error"):
        return out
    for sec in loc.get("plan_sections", []):
        span = text[sec["read_span"][0]:sec["read_span"][1]]
        lines = [m.group(0) for m in _TABLE_LINE.finditer(span)]
        rows = [_cells(ln) for ln in lines]
        keep = [i for i, cs in enumerate(rows) if not _is_rule(cs)]
        if len(keep) < 2:
            continue
        headers = rows[keep[0]]
        roles = [_ROLE_OF_HEADER.get(h.strip().lower()) for h in headers]
        for i in keep[1:]:
            cs = rows[i]
            for j, cell in enumerate(cs):
                if j >= len(roles) or roles[j] in (None, "id", "note"):
                    continue
                if cell.strip().lower() in _EMPTY_CELLS:
                    continue
                at = text.find(cell, sec["read_span"][0], sec["read_span"][1])
                if roles[j] == "readout":
                    # A readout column names the quantities the row will be read on. Each is a CLAIM
                    # candidate, not a requirement: it says what will be measured, not what to configure.
                    for part in re.split(r",| and ", cell):
                        part = part.strip()
                        if part and part.lower() not in _EMPTY_CELLS:
                            pos = text.find(part, sec["read_span"][0], sec["read_span"][1])
                            # Resolved to a channel here, so a readout cell and the same quantity named in
                            # prose carry the SAME role and can agree. An unresolved cell keeps the bare
                            # role rather than being dropped: it is a readout the registry has no words
                            # for, which is a gap in the vocabulary and not an absence in the document.
                            q = adjudicate.resolve_quantity(part)
                            role = (f"readout:{q['channel']}" if q["status"] == "recorded" else "readout")
                            out.append(Record(kind="claim", role=role, value=part, quote=part,
                                              section=sec["heading"], section_kind=sec["kind"],
                                              path="structural", start=max(pos, 0),
                                              end=max(pos, 0) + len(part)))
                    continue
                out.append(Record(kind="requirement", role=roles[j], value=cell, quote=cell,
                                  section=sec["heading"], section_kind=sec["kind"], path="structural",
                                  start=max(at, 0), end=max(at, 0) + len(cell)))
    return out


def _n_design_rows(text: str) -> int:
    """Data rows across every plan table -- the number of SIMULATIONS a plan asks for.

    Reported beside the distinct-demand count because the two answer different questions and swapping them
    is how a 277-run plan reads as four decisions, or four decisions read as 277 rebuilds."""
    n = 0
    for sec in adjudicate.locate(text).get("plan_sections", []):
        span = text[sec["read_span"][0]:sec["read_span"][1]]
        rows = [_cells(m.group(0)) for m in _TABLE_LINE.finditer(span)]
        keep = [cs for cs in rows if not _is_rule(cs)]
        if len(keep) >= 2:
            n += len(keep) - 1          # minus the header
    return n


def _unmapped_columns(text: str) -> list[str]:
    """Plan-table headers no declared role covers — the structural path's own blind spot, counted.

    Reported so that "the table did not say" and "we have no role for this header" stay apart. The second
    is a gap in COLUMN_ROLES, and a gap nobody counts is a gap nobody closes."""
    out: list[str] = []
    loc = adjudicate.locate(text)
    for sec in loc.get("plan_sections", []):
        span = text[sec["read_span"][0]:sec["read_span"][1]]
        rows = [_cells(m.group(0)) for m in _TABLE_LINE.finditer(span)]
        keep = [cs for cs in rows if not _is_rule(cs)]
        if len(keep) < 2:
            continue
        for h in keep[0]:
            if h.strip() and _ROLE_OF_HEADER.get(h.strip().lower()) is None and h not in out:
                out.append(h.strip())
    return out


# --- path B: lexical, the prose only ------------------------------------------------------------------

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def extract_lexical(text: str) -> list[Record]:
    """Records from the PROSE of plan and claim sections, with every table line removed first.

    Removing the tables is what keeps the two paths independent. A lexical path that also read table rows
    would agree with the structural path by construction, and the agreement statistic would measure only
    that both had read the same characters."""
    out: list[Record] = []
    loc = adjudicate.locate(text)
    if "error" in loc and loc.get("error"):
        return out
    from . import capability, doe
    for sec in loc.get("sections", []):
        if sec["kind"] not in ("plan", "claim"):
            continue
        span = text[sec["read_span"][0]:sec["read_span"][1]]
        prose = _TABLE_LINE.sub("", span)
        for m in _SENTENCE.finditer(prose):
            sentence = m.group(0).strip()
            if len(sentence) < 12 or sentence not in text:
                continue
            low = sentence.lower()
            if sec["kind"] == "plan":
                for mode in capability.ELONGATION_MODES:
                    if adjudicate._names(mode, low):
                        out.append(Record(kind="requirement", role="factor:elongation_model", value=mode,
                                          quote=sentence, section=sec["heading"],
                                          section_kind=sec["kind"], path="lexical"))
                for lever in doe.REFIT_FACTORS:
                    if adjudicate._names(lever, low):
                        out.append(Record(kind="requirement",
                                          role=REFIT_LEVER_ROLES.get(lever, "factor:refit"), value=lever,
                                          quote=sentence, section=sec["heading"],
                                          section_kind=sec["kind"], path="lexical"))
            q = adjudicate.resolve_quantity(sentence)
            for cand in (q.get("candidates") or []):
                if cand["status"] == "recorded":
                    out.append(Record(kind="claim", role=f"readout:{cand['channel']}",
                                      value=cand["matched"], quote=sentence, section=sec["heading"],
                                      section_kind=sec["kind"], path="lexical"))
    return out


# --- reconciliation: the comparison, with no winner ---------------------------------------------------

def reconcile(structural, lexical) -> dict:
    """Compare two independent extractions. Reports agreement; never resolves a disagreement.

    AGREEMENT IS NOT ACCURACY, and the distinction is the whole point. Neither path is a reference
    standard, so two paths agreeing on a wrong record agree just as strongly as on a right one. What
    agreement buys is that a DISAGREEMENT is a place to look — which is exactly how the isoleucine
    contamination was caught.

    Cohen's kappa is deliberately not computed. Kappa needs two raters labelling one fixed item set; these
    paths each discover their own items, so there is no shared denominator and a kappa over the union would
    be a number with no referent."""
    a = {r.key(): r for r in structural or []}
    b = {r.key(): r for r in lexical or []}
    shared = sorted(set(a) & set(b))
    union = set(a) | set(b)
    agreed = [{"kind": k[0], "role": k[1], "value": a[k].value,
               "paths": sorted({a[k].path, b[k].path}),
               "quotes": sorted({a[k].quote, b[k].quote}),
               "sections": sorted({a[k].section, b[k].section})} for k in shared]
    # WAS AGREEMENT EVEN POSSIBLE? Measured over the 33 development reports, these two paths produced 2,018
    # and 8,654 records and agreed on SEVEN, a mean per-report Jaccard of 0.004, with 30 of 33 reports
    # agreeing on nothing. Read naively that is violent disagreement. It is nothing of the kind: the
    # structural path finds FACTORS because factors live in table cells, the lexical path finds READOUTS
    # because readouts are named in prose, and their role sets are nearly disjoint -- so agreement was close
    # to impossible before either path read a word.
    #
    # The distinction is load-bearing, because dual extraction's entire value is REDUNDANCY on one
    # quantity. Two paths looking at different things cannot check each other, however much each finds.
    # Reporting a low Jaccard without saying which situation produced it would be a confident wrong reading
    # of our own instrument -- the shape this project keeps finding.
    roles_a = {k[1] for k in a}
    roles_b = {k[1] for k in b}
    roles_union = roles_a | roles_b
    overlap = round(len(roles_a & roles_b) / len(roles_union), 4) if roles_union else 0.0
    kind = ("complementary" if overlap == 0.0 else
            "redundant" if overlap == 1.0 else "partial")
    reading = {
        "complementary": "COMPLEMENTARY: the two paths share no role, so a low agreement checks NOTHING "
                         "about either path's correctness -- it only records that they looked at different "
                         "things. To use agreement as an error check, point both paths at the same roles.",
        "redundant": "REDUNDANT: the two paths cover the same roles, so agreement is informative and each "
                     "disagreement is a place to look.",
        "partial": "PARTIAL: agreement is informative only on the shared roles. On the rest the paths are "
                   "complementary, and a zero there checks nothing.",
    }[kind]
    return {
        "agreed": agreed,
        "structural_only": [asdict(a[k]) for k in sorted(set(a) - set(b))],
        "lexical_only": [asdict(b[k]) for k in sorted(set(b) - set(a))],
        "agreement": {
            "n_structural": len(a), "n_lexical": len(b), "n_agreed": len(shared),
            "jaccard": round(len(shared) / len(union), 4) if union else 0.0,
            "role_overlap": overlap,
            "comparison_kind": kind,
            "roles_structural_only": sorted(roles_a - roles_b),
            "roles_lexical_only": sorted(roles_b - roles_a),
            "not_reported": "Cohen's kappa is NOT reported: it needs two raters labelling one fixed item "
                            "set, and these paths each discover their own items, so a kappa over the union "
                            "would have no denominator to mean anything against.",
        },
        "note": ("AGREEMENT IS NOT ACCURACY. Neither path is a reference standard, so two paths agreeing "
                 "on a wrong record agree exactly as strongly as on a right one. " + reading + " "
                 + ("The two paths agree on NO record." if not shared else
                    f"{len(shared)} record(s) carry two independent provenances.")),
    }


def as_requirement(record: Record):
    """A `Record` as the stage-4 classifier's input, with its role translated into the AUTHORITY's own
    identifier.

    Without the translation a role name reaches the classifier as prose: `factor:target_charging 0.55`
    matches no declared lever, so a demand for a ParCa rebuild comes back `unresolved` and costs nothing.
    Measured on the first run of this module. `ROLE_IDENTIFIERS` carries the translation and a test asserts
    every identifier in it is still recognised by some authority, so a role that stops resolving fails
    loudly rather than quietly reading as free."""
    n = normalise_value(record.role, record.value)
    value = n["value"] if n["basis"] not in ("unnormalised", "multi_level") else record.value
    ident = ROLE_IDENTIFIERS.get(record.role, "")
    if record.role in ROW_DEPENDENT_ROLES:
        # The cost cannot be decided from this cell. The ROLE is put in the text rather than a canonical
        # level, so the classifier returns `unresolved` -- which is the right verdict -- and the reason is
        # recoverable from ROW_DEPENDENT_ROLES rather than being a silent no-match.
        text = f"{record.role} {value}".strip()
    else:
        text = f"{ident} {value}".strip() if ident else value
    return adjudicate.Requirement(text=text, quote=record.quote, section=record.section,
                                  section_kind=record.section_kind)


def extract_report(text, agent_records=None) -> dict:
    """Both mechanical paths, their comparison, and any agent records held to the same gate."""
    if not isinstance(text, str) or not text.strip():
        return {"error": f"extract_report() needs the document text as a non-empty string; got "
                         f"{type(text).__name__}.", "reason": "bad_argument", "about": "request"}
    s_raw, l_raw = extract_structural(text), extract_lexical(text)
    s_v, l_v = verify_quotes(s_raw, text), verify_quotes(l_raw, text)
    s, legs = s_v["kept"], l_v["kept"]
    unmapped = _unmapped_columns(text)
    out = {
        "structural": {"n_records": len(s), "n_rejected": s_v["n_rejected"],
                       "n_distinct": dedupe(s)["n_distinct"],
                       "n_design_rows": _n_design_rows(text),
                       "normalisation": normalisation_coverage(s),
                       "unmapped_columns": unmapped,
                       "note": ("no declared table was found in any plan section, so this path has nothing "
                                "to read — which is a fact about the document's form, not about what it "
                                "demands." if not s else
                                f"{len(s)} record(s) from declared tables; {len(unmapped)} column(s) carry "
                                f"a header no declared role covers and are counted, not dropped.")},
        "lexical": {"n_records": len(legs), "n_rejected": l_v["n_rejected"],
                    "note": f"{len(legs)} record(s) from prose, with every table line removed first so "
                            f"agreement with the structural path is not agreement by construction."},
        "reconciled": reconcile(s, legs),
    }
    if agent_records is not None:
        v = verify_quotes(agent_records, text)
        out["agent"] = {"n_kept": v["n_kept"], "n_rejected": v["n_rejected"],
                        "rejected": v["rejected"], "contract": AGENT_PATH_CONTRACT,
                        "note": "agent records pass the same mechanical gate as every other path: a field "
                                "with no verbatim span is rejected rather than repaired."}
    return out


# --- value normalisation -----------------------------------------------------------------------------
#
# WHY. Measured over the 33 development reports, 79.8% of structural requirements came back `unresolved`
# at stage 4, and the cause was not the classifier: the cells are prose. The real values are
# "*argA* switch-off" (112 cells), "ON" (248), "OFF (Fixed)" (32), "Endogenous Biosynthesis" (50),
# "Glucose minimal" (176), "M9 Glucose (Aerobic)" (26). None of those is an identifier any authority knows.
#
# THE CONSTRAINT THAT KEEPS THIS HONEST, and it is not caution. Normalisation may only produce a value some
# AUTHORITY already recognises; anything else stays raw and is counted as `unnormalised`. Mapping
# "Glucose + 20 AAs" to a plausible-looking medium name we do not have would be strictly worse than leaving
# it alone: a media name reaches the simulator verbatim and is looked up by name, so an invented one is not
# a weaker experiment, it is a run that dies at the first step of the shift and leaves a truncated run
# directory that looks like data. Normalisation must never be the step that invents one.
#
# Every table below is a DECLARED synonym list, built while reading the development set, and frozen against
# the held-out twelve: a spelling they use that is not here is COUNTED as unnormalised, never added.

_PPGPP_SYNONYMS = {"on": "on", "enabled": "on", "dynamic": "on", "responsive": "on", "active": "on",
                   "off": "off", "fixed": "off", "clamped": "off", "disabled": "off", "static": "off"}

_AA_SUPPLY_SYNONYMS = {"on": "enzymes", "endogenous": "enzymes", "biosynthesis": "enzymes",
                       "enzyme-aware": "enzymes", "enzyme aware": "enzymes", "mechanistic": "enzymes",
                       "off": "medium", "clamped": "medium", "medium-clamped": "medium",
                       "medium clamped": "medium", "fixed": "medium", "exogenous": "medium"}

# Media are mapped ONLY into names `envelope.media_with_a_doubling_time()` contains, and the mapping is
# checked against that set at call time rather than trusted from this table.
_MEDIUM_SYNONYMS = (
    ("glucose + 20 aa", "minimal_plus_amino_acids"),
    ("glucose + aa", "minimal_plus_amino_acids"),
    ("plus amino acid", "minimal_plus_amino_acids"),
    ("anaerobic", "minimal_minus_oxygen"),
    ("no glucose", "minimal_no_glucose"),
    ("acetate", "minimal_acetate"),
    ("succinate", "minimal_succinate"),
    ("fumarate", "minimal_fumarate"),
    ("malate", "minimal_malate"),
    ("minus phosphate", "minimal_minus_phosphate"),
    ("nitrate", "minimal_plus_nitrate"),
    ("arabinose", "minimal_plus_arabinose"),
    # Last, because every one of the above also contains the word glucose or is a glucose medium.
    ("glucose", "minimal"),
    ("m9", "minimal"),
    ("minimal", "minimal"),
)

# A cell naming two levels of one factor: "ON vs OFF", "0.55 vs 0.85". It is a factor crossed inside a row,
# and picking the first level would silently halve the design.
_VS = re.compile(r"\s+(?:vs\.?|versus|or)\s+", re.I)

# A gene symbol as these reports write it: *argA*, `argA`, argA. Three to five letters, a capital at the
# end, which is the E. coli convention and specific enough not to match an English word.
_GENE = re.compile(r"[*`_]?\b([a-z]{3}[A-Z])\b[*`_]?")

# A switch-off scheduled at a generation. Measured earlier: 7 of 45 reports ask for one, and NO variant
# module does it. Normalising it to a plain knockout would hide the single demand that must be refused, so
# it gets its own identifier -- one the envelope does not validate, which is what makes stage 4 refuse it.
_GEN_TIMED = re.compile(r"\bgen(?:eration)?[-\s]*(\d+)\b", re.I)

# Roles whose COST cannot be decided from the cell alone, with the reason. `ppGpp module = on` is the
# default under steady_state and costs nothing; under kinetic it is EXT-PORT-P, a drafted patch. The
# deciding fact is another cell in the SAME ROW, so a per-cell verdict would be a guess. Declared, so the
# resulting `unresolved` carries a reason instead of reading as "nothing matched".
ROW_DEPENDENT_ROLES: dict[str, str] = {
    "factor:ppgpp_module": "costs nothing under the steady-state elongation model (it is the default) and "
                           "is the drafted patch EXT-PORT-P under kinetic, so the cost depends on the "
                           "elongation model named elsewhere in the same ROW",
    "factor:aa_supply": "enzyme-aware supply is the steady-state default and the drafted patch EXT-PORT-A "
                        "under kinetic, so the cost depends on the elongation model in the same ROW",
}


def normalise_value(role: str, raw: str) -> dict:
    """A cell value as the authorities spell it, or raw with `basis='unnormalised'`.

    Never invents a value. `basis` is one of declared_synonym, numeric, identity, multi_level or
    unnormalised, and `raw` is always kept so a reader can audit the mapping."""
    from . import capability, envelope
    out = {"role": role, "raw": raw, "value": raw, "basis": "unnormalised", "levels": [], "gene": "",
           "genes": []}
    text = (raw or "").strip()
    if not text:
        return out
    low = text.lower()
    parts = _VS.split(text)
    if len(parts) > 1:
        # Two levels in one cell. Kept raw on purpose: it is not ONE level, so handing a single value
        # downstream would halve the design the author asked for.
        out["basis"] = "multi_level"
        out["levels"] = [p.strip() for p in parts if p.strip()]
        return out
    if role == "factor:ppgpp_module":
        for word, canon in _PPGPP_SYNONYMS.items():
            if word in low:
                return {**out, "value": canon, "basis": "declared_synonym"}
        return out
    if role == "factor:aa_supply":
        for word, canon in _AA_SUPPLY_SYNONYMS.items():
            if word in low:
                return {**out, "value": canon, "basis": "declared_synonym"}
        return out
    if role == "factor:target_charging":
        m = re.search(r"\d*\.?\d+", text)
        if m:
            return {**out, "value": m.group(0), "basis": "numeric"}
        if "none" in low or "no refit" in low or "unanchored" in low:
            return {**out, "value": "none", "basis": "declared_synonym"}
        return out
    if role == "factor:medium":
        known = envelope.media_with_a_doubling_time() or set()
        for word, canon in _MEDIUM_SYNONYMS:
            if word in low:
                # Checked against the authority at CALL time, not trusted from the table above: a medium
                # that stops having a condition row must stop being produced here.
                return ({**out, "value": canon, "basis": "declared_synonym"} if canon in known else out)
        return out
    if role == "factor:elongation_model":
        for mode in capability.ELONGATION_MODES:
            if adjudicate._names(mode, low):
                return {**out, "value": mode, "basis": "identity"}
        return out
    if role == "factor:perturbation":
        genes = [m.group(1) for m in _GENE.finditer(text)]
        g = genes[0] if genes else ""
        if _GEN_TIMED.search(text) and ("switch" in low or "knock" in low or "off" in low):
            # Deliberately an identifier the envelope does NOT validate, so stage 4 refuses it by the
            # authority rather than by a word shape.
            return {**out, "value": "generation_timed_knockout", "basis": "declared_synonym", "gene": g,
                    "genes": genes}
        if "wild" in low or low in ("wt", "none", "control"):
            return {**out, "value": "wildtype", "basis": "declared_synonym"}
        for pert in sorted(envelope.VALIDATED_PERTURBATIONS):
            if adjudicate._names(pert, low):
                return {**out, "value": pert, "basis": "identity", "gene": g, "genes": genes}
        if genes:
            # A GENE SYMBOL in a column whose role is the perturbation target is a knockout of that gene --
            # that is the column's own meaning, and it is read so here rather than inferred at a call site.
            #
            # Measured necessity: 28 of 96 development rows reported as BLOCKED were cells naming genes with
            # no verb ("`argS`, `hisS`", "`alaS`, `argS`, `hisS`, `gltX`"). They matched no synonym, stayed
            # raw, and a raw value is not a validated perturbation -- so ordinary knockouts were reported as
            # refused by the feasibility gate. That is the worst direction to be wrong in: an undecidable
            # row says "I cannot price this", a blocked row says "nothing makes this runnable", and a false
            # block would tell a collaborator to drop rows of their own plan that run.
            value = "gene_knockout" if len(genes) == 1 else "multi_gene_knockout"
            return {**out, "value": value, "basis": "declared_synonym", "gene": g, "genes": genes}
        return out
    return out


def normalisation_coverage(records) -> dict:
    """How much of each role's values normalise, and which ones do not.

    The unnormalised VALUES are listed, not just counted, because a spelling the tables miss is a gap this
    module can close and a gap nobody can see is a gap nobody closes."""
    by_role: dict[str, dict] = {}
    for r in records or []:
        if r.kind != "requirement":
            continue
        n = normalise_value(r.role, r.value)
        slot = by_role.setdefault(r.role, {"normalised": 0, "unnormalised": 0, "multi_level": 0,
                                           "unnormalised_values": []})
        if n["basis"] == "unnormalised":
            slot["unnormalised"] += 1
            if r.value not in slot["unnormalised_values"]:
                slot["unnormalised_values"].append(r.value)
        elif n["basis"] == "multi_level":
            slot["multi_level"] += 1
        else:
            slot["normalised"] += 1
    total = sum(s["normalised"] + s["unnormalised"] + s["multi_level"] for s in by_role.values())
    norm = sum(s["normalised"] for s in by_role.values())
    return {"by_role": by_role, "n_values": total, "n_normalised": norm,
            "fraction_normalised": round(norm / total, 4) if total else 0.0,
            "note": "An unnormalised value is a gap in the declared synonym tables, NOT a value the "
                    "document failed to state. The values are listed so the gap is closeable; they are "
                    "frozen against the held-out reports, where a new spelling is counted rather than "
                    "added."}


# --- dedupe ------------------------------------------------------------------------------------------

def dedupe(records) -> dict:
    """Collapse repeated DEMANDS, keeping every provenance and every occurrence count.

    THE NUMBER THIS FIXES. 342 `rebuild` records came out of roughly 277 table rows each carrying one
    setpoint cell, while the archive asks for FOUR distinct setpoints. Counting cells counts rows.
    `n_occurrences` keeps the row-level fact, the distinct list carries the demand-level one, and
    `extract_report` reports the design-row count separately -- because a plan asking for 277 simulations
    still asks for 277 simulations, and a dedupe that lost that would make the plan look cheap.

    Per DOCUMENT. Two reports asking for the same setpoint are two reports agreeing, not one demand, and
    merging across documents would destroy the count that says how widely a demand is shared."""
    groups: dict[tuple, list] = {}
    for r in records or []:
        groups.setdefault(r.key(), []).append(r)
    distinct = []
    for key, rs in sorted(groups.items()):
        first = rs[0]
        distinct.append({"kind": key[0], "role": key[1], "value": first.value,
                         "n_occurrences": len(rs),
                         "quotes": [x.quote for x in rs],
                         "sections": sorted({x.section for x in rs}),
                         "paths": sorted({x.path for x in rs}),
                         "spans": [[x.start, x.end] for x in rs]})
    return {"n_raw": len(records or []), "n_distinct": len(distinct), "distinct": distinct,
            "note": "Deduplicated per DOCUMENT on (kind, role, normalised value). `n_occurrences` keeps "
                    "the cell-level count, so the demand count and the row count stay separate numbers "
                    "answering separate questions."}


def as_requirements_distinct(records):
    """One `adjudicate.Requirement` per DISTINCT demand, for a cost table that counts decisions not cells."""
    out = []
    for d in dedupe(records)["distinct"]:
        if d["kind"] != "requirement":
            continue
        rec = Record(kind="requirement", role=d["role"], value=d["value"], quote=d["quotes"][0],
                     section=d["sections"][0] if d["sections"] else "", section_kind="plan",
                     path=d["paths"][0] if d["paths"] else "structural")
        out.append(as_requirement(rec))
    return out


def cost_of(record) -> dict:
    """`adjudicate.classify_cost` for a Record, with a row-dependent `unresolved` made legible.

    WHY THIS EXISTS. Decomposed over the development set, 210 distinct demands came back `unresolved`, and
    read as one number that looks like a 69% blind spot. It is not. 68 of them are ROW-DEPENDENT -- the
    cost of `ppGpp module = on` genuinely depends on the elongation model named in the same row -- and that
    is the correct verdict, not a miss. 67 are media, which cost nothing as a cell because a medium is part
    of a design rather than a demand on the model. 47 are cells from a column whose values are
    configuration labels, which the authority constraint rightly refuses to normalise. Only 28 are a gap in
    the declared tables.

    `classify_cost` is right to say `unresolved` for all of them: nothing in its authorities matched. What
    was missing was any way for a caller to tell the four apart without knowing to consult
    ROW_DEPENDENT_ROLES by hand -- which is a reason recoverable only by someone who already knows it, and
    that is the shape this project calls a silent absence. So the distinction is attached here."""
    out = dict(adjudicate.classify_cost(as_requirement(record)))
    if out["cost"] == "unresolved" and record.role in ROW_DEPENDENT_ROLES:
        out["row_dependent"] = True
        out["unresolved_because"] = "row_dependent"
        out["note"] = (f"NOT a gap in the tables: this cell's cost cannot be decided from the cell. "
                       f"{ROW_DEPENDENT_ROLES[record.role]}. Cost the design ROW, not this cell.")
    elif out["cost"] == "unresolved":
        n = normalise_value(record.role, record.value)
        out["row_dependent"] = False
        out["unresolved_because"] = ("value_not_normalised" if n["basis"] == "unnormalised"
                                     else "cell_is_not_cost_bearing")
        if n["basis"] == "unnormalised":
            out["note"] = (f"{record.value!r} matches no declared synonym for {record.role}, so no "
                           f"authority could be consulted. A gap in the tables, and a closeable one -- "
                           f"see normalisation_coverage().")
        else:
            out["note"] = (f"{record.role} normalises to {n['value']!r} but names nothing any cost "
                           f"authority prices: a medium or a shift is part of a DESIGN, not a demand on "
                           f"the model, so it costs nothing on its own.")
    return out


def cost_breakdown(records) -> dict:
    """Costs over DISTINCT demands, with `unresolved` split by why.

    Reported this way because the single number misleads in the expensive direction: a 69% unresolved rate
    reads as a blind instrument when most of it is the instrument correctly declining to cost a cell."""
    counts = {c: 0 for c in adjudicate.COST_CLASSES}
    why = {"row_dependent": 0, "value_not_normalised": 0, "cell_is_not_cost_bearing": 0}
    for d in dedupe(records)["distinct"]:
        if d["kind"] != "requirement":
            continue
        rec = Record(kind="requirement", role=d["role"], value=d["value"], quote=d["quotes"][0],
                     section=d["sections"][0] if d["sections"] else "", section_kind="plan",
                     path=d["paths"][0] if d["paths"] else "structural")
        v = cost_of(rec)
        counts[v["cost"]] += 1
        if v["cost"] == "unresolved":
            why[v["unresolved_because"]] += 1
    return {"by_cost": counts, "unresolved_because": why,
            "n_distinct": sum(counts.values()),
            "note": "Costs are over DISTINCT demands, not cells. `unresolved_because` splits the one class "
                    "that otherwise misleads: `row_dependent` is the classifier being right, "
                    "`cell_is_not_cost_bearing` is a medium or a shift that costs nothing alone, and only "
                    "`value_not_normalised` is a gap in the declared tables."}


# --- costing a design ROW ----------------------------------------------------------------------------
#
# WHY A ROW AND NOT A CELL. Decomposed over the development set, 68 of 210 unresolved distinct demands were
# ROW-DEPENDENT: `ppGpp module = on` costs nothing under the steady-state model, where it is the default,
# and is the drafted patch EXT-PORT-P under kinetic. The deciding fact is another cell in the same row, so
# no per-cell verdict exists and `classify_cost` was right to decline.
#
# A ROW IS NOT A SINGLE COST CLASS. Its prerequisites CO-OCCUR: a row can need a parameter rebuild and a
# code patch and still be refused by the feasibility gate. Collapsing that to a maximum over some declared
# ordering would answer a question nobody asked. What an operator needs is two things -- can I queue this
# today, and if not, what has to happen first -- so this returns a SET of prerequisites plus one blocking
# verdict, and `blocked` is kept separate from `prerequisites` because no ordering of work clears it.
#
# AND THE MODE IS USUALLY UNSTATED. The column that looked like it named elongation models holds
# configuration labels ("Config 1", "Designation"), so most rows never say which model they run under.
# Defaulting to steady_state would silently price a kinetic row as free, so an unstated mode makes the
# module costs `undecidable` and says so. That is the cell-level row-dependence reappearing one level up,
# and the honest answer at both levels is the same: name the missing fact.

# The two module flags, with where each was verified rather than from memory. `--no-ppgpp-regulation` is
# quoted in patch 3's own refusal ("--kinetic-ppgpp needs ppGpp regulation on; remove
# --no-ppgpp-regulation"); `--no-mechanistic-aa-transport` is named in the port patch's switchable-options
# comment and is the flag every option-A simulation actually ran with (Appendix D.5).
MODULE_FLAGS = {
    ("factor:ppgpp_module", "off"): "--no-ppgpp-regulation",
    ("factor:aa_supply", "medium"): "--no-mechanistic-aa-transport",
}

# A row's prerequisites, as a declared set. `undecidable` is one of them on purpose: a row whose mode is
# unstated, or whose cell names two levels, has a cost nobody can compute, and that is a different state
# from needing nothing.
ROW_PREREQUISITES = ("run", "flag", "patch_then_run", "rebuild", "undecidable")


def _patch_for(role: str, value: str):
    """The drafted patch a module cell needs UNDER THE KINETIC MODEL, or None.

    Resolved from `capability.DRAFT_PATCHES` by option name rather than by a table here, so a patch that
    lands upstream stops being a prerequisite without an edit in this file."""
    from . import capability
    want = {"factor:ppgpp_module": "kinetic_ppgpp", "factor:aa_supply": "kinetic_aa_supply"}.get(role)
    if not want:
        return None
    on = {"factor:ppgpp_module": "on", "factor:aa_supply": "enzymes"}[role]
    if value != on:
        return None
    for pid, patch in capability.DRAFT_PATCHES.items():
        if patch.name == want:
            return pid if not patch.applied else None
    return None


def cost_row(cells) -> dict:
    """What one design row would cost: a set of prerequisites, a blocking verdict, and the arm it lands in.

    `cells` is {role: raw value} for one table row. Returns `runnable_today` only when nothing is blocked
    and no prerequisite remains."""
    from . import capability, envelope
    if not isinstance(cells, dict) or not cells:
        return {"error": "cost_row() needs a non-empty {role: value} map for ONE design row; got "
                         f"{type(cells).__name__}. An empty row is an argument fault, not a free row.",
                "reason": "bad_argument", "about": "request"}
    norm, multi, per_cell = {}, [], {}
    for role, raw in cells.items():
        n = normalise_value(role, raw)
        if n["basis"] == "multi_level":
            multi.append(role)
        norm[role] = n["value"] if n["basis"] not in ("unnormalised", "multi_level") else raw
        per_cell[role] = {"raw": raw, "value": norm[role], "basis": n["basis"], "prerequisite": "",
                          "gene": n.get("gene", "")}
    mode = norm.get("factor:elongation_model", "")
    mode_stated = mode in capability.ELONGATION_MODES
    prereq: set[str] = set()
    patches: list[str] = []
    flags: list[str] = []
    blockers: list[dict] = []

    if mode_stated and mode != capability.DEFAULT_MODE:
        flags.append(capability.MODE_FLAGS[mode])
        prereq.add("flag")
        per_cell["factor:elongation_model"]["prerequisite"] = "flag"
    elif mode_stated:
        per_cell["factor:elongation_model"]["prerequisite"] = "run"

    for role in ("factor:ppgpp_module", "factor:aa_supply"):
        if role not in norm:
            continue
        if role in multi:
            prereq.add("undecidable")
            per_cell[role]["prerequisite"] = "undecidable"
            continue
        if not mode_stated:
            # The cell-level row-dependence, one level up. Not defaulted: a kinetic row priced as
            # steady_state reads as free, which is the expensive direction to be wrong in.
            prereq.add("undecidable")
            per_cell[role]["prerequisite"] = "undecidable"
            continue
        if mode == capability.DEFAULT_MODE:
            flag = MODULE_FLAGS.get((role, norm[role]))
            if flag:
                flags.append(flag)
                prereq.add("flag")
                per_cell[role]["prerequisite"] = "flag"
            else:
                per_cell[role]["prerequisite"] = "run"      # the steady-state default costs nothing
        else:
            pid = _patch_for(role, norm[role])
            if pid:
                patches.append(pid)
                prereq.add("patch_then_run")
                per_cell[role]["prerequisite"] = "patch_then_run"
            else:
                per_cell[role]["prerequisite"] = "run"

    if "factor:target_charging" in norm:
        if "factor:target_charging" in multi:
            prereq.add("undecidable")
            per_cell["factor:target_charging"]["prerequisite"] = "undecidable"
        elif norm["factor:target_charging"] != "none":
            prereq.add("rebuild")
            per_cell["factor:target_charging"]["prerequisite"] = "rebuild"

    for role in ("factor:perturbation", "factor:shift", "factor:medium"):
        if role not in norm:
            continue
        v = norm[role]
        if role == "factor:perturbation":
            if v in envelope.VALIDATED_PERTURBATIONS:
                prereq.add("run")
                per_cell[role]["prerequisite"] = "run"
            elif per_cell[role]["basis"] == "unnormalised":
                # Unreadable, which is NOT refused. A cell this module cannot normalise says nothing about
                # whether the design is runnable, and reporting it as blocked would be a false refusal --
                # measured at 28 of 96 blocked rows before the gene-symbol reading landed.
                prereq.add("undecidable")
                per_cell[role]["prerequisite"] = "undecidable"
            else:
                blockers.append({"role": role, "value": v,
                                 "why": f"{v!r} is not a validated model variant, so the feasibility gate "
                                        f"refuses this row before anything runs."})
                per_cell[role]["prerequisite"] = "refused_by_gate"
        elif role == "factor:medium":
            known = envelope.media_with_a_doubling_time() or set()
            if known and v not in known:
                per_cell[role]["prerequisite"] = "undecidable"
                prereq.add("undecidable")
            else:
                per_cell[role]["prerequisite"] = "run"
        else:
            per_cell[role]["prerequisite"] = "run"

    combined = None
    if len(set(patches)) > 1:
        combined = capability.draft_patch_combination(tuple(sorted(set(patches))))
    arm = {"elongation_model": mode or "UNSTATED",
           "operons": norm.get("factor:operons", "on (default)"),
           "charged_fraction_target": norm.get("factor:target_charging", "none (default)")}
    blocked = bool(blockers)
    note_bits = []
    if not mode_stated and any(r in norm for r in ("factor:ppgpp_module", "factor:aa_supply")):
        note_bits.append("This row does not state its elongation model, so the ppGpp and amino-acid module "
                         "costs are UNDECIDABLE and are not assumed: the same cell value costs nothing "
                         "under steady_state (where it is the default) and a drafted patch under kinetic.")
    if multi:
        note_bits.append(f"Cell(s) {multi} name TWO levels, so this is more than one row and costing it as "
                         f"one would price half the design.")
    if blocked:
        note_bits.append("BLOCKED: no ordering of work makes this row runnable, which is why blockers are "
                         "kept apart from prerequisites.")
    if combined:
        note_bits.append(f"Both drafted patches are needed, which is the named arm {combined['arm']}.")
    return {"cells_raw": dict(cells), "cells_normalised": norm, "per_cell": per_cell,
            "prerequisites": sorted(prereq), "patches": sorted(set(patches)), "flags": sorted(set(flags)),
            "combined_arm": combined, "blocked": blocked, "blockers": blockers,
            "multi_level_cells": sorted(multi), "mode_unstated": not mode_stated, "arm": arm,
            "runnable_today": (not blocked) and not (prereq - {"run"}),
            "note": " ".join(note_bits) or ("Runnable today: nothing in this row needs a flag, a patch, a "
                                            "rebuild or a decision."),
            }


def extract_design_rows(text: str) -> list[dict]:
    """One record per DATA ROW of every plan table: the cells grouped, with the row line as its quote.

    A row is the unit a simulation is queued from, and the unit whose cost is computable; the per-cell
    records remain for the demand count. Both are kept because they answer different questions."""
    out: list[dict] = []
    loc = adjudicate.locate(text)
    for sec in loc.get("plan_sections", []):
        span = text[sec["read_span"][0]:sec["read_span"][1]]
        lines = [m.group(0) for m in _TABLE_LINE.finditer(span)]
        rows = [_cells(ln) for ln in lines]
        keep = [i for i, cs in enumerate(rows) if not _is_rule(cs)]
        if len(keep) < 2:
            continue
        headers = rows[keep[0]]
        roles = [_ROLE_OF_HEADER.get(h.strip().lower()) for h in headers]
        for n, i in enumerate(keep[1:]):
            cs = rows[i]
            raw, cooked = {}, {}
            for j, cell in enumerate(cs):
                if j >= len(roles) or roles[j] in (None, "id", "note", "readout"):
                    continue
                if cell.strip().lower() in _EMPTY_CELLS:
                    continue
                nv = normalise_value(roles[j], cell)
                raw[roles[j]] = cell
                cooked[roles[j]] = (nv["value"] if nv["basis"] not in ("unnormalised", "multi_level")
                                    else cell)
            if not raw:
                continue
            out.append({"section": sec["heading"], "row_index": n, "cells_raw": raw, "cells": cooked,
                        "quote": lines[i]})
    return out


def row_cost_summary(text: str) -> dict:
    """Row-level costs for a whole document, with the two numbers that decide whether this can work.

    `n_mode_unstated` is the one to read first: a row that does not name its elongation model cannot be
    priced on its module cells, however good the rest of the pipeline is."""
    rows = extract_design_rows(text)
    by_pre = {p: 0 for p in ROW_PREREQUISITES}
    blocked = runnable = unstated = 0
    patches_needed: dict[str, int] = {}
    details = []
    for r in rows:
        v = cost_row(r["cells_raw"])
        if "error" in v:
            continue
        for p in v["prerequisites"]:
            by_pre[p] = by_pre.get(p, 0) + 1
        blocked += 1 if v["blocked"] else 0
        runnable += 1 if v["runnable_today"] else 0
        unstated += 1 if v["mode_unstated"] else 0
        for pid in v["patches"]:
            patches_needed[pid] = patches_needed.get(pid, 0) + 1
        details.append({"section": r["section"], "row_index": r["row_index"], "quote": r["quote"],
                        "prerequisites": v["prerequisites"], "blocked": v["blocked"],
                        "runnable_today": v["runnable_today"], "arm": v["arm"]})
    return {"n_rows": len(rows), "by_prerequisite": by_pre, "n_blocked": blocked,
            "n_runnable_today": runnable, "n_not_runnable_today": len(rows) - runnable,
            "n_mode_unstated": unstated, "n_mode_stated": len(rows) - unstated,
            "patches_needed": patches_needed, "rows": details,
            "note": ("A row is one simulation. `by_prerequisite` counts rows per prerequisite and the "
                     "counts OVERLAP, because a row can need several; `n_blocked` is kept apart because no "
                     "ordering of work clears a blocker. Read `n_mode_unstated` first: a row that does not "
                     "name its elongation model cannot be priced on its module cells at all.")}
