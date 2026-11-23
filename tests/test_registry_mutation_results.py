"""The registry-mutation verdicts, read against the predictions written before any fault ran (validation item 8).

Run 4 (revision 0863692) is the valid run; runs 1-3 are kept beside it and say why they produced no verdicts. Every
expectation here is a LITERAL from that run. The plan was frozen in c9dcfcb; between the plan and run 4 the harness
was amended three times (reset between runs; kills confirmed by a second run; a false test assertion removed), and
none of the amendments touched an edit, a prediction or a control.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MUT = REPO / "data" / "mutation"


def _load(name: str) -> dict:
    return json.loads((MUT / name).read_text(encoding="utf-8"))


def test_the_valid_run_answers_every_planned_fault_once():
    res, plan = _load("registry_results.json"), _load("registry_plan.json")
    planned = [m["id"] for m in plan["controls"] + plan["mutants"]]
    assert [r["id"] for r in res["rows"]] == planned
    assert res["revision"].startswith("0863692") and not res.get("aborted") and res.get("finished_utc")
    assert res["baseline"]["exit"] == 0 and res["reset_between_runs"] and res["kills_confirmed_by_a_second_run"]


def test_the_controls_behaved():
    rows = {r["id"]: r for r in _load("registry_results.json")["rows"]}
    assert rows["P1"]["verdict"] == "killed" and rows["N1"]["verdict"] == "survived"


def test_every_verdict_matched_its_written_prediction():
    rows = {r["id"]: r["verdict"] for r in _load("registry_results.json")["rows"]}
    assert rows == {"P1": "killed", "N1": "survived",
                    "W1": "killed", "W2": "killed", "A1": "killed", "A2": "killed", "T1": "killed", "T2": "killed",
                    "V1": "killed", "V2": "survived", "B1": "killed", "B2": "killed", "R1": "survived"}
    assert all(r["as_predicted"] for r in _load("registry_results.json")["rows"])


def test_every_kill_was_confirmed_by_a_second_run():
    for r in _load("registry_results.json")["rows"]:
        if r["verdict"] == "killed":
            assert r["confirmation"] and r["confirmation"]["exit"] == 1, r["id"]


def test_the_three_attempts_without_verdicts_are_kept_with_their_reasons():
    assert "negative control" in _load("registry_results_run1_invalid.json")["invalid_because"].lower()
    assert "test_launch" in _load("registry_results_run2_aborted.json")["aborted_because"]
    assert "linked worktree" in _load("registry_results_run3_aborted.json")["aborted_because"]
