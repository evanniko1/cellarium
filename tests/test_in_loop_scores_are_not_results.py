"""S2-3: no score produced inside the loop under test is reported as a result.

ScientistTwo (arXiv:2609.19644) shows the failure in its own tables: a second round of revision lifts the reviewer
its drafts were refined against from 6.9 to 7.6 while a held-out reviewer's acceptance falls. The Council has the
same shape. Its judge enforces an adequacy rubric (falsifiable, specified, operationalised, discriminating), so a
grade on that rubric, the Council's convergence, its objection counts and a best-of-N selector's score are all
measured by the loop's own criteria. They are reported as process, labelled in-loop; results come from the defect
auditors, which sit outside the loop.

Two checks: the M1+M2 report reads quality from auditor fields only, and the July aggregation, whose quality IS the
in-loop rubric, says so in its output.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))

import aggregate  # noqa: E402
import arms_report  # noqa: E402

IN_LOOP_KEYS = {"rubric", "score", "converged", "feasible", "substantive_objections", "judge", "judge_verdict",
                "rule", "objection_ledger"}


def _keys_read(source: str) -> set[str]:
    """String keys a module reads from records: r["k"], r.get("k"), and f-string keys are out of scope."""
    keys: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            keys.add(node.slice.value)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            keys.add(node.args[0].value)
    return keys


def test_the_m1m2_report_reads_no_in_loop_score():
    read = _keys_read((REPO / "evals" / "arms_report.py").read_text(encoding="utf-8"))
    assert not (read & IN_LOOP_KEYS), sorted(read & IN_LOOP_KEYS)


def test_the_m1m2_report_takes_quality_from_the_auditors():
    assert arms_report.AUDITORS == ("claude", "gpt")
    assert arms_report._count({"claude_defects": 7}, "claude") == 7


def test_the_scan_would_catch_an_in_loop_score():
    leaky = 'def readout(r):\n    return r["converged"], r.get("score")\n'
    assert _keys_read(leaky) & IN_LOOP_KEYS == {"converged", "score"}


def test_the_july_aggregation_labels_its_rubric_quality_as_in_loop():
    rec = {"id": "1.1", "config": "full", "rep": 0, "converged": True, "feasible": True, "rounds_used": 2,
           "claude": {"score": 6}, "gpt": {"score": 5}}
    summary = aggregate.summarise([rec])
    entry = summary["configs"]["full"]
    assert entry["quality_basis"] == aggregate.IN_LOOP_BASIS
    assert "in-loop" in aggregate.IN_LOOP_BASIS and "rubric" in aggregate.IN_LOOP_BASIS
