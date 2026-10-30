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

import json
import os
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
    "implemented": True,
    "built_second_because": "The two mechanical paths had to exist first: without them there is nothing to "
                            "compare an agent against except a reference standard this project does not "
                            "have. They then measured what a complementary path buys (role overlap ~0, "
                            "Jaccard 0.004), which is what decided this path's job -- STRUCTURE, aimed at "
                            "the roles the structural path already covers so agreement means something.",
    "what_it_is_for": "Binding a prose sentence into (target, reference, channel, direction, threshold). "
                      "The lexical path found 8,654 readout mentions over the development set and bound "
                      "NONE of them to a target/reference pair.",
    "temperature": 0.0,
    "temperature_caveat": "0.0 WHERE THE MODEL ACCEPTS ONE. Found on the first live call: "
                          "claude-sonnet-5 answers 400 `temperature is deprecated for this model`, and "
                          "llm.temperature_for returns None for that family -- so on THAT model sampling "
                          "is not pinned and cannot be, and an extraction from it is not reproducible run "
                          "to run. That is why the default is now a model which accepts an explicit "
                          "temperature; `temperature_pinned` in the result says which case you are in, "
                          "because the default is overridable and the clause has to stay honest for an "
                          "operator who overrides it. A contract clause the configuration cannot satisfy "
                          "is worse than no clause, so it is recorded rather than quietly dropped.",
    "gate": "every record passes extraction.verify_quotes against the source document; a field with no "
            "verbatim span is rejected, not repaired",
    "quote_provenance": "CUT BY THE PLATFORM out of the units the model cites, never copied by the "
                        "model. Measured on the first live section this path read: 10 records proposed, "
                        "10 rejected for quote_not_in_source, and the cause was NOT markup -- checked all "
                        "three ways it could have been innocent, exact matches 0, matches after the "
                        "declared table-stripping 0, genuinely absent 10. The model rewrote the content "
                        "and offered the rewrite as quotation, while the prompt said CHARACTER FOR "
                        "CHARACTER in capitals. Asking harder is not a fix, so the opportunity is removed "
                        "instead: the model is shown numbered units and cites numbers. What this does NOT "
                        "buy is relevance -- a true span can be cited for a record it does not support, "
                        "and that is counted (n_value_outside_quote), not assumed away.",
    "must": (
        "cite the unit numbers a field is stated on -- the platform cuts the quote out of those units, so "
        "no copying is asked of it",
        "record why a field was left empty, in its own words, naming what the prose said instead",
        "run at temperature 0 — this is justification-side work, not generation",
        "read only the spans the locator marks plan or claim, and subtract excluded_descendants",
    ),
    "may_not": (
        "retype, paraphrase or reconstruct the text: a `quote` field in the reply is IGNORED, and its "
        "difference from the cited units is counted rather than argued with",
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


def extract_report(text, agent_records=None, agent_client=None) -> dict:
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
        out["agent_vs_structural"] = reconcile(s, v["kept"])
    elif agent_client is not None:
        a = extract_agent(text, client=agent_client)
        out["agent"] = {k: a[k] for k in ("n_kept", "n_rejected", "rejected", "unfilled", "note",
                                          "quotes_cut_by_platform", "n_rewrote", "n_value_outside_quote")
                        if k in a}
        # The flag TRAVELS. A caller who must remember to read `span_failures` and then pass a parameter by
        # hand is a caller who forgets once, and the forgetting is silent.
        out["agent"]["partial"] = bool(a.get("span_failures"))
        out["agent"]["n_unread_sections"] = len(a.get("span_failures") or [])
        out["agent"]["contract"] = AGENT_PATH_CONTRACT
        out["agent_claims"] = a.get("claims", [])
        # Reconciled against STRUCTURAL, deliberately, and not against lexical. The two mechanical paths
        # are complementary, so their agreement checks nothing; the agent is aimed at the roles the
        # structural path already covers, which is the only arrangement here where agreement is evidence.
        out["agent_vs_structural"] = reconcile(s, a.get("kept", []))
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
                                           "unnormalised_values": [], "applied_mappings": {}})
        if n["basis"] == "unnormalised":
            slot["unnormalised"] += 1
            if r.value not in slot["unnormalised_values"]:
                slot["unnormalised_values"].append(r.value)
        elif n["basis"] == "multi_level":
            slot["multi_level"] += 1
        else:
            slot["normalised"] += 1
            # The mappings ACTUALLY APPLIED, listed for audit. Probed: round-tripping a normalised medium
            # through the envelope does NOT validate the mapping, it validates the design -- `Acetate
            # minimal -> minimal_acetate` is a correct mapping whose timeline the envelope rightly refuses
            # as a carbon switch, so a round-trip check would report a correct mapping as broken. A machine
            # can check MEMBERSHIP (the value is in the authority's set), and does, at call time. WHICH
            # member is right is a judgement no check makes, so the only honest mitigation is to make the
            # applied mappings readable by someone who can judge them.
            m = slot["applied_mappings"].setdefault(r.value, {"value": n["value"], "n": 0})
            m["n"] += 1
    total = sum(s["normalised"] + s["unnormalised"] + s["multi_level"] for s in by_role.values())
    norm = sum(s["normalised"] for s in by_role.values())
    return {"by_role": by_role, "n_values": total, "n_normalised": norm,
            "fraction_normalised": round(norm / total, 4) if total else 0.0,
            "note": "An unnormalised value is a gap in the declared synonym tables, NOT a value the "
                    "document failed to state. The values are listed so the gap is closeable; they are "
                    "frozen against the held-out reports, where a new spelling is counted rather than "
                    "added. WHAT IS CHECKED AND WHAT IS NOT: membership is checked -- a produced value is "
                    "in its authority's set or it is not produced at all. Whether the mapping chose the "
                    "CORRECT member is a judgement no check here makes, which is why "
                    "`applied_mappings` lists every mapping that fired, for a reader who can judge it."}


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


