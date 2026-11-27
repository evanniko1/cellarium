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


# ---- amended post hoc (2026-11-27, D26): two more files carry wall-clock time ----------------------------------------
# V1's first score failed every pair on exactly two files per generation: Main/attributes.json (its startTime and
# endTime) and shell.log (its " - Runtime: H:MM:SS" line). Every listener column was byte-identical. The amendment
# removes those three wall-clock fields and nothing else; the all-bytes verdict is still reported beside it.

def _with_wall_clock(plan: dict, relaxed_attrs: dict | None = None, relaxed_log_extra: str = "") -> dict:
    for r in plan["runs"]:
        if not r["id"].startswith("V1-"):
            continue
        relaxed = r["id"].endswith("-relaxed")
        for g in range(r["generations"]):
            so = C._sim_out(C._root(r["design"], r["seed"]), g)
            if not so.is_dir():
                continue
            attrs = {"_version": 1, "initialTime": 0.0, "lengthSec": 4073.0, "processes": ["Metabolism"],
                     "states": ["BulkMolecules"], "startTime": f"2026-11-27 1{3 + int(relaxed)}:48:4{g}",
                     "endTime": f"2026-11-27 1{4 + int(relaxed)}:11:3{g}"}
            if relaxed and relaxed_attrs:
                attrs.update(relaxed_attrs)
            (so / "Main").mkdir(exist_ok=True)
            (so / "Main" / "attributes.json").write_text(json.dumps(attrs), encoding="utf-8")
            log = f" 2000.00    450.48\n - Sim length: 1:07:53\n - Runtime: 0:2{int(relaxed)}:{11 + g}\n"
            (so / "shell.log").write_text(log + (relaxed_log_extra if relaxed else ""), encoding="utf-8")
    return plan


def test_wall_clock_attributes_and_the_runtime_line_are_not_compared(tmp_path, monkeypatch):
    res = C.score_v1(_with_wall_clock(_plan_with(tmp_path, monkeypatch, b"m")))
    assert all(v["identical"] and v["complete"] for v in res.values())
    assert not any(v["identical_all_bytes"] for v in res.values())          # the strict verdict is still reported
    g0 = res["basal"]["generations"][0]
    assert g0["n_differ"] == 0 and g0["wall_clock_only"] == ["Main/attributes.json", "shell.log"]


def test_any_other_attribute_still_fails_its_pair(tmp_path, monkeypatch):
    res = C.score_v1(_with_wall_clock(_plan_with(tmp_path, monkeypatch, b"m"), relaxed_attrs={"initialTime": 1.0}))
    assert not any(v["identical"] for v in res.values())
    assert res["basal"]["generations"][0]["differ"] == ["Main/attributes.json"]


def test_any_other_log_line_still_fails_its_pair(tmp_path, monkeypatch):
    res = C.score_v1(_with_wall_clock(_plan_with(tmp_path, monkeypatch, b"m"),
                                      relaxed_log_extra=" - Runtime: a warning, not a clock\n"))
    assert not any(v["identical"] for v in res.values())
    assert res["basal"]["generations"][0]["differ"] == ["shell.log"]
