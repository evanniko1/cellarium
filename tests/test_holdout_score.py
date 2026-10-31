"""The held-out score, computed by committed code. Gate G6_SCORING_IS_MECHANICAL.

G6 is the mitigation for the single-annotator limitation: one person built every vocabulary and has read
the development set five times, so what keeps his reading out of the held-out numbers is that the numbers
come from code which existed before the seal was broken. The gate's own words are that "a number computed
by hand at the time of the run is the thing it exists to forbid".

WHICH MAKES THIS SUITE'S JOB THE OPPOSITE OF REASSURANCE. A scorer that cannot fail is decoration, so most
of what follows forces a failure: a declared gate nothing computes, a measure claimed two ways, a rule for
a gate that no longer exists, a report that did not read, a key that is absent rather than false. The last
of those is not hypothetical -- running the scorer over the development dump turned a missing key into a
FAILED gate, and the test for it is the regression.
"""

import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import extraction, holdout, holdout_score  # noqa: E402


def _row(name="r1", **kw) -> dict:
    """A scored row with enough in it to produce every number, so a test can change ONE thing."""
    row = {
        "report": name, "n_chars": 1000, "digest": "d",
        "structural": [{"kind": "requirement", "role": "factor:ppgpp_module", "value": "on",
                        "path": "structural", "section": "Plan", "quote_sha": "aa"}],
        "agent": [{"kind": "requirement", "role": "factor:ppgpp_module", "value": "on",
                   "path": "agent", "section": "Plan", "quote_sha": "bb"}],
        "roles_structural": ["factor:ppgpp_module"],
        "roles_agent": ["factor:ppgpp_module", "readout:growth_rate"],
        "comparison_kind": "partial", "role_overlap": 0.5,
        "agent_counts": {"n_spans": 10, "n_level_records": 8, "n_level_derived": 6,
                         "n_level_rejected": 4, "n_level_unverified": 1, "n_model_value_differed": 2,
                         "n_value_outside_quote": 1, "levels_derived_by_platform": True,
                         "temperature_pinned": True},
        "n_span_failures": 2, "n_quote_checked": 2, "n_quote_verbatim": 2,
    }
    row.update(kw)
    return row


# --- G6's own measurement: does anything declared still need a human with a calculator? ---------------

def test_every_declared_measurement_is_either_computed_here_or_named_as_one_that_cannot_be():
    cov = holdout_score.coverage()
    assert cov["score_produced_by_committed_code"] is True, cov["note"]
    assert cov["uncovered"] == []
    assert cov["n_declared"] == len(holdout_score.declared_measures())
    # The two that no code could produce are named, not missing.
    assert set(cov["not_from_the_reports"]) == {"applied_mappings_signed_off_by",
                                                "score_produced_by_committed_code"}


def test_a_NEW_GATE_nothing_computes_makes_G6_FAIL(monkeypatch):
    """The failure mode G6 exists for: a gate added later whose number gets worked out at the console.

    `declared_measures` READS the registration instead of carrying a copy, so this is the test that the
    reading is real. If it passed with a fake gate present, the coverage check would be a constant."""
    fake = {"id": "G99_SOMETHING_NEW", "asks": "?", "measure": "a_number_nobody_computes",
            "requires": (">=", 0.5)}
    monkeypatch.setattr(holdout, "READINESS_GATES", holdout.READINESS_GATES + (fake,))
    cov = holdout_score.coverage()
    assert cov["score_produced_by_committed_code"] is False
    assert cov["uncovered"] == ["a_number_nobody_computes"]
    assert "a_number_nobody_computes" in cov["note"]


def test_a_measure_claimed_BOTH_as_computed_and_as_impossible_makes_G6_FAIL(monkeypatch):
    """Two answers for one measure is no answer: which of them governs would be decided by whoever read
    the dict first."""
    monkeypatch.setitem(holdout_score.NOT_FROM_THE_REPORTS, "span_failure_rate", "claimed twice")
    cov = holdout_score.coverage()
    assert cov["score_produced_by_committed_code"] is False
    assert cov["claimed_both_ways"] == ["span_failure_rate"]


def test_a_RULE_for_a_gate_that_no_longer_EXISTS_makes_G6_FAIL(monkeypatch):
    """The other direction. A rule left behind after its gate was retired means this module and the
    registration disagree about what is being measured, and the disagreement should be loud."""
    monkeypatch.setattr(holdout, "MUST_REPORT",
                        tuple(r for r in holdout.MUST_REPORT if r["measure"] != "span_failure_rate"))
    cov = holdout_score.coverage()
    assert cov["score_produced_by_committed_code"] is False
    assert cov["stale_rules"] == ["span_failure_rate"]