def cost_breakdown(records, partial: bool = False, n_unread: int = 0) -> dict:
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
    return {"by_cost": counts, "unresolved_because": why, "partial": bool(partial),
            "n_unread_sections": int(n_unread), "n_distinct": sum(counts.values()),
            "note": "Costs are over DISTINCT demands, not cells. `unresolved_because` splits the one class "
                    "that otherwise misleads: `row_dependent` is the classifier being right, "
                    "`cell_is_not_cost_bearing` is a medium or a shift that costs nothing alone, and only "
                    "`value_not_normalised` is a gap in the declared tables."
                    + (adjudicate.PARTIAL_NOTE.format(n=n_unread) if partial else "")}


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


def row_cost_summary(text: str, partial: bool = False, n_unread: int = 0) -> dict:
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
            "partial": bool(partial), "n_unread_sections": int(n_unread),
            "note": ((adjudicate.PARTIAL_NOTE.format(n=n_unread) if partial else "")
                     + "A row is one simulation. `by_prerequisite` counts rows per prerequisite and the "
                     "counts OVERLAP, because a row can need several; `n_blocked` is kept apart because no "
                     "ordering of work clears a blocker. Read `n_mode_unstated` first: a row that does not "
                     "name its elongation model cannot be priced on its module cells at all.")}


# --- the agent path: STRUCTURE, which is the one thing neither mechanical path produces ---------------
#
# WHAT IT IS FOR, stated narrowly because the measurement already ruled out the obvious alternative. The
# lexical path found 8,654 readout mentions across the 33 development reports and bound NONE of them to a
# target/reference pair -- recall without structure. Turning "growth rate falls by at least 20% in the argS
# knockout relative to wild type" into (target, reference, channel, direction, threshold) is what a language
# model does well and a pattern does not.
#
# WHAT IT IS NOT FOR. Not a second opinion. The two mechanical paths already measured what a complementary
# second path buys: role overlap near zero, Jaccard 0.004, 30 of 33 reports agreeing on nothing. Adding a
# third path that looks somewhere else again would add records and check nothing. So this path is aimed at
# the SAME roles the structural path covers, which is what makes agreement between them informative --
# `extract_report` reconciles agent against structural separately for exactly that reason.
#
# WHY IT IS SAFE TO ADD, and this is the whole argument. The model is allowed to be wrong; the gate is not.
# Every field must quote a verbatim span, so an invented value cannot survive `verify_quotes`; a role
# outside the declared vocabulary is rejected before that, because it could never be reconciled with either
# mechanical path and would sit in `agent_only` looking like a finding; and a field left blank without a
# stated reason is rejected, because a blank with no reason is indistinguishable from a field nobody looked
# at. None of those three checks consults the model.
#
# THE PROHIBITIONS ARE SENT VERBATIM FROM THE CONTRACT rather than paraphrased into the prompt, so the
# rules the prompt states and the rules the tests check cannot drift apart.
#
# No provider SDK is imported here: `llm.client()` is the one place a client is constructed (LLM-7a), and
# `tests/test_llm_seam.py` asserts that over the tree.

