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
    """Run an in-envelope design x seed matrix on the public model and append a manifest shard."""
    rows: list[dict] = []
    for design in designs:
        for seed in seeds:
            run_root = runner.run_one(design, seed, generations)
            rec = build_record(run_root, design, seed)
            rows.append(_flat_row(rec, seed, run_root))
    return append_shard(rows)


def _discover_runs(sim_path: str = "cellarium") -> list[Path]:
    """Existing <variant>/<seed> run roots already on disk (a run root is a simOut's 3rd parent)."""
    base = runner._out_root(sim_path)
    return sorted({so.parents[2] for so in base.glob("**/simOut")}) if base.exists() else []


def _design_from_dir(run_root: Path) -> tuple[Design, int]:
    variant_dir, seed = run_root.parent.name, int(run_root.name)     # e.g. "wildtype_000000", 0
    perturbation, _, idx = variant_dir.rpartition("_")
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
