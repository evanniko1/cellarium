"""Every number the held-out report will carry, computed by committed code.

GATE G6_SCORING_IS_MECHANICAL, which is the mitigation for this project's single-annotator limitation
rather than a defect found in the code. One person built the locator, the vocabularies and the mappings and
has read the development set five times; that cannot be undone. What can be done is to keep his reading out
of the score, so the held-out numbers come from code that existed BEFORE the seal was broken instead of
from anybody's reading of twelve reports. A number computed at the console on the day of the run is the
thing this gate exists to forbid.

WHAT FORCED THIS MODULE, and it is not hypothetical. The development numbers were assembled by scratchpad
scripts, and auditing them against their own declared sources found three defects that a committed scorer
makes impossible:

  * `unresolved_requirement_rate` (M2) was the LITERAL 0.798, carried unchanged across runs with the
    comment "development set, before normalisation". Nothing recomputed it after W10 or W11 changed what
    normalises. Computed here from its declared source it is 0.633 -- 16 points away, and the old value was
    reported as the current measurement.
  * `level_refusal_rate` (M4) was computed with a denominator the registration does not declare:
    `rejected / (rejected + derived + unverified)` rather than the registered
    `rejected / (rejected + n_level_records)`. Those differ, because 73 of 1,378 kept level records are
    neither derived nor unverified. 0.524 reported, 0.510 declared.
  * `agent_vs_structural_comparison_kind` (G1) is registered with a SCALAR comparison and a source that is
    a distribution over reports. "18 of the 21 eligible reports are partial" was turned into the single
    value `partial` by a judgement at the console. The rule is now written down, below, with the
    alternative it was chosen over and the fact that the numbers were already known when it was chosen.

WHAT THIS MODULE DOES NOT DO. It does not decide whether the seal may be broken -- `holdout.readiness`
does, against its own table. It does not supply a measurement it cannot compute: G5 needs a reviewer's
name, so `score` takes one and refuses to invent it, and an absent measurement reaches `readiness` as
absent, where it is reported as unmeasured rather than as a pass.

THE AGGREGATION RULES ARE PART OF THE REGISTRATION. A rate over twelve documents is not defined until
somebody says whether it is a mean of per-report rates or a ratio of pooled counts, and the two differ.
Each rule below states which, why, and -- where the rule was written after the development numbers were
already seen -- that it was, because a rule chosen with the answer in view is a weaker instrument and
hiding that is how a retune passes for a registration.
"""

from __future__ import annotations

import hashlib
import inspect
import io
import json
import os

from . import adjudicate, extraction, holdout

