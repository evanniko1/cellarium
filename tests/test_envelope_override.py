"""A refused design runs only under a declared, recorded override (D28, 2026-11-27).

CRIT tier 1's V3 plan pre-registered the model's own rule under a threshold-moving shift as its NEGATIVE CONTROL: the
defect itself, run to show the panel can tell the rules apart. The plan said those runs go "through the batch, which
calls the runner directly", but `runner.run_one` checks the envelope and refused the first one. The override makes the
code match the registered intent, and only for a run that names why: the reason is written beside the run before it
starts, and a run without one is refused exactly as before.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cellarium import calibration, runner  # noqa: E402
from cellarium.model import Design  # noqa: E402

SHIFT = Design(perturbation="timeline", timeline="0 minimal, 1200 minimal_minus_oxygen")   # CRIT refuses it
STATIC = Design(perturbation="wildtype", condition="basal")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "_out_root", lambda sp: tmp_path / sp)
    monkeypatch.setattr(runner, "_exec", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(runner, "_capture_executed", lambda *a, **k: None)
    monkeypatch.setattr(calibration, "observe_run", lambda *a, **k: None)
    return calls


def test_the_shift_is_refused_by_the_envelope():
    from cellarium import envelope
    assert not envelope.check(SHIFT).in_envelope and envelope.check(STATIC).in_envelope


def test_a_refused_design_does_not_run_without_an_override(isolated, tmp_path):
    with pytest.raises(ValueError, match="out-of-envelope"):
        runner.run_one(SHIFT, 900, 1)
    assert isolated == [] and not any(tmp_path.rglob("design.json"))       # nothing written, nothing run


def test_an_empty_override_is_no_override(isolated):
    with pytest.raises(ValueError, match="out-of-envelope"):
        runner.run_one(SHIFT, 900, 1, envelope_override="  ")
    assert isolated == []


def test_an_override_runs_the_refused_design_and_records_why_first(isolated):
    root = runner.run_one(SHIFT, 900, 1, envelope_override="CRIT tier 1 negative control")
    assert len(isolated) == 1
    rec = json.loads((root / runner._ENVELOPE_OVERRIDE_FILE).read_text(encoding="utf-8"))
    assert rec["override"] == "CRIT tier 1 negative control"
    assert "threshold" in rec["refused_because"].lower()


def test_an_in_envelope_design_records_no_override(isolated):
    root = runner.run_one(STATIC, 900, 1, envelope_override="not needed")
    assert len(isolated) == 1 and not (root / runner._ENVELOPE_OVERRIDE_FILE).exists()


def test_the_batch_passes_a_plans_override_to_the_runner(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bv_batch_ov", ROOT / "scripts" / "bv_batch.py")
    B = importlib.util.module_from_spec(spec)
    sys.modules["bv_batch_ov"] = B
    spec.loader.exec_module(B)
    plan = {"batch": "v3", "sim_path": "cellarium", "runs": [
        {"id": "ctl", "design": SHIFT.model_dump(), "seed": 900, "generations": 3, "group": "g",
         "envelope_override": "CRIT tier 1 negative control"},
        {"id": "run", "design": STATIC.model_dump(), "seed": 900, "generations": 3, "group": "g"}]}
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    _, runs = B.load_plan(p)
    by = {r.id: r for r in runs}
    assert by["ctl"].envelope_override == "CRIT tier 1 negative control" and by["run"].envelope_override == ""
