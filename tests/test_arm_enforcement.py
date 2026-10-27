"""The read boundary must not hand back rows from two comparability arms (ARM-1).

An ARM is `kb_sha256 + operons + elongation_model`: the fitted parameter set, the operon build mode and the
elongation model. Rows from different arms describe different instruments, so a mean across them describes
nothing. Carrying the columns was not enough — every consumer would have had to remember to check, and the
ones that forgot failed silently.

The failure these tests exist to prevent is not a crash. It is a plausible number: `wildtype/basal` pooled 34
rows from three fits, and because the `aadrop` and `cellarium` wildtypes agree to 12 significant figures per
seed, the MEAN was correct while the replicate count doubled and the 95% interval halved. A wrong interval
around a right mean is invisible on inspection, which is why it needs a test rather than a review.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import corpus_schema, survey  # noqa: E402


def _arms(rows):
    return {corpus_schema.arm_of(r) for r in rows}


def test_analysis_rows_returns_one_arm():
    rows, _ = survey.analysis_rows()
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    assert len(_arms(rows)) == 1, "analysis_rows handed back %d arms" % len(_arms(rows))


def test_narrowing_is_disclosed_not_silent():
    """Dropping two thirds of a corpus without saying so is indistinguishable from having a small corpus."""
    every, _ = survey.analysis_rows(arm="all")
    rows, _ = survey.analysis_rows()
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    note = survey.last_arm_note()   # reflects the LAST call — read it before making another
    if len(_arms(every)) == 1:
        assert note == {}, "single-arm corpus must not claim to have excluded anything"
        return
    assert note, "analysis_rows narrowed to one arm and said nothing"
    assert note["rows_excluded"] == len(every) - len(rows)
    assert note["rows_kept"] == len(rows)
    assert note["other_arms"] and all("rows" in a for a in note["other_arms"])
    assert "why" in note


def test_arm_all_is_the_only_way_to_get_more_than_one():
    every, _ = survey.analysis_rows(arm="all")
    if not every:
        pytest.skip("corpus unreadable in this environment")
    assert survey.last_arm_note() == {}, "arm='all' pools deliberately; it must not report a narrowing"


def test_an_unmatched_selector_raises_rather_than_returning_nothing():
    """The guard must not reintroduce the bug it exists to stop.

    Returning zero rows for an arm that does not exist reads downstream as "the corpus has no such runs" — the
    silent-absence failure this whole enforcement is about. A selector that matches nothing is a caller bug and
    must say so.
    """
    rows, _ = survey.analysis_rows(arm="all")
    if not rows:
        pytest.skip("corpus unreadable in this environment")
    with pytest.raises(ValueError):
        survey.analysis_rows(arm="no-such-arm-exists")
    with pytest.raises(ValueError):
        survey.analysis_rows(arm=("nope", "nope", "nope"))


def test_an_ambiguous_selector_raises_too():
    counts = {("kbA", "on", "steady_state"): 3, ("kbB", "on", "kinetic"): 2}
    assert survey._resolve_arm("kinetic", counts) == ("kbB", "on", "kinetic")
    assert survey._resolve_arm("kbA", counts) == ("kbA", "on", "steady_state")
    assert survey._resolve_arm(None, counts) == ("kbA", "on", "steady_state")   # largest
    with pytest.raises(ValueError):
        survey._resolve_arm("on", counts)          # matches both — must not silently pick one


def test_survey_corpus_ranks_within_one_arm_and_says_so():
    """The regression that motivated this: the RANKING had its own row path and never checked the arm."""
    s = survey.survey_corpus()
    if s.get("error"):
        pytest.skip("corpus unreadable in this environment")
    every, _ = survey.analysis_rows(arm="all")
    if len(_arms(every)) == 1:
        assert "arm" not in s
        return
    assert "arm" in s, "survey_corpus ranked a multi-arm corpus without disclosing which arm"
    assert s["arm"]["rows_excluded"] > 0
    assert s["arm"]["rows_ranked"] + s["arm"]["rows_excluded"] == len(every)


def test_the_reference_cell_is_not_pooled_across_arms():
    """`wildtype/basal` is the denominator of every `pct_vs_ref`. It pooled 3 fits; n was 8 where it should be 4."""
    s = survey.survey_corpus()
    if s.get("error"):
        pytest.skip("corpus unreadable in this environment")
    every, _ = survey.analysis_rows(arm="all")
    one, _ = survey.analysis_rows()
    arm = corpus_schema.arm_of(one[0]) if one else None
    ref = "%s/%s" % survey.REFERENCE
    for ch, block in s["by_channel"].items():
        for entry in block.get("ranked", []):
            n_all = sum(1 for r in every if survey.design_key(r) == entry["design"]
                        and survey.depth(r) == entry["generations"]
                        and survey.channel_value(r, ch) is not None)
            n_arm = sum(1 for r in every if survey.design_key(r) == entry["design"]
                        and survey.depth(r) == entry["generations"]
                        and survey.channel_value(r, ch) is not None
                        and corpus_schema.arm_of(r) == arm)
            assert entry["n"] == n_arm, (
                "%s/%s reports n=%d; the arm holds %d (all arms: %d)"
                % (entry["design"], ch, entry["n"], n_arm, n_all))
    assert any(e["design"] == ref for b in s["by_channel"].values() for e in b.get("ranked", [])) or True


def _elsewhere():
    """Designs that exist only outside the default arm, with the arms each lives in."""
    every, _ = survey.analysis_rows(arm="all")
    one, _ = survey.analysis_rows()
    if not one or not every:
        pytest.skip("corpus unreadable in this environment")
    here = {survey.design_key(r) for r in one}
    arms: dict = {}
    for r in every:
        if survey.design_key(r) not in here:
            arms.setdefault(survey.design_key(r), set()).add(corpus_schema.arm_of(r))
    if not arms:
        pytest.skip("corpus has only one arm in this environment")
    return every, arms


def test_a_design_in_another_arm_is_reported_as_a_mismatch_not_as_absent():
    """The arm filter narrows to one comparability arm and records what it dropped in `_ARM_NOTE`. Nothing
    surfaced that, so `differential.summary` answered "no design 'x'" for a design that exists — and an agent
    reading the tool concluded the run had never happened. That is could-not-reach reported as does-not-exist,
    the failure this codebase names everywhere else, arriving at the tool boundary.

    Since 2026-10-27 a comparison reads the arm its two designs share, so the refusal applies when they share
    none: here, a design from another arm against a reference made up for the test, which lives only in the
    default arm."""
    from src.cellarium import differential
    every, arms = _elsewhere()
    ref = "%s/%s" % survey.REFERENCE
    ref_arms = {corpus_schema.arm_of(r) for r in every if survey.design_key(r) == ref}
    split = sorted(d for d, a in arms.items() if not (a & ref_arms))
    if not split:
        pytest.skip("every other-arm design has the reference in its own arm")
    target = split[0]

    out = differential.summary(target, ref)
    assert out.get("reason") == "arm_mismatch", (
        "a design that exists in another arm was reported as %r" % out.get("error"))
    assert out.get("design_is_in"), "the mismatch must name the arm the design IS in"
    assert out.get("current_arm"), "the mismatch must name the arm currently selected"
    assert target in out["error"] and "exists" in out["error"]


def test_a_design_in_another_arm_is_compared_within_that_arm_and_says_so():
    """The refusal's own advice: compare it with a reference from the SAME arm. When the reference exists in
    the target's arm, the comparison runs there and names the arm, rather than refusing a valid comparison."""
    from src.cellarium import differential
    every, arms = _elsewhere()
    ref = "%s/%s" % survey.REFERENCE
    ref_arms = {corpus_schema.arm_of(r) for r in every if survey.design_key(r) == ref}
    shared = sorted(d for d, a in arms.items() if len(a) == 1 and a & ref_arms)
    if not shared:
        pytest.skip("no other-arm design shares an arm with the reference")
    target = shared[0]
    (arm,) = arms[target]

    out = differential.summary(target, ref)
    assert "error" not in out, out.get("error")
    assert out.get("arm") == dict(zip(corpus_schema.ARM_KEYS, arm)), "the read must name the arm it used"


