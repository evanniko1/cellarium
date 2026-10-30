"""The held-out set's completion criterion, pre-registered as a table and checked as a function.

ADJ-W2. Twelve of the forty-five Co-Scientist round-1 idea reports were sealed by SHA-256 on 2026-10-29,
before any extraction pattern existed, and they are ONE-SHOT: a set you have already looked at measures the
tool's fit to it rather than the tool. Sealing them was half the discipline. The missing half was saying what
"the tool is finished" means, because without it the moment to spend them gets chosen by whoever happens to
feel ready -- and with one annotator who has now read the development set five times, that feeling is the
least reliable instrument in the project.

WHAT THIS MODULE IS. The criterion, declared before the run, and `readiness()` so that "may the seal be
broken?" is answered by a comparison against a fixed table instead of by judgement at the moment of
greatest temptation. Four of the six gates ARE the open weakness items, which is the honest reading of
finished: the tool is finished when the things already known to be wrong with it are no longer wrong. A
criterion invented from scratch here would be a second chance to pick thresholds that today's numbers
happen to clear.

THE SMALLEST RULE DOES THE MOST WORK. A missing measurement is NOT a pass. A readiness check that defaults
to yes when nothing objects would wave through a tool nobody measured, which is the silent-absence shape
this project keeps finding, pointed at its own process.

NOT A TOOL. This is not on the agent tool surface and should not be: the tool surface answers questions
about the corpus and the model, and whether a project may spend its own held-out set is a question about the
project. An agent that could open the seal by calling a tool is an agent that can end the only measurement
here that nobody gets to repeat.
"""

from __future__ import annotations

import hashlib
import io
import json
import os

# How a gate may state its threshold. Declared, so a gate cannot arrive with a comparison nobody wrote.
COMPARISONS = ("==", ">=", "<=", "is", "in", "nonempty")

# The seal itself. Local only -- the archive is Co-Scientist output and is not ours to publish -- so this
# module must behave correctly on machines that cannot see it.
DEFAULT_SEAL_PATH = os.path.join("kinetic_port", "coscientist", "HOLDOUT.json")

PREREGISTRATION = {
    "archive": "Google Co-Scientist round-1 idea reports for the kinetic-port goal",
    "frozen_at": "2026-10-29",
    "selection_rule": "sorted by filename, every 4th idea report",
    "n_reports_total": 45,
    "n_held_out": 12,
    "n_development": 33,
    # A file in no category is the one that quietly gets used for development. Found by diffing the seal
    # against the directory: 48 .md files on disk, 45 in the seal. The three extras are the archive's own
    # summary files, not idea reports, and one of them is the largest file in the directory (286 KB) -- so a
    # measurement that globbed *.md and subtracted the held-out twelve would have silently read 36 reports
    # and called them the development set.
    "in_neither_set": ("knowledge_base_report.md", "run_spec_report.md", "summary_report.md"),
    "what_the_run_measures": "how well the extraction and adjudication pipeline reads documents it was not "
                             "developed against -- not whether the hypotheses in them are any good, and "
                             "not whether the simulations they ask for would succeed",
    "registered_by": "this file, frozen by its own git history. The gate list that governs a run is the "
                     "version at the commit PRECEDING it, which is why the run must be a separate commit "
                     "from any change to this table.",
}

