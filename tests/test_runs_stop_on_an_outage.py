"""A paid evaluation stops when its model calls fail in a row, and says so (Agentic Benchmark Checklist T.3).

Before 2026-11-23 none of the three scored harnesses stopped. The gate eval was the sharpest case: `gate.parse`
deliberately proceeds on a blank requirement when its model call fails, so an outage would have been graded as
the gate's ignorance rule on every remaining item, with only a `parser_failed` flag on each record to say so.
The ablation kept calling through any number of errors and wrote each partial state over its canonical
artefact. The A/B kept calling too, and then treated an errored arm as done, so a re-run after an outage skipped
exactly the cells the outage had broken.

Every model call here is faked; nothing leaves the machine. Expectations are literals.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "scripts", "evals"):
    sys.path.insert(0, str(REPO / p))

import ablate  # noqa: E402
import run_ab  # noqa: E402
import run_gate_eval as ev  # noqa: E402

from cellarium import credentials, gate, llm, outage  # noqa: E402

# --- the breaker ---------------------------------------------------------------------------------------


def test_the_breaker_trips_on_the_fifth_failure_in_a_row_and_only_once():
    b = outage.Breaker()
    seq = [True, False, False, True] + [False] * 6
    trips = [b.observe(ok, "APIConnectionError") for ok in seq]
    assert trips == [False] * 8 + [True, False]
    assert (b.tripped, b.tripped_at, b.n_ok, b.n_failed) == (True, 9, 2, 8)
    assert b.report(216)["consecutive_failures"] == ["APIConnectionError"] * 5


def test_a_success_resets_the_run():
    b = outage.Breaker(limit=3)
    for ok in [False, False, True, False, False, True, False, False]:
        assert b.observe(ok, "x") is False
    assert not b.tripped


def test_a_limit_below_one_is_refused():
    with pytest.raises(ValueError):
        outage.Breaker(limit=0)


def test_the_default_limit_is_five_and_the_exit_code_is_three():
    assert (outage.DEFAULT_LIMIT, outage.EXIT_INTERRUPTED) == (5, 3)


def test_the_exit_code_is_zero_until_the_breaker_trips_and_three_after():
    b = outage.Breaker(limit=2)
    assert b.exit_code() == 0
    b.observe(False, "x")
    assert b.exit_code() == 0
    b.observe(False, "x")
    assert b.exit_code() == 3


# --- the gate eval --------------------------------------------------------------------------------------

def gate_run_with(monkeypatch, tmp_path, ok_first: int, workers: int = 1, extra: tuple = ()):
    """The gate eval with its parser faked: the first `ok_first` calls succeed, every later one fails the way
    `gate.parse` reports a failed model call. The key loader is stubbed so no real credential is touched.
    Returns (exit code, the artefact path, the questions the parser was asked)."""
    monkeypatch.setattr(credentials, "load_into_env", lambda *a, **kw: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    calls: list[str] = []

    def fake_parse(question, *, model=None, client=None):
        calls.append(question)
        if len(calls) <= ok_first:
            return gate.Requirement(observable="growth_rate", raw_question=question, parser=model).normalised()
        return gate.Requirement(raw_question=question, parser=f"{model} (failed: APIConnectionError)").normalised()
    monkeypatch.setattr(gate, "parse", fake_parse)
    out = tmp_path / "gate_eval.json"
    code = ev.main(["--workers", str(workers), "--out", str(out), *extra])
    return code, out, calls


@pytest.fixture
def gate_run(monkeypatch, tmp_path):
    return lambda ok_first, workers=1, extra=(): gate_run_with(monkeypatch, tmp_path, ok_first, workers, extra)


def test_the_gate_eval_stops_on_an_outage_and_writes_a_marked_partial(gate_run):
    code, out, calls = gate_run(ok_first=3)
    assert code == 3
    assert not out.exists(), "a stopped run must never be written where a complete artefact goes"
    part = json.loads(out.with_name("gate_eval.partial.json").read_text(encoding="utf-8"))
    stop = part["report"]["stopped_early"]
    # `of` is the generated bank, one framing per registry cell: 36 until G-1 added two records (2026-11-24)
    assert (stop["stopped_early"], stop["after_calls"], stop["of"]) == (True, 8, 42)
    assert stop["consecutive_failures"] == ["APIConnectionError"] * 5
    assert 8 <= len(calls) <= 8 + 1, "after the trip, nothing may start beyond what one worker already had"
    assert len(part["records"]) == len(calls), "every call that was made is recorded"
    assert "accuracy" not in part["report"], "a stopped run reports no score to be cited"


def test_a_failed_parse_names_its_error_on_the_record(gate_run):
    code, out, _ = gate_run(ok_first=3)
    recs = json.loads(out.with_name("gate_eval.partial.json").read_text(encoding="utf-8"))["records"]
    errs = [r["parser_error"] for r in recs]
    assert errs.count(None) == 3 and set(errs) - {None} == {"APIConnectionError"}


def test_an_uninterrupted_gate_eval_is_unchanged(gate_run):
    code, out, calls = gate_run(ok_first=10 ** 6)
    assert code == 0 and out.exists() and len(calls) == 42
    rep = json.loads(out.read_text(encoding="utf-8"))["report"]
    assert "stopped_early" not in rep and rep["parser_failures"] == 0
    assert not out.with_name("gate_eval.partial.json").exists()


def test_the_stop_threshold_is_a_flag(gate_run):
    code, out, calls = gate_run(ok_first=0, extra=("--stop-after-failures", "2"))
    assert code == 3
    stop = json.loads(out.with_name("gate_eval.partial.json").read_text(encoding="utf-8"))["report"]["stopped_early"]
    assert (stop["after_calls"], stop["limit"]) == (2, 2)


# --- the ablation --------------------------------------------------------------------------------------

@pytest.fixture
def ablation(monkeypatch, tmp_path):
    monkeypatch.setattr(ablate, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "client", lambda **kw: object())
    calls: list[tuple] = []

    def run(ok_first: int):
        def fake_cell(case, cfg, rep, temperature, client, oai, gpt_model, claude_grader, **kw):
            calls.append((case["id"], cfg, rep))
            rec = {"id": case["id"], "config": cfg, "rep": rep, "temperature": temperature}
            if len(calls) > ok_first:
                rec["error"] = "APIConnectionError: Connection error."
            else:
                rec["claude"] = {"score": 4}
            return rec
        monkeypatch.setattr(ablate, "_one_cell", fake_cell)
        out = tmp_path / "ablation.json"
        code = ablate.run(None, ["full", "proposer_only"], 1, 0.7, str(out), "gpt-4o", "claude-opus-4-8", workers=1)
        return code, out, calls
    return run


def test_the_ablation_stops_on_an_outage_without_touching_its_artefact(ablation):
    code, out, calls = ablation(ok_first=2)
    assert code == 3
    assert not out.exists(), "the canonical ablation.json must not be overwritten by a stopped run"
    part = json.loads(out.with_name("ablation.partial.json").read_text(encoding="utf-8"))
    assert (part["stopped_early"]["after_calls"], part["stopped_early"]["of"]) == (7, 50)
    assert len(part["results"]) == len(calls) and 7 <= len(calls) <= 8


def test_an_uninterrupted_ablation_writes_its_artefact_and_no_partial(ablation):
    code, out, calls = ablation(ok_first=10 ** 6)
    assert code == 0 and len(calls) == 50
    assert len(json.loads(out.read_text(encoding="utf-8"))["results"]) == 50
    assert not out.with_name("ablation.partial.json").exists()


def test_an_unparseable_gpt_grade_is_an_error_not_a_zero(monkeypatch):
    """The GPT judge's reply was parsed with a bare except that returned {}, which scores 0 of 6: a judge that
    said nothing readable recorded as a judge that found nothing. The stored ablation has none (120 of 120
    graded), so this is preventive."""
    class _Msg:
        content = "I'm sorry, I can't produce JSON for this."

    class _Oai:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return type("R", (), {"choices": [type("C", (), {"message": _Msg})]})
    case = {"question": "q"}
    h = type("H", (), {"model_dump": lambda self, **kw: {}, "brief": lambda self: ""})()
    with pytest.raises(ValueError, match="not JSON"):
        ablate.grade_gpt(case, h, _Oai())


# --- the A/B -------------------------------------------------------------------------------------------

@pytest.fixture
def ab(monkeypatch, tmp_path):
    monkeypatch.setattr(run_ab, "LEDGER", tmp_path / "ab_ledger.json")
    monkeypatch.setattr(run_ab, "RESULTS", tmp_path)
    monkeypatch.setattr(run_ab, "_resolve_api_key", lambda log=print: None)
    monkeypatch.setattr(run_ab, "_aggregate", lambda *a, **kw: None)
    monkeypatch.setattr(llm, "client", lambda **kw: object())
    logs: list[str] = []
    monkeypatch.setattr(run_ab, "_log", logs.append)
    monkeypatch.setattr(sys, "argv", ["run_ab.py", "--arm", "b"])
    return logs


def test_the_ab_ledger_survives_a_rename_windows_refuses_for_a_moment(ab, monkeypatch):
    """Found 2026-11-23 when the stop test below failed once with WinError 5 on the ledger's rename: the same
    transient refusal the job queue retries (tests/test_launch.py). An unattended sweep must not die of it."""
    import os as _os
    real = _os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(5, "Access is denied")
        return real(src, dst)
    monkeypatch.setattr(_os, "replace", flaky)
    run_ab._save_ledger({"1.1": {"b": {"status": "ok"}}})
    assert calls["n"] == 3
    assert json.loads(run_ab.LEDGER.read_text(encoding="utf-8")) == {"1.1": {"b": {"status": "ok"}}}


def test_the_ab_sweep_stops_after_five_failed_arms_and_a_rerun_retries_them(ab, monkeypatch):
    ran: list[str] = []

    def down(case, *a, **kw):
        ran.append(case["id"])
        raise ConnectionError("no route to host")
    monkeypatch.setattr(run_ab, "run_arm_b", down)
    assert run_ab.main() == 3
    assert len(ran) == 5
    assert any("STOPPED" in m for m in ab)
    led = json.loads(run_ab.LEDGER.read_text(encoding="utf-8"))
    assert sum(1 for v in led.values() if v.get("b", {}).get("status") == "error") == 5

    ran.clear()

    def up(case, *a, **kw):
        ran.append(case["id"])
        return {"id": case["id"], "status": "ok"}
    monkeypatch.setattr(run_ab, "run_arm_b", up)
    assert run_ab.main() == 0
    assert len(ran) == 25, "the 5 errored arms are retried with the 20 never run; --force is not needed"


# --- the judge panel (validation item 6 runs through it) ----------------------------------------------------
# `regrade` let a failed judge call raise out of the loop, and the panel was written only after it returned, so an
# outage part-way lost every grade already paid for; and a stored panel was "resumed" by reporting it as complete.

import panel as PANEL  # noqa: E402


def _ledger(n: int) -> dict:
    return {f"{i}.1": {"_case": f"{i}.1", "_rep": 0,
                       "a": {"shared": {"graded_text": f"answer {i}", "quality_score": 0.5, "judge_model": "j"}}}
            for i in range(1, n + 1)}


def _case(cid: str) -> dict:
    return {"id": cid, "question": "q", "canonical": "c", "expected_observables": [], "expected_rivals": [],
            "min_criteria": ["m"], "stringent_criteria": ["s"]}


class _Judge:
    """A judge whose first `ok_first` calls return a verdict and every later one raises."""

    def __init__(self, ok_first: int):
        self.ok_first, self.n = ok_first, 0

    @property
    def messages(self):
        return self

    def create(self, **kw):
        self.n += 1
        if self.n > self.ok_first:
            raise ConnectionError("no route to host")
        block = type("B", (), {"type": "tool_use", "input": {"min_criteria": [{"passed": True}], "stringent_criteria": [{"passed": True}]}})
        return type("R", (), {"content": [block]})


def test_the_panel_stops_on_an_outage_and_keeps_what_it_paid_for():
    led = _ledger(5)
    by_id = {f"{i}.1": _case(f"{i}.1") for i in range(1, 6)}
    judge = _Judge(ok_first=3)
    out = PANEL.regrade(led, ["claude-opus-4-8"], 2, judge, by_id)
    assert judge.n == 3 + 5, "it stops at the fifth failure in a row"
    assert out["_stopped_early"]["after_calls"] == 8 and out["_stopped_early"]["of"] == 10
    kept = {u: s for u, s in out.items() if not u.startswith("_")}
    assert sum(len(v) for js in kept.values() for v in js.values()) == 3, "the 3 grades paid for are kept"
    assert all(q is not None for js in kept.values() for v in js.values() for q in v), "a failed call is no sample"


def test_a_stopped_panel_resumes_by_asking_only_for_what_is_missing():
    led = _ledger(5)
    by_id = {f"{i}.1": _case(f"{i}.1") for i in range(1, 6)}
    first = PANEL.regrade(led, ["claude-opus-4-8"], 2, _Judge(ok_first=3), by_id)
    judge = _Judge(ok_first=10 ** 6)
    done = PANEL.regrade(led, ["claude-opus-4-8"], 2, judge, by_id, existing=first)
    assert judge.n == 10 - 3, "only the 7 missing samples are asked for"
    assert "_stopped_early" not in done
    assert all(len(v) == 2 for js in done.values() if isinstance(js, dict) for v in js.values())
