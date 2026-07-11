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
from pathlib import Path

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


def redundancy(target_seeds: int = TARGET_SEEDS, channel: str = "growth_rate", ref_effect_pct: float = 10.0) -> dict:
    """Designs replicated beyond `target_seeds`, each with a POWER-GROUNDED verdict (not a heuristic): given the
    design's OWN replicate CV on `channel`, does dropping to target_seeds still detect a `ref_effect_pct` change?
    If yes the excess seeds are 'prune-safe'; if no they buy detection power -> 'keep-for-power'. The tool decides,
    grounded in real noise; the agent only relays it. Same two-sample math as power_check (alpha .05, power .8)."""
    import math
    import statistics as st

    from . import survey
    rows = survey._deduped_rows([channel])
    if rows and "__error__" in rows[0]:
        return {"error": rows[0]["__error__"]}
    by_design: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = r.get(channel)
        if v is not None:
            by_design[_design(r)].append(float(v))
    gens = {d: i["max_generations"] for d, i in coverage().get("designs", {}).items()}
    K = 2 * (1.96 + 0.84) ** 2   # two-sample n-per-group constant — matches power_check
    over, safe_gb = {}, 0.0
    for d, vals in sorted(by_design.items()):
        n, mean = len(vals), (st.fmean(vals) if vals else 0.0)
        if n <= target_seeds or not mean:
            continue
        cv = st.pstdev(vals) / abs(mean)
        mde_t = round(cv * math.sqrt(K / target_seeds) * 100, 1)
        mde_n = round(cv * math.sqrt(K / n) * 100, 1)
        prune_safe = mde_t <= ref_effect_pct
        gb = _gb(gens.get(d, 0), n - target_seeds)
        over[d] = {"n_seeds": n, "excess_seeds": n - target_seeds, "cv": round(cv, 4),
                   "mde_pct_at_target": mde_t, "mde_pct_at_current": mde_n,
                   "verdict": "prune-safe" if prune_safe else "keep-for-power", "est_gb_if_pruned": gb}
        if prune_safe:
            safe_gb += gb
    n_safe = sum(1 for v in over.values() if v["verdict"] == "prune-safe")
    return {"target_seeds": target_seeds, "channel": channel, "ref_effect_pct": ref_effect_pct,
            "n_designs_over": len(over), "n_prune_safe": n_safe, "est_gb_prunable_safe": round(safe_gb, 2),
            "designs": over,
            "note": f"prune-safe = {target_seeds} seeds still detect a {ref_effect_pct}% change on {channel} (the "
                    f"design's OWN CV); keep-for-power = the extra seeds buy detection. Two-sample a=.05 power=.8; "
                    f"GB counts only prune-safe designs."}


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
            "note": "superseded_manifest_rows are older duplicate rows AUTO-consolidated by manifest.compact() "
                    "(runs after each re-index) — housekeeping, NOT a user/agent decision. n_inviable_by_crash are "
                    "VALID lethal-KO results kept on purpose."}


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


def prune_candidates(target_seeds: int = TARGET_SEEDS, channel: str = "growth_rate",
                     ref_effect_pct: float = 10.0) -> dict:
    """Deterministically resolve the SPECIFIC run dirs safe to prune: the excess seeds (beyond target_seeds) of
    designs the grounded redundancy verdict marks 'prune-safe'. Keeps the lowest seed indices, lists the higher
    ones, with raw-on-disk + GB per candidate. DELETES NOTHING — the caller reviews and acts; the agent only
    relays this grounded list, it NEVER decides deletions (keep-for-power designs are never listed)."""
    red = redundancy(target_seeds, channel, ref_effect_pct)
    if "error" in red:
        return red
    gens = {d: i["max_generations"] for d, i in coverage().get("designs", {}).items()}
    safe = {d for d, i in red["designs"].items() if i["verdict"] == "prune-safe"}
    by_design: dict[str, list[tuple]] = defaultdict(list)
    for r in _latest_per_run(_rows()):
        d = _design(r)
        if d in safe:
            seed = r.get("seed")
            by_design[d].append((seed if seed is not None else 10 ** 9, r.get("run_key")))
    cands, gb_disk = [], 0.0
    for d in sorted(by_design):
        excess = sorted(by_design[d])[target_seeds:]        # keep the lowest target_seeds seeds; list the rest
        per_gb = _gb(gens.get(d, 0), 1)
        for seed, run_root in excess:
            on_disk = bool(run_root) and Path(run_root).exists()
            cands.append({"design": d, "seed": (None if seed == 10 ** 9 else seed), "run_root": run_root,
                          "raw_on_disk": on_disk, "est_gb": (per_gb if on_disk else 0.0)})
            if on_disk:
                gb_disk += per_gb
    return {"target_seeds": target_seeds, "n_candidates": len(cands), "est_gb_on_disk": round(gb_disk, 2),
            "candidates": cands,
            "note": "EXCESS seeds of PRUNE-SAFE designs only (the lowest seed indices are KEPT). Deterministic — the "
                    "agent relays this list, it never decides. DELETES NOTHING.",
            "how_to_delete": "review each run_root; delete only the ones you confirm (IRREVERSIBLE: rm -rf <run_root>), "
                             "then run manifest.compact() to drop their now-orphaned manifest rows."}


def audit_report(target_seeds: int = TARGET_SEEDS) -> dict:
    """Full audit: coverage + safe-to-prune (redundancy + supersession) + gaps/budget. Deletes NOTHING — the
    caller decides. 'Irreplaceable' = every run not flagged prunable."""
    cov = coverage()
    if "error" in cov:
        return cov
    red, sup, gp = redundancy(target_seeds), supersession(), gaps(target_seeds)
    return {"summary": {"n_designs": cov["n_designs"], "n_runs": cov["n_runs"],
                        "redundancy_prune_safe_designs": red.get("n_prune_safe", 0),
                        "est_gb_prunable_safe": red.get("est_gb_prunable_safe", 0.0),
                        "n_inviable_by_crash": sup.get("n_inviable_by_crash", 0),
                        "n_thin_designs": gp.get("n_thin_designs", 0),
                        "feasible_8gen_lineages": gp.get("feasible_8gen_lineages", 0)},
            "coverage": cov, "redundancy": red, "gaps": gp,
            "housekeeping": sup,   # supersession is auto-consolidated by manifest.compact(); NOT a user decision
            "disclaimer": "read-only; nothing deleted. DECISIONS: redundancy carries a per-design power-grounded "
                          "verdict (prune-safe vs keep-for-power); gaps = thin designs + the disk budget. Superseded "
                          "rows are HOUSEKEEPING, auto-consolidated by manifest.compact() after a re-index — not a "
                          "user decision. Crashed runs are valid inviable datapoints, never pruned. GB figures are "
                          "estimates (~0.65 GB/generation)."}
