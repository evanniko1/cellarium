"""TRAJ-1 tests. Every measure is exercised BOTH ways.

A clean result on the six recorded discovery traces proves nothing on its own — a check that cannot fail reports
1.00 forever. So each measure is also run against a trajectory built to violate exactly that measure, and the
test asserts it fires. (This is the null-arm rule applied to an eval: a perturbation needs a no-change control,
and a control needs a known-bad case.)
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import trajectory  # noqa: E402

TRACES = sorted((Path(__file__).resolve().parents[1] / "kinetic_port" / "optionA_ws" / "traces")
                .glob("cellwright_discovery_v*.json"))


def _trace(calls, question=""):
    return {"id": "synthetic", "question": question, "seconds": 0, "calls": calls}


def _call(tool, args, output=None):
    return {"t": 0.0, "tool": tool, "input": args, "output": output if output is not None else {"rows": []}}


# ---- the measures fire on a known-bad trajectory -------------------------------------------------------------

def test_unknown_tool_is_caught():
    s = trajectory.score(_trace([_call("survey_corpus", {}), _call("no_such_tool", {"x": 1})]))
    assert s["unknown_tools"] == ["no_such_tool"]
    assert s["selection_validity"] == 0.5


def test_missing_required_argument_is_caught():
    s = trajectory.score(_trace([_call("survey_corpus", {}), _call("trajectory", {})]))
    assert any("missing_required:design" in f for r in s["argument_faults"] for f in r["faults"])


def test_unknown_property_is_caught():
    s = trajectory.score(_trace([_call("survey_corpus", {"nonsense": 1})]))
    assert any("unknown_property:nonsense" in f for r in s["argument_faults"] for f in r["faults"])


def test_wrong_type_is_caught():
    s = trajectory.score(_trace([_call("survey_corpus", {"arm": 7})]))
    assert any("wrong_type:arm" in f for r in s["argument_faults"] for f in r["faults"])


def test_value_outside_an_enum_is_caught():
    s = trajectory.score(_trace([_call("survey_corpus", {}),
                                 _call("trajectory", {"design": "wildtype/basal", "channel": "not_a_channel"})]))
    assert any("not_in_enum:channel" in f for r in s["argument_faults"] for f in r["faults"])
    # ...and the same call with a declared channel is clean
    ok = trajectory.score(_trace([_call("survey_corpus", {}),
                                  _call("trajectory", {"design": "wildtype/basal", "channel": "growth_rate"})]))
    assert ok["argument_faults"] == []


def test_an_anyOf_branch_must_be_satisfied():
    s = trajectory.score(_trace([_call("chart", {"kind": "line", "channel": "growth_rate"})]))
    assert any("no_anyOf_branch_satisfied" in f for r in s["argument_faults"] for f in r["faults"])


def test_an_invented_handle_is_ungrounded():
    """The failure that looks like success: a plausible design label the agent never read anywhere."""
    s = trajectory.score(_trace([_call("survey_corpus", {}),
                                 _call("trajectory", {"design": "gene_knockout/KO:invented_xyz"})]))
    assert [u["tool"] for u in s["ungrounded"]] == ["trajectory"]
    assert s["grounding"] == 0.5


def test_a_handle_read_from_an_earlier_output_is_grounded():
    s = trajectory.score(_trace([
        _call("survey_corpus", {}, {"designs": ["gene_knockout/KO:pfkA"]}),
        _call("trajectory", {"design": "gene_knockout/KO:pfkA"}),
    ]))
    assert s["ungrounded"] == []
    assert s["grounding"] == 1.0


def test_a_handle_given_in_the_question_is_grounded():
    s = trajectory.score(_trace([_call("trajectory", {"design": "condition/acetate"})],
                                question="How does condition/acetate behave?"))
    assert s["ungrounded"] == []


def test_the_declared_first_step_is_read_from_the_description_not_hardcoded():
    assert trajectory._declared_first_steps() == {"survey_corpus"}
    late = trajectory.score(_trace([_call("list_results", {}), _call("survey_corpus", {})]))
    assert not late["first_call_is_a_declared_first_step"]
    early = trajectory.score(_trace([_call("survey_corpus", {}), _call("list_results", {})]))
    assert early["first_call_is_a_declared_first_step"]


def test_identical_calls_and_retries_are_counted_separately():
    err = {"error": "no such design", "reason": "unknown_entity", "about": "request"}
    s = trajectory.score(_trace([
        _call("survey_corpus", {}),
        _call("trajectory", {"design": "wildtype/basal"}, err),
        _call("trajectory", {"design": "wildtype/basal"}, err),
    ]))
    assert len(s["redundant_calls"]) == 1          # the second identical call
    assert len(s["retries_after_an_error"]) == 1   # ...which also followed an error from the same tool
    assert len(s["request_refusals"]) == 2


# ---- absence must not read as a fact ------------------------------------------------------------------------

def test_an_error_without_about_makes_the_refusal_rate_not_measurable(tmp_path):
    """A trace recorded before the error contract cannot say whose fault a refusal was. 0.0 would be a lie."""
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"question": "q", "tool_calls": [
        {"t": 0, "tool": "survey_corpus", "input": {}, "output": {"rows": []}},
        {"t": 1, "tool": "trajectory", "input": {"design": "wildtype/basal"},
         "output": {"error": "no such design"}},     # pre-contract: no `about`
    ]}), encoding="utf-8")
    rep = trajectory.score_set([p])
    assert rep["per_call_request_refusal_rate"] is None
    assert "not measurable" in rep["request_refusal_basis"]


def test_a_fully_annotated_set_does_get_a_rate(tmp_path):
    p = tmp_path / "new.json"
    p.write_text(json.dumps({"question": "q", "tool_calls": [
        {"t": 0, "tool": "survey_corpus", "input": {}, "output": {"rows": []}},
        {"t": 1, "tool": "survey_corpus", "input": {"arm": "kinetic"},
         "output": {"error": "no such arm", "reason": "bad_argument", "about": "request"}},
    ]}), encoding="utf-8")
    rep = trajectory.score_set([p])
    assert rep["per_call_request_refusal_rate"] == pytest.approx(0.5)


def test_an_empty_trace_does_not_claim_a_clean_run():
    s = trajectory.score(_trace([]))
    assert s["n_calls"] == 0
    assert s["first_call"] is None


# ---- the recorded traces --------------------------------------------------------------------------------------

@pytest.mark.skipif(not TRACES, reason="discovery traces not present")
def test_the_recorded_discovery_traces_score():
    rep = trajectory.score_set(TRACES)
    assert rep["n_traces"] == len(TRACES)
    assert rep["n_calls"] > 100
    # Measured 2026-10-28 on the six discovery traces: no unknown tool, no schema-invalid call, every handle
    # grounded. v4 is the one trace that did not start on survey_corpus, and that is the whole finding.
    assert rep["per_call_argument_fault_rate"] == 0.0
    assert rep["per_call_ungrounded_rate"] == 0.0
    assert rep["traces_starting_on_a_declared_first_step"] == len(TRACES) - 1
    assert rep["per_call_request_refusal_rate"] is None   # these traces predate errors.py


def test_handle_params_do_not_include_the_agents_own_prose():
    """`title`, `claim` and `rationale` are the agent's to invent; grounding must not punish them."""
    for free in ("title", "claim", "rationale", "question", "url"):
        assert free not in trajectory.HANDLE_PARAMS