def test_every_rule_states_its_AGGREGATION_and_why_that_one():
    """A rate over twelve documents is undefined until somebody says mean or pooled, so the rule is part
    of the registration and not an implementation detail."""
    for name, rule in holdout_score.MEASURE_RULES.items():
        assert rule["aggregate"].strip(), name
        assert len(rule["why"]) > 60, name
        assert rule["per_report"].strip(), name
        assert isinstance(rule["chosen_after_seeing_the_numbers"], bool), name
        if rule["chosen_after_seeing_the_numbers"]:
            # Recorded, not hidden: a rule chosen with the answer in view is a weaker instrument, and the
            # alternative it beat has to be stated or the choice cannot be audited.
            assert rule["the_alternative_it_was_chosen_over"].strip(), name


def test_every_rule_points_at_a_gate_or_a_must_report_item():
    ids = {g["id"] for g in holdout.READINESS_GATES} | {r["id"] for r in holdout.MUST_REPORT}
    for name, rule in holdout_score.MEASURE_RULES.items():
        assert rule.get("gate", rule.get("must_report")) in ids, name


# --- a report that did not read is not a report with nothing in it ------------------------------------

def test_ONE_failed_report_makes_the_WHOLE_SCORE_REFUSE():
    """Twelve documents is small enough that quietly scoring eleven changes every rate -- and on a
    one-shot set there is no second run to notice. So the score refuses and says which report failed."""
    out = holdout_score.score_rows([_row("ok"), {"report": "bad", "error": "RateLimit",
                                                 "about": "environment"}])
    assert out["measurements"] == {}
    assert "did not produce a reading" in out["refused"]
    assert [f["report"] for f in out["failed"]] == ["bad"]
    assert out["detail"]["reports_read"] == 1


def test_NO_rows_is_a_refusal_and_not_a_clean_sheet():
    out = holdout_score.score_rows([])
    assert out["measurements"] == {}
    assert "not a clean one" in out["refused"]


def test_the_refusal_does_NOT_spend_the_seal():
    """Stated in the refusal itself, because the one-shot rule makes "re-run it" the question a reader
    will have and the wrong answer loses the set."""
    out = holdout_score.score_rows([{"report": "bad", "error": "boom"}])
    assert "the seal is not spent by a run that refused" in out["refused"]


# --- absence is not failure, and this one is a regression --------------------------------------------

def test_a_MISSING_boolean_key_is_ABSENT_rather_than_FALSE():
    """THE DEFECT THIS TEST EXISTS FOR, found by running the scorer over the development dump: the dump
    carries no `levels_derived_by_platform`, a plain `all(v is True ...)` read that absence as False, and
    `readiness` reported G7 as a FAILED gate. "I could not see it" reported as "it is broken" is this
    project's own recurring bug class, aimed at its own completion criterion."""
    counts = dict(_row()["agent_counts"])
    counts.pop("levels_derived_by_platform")
    out = holdout_score.score_rows([_row(agent_counts=counts)])
    assert "levels_derived_by_platform" not in out["measurements"]
    # And it reaches the criterion as unmeasured, which is the whole point of dropping it.
    r = holdout.readiness(out["measurements"])
    assert "G7_LEVELS_DERIVED" in [g["id"] for g in r["unmeasured"]]
    assert "G7_LEVELS_DERIVED" not in [g["id"] for g in r["unmet"]]


def test_a_key_that_actually_says_FALSE_is_FALSE():
    """The other half of the same rule -- dropping a real negative would be worse than the bug it fixes."""
    counts = {**_row()["agent_counts"], "levels_derived_by_platform": False}
    out = holdout_score.score_rows([_row(agent_counts=counts)])
    assert out["measurements"]["levels_derived_by_platform"] is False
    assert "G7_LEVELS_DERIVED" in [g["id"] for g in holdout.readiness(out["measurements"])["unmet"]]


def test_ONE_report_failing_the_boolean_fails_it_for_the_SET():
    counts = {**_row()["agent_counts"], "temperature_pinned": False}
    out = holdout_score.score_rows([_row("a"), _row("b", agent_counts=counts)])
    assert out["measurements"]["extraction_temperature_pinned"] is False