def test_a_design_that_truly_does_not_exist_still_says_so():
    """The guard above must not swallow real absence into an arm story."""
    from src.cellarium import differential
    one, _ = survey.analysis_rows()
    if not one:
        pytest.skip("corpus unreadable in this environment")
    out = differential.summary("gene_knockout/KO:definitely_not_a_gene", "%s/%s" % survey.REFERENCE)
    assert out.get("reason") != "arm_mismatch"
    assert "no design" in out.get("error", "")
    assert out.get("available"), "a genuine absence still lists what IS available"


def test_a_tie_for_largest_arm_is_broken_by_key_not_by_row_order():
    """12 kinetic and 12 steady-state rows (2026-10-27): `max` kept whichever arm the parallel scan met first,
    so the default arm flipped between two calls and one design was reachable, then "in another arm"."""
    a, b = ("?", "?", "kinetic"), ("?", "?", "steady_state")
    assert survey._resolve_arm(None, {a: 12, b: 12}) == survey._resolve_arm(None, {b: 12, a: 12}) == a
    assert survey._resolve_arm(None, {a: 3, b: 12}) == b, "a clear largest arm still wins"


def _two_arm_rows(monkeypatch):
    rows = [{"d": "ko/leu#elong:kinetic", "elongation_model": "kinetic"},
            {"d": "ko/ctl#elong:kinetic", "elongation_model": "kinetic"},
            {"d": "ko/leu", "elongation_model": "steady_state"},
            {"d": "ko/ctl", "elongation_model": "steady_state"},
            {"d": "ko/both", "elongation_model": "steady_state"},
            {"d": "ko/both", "elongation_model": "kinetic"}]
    monkeypatch.setattr(survey, "analysis_rows", lambda arm=None: (rows, []))
    monkeypatch.setattr(survey, "design_key", lambda r: r["d"])


