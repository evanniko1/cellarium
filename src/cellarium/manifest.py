"""Build shardable Parquet manifest records from simOut, via the container reader + the QC guardrail.

Each contributor writes their own shard (data/manifest/<contributor>-<stamp>.parquet); the corpus is the
union of shards (concatenation), queried with DuckDB. Full simOut stays local; the manifest carries
provenance + QC + summary channels (+ a curated species panel, once decided — see docs/DECISIONS.md D2).
Reading of simOut happens inside the model image (see reader.py / _reader_worker.py).
"""

from __future__ import annotations

import getpass
import json
import socket
import time
import uuid
from pathlib import Path

from . import qc, reader, runner
from .model import Design, GenerationResult, SimResult


def _portable_runpath(run_root) -> str:
    """Repo-relative, forward-slash run path (e.g. 'runs/cellarium/<variant>/<seed>'). A stable dedup key that
    does NOT embed the machine's absolute directory — so the distilled/public manifest can't leak it. `store`
    resolves it back to an absolute path for local reads. Falls back to a slash-normalized path if no runs root
    is found."""
    parts = str(run_root).replace("\\", "/").split("/")
    for i, c in enumerate(parts):
        if c == "runs" or c.startswith("runs_"):
            return "/".join(parts[i:])
    return str(run_root).replace("\\", "/")

MANIFEST_DIR = Path("data/manifest")


def _design_tag(design: Design) -> str:
    """The label's middle segment. For a gene KO, the GENE is the identity — but the propose (agent/UI) path sets
    condition='basal' with the gene in params.target_genes, while generate.py sets condition='KO:<gene>'. Both must
    label as 'KO:<gene>' so a KO run is never mislabeled 'basal'. Appends a non-basal media as '@<cond>'."""
    genes = list((design.params or {}).get("target_genes") or [])
    if "gene_knockout" in design.perturbation and genes:
        tag = "KO:" + "+".join(genes)
        if design.condition and design.condition not in ("basal", "KO:" + "+".join(genes)):
            tag += "@" + design.condition
        return tag
    return design.condition or design.timeline or "basal"


def build_record(run_root: Path, design: Design, seed: int) -> SimResult:
    data = reader.read_run(run_root)
    note = "" if "error" not in data else f"reader error: {data['error']}"
    gens = [GenerationResult(**g) for g in data.get("generations", [])]
    label = f"{design.perturbation}·{_design_tag(design)}·s{seed}"
    return SimResult(id=f"{design.perturbation}_{seed}_{uuid.uuid4().hex[:8]}", label=label,
                     design=design, channels=data.get("channels", {}), generations=gens, note=note,
                     channel_stats=data.get("channel_stats", {}), series=data.get("series", {}),
                     media_segments=data.get("media_segments", []), pathways=data.get("pathways", {}),
                     species_panel=data.get("species_panel", {}),
                     viability=data.get("viability", {}))