# Each gate: what it asks, the measurement that answers it, the threshold, which open weakness it closes,
# and why it belongs here at all.
READINESS_GATES = (
    {
        "id": "G1_INDEPENDENT_CHECK",
        "weakness": "ADJ-W1",
        "asks": "Does anything in the pipeline check anything else?",
        "measure": "agent_vs_structural_comparison_kind",
        "requires": ("in", ("redundant", "partial")),
        "source": "extraction.extract_report(text, agent_client=...)"
                  "['agent_vs_structural']['agreement']['comparison_kind'], over the development set",
        "why": "The two mechanical paths turned out COMPLEMENTARY -- role overlap about zero, Jaccard "
               "0.004, 30 of 33 reports agreeing on nothing -- so their agreement checked nothing about "
               "either. Dual extraction's whole value is two independent readings of ONE quantity. Until "
               "two paths read the same fields, every field in this pipeline has a provenance and no "
               "check, and a held-out run would report numbers nothing had verified.",
    },
    {
        "id": "G2_ROLE_OVERLAP",
        "weakness": "ADJ-W1",
        "asks": "Do the two compared paths actually cover the same roles?",
        "measure": "agent_vs_structural_role_overlap",
        "requires": (">=", 0.5),
        "source": "extraction.extract_report(text, agent_client=...)"
                  "['agent_vs_structural']['agreement']['role_overlap'], over the development set",
        "why": "`comparison_kind` can read `partial` on a thin overlap. Half the roles shared is the "
               "weakest overlap on which an agreement rate means anything; below it, agreement is a "
               "statement about a handful of fields being reported as if it were about the pipeline.",
    },
    {
        "id": "G3_QUOTES_VERBATIM",
        "weakness": "ADJ-W9",
        "asks": "Is every kept record's quote a verbatim span of its own document?",
        "measure": "quote_verbatim_rate",
        "requires": ("==", 1.0),
        "source": "the share of extraction.extract_agent(...)['kept'] records whose quote is a substring "
                  "of its own document; extraction.verify_quotes is the same check at the boundary",
        "why": "Rule R1 of the hypothesis hand-off, and the only check in the pipeline that asks for "
               "evidence at all. The first live agent run proposed 10 records and fabricated 10 quotes, "
               "which is why quotes are now CUT BY THE PLATFORM from cited units rather than copied. The "
               "rate is 1.0 by construction, so this gate is a check on the construction: anything below "
               "1.0 means the construction is broken and the number would be the finding.",
    },
    {
        "id": "G4_PARTIALITY_TRAVELS",
        "weakness": "ADJ-W8",
        "asks": "Can a summary report a count over a document it only partly read, without saying so?",
        "measure": "summaries_carry_partial_flag",
        "requires": ("is", True),
        "source": "whether adjudicate.cost_summary / extraction.cost_breakdown / "
                  "extraction.row_cost_summary can still be called over a partial reading WITHOUT saying "
                  "so. They accept `partial` and append PARTIAL_NOTE when told; all three default to "
                  "False, so today the answer is no and this gate is unmet.",
        "why": "Per-section calling means a document can come back with sections unread. A cost table over "
               "a partial extraction UNDER-COUNTS, and an under-count that looks clean is worse on a "
               "held-out set than anywhere else, because there is no second run to catch it.",
    },
    {
        "id": "G5_MAPPINGS_REVIEWED",
        "weakness": "ADJ-W5",
        "asks": "Has anyone other than the author checked which declared member each value maps to?",
        "measure": "applied_mappings_signed_off_by",
        "requires": ("nonempty", ""),
        "source": "a name and a date, recorded by whoever reviewed "
                  "extraction.normalisation_coverage(records)['applied_mappings'] over the development "
                  "set. Not the author of the mapping table.",
        "why": "Membership is checked at call time; WHICH member is right is a judgement no check makes, "
               "and a round-trip through the envelope validates the design rather than the mapping. "
               "`applied_mappings` lists every mapping that fired so the judgement can be reviewed. One "
               "annotator reviewing his own mapping table is not a review -- the field records who.",
    },
    {
        "id": "G6_SCORING_IS_MECHANICAL",
        "not_a_weakness_because": "it is the mitigation for the single-annotator limitation rather than a "
                                  "defect found in the code",
        "asks": "Is every number in the held-out result produced by committed, tested code?",
        "measure": "score_produced_by_committed_code",
        "requires": ("is", True),
        "source": "whether a committed, tested script computes every number the held-out report will "
                  "carry. None exists yet, so this gate is unmet; a number computed by hand at the time "
                  "of the run is the thing it exists to forbid.",
        "why": "The literature on single extraction is blunt: error rates up to 50-63% in reviews of the "
               "practice, single extraction about 22% worse than double, single screeners missing a median "
               "5% of studies. There is one annotator here and he has read the development set five times, "
               "which cannot be undone. What can be done is to keep his reading out of the score, so the "
               "held-out numbers come from code that existed BEFORE the seal was broken and not from "
               "anybody's reading of twelve reports.",
    },
)

# Numbers with no defensible threshold yet. Not having a threshold is not the same as not having to report
# it, and an unreported number is how a known weakness disappears from a result.
#
# AT READINESS TIME these are supplied as the DEVELOPMENT-set value. The held-out value cannot exist before
# the run, so what the gate is asking is whether the instrument that produces the number exists and produces
# one -- a result that omits a number because nothing could compute it is the same omission either way.
MUST_REPORT = (
    {
        "id": "M1_VALUE_OUTSIDE_QUOTE_RATE",
        "measure": "value_outside_quote_rate",
        "source": "extract_agent(...)['n_value_outside_quote'] / ['n_level_records']",
        "asks": "How often is a real span cited for a record it does not support?",
        "why": "What the platform-cut quote does NOT buy. Verbatim is not relevant, and nobody has a "
               "principled threshold for this yet -- a claim may legitimately be stated in words that "
               "never repeat its level. Reported, so the construction guarantee is not read as a guarantee "
               "of relevance.",
    },
    {
        "id": "M2_UNRESOLVED_REQUIREMENT_RATE",
        "measure": "unresolved_requirement_rate",
        "source": "extraction.cost_breakdown(records)['by_cost']['unresolved'] over the total",
        "asks": "What share of extracted requirements cannot be costed at all?",
        "why": "79.8% of structural requirements came back `unresolved` on the development set before "
               "normalisation. Whatever it is on the held-out set is the number a reader needs to size "
               "every other number in the result.",
    },
    {
        "id": "M3_SPAN_FAILURE_RATE",
        "measure": "span_failure_rate",
        "source": "len(extract_agent(...)['span_failures']) / ['n_spans']",
        "asks": "What share of located sections could not be read at all?",
        "why": "An environment fault, not a corpus fact -- but one that shrinks every count in the run. A "
               "result over 80% of the sections is not a result over the documents.",
    },
)