# MEASURED, not chosen on taste. On `claude-sonnet-5` this path does not work at all: the first live call
# on a 3,114-character section came back with `block_types: ['thinking']` and `stop_reason: 'max_tokens'`
# TWICE -- the model spent its entire budget on extended reasoning and never wrote a text block, at 3,000
# and again at 9,000 tokens. That is Appendix E item 4 with the evidence attached.
#
# The same family also refuses an explicit temperature, so sampling could not be pinned there and the
# extraction was not reproducible run to run. ADJ-W7 was recorded as a trade between a weaker model and
# reproducibility; the measurement removed the trade. A transcription step does not need extended
# reasoning, and this one is actively broken by it.
#
# Haiku accepts a pinned temperature (`llm.temperature_for` returns 0.0 for it) and writes text, so the
# default is a model this path WORKS on and whose output is reproducible. Overridable, because the choice
# is a measurement about today's models rather than a property of the design.
AGENT_MODEL_DEFAULT = os.environ.get("CELLARIUM_EXTRACT_MODEL", "claude-haiku-4-5-20251001")

# Fields a claim record may carry beyond the common ones. Declared so a model cannot introduce a field the
# adjudicator will not read.
_AGENT_CLAIM_FIELDS = ("target", "reference", "direction", "threshold_pct")


def _llm_client(**kw):
    """The provider seam. Separate function so a test can replace it without touching `llm`."""
    from . import llm
    return llm.client(**kw)


# This path's OWN sampling temperature, pinned at zero. The Council pins its own too, and the asymmetry is
# by purpose: a proposer samples warm to generate rivals, a transcriber must not sample at all.
EXTRACTOR_TEMPERATURE = 0.0


def _temperature_for(model: str):
    """The temperature to SEND, or None to omit it.

    TWO JOBS, and only one of them belongs to the seam. Whether a model ACCEPTS an explicit temperature is
    provider policy and `llm.temperature_for` owns it -- hardcoding a value here is what the first live call
    failed on. But WHICH value to send is this path's own decision, and inheriting the global was a defect
    caught before shipping: `llm.temperature_for` returns `CELLARIUM_TEMPERATURE`, the Cellwright knob, so
    an operator raising it for a sweep would have made this transcriber sample WARM while the result
    reported `temperature_pinned: True`.

    Pinned is not deterministic. A fixed 0.7 still samples, and two runs of a TRANSCRIPTION differing is
    precisely the thing that field is read as denying. So the seam decides whether to send one and this
    module decides that it is zero."""
    from . import llm
    return None if llm.temperature_for(model) is None else EXTRACTOR_TEMPERATURE


# --- W9: a quote is CUT BY THE PLATFORM from cited units, never copied by the model --------------------
#
# THE MEASUREMENT THAT FORCED THIS. On the first live section this path ever read: 10 records proposed, 10
# rejected for `quote_not_in_source`. Checked all three ways it could have been innocent -- exact matches 0,
# matches after the declared table-stripping 0, genuinely absent 10 -- so it was not markup normalisation.
# The model rewrote the content and offered the rewrite as quotation, with a prompt that said CHARACTER FOR
# CHARACTER in capitals. A stricter prompt is not a fix for that; it is the same instrument, asked louder.
#
# So the opportunity is removed. The span is shown as NUMBERED UNITS, the model returns unit numbers, and
# the platform cuts the quote. Verbatim stops depending on compliance and becomes a property of the cut --
# which is why the units must TILE the span exactly: a cut that spans two units is a substring only if no
# character falls between them. `verify_quotes` stays in place, now checking the construction rather than
# the model.
#
# WHY UNITS AND NOT LINES. Measured over the development set: 11.7% of the lines inside a plan or claim span
# run past 300 characters and the widest is 1,596. Numbering those as lines would make a citation resolve to
# a whole paragraph -- verbatim and unreadable -- and would make a quote's size a property of how the OUTSIDE
# producer wraps its text. A long line is therefore split at sentence boundaries, and a long line with no
# sentence boundary stays whole, because inventing a break the text does not have is the worse error.
#
# WHAT THE SPLIT LEAVES, measured rather than assumed -- I first attributed the residue to wide table rows
# and that was wrong. After the split 2.0% of units still exceed 300 characters (widest 584), and of those
# 479 units: 253 are ONE unbroken sentence, 139 a list item, 84 have a break whose pieces are still long,
# and 3 are table rows. Real table rows in this archive top out at 352 characters. So the residue is not a
# failure of the split -- a 436-character sentence IS one sentence, and quoting it whole is right.

CITABLE_UNIT_MAX = 300
MIN_UNIT_CHARS = 40
MAX_CITED_UNITS = 12

# Why a record can fail to produce a quote. Declared, so a rejection names a cause instead of arriving as a
# smaller list, and so `cut_not_in_source` stays distinguishable from the model-side failure it replaces:
# it means the PLATFORM cut something the document does not contain, which is this module's bug.
CITATION_REASONS = ("no_line_citation", "line_out_of_range", "line_citation_too_wide",
                    "cited_units_are_blank", "cut_not_in_source")

