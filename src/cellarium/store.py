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
    from . import provenance

    if has_manifest():
        # dedup: one row per run (latest ts wins) so re-indexed/duplicate shards don't double-count
        rows = _duck(f"SELECT id,label,perturbation,condition,timeline,seed,qc,reportable FROM {_FROM} "
                     f"QUALIFY row_number() OVER (PARTITION BY COALESCE(simout_path, id) ORDER BY ts DESC) = 1")
    else:
        rows = [{"id": r.id, "label": r.label, "perturbation": r.design.perturbation,
                 "condition": r.design.condition, "timeline": r.design.timeline,
                 "seed": r.design.seeds, "qc": "ok", "reportable": True} for r in _json.list()]
    for r in rows:  # tag each result in-sample (fitted) vs out-of-sample (predicted)
        r["provenance"] = provenance.tag(r.get("perturbation"), r.get("condition"))
    return rows


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


def _viability_verdict(rows: list[dict]) -> dict:
    """Cross-seed viability of one design from its per-seed manifest rows. The verdict is a MIN/BOOL_AND rollup —
    a single seed collapsing (terminal_divided False, low division_rate) flags the design, which a per-seed row
    can't do alone (a lineage can't see the requested depth). Reproduces CORPUS_OBSERVATIONS.md §J."""
    drs = [r["division_rate"] for r in rows if r.get("division_rate") is not None]
    if not drs:  # shards predate the viability channel
        return {"n_seeds": len(rows), "verdict": "unknown",
                "note": "no viability columns in the manifest — run `manifest.record_existing()` to backfill (§J)."}
    gens = [r.get("gens_reached") or 0 for r in rows]
    term = [bool(r.get("terminal_divided")) for r in rows]
    fbf = sum(int(r.get("n_fba_failures") or 0) for r in rows)
    min_dr = min(drs)
    from . import viability_rules
    verdict = viability_rules.verdict(min_dr, all(term), any(term), fbf)
    # §M truncation/crash override: a lineage that CRASHED (run raised) or stopped short of the requested depth is
    # inviable even if its completed generations all divided (the alaS/pheS blind spot — crash on gen-4 startup).
    crashed = any(bool(r.get("crashed")) for r in rows)
    reqs = [r.get("requested_generations") for r in rows if r.get("requested_generations")]
    truncated = bool(reqs) and max(gens) < max(reqs)
    if crashed or truncated:
        verdict = "inviable"
    return {"n_seeds": len(rows), "min_division_rate": round(min_dr, 3),
            "max_gens_reached": max(gens), "requested_generations": (max(reqs) if reqs else None),
            "crashed": crashed, "truncated": truncated,
            "all_terminal_divided": all(term), "n_fba_failures": fbf,
            "verdict": verdict,
            "per_seed": [{"seed": r.get("seed"), "division_rate": r.get("division_rate"),
                          "gens_reached": r.get("gens_reached"), "terminal_divided": r.get("terminal_divided"),
                          "median_division_time_sec": r.get("median_division_time_sec")} for r in rows]}


def viability(perturbation: str, condition: str | None = None) -> dict:
    """Cross-seed VIABILITY (does the lineage divide?) per design, from the manifest viability columns — instant,
    no container. If `condition` is omitted, returns a verdict for every condition under `perturbation` (e.g. all
    gene_knockout variants). The KO readout that does NOT reroute away like a graded growth channel (§J)."""
    if not has_manifest():
        return {"error": "viability needs the Parquet manifest (record a campaign first)."}
    base = "perturbation, condition, seed, division_rate, gens_reached, terminal_divided, n_fba_failures, median_division_time_sec"
    where, params = "WHERE perturbation = ?", [perturbation]
    if condition is not None:
        where += " AND condition = ?"
        params.append(condition)

    def q(cols):
        return _duck(f"SELECT {cols} FROM {_FROM} {where} "
                     f"QUALIFY row_number() OVER (PARTITION BY COALESCE(simout_path,id) ORDER BY ts DESC)=1", params)

    try:  # prefer the crash/truncation columns; fall back if no shard has them yet
        rows = q(base + ", requested_generations, crashed")
    except Exception:
        try:
            rows = q(base)
        except Exception:
            return {"error": "manifest has no viability columns; run `manifest.record_existing()` to backfill (§J)."}
    if not rows:
        return {"error": f"no runs for perturbation='{perturbation}'" +
                (f", condition='{condition}'" if condition is not None else "") + "."}
    by_cond: dict = {}
    for r in rows:
        by_cond.setdefault(r.get("condition"), []).append(r)
    designs = [{"condition": c, **_viability_verdict(rs)} for c, rs in sorted(by_cond.items(), key=lambda x: str(x[0]))]
    return {"perturbation": perturbation, "designs": designs}


def _resolve_run(p: str | None) -> str | None:
    """A stored run path may be repo-relative (portable, current) or absolute (legacy). Return an absolute path so
    local reads work regardless of the caller's CWD."""
    if not p:
        return p
    from pathlib import Path
    pp = Path(p)
    return str(pp if pp.is_absolute() else (Path.cwd() / pp))


def simout_path(result_id: str) -> str | None:
    if has_manifest():
        rows = _duck(f"SELECT simout_path FROM {_FROM} WHERE id = ?", [result_id])
        return _resolve_run(rows[0]["simout_path"]) if rows else None
    return None