def _flat_row(rec: SimResult, seed: int, run_root: Path,
              requested_generations: int | None = None, crashed: bool = False) -> dict:
    overall, per = qc.check_result(rec)
    row = {"id": rec.id, "label": rec.label,
           "requested_generations": requested_generations,   # for the viability truncation signal (§M)
           "crashed": crashed,                                # the sim raised — inviable regardless of partial data
           "contributor": getpass.getuser(), "host": socket.gethostname(), "ts": time.time(),
           "perturbation": rec.design.perturbation, "condition": rec.design.condition,
           "timeline": rec.design.timeline, "seed": seed, "generations": len(rec.generations),
           "qc": overall.value, "generation_qc": json.dumps([s.value for s in per]),
           "reportable": qc.is_reportable(rec), "note": rec.note,
           "per_generation": json.dumps([{"i": g.index, "growth": g.growth_mean, "ppgpp": g.ppgpp_mean,
                                           "divided": g.divided} for g in rec.generations]),
           "pathways": json.dumps(rec.pathways),   # {pathway: proteome_fraction} — surveyed as channels
           "species_panel": json.dumps(rec.species_panel),  # {monomer_id: {mean,last,series}} — per-species depth (scope A)
           "simout_path": _portable_runpath(run_root),  # repo-RELATIVE, forward-slash: a stable dedup key that
           # does NOT leak the machine's absolute path into the distilled/public manifest (store resolves it back
           # to an absolute path for local reads).
           "channel_stats": json.dumps(rec.channel_stats),   # dynamics (JSON) — depth without a live read
           "series": json.dumps(rec.series),
           "media_segments": json.dumps(rec.media_segments)}
    # viability (§J) as first-class queryable columns: does this lineage divide? A metabolic KO reroutes (viable);
    # a machinery KO collapses. gens_reached < requested (a cross-seed GROUP BY) is the 'died early' signal.
    v = rec.viability or {}
    row.update({"division_rate": v.get("division_rate"), "gens_reached": v.get("gens_reached"),
                "terminal_divided": v.get("terminal_divided"), "n_fba_failures": v.get("n_fba_failures"),
                "median_division_time_sec": v.get("median_division_time_sec")})
    row.update(rec.channels)  # flatten summary channel means into columns for easy DuckDB SQL
    return row


def append_shard(rows: list[dict], name: str | None = None) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not rows:
        raise RuntimeError("nothing to write (no rows)")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{name}.parquet" if name else f"{getpass.getuser()}-{int(time.time())}-{uuid.uuid4().hex[:6]}.parquet"
    shard = MANIFEST_DIR / fname
    pq.write_table(pa.Table.from_pylist(rows), shard)
    return shard


def compact(dry_run: bool = False) -> dict:
    """Housekeeping guardrail: consolidate ALL manifest shards into ONE deduped shard, dropping superseded rows
    (older duplicates per run; latest ts wins, matching the read layer). Deterministic — NO judgment — so the
    shard files don't blow up as re-indexes accumulate. Not an agent/user decision; runs automatically after a
    re-index (see record_existing). Writes + verifies the new shard, THEN removes the olds; dry_run only reports."""
    import glob
    import os

    import duckdb

    glob_pat = "data/manifest/*.parquet"
    files = sorted(glob.glob(str(MANIFEST_DIR / "*.parquet")))
    if not files:
        return {"error": "no manifest shards to compact"}
    con = duckdb.connect()
    try:
        latest = con.execute(
            f"SELECT * FROM read_parquet('{glob_pat}', union_by_name=true) "
            "QUALIFY row_number() OVER (PARTITION BY COALESCE(simout_path, id) ORDER BY ts DESC) = 1"
        ).fetch_arrow_table().to_pylist()
        total = con.execute(f"SELECT count(*) FROM read_parquet('{glob_pat}', union_by_name=true)").fetchone()[0]
    finally:
        con.close()
    res = {"files_before": len(files), "rows_before": total, "rows_after": len(latest),
           "superseded_dropped": total - len(latest), "dry_run": dry_run}
    if dry_run or not latest:
        return res
    new = append_shard(latest, name=f"{getpass.getuser()}-compact")  # write the consolidated shard FIRST
    for f in files:
        if Path(f).resolve() != Path(new).resolve():                 # ...then drop the olds
            os.remove(f)
    res.update({"files_after": 1, "shard": str(new)})
    return res