# Which per-report quantity feeds each declared measurement, and how the per-report values become the one
# number a gate is compared against. `aggregate` is the rule; `why` is why that rule and not the other one.
#
# POOLED vs MEAN, stated once because it decides half these numbers. A POOLED ratio (sum of numerators over
# sum of denominators) answers "of all the records, what share"; a MEAN of per-report rates answers "in a
# typical document, what share", and weights a report with three records equally with one that has two
# hundred. Rates over RECORDS are pooled here. The two role-axis gates are means, because their question is
# per-document by construction -- whether the two readings of THIS document covered the same fields.
MEASURE_RULES = {
    "agent_vs_structural_comparison_kind": {
        "gate": "G1_INDEPENDENT_CHECK",
        "per_report": "extract_report(...)['agent_vs_structural']['agreement']['comparison_kind']",
        "eligible": "reports where BOTH paths produced at least one record",
        "aggregate": "modal kind over the eligible reports",
        "why": "The gate asks whether anything in the pipeline checks anything else -- a property of the "
               "pipeline, so the typical eligible document is what answers it. A report whose table "
               "reading finds nothing has nothing to check and is excluded rather than counted as "
               "disagreement, which is the denominator the registration already states.",
        "chosen_after_seeing_the_numbers": True,
        "the_alternative_it_was_chosen_over": "ALL eligible reports must be partial or redundant. On the "
            "development set that rule reads `complementary` and G1 does NOT pass: 3 of the 21 eligible "
            "reports share no role between the two readings, so on those three the agreement checks "
            "nothing. Both numbers are reported by `score_rows` -- `comparison_kind_all_eligible` is the "
            "strict rule's answer -- so a reader can apply either and see that they differ. The modal rule "
            "is the one the gate consumes, and it was chosen with 18/21 already in view.",
    },
    "agent_vs_structural_role_overlap": {
        "gate": "G2_ROLE_OVERLAP",
        "per_report": "...['agreement']['role_overlap']",
        "eligible": "all reports, which is what 'over the development set' in the registration means",
        "aggregate": "mean of the per-report values",
        "why": "A Jaccard over role SETS is defined per document. Pooling the role sets across reports "
               "would compute a different quantity -- and a MUCH more forgiving one, because the union "
               "stops growing once every role has appeared somewhere. THAT MATTERS HERE: G2 is a FAILED "
               "gate (mean 0.161 against a 0.5 threshold), and pooling would raise it toward passing. "
               "Switching a failed gate's aggregation after seeing it fail is retuning it under another "
               "name, so the rule is fixed as the one it failed under.",
        "chosen_after_seeing_the_numbers": True,
        "the_alternative_it_was_chosen_over": "pooled role sets over the whole corpus, REFUSED for the "
                                              "reason above rather than evaluated.",
    },
    "agent_covers_structural_roles": {
        "gate": "G2B_STRUCTURAL_COVERAGE",
        "per_report": "|roles(structural) & roles(agent)| / |roles(structural)|",
        "eligible": "reports with a non-empty structural reading, as registered",
        "aggregate": "mean of the per-report values",
        "why": "Same per-document question as G2, in the form G2's own arithmetic does not cap. The "
               "eligibility rule is not a choice: the ratio has no denominator on a report whose table "
               "reading found nothing, and filling that in as 0 or as 1 would both be inventions.",
        "chosen_after_seeing_the_numbers": True,
        "the_alternative_it_was_chosen_over": "none -- the registration states this aggregation and this "
                                              "denominator in its own `source` field.",
    },
    "quote_verbatim_rate": {
        "gate": "G3_QUOTES_VERBATIM",
        "per_report": "share of kept records whose quote is a substring of ITS OWN document",
        "eligible": "all reports with at least one kept record",
        "aggregate": "pooled: verbatim records over checked records",
        "why": "The gate says EVERY kept record, so the denominator is records and not documents. The "
               "check is re-run here against the document text rather than taken from the path that "
               "produced the records: the rate is 1.0 by construction, so a scorer that trusted the "
               "construction would report the construction instead of checking it.",
        "chosen_after_seeing_the_numbers": False,
    },
    "levels_derived_by_platform": {
        "gate": "G7_LEVELS_DERIVED",
        "per_report": "extract_report(...)['agent']['levels_derived_by_platform']",
        "eligible": "all reports",
        "aggregate": "all() -- one report that accepted a level from the model falsifies the claim",
        "why": "A yes/no about the construction, not a rate. Any aggregation but `all` would let a "
               "document whose levels were taken from the reply disappear into a majority.",
        "chosen_after_seeing_the_numbers": False,
    },
    "extraction_temperature_pinned": {
        "gate": "G8_SAMPLING_PINNED",
        "per_report": "extract_agent(...)['temperature_pinned']",
        "eligible": "all reports",
        "aggregate": "all() -- the same reasoning as G7",
        "why": "The model is overridable, and `temperature_pinned` only REPORTS the unpinned case. On a "
               "one-shot run the report is the only artefact there will ever be.",
        "chosen_after_seeing_the_numbers": False,
    },
    "summaries_carry_partial_flag": {
        "gate": "G4_PARTIALITY_TRAVELS",
        "per_report": "NOT PER REPORT: a property of the code, read by inspecting the signatures of "
                      "adjudicate.COMPLETENESS_AWARE",
        "eligible": "not applicable",
        "aggregate": "all five declared summaries take `partial` and default it to None",
        "why": "G4 asks whether a summary CAN be called over a partial reading without saying so. That is "
               "answered by the code, and a held-out run cannot establish it: twelve documents that all "
               "happened to be read completely would answer nothing.",
        "chosen_after_seeing_the_numbers": False,
    },
    "value_outside_quote_rate": {
        "must_report": "M1_VALUE_OUTSIDE_QUOTE_RATE",
        "per_report": "n_value_outside_quote / n_level_records",
        "eligible": "all reports with at least one level record",
        "aggregate": "pooled",
        "why": "A rate over LEVEL RECORDS, so it is pooled: a report with ninety level records and a report with one are not two equal votes on whether a level is evidenced by its own span. The mean of the per-report rates would make them so, and the small reports are the ones whose rates swing.",
        "chosen_after_seeing_the_numbers": False,
    },
    "unresolved_requirement_rate": {
        "must_report": "M2_UNRESOLVED_REQUIREMENT_RATE",
        "per_report": "cost_breakdown(structural records)['by_cost']['unresolved'] / ['n_distinct']",
        "eligible": "reports with at least one distinct structural demand",
        "aggregate": "pooled",
        "why": "WHICH PATH'S RECORDS was not stated by the registration and had to be decided: the TABLE "
               "reading's, because the cost table an operator reads is the one over declared design rows, "
               "and every unresolved-rate this project has reported was over that path. The model path's "
               "rate is computed too and reported beside it (`unresolved_requirement_rate_agent_path`), "
               "because it is four times as high and omitting it would make the costing look sharper than "
               "it is. `cost_breakdown` counts DISTINCT demands per report, so the pooled ratio sums "
               "per-report counts rather than deduplicating across documents -- two reports asking for "
               "the same thing are two demands on the platform.",
        "chosen_after_seeing_the_numbers": True,
        "the_alternative_it_was_chosen_over": "the agent path, or the two pooled together. Reported "
                                              "separately instead, because they differ by a factor of "
                                              "four and a pooled figure would hide which path it came "
                                              "from.",
    },
    "span_failure_rate": {
        "must_report": "M3_SPAN_FAILURE_RATE",
        "per_report": "len(span_failures) / n_spans",
        "eligible": "all reports with at least one located span",
        "aggregate": "pooled",
        "why": "A rate over SECTIONS, pooled for the same reason as M1: a document with one located section would otherwise contribute a 0 or a 1 that weighs as much as a document with thirty. This is the number that says how much of the corpus was read at all, so its denominator has to be the sections.",
        "chosen_after_seeing_the_numbers": False,
    },
    "level_refusal_rate": {
        "must_report": "M4_LEVEL_REFUSAL_RATE",
        "per_report": "n_level_rejected / (n_level_rejected + n_level_records)",
        "eligible": "all reports that produced at least one level record or rejection",
        "aggregate": "pooled",
        "why": "THE DENOMINATOR IS THE REGISTERED ONE, and it is not the one the development number was "
               "computed with. `n_level_records` counts kept level records; `derived + unverified` is a "
               "SUBSET of them -- 1,305 of 1,378 on the development set, because a record whose supplied "
               "value already is the declared level is kept without being either. The scratchpad script "
               "used the subset and reported 0.524; the registered formula gives 0.510.",
        "chosen_after_seeing_the_numbers": False,
    },
    "model_level_disagreement_rate": {
        "must_report": "M5_MODEL_LEVEL_DISAGREEMENT_RATE",
        "per_report": "n_model_value_differed / n_level_derived",
        "eligible": "all reports with at least one derived level",
        "aggregate": "pooled",
        "why": "Pooled over derived levels, which are the only population where the model's value and the "
               "platform's can be compared at all.",
        "chosen_after_seeing_the_numbers": False,
    },
}

