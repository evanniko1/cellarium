"""A tombstoned run must never come back from a read path as a usable result.

`manifest.drop_run` keeps the parquet row on purpose — a dropped run has to stay auditable. But keeping the
row and filtering it on read are two different jobs, and until 2026-08-06 only the second was missing:
`dropped_keys()` had exactly two consumers, both in survey.py, so `store.list_results()` — the row source for
integrity_check, reconcile_disk, hf._design_seeds and the UI — returned dropped runs indistinguishably from
good ones.

The concrete failure: 20 runs tombstoned as mislabelled knockouts (they silenced unrelated transcription
units while carrying synthetase labels) came back from list_results(gene="argS") with qc="ok" and
reportable=true, while the correct re-runs were legitimately crashed/false. A caller taking the reportable
rows got precisely the wrong ones.
"""
import pytest

from src.cellarium import manifest, store, tools


def _tombstoned_ids():
    t = manifest.dropped_keys()
    if not t:
        pytest.skip("nothing is tombstoned in this checkout, so there is nothing to filter")
    return {v.get("id") for v in t.values()}


def test_store_marks_dropped_runs_unreportable():
    """On the retrieval path, a tombstoned run must arrive labelled — not as an ordinary result.

    This asserted over the DEFAULT read until TOMB-1 moved the rows out of the glob, at which point its
    `if not seen: skip` guard made it vacuous: it passed by testing nothing. It now asserts over the path
    where those rows actually appear, which is the only place the labelling can still be got wrong.
    """
    ids = _tombstoned_ids()
    seen = [r for r in store.list_results(include_dropped=True) if r.get("id") in ids]
    assert seen, "no tombstoned run is retrievable at all — the record has been lost, not quarantined"
    for r in seen:
        assert r.get("dropped") is True, f"{r['id']} is tombstoned but not flagged dropped"
        assert r.get("reportable") is False, (
            f"{r['id']} is tombstoned but still reportable — every downstream gate tests this field")
        assert r.get("dropped_reason"), f"{r['id']} is flagged dropped with no recorded reason"


def test_tool_excludes_dropped_runs_but_says_how_many():
    ids = _tombstoned_ids()
    res = tools.list_results()
    assert not [r for r in res["results"] if r.get("id") in ids], (
        "list_results returned a tombstoned run; a dropped run must not be readable as a result")
    assert res.get("n_dropped_hidden") == len(ids), (
        "the hidden count must come from the tombstone set, not from the rows: since TOMB-1 the quarantined "
        "rows are absent from the default read, so counting them there reports 0 and the omission goes silent")
    assert res.get("note"), "runs were hidden with no note — a silent omission is the bug, not the fix"


def test_dropped_runs_are_still_retrievable_on_request():
    """Excluded by default, never erased: the audit trail must survive the filter."""
    ids = _tombstoned_ids()
    res = tools.list_results(include_dropped=True)
    got = {r["id"] for r in res["results"]} & ids
    assert got, "include_dropped=True returned none of the tombstoned runs — the record has been lost"


# ---------------------------------------------------------------------------------------------------------
# TOMB-1: unreachable by construction, not by discipline.
#
# The tests above check that readers FILTER tombstoned rows. Those below check they cannot SEE them, which is a
# different guarantee. The discipline version demonstrably did not hold: `audit.py`, `operons.py`,
# `evidence.py` and `corpus_schema._rows` never consulted the tombstone set and each returned all 52 as live.
# ---------------------------------------------------------------------------------------------------------

def test_no_tombstoned_row_is_in_the_glob_every_reader_uses():
    """The invariant. 17 read sites across 8 modules use this pattern; none of them can be made to forget it."""
    import duckdb
    ids = _tombstoned_ids()
    con = duckdb.connect()
    try:
        rows = con.execute("SELECT id FROM read_parquet('data/manifest/*.parquet', union_by_name=true)"
                           ).fetch_arrow_table().to_pylist()
    finally:
        con.close()
    leaked = sorted({r["id"] for r in rows} & ids)
    assert not leaked, ("%d tombstoned run(s) are reachable from data/manifest/*.parquet: %s. Run "
                        "manifest.quarantine_tombstones(dry_run=False)." % (len(leaked), leaked[:5]))


def test_a_glob_does_not_descend_into_the_quarantine():
    """The whole mechanism rests on this one property of both globbers. Pin it rather than assume it."""
    import glob as _glob
    from pathlib import Path

    import duckdb
    files = _glob.glob(str(manifest.MANIFEST_DIR / "*.parquet"))
    assert files, "no shards at all — this test would pass vacuously"
    assert not any(Path(f).parent.name == "dropped" for f in files), "Python's glob descended into the quarantine"
    con = duckdb.connect()
    try:
        seen = {r["id"] for r in con.execute(
            "SELECT id FROM read_parquet('data/manifest/*.parquet', union_by_name=true)"
        ).fetch_arrow_table().to_pylist()}
    finally:
        con.close()
    quarantined = {r.get("id") for r in manifest.dropped_rows()}
    assert quarantined, "the quarantine is empty — this test would pass vacuously"
    assert not (seen & quarantined), "DuckDB's read_parquet descended into the quarantine directory"


def test_quarantining_loses_nothing():
    """Every tombstone has its row, and it is in exactly one of the two places.

    Deliberately NOT pinned to an absolute corpus size: that would fail on the next run added, which is a false
    alarm, and the count is already pinned in test_corpus_integrity. What matters here is that the move was
    total — a partial move leaves rows gone from the shards and absent from the quarantine, which on this
    corpus is indistinguishable from the silent loss the tombstone mechanism exists to prevent.
    """
    import duckdb
    con = duckdb.connect()
    try:
        live = {r["id"] for r in con.execute(
            "SELECT id FROM read_parquet('data/manifest/*.parquet', union_by_name=true)"
        ).fetch_arrow_table().to_pylist()}
    finally:
        con.close()
    quarantined = manifest.dropped_rows()
    ids = _tombstoned_ids()
    assert len(quarantined) == len(ids), (
        "%d rows quarantined for %d tombstones — the move was partial" % (len(quarantined), len(ids)))
    assert {r.get("id") for r in quarantined} == ids, "the quarantine holds different runs than the tombstones name"
    assert live and not (live & ids)


def test_quarantine_is_idempotent():
    before = len(manifest.dropped_rows())
    res = manifest.quarantine_tombstones(dry_run=True)
    assert res["moved"] == 0, "a second pass found %d rows still to move" % res["moved"]
    assert len(manifest.dropped_rows()) == before