_SENTENCE_BREAK = re.compile(r"(?<=[.;:!?])\s+")
_CITATION_TOKEN = re.compile(r"L?0*(\d+)\s*(?:[-\u2013\u2014]\s*L?0*(\d+))?")


def _line_spans(text: str) -> list[tuple[int, int]]:
    """The lines of `text` WITH their newline, so the spans tile it exactly and leave no gap."""
    out, start = [], 0
    for m in re.finditer("\n", text):
        out.append((start, m.end()))
        start = m.end()
    if start < len(text) or not out:
        out.append((start, len(text)))
    return out


def _sentence_spans(text: str, lo: int, hi: int) -> list[tuple[int, int]]:
    """One line split into sentence-sized pieces, or left whole when it has nowhere to break."""
    if hi - lo <= CITABLE_UNIT_MAX:
        return [(lo, hi)]
    line = text[lo:hi]
    cuts, last = [], 0
    for m in _SENTENCE_BREAK.finditer(line):
        if m.end() - last >= MIN_UNIT_CHARS and m.end() < len(line):
            cuts.append(m.end())
            last = m.end()
    if not cuts:
        return [(lo, hi)]
    out, prev = [], 0
    for c in cuts:
        out.append((lo + prev, lo + c))
        prev = c
    out.append((lo + prev, hi))
    return out


def citable_units(span_text: str) -> list[dict]:
    """Numbered units that TILE `span_text` exactly: every character belongs to exactly one unit.

    The tiling is the whole guarantee. A citation of units i..j is cut as span[units[i].start:units[j].end],
    which is a contiguous substring precisely because nothing lies between consecutive units -- so a quote
    cannot be a splice of two real fragments, which would be a fabrication manufactured by this module
    rather than by the model."""
    units = []
    for lo, hi in _line_spans(span_text or ""):
        for a, b in _sentence_spans(span_text, lo, hi):
            units.append({"n": len(units) + 1, "start": a, "end": b, "text": span_text[a:b]})
    return units


def numbered_body(units: list[dict]) -> str:
    """What the model is shown: one numbered unit per line, with its own newline stripped for display."""
    return "\n".join("L%04d| %s" % (u["n"], u["text"].rstrip("\n")) for u in units)


def _cited_numbers(cited) -> list[int]:
    """The unit numbers a reply refers to, from whatever shape it wrote them in.

    GENEROUS ABOUT THE POINTER, STRICT ABOUT THE CUT. "L0003", "3-4" and 3 are the same citation written
    three ways; rejecting the spelling would discard a record whose evidence is fine, while the cut itself
    stays mechanical and refuses anything it cannot resolve."""
    if cited is None or isinstance(cited, bool):
        return []
    if isinstance(cited, dict):
        for key in ("lines", "line", "line_numbers", "units", "unit"):
            if key in cited:
                return _cited_numbers(cited[key])
        return []
    if isinstance(cited, int):
        return [cited]
    items = [cited] if isinstance(cited, str) else list(cited) if isinstance(cited, (list, tuple, set)) \
        else []
    out: list[int] = []
    for it in items:
        if isinstance(it, bool):
            continue
        if isinstance(it, (int, float)):
            out.append(int(it))
        elif isinstance(it, (list, tuple, set, dict)):
            out += _cited_numbers(it)
        else:
            for m in _CITATION_TOKEN.finditer(str(it)):
                out.append(int(m.group(1)))
                if m.group(2):
                    out.append(int(m.group(2)))
    return sorted(set(out))


