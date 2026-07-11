"""Corpus audit — a read-only inventory of the simulation corpus.

Answers the four librarian questions over the manifest (no Docker, no raw reads, deletes NOTHING):
  * coverage     — what's in the corpus: designs, seeds/design, generation depth, viability spread
  * redundancy   — designs replicated beyond the target (the excess seeds are safe-to-prune, with GB freed)
  * supersession — dead-weight rows: an older run superseded by a newer one, and crashed runs still on disk
  * gaps         — power-thin designs (< target seeds) + a disk-feasibility budget for what more will FIT

`audit_report()` combines them, separating SAFE-TO-PRUNE (redundancy + supersession) from irreplaceable, so the
caller decides. The gaps + budget are the data layer the council + agent turn into feasibility-gated experiment
proposals ("what to run to strengthen / disconfirm a claim, given the disk budget"). GB figures are ESTIMATES
from the observed ~650 MB/generation footprint (see docker-sim-ops), not a live directory scan.
"""

from __future__ import annotations

import shutil
from collections import Counter, defaultdict

MANIFEST_GLOB = "data/manifest/*.parquet"
GB_PER_GENERATION = 0.65   # observed simOut footprint per generation
TARGET_SEEDS = 4           # replication target: > this = redundancy candidate, < this = power gap


def _rows() -> list[dict]:
    """Every shard row (NOT deduped — supersession needs the duplicates). union_by_name tolerates schema drift."""
    import duckdb

    con = duckdb.connect()
    try:
        q = ("SELECT COALESCE(simout_path, id) AS run_key, id, perturbation, condition, timeline, seed, "
             "qc, reportable, crashed, ts, generations, requested_generations, gens_reached "
             f"FROM read_parquet('{MANIFEST_GLOB}', union_by_name=true)")
        return con.execute(q).fetch_arrow_table().to_pylist()
    except Exception as exc:
        return [{"__error__": str(exc)}]
    finally:
        con.close()


def _design(r: dict) -> str:
    return f"{r['perturbation']}/{r.get('condition') or r.get('timeline') or 'basal'}"


def _latest_per_run(rows: list[dict]) -> list[dict]:
    """Newest row per run_key — matches store's read-time dedup (latest ts wins)."""
    best: dict[str, dict] = {}
    for r in rows:
        k = r["run_key"]
        if k not in best or (r.get("ts") or 0) > (best[k].get("ts") or 0):
            best[k] = r
    return list(best.values())


def _gb(generations: int | None, seeds: int = 1) -> float:
    return round((generations or 0) * GB_PER_GENERATION * seeds, 2)


def coverage() -> dict:
    """Per-design inventory: seed count, max generation depth, and the QC verdict spread."""
    rows = _rows()
    if rows and "__error__" in rows[0]:
        return {"error": rows[0]["__error__"]}
    live = _latest_per_run(rows)
    by_design: dict[str, list[dict]] = defaultdict(list)
    for r in live:
        by_design[_design(r)].append(r)
    designs = {}
    for d, rs in sorted(by_design.items()):
        max_gen = max((r.get("generations") or 0) for r in rs)
        designs[d] = {"n_seeds": len(rs), "max_generations": max_gen,
                      "qc": dict(Counter(r.get("qc") for r in rs)), "est_gb": _gb(max_gen, len(rs))}
    return {"n_designs": len(designs), "n_runs": len(live),
            "n_perturbation_types": len({r["perturbation"] for r in live}), "designs": designs}


def redundancy(target_seeds: int = TARGET_SEEDS) -> dict:
    """Designs replicated beyond `target_seeds` — the excess seeds are safe-to-prune, with estimated GB freed."""
    cov = coverage()
    if "error" in cov:
        return cov
    over, total = {}, 0.0
    for d, info in cov["designs"].items():
        excess = info["n_seeds"] - target_seeds
        if excess > 0:
            gb = _gb(info["max_generations"], excess)
            over[d] = {"n_seeds": info["n_seeds"], "excess_seeds": excess, "est_gb_prunable": gb}
            total += gb
    return {"target_seeds": target_seeds, "n_designs_over": len(over),
            "est_gb_prunable": round(total, 2), "designs": over}


