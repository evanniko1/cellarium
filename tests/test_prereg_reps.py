"""CAPBENCH-3 — the repetition count is a pre-registration, so the code has to be able to prove it.

THE LOOPHOLE THIS CLOSES, stated plainly: run three replicates, dislike the error bars, run seven more,
report ten. Nothing in a result file would show it happened. The manuscript closes it in prose — section 6
says each stochastic system is run five times, and Appendix ML adds that the count is "fixed before any
response is generated" — but prose in a paper cannot constrain a script, and until now the two were not
connected at all: `evals/run_ab.py` declared `--reps` with `default=1`, so following the documented command
produced a single-replicate sweep whose output never mentioned the word.

So there are two separate defects and these tests pin both.

  1. THE NUMBER MUST EXIST IN CODE, ONCE. `evals/capbench_cases.PREREGISTERED_REPS` is that single copy. A
     number written down twice can drift, and the drift would be invisible in precisely the artefact meant
     to prevent it — so `run_ab.py` imports it rather than restating it, and the test below asserts they are
     the same object's value rather than two equal literals that happen to agree today.

  2. EVERY RESULT MUST CARRY ITS OWN n. This is the part that makes the commitment checkable by a reader
     who has only the output file. A sweep is free to run at a count other than five — `run_ab.py` is the
     Council/Cellwright A/B, a different experiment, and is NOT bound to the CAPBENCH protocol — but its
     summary must say which count produced it, what the commitment is, and whether the two match. Silence
     is the failure mode; a mismatch that is recorded is merely a fact.

WHAT THESE TESTS DELIBERATELY DO NOT DO. They do not assert that any sweep runs at five. Forcing the A/B
harness to the CAPBENCH count would multiply its cost fivefold for an experiment the commitment does not
govern, and would encode a claim that is not true.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
sys.path.insert(0, str(EVALS))


def _run_ab_source() -> str:
    return (EVALS / "run_ab.py").read_text(encoding="utf-8")


def _run_aggregate_capturing(run_ab, captured: dict, args) -> None:
    """Run the real `_aggregate` and capture the summary WITHOUT writing into evals/results.

    `_aggregate` serialises with `json.dumps` and writes through `Path.write_text`, so both are stubbed: the
    first to capture, the second so a test run never overwrites a real sweep's scorecard. Going through the
    genuine roll-up (rather than asserting on source text) is the point -- a refactor that stopped recording
    the count would then fail here instead of passing a grep.
    """
    orig_dumps, orig_write = run_ab.json.dumps, run_ab.Path.write_text

    def _dumps(obj, *a, **k):
        if isinstance(obj, dict):
            captured.update(obj)
        return orig_dumps(obj, *a, **k)

    run_ab.json.dumps = _dumps
    run_ab.Path.write_text = lambda self, *a, **k: None
    try:
        run_ab._aggregate({}, [], args, 1.0)
    finally:
        run_ab.json.dumps, run_ab.Path.write_text = orig_dumps, orig_write


def test_the_committed_count_exists_and_is_the_number_the_paper_states():
    """Five, in one place. The paper states it in two sections; the code must state it in exactly one."""
    from capbench_cases import PREREGISTERED_REPS

    assert isinstance(PREREGISTERED_REPS, int), type(PREREGISTERED_REPS)
    assert PREREGISTERED_REPS == 5, (
        f"the manuscript commits to five repetitions in section 6 and Appendix ML; this says "
        f"{PREREGISTERED_REPS}. Changing it is a PROTOCOL change — permissible only before any arm has run "
        "against the frozen labels (CAPBENCH-1a), and then only with the change and its reason recorded in "
        "the paper.")


def test_the_runner_imports_the_count_instead_of_restating_it():
    """Two copies of a pre-registered number can drift apart, and nothing downstream would notice.

    Checked in the syntax tree rather than by grepping for `5`, because the literal appears elsewhere in the
    file for unrelated reasons and a text match would pass on a coincidence.
    """
    tree = ast.parse(_run_ab_source(), filename="run_ab.py")
    imported = [n for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom)
                and (n.module or "").endswith("capbench_cases")
                and any(al.name == "PREREGISTERED_REPS" for al in n.names)]
    assert imported, ("run_ab.py must IMPORT PREREGISTERED_REPS from capbench_cases; restating the number "
                      "creates a second copy that can drift from the pre-registration.")


def test_the_summary_records_the_count_that_actually_ran():
    """A result file that cannot say how many replicates produced it is unauditable.

    Builds the summary through the real `_aggregate` on an empty ledger — the roll-up path every sweep takes
    — rather than asserting on the source text, so a future refactor that stops recording the field fails
    here instead of passing a grep.
    """
    import run_ab
    from capbench_cases import PREREGISTERED_REPS

    captured: dict = {}
    args = argparse.Namespace(
        arm="a", reps=3, council_model="m", grader_model="g", agent_model=None,
        judge_model=None, matched_framing=False, out=None, rounds=4, quota=3, force=False, ids=None)

    _run_aggregate_capturing(run_ab, captured, args)
    assert captured, "_aggregate wrote no summary at all"
    assert captured.get("reps") == 3, (
        f"the summary must record the count that ran; got {captured.get('reps')!r}. Without it a reported "
        "result cannot be checked against the pre-registered count by anyone holding only the output.")
    assert captured.get("preregistered_reps") == PREREGISTERED_REPS
    assert captured.get("meets_preregistered_reps") is False, (
        "a sweep at 3 against a commitment of 5 must record the mismatch as False — recorded is fine, "
        "silent is not.")


def test_a_sweep_at_the_committed_count_records_that_it_met_it():
    """The other direction: the flag must be capable of saying yes, or it is decoration."""
    import run_ab
    from capbench_cases import PREREGISTERED_REPS

    captured: dict = {}
    args = argparse.Namespace(
        arm="a", reps=PREREGISTERED_REPS, council_model="m", grader_model="g", agent_model=None,
        judge_model=None, matched_framing=False, out=None, rounds=4, quota=3, force=False, ids=None)
    _run_aggregate_capturing(run_ab, captured, args)
    assert captured.get("meets_preregistered_reps") is True


def test_the_default_reps_is_declared_and_its_mismatch_is_visible():
    """`--reps` still defaults to 1, and that is deliberate — but it must not be silent.

    The A/B harness is not the pre-registered CAPBENCH evaluation and forcing it to five would quintuple the
    cost of an experiment the commitment does not govern. What is NOT acceptable is a default that produces
    an off-protocol run indistinguishable from an on-protocol one, which is why the summary carries the
    comparison. This test documents the default so a change to it is a deliberate, reviewed act.
    """
    tree = ast.parse(_run_ab_source(), filename="run_ab.py")
    defaults = [
        kw.value.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_argument"
        and any(isinstance(arg, ast.Constant) and arg.value == "--reps" for arg in n.args)
        for kw in n.keywords if kw.arg == "default" and isinstance(kw.value, ast.Constant)
    ]
    assert defaults == [1], (
        f"--reps default is {defaults}; if this changed deliberately, update this test and say why. The "
        "point of pinning it is that the gap between the default and the pre-registered count stays a "
        "conscious, recorded choice rather than a silent one.")


@pytest.mark.parametrize("field", ["reps", "preregistered_reps", "meets_preregistered_reps"])
def test_each_audit_field_is_named_in_the_runner(field):
    """Cheap belt-and-braces: the three fields a reader needs are all emitted by name."""
    assert f'"{field}"' in _run_ab_source(), f"{field} is not written into the summary"
