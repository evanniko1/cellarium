"""PLAT-1 — the post-hoc claim check, and the four ways it could be worse than useless.

A provenance guard fails in more interesting ways than it succeeds, and each of these is a real failure this
project has met somewhere else:

  1. It passes when it could not run. Reporting an unavailable check as a pass is the silent-absence bug
     class, and it is the reason `could_not_verify` is a distinct verdict rather than a quiet `grounded`.
  2. It grounds a claim on a coincidence. The rejected design (PLAT-R1) asked whether the token appears
     anywhere in the serialized tool output, so a seed, an index or a synthetic placeholder would pass.
     Here a mention must resolve to the MANIFEST and then to what this turn read.
  3. It rewrites the sentence. Repairing prose hides the failure instead of recording it, so the original
     text must always survive verbatim.
  4. It cries wolf. An annotation on a correctly-cited answer, or on "I did NOT read X", trains the reader
     to skip the annotation — and then the one that matters is skipped too.

The corpus half is stubbed rather than read from the manifest: these tests are about the PREDICATE, and a
predicate tested against whatever happens to be on disk today is a predicate that changes meaning when the
corpus does.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import reconcile, tools  # noqa: E402

CORPUS = {"available": True,
          "designs": {"gene_knockout/KO:argS", "gene_knockout/KO:pfkA", "wildtype/basal"},
          "ids": {"ko_argS_s0", "ko_pfkA_s1", "wt_basal_s0"}}


@pytest.fixture(autouse=True)
def _fresh_turn():
    reconcile.start_turn()
    yield
    reconcile.start_turn()


# ---------------------------------------------------------------------------------------------------------
# (a) The execution envelope.
# ---------------------------------------------------------------------------------------------------------

def test_every_tool_is_classified_as_a_measurement_or_explicitly_not():
    """The exhaustiveness invariant, same shape as `test_registry.unclassified_tools`. A tool added later must
    force a one-line decision — "does this read the corpus?" — rather than defaulting into being able to
    ground a claim."""
    missing = reconcile.unclassified_tools([t["name"] for t in tools.TOOLS])
    assert not missing, (
        f"{len(missing)} tool(s) are neither MEASUREMENT_TOOLS nor NOT_A_MEASUREMENT: {missing}. Decide "
        f"whether each reads THIS corpus; if not, add it with the reason it is not a measurement.")


def test_no_tool_is_classified_both_ways():
    overlap = set(reconcile.NOT_A_MEASUREMENT) & set(reconcile.MEASUREMENT_TOOLS)
    assert not overlap, overlap


def test_a_prediction_carries_a_marker_saying_it_is_not_a_measurement():
    """`viability_surrogate` returns a probability for a design that was never run. On the wire it is a float
    like any other, which is exactly the confusion the marker exists to prevent."""
    out = reconcile.mark_non_measurement("viability_surrogate", {"p_viable": 0.81})
    assert out["not_a_measurement"] and "PREDICTION" in out["not_a_measurement"]


def test_the_marker_names_the_other_model_for_an_fba_result():
    """An FBA number is from iML1515, a different model entirely. "FBA says the knockout grows" and "the
    simulation says the knockout grows" are different claims and must not read the same."""
    out = reconcile.mark_non_measurement("fba_gene_knockout", {"growth": 0.4})
    assert "iML1515" in out["not_a_measurement"]


def test_a_real_corpus_read_is_left_alone():
    out = reconcile.mark_non_measurement("read_series", {"series": [1, 2, 3]})
    assert "not_a_measurement" not in out


def test_an_errored_call_is_not_stamped():
    """An error is already an error; adding "this is not a measurement" to it says nothing and buries the
    message the model needs to act on."""
    out = reconcile.mark_non_measurement("fba_growth", {"error": "no model"})
    assert "not_a_measurement" not in out


def test_the_marker_reaches_the_model_through_dispatch():
    """Tested at the boundary the AGENT calls. A marker that never leaves the helper is a marker the model
    cannot obey — the same failure `test_agent_elongation_axis` caught for the elongation mode."""
    out = tools.dispatch("system_resources", {})
    if out.get("error"):
        pytest.skip(out["error"])
    assert out.get("not_a_measurement")


# ---------------------------------------------------------------------------------------------------------
# (b) Reconciliation. The predicate.
# ---------------------------------------------------------------------------------------------------------

def test_a_design_the_turn_never_read_is_caught():
    reconcile.record_call("read_series", {"design": "gene_knockout/KO:argS", "series": [1]})
    r = reconcile.reconcile("ppGpp falls in gene_knockout/KO:pfkA relative to wildtype/basal.", corpus=CORPUS)
    assert r["verdict"] == "unbacked_claims"
    flagged = {u["mention"] for u in r["unbacked"]}
    assert "gene_knockout/KO:pfkA" in flagged and "wildtype/basal" in flagged
    assert "gene_knockout/KO:argS" not in flagged, "the design that WAS read must not be flagged"


