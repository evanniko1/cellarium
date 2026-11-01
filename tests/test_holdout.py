"""The held-out set's completion criterion, pre-registered.

ADJ-W2. Twelve of the forty-five Co-Scientist idea reports were sealed by SHA-256 on 2026-10-29, before any
extraction pattern existed, and they are ONE-SHOT: a set you have already looked at measures the tool's fit
to it, not the tool. What was missing is the other half of that discipline. Nothing said what "the tool is
finished" means, so the moment to spend them would have been chosen by whoever happened to feel ready -- and
with one annotator who has now read the development set five times, that feeling is the least reliable
instrument in the project.

So the criterion is declared BEFORE the run, in a table, and the question "may the seal be broken?" is a
function call rather than a judgement. The gates are not new inventions either: four of the five are the
open weakness items, which is the honest reading of "finished" -- the tool is finished when the things
already known to be wrong with it are no longer wrong.

The rule that does the most work here is the smallest: a MISSING measurement is not a pass. A readiness
check whose default is "yes, nothing objected" would pass a tool nobody measured, which is the
silent-absence shape applied to the project's own process.
"""

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import holdout  # noqa: E402

DOC = os.path.join(os.path.dirname(__file__), "..", "docs", "HOLDOUT_PREREGISTRATION.md")

# The gate classification, pinned so `holdout.READINESS_GATES` and this file have to agree. A
# `measured_number` verdict is a rate over the development documents; `construction` and `configuration`
# verdicts are statements about code that any reader can re-read, and the numbers behind the first kind
# CANNOT be re-derived from this repository at all
# (holdout.LIMITATIONS['development_verdicts_are_not_offline']). The distinction is a judgement, so it is
# stored rather than derived -- and stored twice, because a single store can be edited without anything
# noticing, which a mutation sweep demonstrated on 2026-11-01.
EXPECTED_VERDICT_KIND = {
    "G1_INDEPENDENT_CHECK": "measured_number",
    "G2_ROLE_OVERLAP": "measured_number",
    "G2B_STRUCTURAL_COVERAGE": "measured_number",
    "G3_QUOTES_VERBATIM": "construction",
    "G7_LEVELS_DERIVED": "construction",
    "G4_PARTIALITY_TRAVELS": "construction",
    "G8_SAMPLING_PINNED": "configuration",
    "G5_MAPPINGS_REVIEWED": "measured_number",
    "G6_SCORING_IS_MECHANICAL": "construction",
}


def _all_met() -> dict:
    """A measurement set that meets every gate, built FROM the declared table rather than hand-listed.

    Hand-listing it would let a gate be added without this fixture noticing, and the suite would then test
    a criterion that is one gate out of date."""
    out = {}
    for g in holdout.READINESS_GATES:
        op, want = g["requires"]
        out[g["measure"]] = {"==": want, ">=": want, "<=": want, "is": want,
                             "in": want[0] if isinstance(want, (tuple, list)) else want,
                             "nonempty": "signed off by A. Reviewer, 2026-11-02"}[op]
    for m in holdout.MUST_REPORT:
        out.setdefault(m["measure"], 0.0)
    return out


# --- the criterion is a table, not a feeling ----------------------------------------------------------

def test_the_gates_are_declared_with_what_they_ask_and_why():
    assert len(holdout.READINESS_GATES) >= 5
    for g in holdout.READINESS_GATES:
        assert g["id"] and g["asks"] and g["measure"] and g["why"]
        op, _ = g["requires"]
        assert op in holdout.COMPARISONS, g


def test_every_gate_traces_to_an_OPEN_WEAKNESS_or_says_why_it_does_not():
    """The criterion must not be a fresh list of nice properties. It is the open items, so that "finished"
    means "the known defects are fixed" rather than "I have run out of ideas"."""
    traced = [g for g in holdout.READINESS_GATES if g.get("weakness")]
    assert len(traced) >= 4
    assert {g["weakness"] for g in traced} >= {"ADJ-W1", "ADJ-W5", "ADJ-W8", "ADJ-W9"}
    for g in holdout.READINESS_GATES:
        assert g.get("weakness") or g.get("not_a_weakness_because"), g["id"]


