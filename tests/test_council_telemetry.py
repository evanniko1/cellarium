"""Validation-layer item 5 (the free part): the debate measures, on synthetic runs and on the stored artefact.

The synthetic runs are built so each measure must move: an objection closed with the proposer's text unchanged
must be counted, one closed after a real edit must not (both directions, so a comparator that looked at the wrong
rounds would fail one of them). The artefact numbers are LITERALS from the 2026-11-23 run over the app store; the
store is local and gitignored, so the recomputation test skips with a reason where it is absent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))

import council_telemetry as T  # noqa: E402

GOOD = {"falsifiable": True, "specified": True, "operationalized": True, "discriminating": True}


def _round(n, claim, objs=(), judge=None):
    return {"round": n, "proposer": {"claim": claim, "h1": "h1", "h0": "h0"},
            "skeptic": [{"id": i, "severity": s, "type": "t", "issue": "x"} for i, s in objs], "judge": judge or GOOD}


def _run(rounds, resolutions, converged=True, rid="h_test"):
    return {"id": rid, "rounds": rounds,
            "meta": {"converged": converged, "rounds_used": len(rounds), "resolutions": resolutions}}


def test_an_objection_closed_with_the_text_unchanged_is_counted_and_one_closed_after_an_edit_is_not():
    run = _run([_round(1, "A", [("r1.1", "substantive"), ("r1.2", "substantive")]),
                _round(2, "A"),                                     # r1.1 "resolved" here: nothing changed
                _round(3, "A, now with a dose series")],            # r1.2 resolved here, after a real edit
               {"r1.1": 2, "r1.2": 3})
    o = {x["id"]: x for x in T.objections(run)}
    assert o["r1.1"]["identical"] is True and o["r1.2"]["identical"] is False
    s = T.summarize([run])
    assert s["substantive"]["resolved_with_identical_claim_h1_h0"] == 1
    assert s["substantive"]["identical_at"] == ["h_test:r1.1"]


def test_an_unresolved_objection_is_not_read_as_resolved():
    run = _run([_round(1, "A", [("r1.1", "substantive")]), _round(2, "A")], {})
    s = T.summarize([run])
    assert s["substantive"] == {**s["substantive"], "raised": 1, "resolved": 0, "unresolved": 1,
                                "resolved_with_identical_claim_h1_h0": 0}


def test_collapse_needs_a_substantive_objection_and_an_early_clean_exit():
    sub = [_round(1, "A", [("r1.1", "substantive")]), _round(2, "B")]
    assert T.collapsed(_run(sub, {"r1.1": 2})) is True
    assert T.collapsed(_run(sub + [_round(3, "C")], {"r1.1": 2})) is False       # took a third round
    assert T.collapsed(_run([_round(1, "A", [("r1.1", "minor")]), _round(2, "B")], {})) is False
    assert T.collapsed(_run(sub, {"r1.1": 2}, converged=False)) is False


def test_converging_below_an_earlier_round_is_caught_and_the_inapplicable_cases_say_so():
    worse = {**GOOD, "discriminating": False}
    assert T.converged_below_earlier_best(_run([_round(1, "A"), _round(2, "B", judge=worse)], {})) is True
    assert T.converged_below_earlier_best(_run([_round(1, "A", judge=worse), _round(2, "B")], {})) is False
    assert T.converged_below_earlier_best(_run([_round(1, "A")], {})) is None
    assert T.converged_below_earlier_best(_run([_round(1, "A"), _round(2, "B")], {}, converged=False)) is None


@pytest.fixture(scope="module")
def stored() -> dict:
    return json.loads(T.OUT.read_text(encoding="utf-8"))


def test_the_stored_artefact_says_what_the_2026_11_23_run_found(stored):
    assert (stored["runs"], stored["rounds"], stored["objections"]) == (30, 88, 97)
    sub, minor = stored["substantive"], stored["minor"]
    assert (sub["raised"], sub["resolved"], sub["unresolved"]) == (46, 43, 3)
    assert sub["resolved_with_identical_claim_h1_h0"] == 2 and sub["resolved_in_the_round_raised"] == 0
    assert (minor["raised"], minor["resolved"], minor["resolved_with_identical_claim_h1_h0"]) == (50, 40, 4)
    assert stored["collapse"]["runs_with_a_substantive_objection"] == 23
    assert stored["collapse"]["converged_within_2_rounds_anyway"] == 1
    assert stored["converged_below_its_own_earlier_best"] == {"applicable_runs": 28, "count": 0}


def test_the_artefact_carries_no_question_or_hypothesis_text(stored):
    """The app store holds a person's research questions; only ids and counts may leave it."""
    def strings(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k not in ("source", "limits", "computed_utc"):
                    yield from strings(v)
        elif isinstance(x, list):
            for v in x:
                yield from strings(v)
        elif isinstance(x, str):
            yield x
    assert all(len(s) <= 40 for s in strings(stored))
    assert "question" not in json.dumps(stored)


@pytest.mark.skipif(not T.DB.is_file(), reason="data/sessions.db is the local app store; absent on this machine")
def test_the_artefact_is_what_the_store_gives_today(stored):
    """Recomputed over EXACTLY the runs the artefact was made from. A store that is not that store -- a fresh
    clone's seeded demo database, or this machine's store after new runs were added -- is not a disagreement
    with the artefact, so it skips with the reason instead of failing. (Found 2026-11-23: comparing against
    whatever store existed made this test fail in a clean worktree once another test had seeded one.)"""
    ids = {r["id"] for r in stored["per_run"]}
    runs = [r for r in T.load_app_runs() if r["id"] in ids]
    if len(runs) != len(ids):
        pytest.skip(f"this machine's app store holds {len(runs)} of the artefact's {len(ids)} runs, so it is not "
                    "the store the artefact was computed from")
    now = T.summarize(runs)
    for k in ("runs", "rounds", "objections", "substantive", "minor", "collapse",
              "converged_below_its_own_earlier_best"):
        assert stored[k] == now[k], k
