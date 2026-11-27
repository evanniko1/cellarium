"""D35: a deposited run carries no username.

The local image is named after its user (`<user>-wcm-code:latest`), and since 2026-08-24 every run's `executed.json`
recorded that tag verbatim, so every archive deposited to the public corpus carried the username, and so did the
manifest's `executed_image_tag` column. The packer left out only `sim.log`. The user is written as ${USER}.
"""
import io
import json
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from cellarium import manifest, provenance, runner  # noqa: E402


def _as_user(monkeypatch, name):
    monkeypatch.setenv("USER", name)
    monkeypatch.setenv("USERNAME", name)


def test_the_local_user_becomes_a_placeholder_and_nothing_else_moves(monkeypatch):
    _as_user(monkeypatch, "alice")
    assert provenance.portable_image_tag("alice-wcm-code:latest") == "${USER}-wcm-code:latest"
    assert provenance.portable_image_tag("registry.io/alice-wcm-code:1") == "registry.io/${USER}-wcm-code:1"
    assert provenance.portable_image_tag("Alice-wcm-code:latest") == "${USER}-wcm-code:latest"
    assert provenance.portable_image_tag("malice-wcm-code:latest") == "malice-wcm-code:latest"   # not a word boundary
    assert provenance.portable_image_tag("covertlab/wcm-code:latest") == "covertlab/wcm-code:latest"
    assert provenance.portable_image_tag(None) is None and provenance.portable_image_tag("") == ""


def test_executed_json_is_written_with_the_placeholder(tmp_path, monkeypatch):
    _as_user(monkeypatch, "alice")
    monkeypatch.setattr(runner, "WCECOLI_DOCKER", "alice-wcm-code:latest")
    run_root = tmp_path / "wildtype_000000" / "000000"
    run_root.mkdir(parents=True)
    runner._capture_executed(run_root, "cellarium")
    rec = json.loads((run_root / "executed.json").read_text(encoding="utf-8"))
    assert rec["image_tag"] == "${USER}-wcm-code:latest"
    assert "alice" not in (run_root / "executed.json").read_text(encoding="utf-8")


def test_the_manifest_column_is_portable_for_runs_written_before_the_fix(tmp_path, monkeypatch):
    _as_user(monkeypatch, "alice")
    run_root = tmp_path / "r" / "000000"
    run_root.mkdir(parents=True)
    (run_root / "executed.json").write_text(json.dumps({"image_tag": "alice-wcm-code:latest",
                                                        "image_digest": "sha256:abc"}), encoding="utf-8")
    assert manifest._executed_prov(run_root)["executed_image_tag"] == "${USER}-wcm-code:latest"


def test_a_packed_run_carries_no_username_in_any_member(tmp_path, monkeypatch):
    import hf_pack_upload
    _as_user(monkeypatch, "alice")
    rr = tmp_path / "wildtype_000000" / "000000"
    so = rr / "generation_000000" / "000000" / "simOut"
    so.mkdir(parents=True)
    (so / "data.bin").write_bytes(b"\x00\x01")
    (rr / "sim.log").write_text("ran as alice in C:/Users/alice", encoding="utf-8")
    (rr / "executed.json").write_text(json.dumps({"image_tag": "alice-wcm-code:latest", "image_digest": "sha256:abc",
                                                  "missing": []}, indent=2), encoding="utf-8")
    tarp = tmp_path / "out.tar.gz"
    hf_pack_upload.pack_run(rr, "cellarium/wildtype_000000/000000", tarp)
    with tarfile.open(tarp) as tf:
        names = tf.getnames()
        assert "cellarium/wildtype_000000/000000/executed.json" in names
        assert not any(n.endswith("sim.log") for n in names)                  # still left out (FAIL-1b)
        assert "cellarium/wildtype_000000/000000/generation_000000/000000/simOut/data.bin" in names
        packed = json.loads(tf.extractfile("cellarium/wildtype_000000/000000/executed.json").read())
        assert packed["image_tag"] == "${USER}-wcm-code:latest"
        assert packed["image_digest"] == "sha256:abc"                         # every other field kept
        for m in tf.getmembers():
            if m.isfile():
                assert b"alice" not in tf.extractfile(m).read(), m.name
    assert names.count("cellarium/wildtype_000000/000000/executed.json") == 1  # not packed twice
    assert io  # noqa: B018


def test_no_tracked_manifest_shard_carries_this_machines_identity():
    """The 2026-09-02 fix (e8203b5) pseudonymised the distributed shards once, but the writer still stamps
    `getpass.getuser()` and `socket.gethostname()` into every new row and shard name. This guard fails if a shard
    carrying this machine's identity is ever committed. It can only catch the identity of the machine it runs on."""
    import getpass
    import socket
    import subprocess

    import duckdb
    import pytest
    try:
        tracked = subprocess.run(["git", "ls-files", "data/manifest"], cwd=REPO, capture_output=True, text=True,
                                 timeout=60).stdout.split()
    except Exception as exc:                      # no git: say so rather than pass silently
        pytest.skip(f"git unavailable: {exc}")
    shards = [t for t in tracked if t.endswith(".parquet")]
    assert shards, "no tracked manifest shard found; the guard would be vacuous"
    user, host = getpass.getuser().lower(), socket.gethostname().lower()
    assert not [t for t in tracked if user in t.lower()], "a tracked manifest file is named after the local user"
    con = duckdb.connect()
    try:
        for t in shards:
            cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{(REPO / t).as_posix()}')").fetchall()}
            for col, me in (("contributor", user), ("host", host)):
                if col not in cols:
                    continue
                vals = {str(v[0]).lower() for v in con.execute(
                    f"SELECT DISTINCT {col} FROM read_parquet('{(REPO / t).as_posix()}')").fetchall() if v[0]}
                assert me not in vals, f"{t} carries this machine's {col}"
    finally:
        con.close()
