"""Build shardable Parquet manifest records from simOut, via the public reader + the QC guardrail.

Each contributor writes their own shard (data/manifest/<contributor>-<stamp>.parquet); the corpus is the
union of shards (concatenation), queried with DuckDB. Full simOut stays local; the manifest carries
provenance + QC + summary channels (+ a curated species panel, once decided — see docs/DECISIONS.md D2).
"""

from __future__ import annotations

import getpass
import json
import socket
import time
import uuid
from pathlib import Path

import numpy as np

from . import qc, runner, simout
from .model import Design, GenerationResult, SimResult

MANIFEST_DIR = Path("data/manifest")
CURATED_PANEL: list[tuple[str, str]] = []  # (kind, species_id) — deferred (DECISIONS.md D2)


def _generation(simout_dir: Path, index: int) -> GenerationResult:
    t = simout.read_time(simout_dir)
    n = int(t.size)
    try:
        fc = simout.full_chromosome_end(simout_dir)
    except Exception:
        fc = -1
    try:
        fo = simout.read_column(simout_dir, "FBAResults", "objectiveValue").ravel()
        fba_ok = bool(np.isfinite(fo[-1]) and fo[-1] > 0)
    except Exception:
        fba_ok = True
    divided = fc == 2 and n > qc.DEGENERATE_MAX_STEPS
    return GenerationResult(index=index, full_chromosome_end=fc, divided=divided,
                            division_time_sec=float(t[-1]) if divided else None,
                            n_steps=n, fba_ok=fba_ok, is_dead=False)


def _summary(simout_dir: Path) -> dict[str, float]:
    ch: dict[str, float] = {}
    for name in simout.SUMMARY_CHANNELS:
        try:
            ch[name] = float(np.nanmean(simout.read_channel(simout_dir, name)))
        except Exception:
            continue
    for kind, sid in CURATED_PANEL:
        try:
            ch[f"{kind}:{sid}"] = simout.read_species(simout_dir, kind, sid)["mean"]
        except Exception:
            continue
    return ch


def build_record(run_root: Path, design: Design, seed: int) -> SimResult:
    gens_dirs = simout.find_generations(run_root)
    gens = [_generation(d, i) for i, d in enumerate(gens_dirs)]
    channels = _summary(gens_dirs[0]) if gens_dirs else {}
    label = f"{design.perturbation}·{design.condition or design.timeline or 'basal'}·s{seed}"
    return SimResult(id=f"{design.perturbation}_{seed}_{uuid.uuid4().hex[:8]}", label=label,
                     design=design, channels=channels, generations=gens)


def _flat_row(rec: SimResult, seed: int, run_root: Path) -> dict:
    overall, per = qc.check_result(rec)
    row = {"id": rec.id, "label": rec.label,
           "contributor": getpass.getuser(), "host": socket.gethostname(), "ts": time.time(),
           "perturbation": rec.design.perturbation, "condition": rec.design.condition,
           "timeline": rec.design.timeline, "seed": seed, "generations": len(rec.generations),
           "qc": overall.value, "generation_qc": json.dumps([s.value for s in per]),
           "reportable": qc.is_reportable(rec),
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