OUTCOME_RULES = {
    "one_shot": "The seal is broken ONCE. A second run on the same twelve measures the tool's fit to a set "
                "it has now seen, which is the thing holding them back was for.",
    "report_whatever_it_says": "The result is reported as it comes out. A failure is a finding about the "
                               "tool, not a reason to revisit the gates -- the gates were the claim that "
                               "the tool was ready, and a failed run falsifies that claim.",
    "no_widening_after_the_result": "No gate, threshold, declared vocabulary, synonym table or mapping may "
                                    "be added or widened after the seal is broken. A field the tool cannot "
                                    "transcribe is COUNTED, exactly as on the development set.",
    "never_used_for_development_again": "After the run the twelve are spent. They do not become "
                                        "development data, because every pattern fitted to them afterwards "
                                        "would be fitted to the only documents left that could have "
                                        "tested it.",
    "separate_commit": "The run is its own commit, and the commit preceding it is the version of this file "
                       "that governed it. A registration edited in the same change as the run it governs "
                       "registers nothing.",
}

LIMITATIONS = {
    "single_annotator": "One person built the locator, the vocabularies and the mappings, and has read the "
                        "development set five times. There is no second extractor to compare against, and "
                        "the literature puts single extraction at up to 50-63% error and about 22% worse "
                        "than double.",
    "mitigation_mechanical_scoring": "Every held-out number is produced by committed, tested code (gate "
                                     "G6_SCORING_IS_MECHANICAL), so the annotator's familiarity with the "
                                     "development set cannot reach the score through his reading of the "
                                     "twelve.",
    "mitigation_two_paths": "Where two paths read the same field the record has two provenances. That is "
                            "what gate G1_INDEPENDENT_CHECK exists to establish BEFORE the run, because "
                            "a pipeline with one reading per field has no internal check at all.",
    "n_is_twelve": "Twelve documents is a small set. A rate measured on it carries an interval wide enough "
                   "that only a large difference from the development set means anything, and the result "
                   "should be read as a sanity check on generalisation rather than as an estimate.",
}

OUT_OF_SCOPE = {
    "ADJ-W3_elongation_model_unstated": "The elongation model is unstated in 394 of 394 development rows. "
                                        "No pattern fixes that; the next round's goal text has to ask for "
                                        "it. The held-out run cannot settle it and must not be read as "
                                        "having tried.",
    "ADJ-W6_setpoints_not_built": "The archive asks for charging setpoints 0.70 and 0.75 in 110 "
                                  "development rows; the campaign builds none/0.55/0.85. That is a "
                                  "mismatch between two plans, not an extraction defect.",
    "hypothesis_quality": "Whether the ideas in these reports are good science is not what the seal "
                          "measures. The run measures reading.",
}


def _meets(requires, value) -> tuple[bool, str]:
    """Whether a measurement meets a gate, or why it cannot be compared at all.

    THE WRONG KIND IS NOT A FAILURE AND NOT A PASS. "0.9" is not 0.9, and a comparison that coerced it
    would let a string clear a numeric threshold. An uncomparable value is UNMEASURED: the honest report is
    that nothing was established, not that the gate was failed by a value nobody could read."""
    op, want = requires
    if op in ("==", ">=", "<="):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, (f"{value!r} is not a number, and a numeric threshold does not coerce one -- "
                           f"the measurement is missing rather than failed")
        return ({"==": value == want, ">=": value >= want, "<=": value <= want}[op], "")
    if op == "is":
        if not isinstance(value, bool):
            return False, f"{value!r} is not a boolean, and this gate asks a yes/no question"
        return value is want, ""
    if op == "in":
        return value in want, ""
    if op == "nonempty":
        return bool(str(value or "").strip()), ""
    return False, f"unknown comparison {op!r}; the declared set is {COMPARISONS}"


