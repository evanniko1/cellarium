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

MANIFEST_DIR = Path("data/manifest")


def build_record(run_root: Path, design: Design, seed: int) -> SimResult:
    data = reader.read_run(run_root)
    note = "" if "error" not in data else f"reader error: {data['error']}"
    gens = [GenerationResult(**g) for g in data.get("generations", [])]
    label = f"{design.perturbation}·{design.condition or design.timeline or 'basal'}·s{seed}"
    return SimResult(id=f"{design.perturbation}_{seed}_{uuid.uuid4().hex[:8]}", label=label,
                     design=design, channels=data.get("channels", {}), generations=gens, note=note,
                     channel_stats=data.get("channel_stats", {}), series=data.get("series", {}),
                     media_segments=data.get("media_segments", []), pathways=data.get("pathways", {}),
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
           "simout_path": str(Path(run_root).resolve()),  # RESOLVED so the read-time dedup key is consistent
           # (absolute vs relative path strings were treated as distinct runs — a dedup-fragility bug)
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


def _label(design: Design, seed: int) -> str:
    return f"{design.perturbation}/{design.condition or design.timeline or 'basal'} seed{seed}"


def _run_job(design: Design, seed: int, generations: int) -> dict:
    run_root = runner.run_one(design, seed, generations)
    return _flat_row(build_record(run_root, design, seed), seed, run_root, requested_generations=generations)


def _crash_row(design: Design, seed: int, generations: int, exc: Exception) -> dict:
    """A row for a sim that CRASHED (run_one raised) — captures the partial on-disk lineage so the crash is a
    first-class INVIABLE point (§M), not a silently-dropped job. crashed=True overrides any 'looks viable' partial."""
    run_root = runner._run_subpath(design, seed, "cellarium")
    try:
        rec = build_record(run_root, design, seed) if run_root.exists() else None
    except Exception:
        rec = None
    if rec is not None:
        row = _flat_row(rec, seed, run_root, requested_generations=generations, crashed=True)
        row["qc"], row["reportable"], row["note"] = "crashed", False, f"sim crashed: {str(exc)[:150]}"
        return row
    return {"id": f"{design.perturbation}_{seed}_crash", "label": _label(design, seed),
            "perturbation": design.perturbation, "condition": design.condition, "timeline": design.timeline,
            "seed": seed, "generations": 0, "requested_generations": generations, "crashed": True,
            "qc": "crashed", "reportable": False, "gens_reached": 0, "division_rate": 0.0,
            "terminal_divided": False, "n_fba_failures": 0, "note": f"sim crashed (no data): {str(exc)[:150]}",
            "simout_path": str(run_root)}


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
    return append_shard(rows, name=f"{getpass.getuser()}-index")


if __name__ == "__main__":  # `python -m cellarium.manifest` -> index existing runs without re-simulating
    shard = record_existing()
    print(f"Indexed existing runs -> {shard}")
