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
    channels = data.get("channels", {})
    label = f"{design.perturbation}·{design.condition or design.timeline or 'basal'}·s{seed}"
    return SimResult(id=f"{design.perturbation}_{seed}_{uuid.uuid4().hex[:8]}", label=label,
                     design=design, channels=channels, generations=gens, note=note)


def _flat_row(rec: SimResult, seed: int, run_root: Path) -> dict:
    overall, per = qc.check_result(rec)
    row = {"id": rec.id, "label": rec.label,
           "contributor": getpass.getuser(), "host": socket.gethostname(), "ts": time.time(),
           "perturbation": rec.design.perturbation, "condition": rec.design.condition,
           "timeline": rec.design.timeline, "seed": seed, "generations": len(rec.generations),
           "qc": overall.value, "generation_qc": json.dumps([s.value for s in per]),
           "reportable": qc.is_reportable(rec), "note": rec.note,
           "simout_path": str(run_root)}  # LOCAL path for read_species; full simOut stays on this machine
    row.update(rec.channels)  # flatten summary channels into columns for DuckDB
    return row


def append_shard(rows: list[dict]) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    shard = MANIFEST_DIR / f"{getpass.getuser()}-{int(time.time())}-{uuid.uuid4().hex[:6]}.parquet"
    pq.write_table(pa.Table.from_pylist(rows), shard)
    return shard


def campaign(designs: list[Design], seeds: list[int], generations: int = 1) -> Path:
    """Run an in-envelope design x seed matrix on the public model and append a manifest shard.

    Sequential, but crash-isolated: a failed sim is logged and skipped (never kills the batch), and the
    shard is written for whatever completed — so a long unattended run always leaves a usable corpus.
    """
    jobs = [(d, s) for d in designs for s in seeds]
    rows: list[dict] = []
    for i, (design, seed) in enumerate(jobs, 1):
        label = f"{design.perturbation}/{design.condition or design.timeline or 'basal'} seed{seed}"
        print(f"[{i}/{len(jobs)}] {label} ...", flush=True)
        try:
            run_root = runner.run_one(design, seed, generations)
            rows.append(_flat_row(build_record(run_root, design, seed), seed, run_root))
            print(f"[{i}/{len(jobs)}] {label} -> qc={rows[-1]['qc']}", flush=True)
        except Exception as exc:  # one bad sim must not lose the whole batch
            print(f"[{i}/{len(jobs)}] {label} FAILED: {exc}", flush=True)
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
    """Index runs ALREADY on disk into a manifest shard — no re-simulation (one container read each)."""
    rows: list[dict] = []
    for run_root in _discover_runs(sim_path):
        design, seed = _design_from_dir(run_root)
        rec = build_record(run_root, design, seed)
        rows.append(_flat_row(rec, seed, run_root))
    return append_shard(rows)


if __name__ == "__main__":  # `python -m cellarium.manifest` -> index existing runs without re-simulating
    shard = record_existing()
    print(f"Indexed existing runs -> {shard}")
