"""SCI-QC-2 — the per-segment mean repair, and the data-loss hazard it nearly shipped with.

The safety test here is `test_a_repaired_row_preserves_every_column`. The manifest is append-only and the read
layer resolves `union_by_name` + `ORDER BY ts DESC`, so a superseding row that omits a column does not leave
the old value in place — it NULLs it. The first version of `repair()` built its rows from
`store.list_results()`, which projects 9 of 43 columns; writing that would have silently destroyed every
channel value, the series, the pathways and the species panel for exactly the runs it was trying to fix.
"""

from __future__ import annotations

import json

import pytest

from cellarium import segments, store, survey


def _needs_manifest():
    if not store.has_manifest():
        pytest.skip("no manifest")


def _timeline_rows():
    return [r for r in store.list_results() if (r.get("perturbation") or "") == "timeline"]


def test_a_repaired_row_preserves_every_column():
    """THE safety property. A repaired row must carry every column the original had — anything missing is
    silently destroyed by the ts-DESC supersession, not merely left alone."""
    _needs_manifest()
    rows = _timeline_rows()
    if not rows:
        pytest.skip("no timeline runs")
    res = segments.repair(write=False)
    if not res["n_corrupted"]:
        pytest.skip("nothing corrupted to repair")
    for f in res["findings"]:
        base = segments.full_row(f["result_id"])
        assert base is not None
        assert len(base) > 30, f"expected the FULL row, got {len(base)} columns — projection leak"
        # the projected view must never be mistaken for the full row. `provenance` is computed in Python by
        # `list_results` rather than stored, so it is legitimately absent from the parquet row.
        proj = {k for k in next(r for r in store.list_results() if r["id"] == f["result_id"])} - {"provenance"}
        assert proj.issubset(set(base)) and len(base) > len(proj)


def test_repair_is_dry_by_default_and_writes_nothing():
    """A corpus-mutating function must not mutate on the default call."""
    _needs_manifest()
    import glob
    before = sorted(glob.glob("data/manifest/*.parquet"))
    res = segments.repair()
    assert res["dry_run"] is True
    assert "shard_written" not in res
    assert sorted(glob.glob("data/manifest/*.parquet")) == before


def test_the_upshift_segments_are_corrupt_and_the_downshift_are_not():
    """The asymmetry is the proof the diagnosis is right: the upshift's media column is <U7 (its first value is
    the 7-char `minimal`) so its later 24-char medium truncates, while the downshift starts with the long name,
    gets <U24, and truncates nothing. If a repair ever flagged a downshift seed, the model of the bug is wrong."""
    _needs_manifest()
    if not _timeline_rows():
        pytest.skip("no timeline runs")
    res = segments.repair(write=False)
    if not res["n_corrupted"]:
        pytest.skip("no local raw for the shift designs")
    for f in res["findings"]:
        assert f["design"].startswith("timeline/0 minimal,"), (
            f"only the UPSHIFT should be corrupt; got {f['design']}")
        assert "minimal_plus_amino_acids" in f["recomputed"], f
        assert f["stored"] == ["minimal"], f


def test_recompute_covers_every_generation_not_just_the_last():
    """SCI-QC-3: the stored value comes from `_dynamics(gs[-1])`. On a 4-generation run that is ~20% of the
    lineage, and the retained window can carry the wrong label while being internally self-consistent."""
    _needs_manifest()
    for r in _timeline_rows():
        rec = segments.recompute(r["id"])
        if not rec.get("available"):
            continue
        if rec["n_generations"] > 1:
            n_last = sum(s["n"] for s in rec["last_generation"])
            n_all = sum(s["n"] for s in rec["whole_lineage"])
            assert n_all > n_last, "whole_lineage must cover more timesteps than the last generation alone"
            assert len(rec["per_generation"]) == rec["n_generations"]
            return
    pytest.skip("no multi-generation timeline run with local raw")


def test_recomputed_segments_split_the_step_the_stored_mean_hid():
    """The scientific point. Where the recorder collapsed a shift into one segment, its 'mean' averages across
    a step. The repair must recover BOTH sides, and they must differ by far more than the stored single value
    could represent."""
    _needs_manifest()
    res = segments.repair(write=False)
    if not res["n_corrupted"]:
        pytest.skip("nothing corrupted")
    worst = max(f["worst_fold_error"] or 0 for f in res["findings"])
    assert worst > 5, f"expected a large hidden step; worst fold was {worst}"
    for f in res["findings"]:
        lineage = f["channels"]["fba_objective"]["recomputed_whole_lineage"]
        if len(lineage) >= 2:
            vals = [v for _m, v in lineage if v is not None]
            assert max(vals) > 5 * min(vals), (f["result_id"], lineage)


def test_recompute_refuses_when_raw_is_absent():
    """Same silent-absence rule as the miase repair: no raw means unavailable, never an empty-but-confident
    answer that downstream code would compare against and act on."""
    for bogus in ("not_a_result", ""):
        out = segments.recompute(bogus)
        assert out.get("available") is False and "why" in out
        assert "last_generation" not in out


def test_repair_targets_only_designs_with_a_declared_timeline():
    """A static-media design has one legitimate segment; it must never be 'repaired'."""
    _needs_manifest()
    res = segments.repair(write=False)
    flagged = {f["design"] for f in res["findings"]}
    for d in flagged:
        rows = [r for r in store.list_results() if survey.design_key(r) == d]
        assert rows and all(r.get("timeline") for r in rows), d


def test_segments_are_json_serialisable_for_the_shard():
    """The repaired value is written as a JSON string into a parquet column; a numpy float would break it."""
    _needs_manifest()
    for r in _timeline_rows():
        rec = segments.recompute(r["id"])
        if rec.get("available"):
            json.dumps(rec["last_generation"])
            json.dumps(rec["whole_lineage"])
            return
    pytest.skip("no timeline run with local raw")