def test_the_selection_rule_and_the_counts_are_part_of_the_registration():
    r = holdout.PREREGISTRATION
    assert r["n_held_out"] == 12 and r["n_development"] == 33 and r["n_reports_total"] == 45
    assert "every 4th" in r["selection_rule"]
    assert r["frozen_at"] == "2026-10-29"
    # The archive also ships three files that are in NEITHER set. Named, because a file in no category is
    # the one that quietly gets used for development.
    assert len(r["in_neither_set"]) == 3
    assert "knowledge_base_report.md" in r["in_neither_set"]


# --- the gate, and the thing that makes it a gate ------------------------------------------------------

def test_every_gate_met_opens_the_seal():
    out = holdout.readiness(_all_met())
    assert out["may_break_seal"] is True, out["unmet"] + out["unmeasured"]
    assert not out["unmet"] and not out["unmeasured"]


def test_a_MISSING_measurement_is_not_a_pass():
    """The rule that matters most. A readiness check that defaults to yes would pass a tool nobody
    measured -- the silent-absence shape, pointed at the project's own process."""
    out = holdout.readiness({})
    assert out["may_break_seal"] is False
    assert len(out["unmeasured"]) == len(holdout.READINESS_GATES) + len(holdout.MUST_REPORT)
    assert "not a pass" in out["note"].lower()
    assert not out["unmet"]          # unmeasured is its own category, not a failure


def test_one_unmet_gate_closes_it():
    """Forcing the instrument to fail. A gate that has never said no is decoration."""
    for g in holdout.READINESS_GATES:
        m = _all_met()
        op, want = g["requires"]
        m[g["measure"]] = {"==": -1.0, ">=": -1.0, "<=": 10 ** 9, "is": not want,
                           "in": "something_else", "nonempty": ""}[op]
        out = holdout.readiness(m)
        assert out["may_break_seal"] is False, g["id"]
        assert g["id"] in [u["id"] for u in out["unmet"]], g["id"]


def test_a_value_of_the_WRONG_KIND_is_unmeasured_rather_than_a_pass():
    """"0.9" is not 0.9. A comparison that coerced it would let a string pass a numeric threshold, and a
    readiness gate is the last place to be relaxed about types."""
    m = _all_met()
    numeric = [g for g in holdout.READINESS_GATES if g["requires"][0] in (">=", "<=", "==")
               and isinstance(g["requires"][1], (int, float))]
    assert numeric
    m[numeric[0]["measure"]] = "0.9"
    out = holdout.readiness(m)
    assert out["may_break_seal"] is False
    assert numeric[0]["id"] in [u["id"] for u in out["unmeasured"]]


def test_a_measurement_with_no_threshold_still_has_to_be_PRESENT():
    """Some numbers have no defensible threshold yet -- the rate at which a verbatim span is cited for a
    record it does not support is one. Not having a threshold is not the same as not having to report it,
    and an unreported number is how a known weakness disappears from a result."""
    assert holdout.MUST_REPORT
    m = _all_met()
    del m[holdout.MUST_REPORT[0]["measure"]]
    out = holdout.readiness(m)
    assert out["may_break_seal"] is False
    assert holdout.MUST_REPORT[0]["id"] in [u["id"] for u in out["unmeasured"]]


# --- what the run means once it happens ---------------------------------------------------------------

def test_the_outcome_rules_make_the_run_one_shot_and_the_result_binding():
    r = holdout.OUTCOME_RULES
    assert "one_shot" in r and "report_whatever_it_says" in r
    assert "no_widening_after_the_result" in r
    assert "never_used_for_development_again" in r
    for v in r.values():
        assert len(v) > 40


def test_the_single_annotator_limitation_is_recorded_with_its_MITIGATION():
    """The literature is blunt about single extraction -- error rates up to 50-63% in reviews of the
    practice, about 22% worse than double. There is one annotator here and he has read the development set
    five times, which cannot be undone; what can be done is to keep his reading out of the score."""
    lim = holdout.LIMITATIONS
    assert any("annotator" in k for k in lim)
    assert any("mechanical" in v or "code" in v for v in lim.values())