def _card(item: dict) -> dict:
    return {k: item[k] for k in ("id", "asks", "measure") if k in item}


def readiness(measurements: dict | None = None) -> dict:
    """May the seal be broken? Answered against the declared table, never by judgement.

    Returns the gates met, the gates failed, and the gates NOTHING WAS MEASURED FOR -- three categories,
    deliberately, because collapsing the third into either of the others is how a tool nobody measured
    gets called ready."""
    m = measurements if isinstance(measurements, dict) else {}
    met, unmet, unmeasured, reported = [], [], [], []
    for g in READINESS_GATES:
        if g["measure"] not in m:
            unmeasured.append({**_card(g), "why_unmeasured": "no measurement was supplied for it"})
            continue
        ok, problem = _meets(g["requires"], m[g["measure"]])
        if problem:
            unmeasured.append({**_card(g), "why_unmeasured": problem, "value": m[g["measure"]]})
        elif ok:
            met.append({**_card(g), "value": m[g["measure"]]})
        else:
            unmet.append({**_card(g), "value": m[g["measure"]], "requires": list(g["requires"]),
                          "weakness": g.get("weakness", "")})
    for r in MUST_REPORT:
        if r["measure"] not in m:
            unmeasured.append({**_card(r), "why_unmeasured": "it has no threshold, but it still has to be "
                                                             "reported with the result"})
        else:
            reported.append({**_card(r), "value": m[r["measure"]]})
    may = not unmet and not unmeasured
    note = [f"{len(met)} of {len(READINESS_GATES)} gate(s) met, {len(unmet)} failed, "
            f"{len(unmeasured)} with nothing measured."]
    note.append("A MISSING MEASUREMENT IS NOT A PASS: a readiness check that defaulted to yes would wave "
                "through a tool nobody measured, which is the silent-absence shape applied to this "
                "project's own process.")
    if may:
        note.append("The seal may be broken, ONCE, in its own commit. The gate list that governs the run "
                    "is the version of this file at the commit preceding it.")
    else:
        note.append("The seal stays closed. The held-out twelve are the only documents left that can test "
                    "this pipeline, and spending them early cannot be undone.")
    return {"may_break_seal": may, "n_gates": len(READINESS_GATES), "met": met, "unmet": unmet,
            "unmeasured": unmeasured, "reported": reported, "note": " ".join(note)}


def seal_state(path: str | None = None) -> dict:
    """What the seal file on THIS machine says, or the fact that this machine cannot see it.

    The archive is local only, so most machines running this cannot read the seal. "I could not find the
    seal" reported as "there is no seal" is the bug class this project keeps finding, so an unreadable file
    returns `sealed: None` and `about: environment` -- unknown, not negative."""
    p = path or os.environ.get("CELLARIUM_HOLDOUT_SEAL") or DEFAULT_SEAL_PATH
    try:
        raw = io.open(p, "rb").read()
    except OSError as exc:
        return {"sealed": None, "about": "environment", "path": p,
                "note": f"the seal file could not be read at {p} ({exc.__class__.__name__}). This machine "
                        f"could not look; NOTHING about whether the held-out set is sealed follows from "
                        f"it. The archive is local only by design."}
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return {"sealed": None, "about": "environment", "path": p,
                "digest": hashlib.sha256(raw).hexdigest(),
                "note": f"the seal file at {p} is present but could not be parsed ({exc}). Present and "
                        f"unreadable is not the same as absent, and neither is the same as unsealed."}
    n_held = len(obj.get("held_out") or {})
    n_dev = len(obj.get("development") or {})
    disagrees = []
    for key, counted in (("n_held_out", n_held), ("n_development", n_dev)):
        if obj.get(key) != counted:
            disagrees.append(f"the file says {key}={obj.get(key)!r} and lists {counted}")
        if PREREGISTRATION[key] != counted:
            disagrees.append(f"the registration says {key}={PREREGISTRATION[key]} and the file lists "
                             f"{counted}")
    if obj.get("frozen_at") != PREREGISTRATION["frozen_at"]:
        disagrees.append(f"the file was frozen at {obj.get('frozen_at')!r}, the registration says "
                         f"{PREREGISTRATION['frozen_at']!r}")
    return {"sealed": True, "about": "", "path": p, "digest": hashlib.sha256(raw).hexdigest(),
            "frozen_at": obj.get("frozen_at", ""), "n_held_out": n_held, "n_development": n_dev,
            "disagrees_with_registration": disagrees,
            "note": ("the seal is present and agrees with the registration." if not disagrees else
                     "the seal is present and DISAGREES with the registration: " + "; ".join(disagrees) +
                     ". Reported, not reconciled -- a registration edited to match a file it was supposed "
                     "to govern governs nothing.")}
