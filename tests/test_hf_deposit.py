"""scripts/hf_deposit.py: deposit local runs to the HF corpus one at a time and reclaim the disk only after an
anonymous check sees the archive at its exact size. The deletion is the dangerous step, so every path that must
NOT delete is forced here: a missing remote object, a size mismatch, a listing failure, reclaim switched off, and
an unnamed crash in the campaign."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
_spec = importlib.util.spec_from_file_location("hf_deposit", REPO / "scripts" / "hf_deposit.py")
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)


class _Entry:
    def __init__(self, path, size):
        self.path, self.size = path, size


class FakeHub:
    """Stands in for both clients: uploads land in `store`; the anonymous listing reads `store` unless told to
    lie (`listed_size`) or fail (`fail_listing`)."""

    def __init__(self, listed_size=None, fail_listing=False, preexisting=None):
        self.store = dict(preexisting or {})
        self.uploads = []
        self.listed_size = listed_size
        self.fail_listing = fail_listing

    def upload_file(self, path_or_fileobj, path_in_repo, repo_id, repo_type):
        self.uploads.append(path_in_repo)
        self.store[path_in_repo] = Path(path_or_fileobj).stat().st_size

    def list_repo_tree(self, repo, repo_type, recursive):
        if self.fail_listing:
            raise RuntimeError("listing unavailable")
        return [_Entry(p, self.listed_size if self.listed_size is not None else s) for p, s in self.store.items()]


def _run(tmp_path, design="gene_knockout_000001", seed="000000", payload=b"x" * 4096):
    root = tmp_path / "runs" / "cellarium" / design / seed
    so = root / "generation_000000" / "000000" / "simOut"
    so.mkdir(parents=True)
    (so / "Main.bin").write_bytes(payload)
    (root / "sim.log").write_text("host path C:/Users/someone", encoding="utf-8")   # dev-only, must not ship
    return root


def _deposit(tmp_path, hub, **kw):
    ledger = tmp_path / "ledger.jsonl"
    rows = D.deposit(out=str(tmp_path / "runs"), sim_path="cellarium", repo="org/corpus", upload_api=hub,
                     anon_api=hub, ledger=ledger, failures=lambda sp: [], sleep=lambda s: None, **kw)
    return rows, [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines()]


def test_a_verified_upload_reclaims_the_run(tmp_path):
    root = _run(tmp_path)
    hub = FakeHub()
    rows, ledger = _deposit(tmp_path, hub, reclaim=True)
    assert hub.uploads == ["runs/cellarium/gene_knockout_000001/000000.tar.gz"]
    assert rows[0]["verified"] is True and rows[0]["reclaimed"] is True and not root.exists()
    assert ledger[0]["remote_bytes"] == ledger[0]["tar_bytes"]


def test_a_size_mismatch_keeps_the_run(tmp_path):
    root = _run(tmp_path)
    rows, _ = _deposit(tmp_path, FakeHub(listed_size=7), reclaim=True)
    assert rows[0]["verified"] is False and rows[0]["reclaimed"] is False and root.exists()


def test_a_listing_failure_keeps_the_run(tmp_path):
    root = _run(tmp_path)
    hub = FakeHub(fail_listing=True)
    rows, _ = _deposit(tmp_path, hub, reclaim=True)
    assert rows[0]["verified"] is False and root.exists()
    assert "listing" in rows[0]["why"]


def test_without_reclaim_nothing_is_deleted(tmp_path):
    root = _run(tmp_path)
    rows, _ = _deposit(tmp_path, FakeHub(), reclaim=False)
    assert rows[0]["verified"] is True and rows[0]["reclaimed"] is False and root.exists()


def test_a_run_already_on_the_hub_is_not_reuploaded_and_is_checked_against_a_floor(tmp_path):
    root = _run(tmp_path, payload=b"y" * 100_000)
    key = "runs/cellarium/gene_knockout_000001/000000.tar.gz"
    small = FakeHub(preexisting={key: 5})                    # a truncated object far under 10% of the raw tree
    rows, _ = _deposit(tmp_path, small, reclaim=True)
    assert small.uploads == [] and rows[0]["verified"] is False and root.exists()
    fine = FakeHub(preexisting={key: 50_000})
    rows, _ = _deposit(tmp_path, fine, reclaim=True)
    assert fine.uploads == [] and rows[0]["verified"] is True and not root.exists()


def test_the_dev_only_log_does_not_ship(tmp_path):
    _run(tmp_path)
    shipped = {}

    class Capture(FakeHub):
        def upload_file(self, path_or_fileobj, path_in_repo, repo_id, repo_type):
            import tarfile
            with tarfile.open(path_or_fileobj) as tf:
                shipped[path_in_repo] = tf.getnames()
            super().upload_file(path_or_fileobj, path_in_repo, repo_id, repo_type)

    _deposit(tmp_path, Capture(), reclaim=False)
    names = next(iter(shipped.values()))
    assert any(n.endswith("Main.bin") for n in names) and not any(n.endswith("sim.log") for n in names)


def test_an_unnamed_crash_refuses_the_whole_deposit(tmp_path):
    root = _run(tmp_path)
    hub = FakeHub()
    with pytest.raises(SystemExit):
        D.deposit(out=str(tmp_path / "runs"), sim_path="cellarium", repo="org/corpus", upload_api=hub, anon_api=hub,
                  ledger=tmp_path / "l.jsonl", failures=lambda sp: [{"key": "unnamed"}], sleep=lambda s: None,
                  reclaim=True)
    assert hub.uploads == [] and root.exists()


def test_the_selection_takes_design_prefixes_and_leaves_the_rest(tmp_path):
    _run(tmp_path, design="gene_knockout_000001")
    kept = _run(tmp_path, design="wildtype_000000")
    rows, _ = _deposit(tmp_path, FakeHub(), reclaim=True, prefixes=("gene_knockout",))
    assert [r["rel"] for r in rows] == ["cellarium/gene_knockout_000001/000000"] and kept.exists()


def test_a_root_another_process_already_reclaimed_is_reported_not_verified_and_does_not_raise(tmp_path):
    # 2026-11-25: two depositors listed the same run (the knockout deposit at 14:24, the restarted batch later). The
    # second found the root gone: it counted 0 local bytes as "verified" against the hub's archive, then
    # shutil.rmtree raised FileNotFoundError, which would have ended that depositor's whole remaining queue.
    root = _run(tmp_path)
    hub = FakeHub()
    D.deposit_one(root, out=str(tmp_path / "runs"), repo="org/corpus", upload_api=hub, anon_api=hub,
                  ledger=tmp_path / "l.jsonl", reclaim=True, sleep=lambda s: None)
    assert not root.exists()
    row = D.deposit_one(root, out=str(tmp_path / "runs"), repo="org/corpus", upload_api=hub, anon_api=hub,
                        ledger=tmp_path / "l.jsonl", reclaim=True, sleep=lambda s: None)
    assert row["verified"] is False and row["reclaimed"] is False and "not on disk" in row["why"]
    assert hub.uploads == ["runs/cellarium/gene_knockout_000001/000000.tar.gz"]       # never uploaded twice