def test_an_EMPTY_denominator_drops_the_rate_instead_of_reporting_ZERO():
    """A rate of 0.0 clears two of the registered thresholds, so an absent one must not be spelled that
    way. `readiness` has a third category for exactly this."""
    counts = {k: 0 for k in _row()["agent_counts"] if k.startswith("n_")}
    counts.update({"levels_derived_by_platform": True, "temperature_pinned": True})
    out = holdout_score.score_rows([_row(agent_counts=counts, n_span_failures=0)])
    for absent in ("value_outside_quote_rate", "span_failure_rate", "level_refusal_rate",
                   "model_level_disagreement_rate"):
        assert absent not in out["measurements"], absent


def test_rows_with_no_quote_check_leave_G3_UNMEASURED_and_SAY_SO():
    row = _row()
    row.pop("n_quote_checked")
    row.pop("n_quote_verbatim")
    out = holdout_score.score_rows([row])
    assert "quote_verbatim_rate" not in out["measurements"]
    assert out["beside_the_gates"]["quote_verbatim_not_checked"] is True
    assert "QUOTE VERBATIM RATE IS ABSENT" in out["note"]


# --- the numbers themselves, against their REGISTERED formulas ----------------------------------------

def test_M4_uses_the_REGISTERED_denominator_and_not_the_one_the_scratchpad_used():
    """The registration says `rejected / (rejected + n_level_records)`. The development number was
    computed as `rejected / (rejected + derived + unverified)`, which is a SUBSET of the kept level
    records -- 1,305 of 1,378 -- so the two formulas gave 0.524 and 0.510 for the same run. This row makes
    the subset differ on purpose, so a scorer that used it would be caught."""
    counts = {**_row()["agent_counts"], "n_level_records": 8, "n_level_derived": 3,
              "n_level_unverified": 1, "n_level_rejected": 4}
    out = holdout_score.score_rows([_row(agent_counts=counts)])
    # The rates are rounded to four places, so the comparison is to that precision -- not approx's
    # default relative tolerance, which would read 0.3333 and 1/3 as different numbers.
    assert out["measurements"]["level_refusal_rate"] == pytest.approx(4 / 12, abs=1e-4)   # registered
    assert out["measurements"]["level_refusal_rate"] != pytest.approx(4 / 8, abs=1e-4)    # the subset


def test_the_rates_over_RECORDS_are_pooled_and_not_a_mean_of_per_report_rates():
    """Pooled and mean differ whenever the reports differ in size, and the difference is the whole content
    of the rule. A ten-record report must not weigh the same as a one-record report."""
    big = {**_row()["agent_counts"], "n_level_records": 100, "n_value_outside_quote": 0}
    small = {**_row()["agent_counts"], "n_level_records": 1, "n_value_outside_quote": 1}
    out = holdout_score.score_rows([_row("big", agent_counts=big), _row("small", agent_counts=small)])
    assert out["measurements"]["value_outside_quote_rate"] == pytest.approx(1 / 101, abs=1e-4)
    assert out["measurements"]["value_outside_quote_rate"] != pytest.approx(0.5, abs=1e-3)


def test_the_two_role_axis_gates_are_MEANS_over_their_OWN_declared_denominators():
    """G2B's denominator is the reports with a non-empty table reading -- a report whose table found
    nothing has no ratio, and filling it in as 0 or 1 would both be inventions."""
    out = holdout_score.score_rows([
        _row("with_table"),
        _row("no_table", structural=[], roles_structural=[], comparison_kind="complementary",
             role_overlap=0.0)])
    assert out["denominators"]["reports_with_a_structural_reading"] == 1
    assert out["measurements"]["agent_covers_structural_roles"] == pytest.approx(1.0)
    # G2 is the mean over ALL reports, which is how it was measured and how it FAILED.
    assert out["measurements"]["agent_vs_structural_role_overlap"] == pytest.approx(0.25)


def test_a_report_with_no_table_reading_is_EXCLUDED_from_the_comparison_kind():
    """Stated in the registration's own denominator: a report with nothing to compare against contributes
    `complementary` by arithmetic rather than by disagreement."""
    out = holdout_score.score_rows([
        _row("a"), _row("b"),
        _row("empty", structural=[], roles_structural=[], comparison_kind="complementary")])
    assert out["denominators"]["eligible_for_comparison_kind"] == 2
    assert out["measurements"]["agent_vs_structural_comparison_kind"] == "partial"


