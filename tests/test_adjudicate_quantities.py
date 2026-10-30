"""Stage 1 of the adjudicator: which quantity a claim names, and whether this corpus records it.

The registry's MEASURABLE half is derived from `instrument.CHANNELS` — the one declared channel namespace,
the same list the tool schemas take their `channel` enums from — so a channel added there becomes
adjudicable without an edit here.

The other half is a hand-written map from the words a document uses to the channel it means, and saying so
is the point. Deriving a namespace does not derive a vocabulary: "does ppGpp rise" has to be connected to
`ppgpp_conc` by somebody, and pretending that mapping is derived would move the hand-typing one layer down
and call it automatic. It is declared, it is audited for entries that can never fire, and it is frozen
against the held-out reports.

THREE VALUES, NOT TWO. `recorded` (a channel exists), `not_recorded` (the quantity is a real thing this
corpus has no channel for — ribosome stalling, polysome occupancy), and `unresolved` (nothing matched, so
the registry has no opinion). Collapsing the last two is the error that produced a wrong headline: a
quantity nobody mapped is not a quantity the model lacks.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import adjudicate, instrument  # noqa: E402


def test_the_measurable_half_is_derived_from_the_one_declared_namespace():
    assert adjudicate.channels() == dict(instrument.CHANNELS)
    assert set(adjudicate.channels()) >= {"growth_rate", "ppgpp_conc", "fraction_trna_charged"}


def test_the_vocabulary_is_declared_and_every_entry_can_fire():
    """An entry pointing at a channel that does not exist is dead: it can never resolve, and its absence
    from the output reads as the document not having mentioned that quantity."""
    vocab = adjudicate.CHANNEL_VOCABULARY
    assert vocab, "the claim vocabulary must be declared, not inferred"
    unknown = {ch for ch in vocab if ch not in adjudicate.channels()}
    assert not unknown, f"vocabulary maps to channels that do not exist: {unknown}"
    assert all(words for words in vocab.values())


def test_the_two_vocabularies_do_not_overlap():
    """A phrase that is both a channel word and a known-unrecorded word would resolve by table order."""
    recorded = {w for ws in adjudicate.CHANNEL_VOCABULARY.values() for w in ws}
    assert not (recorded & set(adjudicate.NOT_RECORDED_QUANTITIES))


@pytest.mark.parametrize("phrase,channel", [
    ("growth rate should fall by 20%", "growth_rate"),
    ("the doubling time lengthens", "growth_rate"),
    ("ppGpp accumulates within two minutes", "ppgpp_conc"),
    ("the charged fraction of leucine tRNA drops", "fraction_trna_charged"),
    ("ribosome concentration declines", "ribosome_conc"),
    ("RelA levels rise", "rela_conc"),
    ("dry mass per cell increases", "dry_mass"),
])
def test_a_recorded_quantity_resolves_to_its_channel(phrase, channel):
    out = adjudicate.resolve_quantity(phrase)
    assert out["status"] == "recorded" and out["channel"] == channel
    assert out["matched"] and out["matched"] in phrase.lower()


@pytest.mark.parametrize("phrase,quantity", [
    ("stalling must be monitored by ribosome profiling", "ribosome profiling"),
    ("polysome occupancy shifts toward monosomes", "polysome"),
    ("we will measure the elongation pause duration", "pause"),
])
def test_a_known_but_unrecorded_quantity_says_not_recorded_and_names_itself(phrase, quantity):
    out = adjudicate.resolve_quantity(phrase)
    assert out["status"] == "not_recorded"
    assert out["channel"] is None
    assert quantity in out["matched"]
    assert out["reason"] == "channel_not_recorded"       # the existing code, not a new one
    assert out["about"] == "corpus"                      # this IS evidence: about coverage


def test_an_unmapped_phrase_is_unresolved_and_NOT_not_recorded():
    """The collapse that produced a wrong headline. "the model will be more robust" names no quantity at
    all; reporting it as a quantity the corpus lacks would be an absence invented by the registry."""
    out = adjudicate.resolve_quantity("the model will be more robust and more biologically faithful")
    assert out["status"] == "unresolved"
    assert out["channel"] is None and out["matched"] is None
    assert out["about"] == "request"                     # the registry has no opinion; nothing about biology
    assert "unresolved" in out["note"].lower() or "no opinion" in out["note"].lower()


def test_resolution_is_case_insensitive():
    a = adjudicate.resolve_quantity("CHARGED FRACTION of tRNA")
    assert a["status"] == "recorded" and a["channel"] == "fraction_trna_charged"


def test_the_longest_match_within_one_channel_wins():
    """`rela` and `rela level` both map to rela_conc. The longer must be reported, because the quote is
    what a reader audits the verdict against and the shorter one is a fragment of it.

    The two must also count as ONE quantity rather than two, or every mention of a longer phrase would come
    back `ambiguous` with itself."""
    out = adjudicate.resolve_quantity("RelA level rises sharply")
    assert out["status"] == "recorded" and out["channel"] == "rela_conc"
    assert out["matched"] == "rela level"


def test_a_phrase_naming_two_quantities_is_ambiguous_not_the_first_one():
    """'the growth rate of ppGpp synthesis' names two declared quantities. Choosing the first by table
    order is exactly the silent reduction `ambiguous` exists to prevent."""
    out = adjudicate.resolve_quantity("the growth rate of ppGpp synthesis")
    assert out["status"] == "ambiguous" and out["matched"] is None
    assert {c["channel"] for c in out["candidates"]} == {"growth_rate", "ppgpp_conc"}


def test_every_candidate_is_returned_when_a_phrase_names_more_than_one():
    """A sentence naming two quantities must not be silently reduced to the first. The adjudicator needs to
    refuse an ambiguous claim, which it cannot do if the registry has already chosen."""
    out = adjudicate.resolve_quantity("growth rate falls while ppGpp rises")
    assert out["status"] == "ambiguous"
    assert {c["channel"] for c in out["candidates"]} == {"growth_rate", "ppgpp_conc"}
    assert out["channel"] is None


def test_bad_input_is_an_argument_error():
    for bad in (None, "", 17, "   "):
        out = adjudicate.resolve_quantity(bad)
        assert out["status"] == "error", bad


def test_a_channel_with_no_vocabulary_is_reported_rather_than_hidden():
    """Coverage of the registry over its own namespace, so "the document never mentioned it" and "we have no
    words for it" stay distinguishable."""
    rep = adjudicate.quantity_coverage()
    assert rep["n_channels"] == len(adjudicate.channels())
    assert set(rep["channels_without_vocabulary"]) == (
        set(adjudicate.channels()) - set(adjudicate.CHANNEL_VOCABULARY))
    assert rep["n_not_recorded_quantities"] == len(adjudicate.NOT_RECORDED_QUANTITIES)
