"""The generated limits benchmark must be answerable and correctly keyed, or its score means nothing.

The defect these were written against, found by reading the first generated batch rather than by trusting it:
the mode was not in the question text, so ONE sentence appeared three times carrying `refuse` / `answer` /
`refuse` depending on which cell produced it. An agent cannot know which was meant, so those items measure
guessing, not limits — and they would have depressed every arm's score equally, which is the kind of noise
that looks like a finding.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import gen_limits_questions as G  # noqa: E402

from cellarium import capability as C  # noqa: E402


def test_no_question_text_carries_two_different_answer_keys():
    """THE defect. If one `ask` maps to both verdicts, the item is unanswerable by construction."""
    by_ask = collections.defaultdict(set)
    for q in G.generate(len(G.FRAMINGS)):
        by_ask[q["ask"]].add(q["required"])
    bad = {a: v for a, v in by_ask.items() if len(v) > 1}
    assert not bad, f"{len(bad)} question(s) carry more than one answer key, e.g. {list(bad)[:1]}"


def test_every_non_default_mode_is_named_in_the_text():
    for q in G.generate(1):
        if q["mode"] != C.DEFAULT_MODE:
            assert G._MODE_CLAUSE[q["mode"]].strip()[:20] in q["ask"], (
                f"{q['id']} does not tell the reader which elongation model it is about")


def test_the_key_matches_the_registry_EXCEPT_where_coverage_overrides_it():
    """Generator and scorer must not drift silently — but they DO differ in one defined place, and the test
    pins exactly where. The registry says "representable"; the benchmark asks "answerable". A quantity that is
    represented, in a mode the corpus has, but with no run carrying the needed perturbation is a decline."""
    overrides = []
    for q in G.generate(1):
        cap = next(c for c in C.CAPABILITIES if c.key == q["capability"])
        usable = cap.present and q["mode"] in cap.holds_in and q["mode"] in C.MODES_IN_CORPUS
        registry_says = "answer" if usable else "refuse"
        if q["required"] != registry_says:
            overrides.append((q["capability"], q["mode"], q["kind"]))
            assert q["kind"] == "no_corpus_data", (
                f"{q['id']} diverges from the registry for a reason other than coverage")
            assert registry_says == "answer" and q["required"] == "refuse", (
                "coverage may only turn an answer into a decline, never the reverse")
    assert overrides, "no cell exercises the coverage override — has the corpus changed?"


def test_the_coverage_override_is_the_cell_the_pilot_found():
    """The pilot's one contested miss. If this stops being nutrient_shift_timelines/kinetic, either a kinetic
    timeline run landed (good — regenerate) or the coverage table drifted (check it)."""
    over = [(q["capability"], q["mode"]) for q in G.generate(1) if q["kind"] == "no_corpus_data"]
    assert over == [("nutrient_shift_timelines", "kinetic")], over


def test_coverage_is_read_from_the_corpus_not_hardcoded():
    """INJECTION. Empty the coverage map and the override must spread, not stay put — otherwise the stratum is
    a constant wearing the shape of a measurement."""
    real = G._coverage_cache
    try:
        G._coverage_cache = {"steady_state": set(), "kinetic": set()}
        kinds = {q["kind"] for q in G.generate(1)}
        assert "no_corpus_data" in kinds
        n = sum(1 for q in G.generate(1) if q["kind"] == "no_corpus_data")
        assert n > 1, "coverage did not react to an emptied corpus — it is not reading it"
    finally:
        G._coverage_cache = real


def test_the_cell_census_is_what_the_plan_assumed():
    """Pins the numbers the budget was built on. 27 cells, and a HEADLINE of 18 once the coarse_kinetic
    column — refusals for lack of runs, not for lack of representation — is set aside."""
    items = G.generate(1)
    st = G.census(items)
    assert st["n_cells"] == 27
    assert st["by_required"] == {"refuse": 18, "answer": 9}
    assert st["headline_items"] == 17
    assert st["headline_by_required"] == {"refuse": 8, "answer": 9}
    assert st["by_stratum"]["no_corpus_data"] == 1


def test_the_easy_stratum_is_labelled_and_reported_separately():
    st = G.census(G.generate(1))
    assert st["by_stratum"]["no_corpus_mode"] == 9
    assert "coverage, not limits" in st["note"]


def test_ids_are_unique_and_self_describing():
    ids = [q["id"] for q in G.generate(len(G.FRAMINGS))]
    assert len(ids) == len(set(ids))
    assert all(i.count("__") == 2 for i in ids)


def test_framings_change_the_wording_and_never_the_key():
    per_cell = collections.defaultdict(list)
    for q in G.generate(len(G.FRAMINGS)):
        per_cell[(q["capability"], q["mode"])].append(q)
    for cell, qs in per_cell.items():
        assert len({q["required"] for q in qs}) == 1, f"framings changed the answer key for {cell}"
        assert len({q["ask"] for q in qs}) == len(qs), f"two framings produced identical text for {cell}"


def test_more_framings_than_exist_is_clamped_not_crashed():
    assert G.census(G.generate(999))["framings_per_cell"] == len(G.FRAMINGS)
    assert G.census(G.generate(0))["framings_per_cell"] == 1
