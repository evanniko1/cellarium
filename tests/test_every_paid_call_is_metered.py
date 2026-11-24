"""Every model call a paid evaluation makes reaches the meter, so a spend cap counts it and a run's cost includes it.

FOUND 2026-11-24 by M4: its meter listed the rubric graders and both defect auditors but not the A/B's shared
judge, whose 30 calls never reported to it. Three call sites made their model call without emitting a usage
record: `shared_metric.grade` (the A/B's shared judge, used by M4 and M5), `grade.llm_grade` (the A/B's grader
for the Council arm, M5) and `gate.parse` (the gate eval, M3). A cap cannot hold an approval for calls it cannot
see, and a reported cost that leaves them out is the silent-absence defect again. M4 stayed under its cap.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "evals"):
    sys.path.insert(0, str(REPO / p))

import cases as cases_mod  # noqa: E402
import grade as grade_mod  # noqa: E402
import shared_metric  # noqa: E402
import trivial_baselines as tb  # noqa: E402

from cellarium import gate, observability  # noqa: E402

OPUS_1000_IN_200_OUT = 1000 * 5.00 / 1e6 + 200 * 25.00 / 1e6


class _Client:
    """Answers every call with one tool block carrying `tool_input`, billed 1,000 input and 200 output tokens."""

    def __init__(self, tool_input: dict):
        self.messages = SimpleNamespace(create=self._create)
        self._input = tool_input

    def _create(self, **kw):
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=self._input)],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
                               model=kw["model"], stop_reason="tool_use")


def _verdicts(case):
    return {"min_criteria": [{"criterion": c, "passed": False, "rationale": "r"} for c in case["min_criteria"]],
            "stringent_criteria": [{"criterion": c, "passed": False, "rationale": "r"}
                                   for c in case["stringent_criteria"]],
            "comment": "c"}


@pytest.fixture
def case():
    return cases_mod.by_id(["1.1"])[0]


def _metered(fn) -> dict:
    with observability.meter() as m:
        fn()
    return m.summary()


def test_the_shared_judge_reports_to_the_meter(case):
    h = tb.hypothesis(case["question"], "restated")
    s = _metered(lambda: shared_metric.grade(case, shared_metric.from_council(h), _Client(_verdicts(case)),
                                             "claude-opus-4-8"))
    assert (s["n_calls"], s["by_role"]) == (1, {"shared_judge": 1})
    assert s["cost_usd"] == pytest.approx(OPUS_1000_IN_200_OUT)


def test_the_ab_grader_for_the_council_arm_reports_to_the_meter(case):
    h = tb.hypothesis(case["question"], "restated")
    s = _metered(lambda: grade_mod.llm_grade(case, h, _Client(_verdicts(case)), "claude-opus-4-8"))
    assert (s["n_calls"], s["by_role"]) == (1, {"case_grader": 1})
    assert s["cost_usd"] == pytest.approx(OPUS_1000_IN_200_OUT)


def test_the_gate_parse_reports_to_the_meter():
    req = {"entity": "argS", "intervention": "knockout", "observable": "ppgpp_conc", "granularity": "molecule"}
    s = _metered(lambda: gate.parse("Does knocking out argS raise ppGpp?", model="claude-opus-4-8",
                                    client=_Client(req)))
    assert (s["n_calls"], s["by_role"]) == (1, {"gate_parse": 1})
    assert s["cost_usd"] == pytest.approx(OPUS_1000_IN_200_OUT)