def test_what_the_run_CANNOT_settle_is_listed_too():
    """ADJ-W3 and ADJ-W6 are upstream: the documents do not state the elongation model and the campaign
    does not build two of the setpoints they ask for. Neither is a defect in the extractor, so neither
    gates the seal -- and both have to be stated, or the held-out result will be read as covering them."""
    assert holdout.OUT_OF_SCOPE
    assert any("ADJ-W3" in k for k in holdout.OUT_OF_SCOPE)
    assert any("ADJ-W6" in k for k in holdout.OUT_OF_SCOPE)


# --- the seal file itself, which is not on every machine ----------------------------------------------

def test_the_seal_file_being_ABSENT_is_an_environment_fact_not_an_unsealed_set():
    """The archive is local-only, so this check runs on machines that cannot see it. "I could not find the
    seal" reported as "there is no seal" is the bug class this project keeps finding."""
    out = holdout.seal_state(os.path.join(os.path.dirname(__file__), "no_such_seal.json"))
    assert out["about"] == "environment"
    assert out["sealed"] is None
    assert "could not" in out["note"].lower()


def test_the_seal_state_reports_the_DIGEST_and_the_counts_when_the_file_is_here(tmp_path):
    p = tmp_path / "HOLDOUT.json"
    p.write_text(json.dumps({"frozen_at": "2026-10-29", "n_reports_total": 45, "n_held_out": 12,
                             "n_development": 33, "held_out": {"a.md": "aa"},
                             "development": {"b.md": "bb"}}), encoding="utf-8")
    out = holdout.seal_state(str(p))
    assert out["sealed"] is True and out["about"] == ""
    assert len(out["digest"]) == 64
    assert out["n_held_out"] == 1 and out["n_development"] == 1


def test_a_seal_whose_counts_contradict_the_registration_is_reported_not_trusted(tmp_path):
    p = tmp_path / "HOLDOUT.json"
    p.write_text(json.dumps({"frozen_at": "2026-10-29", "n_reports_total": 45, "n_held_out": 99,
                             "n_development": 33, "held_out": {}, "development": {}}), encoding="utf-8")
    out = holdout.seal_state(str(p))
    assert out["disagrees_with_registration"]
    assert out["sealed"] is True          # the file is there; what it says is the finding


# --- the prose and the table cannot drift -------------------------------------------------------------

def test_the_prose_registration_names_every_gate_and_every_rule():
    """The Platform Map lesson, applied to a document that matters more: v30 described two mechanisms in
    the past tense before either existed. A pre-registration that falls behind its own gate table is worse
    than none, because it is the version a reader will cite."""
    text = io.open(DOC, encoding="utf-8").read()
    for g in holdout.READINESS_GATES:
        assert g["id"] in text, g["id"]
    for m in holdout.MUST_REPORT:
        assert m["id"] in text, m["id"]
    for k in holdout.OUTCOME_RULES:
        assert k in text, k
    assert holdout.PREREGISTRATION["selection_rule"] in text


def test_every_gate_names_WHERE_ITS_NUMBER_COMES_FROM():
    """A gate whose measurement has no stated source is a gate somebody fills in by hand at the moment of
    the run -- which is precisely what G6_SCORING_IS_MECHANICAL exists to forbid. So each one names the call
    that produces its number, and three of them say plainly that the answer today is no."""
    for item in list(holdout.READINESS_GATES) + list(holdout.MUST_REPORT):
        assert item.get("source"), item["id"]
        assert len(item["source"]) > 30, item["id"]