def prune(where_sql: str, dry_run: bool = True) -> dict:
    """Delete manifest rows matching a SQL predicate and rewrite ONE consolidated shard. DELIBERATE and auditable
    (dry_run returns exactly what WOULD be dropped) — unlike compact() this is NOT automatic, because it removes
    rows you name. Use ONLY for infrastructure-crash artifacts (e.g. a disk-crashed batch); NEVER for valid results.
    Keeps rows by id (NULL-safe); write-new-then-delete-old."""
    import glob
    import os

    import duckdb

    glob_pat = "data/manifest/*.parquet"
    files = sorted(glob.glob(str(MANIFEST_DIR / "*.parquet")))
    if not files:
        return {"error": "no manifest shards"}
    con = duckdb.connect()
    try:
        drop = con.execute(f"SELECT id, perturbation, condition, seed, generations, crashed, simout_path "
                           f"FROM read_parquet('{glob_pat}', union_by_name=true) WHERE {where_sql}"
                           ).fetch_arrow_table().to_pylist()
        allrows = con.execute(f"SELECT * FROM read_parquet('{glob_pat}', union_by_name=true)"
                              ).fetch_arrow_table().to_pylist()
    finally:
        con.close()
    drop_ids = {r["id"] for r in drop}
    keep = [r for r in allrows if r.get("id") not in drop_ids]
    res = {"where": where_sql, "n_dropped": len(drop_ids), "n_kept": len(keep), "dry_run": dry_run,
           "dropped_sample": [{k: r.get(k) for k in ("perturbation", "condition", "seed", "generations", "crashed")}
                              for r in drop[:15]]}
    if dry_run:
        return res
    new = append_shard(keep, name=f"{getpass.getuser()}-compact")
    for f in files:
        if Path(f).resolve() != Path(new).resolve():
            os.remove(f)
    res["shard"] = str(new)
    return res


def _label(design: Design, seed: int) -> str:
    return f"{design.perturbation}/{design.condition or design.timeline or 'basal'} seed{seed}"


def _run_job(design: Design, seed: int, generations: int) -> dict:
    run_root = runner.run_one(design, seed, generations)
    return _flat_row(build_record(run_root, design, seed), seed, run_root, requested_generations=generations)


def _classify_crash(exc: Exception) -> str:
    """infrastructure (disk / I/O / host) vs model (FBA / biology) crash. A lethal KO and an infra-crash otherwise
    look identical in the row (generations=0, crashed=True), so tagging the CAUSE at write time is the only way to
    tell a valid inviable datapoint from a disk-crash artifact without batch archaeology."""
    s = f"{type(exc).__name__}: {exc}".lower()
    if any(k in s for k in ("oserror", "ioerror", "errno 5", "winerror", "no space", "input/output", "disk full")):
        return "infrastructure"
    if "returned non-zero" in s or "docker" in s:      # container failure — ambiguous (could be either)
        return "container"
    return "model"


def _crash_row(design: Design, seed: int, generations: int, exc: Exception) -> dict:
    """A row for a sim that CRASHED (run_one raised) — captures the partial on-disk lineage so the crash is a
    first-class INVIABLE point (§M), not a silently-dropped job. crashed=True overrides any 'looks viable' partial.
    crash_type distinguishes a real lethal KO (model) from a disk/host failure (infrastructure)."""
    run_root = runner._run_subpath(design, seed, "cellarium")
    ctype = _classify_crash(exc)
    try:
        rec = build_record(run_root, design, seed) if run_root.exists() else None
    except Exception:
        rec = None
    if rec is not None:
        row = _flat_row(rec, seed, run_root, requested_generations=generations, crashed=True)
        row["qc"], row["reportable"], row["note"] = "crashed", False, f"sim crashed: {str(exc)[:150]}"
        row["crash_type"] = ctype
        return row
    return {"id": f"{design.perturbation}_{seed}_crash", "label": _label(design, seed),
            "perturbation": design.perturbation, "condition": design.condition, "timeline": design.timeline,
            "seed": seed, "generations": 0, "requested_generations": generations, "crashed": True,
            "qc": "crashed", "reportable": False, "gens_reached": 0, "division_rate": 0.0, "crash_type": ctype,
            "terminal_divided": False, "n_fba_failures": 0, "note": f"sim crashed (no data): {str(exc)[:150]}",
            "simout_path": _portable_runpath(run_root)}


