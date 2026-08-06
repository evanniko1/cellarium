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
    ids = _tombstoned_ids()
    seen = [r for r in store.list_results() if r.get("id") in ids]
    if not seen:
        pytest.skip("tombstoned runs have no surviving manifest rows here")
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
    if res.get("n_dropped_hidden"):
        assert res.get("note"), "runs were hidden with no note — a silent omission is the bug, not the fix"


def test_dropped_runs_are_still_retrievable_on_request():
    """Excluded by default, never erased: the audit trail must survive the filter."""
    ids = _tombstoned_ids()
    res = tools.list_results(include_dropped=True)
    got = {r["id"] for r in res["results"]} & ids
    assert got, "include_dropped=True returned none of the tombstoned runs — the record has been lost"
