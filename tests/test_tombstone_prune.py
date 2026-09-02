"""WELL-1y: prune = TOMBSTONE, never delete.

The dev/benchmark corpus may drop underpowered or purpose-served runs to free disk — but the record must
survive, because silent absence (the invisible valS, the phantom rows) was this project's worst failure mode.
So `drop_run` marks a run dropped, writes a ledger line, and returns the raw path for the USER to delete; the
manifest row and the tombstone stay. Surveys exclude a dropped run from ranking but KEEP it in coverage.

These drive `manifest.drop_run` against a TEMP manifest + a monkeypatched dropped-store, so the real corpus and
the real ledger are never touched.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402


def test_the_python_and_sql_dedup_keys_agree_on_the_corpus():
    """`drop_run` and the dropped-filter key rows in Python (`dedup_key_py`); the survey dedups in SQL
    (`DEDUP_KEY`). If they disagree, a tombstone written against the Python key would never match the SQL row —
    the drop would silently do nothing. Pinned over every corpus path."""
    os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/*.parquet")
    import duckdb

    from cellarium import manifest
    if not os.path.exists("data/manifest"):
        pytest.skip("no local manifest")
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT id, simout_path, {manifest.DEDUP_KEY} AS sql_key "
            "FROM read_parquet('data/manifest/*.parquet', union_by_name=true) "
            f"{manifest.DEDUP_QUALIFY}").fetch_arrow_table().to_pylist()
    finally:
        con.close()
    bad = [r for r in rows if manifest.dedup_key_py(r) != r["sql_key"]]
    assert not bad, f"{len(bad)} rows where Python dedup key != SQL, e.g. {bad[0]['id'] if bad else None}"


def _tmp_manifest(tmp_path, monkeypatch):
    """A one-row parquet manifest + isolated dropped.json/ledger under tmp_path."""
    import duckdb

    from cellarium import manifest
    mdir = tmp_path / "manifest"
    mdir.mkdir()
    con = duckdb.connect()
    con.execute(
        "COPY (SELECT 'run_A' AS id, 'runs/cellarium/wt_1/000000' AS simout_path, 'wildtype' AS perturbation, "
        "'basal' AS condition, NULL AS timeline, 'wildtype·basal·s0' AS label, 1 AS generations, "
        "true AS reportable, 1.0 AS ts) "
        f"TO '{(mdir / 'shard.parquet').as_posix()}' (FORMAT parquet)")
    con.close()
    monkeypatch.setattr(manifest, "MANIFEST_DIR", mdir)
    monkeypatch.setattr(manifest, "DROPPED_PATH", mdir / "dropped.json")
    monkeypatch.setattr(manifest, "LEDGER_PATH", tmp_path / "CORPUS_LEDGER.md")
    return manifest, mdir


def test_drop_run_tombstones_without_deleting_the_row(tmp_path, monkeypatch):
    manifest, mdir = _tmp_manifest(tmp_path, monkeypatch)
    out = manifest.drop_run("run_A", "underpowered n=1, superseded", ts=1.0)
    assert "error" not in out, out
    # the record exists...
    dropped = manifest.dropped_keys()
    assert len(dropped) == 1 and next(iter(dropped.values()))["reason"].startswith("underpowered")
    # ...the manifest shard is untouched (the row still there)...
    import duckdb
    con = duckdb.connect()
    n = con.execute(f"SELECT count(*) FROM read_parquet('{(mdir / '*.parquet').as_posix()}')").fetchone()[0]
    con.close()
    assert n == 1, "drop_run deleted the manifest row — it must only tombstone"
    # ...and the ledger got a human-readable line naming the design + reason.
    ledger = (tmp_path / "CORPUS_LEDGER.md").read_text(encoding="utf-8")
    assert "wildtype/basal" in ledger and "underpowered" in ledger and "run_A" in ledger


def test_drop_run_requires_a_reason():
    from cellarium import manifest
    assert "error" in manifest.drop_run("run_A", "   ")


def test_drop_run_refuses_an_unknown_id(tmp_path, monkeypatch):
    manifest, _ = _tmp_manifest(tmp_path, monkeypatch)
    assert "error" in manifest.drop_run("no_such_run", "x")


def test_drop_run_is_idempotent(tmp_path, monkeypatch):
    manifest, _ = _tmp_manifest(tmp_path, monkeypatch)
    manifest.drop_run("run_A", "first", ts=1.0)
    manifest.drop_run("run_A", "second", ts=2.0)
    assert len(manifest.dropped_keys()) == 1, "a second drop of the same run must not duplicate the tombstone"


def test_a_dropped_run_leaves_the_ranking_but_stays_in_coverage(tmp_path, monkeypatch):
    """The load-bearing behaviour: exclude from ranking, KEEP in coverage."""
    from cellarium import manifest, survey
    dropped = {"run_A@@runs/cellarium/wt_1/000000": {"key": "run_A@@runs/cellarium/wt_1/000000",
                                                     "id": "run_A", "reason": "test drop"}}
    monkeypatch.setattr(manifest, "dropped_keys", lambda: dropped)
    live = [{"id": "run_A", "simout_path": "runs/cellarium/wt_1/000000", "reportable": True},
            {"id": "run_B", "simout_path": "runs/cellarium/wt_1/000001", "reportable": True}]
    marked = survey._mark_dropped(live)
    assert marked[0]["_dropped"] is True and marked[1]["_dropped"] is False


def test_dropped_keys_is_empty_and_harmless_when_nothing_is_dropped(tmp_path, monkeypatch):
    manifest, _ = _tmp_manifest(tmp_path, monkeypatch)
    assert manifest.dropped_keys() == {}
    # _mark_dropped is a no-op when there are no tombstones (the common case — must not touch the hot path)
    from cellarium import survey
    rows = [{"id": "x", "simout_path": "runs/cellarium/a/0"}]
    assert "_dropped" not in survey._mark_dropped(rows)[0]