def cut_cited(span_text: str, units: list[dict], cited, source: str | None = None) -> dict:
    """The quote for a citation, cut by this module. Returns a reason instead when it cannot be cut.

    A NON-CONTIGUOUS citation is WIDENED to its range rather than joined. Joining units 3 and 5 would
    produce text that appears nowhere in the document -- the exact failure this design exists to prevent,
    committed by the platform instead of the model. Widening gives back something a reader can find, and
    says it widened."""
    nums = _cited_numbers(cited)
    if not nums:
        return {"quote": "", "units": [], "cited": nums, "reason": "no_line_citation",
                "note": "the reply cites no unit number, so there is nothing to cut. A record with no "
                        "citation has no evidence, and this path does not supply one for it."}
    if nums[0] < 1 or nums[-1] > len(units):
        return {"quote": "", "units": [], "cited": nums, "reason": "line_out_of_range",
                "note": f"unit(s) cited outside the {len(units)} this section has. NOT clamped to the "
                        f"nearest one: a clamped citation comes back as a confident quote of whatever "
                        f"happens to sit at the boundary, which is the expensive direction."}
    lo, hi = nums[0], nums[-1]
    if hi - lo + 1 > MAX_CITED_UNITS:
        return {"quote": "", "units": [], "cited": nums, "reason": "line_citation_too_wide",
                "note": f"the citation spans {hi - lo + 1} units; the cap is {MAX_CITED_UNITS}. A whole "
                        f"section is not a quote."}
    span = list(range(lo, hi + 1))
    quote = span_text[units[lo - 1]["start"]:units[hi - 1]["end"]].strip()
    if not quote:
        return {"quote": "", "units": span, "cited": nums, "reason": "cited_units_are_blank",
                "note": "the cited units hold no text. An empty string is a substring of every document, "
                        "so accepting it would pass a field with no evidence through the only check that "
                        "asks for any."}
    if source is not None and quote not in source:
        return {"quote": "", "units": span, "cited": nums, "reason": "cut_not_in_source",
                "note": "the cut is not a span of the source document. This is a fault in THIS module, not "
                        "in the reply -- the units and the text being cut do not belong together -- and it "
                        "is reported rather than repaired because it falsifies the construction this "
                        "path's quotes rest on."}
    note = f"cut by the platform from unit(s) {lo}-{hi} ({len(quote)} characters); verbatim by construction."
    if len(span) > len(nums):
        note += (f" The citation named {len(nums)} non-contiguous unit(s) and was WIDENED to the range "
                 f"{lo}-{hi}: joining {nums} directly would have produced text that appears nowhere in the "
                 f"document.")
    return {"quote": quote, "units": span, "cited": nums, "reason": "", "note": note}


# WHICH ROLES MUST CARRY THEIR VALUE IN THEIR OWN EVIDENCE. Exactly the roles whose value this module later
# resolves against a DECLARED VOCABULARY -- the `factor:` roles, whose levels go through `normalise_value`
# against a closed synonym table. For those, the value is a token the document either carries or does not.
#
# Everything else states its value in prose BY DESIGN. A `note` is the transcriber's sentence about the span;
# a `readout:` record has its channel pinned by the ROLE and uses the value to describe what is predicted;
# an `id` is a label. Asking prose to appear verbatim inside its own evidence asks the field to be something
# it is not.
#
# MEASURED, in two steps, and the first was wrong. Across two development reports 298 of 333 kept records
# reported "value not in the cited span" -- a 90% rate that was the instrument's fault. Excluding only
# `note` and `id` left 97 of 104 still reporting it, because `readout:` records were counted as levels while
# carrying sentences like "uncharged tRNA <2% during hardware dilution". The rule is not "exclude whatever
# scores badly"; it is that a value is checkable against its span exactly when the platform will later check
# it against a vocabulary. Both counts are always reported, so narrowing the population hides nothing.
def _is_level_role(role: str) -> bool:
    return str(role).startswith("factor:")


def _value_in_quote(value: str, quote: str) -> bool:
    """Whether the cited span actually carries the value, on a word boundary rather than a substring.

    This is the risk the construction DOES NOT remove. A quote can no longer be invented, so the remaining
    way to be wrong is to cite a real span for a record it does not support. It is counted, not refused: a
    claim may legitimately be stated in words that never repeat its level ("raised to the higher setpoint"),
    and refusing those would be a false rejection -- the direction this project treats as expensive."""
    v = re.sub(r"\s+", " ", str(value or "")).strip()
    if not v:
        return True
    return bool(re.search(r"(?<![\w.-])" + re.escape(v) + r"(?![\w.-])", quote, re.I))


def _agent_prompt(spans: list[dict]) -> tuple[str, str]:
    """The system prompt and the user message. Roles and prohibitions come from the declared tables."""
    roles = sorted(set(COLUMN_ROLES) | set(ROLE_IDENTIFIERS) | {f"readout:{c}" for c in adjudicate.channels()})
    must = "\n".join(f"  - {m}" for m in AGENT_PATH_CONTRACT["must"])
    may_not = "\n".join(f"  - {m}" for m in AGENT_PATH_CONTRACT["may_not"])
    system = (
        "You transcribe an outside research document into structured records. You are NOT asked to judge, "
        "improve, or complete it, and you are not the adjudicator of your own output -- a deterministic "
        "checker gates everything you return.\n\n"
        "YOU MUST:\n" + must + "\n\nYOU MAY NOT:\n" + may_not + "\n\n"
        "The text is given to you as NUMBERED UNITS, one per line, in the form `L0007| ...`. YOU DO NOT "
        "COPY ANY TEXT. For each record you name the unit numbers it is stated on and the platform cuts "
        "the quotation out of those units itself, so a quotation cannot be mistyped or reworded. Cite the "
        "FEWEST units that state the record.\n\n"
        "A record is JSON with: kind ('requirement' or 'claim'), role (one of the declared roles below), "
        "value, lines (a list of unit numbers, e.g. [7] or [7, 8]), section. A claim may also carry "
        "target, reference, direction ('up'/'down'/'change'), threshold_pct. For any field you leave "
        "empty, add it to an `unfilled` object mapping the field name to your reason in your own words, "
        "naming what the text said instead. A record whose `lines` are missing, outside the list, or more "
        f"than {MAX_CITED_UNITS} units wide is REJECTED, and so is an empty field with no reason -- "
        "neither is repaired. Any `quote` you write is IGNORED.\n\n"
        "DECLARED ROLES (use these exactly; do not invent one):\n  " + "\n  ".join(roles) + "\n\n"
        'Reply with JSON only: {"records": [ ... ]}'
    )
    body = "\n\n".join(f"### SECTION: {s['heading']}  [{s['kind']}]\n"
                        f"{numbered_body(s.get('units') or citable_units(s['text']))}" for s in spans)
    user = ("Transcribe the records stated in these sections. Cite unit numbers; do not copy text.\n\n"
            + body)
    return system, user


