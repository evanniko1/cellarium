"""Unified corpus read layer: DuckDB over the Parquet manifest shards when present, else the JSON demo cache.

The manifest (union of contributor shards) is the source of truth once we start generating; the JSON cache
keeps the zero-setup demo working before then.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import ResultStore

MANIFEST_DIR = Path("data/manifest")
MANIFEST_GLOB = "data/manifest/*.parquet"
# union_by_name tolerates shards with different channel sets (contributors, schema drift over time)
_FROM = f"read_parquet('{MANIFEST_GLOB}', union_by_name=true)"
_json = ResultStore()
_SAFE = re.compile(r"^[A-Za-z0-9_:.]+$")


def has_manifest() -> bool:
    return MANIFEST_DIR.exists() and any(MANIFEST_DIR.glob("*.parquet"))


def _duck(sql: str, params: list | None = None) -> list[dict]:
    import duckdb

    con = duckdb.connect()
    try:
        return con.execute(sql, params or []).fetch_arrow_table().to_pylist()
    finally:
        con.close()


def list_results() -> list[dict]:
    if has_manifest():
        return _duck(f"SELECT id,label,perturbation,condition,timeline,seed,qc,reportable FROM {_FROM}")
    return [{"id": r.id, "label": r.label, "perturbation": r.design.perturbation,
             "condition": r.design.condition, "timeline": r.design.timeline,
             "seed": r.design.seeds, "qc": "ok", "reportable": True} for r in _json.list()]


def _attach_dynamics(out: dict, channel: str, row: dict) -> None:
    """Add this channel's downsampled trajectory + per-media-segment means from the manifest JSON columns."""
    import json

    try:
        ser = json.loads(row.get("series") or "{}").get(channel)
        if ser:
            out["series"] = ser
        segs = json.loads(row.get("media_segments") or "[]")
        if segs:
            out["by_media_segment"] = [{"media": s.get("media"), "t0": s.get("t0"), "t1": s.get("t1"),
                                        "mean": (s.get("means") or {}).get(channel)} for s in segs]
    except Exception:
        pass


def read_channel(result_id: str, channel: str) -> dict:
    if not _SAFE.match(channel):
        return {"error": "invalid channel name"}
    if has_manifest():
        try:
            rows = _duck(f'SELECT "{channel}" AS value, qc, reportable, series, media_segments '
                         f"FROM {_FROM} WHERE id = ?", [result_id])
        except Exception:
            return {"error": f"channel '{channel}' not a manifest column; try read_species for arbitrary molecules."}
        if not rows:
            return {"error": f"no result '{result_id}'."}
        r = rows[0]
        out = {"result_id": result_id, "channel": channel, "value": r.get("value"),
               "qc": r.get("qc"), "reportable": r.get("reportable"), "grounded_from": "manifest"}
        _attach_dynamics(out, channel, r)  # trajectory + per-media-segment means (the transient the mean hides)
        return out
    r = _json.get(result_id)
    if not r:
        return {"error": f"no result '{result_id}'."}
    if channel not in r.channels:
        return {"error": f"channel '{channel}' unavailable.", "available": sorted(r.channels)}
    return {"result_id": result_id, "channel": channel, "value": r.channels[channel],
            "unit": r.units.get(channel, ""), "grounded_from": f"simOut::{result_id}"}


def simout_path(result_id: str) -> str | None:
    if has_manifest():
        rows = _duck(f"SELECT simout_path FROM {_FROM} WHERE id = ?", [result_id])
        return rows[0]["simout_path"] if rows else None
    return None
