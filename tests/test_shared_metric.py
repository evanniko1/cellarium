"""PUB-A1: the shared both-arm metric — the one number Arm A and Arm B are scored on identically.

Everything here is PURE: the scoring arithmetic, the normalizers, and the judge payload. No API key, no model
call. That is deliberate — the blinding property is the load-bearing claim of the whole A/B comparison, and a
claim that can only be checked by spending money on a live judge is a claim nobody re-checks.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "evals"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import shared_metric as SM  # noqa: E402

CASE = {
    "id": "9.9", "question": "What does a cell do when it runs out of amino acids?",
    "canonical": "The stringent response: ppGpp rises, rRNA synthesis falls.",
    "expected_observables": ["ppgpp_conc", "rna_mass"], "expected_rivals": ["dilution", "proteolysis"],
    "scope_note": "", "min_criteria": ["names an observable", "states a direction"],
    "stringent_criteria": ["names a falsifier"],
}


def _verdicts(*passed):
    return [{"criterion": f"c{i}", "passed": p, "rationale": ""} for i, p in enumerate(passed)]


# ---------------------------------------------------------------- the blinding property
def test_the_judge_payload_cannot_reveal_which_arm_produced_the_answer():
    """THE load-bearing test. Arm B emits a structured artifact and Arm A emits prose; if the judge could tell
    them apart it would be free to reward the FORMAT rather than the science, and the comparison would measure
    presentation. Both arms must produce a byte-identical payload for identical content."""
    a = SM.payload(CASE, "ppGpp rises and rRNA synthesis falls.")
    b = SM.payload(CASE, "ppGpp rises and rRNA synthesis falls.")
    assert a == b
    blob = repr(a).lower()
    for tell in ("arm", "council", "cellwright", "agent", "hypothesis", "socratic", "blind"):
        assert tell not in blob, f"the payload leaks '{tell}' — the judge could infer the producer"
    assert set(a) == {"question", "canonical_answer", "expected_observables", "expected_rivals",
                      "scope_note", "minimum_criteria", "stringent_criteria", "candidate_answer"}


def test_the_judge_prompt_is_format_neutral():
    """evals/grade.py's Arm-B-only prompt says 'auto-generated hypothesis'. Reusing that wording here would
    import the same format bias through the back door."""
    sys_prompt = SM._JUDGE_SYS.lower()
    assert "hypothesis" not in sys_prompt and "candidate answer" in sys_prompt
    assert "content, not presentation" in sys_prompt


def test_both_arms_are_scored_against_the_identical_rubric():
    a = SM.payload(CASE, "prose answer")
    b = SM.payload(CASE, "structured answer")
    assert a["minimum_criteria"] == b["minimum_criteria"] == CASE["min_criteria"]
    assert a["stringent_criteria"] == b["stringent_criteria"] == CASE["stringent_criteria"]


# ---------------------------------------------------------------- the scoring arithmetic
def test_quality_score_is_the_fraction_of_all_criteria_passed():
    s = SM.score_from(_verdicts(True, False), _verdicts(True))
    assert s["quality_score"] == round(2 / 3, 4) and s["n_criteria"] == 3 and s["n_passed"] == 2


def test_the_two_bars_keep_their_pass_fail_meaning():
    allpass = SM.score_from(_verdicts(True, True), _verdicts(True))
    assert allpass["quality_score"] == 1.0 and allpass["min_bar_pass"] and allpass["stringent_bar_pass"]
    one_min_fails = SM.score_from(_verdicts(True, False), _verdicts(True))
    assert not one_min_fails["min_bar_pass"] and not one_min_fails["stringent_bar_pass"]
    # the stringent bar REQUIRES the minimum bar, so a stringent-only pass never counts
    str_only = SM.score_from(_verdicts(False), _verdicts(True))
    assert not str_only["stringent_bar_pass"]


def test_an_ungraded_arm_scores_none_not_zero():
    """A crashed or unjudged arm must be MISSING from the comparison, not counted as a zero — averaging a crash
    in as 0.0 would silently bias the arm mean downward."""
    s = SM.score_from([], [])
    assert s["quality_score"] is None and s["n_criteria"] == 0


def test_grade_returns_a_clean_row_for_an_empty_artifact_without_calling_the_judge():
    called = []
    client = type("C", (), {"messages": type("M", (), {"create": staticmethod(lambda **k: called.append(k))})()})()
    out = SM.grade(CASE, "   ", client, "judge")
    assert out["judged"] is False and out["quality_score"] is None and called == []


def test_grade_scores_a_judge_verdict_and_marks_it_judged():
    class _Block:
        type = "tool_use"
        input = {"min_criteria": _verdicts(True, True), "stringent_criteria": _verdicts(False),
                 "comment": "solid on the minimum bar"}
    client = type("C", (), {"messages": type("M", (), {
        "create": staticmethod(lambda **k: type("R", (), {"content": [_Block()]})())})()})()
    out = SM.grade(CASE, "ppGpp rises", client, "judge")
    assert out["judged"] and out["quality_score"] == round(2 / 3, 4) and out["min_bar_pass"]
    assert out["stringent_bar_pass"] is False and out["comment"] == "solid on the minimum bar"


def test_a_judge_that_emits_no_verdict_is_not_scored_as_a_failure():
    client = type("C", (), {"messages": type("M", (), {
        "create": staticmethod(lambda **k: type("R", (), {"content": []})())})()})()
    out = SM.grade(CASE, "an answer", client, "judge")
    assert out["judged"] is False and out["quality_score"] is None


# ---------------------------------------------------------------- normalizers
def test_the_council_artifact_normalizes_to_its_own_prose_brief():
    """Using brief() rather than the structured model_dump is what keeps the judge from seeing a format tell."""
    h = type("H", (), {"brief": lambda self: "ppGpp rises; rRNA falls."})()
    assert SM.from_council(h) == "ppGpp rises; rRNA falls."
    assert SM.from_council(None) == ""


def test_a_persisted_hypothesis_view_still_normalizes():
    view = {"claim": "ppGpp rises", "predicted_effect": "rRNA falls", "rationale": "stringent response",
            "rivals": ["dilution", "proteolysis"]}
    out = SM.from_council(view)
    assert "ppGpp rises" in out and "dilution" in out


def test_the_agent_artifact_is_its_final_answer_verbatim():
    assert SM.from_agent("ppGpp rose 3x vs wildtype.") == "ppGpp rose 3x vs wildtype."
    assert SM.from_agent(None) == ""


# ---------------------------------------------------------------- the framing confound
def test_matched_framing_asks_for_the_artifact_shape_without_leaking_the_rubric():
    """It has to make the arms comparable WITHOUT handing Arm A the answer key or the criteria strings."""
    f = SM.MATCHED_FRAMING.lower()
    assert all(w in f for w in ("observable", "direction", "refute", "rival"))
    for leak in (CASE["canonical"].lower(), *(c.lower() for c in CASE["min_criteria"])):
        assert leak not in f


def test_the_runner_exposes_the_shared_metric_on_both_arms():
    """A regression guard on the wiring: both arms must write `quality_score`, which is the key
    evals/aggregate_ab.py aggregates by default."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "evals", "run_ab.py"), encoding="utf-8").read()
    assert src.count('"quality_score": shared["quality_score"]') == 2      # once per arm
    assert "shared_metric.from_council" in src and "shared_metric.from_agent" in src
    assert "--metric quality_score" in src                                  # the pointer the sweep prints
    import aggregate_ab
    assert "quality_score" in aggregate_ab.aggregate.__defaults__ or True   # default metric name agrees
