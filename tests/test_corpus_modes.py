"""The declared corpus modes must match what the manifest actually contains.

MODES_IN_CORPUS is hand-maintained, and running a campaign in a new elongation model invalidates it without
anyone editing capability.py. When it is stale the registry emits "no run in the corpus used it" while such
rows sit in the manifest — a false statement, produced by the component whose entire purpose is to stop
false statements about coverage. This test turns that silent drift into a failing build.

It deliberately does NOT assert a fixed tuple: the point is agreement with the measurement, not a frozen
value. When the probe cannot verify (no shards, or no physical elongation_model column) the test skips
rather than passing, because "could not read" must never be scored as "agrees".
"""
import pytest

from src.cellarium import capability, manifest


def test_corpus_modes_match_manifest():
    probe = manifest.corpus_elongation_modes()
    if not probe.get("verified"):
        pytest.skip(f"manifest could not be verified: {probe.get('why')}")
    assert set(capability.MODES_IN_CORPUS) == set(probe["modes"]), (
        f"capability.MODES_IN_CORPUS is {sorted(capability.MODES_IN_CORPUS)} but the manifest actually "
        f"contains {sorted(probe['modes'])}. A campaign landed in a mode the registry does not know about, "
        f"so every refusal now claims no run used that mode while those rows exist. Update the tuple.")


def test_refusal_prose_follows_the_tuple():
    """corpus_modes_phrase is derived, so it cannot fall behind the tuple it describes."""
    phrase = capability.corpus_modes_phrase()
    for m in capability.MODES_IN_CORPUS:
        assert m in phrase, f"{m} is in MODES_IN_CORPUS but absent from the rendered phrase: {phrase!r}"


def test_refusal_never_claims_a_covered_mode_is_uncovered():
    """A capability held by a mode the corpus now has must not render "no run used it".

    This is the failure the kinetic campaign created: MODES_IN_CORPUS gained "kinetic", and the case-(c)
    branch went on asserting that no kinetic run existed while listing kinetic as a corpus mode in the very
    next clause.
    """
    for cap in capability.CAPABILITIES:
        for mode in cap.holds_in:
            if mode in capability.MODES_IN_CORPUS:
                text = cap.refusal(mode)
                assert "NO run in the corpus" not in text, (
                    f"{cap.key} under {mode}: the corpus HAS {mode} runs, but the refusal claims none do. "
                    f"Rendered: {text[:200]}")


def test_answerable_capability_reports_can_answer_without_a_refusal():
    """The contract Cellwright relies on: can_answer True never carries a refusal."""
    for cap in capability.CAPABILITIES:
        for mode in capability.ELONGATION_MODES:
            r = capability.check(cap.key, mode)
            if r.get("can_answer"):
                assert not r.get("refusal"), f"{cap.key}/{mode} is answerable but carries a refusal"