def test_G1_reports_the_STRICT_rule_beside_the_one_the_gate_consumes():
    """The gate is registered with a SCALAR comparison and a source that is a distribution over reports,
    so the aggregation was a choice. Both answers are reported and the disagreement is flagged -- on the
    development set the modal rule says `partial` and the strict rule says `complementary`, because 3 of
    the 21 eligible reports share no role at all."""
    out = holdout_score.score_rows([
        _row("a"), _row("b"), _row("c", comparison_kind="complementary")])
    b = out["beside_the_gates"]
    assert out["measurements"]["agent_vs_structural_comparison_kind"] == "partial"
    assert b["comparison_kind_all_eligible"] == "complementary"
    assert b["comparison_kind_rule_disagrees_with_strict"] is True
    assert b["comparison_kind_distribution"] == {"complementary": 1, "partial": 2}


def test_M2_is_COMPUTED_from_the_cost_table_and_reports_BOTH_paths():
    """It was a literal -- 0.798, commented "before normalisation" and carried unchanged across runs that
    changed what normalises. Computed from its declared source the development value is 0.633, and the
    model path's is four times further from it, so both travel."""
    out = holdout_score.score_rows([_row()])
    assert "unresolved_requirement_rate" in out["measurements"]
    assert "unresolved_requirement_rate_agent_path" in out["beside_the_gates"]
    assert out["denominators"]["distinct_structural_demands"] >= 1


def test_G4_is_read_off_the_CODE_because_twelve_documents_cannot_establish_it():
    """Whether a summary CAN be called over a partial reading without saying so is a property of the
    signatures. Twelve reports that all happened to be read completely would answer nothing."""
    out = holdout_score.score_rows([_row()])
    assert out["measurements"]["summaries_carry_partial_flag"] is True
    assert out["beside_the_gates"]["summaries_carry_partial_flag_problems"] == []
    assert holdout_score.MEASURE_RULES["summaries_carry_partial_flag"]["per_report"].startswith(
        "NOT PER REPORT")


# --- the quote check is re-cut from the source, not taken from the path that made the records ----------

def test_the_verbatim_check_is_run_against_the_DOCUMENT_and_an_EMPTY_quote_is_not_evidence():
    """The empty string is a substring of everything, which is how a blank would score as a citation."""
    text = "The ppGpp module is on for all runs."
    good = extraction.Record(kind="requirement", role="factor:ppgpp_module", value="on",
                             quote="ppGpp module is on", section="Plan", section_kind="plan",
                             path="agent")
    blank = extraction.Record(kind="requirement", role="factor:ppgpp_module", value="on", quote="",
                              section="Plan", section_kind="plan", path="agent")
    invented = extraction.Record(kind="requirement", role="factor:ppgpp_module", value="on",
                                 quote="the ppGpp module was disabled", section="Plan",
                                 section_kind="plan", path="agent")
    assert holdout_score.verbatim_counts([good], text) == {"n_checked": 1, "n_verbatim": 1}
    assert holdout_score.verbatim_counts([blank], text) == {"n_checked": 1, "n_verbatim": 0}
    assert holdout_score.verbatim_counts([invented], text) == {"n_checked": 1, "n_verbatim": 0}
    assert holdout_score.verbatim_counts([good, blank, invented], text)["n_verbatim"] == 1


def test_a_NON_VERBATIM_quote_pulls_G3_BELOW_its_threshold():
    """G3 requires exactly 1.0, so the test that matters is that the scorer can report less than 1.0."""
    out = holdout_score.score_rows([_row(n_quote_checked=10, n_quote_verbatim=9)])
    assert out["measurements"]["quote_verbatim_rate"] == pytest.approx(0.9)
    assert "G3_QUOTES_VERBATIM" in [g["id"] for g in holdout.readiness(out["measurements"])["unmet"]]


# --- G5 is a person, and this module must not become one ---------------------------------------------

def test_the_scorer_does_NOT_invent_the_REVIEWER_and_says_so():
    out = holdout_score.score(
        {"r1": "The ppGpp module is on."},
        client=_StubClient(), mappings_signed_off_by="")
    assert "applied_mappings_signed_off_by" not in out["measurements"]
    assert "Nobody has reviewed the mapping list" in out["g5_note"]


def test_a_SUPPLIED_reviewer_is_passed_through_unchanged():
    out = holdout_score.score({"r1": "The ppGpp module is on."}, client=_StubClient(),
                              mappings_signed_off_by="  A. Reviewer, 2026-11-02  ")
    assert out["mappings_signed_off_by"] == "A. Reviewer, 2026-11-02"


