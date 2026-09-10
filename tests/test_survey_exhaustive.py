"""WELL-6e — `survey_corpus` claims exhaustiveness, so exhaustiveness is a test, not a sentence in a note.

THE DEFECT THIS CLOSES, found by counting rather than by reasoning. `survey_corpus` is the mandatory first
read and its anti-anchoring mechanism *is* exhaustiveness: it hands the agent every design ranked by
arithmetic, so that attention is not what decides which designs get considered. Each channel then shows its
top 6. Measured on the corpus of 2026-09-10, the whole payload named **29 of 40** reportable designs — the
other eleven appeared nowhere — while the payload's own note described it as a "full-corpus survey".

That is the anchoring bias returning through the door built to keep it out, and it is worse than a plain
omission because the tool asserts the opposite. It also has a specific bite: a design that is quiet on
every channel is a CONTROL, and controls are exactly what a top-N-by-salience ranking discards. Among the
eleven were the full glucose dose ladder, both phosphofructokinase knockouts, and `rRNA_KO:2op` — the
design WELL-6z showed *flips sign* on growth once depth-matched.

WHAT IS ASSERTED HERE, and why it is phrased over the PAYLOAD rather than over any one block: the union of
`by_channel` + `notable` + `lethality` + `quiet_designs` must be every ranked, reportable design. Any future
change to how the ranking truncates, how many channels there are, or how `notable` is capped will keep that
property or fail here. Asserting the roster's contents instead would pin today's corpus and break on the
next run that lands.

WELL-6e also predicted this would arrive at ~10^4 runs. It arrived at 369. The prediction was about payload
size and the mechanism turned out to be channel count — 24 channels x 6 rows is a lot of rows and still a
small slice of the corpus. Worth remembering when the next "we will deal with it at scale" item is written.
"""

from __future__ import annotations

import pytest

from cellarium import survey, tools


@pytest.fixture(scope="module")
def payload() -> dict:
    return tools.survey_corpus()


@pytest.fixture(scope="module")
def reportable() -> set:
    rows, _ = survey.analysis_rows()
    out = {survey.design_key(r) for r in rows if r.get("reportable")}
    if not out:
        pytest.skip("no reportable rows in this checkout, so exhaustiveness is unanswerable here")
    return out


def _named_anywhere(p: dict) -> set:
    """Every design a reader could NAME from the payload — the only definition that matters, since a design
    the agent cannot name is a design it cannot query."""
    seen = {e["design"] for v in p.get("by_channel", {}).values() for e in v.get("ranked", [])}
    seen |= {e["design"] for e in p.get("notable", [])}
    seen |= {e["design"] for e in (p.get("lethality") or {}).get("collapsing_designs", [])}
    seen |= {e["design"] for e in (p.get("quiet_designs") or {}).get("designs", [])}
    return seen


def test_every_ranked_design_is_nameable_from_the_payload(payload, reportable):
    """The invariant. Before `quiet_designs` this failed by eleven."""
    missing = sorted(reportable - _named_anywhere(payload))
    assert not missing, (
        f"{len(missing)} reportable designs appear nowhere in survey_corpus, which calls itself exhaustive: "
        f"{missing}. The agent cannot query a design it was never told exists, so this is the anchoring bias "
        "the tool was built to remove, reintroduced by truncation. Add them to `quiet_designs` rather than "
        "widening every channel's top-N.")


def test_the_quiet_roster_is_exactly_the_complement_and_holds_no_duplicates(payload, reportable):
    """A roster that repeats what the ranking already showed wastes context and reads as a second ranking."""
    q = payload["quiet_designs"]
    names = [e["design"] for e in q["designs"]]
    assert len(names) == len(set(names)) == q["n"], "the quiet roster double-counts"

    elsewhere = set()
    for v in payload["by_channel"].values():
        elsewhere |= {e["design"] for e in v.get("ranked", [])}
    elsewhere |= {e["design"] for e in payload["notable"]}
    overlap = sorted(set(names) & elsewhere)
    assert not overlap, f"these are in the roster AND in a ranking, so they are shown twice: {overlap}"
    assert set(names) <= reportable, "the roster names something that is not a ranked, reportable design"


def test_each_quiet_design_says_how_quiet_rather_than_only_that_it_is(payload):
    """"It did not make a top-6" is a fact about the ranking. `largest_z_anywhere` is a fact about the design,
    and it is what lets a reader tell a genuine null control from something that just missed the cut."""
    for e in payload["quiet_designs"]["designs"]:
        z = e.get("largest_z_anywhere")
        assert z is not None, f"{e['design']} is named but carries no salience at all"
        assert abs(z) < 6.0, f"{e['design']} has |z|={abs(z)} and should have ranked somewhere"
        assert e.get("on_channel"), f"{e['design']} does not say which channel that z was on"


def test_a_misnamed_design_carries_its_honest_name_into_the_quiet_tier_too(payload):
    """The label-integrity guarantee must not have a hole where the ranking does not reach.

    `KO:valS` is really `TU_KO:holC-valS` and `rRNA_KO:2op` really removes 2 of 7 operons. Both are quiet,
    so before this roster existed their true labels travelled nowhere — the one tier where a wrong name
    would go unchallenged is the tier nobody looks at.
    """
    from cellarium import factors
    for e in payload["quiet_designs"]["designs"]:
        ident = None
        try:
            ident = factors.identity(e["design"])
        except Exception:
            continue
        if ident and ident.get("label_integrity") not in (None, "ok"):
            assert e.get("true_label") == ident["true_label"], (
                f"{e['design']} is {ident['label_integrity']} but the roster does not carry its true label")


def test_the_note_no_longer_claims_something_the_payload_does_not_do(payload):
    """The note is read by the model on every first call, so a false word in it is a false premise for the
    whole investigation. It said "full-corpus survey" while omitting eleven designs."""
    note = payload["note"]
    assert "full-corpus survey" not in note, "the note reasserts exhaustiveness instead of describing it"
    assert "quiet_designs" in note, "the note must point at where the rest of the corpus is named"
    assert "nothing is silently omitted" in note
