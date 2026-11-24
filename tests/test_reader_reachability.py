"""A comparison over a SET of runs must survive one run the reader container cannot see.

Found 2026-11-24 re-deriving the Platform Map's arabinose row (Appendix J): `wildtype/basal` has seeds under
`runs_seed_aars/`, outside the mounted output root. `reader.differential` -- which `top_movers` and
`regulon_response` call -- raised on the first such seed and aborted a comparison its reachable seeds could
answer. `reader.gene_lfc` already handled this through `_reachable`: drop the unreachable run, name it on the
payload, and refuse below the evidential seed floor. `differential` and `reroute_diagnosis` did not.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import reader, support  # noqa: E402


def _setup(monkeypatch, tmp_path):
    out = tmp_path / "runs"
    other = tmp_path / "runs_seed_aars"
    for d in (out / "t0", out / "t1", out / "r0", out / "r1", other / "r2", other / "t2"):
        d.mkdir(parents=True)
    monkeypatch.setattr(reader, "OUT_ROOT", out.resolve())
    monkeypatch.setattr(reader, "WCECOLI_DOCKER", "image:tag")
    calls = []
    monkeypatch.setattr(reader, "_run_cmd", lambda cmd, cwd: calls.append(cmd) or {"ok": True})
    return out, other, calls


def test_the_seed_floor_these_tests_assume():
    assert support.MIN_SEEDS == 2


def test_differential_drops_an_unreachable_reference_run_and_names_it(monkeypatch, tmp_path):
    out, other, calls = _setup(monkeypatch, tmp_path)
    res = reader.differential([out / "t0", out / "t1"], [out / "r0", out / "r1", other / "r2"])
    assert len(calls) == 1, "the comparison must still run on the reachable runs"
    # worker args end: mode, targets, references, kind, top, floor
    assert calls[0][-5:-3] == ["/wcEcoli/out/t0,/wcEcoli/out/t1", "/wcEcoli/out/r0,/wcEcoli/out/r1"]
    omitted = res["_unreachable_runs"]
    assert [o["role"] for o in omitted] == ["reference"]
    assert omitted[0]["n_unreachable"] == 1 and omitted[0]["n_reachable"] == 2


def test_differential_refuses_when_too_few_runs_are_reachable(monkeypatch, tmp_path):
    out, other, calls = _setup(monkeypatch, tmp_path)
    res = reader.differential([out / "t0", out / "t1"], [out / "r0", other / "r2"])
    assert calls == [], "below the seed floor it must refuse, not answer from one run"
    assert "reachable" in res["error"]
    assert [o["role"] for o in res["unreachable"]] == ["reference"]


def test_differential_with_every_run_reachable_attaches_no_omission(monkeypatch, tmp_path):
    out, _, calls = _setup(monkeypatch, tmp_path)
    res = reader.differential([out / "t0", out / "t1"], [out / "r0", out / "r1"])
    assert len(calls) == 1 and "_unreachable_runs" not in res


def test_reroute_diagnosis_drops_an_unreachable_knockout_run_and_names_it(monkeypatch, tmp_path):
    out, other, calls = _setup(monkeypatch, tmp_path)
    res = reader.reroute_diagnosis("pgi", [out / "t0", out / "t1", other / "t2"], [out / "r0", out / "r1"])
    assert len(calls) == 1
    # worker args end: mode, gene, knockouts, wild types
    assert calls[0][-2:] == ["/wcEcoli/out/t0,/wcEcoli/out/t1", "/wcEcoli/out/r0,/wcEcoli/out/r1"]
    assert [o["role"] for o in res["_unreachable_runs"]] == ["target"]


def test_reroute_diagnosis_refuses_when_too_few_wild_types_are_reachable(monkeypatch, tmp_path):
    out, other, calls = _setup(monkeypatch, tmp_path)
    res = reader.reroute_diagnosis("pgi", [out / "t0", out / "t1"], [out / "r0", other / "r2"])
    assert calls == [] and "reachable" in res["error"]