# --- the paid half: a failure there is an environment fact ---------------------------------------------

class _StubClient:
    """A client that answers nothing. The point is the SHAPE of the result, not the records."""

    class messages:                                            # noqa: N801
        @staticmethod
        def create(**kw):
            class R:
                content = [type("B", (), {"type": "text", "text": "[]"})()]
                usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()
                stop_reason = "end_turn"
            return R()


class _AngryClient:
    class messages:                                            # noqa: N801
        @staticmethod
        def create(**kw):
            raise RuntimeError("connection reset")


def test_a_client_that_raises_gives_an_ERROR_row_and_not_an_empty_reading():
    row = holdout_score.row_for("r1", "The ppGpp module is on.", client=_AngryClient())
    # extract_agent catches per-span failures itself, so the row may come back partial rather than
    # errored. Either way what must NOT happen is a clean row with zero records and no sign of trouble.
    assert row.get("error") or row.get("n_span_failures") or not row.get("agent")
    if row.get("error"):
        assert row["about"] == "environment"


def test_read_reports_names_what_it_COULD_NOT_find():
    """The archive is local only, so most machines running this cannot see it. An unreadable file is an
    environment fact; reporting it as an empty corpus is the bug this project keeps finding."""
    out = holdout_score.read_reports(os.path.join(os.path.dirname(__file__), "no_such_dir"),
                                     ["a.md", "b.md"])
    assert out["texts"] == {}
    assert out["missing"] == ["a.md", "b.md"]
    assert "could not read them" in out["note"]


def test_read_reports_returns_the_DIGEST_so_a_row_can_be_checked_against_the_seal(tmp_path):
    p = tmp_path / "r1.md"
    io.open(p, "w", encoding="utf-8").write("# Plan\nThe ppGpp module is on.\n")
    out = holdout_score.read_reports(str(tmp_path), ["r1.md"])
    assert out["missing"] == []
    assert len(out["digests"]["r1.md"]) == 64
    assert out["texts"]["r1.md"].startswith("# Plan")


# --- what the module says about itself ----------------------------------------------------------------

def test_the_module_records_the_THREE_defects_that_forced_it():
    """The audit that produced this module found a stale literal, a wrong denominator and an aggregation
    decided at the console. They are named in the docstring, because a mitigation whose own motivation is
    undocumented is the next thing to be quietly dropped."""
    doc = holdout_score.__doc__
    for marker in ("0.798", "0.633", "0.524", "0.510", "SCALAR"):
        assert marker in doc, marker


# --- the attacks that changed the code ----------------------------------------------------------------

def test_a_RULE_WITH_NO_ARITHMETIC_BEHIND_IT_makes_G6_FAIL(monkeypatch):
    """FOUND BY ATTACKING `coverage`. It compared the registration against MEASURE_RULES, which is a table
    of PROSE -- so a rule entry written without the code to compute it passed the gate while the number
    never appeared in any result. `coverage` now scores SPECIMEN_ROW and checks the number comes out."""
    fake = {"id": "G98_PROSE_ONLY", "asks": "?", "measure": "described_but_never_computed",
            "requires": (">=", 0.5)}
    monkeypatch.setattr(holdout, "READINESS_GATES", holdout.READINESS_GATES + (fake,))
    monkeypatch.setitem(holdout_score.MEASURE_RULES, "described_but_never_computed",
                        {"gate": "G98_PROSE_ONLY", "per_report": "x", "eligible": "all",
                         "aggregate": "pooled", "why": "a rule with nothing behind it, for the test",
                         "chosen_after_seeing_the_numbers": False})
    cov = holdout_score.coverage()
    assert cov["score_produced_by_committed_code"] is False
    assert cov["uncovered"] == []                      # the rule EXISTS, which is why this was invisible
    assert cov["declared_but_not_produced"] == ["described_but_never_computed"]
    assert "prose with nothing behind it" in cov["note"]


def test_the_SPECIMEN_produces_every_number_the_rules_claim():
    """The specimen is what `coverage` rests on, so it must be complete enough to exercise every rule."""
    produced = set(holdout_score.score_rows([holdout_score.SPECIMEN_ROW])["measurements"])
    assert set(holdout_score.MEASURE_RULES) <= produced