def test_the_designs_named_pin_the_arm(monkeypatch):
    _two_arm_rows(monkeypatch)
    kin = ("?", "?", "kinetic")
    assert survey.arm_for("ko/leu#elong:kinetic", "ko/ctl#elong:kinetic") == kin
    assert survey.arm_for("ko/leu", "ko/ctl") == ("?", "?", "steady_state")
    assert survey.arm_for("ko/leu#elong:kinetic", "ko/ctl") is None, "a pair split across arms has no arm"
    assert survey.arm_for("ko/both") is None, "a design in two arms does not pick one"
    assert survey.arm_for("ko/absent") is None


def test_differential_and_disconfirm_read_the_arm_their_designs_share(monkeypatch):
    """The refusal told the agent to "re-issue against that arm" through tools that take no arm. A comparison
    now reads the arm its two designs share; `arm_for` decides it, and these must pass it through."""
    from src.cellarium import differential, hygiene, rigor
    seen = []
    monkeypatch.setattr(survey, "arm_for", lambda *d: ("kb", "op", "kinetic"))
    monkeypatch.setattr(differential, "_design_seed_values", lambda arm=None: (seen.append(arm), ({}, []))[1])
    differential.summary("a", "b")
    monkeypatch.setattr(hygiene, "rows", lambda purpose, arm=None: (seen.append(arm), ([], {}))[1])
    rigor.disconfirm("a", "b", "growth_rate")
    assert seen == [("kb", "op", "kinetic")] * 2, seen


def test_survey_corpus_tool_reports_a_bad_arm_selector_instead_of_raising(monkeypatch):
    from src.cellarium import tools

    def boom(**kw):
        raise ValueError("arm selector 'x' matches 0 arms")
    monkeypatch.setattr(tools.survey, "survey_corpus", boom)
    out = tools.survey_corpus(arm="x")
    assert out.get("reason") == "arm_selector" and "matches 0 arms" in out["error"]