def _agent_spans(text: str) -> list[dict]:
    """Only the plan and claim spans, with their excluded descendants removed.

    The wet-lab sections never reach the model. A model shown a bench leg will faithfully extract a bench
    readout and the quote gate would PASS it, because the span is real -- so the exclusion has to happen
    before the model sees the text, not after it answers."""
    out = []
    loc = adjudicate.locate(text)
    if loc.get("error"):
        return out
    for sec in loc.get("sections", []):
        if sec["kind"] not in ("plan", "claim"):
            continue
        span = text[sec["read_span"][0]:sec["read_span"][1]]
        for child in loc.get("sections", []):
            if child["kind"] in ("validation_wetlab", "citation_context") and \
                    sec["start"] < child["start"] < sec["subtree_end"]:
                span = span.replace(text[child["start"]:child["subtree_end"]], "")
        body = span.strip()
        out.append({"heading": sec["heading"], "kind": sec["kind"], "text": body,
                    "units": citable_units(body)})
    return out


def _parse_agent_reply(raw: str) -> list[dict] | None:
    """The records a reply carries, or None when it cannot be read.

    None rather than [] on purpose: an unparseable reply means we could not look, and an empty list would
    report that as a document stating nothing."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-z]*\s*|\s*```$", "", s)
    try:
        obj = json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.S)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None
    recs = obj.get("records") if isinstance(obj, dict) else obj
    return recs if isinstance(recs, list) else None


# A budget big enough that the SDK demands streaming is a budget this path must not ask for. Found on the
# second live failure: a retry at a tripled budget raised "Streaming is required for operations that may
# take longer than 10 minutes." The retry now multiplies WITHIN this cap rather than past it.
AGENT_MAX_TOKENS_CAP = 12000


def _agent_one_span(cl, span: dict, mdl: str, temp, budget: int) -> dict:
    """One call for one section. Returns parsed records, or a per-span failure with its cause.

    ONE CALL PER SECTION, not per document, and both reasons came from live failures on a 60,073-character
    report. A single prompt carrying every span returned no text block at moderate budgets, and the retry
    tripped the SDK's streaming guard. A section is small enough to answer and to parse, keeps the quote
    gate on a span the model actually saw, and makes a failure LOCAL -- one unreadable section no longer
    costs the whole document, which is the difference between a partial result and none."""
    system, user = _agent_prompt([span])
    budget = min(budget, AGENT_MAX_TOKENS_CAP)

    def _ask(b):
        kw = {"model": mdl, "max_tokens": min(b, AGENT_MAX_TOKENS_CAP), "system": system,
              "messages": [{"role": "user", "content": user}]}
        if temp is not None:
            kw["temperature"] = temp
        m = cl.messages.create(**kw)
        return m, "".join(blk.text for blk in m.content if getattr(blk, "type", "") == "text")

    retried = False
    try:
        msg, raw = _ask(budget)
        # AN EMPTY REPLY IS NOT AN UNPARSEABLE ONE. Conflating them misattributes the cause: the first live
        # run reported "could not be parsed as JSON" for a reply that had no text block at all, which sends
        # a reader at the output format when the cause is the budget. It is also Appendix E item 4 in a new
        # call site -- a reply spending its cap before writing text -- fixed in the agent loop with one
        # retry at a higher cap, and not fixed here because this path was written without consulting it.
        if not raw.strip():
            retried = True
            msg, raw = _ask(budget * 3)
    except Exception as exc:
        return {"records": None, "retried": retried, "failure": {
            "section": span["heading"], "error": f"the extraction model could not be reached: {exc}",
            "reason": "runtime_fault", "about": "environment"}}
    if not raw.strip():
        return {"records": None, "retried": retried, "empty": True, "failure": {
            "section": span["heading"],
            "error": f"the extraction model returned no text block for this section "
                     f"(stop_reason={getattr(msg, 'stop_reason', None)!r}), twice",
            "reason": "runtime_fault", "about": "environment",
            "stop_reason": getattr(msg, "stop_reason", None),
            "block_types": [getattr(b, "type", "?") for b in msg.content]}}
    parsed = _parse_agent_reply(raw)
    if parsed is None:
        return {"records": None, "retried": retried, "unparseable": True, "raw_prefix": raw[:200],
                "failure": {"section": span["heading"],
                            "error": "the model's reply for this section could not be parsed as JSON",
                            "reason": "runtime_fault", "about": "environment"}}
    return {"records": parsed, "retried": retried}


def extract_agent(text: str, client=None, model: str | None = None,
                  max_tokens: int = 4000) -> dict:
    """The third extraction path: a language model, temperature from the seam, gated mechanically.

    One call per located section. Returns the kept records, the rejected ones with a reason each, the
    fields the model declined to fill with the reason it gave, and any per-span failures -- so a document
    whose sections partly failed comes back partial and SAYS it is partial, rather than as a smaller clean
    answer."""
    from . import errors
    if not isinstance(text, str) or not text.strip():
        return {"n_kept": 0, "n_rejected": 0, "kept": [], "rejected": [], "claims": [], "unfilled": [],
                "span_failures": [],
                **errors.fail("bad_argument", "extract_agent() needs the document text as a non-empty "
                                              f"string; got {type(text).__name__}.")}
    spans = _agent_spans(text)
    if not spans:
        return {"n_kept": 0, "n_rejected": 0, "kept": [], "rejected": [], "claims": [], "unfilled": [],
                "span_failures": [], "n_spans": 0,
                "note": "no plan or claim span was located, so there is nothing to transcribe. That is a "
                        "fact about the document's form, not about what it states."}
    mdl = model or AGENT_MODEL_DEFAULT
    temp = _temperature_for(mdl)
    try:
        cl = client if client is not None else _llm_client(max_retries=2)
    except Exception as exc:
        return {"n_kept": 0, "n_rejected": 0, "kept": [], "rejected": [], "claims": [], "unfilled": [],
                "span_failures": [], "n_spans": len(spans),
                **errors.fail("runtime_fault", f"no model client could be built: {exc}"),
                "about": "environment",
                "note": "This machine could not look. NOTHING about the document follows from it."}

    known_roles = (set(COLUMN_ROLES) | set(ROLE_IDENTIFIERS)
                   | {f"readout:{c}" for c in adjudicate.channels()} | {"readout"})
    parsed_all, failures, retried_any = [], [], False
    for si, span in enumerate(spans):
        got = _agent_one_span(cl, span, mdl, temp, max_tokens)
        retried_any = retried_any or got.get("retried", False)
        if got["records"] is None:
            failures.append(got["failure"])
            continue
        for item in got["records"]:
            if isinstance(item, dict):
                item.setdefault("section", span["heading"])
            # The span INDEX travels with the record. The quote is cut from the span the model was shown,
            # and cutting it from any other one is the `cut_not_in_source` fault.
            parsed_all.append((si, item))

    candidates, rejected, unfilled, claims = [], [], [], []
    n_rewrote = n_value_outside = n_level = n_free_text = n_free_text_para = 0
    for si, item in parsed_all:
        if not isinstance(item, dict):
            rejected.append({"record": str(item)[:120], "reason": "not_a_record", "quote": ""})
            continue
        role = str(item.get("role") or "")
        if role not in known_roles:
            # Rejected BEFORE the quote gate. A role outside the vocabulary can never be reconciled with
            # either mechanical path, so it would sit in `agent_only` for ever and read as a finding.
            rejected.append({**item, "reason": "undeclared_role"})
            continue
        why = item.get("unfilled") or {}
        blanks = [f for f in _AGENT_CLAIM_FIELDS if f in item and not str(item.get(f) or "").strip()]
        missing_reason = [f for f in blanks if not str(why.get(f) or "").strip()]
        if missing_reason:
            rejected.append({**item, "reason": "unfilled_without_reason", "fields": missing_reason})
            continue
        cut = cut_cited(spans[si]["text"], spans[si]["units"], item, source=text)
        if cut["reason"]:
            rejected.append({**item, "reason": cut["reason"], "cited": cut["cited"],
                             "quote": "", "note": cut["note"]})
            continue
        q = cut["quote"]
        offered = str(item.get("quote") or "").strip()
        if offered and offered not in q:
            # The W9 behaviour, still present and now inert. Counted rather than dropped: a design that
            # removes an opportunity should keep showing that the behaviour it removed is still there.
            n_rewrote += 1
        value = str(item.get("value") or "")
        supported = _value_in_quote(value, q)
        if _is_level_role(role):
            n_level += 1
            if not supported:
                n_value_outside += 1
        else:
            n_free_text += 1
            if not supported:
                # NOT an unsupported value -- a paraphrase is what this field is for. Counted because it is
                # where the rewriting went: the model no longer offers a reworded QUOTE, it offers a
                # reworded note beside a real one, and a reader can take the note for the document's words.
                n_free_text_para += 1
        for f, reason in why.items():
            unfilled.append({"field": f, "why": str(reason), "quote": q,
                             "section": str(item.get("section") or "")})
        candidates.append(Record(kind=str(item.get("kind") or "requirement"), role=role,
                                 value=value, quote=q,
                                 section=str(item.get("section") or ""), section_kind="plan",
                                 path="agent"))
        if str(item.get("kind")) == "claim":
            thr = item.get("threshold_pct")
            if q and q in text:
                claims.append(adjudicate.Claim(
                    quantity=str(item.get("value") or ""), target=str(item.get("target") or ""),
                    reference=str(item.get("reference") or ""), quote=q,
                    section=str(item.get("section") or ""), section_kind="claim",
                    direction=str(item.get("direction") or ""),
                    threshold_pct=(float(thr) if isinstance(thr, (int, float)) else None)))
    gated = verify_quotes(candidates, text)
    out = {"n_kept": gated["n_kept"], "n_rejected": gated["n_rejected"] + len(rejected),
           "kept": gated["kept"], "rejected": gated["rejected"] + rejected, "claims": claims,
           "unfilled": unfilled, "model": mdl, "n_spans": len(spans),
           "span_failures": failures, "retried_for_room": retried_any,
           "temperature_pinned": temp is not None, "temperature_sent": temp,
           "quotes_cut_by_platform": True, "n_rewrote": n_rewrote,
           "n_value_outside_quote": n_value_outside, "n_level_records": n_level,
           "n_free_text_records": n_free_text, "n_free_text_paraphrased": n_free_text_para}
    note = [f"{gated['n_kept']} record(s) kept, {gated['n_rejected'] + len(rejected)} rejected, over "
            f"{len(spans)} section(s). Rejections are NOT repaired: an unusable citation, an undeclared "
            f"role and a blank without a reason are each a record this path may not contribute. The model "
            f"never saw the wet-lab sections.",
            "Every quote was CUT BY THE PLATFORM out of the units the record cited, so a quote is verbatim "
            "by construction and the gate checks that construction rather than the model's compliance."]
    if n_rewrote:
        note.append(f"{n_rewrote} record(s) also supplied their own wording, and it was not the cited "
                    f"text: IGNORED, and counted. The behaviour that forced this design is still there; it "
                    f"can no longer reach the output.")
    if n_value_outside:
        note.append(f"{n_value_outside} of {n_level} LEVEL-bearing record(s) carry a value the cited span "
                    f"does not contain. Verbatim is not the same as relevant -- a real span can be cited "
                    f"for a record it does not support -- so this is counted and not refused: a claim may "
                    f"legitimately be stated in words that never repeat its level.")
    if n_free_text:
        note.append(f"{n_free_text} of {gated['n_kept']} kept record(s) state their value in prose "
                    f"(note / readout / id) rather than as a declared factor level, so the kept count is "
                    f"not a count of design facts; "
                    f"{n_free_text_para} of them state the span in the transcriber's "
                    f"own words, which is what the field is for and is NOT counted as an unsupported "
                    f"value -- but it is where the rewriting went, and a note beside a verbatim quote can "
                    f"be read as the document's words.")
    note.append("Sampling pinned at temperature 0, so a re-run is reproducible." if temp is not None else
                f"SAMPLING IS NOT PINNED: {mdl} refuses an explicit temperature, so this extraction is NOT "
                f"reproducible run to run. Two runs disagreeing is then a property of the sampler, not a "
                f"finding about the document.")
    if failures:
        note.append(f"PARTIAL: {len(failures)} of {len(spans)} section(s) could not be read "
                    f"(about: environment). The sections that did read are here; the ones that did not are "
                    f"in span_failures. A smaller clean-looking answer would hide them.")
    out["note"] = " ".join(note)
    if failures and not candidates:
        out.update(errors.fail("runtime_fault",
                               f"every one of {len(spans)} section(s) failed to read"))
        out["about"] = "environment"
    return out