def test_THE_SAME_REPORT_TWICE_is_refused_rather_than_weighted_double():
    """FOUND BY ATTACKING `score_rows`: every pooled rate sums counters across rows, so a duplicate counts
    that document twice and nothing in the result would show it."""
    out = holdout_score.score_rows([_row("same"), _row("same")])
    assert out["measurements"] == {}
    assert "appears more than once" in out["refused"]


def test_the_ROLE_OVERLAP_MEAN_reports_its_OWN_denominator():
    """A row whose overlap is unreadable is left out of the mean. A mean over fewer reports than the set
    says it scored is the silent-absence shape wearing a finished-looking number."""
    out = holdout_score.score_rows([_row("a"), _row("b", role_overlap="0.9")])
    assert out["denominators"]["reports"] == 2
    assert out["denominators"]["reports_in_the_role_overlap_mean"] == 1


# --- the seal: is what we just scored what was sealed? ------------------------------------------------

def _seal(tmp_path, held) -> str:
    import json
    p = tmp_path / "HOLDOUT.json"
    io.open(p, "w", encoding="utf-8").write(json.dumps(
        {"frozen_at": "2026-10-29", "n_held_out": len(held), "n_development": 0,
         "held_out": held, "development": {}}))
    return str(p)


def test_an_UNREADABLE_seal_is_UNKNOWN_and_never_a_silent_pass(tmp_path):
    out = holdout_score.check_against_the_seal({"a.md": "ff"}, seal_path=str(tmp_path / "nope.json"))
    assert out["verified"] is None
    assert out["about"] == "environment"


def test_a_DIGEST_THAT_DOES_NOT_MATCH_THE_SEAL_refuses_the_whole_score(tmp_path):
    """The one-shot rule is what makes this matter: an edited or re-exported copy produces a number that
    reads exactly like a held-out result, and afterwards nothing can tell them apart."""
    path = _seal(tmp_path, {"r1.md": "a" * 64})
    out = holdout_score.score({"r1.md": "The ppGpp module is on."}, client=_StubClient(),
                              digests={"r1.md": "b" * 64}, seal_path=path)
    assert out["measurements"] == {}
    assert "do not match the seal" in out["refused"]
    assert out["seal"]["digest_mismatch"] == ["r1.md"]


def test_a_DOCUMENT_NOT_IN_THE_PARTITION_is_refused_too(tmp_path):
    path = _seal(tmp_path, {"r1.md": "a" * 64})
    out = holdout_score.check_against_the_seal({"other.md": "a" * 64}, seal_path=path)
    assert out["verified"] is False
    assert out["not_in_the_seal"] == ["other.md"]


def test_a_MATCHING_digest_verifies_and_names_what_was_left_UNSCORED(tmp_path):
    """Twelve sealed and eleven scored is a partial held-out run, and it must not look like a whole one."""
    path = _seal(tmp_path, {"r1.md": "a" * 64, "r2.md": "c" * 64})
    out = holdout_score.check_against_the_seal({"r1.md": "a" * 64}, seal_path=path)
    assert out["verified"] is True
    assert out["sealed_but_not_scored"] == ["r2.md"]


def test_NO_DIGESTS_SUPPLIED_says_nothing_was_checked(tmp_path):
    out = holdout_score.score({"r1.md": "The ppGpp module is on."}, client=_StubClient())
    assert out["seal"]["verified"] is None
    assert "no digests were supplied" in out["seal"]["note"]


def test_sealed_digests_refuses_a_partition_that_does_not_exist(tmp_path):
    path = _seal(tmp_path, {"r1.md": "a" * 64})
    out = holdout.sealed_digests("made_up", path)
    assert out["digests"] is None
    assert out["about"] == "request"


def test_NO_ELIGIBLE_REPORT_leaves_G1_UNMEASURED_rather_than_FAILED():
    """FOUND BY THE SAME LIVE RUN. With no eligible report the modal kind was the empty string, and `in`
    compares it against (redundant, partial), so the criterion read a set nobody could measure as a FAILED
    gate. Categorical measurements need the same absent-is-not-no rule as the booleans."""
    out = holdout_score.score_rows([_row("a", structural=[], roles_structural=[])])
    assert out["denominators"]["eligible_for_comparison_kind"] == 0
    assert "agent_vs_structural_comparison_kind" not in out["measurements"]
    r = holdout.readiness(out["measurements"])
    assert "G1_INDEPENDENT_CHECK" in [g["id"] for g in r["unmeasured"]]
    assert "G1_INDEPENDENT_CHECK" not in [g["id"] for g in r["unmet"]]
    assert out["beside_the_gates"]["comparison_kind_all_eligible"] is None