def supersession() -> dict:
    """Truly dead-weight manifest rows: an OLDER row for a run_key that also has a NEWER row (e.g. the enriched
    re-index superseding the pre-enrichment rows) — safe to COMPACT the shards (re-index dups free ~0 raw GB, the
    run_root being unchanged). Crashed runs are deliberately NOT flagged as prunable: a crashed KO is a first-class
    INVIABLE datapoint (keep-all-models), not garbage — only infrastructure crashes would be junk and those never
    reach the manifest (the batch stalls before writing). n_inviable_by_crash is a coverage fact, not a target."""
    rows = _rows()
    if rows and "__error__" in rows[0]:
        return {"error": rows[0]["__error__"]}
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_key[r["run_key"]].append(r)
    stale = sum(len(rs) - 1 for rs in by_key.values() if len(rs) > 1)
    inviable = sorted({_design(r) for r in _latest_per_run(rows) if r.get("crashed")})
    return {"superseded_manifest_rows": stale, "n_inviable_by_crash": len(inviable),
            "inviable_by_crash_designs": inviable,
            "note": "superseded_manifest_rows = older duplicate rows safe to compact (re-index dups free ~0 raw "
                    "GB). n_inviable_by_crash are VALID lethal-KO results kept on purpose — NOT prune targets."}


def gaps(target_seeds: int = TARGET_SEEDS) -> dict:
    """Power-thin designs (< target_seeds) + a disk-feasibility budget: how many more full 8-gen lineages FIT in
    free disk now. This is the data layer the council + agent rank into claim-impact-ordered, feasibility-gated
    experiment proposals (the open-ended 'what should we run next?')."""
    cov = coverage()
    if "error" in cov:
        return cov
    thin = {d: {"n_seeds": info["n_seeds"], "seeds_needed": target_seeds - info["n_seeds"]}
            for d, info in cov["designs"].items() if info["n_seeds"] < target_seeds}
    free_gb = round(shutil.disk_usage(".").free / (1024 ** 3), 1)
    per_lineage = _gb(8, 1)   # a full 8-generation lineage
    return {"target_seeds": target_seeds, "n_thin_designs": len(thin), "thin_designs": thin,
            "free_disk_gb": free_gb, "est_gb_per_8gen_lineage": per_lineage,
            "feasible_8gen_lineages": int(free_gb / per_lineage) if per_lineage else 0,
            "note": "thin_designs are power gaps; feasible_8gen_lineages is the disk ceiling for new runs."}


def audit_report(target_seeds: int = TARGET_SEEDS) -> dict:
    """Full audit: coverage + safe-to-prune (redundancy + supersession) + gaps/budget. Deletes NOTHING — the
    caller decides. 'Irreplaceable' = every run not flagged prunable."""
    cov = coverage()
    if "error" in cov:
        return cov
    red, sup, gp = redundancy(target_seeds), supersession(), gaps(target_seeds)
    return {"summary": {"n_designs": cov["n_designs"], "n_runs": cov["n_runs"],
                        "est_gb_prunable_redundancy": red.get("est_gb_prunable", 0.0),
                        "superseded_manifest_rows": sup.get("superseded_manifest_rows", 0),
                        "n_inviable_by_crash": sup.get("n_inviable_by_crash", 0),
                        "n_thin_designs": gp.get("n_thin_designs", 0),
                        "feasible_8gen_lineages": gp.get("feasible_8gen_lineages", 0)},
            "coverage": cov, "redundancy": red, "supersession": sup, "gaps": gp,
            "disclaimer": "read-only inventory; nothing deleted. redundancy = CANDIDATE excess seeds (keep them if "
                          "a design needs the statistical power); superseded_manifest_rows = older duplicate rows "
                          "safe to compact. Crashed runs are valid inviable datapoints, never prune targets. "
                          "GB figures are estimates (~0.65 GB/generation)."}