# Declared measurements this module CANNOT produce from the reports, each with why. Declared rather than
# left out: a measure that is simply absent from `MEASURE_RULES` is a HOLE, and `coverage` fails on it. The
# difference between "no code computes this" and "no code could" is the whole content of gate G6.
NOT_FROM_THE_REPORTS = {
    "applied_mappings_signed_off_by": "a person's name and a date. Gate G5 asks whether somebody OTHER "
                                      "than the author checked which declared member each value maps to; "
                                      "code cannot answer that, and code that filled it in would be the "
                                      "defect. `score` takes it as an argument and passes it through "
                                      "unchanged -- empty if nobody has reviewed the list, which reaches "
                                      "`readiness` as a failed gate.",
    "score_produced_by_committed_code": "gate G6 itself, which is what this module is for. It cannot be "
                                        "asserted from the reports: it is answered by `coverage`, which "
                                        "checks that every OTHER declared measurement is either computed "
                                        "here or named above. A module that scored its own existence "
                                        "would always pass.",
}


# A row with every field a scored row can carry, used to check that the arithmetic for each rule actually
# EXISTS. Found by attacking `coverage`: it compared the registration against `MEASURE_RULES`, which is a
# table of PROSE, so a rule entry added without the code behind it passed the gate while the number never
# appeared in any result. The specimen is deliberately small and deliberately not a real report -- it tests
# that each number comes out at all, not what it comes out as.
SPECIMEN_ROW = {
    "report": "specimen", "n_chars": 100, "digest": "",
    "structural": [{"kind": "requirement", "role": "factor:ppgpp_module", "value": "on",
                    "path": "structural", "section": "Plan", "quote_sha": "aa"}],
    "agent": [{"kind": "requirement", "role": "factor:ppgpp_module", "value": "on",
               "path": "agent", "section": "Plan", "quote_sha": "bb"}],
    "roles_structural": ["factor:ppgpp_module"],
    "roles_agent": ["factor:ppgpp_module", "readout:growth_rate"],
    "comparison_kind": "partial", "role_overlap": 0.5,
    "agent_counts": {"n_spans": 4, "n_level_records": 3, "n_level_derived": 2, "n_level_rejected": 1,
                     "n_level_unverified": 1, "n_model_value_differed": 1, "n_value_outside_quote": 1,
                     "levels_derived_by_platform": True, "temperature_pinned": True},
    "n_span_failures": 1, "n_quote_checked": 2, "n_quote_verbatim": 2,
}


def declared_measures() -> set:
    """Every measurement name the registration will ask for, read from the registration rather than listed.

    Read, not copied: a gate added to `holdout.READINESS_GATES` next month must make `coverage` fail until
    somebody teaches this module to compute it. A hard-coded list here would silently keep passing."""
    return ({g["measure"] for g in holdout.READINESS_GATES}
            | {r["measure"] for r in holdout.MUST_REPORT})