# --- the entry point. G6 asks for a committed SCRIPT, so the script is covered too -------------------

def _script_main():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import score_heldout  # noqa: I001, PLC0415  -- imported AFTER the path insert, by necessity

    return score_heldout.main


def test_the_script_REFUSES_an_unreadable_seal_instead_of_scoring_nothing(tmp_path, capsys):
    """"I could not open the seal" must not become "there are no documents". The run does not happen, and
    the exit code says so."""
    rc = _script_main()([str(tmp_path / "nope.json"), str(tmp_path), str(tmp_path / "out.json")])
    assert rc == 1
    assert "REFUSED" in capsys.readouterr().out


def test_the_script_REFUSES_when_the_SEALED_DOCUMENTS_ARE_NOT_THERE(tmp_path, capsys):
    """A machine that cannot see the archive -- which is most of them, the archive being local only --
    must fail by not having the files, not by scoring an empty corpus to a clean sheet."""
    path = _seal(tmp_path, {"r1.md": "a" * 64})
    rc = _script_main()([path, str(tmp_path / "no_reports"), str(tmp_path / "out.json")])
    assert rc == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out and "could not read them" in out


def test_the_script_asks_for_its_arguments_rather_than_defaulting_to_a_path(capsys):
    """Both paths are arguments and neither has a default: the archive is a collaborator's unpublished
    output, and a default path is how a scorer quietly reads the wrong thing."""
    assert _script_main()([]) == 2
    assert "score_heldout.py" in capsys.readouterr().out


# --- G5: a reviewer's sign-off, tied to what they actually saw ----------------------------------------

def _sheet(mappings):
    return {"rows": [{"role": r, "author_wrote": w, "mapped_to": m} for r, w, m in mappings]}


def _signoff_file(tmp_path, mappings, *, name="A. Reviewer", digest=None):
    import hashlib
    triples = sorted([list(t) for t in mappings])
    d = digest or hashlib.sha256(
        json.dumps(triples, sort_keys=True).encode("utf-8")).hexdigest()
    p = tmp_path / "signoff.json"
    io.open(p, "w", encoding="utf-8").write(json.dumps(
        {"signed_off_by": name, "date": "2026-11-02", "mapping_digest": d, "mappings": triples}))
    return str(p)


M1 = ("factor:aa_supply", "Clamped 20 AA", "medium")
M2 = ("factor:medium", "Glucose minimal", "minimal")
M3 = ("factor:ppgpp_module", "OFF (Fixed)", "off")


def test_a_valid_signoff_supplies_G5s_measurement(tmp_path):
    out = holdout_score.read_signoff(_signoff_file(tmp_path, [M1, M2]), _sheet([M1, M2]))
    assert out["signed_off_by"] == "A. Reviewer"
    assert out["intact"] is True and out["n_covered"] == 2 and out["unreviewed"] == []
    assert "G5_MAPPINGS_REVIEWED" in [g["id"] for g in holdout.readiness(
        {"applied_mappings_signed_off_by": out["signed_off_by"]})["met"]]