def test_every_gate_RECORDS_ITS_VERDICT_and_an_absent_record_cannot_be_silent():
    """The companion to the test above, and it exists because the blank was real. On 2026-11-01 four of the
    nine gates -- G3, G4, G7, G8 -- carried no `measured` field at all, while five did. Nothing was wrong
    with the gates; what was wrong is that a reader of this module could not tell which seven of the nine
    the project's own headline ("7 of 9 gates met") referred to, because a missing record reads exactly like
    a gate nobody had measured. That is this repository's own silent-absence defect pointed at its own
    criterion, which is the one place it had no business being.

    `readiness()` already keeps absence distinct at RUNTIME -- `unmeasured` is a third list beside met and
    unmet. This asserts the same discipline for the WRITTEN record: every gate says what it found, or says
    explicitly that it has nothing to say. There is no third option, because the third option is the blank.

    MUST_REPORT IS DELIBERATELY NOT COVERED, and the boundary is a real distinction rather than a
    convenience. A gate has a threshold and therefore a VERDICT; `readiness()` sorts it into met, unmet or
    unmeasured. A must-report item has no threshold at all -- it goes into `reported`, and demanding a
    met/unmet verdict of it would be a category error. Every one of the five does record its development
    value, in `why`, which is where an item with no verdict can honestly carry it.

    THE KIND IS DECLARED, NEVER INFERRED FROM THE PROSE. The first version of this test decided whether a
    verdict was a construction claim by searching its text for "BY CONSTRUCTION", and it misfired
    immediately in both directions: `G2_ROLE_OVERLAP` carries that phrase in a different sense and was
    wrongly caught, while `G4`'s verdict is a construction claim containing neither marker and was missed.
    Classifying a record by scanning its own words is the proxy habit this project keeps finding in itself.
    """
    kinds = {"measured_number", "construction", "configuration"}
    for g in holdout.READINESS_GATES:
        verdict = str(g.get("measured") or "")
        no_record = str(g.get("no_record_because") or "")
        assert bool(verdict) != bool(no_record), (
            f"{g['id']} must carry EITHER `measured` (what it found) OR `no_record_because` (why it has "
            f"nothing), and exactly one: measured={bool(verdict)}, no_record_because={bool(no_record)}. A "
            "gate with neither is a blank that reads as 'nobody measured it'; one with both is two answers")
        assert len(verdict or no_record) > 30, f"{g['id']}'s record is too short to say anything"
        assert g.get("verdict_kind") in kinds, (
            f"{g['id']} declares verdict_kind={g.get('verdict_kind')!r}, not one of {sorted(kinds)}")
        # THE CLASSIFICATION IS PINNED HERE TOO, and that is the point rather than belt-and-braces. A
        # mutation sweep found the hole: the obligation below applies only to the non-number kinds, so
        # relabelling a construction verdict AS a `measured_number` lifted it and nothing objected -- a
        # guard that ran in one direction. The kind is a judgement and cannot be derived; what it can be is
        # stored in two places that have to agree, the discipline `capbench_cases` applies to its own answer
        # keys. Changing one is now an edit in two files, which is the intent.
        assert g["verdict_kind"] == EXPECTED_VERDICT_KIND[g["id"]], (
            f"{g['id']} is declared {g['verdict_kind']!r} and this test expects "
            f"{EXPECTED_VERDICT_KIND[g['id']]!r}. If the kind really changed, change it here too and say "
            "why; if it did not, a construction claim has just been relabelled as a rate over the "
            "development documents, which is what the limitation exists to prevent")
        # A verdict about code rather than about the documents has to say so where it is read, or the
        # distinction survives only in whoever wrote it.
        if g["verdict_kind"] != "measured_number":
            assert "development_verdicts_are_not_offline" in verdict, (
                f"{g['id']} is a {g['verdict_kind']} verdict and does not point at "
                "LIMITATIONS['development_verdicts_are_not_offline'] -- so a reader has no way to know it "
                "is not a rate over the development set")
    assert "development_verdicts_are_not_offline" in holdout.LIMITATIONS, (
        "the limitation those records point at is gone; they would be pointing at nothing")
    # The boundary itself, in both directions, so it stays a decision rather than an oversight.
    for r in holdout.MUST_REPORT:
        assert not r.get("measured"), (
            f"{r['id']} has grown a `measured` field. Must-report items have no threshold and no verdict, "
            "so either that is a real change of kind -- give it a verdict_kind and bring it under the loop "
            "above -- or the value belongs in `why` with the others")
        assert len(str(r.get("why") or "")) > 30, f"{r['id']} records nothing about what it found"