def coverage() -> dict:
    """Is every number the held-out report will carry produced by committed code? Gate G6's measurement.

    THE CHECK HAS TO BE ABLE TO FAIL. It fails in two directions: a declared measure that nothing here
    computes and nothing above excuses is `uncovered`, and a rule here for a measure the registration no
    longer declares is `stale`. The first is the real risk -- a new gate whose number gets computed by hand
    on the day -- and a test adds a fake gate to force exactly that."""
    declared = declared_measures()
    rules, excused = set(MEASURE_RULES), set(NOT_FROM_THE_REPORTS)
    both = sorted(rules & excused)
    uncovered = sorted(declared - rules - excused)
    stale = sorted((rules | excused) - declared)
    # THE RULE IS PROSE; THE NUMBER IS CODE. Scoring the specimen is what tells the two apart.
    produced = set((score_rows([SPECIMEN_ROW]).get("measurements") or {}))
    unimplemented = sorted((rules & declared) - produced)
    ok = not uncovered and not both and not stale and not unimplemented
    return {
        "score_produced_by_committed_code": ok,
        "n_declared": len(declared),
        "computed_here": sorted(rules & declared),
        "not_from_the_reports": sorted(excused & declared),
        "uncovered": uncovered,
        "claimed_both_ways": both,
        "stale_rules": stale,
        "declared_but_not_produced": unimplemented,
        "note": ("every declared measurement is either computed by this module -- demonstrated by scoring "
                 "SPECIMEN_ROW, not by the rule table saying so -- or named as one no code could produce."
                 if ok else
                 "G6 IS NOT MET. " + "; ".join(filter(None, [
                     f"nothing here computes {uncovered}" if uncovered else "",
                     f"{both} is both computed and excused, so which one governs is undefined" if both
                     else "",
                     f"{stale} has a rule here but is no longer declared" if stale else "",
                     f"{unimplemented} has a RULE here but produced no number for the specimen row, so "
                     f"the rule is prose with nothing behind it" if unimplemented else ""]))),
    }


def verbatim_counts(records, text: str) -> dict:
    """How many kept records carry a quote that really is a span of THIS document.

    Separate from the extraction on purpose. `verify_quotes` runs inside every path, so asking the path
    whether its own output passed the path's own gate establishes nothing; this re-cuts the question from
    the source text. An EMPTY quote is counted as not verbatim rather than skipped -- the empty string is a
    substring of everything, which is how a blank would otherwise score as evidence."""
    n = v = 0
    for r in records or []:
        n += 1
        q = getattr(r, "quote", None)
        if q is None and isinstance(r, dict):
            q = r.get("quote")
        q = str(q or "")
        v += int(bool(q.strip()) and q in text)
    return {"n_checked": n, "n_verbatim": v}


def _summaries_carry_partial_flag() -> dict:
    """G4, read off the code. The same walk the test does: every declared summary takes `partial` and
    defaults it to None, and nothing in either module defaults it to False again."""
    mods = {"extraction": extraction, "adjudicate": adjudicate}
    problems = []
    for name in adjudicate.COMPLETENESS_AWARE:
        mod, fn = name.split(".")
        p = inspect.signature(getattr(mods[mod], fn)).parameters.get("partial")
        if p is None:
            problems.append(f"{name} does not take `partial`")
        elif p.default is not None:
            problems.append(f"{name} defaults `partial` to {p.default!r}")
    for mod in mods.values():
        for fname, fn in vars(mod).items():
            if not inspect.isfunction(fn) or fn.__module__ != mod.__name__:
                continue
            p = inspect.signature(fn).parameters.get("partial")
            if p is None or p.default is inspect.Parameter.empty:
                continue
            if p.default is False:
                problems.append(f"{mod.__name__}.{fname} defaults `partial` to False")
    return {"value": not problems, "problems": problems,
            "n_declared": len(adjudicate.COMPLETENESS_AWARE)}


def _as_record(d: dict) -> extraction.Record:
    """One reduced row back into a `Record`, for the costing. The quote is a DIGEST in a scored row and
    `cost_of` never reads quote text, so costing survives the reduction -- which is also what lets this
    module recompute the development numbers from a dump that kept no prose."""
    return extraction.Record(
        kind=str(d.get("kind") or "requirement"), role=str(d.get("role") or ""),
        value=str(d.get("value") or ""), quote=str(d.get("quote_sha") or d.get("quote") or ""),
        section=str(d.get("section") or ""), section_kind="plan",
        path=str(d.get("path") or "structural"),
        level_unverified=bool(d.get("level_unverified")))


def _reduce(r: extraction.Record) -> dict:
    """A kept record as a scored row carries it. The quote is HASHED: it is a collaborator's unpublished
    prose, no measurement here reads its text, and a digest still tells two citations apart."""
    return {"kind": r.kind, "role": r.role, "value": r.value, "path": r.path, "section": r.section,
            "level_unverified": bool(getattr(r, "level_unverified", False)),
            "quote_sha": hashlib.sha256((r.quote or "").encode("utf-8")).hexdigest()[:16]}


