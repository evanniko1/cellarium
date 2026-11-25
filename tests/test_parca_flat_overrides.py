"""A rebuild with edited knowledge-base tables mounts EXACTLY those tables and records what it mounted.

Mounting the whole checkout's overlays (WCECOLI_DIR) also mounts `variants/__init__.py`, which names variants the
image may not have: the first BV-14 refit died at import on `sinusoidal_media` (2026-11-25). A rebuild that changes
two flat files must mount two flat files, and its provenance must carry their hashes, because the image digest
cannot see a bind mount (PROV-3)."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import provenance, runner  # noqa: E402


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_exec(args):
        seen["args"] = list(args)
        seen["mounts"] = list(getattr(runner._EXEC_LOCAL, "mounts", None) or [])

    monkeypatch.setattr(runner, "_exec", fake_exec)
    monkeypatch.setattr(provenance, "kb_provenance", lambda sp: {"kb_sha256": "abc", "parca_ts": 1.0})
    return seen


def test_only_the_named_tables_are_mounted_and_their_hashes_recorded(tmp_path, captured):
    cd = tmp_path / "condition_defs.tsv"
    cd.write_text('"condition"\t"nutrients"\n"basal"\t"minimal"\n', encoding="utf-8")
    res = runner.parca_rebuild("bv14_x", flat_overrides={"condition/condition_defs.tsv": cd}, cpus=2)
    assert captured["mounts"] == ["-v", f"{cd.as_posix()}:/wcEcoli/reconstruction/ecoli/flat/condition/"
                                        f"condition_defs.tsv:ro"]
    assert res["flat_overrides"] == {"condition/condition_defs.tsv":
                                     hashlib.sha256(cd.read_bytes()).hexdigest()}
    assert captured["args"][:2] == ["runscripts/manual/runParca.py", "bv14_x"]


def test_the_mounts_do_not_outlive_the_rebuild(tmp_path, captured):
    cd = tmp_path / "condition_defs.tsv"
    cd.write_text("x", encoding="utf-8")
    runner.parca_rebuild("bv14_x", flat_overrides={"condition/condition_defs.tsv": cd}, cpus=1)
    assert not getattr(runner._EXEC_LOCAL, "mounts", None)


def test_a_missing_override_file_refuses_before_running(tmp_path, captured):
    with pytest.raises(FileNotFoundError):
        runner.parca_rebuild("bv14_x", flat_overrides={"condition/condition_defs.tsv": tmp_path / "nope.tsv"})
    assert "args" not in captured


def test_a_path_outside_the_flat_tree_is_refused(tmp_path, captured):
    f = tmp_path / "x.py"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        runner.parca_rebuild("bv14_x", flat_overrides={"../../models/ecoli/sim/variants/__init__.py": f})
    assert "args" not in captured