def test_the_prose_COUNTS_are_recomputed_from_the_gates_rather_than_typed():
    """Both counts in the preregistration page had drifted, and nothing recomputed either.

    Found 2026-11-01. The page said "Six of the nine are the open weakness items" -- six is the number of
    DISTINCT weakness items and eight is the number of GATES closing one, so it was neither count. And it
    said "Two of the eight -- `G5` and `G6` -- say plainly that the answer today is no", two paragraphs
    below its own table recording `G6` as met on 2026-10-31: the page contradicted itself, and the pair had
    become `G2` and `G5`.

    Both are derivable, so neither should have been typed. `weakness` on each gate gives the closing counts;
    the recorded verdict gives the pair.

    THE SENTENCE IS READ, NOT THE PAGE. A mutation sweep found that hole too: an earlier version asserted
    the gate ids appeared in `text`, and every gate id appears in the table anyway, so swapping `G2` for
    `G6` inside the sentence passed. Searching a whole document for a name is not reading the claim that
    names it. Whitespace is normalised first so the assertions do not depend on where the prose wraps."""
    text = io.open(DOC, encoding="utf-8").read()
    flat = " ".join(text.split())
    gates = holdout.READINESS_GATES
    weaknesses = [g["weakness"] for g in gates if g.get("weakness")]
    words = {1: "One", 2: "Two", 6: "six", 8: "Eight", 9: "nine"}

    # 8 of 9 close one of 6 distinct items; the 9th (G6) closes none and is a mitigation, not a fix.
    assert f"{words[len(weaknesses)]} of the {words[len(gates)]} close one of" in flat, (
        f"the page no longer states that {len(weaknesses)} of the {len(gates)} gates close a weakness item")
    assert f"**{words[len(set(weaknesses))]}** open weakness items" in flat, (
        f"the page no longer states the {len(set(weaknesses))} distinct weakness items "
        f"({sorted(set(weaknesses))})")
    # SCOPED TO THE SENTENCE, for the third time in one sitting. The first version of this loop asked
    # whether each weakness id appeared anywhere in `flat` -- and every one of them appears elsewhere on
    # the page, so renaming `ADJ-W10` inside the list still passed. A whole-page search for a name is not
    # reading the claim that lists it, and that is the same error this test was written to catch.
    listing = flat[flat.index("close one of"):flat.index("and the ninth")]
    for w in sorted(set(weaknesses)):
        assert f"`{w}`" in listing, (
            f"{w} closes a gate and the sentence listing the weakness items does not name it. "
            f"Listing read: {listing!r}")
    stale = [m for m in ("ADJ-W2", "ADJ-W3", "ADJ-W4", "ADJ-W6", "ADJ-W11", "ADJ-W12")
             if f"`{m}`" in listing]
    assert not stale, (
        f"the sentence lists {stale}, which close no gate -- every id in it must be one of "
        f"{sorted(set(weaknesses))}")

    # ... and the gates whose recorded verdict says no TODAY, by id, inside the sentence that claims them.
    says_no = [g["id"] for g in gates if str(g.get("measured") or "").startswith(("FAILED", "UNMET"))]
    marker = "say plainly that the answer today is no"
    assert marker in flat, (
        "the page no longer carries the sentence naming the gates that say no; this test pins its content "
        "and cannot find it")
    start = flat.index(marker)
    sentence = flat[start:start + 260]
    assert len(says_no) == 2, (
        f"{len(says_no)} gates now say no ({says_no}) and the page says two -- recount and rewrite it")
    assert f"Two of the **{words[len(gates)]}**" in flat[max(0, start - 120):start], (
        f"the sentence no longer says two of the {len(gates)}")
    for gid in says_no:
        assert f"`{gid}`" in sentence, (
            f"{gid}'s recorded verdict says no and the sentence does not name it. This is the 2026-11-01 "
            f"error exactly -- it named G5 and G6 while the module said G2 and G5. Sentence: {sentence!r}")
    for g in gates:
        if str(g.get("measured") or "").startswith("MET"):
            assert f"`{g['id']}`" not in sentence, (
                f"{g['id']} is recorded MET and the sentence names it among those saying no, which is the "
                "half of the 2026-11-01 error that made the page contradict its own table")