def row_for(name: str, text: str, *, client, digest: str = "") -> dict:
    """One report, read by the platform's own declared entry point, reduced to what the score needs.

    THE PAID HALF, and the only part that needs a key or the archive. It goes through
    `extraction.extract_report` rather than calling the paths separately, so what gets scored is the
    surface that ships. A failure comes back as `error` with `about: environment` and is NOT a report with
    no records: on a one-shot run over twelve documents, averaging over the eleven that worked would be the
    silent-absence defect in the one place it cannot be caught by a second run."""
    try:
        rep = extraction.extract_report(text, agent_client=client)
        if rep.get("error"):
            return {"report": name, "error": str(rep["error"])[:300], "about": rep.get("about", "request")}
        agent = rep.get("agent") or {}
        # Both paths' records come from the ONE call. Re-parsing the document for the structural side was
        # what this did first, and two parses of one document are two chances to disagree.
        s_recs = (rep.get("structural") or {}).get("kept") or []
        a_recs = agent.get("kept") or []
    except Exception as exc:                                              # noqa: BLE001
        return {"report": name, "error": f"{type(exc).__name__}: {exc}"[:300], "about": "environment"}
    ag = (rep.get("agent_vs_structural") or {}).get("agreement") or {}
    roles_s = sorted({r.role for r in s_recs})
    roles_a = sorted({r.role for r in a_recs})
    vb_s = verbatim_counts(s_recs, text)
    vb_a = verbatim_counts(a_recs, text)
    return {
        "report": name, "n_chars": len(text), "digest": digest,
        "structural": [_reduce(r) for r in s_recs],
        "agent": [_reduce(r) for r in a_recs],
        "roles_structural": roles_s, "roles_agent": roles_a,
        "comparison_kind": ag.get("comparison_kind", ""),
        "role_overlap": ag.get("role_overlap"),
        "agent_counts": {k: agent.get(k) for k in (
            "n_kept", "n_rejected", "n_spans", "n_level_records", "n_level_derived", "n_level_rejected",
            "n_level_unverified", "n_model_value_differed", "n_value_outside_quote",
            "levels_derived_by_platform", "temperature_pinned")},
        "n_span_failures": int(agent.get("n_unread_sections") or 0),
        "n_quote_checked": vb_s["n_checked"] + vb_a["n_checked"],
        "n_quote_verbatim": vb_s["n_verbatim"] + vb_a["n_verbatim"],
    }


def _all_true(values):
    """`all()` over a yes/no measurement, with ABSENT kept distinct from NO.

    FOUND BY RUNNING THIS MODULE over the development dump, which carries no `levels_derived_by_platform`
    key because the script that wrote it never asked for one. A plain `all(v is True ...)` turned that
    absence into `False` and `readiness` read it as a FAILED gate -- a tool reporting "I could not see it"
    as "it is broken", which is this project's own recurring defect aimed at its own criterion. So: None
    when nothing supplied the key, False only when something actually said False."""
    seen = [v for v in values if isinstance(v, bool)]
    if not seen:
        return None
    return all(seen)


def _ratio(num, den):
    """A pooled ratio, or None when its denominator is empty. NOT 0.0: an absent rate reported as zero is a
    perfect score, and `readiness` has a third category for exactly this."""
    return round(num / den, 4) if den else None


