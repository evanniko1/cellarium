"""evals/crit_t1.py's V1 scorer: identical listener files, the wall-clock listener excepted, and an absent run is
named rather than counted as identical."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "src"))

import crit_t1 as C  # noqa: E402


def _tree(root: Path, gens: int, mass: bytes, clock: bytes) -> None:
    for g in range(gens):
        so = C._sim_out(root, g)
        (so / "Mass").mkdir(parents=True)
        (so / "Mass" / "cellMass").write_bytes(mass)
        (so / "EvaluationTime").mkdir()
        (so / "EvaluationTime" / "clock").write_bytes(clock)


def _plan_with(tmp_path, monkeypatch, relaxed_mass: bytes, make_relaxed: bool = True) -> dict:
    roots = {}

    def fake_root(design, seed):
        key = ("relaxed" if (design.get("params") or {}).get("initiation_threshold") else "medium",
               design.get("condition") or design.get("timeline"))
        return roots.setdefault(key, tmp_path / f"{key[0]}_{len(roots)}")

    monkeypatch.setattr(C, "_root", fake_root)
    plan = json.loads(C.PLAN.read_text(encoding="utf-8"))
    for r in plan["runs"]:
        if r["id"].startswith("V1-"):
            root = fake_root(r["design"], r["seed"])
            relaxed = r["id"].endswith("-relaxed")
            if relaxed and not make_relaxed:
                continue
            _tree(root, r["generations"], relaxed_mass if relaxed else b"m", b"clock-" + r["id"].encode())
    return plan


def test_identical_listeners_pass_whatever_the_wall_clock_says(tmp_path, monkeypatch):
    res = C.score_v1(_plan_with(tmp_path, monkeypatch, b"m"))
    assert all(v["identical"] and v["complete"] for v in res.values())


def test_one_differing_column_fails_its_pair(tmp_path, monkeypatch):
    res = C.score_v1(_plan_with(tmp_path, monkeypatch, b"M"))
    assert not any(v["identical"] for v in res.values())
    assert res["basal"]["generations"][0]["differ"] == ["Mass/cellMass"]


def test_an_absent_run_is_named_not_counted_identical(tmp_path, monkeypatch):
    res = C.score_v1(_plan_with(tmp_path, monkeypatch, b"m", make_relaxed=False))
    assert all(not v["identical"] and not v["complete"] for v in res.values())
    assert "absent" in res["basal"]["generations"][0]


def test_the_listeners_first_row_is_not_a_threshold_step():
    """The smoke test (2026-11-27) read a 975 fg 'largest step' in BOTH arms: the first row of every generation is 0,
    written before the process runs. A continuity check over all rows would fail every relaxed run on it."""
    steps, at = C._steps([0, 1, 2, 3], [0.0, 975.0, 974.96, 974.9])
    assert max(steps) < 0.1 and list(at) == [2.0, 3.0]
    jump, at2 = C._steps([0, 599, 600], [0.0, 975.0, 590.02])
    assert max(jump) == 975.0 - 590.02 and at2[0] == 600.0


def test_the_worker_carries_the_same_step_function():
    assert "def _steps(t, m):" in C._WORKER and "steps, at = _steps(t, m)" in C._WORKER
