"""M-7: progressive sufficiency narrowing. The nudge is deterministic, blind, and non-blocking — it names only the
still-missing of {manipulation, observable, comparison} and, on a re-convene, asks only for what the refinement
did not already supply. These lock the pure functions + the run_council threading."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps"))

from cellarium import council  # noqa: E402


def test_missing_axes_detects_each_axis():
    assert council.missing_axes("what happens to the cell?") == ["manipulation", "observable", "comparison"]
    # manipulation + observable present, no contrast named -> only comparison missing
    assert council.missing_axes("does a pfkA knockout stop division?") == ["comparison"]
    # all three -> nothing missing
    assert council.missing_axes("does a pfkA knockout reduce growth versus wildtype?") == []


def test_looks_specific_unchanged_by_refactor():
    # the pre-pass firing set must be exactly as before (comparison is NOT required for testable-by-construction)
    assert council.looks_specific("does a pfkA knockout stop division?") is True
    assert council.looks_specific("clamp ppGpp and watch growth") is True
    assert council.looks_specific("what happens to the cell?") is False
    assert council.looks_specific("tell me about metabolism") is False


def test_sharpening_hint_none_when_fully_specified():
    assert council.sharpening_hint("does a pfkA knockout reduce growth versus wildtype?") is None


def test_sharpening_hint_names_only_missing_axes():
    h = council.sharpening_hint("does a pfkA knockout stop division?")   # only comparison missing
    assert h["missing"] == ["comparison"]
    assert "compare against" in h["text"]
    assert "perturbation it can run" not in h["text"]   # does NOT re-ask for the manipulation it already has
    assert h["progress"] is None                        # no prior attempt -> no narrowing preamble


def test_sharpening_hint_is_progressive_on_reconvene():
    # prior was maximally broad; the refinement added a manipulation + observable, leaving only the comparison
    h = council.sharpening_hint("does a pfkA knockout stop division?",
                                prior_question="what happens to the cell?")
    assert h["missing"] == ["comparison"]
    assert h["progress"] is not None
    assert "manipulation" in h["progress"] and "observable" in h["progress"]   # acknowledges what's now supplied
    assert "comparison" in h["progress"]                                       # and names what's still helpful
    assert h["progress"] in h["text"]


def test_sharpening_hint_no_progress_when_nothing_resolved():
    # a re-convene that did not add any axis -> still missing the same ones, no false "you've narrowed it"
    h = council.sharpening_hint("tell me about the cell", prior_question="what happens to the cell?")
    assert h["progress"] is None


def test_run_council_threads_prior_question_for_progressive_hint(tmp_path, monkeypatch):
    import hypotheses

    class _Hyp:
        claim = "c"; candidate_designs = []
        converged = True; rounds_used = 1; substantive_objections = 0

        def brief(self):
            return "b"

    monkeypatch.setattr(council, "deliberate", lambda q, *, verbose=False, on_round=None, **kw: _Hyp())
    s = hypotheses.HypothesisStore(path=tmp_path / "narrow.db")

    first = s.new_id()
    run1 = hypotheses.run_council(s, "what happens to the cell?", reuse_id=first)
    assert run1["meta"]["missing_axes"] == ["manipulation", "observable", "comparison"]
    assert run1["meta"]["narrowing"] is None

    # re-convene the SAME row with a sharpened question — the hint must narrow, not restart
    run2 = hypotheses.run_council(s, "does a pfkA knockout stop division?", reuse_id=first)
    assert run2["meta"]["missing_axes"] == ["comparison"]
    assert run2["meta"]["narrowing"] is not None and "now specified" in run2["meta"]["narrowing"]
    assert run2["meta"]["broad_question"] is False   # manipulation + observable present -> not broad
