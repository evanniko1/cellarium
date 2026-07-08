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
        return _duck(f"SELECT id,label,perturbation,condition,timeline,seed,qc,reportable "
                     f"FROM read_parquet('{MANIFEST_GLOB}')")
    return [{"id": r.id, "label": r.label, "perturbation": r.design.perturbation,
             "condition": r.design.condition, "timeline": r.design.timeline,
             "seed": r.design.seeds, "qc": "ok", "reportable": True} for r in _json.list()]


def read_channel(result_id: str, channel: str) -> dict:
    if not _SAFE.match(channel):
        return {"error": "invalid channel name"}
    if has_manifest():
        try:
            rows = _duck(f'SELECT "{channel}" AS value, qc, reportable FROM read_parquet(\'{MANIFEST_GLOB}\') '
                         f"WHERE id = ?", [result_id])
        except Exception:
            return {"error": f"channel '{channel}' not a manifest column; try read_species for arbitrary molecules."}
        if not rows:
            return {"error": f"no result '{result_id}'."}
        r = rows[0]
        return {"result_id": result_id, "channel": channel, "value": r.get("value"),
                "qc": r.get("qc"), "reportable": r.get("reportable"), "grounded_from": "manifest"}
    r = _json.get(result_id)
    if not r:
        return {"error": f"no result '{result_id}'."}
    if channel not in r.channels:
        return {"error": f"channel '{channel}' unavailable.", "available": sorted(r.channels)}
    return {"result_id": result_id, "channel": channel, "value": r.channels[channel],
            "unit": r.units.get(channel, ""), "grounded_from": f"simOut::{result_id}"}


def simout_path(result_id: str) -> str | None:
    if has_manifest():
        rows = _duck(f"SELECT simout_path FROM read_parquet('{MANIFEST_GLOB}') WHERE id = ?", [result_id])
        return rows[0]["simout_path"] if rows else None
    return None
