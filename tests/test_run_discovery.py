"""scripts/run_discovery.py, offline: the dry run spends nothing, and a stage whose high estimate would pass the cap is
never started."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "apps"))


@pytest.fixture()
def drv(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("run_discovery", ROOT / "scripts" / "run_discovery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "OUT", tmp_path / "discovery_runs.json")
    return mod


def test_the_dry_run_prints_its_plan_and_calls_nothing(drv, monkeypatch, capsys):
    sys.modules.pop("api_keys", None)
    monkeypatch.setitem(sys.modules, "api_keys", type(sys)("api_keys"))   # no `require`: a call would raise
    monkeypatch.setattr(sys, "argv", ["run_discovery.py", "--dry-run", "--seeds", "S1,S4"])
    assert drv.main() == 0
    out = capsys.readouterr().out
    # two seeds at 1.10 + 0.05 + 1.85 (5.36 until the Council's high was raised on its metered runs, 2026-11-27)
    assert '"S1"' in out and '"S4"' in out and '"high_total_usd": 6.0' in out
    assert not drv.OUT.exists()


def test_an_unknown_seed_is_refused(drv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_discovery.py", "--dry-run", "--seeds", "S9"])
    with pytest.raises(SystemExit, match="unknown seeds"):
        drv.main()


def test_a_stage_that_would_pass_the_cap_is_not_started(drv, monkeypatch):
    import hypotheses

    def boom(*a, **k):
        raise AssertionError("the Council was called although its high estimate passes the cap")

    monkeypatch.setattr(hypotheses, "run_council", boom)
    state = {"records": {}, "spent_usd": 39.5}
    assert drv.run_seed("S1", state, cap=40.0) == "capped"          # 39.5 + 0.78 > 40
    assert drv.run_seed("S1", {"records": {}, "spent_usd": 0.0}, cap=0.5) == "capped"


def test_each_seed_is_gated_in_its_own_mode(drv, monkeypatch):
    """The gate's default mode is the steady-state corpus mode, where S1's per-isoacceptor charging is not represented;
    asked there it is refused with a route to kinetic and Cellwright never runs."""
    import hypotheses

    from cellarium import orchestrate

    class _Hyp:
        def brief(self):
            return "b"

    def fake_council(store, question, **kw):
        kw["on_hypothesis"]("h_x", _Hyp())
        return {"id": "h_x", "status": "done", "meta": {"llm": {"cost_usd": 0.1}}}

    seen = {}

    class _Decision:
        verdict, required_capabilities, blocking, route, notes, reason = "refuse", (), (), "", [], "stub"

    def fake_gate(question, **kw):
        seen.update(kw)
        return _Decision()

    monkeypatch.setattr(hypotheses, "run_council", fake_council)
    monkeypatch.setattr(hypotheses, "HypothesisStore", lambda: None)
    monkeypatch.setattr(orchestrate, "gate_question", fake_gate)
    state = {"records": {}, "spent_usd": 0.0}
    assert drv.run_seed("S1", state, cap=40.0) == "gated"
    assert seen == {"elongation_model": "kinetic"}
    assert state["records"]["S1"]["elongation_model"] == "kinetic"


def test_each_stage_high_is_at_least_the_most_it_has_metered(drv):
    """The paid-run recipe: compare a new kind's first metered runs with the estimate's high band. This campaign's
    Councils metered 0.55, 0.55, 0.75, 0.80 and 0.88 (the first high, 0.78, was exceeded twice); Cellwright 0.70 and
    0.71; the gate 0.021 to 0.041."""
    assert drv.STAGE_HIGH_USD["council"] >= 0.88
    assert drv.STAGE_HIGH_USD["cellwright"] >= 0.71
    assert drv.STAGE_HIGH_USD["gate"] >= 0.041