def test_a_TAMPERED_signoff_yields_NO_NAME():
    """A signature on a worksheet that has since changed means nothing. The recorded mappings must hash
    to the recorded digest or no name is taken from the file at all."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        p = _signoff_file(Path(d), [M1, M2], digest="0" * 64)
        out = holdout_score.read_signoff(p, _sheet([M1, M2]))
    assert out["intact"] is False
    assert out["signed_off_by"] == ""
    assert "drifted from whatever was actually reviewed" in out["note"]


def test_a_mapping_the_signoff_NEVER_COVERED_is_reported_and_not_hidden(tmp_path):
    """On a held-out run the documents may use spellings the reviewer could not have seen -- they were
    sealed. A reviewer who checked two mappings has reviewed two; a third is a gap in the REVIEW, so it is
    listed rather than silently inheriting the name."""
    out = holdout_score.read_signoff(_signoff_file(tmp_path, [M1, M2]), _sheet([M1, M2, M3]))
    assert out["signed_off_by"] == "A. Reviewer"          # the name still stands for what it covered
    assert out["n_covered"] == 2 and out["n_in_front_of_us"] == 3
    assert list(out["unreviewed"]) == [list(M3)] or out["unreviewed"] == [M3]
    assert "were NOT" in out["note"]


def test_an_UNREADABLE_signoff_is_an_ENVIRONMENT_fact_and_not_an_unsigned_one(tmp_path):
    out = holdout_score.read_signoff(str(tmp_path / "nope.json"), _sheet([M1]))
    assert out["signed_off_by"] is None
    assert out["about"] == "environment"
    # And None must not be mistaken for a name by the criterion.
    assert "G5_MAPPINGS_REVIEWED" not in [g["id"] for g in holdout.readiness({})["met"]]


def test_an_UNSIGNED_but_intact_template_gives_no_name(tmp_path):
    """The generated template is intact by construction; what it lacks is a person."""
    out = holdout_score.read_signoff(_signoff_file(tmp_path, [M1], name=""), _sheet([M1]))
    assert out["intact"] is True and out["signed_off_by"] == ""


# --- the worksheet itself -----------------------------------------------------------------------------

def test_the_review_sheet_shows_what_each_mapping_was_chosen_OVER():
    """A reviewer cannot judge a mapping without seeing the alternatives. `Clamped Arg (150 uM)` mapping
    to `medium` rather than `enzymes` is exactly the judgement no mechanical check makes."""
    from cellarium import extraction as ex
    recs = [ex.Record(kind="requirement", role="factor:aa_supply", value="Clamped 20 AA",
                      quote="Clamped 20 AA", section="M", section_kind="plan", path="structural")]
    sheet = ex.mapping_review_sheet(recs)
    assert sheet["n_mappings"] == 1
    row = sheet["rows"][0]
    assert row["mapped_to"] == "medium"
    assert "enzymes" in row["other_members"]
    assert len(sheet["digest"]) == 64


def test_the_sheets_DIGEST_ignores_how_many_times_a_mapping_fired():
    """Re-running on more documents without changing any mapping must keep a signature valid; changing a
    mapping must invalidate it. So the digest covers the triples, not the counts."""
    from cellarium import extraction as ex

    def rec(value, n):
        return [ex.Record(kind="requirement", role="factor:aa_supply", value=value, quote=value,
                          section="M", section_kind="plan", path="structural") for _ in range(n)]
    a = ex.mapping_review_sheet(rec("Clamped 20 AA", 1))
    b = ex.mapping_review_sheet(rec("Clamped 20 AA", 9))
    c = ex.mapping_review_sheet(rec("Endogenous ON", 1))
    assert a["digest"] == b["digest"]
    assert a["digest"] != c["digest"]


def test_the_worksheet_script_REFUSES_to_build_from_the_HELD_OUT_partition(tmp_path, capsys):
    """The worksheet is built by READING the documents, and reading the held-out set before the run is
    the one thing the seal exists to prevent."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import mapping_review  # noqa: I001, PLC0415

    path = _seal(tmp_path, {"r1.md": "a" * 64})
    rc = mapping_review.main([str(tmp_path), path, str(tmp_path / "out.md"), "--partition=held_out"])
    assert rc == 1
    assert "what the seal exists to prevent" in capsys.readouterr().out


# --- what "kept failed" costs, made visible --------------------------------------------------------

def test_a_gate_kept_FAILED_AS_REGISTERED_is_named_as_PERMANENTLY_blocking():
    """G2's threshold turned out unreachable by construction and the registration refuses to retune it.
    The consequence is that `may_break_seal` can never answer yes while G2 counts as unmet -- which is a
    decision about the claim, not a fact for a function to settle, so it is NAMED rather than resolved.
    Surfacing it here means it cannot be discovered by whoever happens to be holding the seal."""
    m = {g["measure"]: (g["requires"][1][0] if g["requires"][0] == "in" else g["requires"][1])
         for g in holdout.READINESS_GATES}
    m["applied_mappings_signed_off_by"] = "A. Reviewer, 2026-11-02"
    for r in holdout.MUST_REPORT:
        m.setdefault(r["measure"], 0.0)
    assert holdout.readiness(m)["may_break_seal"] is True       # everything met: no permanent blocker
    assert holdout.readiness(m)["permanently_unmet"] == []

    m["agent_vs_structural_role_overlap"] = 0.1654              # as measured
    out = holdout.readiness(m)
    assert out["may_break_seal"] is False
    assert out["permanently_unmet"] == ["G2_ROLE_OVERLAP"]
    assert "can never answer yes" in out["note"]
    assert "is NOT\nmade here" in out["note"] or "is NOT made here" in out["note"]