def test_a_correctly_cited_claim_is_not_flagged():
    """The false positive that would get this switched off. An answer that cites only what it read must come
    back clean, and the annotation must be empty — not a reassuring banner."""
    reconcile.record_call("read_series", {"design": "gene_knockout/KO:argS", "series": [1]})
    r = reconcile.reconcile("In gene_knockout/KO:argS, charging falls.", corpus=CORPUS)
    assert r["verdict"] == "grounded" and not r["unbacked"]
    assert reconcile.annotation(r) == ""


def test_a_token_that_is_not_a_corpus_identifier_is_not_a_claim():
    """PLAT-R1's correction, as a test. The haystack is the CORPUS: prose mentioning `argS`, a file path or a
    library name is not asserting a run, and flagging it would bury the real findings."""
    r = reconcile.reconcile("The argS story matches Ahn-Horst 2022; see src/cellarium/rigor.py.", corpus=CORPUS)
    assert r["verdict"] == "no_corpus_claims", r


def test_an_explicitly_disclaimed_mention_is_not_flagged():
    """"I did not examine gene_knockout/KO:pfkA" names a design the turn never read — correctly, and while
    saying so. Flagging it would train the reader to ignore the annotation."""
    reconcile.record_call("read_series", {"design": "gene_knockout/KO:argS", "series": [1]})
    r = reconcile.reconcile("I did not examine gene_knockout/KO:pfkA this turn.", corpus=CORPUS)
    assert r["verdict"] in ("grounded", "no_corpus_claims"), r
    assert not r["unbacked"]


def test_a_run_id_is_checked_as_well_as_a_design():
    reconcile.record_call("read_series", {"id": "ko_argS_s0", "series": [1]})
    r = reconcile.reconcile("Seed ko_pfkA_s1 shows the same drop.", corpus=CORPUS)
    assert [u["kind"] for u in r["unbacked"]] == ["run_id"]


def test_the_same_mention_is_reported_once():
    """Six sentences about one unread design is one finding, not six. A list long enough to scroll past is a
    list nobody reads."""
    r = reconcile.reconcile("wildtype/basal is the reference. wildtype/basal has 26 seeds. "
                            "Compare against wildtype/basal.", corpus=CORPUS)
    assert len(r["unbacked"]) == 1


def test_a_failed_tool_call_reads_nothing():
    """An error carries a design key in its arguments and no data. Counting it as a read would ground a claim
    on a call that returned nothing — the inverse of the bug being fixed."""
    reconcile.record_call("read_series", {"design": "gene_knockout/KO:argS", "error": "no such channel"})
    r = reconcile.reconcile("gene_knockout/KO:argS shows a clear drop.", corpus=CORPUS)
    assert r["verdict"] == "unbacked_claims"


def test_a_non_measurement_tool_does_not_ground_a_claim():
    """PLAT-R1's second binding correction: a result with a synthetic or unverified provenance must fail BY
    CONSTRUCTION rather than be eligible to ground a number. An FBA call naming a design is not a corpus read
    of it, however many identifiers it echoes back."""
    reconcile.record_call("fba_gene_knockout", {"design": "gene_knockout/KO:argS", "growth": 0.4})
    r = reconcile.reconcile("gene_knockout/KO:argS grows slowly.", corpus=CORPUS)
    assert r["verdict"] == "unbacked_claims"
    assert r["non_measurement_calls"] == {"fba_gene_knockout": 1}


# ---------------------------------------------------------------------------------------------------------
# (c) Annotate, never rewrite.  (d) Fail closed.
# ---------------------------------------------------------------------------------------------------------

def test_the_original_prose_survives_verbatim():
    """Silently repairing the sentence hides the failure instead of recording it. The answer the model wrote
    must always be a prefix of what the user sees."""
    reconcile.record_call("read_series", {"design": "gene_knockout/KO:argS", "series": [1]})
    prose = "ppGpp falls in gene_knockout/KO:pfkA."
    out = reconcile.check_and_annotate(prose)
    assert out.startswith(prose), "the check rewrote the answer instead of annotating it"
    assert len(out) > len(prose), "an unbacked claim produced no note at all"


def test_the_note_names_the_claim_and_what_was_read():
    reconcile.record_call("read_series", {"design": "gene_knockout/KO:argS", "series": [1]})
    note = reconcile.annotation(reconcile.reconcile("Look at gene_knockout/KO:pfkA.", corpus=CORPUS))
    assert "gene_knockout/KO:pfkA" in note, "the note does not say WHICH claim"
    assert "gene_knockout/KO:argS" in note, "the note does not say what WAS read"