def campaign(designs: list[Design], seeds: list[int], generations: int = 1, parallel: int = 1) -> Path:
    """Run an in-envelope design x seed matrix on the public model and append a manifest shard.

    Crash-isolated: a failed sim is logged and skipped (never kills the batch), and the shard is written for
    whatever completed — so a long unattended run always leaves a usable corpus. `parallel>1` runs that many
    sims concurrently (each writes a distinct dir since Fix #1, and loads ~1GB sim_data — size to host RAM).
    """
    jobs = [(d, s) for d in designs for s in seeds]
    n = len(jobs)
    rows: list[dict] = []

    if parallel <= 1:
        for i, (d, s) in enumerate(jobs, 1):
            print(f"[{i}/{n}] {_label(d, s)} ...", flush=True)
            try:
                rows.append(_run_job(d, s, generations))
                print(f"[{i}/{n}] {_label(d, s)} -> qc={rows[-1]['qc']}", flush=True)
            except Exception as exc:  # one bad sim must not lose the whole batch — but record it as a crash (§M)
                print(f"[{i}/{n}] {_label(d, s)} FAILED: {exc}", flush=True)
                try:
                    rows.append(_crash_row(d, s, generations, exc))
                except Exception:
                    pass
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print(f"Running {n} sims, {parallel} at a time (each loads ~1GB sim_data — mind host RAM).", flush=True)
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            fut = {ex.submit(_run_job, d, s, generations): (d, s) for d, s in jobs}
            for k, f in enumerate(as_completed(fut), 1):
                d, s = fut[f]
                try:
                    rows.append(f.result())
                    print(f"[{k}/{n}] {_label(d, s)} -> qc={rows[-1]['qc']}", flush=True)
                except Exception as exc:
                    print(f"[{k}/{n}] {_label(d, s)} FAILED: {exc}", flush=True)
                    try:
                        rows.append(_crash_row(d, s, generations, exc))
                    except Exception:
                        pass

    if not rows:
        raise RuntimeError("campaign produced no completed runs")
    return append_shard(rows)


def _discover_runs(sim_path: str = "cellarium") -> list[Path]:
    """Existing <variant>/<seed> run roots already on disk (a run root is a simOut's 3rd parent)."""
    base = runner._out_root(sim_path)
    return sorted({so.parents[2] for so in base.glob("**/simOut")}) if base.exists() else []


def _design_from_dir(run_root: Path) -> tuple[Design, int]:
    seed = int(run_root.name)
    prov = run_root / "design.json"
    if prov.exists():  # true design written at run time (survives the opaque variant-dir naming)
        return Design.model_validate_json(prov.read_text(encoding="utf-8")), seed
    perturbation, _, idx = run_root.parent.name.rpartition("_")  # fallback for pre-provenance runs
    return Design(perturbation=perturbation, params={"variant_index": int(idx)}), seed


def record_existing(sim_path: str = "cellarium") -> Path:
    """Index runs ALREADY on disk into a manifest shard — no re-simulation (one container read each).

    Idempotent: writes to a fixed per-contributor shard (overwritten each call), so repeated re-indexing
    doesn't pile up files; read-time dedup handles any remaining overlap with campaign shards.
    """
    rows: list[dict] = []
    for run_root in _discover_runs(sim_path):
        design, seed = _design_from_dir(run_root)
        rows.append(_flat_row(build_record(run_root, design, seed), seed, run_root))
    if not rows:
        raise RuntimeError(f"no existing runs found under {runner._out_root(sim_path)}")
    append_shard(rows, name=f"{getpass.getuser()}-index")
    res = compact()   # guardrail: auto-consolidate so re-indexes don't pile up superseded shards
    return Path(res["shard"]) if "shard" in res else MANIFEST_DIR


if __name__ == "__main__":  # `python -m cellarium.manifest` -> index existing runs without re-simulating
    shard = record_existing()
    print(f"Indexed existing runs -> {shard}")