def score_rows(rows) -> dict:
    """Every declared number, from the rows and nothing else. Deterministic, offline, and the half that is
    actually tested.

    Separated from `row_for` so the arithmetic can be exercised without a key, without the archive and
    without a model -- and so the development numbers can be recomputed from a dump years later, which is
    how the three defects in the module docstring were found. A row carrying `error` makes the whole score
    REFUSE rather than contribute nothing: twelve documents is small enough that a quiet eleven changes
    every rate."""
    rows = list(rows or [])
    failed = [{"report": r.get("report", "?"), "error": r.get("error"), "about": r.get("about", "")}
              for r in rows if r.get("error")]
    if not rows:
        return {"measurements": {}, "n_reports": 0, "failed": [],
                "refused": "no rows were supplied, so there is nothing to score. An empty score is not a "
                           "clean one."}
    names = [str(r.get("report") or "") for r in rows]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        # FOUND BY ATTACKING THIS FUNCTION. Every pooled rate sums counters across rows, so the same
        # report scored twice weights itself double and nothing in the output would show it. The seal
        # names twelve documents once each; anything else is a mistake upstream, not a corpus.
        return {"measurements": {}, "n_reports": len(rows), "failed": [],
                "refused": f"the same report appears more than once: {dupes}. Every pooled rate sums "
                           f"counters across rows, so a duplicate weights that document twice and the "
                           f"result would not show it."}
    if failed:
        return {"measurements": {}, "n_reports": len(rows), "failed": failed,
                "refused": f"{len(failed)} of {len(rows)} report(s) did not produce a reading, so no "
                           f"rate over this set is defined. Scoring the rest would report a number for a "
                           f"corpus that was not read -- and on a one-shot set there is no second run to "
                           f"find that out. Fix the environment and re-run; the seal is not spent by a "
                           f"run that refused.",
                "detail": {"reports_read": len(rows) - len(failed)}}

    # --- the role axis: per-report by construction, so these are means over a stated denominator -------
    kinds, overlaps, covers, eligible, overlaps_with_a_table = [], [], [], [], []
    for r in rows:
        # The role sets fall back to the roles of the kept records, which is what they are. Only the role
        # SETS: `role_overlap` and `comparison_kind` are taken from whatever `extraction.reconcile`
        # returned and never recomputed here, because a second copy of that formula is a second
        # definition, and this project has already measured what two definitions of one key cost.
        roles_s = set(r.get("roles_structural") or ()) or {d.get("role") for d in (r.get("structural")
                                                                                  or [])}
        roles_a = set(r.get("roles_agent") or ()) or {d.get("role") for d in (r.get("agent") or [])}
        ov = r.get("role_overlap")
        if isinstance(ov, (int, float)) and not isinstance(ov, bool):
            overlaps.append(float(ov))
            # Paired with the report rather than zipped against it afterwards: `overlaps` skips a report
            # whose overlap is unreadable, so a later zip would silently shift every value by one.
            if roles_s:
                overlaps_with_a_table.append(float(ov))
        if roles_s:
            covers.append(len(roles_s & roles_a) / len(roles_s))
        if r.get("structural") and r.get("agent"):
            eligible.append(r.get("report", "?"))
            kinds.append(str(r.get("comparison_kind") or ""))
    # ABSENT, not the empty string. `_meets` compares with `in`, and "" is not in the allowed set, so an
    # empty modal would reach the criterion as a FAILED gate on a set where no report was even eligible --
    # the same absence-as-failure defect `_all_true` exists to prevent, in the one measurement that is
    # categorical rather than numeric.
    modal = max(set(kinds), key=kinds.count) if kinds else None
    strict = ("complementary" if any(k == "complementary" for k in kinds) else modal)
    if modal is None:
        strict = None

    # --- rates over records: pooled, each with its own denominator ------------------------------------
    t = {}
    for r in rows:
        for k, v in (r.get("agent_counts") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                t[k] = t.get(k, 0) + v
        for k in ("n_span_failures", "n_quote_checked", "n_quote_verbatim"):
            if isinstance(r.get(k), (int, float)):
                t[k] = t.get(k, 0) + r[k]

    # --- the costing, per report and summed. `cost_breakdown` counts DISTINCT demands within a report --
    cost = {"structural": [0, 0], "agent": [0, 0]}
    for r in rows:
        for path in ("structural", "agent"):
            recs = [_as_record(d) for d in (r.get(path) or [])]
            if not recs:
                continue
            cb = extraction.cost_breakdown(recs)
            cost[path][0] += cb["by_cost"]["unresolved"]
            cost[path][1] += cb["n_distinct"]

    derived_ok = [r.get("agent_counts", {}).get("levels_derived_by_platform") for r in rows]
    pinned = [r.get("agent_counts", {}).get("temperature_pinned") for r in rows]
    g4 = _summaries_carry_partial_flag()
    quotes_checked = t.get("n_quote_checked", 0)

    m = {
        "agent_vs_structural_comparison_kind": modal,
        "agent_vs_structural_role_overlap": (round(sum(overlaps) / len(overlaps), 4) if overlaps
                                             else None),
        "agent_covers_structural_roles": round(sum(covers) / len(covers), 4) if covers else None,
        "levels_derived_by_platform": _all_true(derived_ok),
        "extraction_temperature_pinned": _all_true(pinned),
        "summaries_carry_partial_flag": g4["value"],
        "value_outside_quote_rate": _ratio(t.get("n_value_outside_quote", 0), t.get("n_level_records", 0)),
        "unresolved_requirement_rate": _ratio(*cost["structural"]),
        "span_failure_rate": _ratio(t.get("n_span_failures", 0), t.get("n_spans", 0)),
        "level_refusal_rate": _ratio(t.get("n_level_rejected", 0),
                                     t.get("n_level_rejected", 0) + t.get("n_level_records", 0)),
        "model_level_disagreement_rate": _ratio(t.get("n_model_value_differed", 0),
                                                t.get("n_level_derived", 0)),
    }
    # A measurement nothing could compute is DROPPED, not zeroed. `readiness` reports an absent number as
    # unmeasured, which is the honest outcome; a 0.0 here would clear two of the thresholds.
    if quotes_checked:
        m["quote_verbatim_rate"] = _ratio(t.get("n_quote_verbatim", 0), quotes_checked)
    m = {k: v for k, v in m.items() if v is not None}

    return {
        "measurements": m,
        "n_reports": len(rows),
        "failed": [],
        "denominators": {
            "reports": len(rows),
            "eligible_for_comparison_kind": len(eligible),
            # The mean's OWN denominator. A row whose `role_overlap` is unreadable is left out of the
            # mean, and a mean over fewer reports than the set reported as scored is the silent-absence
            # shape in a number that looks finished.
            "reports_in_the_role_overlap_mean": len(overlaps),
            "reports_with_a_structural_reading": len(covers),
            "quote_records_checked": quotes_checked,
            "level_records_kept": t.get("n_level_records", 0),
            "level_records_rejected": t.get("n_level_rejected", 0),
            "spans": t.get("n_spans", 0),
            "distinct_structural_demands": cost["structural"][1],
            "distinct_agent_demands": cost["agent"][1],
        },
        "beside_the_gates": {
            # Reported because the rule that produced the gate's value was a choice, and the reader is
            # entitled to the other answer.
            "comparison_kind_distribution": {k: kinds.count(k) for k in sorted(set(kinds))},
            "comparison_kind_all_eligible": strict,
            "comparison_kind_rule_disagrees_with_strict": strict != modal,
            "role_overlap_reports_with_a_table": (
                round(sum(overlaps_with_a_table) / len(overlaps_with_a_table), 4)
                if overlaps_with_a_table else None),
            "unresolved_requirement_rate_agent_path": _ratio(*cost["agent"]),
            "quote_verbatim_not_checked": not quotes_checked,
            "summaries_carry_partial_flag_problems": g4["problems"],
        },
        "note": ("Every number above comes from `MEASURE_RULES`, which states the aggregation and why. "
                 "Nothing here decides whether the seal may be broken; pass `measurements` to "
                 "holdout.readiness()."
                 + ("" if quotes_checked else
                    " QUOTE VERBATIM RATE IS ABSENT: these rows carry no quote check, so G3 reaches "
                    "`readiness` unmeasured rather than as a 1.0 nobody computed.")),
    }


def check_against_the_seal(digests, partition: str = "held_out", seal_path: str | None = None) -> dict:
    """Are the documents about to be scored the ones that were sealed, byte for byte?

    WHY THIS IS NOT PARANOIA. The held-out result's entire claim is that the tool had never seen these
    twelve. A path typo, a re-exported archive or an edited copy would produce a number that reads exactly
    like a held-out result and is not one -- and the run is one-shot, so there is no second chance to
    notice. The seal already committed to the bytes; this is the comparison nobody had written.

    A machine that cannot read the seal gets `about: environment` and `verified: None`: unknown, never a
    silent pass. The caller decides what to do with that, and `score` refuses only on a real mismatch."""
    sealed = holdout.sealed_digests(partition, seal_path)
    if sealed["digests"] is None:
        return {"verified": None, "about": sealed["about"], "note": sealed["note"]}
    want, missing, mismatched = sealed["digests"], [], []
    for name, got in sorted(dict(digests or {}).items()):
        if name not in want:
            missing.append(name)
        elif got and got != want[name]:
            mismatched.append(name)
    unscored = sorted(set(want) - set(digests or {}))
    return {"verified": not missing and not mismatched, "about": "", "partition": partition,
            "not_in_the_seal": missing, "digest_mismatch": mismatched, "sealed_but_not_scored": unscored,
            "n_sealed": len(want),
            "note": ("every document scored is one the seal committed to, with matching bytes."
                     if not missing and not mismatched else
                     "; ".join(filter(None, [
                         f"{missing} is not in the {partition!r} partition of the seal" if missing else "",
                         f"{mismatched} does not match the bytes that were sealed" if mismatched
                         else ""])))}


def read_signoff(path: str, sheet) -> dict:
    """A reviewer's sign-off on the value-to-member mappings, checked against the mappings in front of us.

    GATE G5, and the reason it needs more than a name in a field. A signature on a worksheet that has
    since changed means nothing, and on a held-out run the documents may use spellings the reviewer could
    not have seen -- they were sealed. So this separates three things a single string cannot:

      * whether the sign-off is INTACT (its own recorded triples hash to its own recorded digest, so the
        file has not drifted from what was signed);
      * which of the mappings now firing were COVERED by it;
      * which are NEW SINCE THE SIGN-OFF, and therefore unreviewed. Those are reported, never used to
        retroactively fail the gate and never hidden: a reviewer who checked 55 mappings has reviewed 55
        mappings, and a held-out document that invents a 56th has found a gap in the review, not in the
        reviewer.

    An unreadable file is an environment fact (`signed_off_by: None`), never an unsigned one."""
    try:
        obj = json.loads(io.open(path, "rb").read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        return {"signed_off_by": None, "about": "environment", "path": path,
                "note": f"the sign-off could not be read at {path} ({exc.__class__.__name__}). This "
                        f"machine could not look; nothing about whether anybody reviewed the mappings "
                        f"follows from it."}
    signed = [tuple(str(x) for x in t) for t in (obj.get("mappings") or []) if len(t) == 3]
    recomputed = hashlib.sha256(json.dumps(sorted(signed), sort_keys=True).encode("utf-8")).hexdigest()
    intact = bool(signed) and recomputed == str(obj.get("mapping_digest") or "")
    now = {(r["role"], r["author_wrote"], r["mapped_to"]) for r in (sheet or {}).get("rows") or []}
    unreviewed = sorted(now - set(signed))
    return {"signed_off_by": (str(obj.get("signed_off_by") or "").strip() if intact else ""),
            "about": "", "path": path, "intact": intact, "date": str(obj.get("date") or ""),
            "n_signed": len(signed), "n_in_front_of_us": len(now),
            "n_covered": len(now & set(signed)), "unreviewed": unreviewed,
            "note": ("the sign-off's recorded mappings do not hash to its recorded digest, so it has "
                     "drifted from whatever was actually reviewed and NO name is taken from it."
                     if not intact else
                     f"{len(now & set(signed))} of {len(now)} mapping(s) now firing were covered by the "
                     f"sign-off." + (f" {len(unreviewed)} were NOT, and are listed: a reviewer who "
                                     f"checked {len(signed)} mappings has reviewed those and no others."
                                     if unreviewed else " None are new since it was signed."))}


def score(reports, *, client, mappings_signed_off_by: str = "", digests=None,
          partition: str = "held_out", seal_path: str | None = None, signoff_path: str = "") -> dict:
    """The whole held-out score: read the reports, compute every number, and say what is still missing.

    `reports` maps a name to the document text. `mappings_signed_off_by` is G5 and is passed through
    UNCHANGED -- empty means nobody other than the author has reviewed the mapping list, and that reaches
    `readiness` as a failed gate rather than as an absent one. G6's own measurement comes from `coverage`,
    which asks whether anything declared is left for somebody to compute by hand.

    Digests are checked against the seal when `digests` is supplied and the seal is readable. A MISMATCH
    REFUSES: a number computed from a document that is not the sealed one is not a held-out result, and it
    would be indistinguishable from one afterwards."""
    digests = digests or {}
    seal = check_against_the_seal(digests, partition, seal_path) if digests else {
        "verified": None, "about": "request",
        "note": "no digests were supplied, so nothing was checked against the seal. The held-out run must "
                "supply them -- `read_reports` returns them for exactly this."}
    if seal["verified"] is False:
        return {"measurements": {}, "n_reports": len(reports or {}), "failed": [], "seal": seal,
                "coverage": coverage(), "rows": [],
                "refused": f"the documents do not match the seal: {seal['note']} Scoring them would "
                           f"produce a number that reads like a held-out result and is not one."}
    rows = [row_for(name, text, client=client, digest=digests.get(name, ""))
            for name, text in sorted(dict(reports or {}).items())]
    scored = score_rows(rows)
    cov = coverage()
    # The sheet is built from the records just read, so the sign-off is checked against the mappings that
    # actually fired on THESE documents rather than against the ones that fired when it was signed.
    sheet = extraction.mapping_review_sheet(
        [_as_record(d) for r in rows for d in (r.get("structural") or [])])
    signoff = (read_signoff(signoff_path, sheet) if signoff_path else
               {"signed_off_by": "", "about": "request", "unreviewed": [],
                "note": "no sign-off file was given, so nothing was checked. `mappings_signed_off_by` "
                        "supplies a bare name instead, which records WHO but not WHAT they saw."})
    name = (signoff.get("signed_off_by") or "") or str(mappings_signed_off_by or "").strip()
    m = dict(scored.get("measurements") or {})
    if m:
        m["score_produced_by_committed_code"] = cov["score_produced_by_committed_code"]
        if name:
            m["applied_mappings_signed_off_by"] = name
    return {**scored, "measurements": m, "coverage": cov, "rows": rows, "seal": seal,
            "mapping_sheet": {k: v for k, v in sheet.items() if k != "rows"},
            "signoff": signoff,
            "mappings_signed_off_by": name,
            "g5_note": ("" if name else
                        "G5 has no reviewer: `applied_mappings_signed_off_by` is left OUT of the "
                        "measurements rather than supplied empty, so `readiness` reports it as "
                        "unmeasured -- which is what it is. Nobody has reviewed the mapping list. "
                        "`scripts/mapping_review.py` writes the worksheet that makes the review a "
                        "page rather than a corpus.")}


def read_reports(directory: str, names) -> dict:
    """The named documents, read as text, with their digests.

    The archive is a collaborator's unpublished output and is local only, so this takes a directory as an
    ARGUMENT and never a default: a machine that cannot see the archive must fail by not being given a
    path, not by silently scoring nothing."""
    texts, digests, missing = {}, {}, []
    for name in names or ():
        p = os.path.join(directory, name)
        try:
            raw = io.open(p, "rb").read()
        except OSError:
            missing.append(name)
            continue
        texts[name] = raw.decode("utf-8", errors="replace")
        digests[name] = hashlib.sha256(raw).hexdigest()
    return {"texts": texts, "digests": digests, "missing": missing,
            "note": ("" if not missing else
                     f"{len(missing)} named report(s) were not found under {directory}. This machine "
                     f"could not read them; NOTHING about the held-out set follows from that.")}