def test_an_unrecorded_turn_reports_that_it_could_not_verify():
    """FAIL CLOSED. If nothing was recorded the check cannot say the answer is fine, and it must not."""
    reconcile._turn.clear()
    r = reconcile.reconcile("gene_knockout/KO:pfkA is lethal.", corpus=CORPUS)
    assert r["verdict"] == "could_not_verify"
    assert "unverified" in reconcile.annotation(r).lower()


def test_an_unreadable_manifest_reports_that_it_could_not_verify():
    r = reconcile.reconcile("anything", corpus={"available": False, "designs": set(), "ids": set()})
    assert r["verdict"] == "could_not_verify"


def test_no_verdict_is_ever_the_word_verified_when_the_check_did_not_run():
    r = reconcile.reconcile("x", corpus={"available": False, "designs": set(), "ids": set()})
    assert "verified" not in r["verdict"] or r["verdict"] == "could_not_verify"


def test_the_check_never_breaks_the_answer():
    """A provenance check that can raise is worse than the absence it guards against — the turn's whole
    answer would be lost to a bookkeeping bug."""
    import unittest.mock as mock
    with mock.patch.object(reconcile, "reconcile", side_effect=RuntimeError("boom")):
        assert reconcile.check_and_annotate("the answer") == "the answer"


def test_it_can_be_switched_off_but_is_on_by_default(monkeypatch):
    """On by default is the decision: a guard against silent absence that is itself off by default guards
    nothing. The escape hatch exists for evals that assert on exact answer text."""
    monkeypatch.delenv("CELLARIUM_RECONCILE", raising=False)
    assert reconcile.enabled() is True
    monkeypatch.setenv("CELLARIUM_RECONCILE", "0")
    assert reconcile.enabled() is False


def test_the_durable_ledger_state_is_reported_not_assumed(monkeypatch):
    """The deliberate deviation from the spec, pinned. The check runs off an in-memory turn record so it is
    not disabled by default, and it says out loud whether the DURABLE ledger is on — rather than letting a
    reader assume the finding was persisted."""
    r = reconcile.reconcile("x", corpus=CORPUS)
    assert "durable_ledger" in r


# ---------------------------------------------------------------------------------------------------------
# The wiring.
# ---------------------------------------------------------------------------------------------------------

def test_the_agent_starts_a_turn_and_checks_on_the_way_out():
    """Both exits matter. The forced-synthesis path — budget spent, tools disabled, model writing a
    conclusion under pressure — is the likelier place for an ungrounded claim, and it is a different return
    statement."""
    import inspect
    src = inspect.getsource(__import__("src.cellarium.agent", fromlist=["agent"]).converse)
    assert "reconcile.start_turn(" in src
    assert src.count("reconcile.check_and_annotate") == 2, (
        "both converse() exits must reconcile — the normal one and the forced synthesis")


def test_dispatch_records_and_stamps_in_one_place():
    """One funnel: a tool added later participates without remembering to."""
    import inspect
    src = inspect.getsource(tools.dispatch)
    assert "reconcile.mark_non_measurement" in src and "reconcile.record_call" in src


def test_a_follow_up_turn_keeps_what_earlier_turns_read():
    """The cry-wolf case, found by running the check rather than by reasoning about it. Scoped strictly per
    turn, "as shown above, KO:argS falls" names a design read in turn 1 and is annotated in turn 2 — every
    time, until the reader stops looking at annotations."""
    reconcile.start_turn(fresh=True)
    reconcile.record_call("read_series", {"design": "gene_knockout/KO:argS", "series": [1]})
    reconcile.start_turn(fresh=False)                       # the user asks a follow-up
    r = reconcile.reconcile("As shown above, gene_knockout/KO:argS falls.", corpus=CORPUS)
    assert r["verdict"] == "grounded", r


def test_a_new_conversation_does_not_inherit_the_last_one():
    """The other half. Grounding must not leak across conversations, or the check reports a claim as backed
    by evidence the user never saw."""
    reconcile.start_turn(fresh=True)
    reconcile.record_call("read_series", {"design": "gene_knockout/KO:argS", "series": [1]})
    reconcile.start_turn(fresh=True)
    r = reconcile.reconcile("gene_knockout/KO:argS falls.", corpus=CORPUS)
    assert r["verdict"] == "unbacked_claims", r


def test_the_agent_only_starts_fresh_on_a_conversations_first_turn():
    import inspect
    src = inspect.getsource(__import__("src.cellarium.agent", fromlist=["agent"]).converse)
    assert "reconcile.start_turn(fresh=len(messages) <= 1)" in src
