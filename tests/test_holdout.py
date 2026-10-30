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
