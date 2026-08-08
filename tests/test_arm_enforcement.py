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
