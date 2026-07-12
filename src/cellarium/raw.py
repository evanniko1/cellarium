"""Host-side raw simOut reader — reach into the FULL-RESOLUTION wcEcoli output on local disk, no Docker.

The distilled manifest/shard carries only a coarse k=16 downsample per design (one representative seed). But the
raw simOut for a design's seeds is often already on local disk (see the upload ledger / data_availability). This
module reads those wcEcoli `TableReader` columns directly with a small, self-contained COLM/BLOC parser (numpy
only — it deliberately does NOT import `wholecell`, so it works in Cellarium's host venv without the model image).
That lets the agent DRILL DOWN: full-resolution per-seed trajectories, and a true CROSS-SEED VARIANCE band that the
coarse shard cannot express.

Format (wcEcoli tablewriter v3, big-endian IFF chunks, no alignment): a `COLM` header chunk (bytes_per_entry,
elements_per_entry, entries_per_block, compression as `>2I2H`, then the numpy dtype descr as JSON) followed by one
or more `BLOC` data chunks (zlib-compressed when compression==1). Mirrors wholecell/io/tablereader.py::readColumn.
"""

from __future__ import annotations

import glob
import json
import math
import os
import struct
import zlib
from pathlib import Path

import numpy as np

from . import stats, store

# channel -> (listener table, column). Mirrors _reader_worker.SUMMARY_CHANNELS (which can't be imported here — it
# pulls `wholecell`). Keep in sync with that dict.
CHANNELS = {
    "growth_rate": ("Mass", "instantaneous_growth_rate"),
    "cell_mass": ("Mass", "cellMass"),
    "dry_mass": ("Mass", "dryMass"),
    "protein_mass": ("Mass", "proteinMass"),
    "rna_mass": ("Mass", "rnaMass"),
    "ppgpp_conc": ("GrowthLimits", "ppgpp_conc"),
    "fba_objective": ("FBAResults", "objectiveValue"),
    "ribosome_conc": ("GrowthLimits", "ribosome_conc"),
    "fraction_trna_charged": ("GrowthLimits", "fraction_trna_charged"),
    "rela_conc": ("GrowthLimits", "rela_conc"),
}


# ---------------- the COLM/BLOC column reader ----------------
def read_column(path: str) -> np.ndarray:
    """Read one wcEcoli fixed-length table column file into a squeezed numpy array. Raises on a missing/variable
    (VCOL) column — those aren't summary channels."""
    with open(path, "rb") as f:
        name = f.read(4)
        (size,) = struct.unpack(">I", f.read(4))
        if name != b"COLM":
            raise ValueError(f"{os.path.basename(path)}: not a fixed-length COLM column ({name!r})")
        bytes_per_entry, elements_per_entry, entries_per_block, comp = struct.unpack(">2I2H", f.read(12))
        descr = json.loads(f.read(size - 12))
        dtype = np.dtype(descr if isinstance(descr, str) else [(str(n), str(t)) for n, t in descr])
        blocks = []
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            cname, csize = struct.unpack(">4sI", hdr)
            data = f.read(csize)
            if cname == b"BLOC":
                if comp == 1:
                    data = zlib.decompress(data)
                blocks.append(np.frombuffer(data, dtype).reshape(-1, elements_per_entry))
            # ROW_SIZE (RWSZ) etc. are only for variable-length columns; summary channels never hit them
    arr = np.concatenate(blocks, axis=0) if blocks else np.zeros((0, elements_per_entry), dtype)
    return arr.squeeze()


def _col_1d(simout: str, table: str, column: str) -> np.ndarray:
    """One scalar per timestep. Some listener columns are 2-D (per-species, e.g. fraction_trna_charged is
    per-tRNA) — collapse the non-time axes to a per-timestep mean, matching _reader_worker._chan_1d."""
    a = read_column(os.path.join(simout, table, column))
    if a.ndim > 1:
        a = np.nanmean(a.reshape(a.shape[0], -1), axis=1)
    return np.asarray(a, dtype=float).ravel()


# ---------------- disk discovery ----------------
def simout_dirs(seed_root: str) -> list[str]:
    """The simOut dirs under one seed's run root, sorted (one per generation in a lineage)."""
    return sorted(p for p in glob.glob(os.path.join(seed_root, "**", "simOut"), recursive=True) if os.path.isdir(p))


def _seed_root(result_id: str) -> str | None:
    p = store.simout_path(result_id)
    return p if (p and Path(p).exists()) else None


def seed_runs(design_or_id: str) -> list[dict]:
    """Every seed of the design that has raw simOut ON LOCAL DISK: {result_id, seed, qc, root, n_gens}. Accepts a
    design label ('condition/no_oxygen') or a single result_id."""
    rows = store.list_results()
    by_id = {r.get("id"): r for r in rows}
    if design_or_id in by_id:
        sel = [by_id[design_or_id]]
    else:
        pert, _, cond = str(design_or_id).partition("/")
        sel = [r for r in rows if r.get("perturbation") == pert
               and ((r.get("condition") or "") == cond or (cond and cond in (r.get("condition") or "")))]
    out = []
    for r in sorted(sel, key=lambda r: (r.get("seed") if r.get("seed") is not None else 99)):
        root = _seed_root(r["id"])
        if root:
            out.append({"result_id": r["id"], "seed": r.get("seed"), "qc": r.get("qc"),
                        "root": root, "n_gens": len(simout_dirs(root))})
    return out


# ---------------- full-resolution per-seed channel ----------------
def seed_channel(seed_root: str, channel: str) -> tuple[np.ndarray, np.ndarray]:
    """Full-resolution (time_since_birth_sec, value) for one seed, concatenating its generations in order onto a
    continuous time axis (each generation offset by the cumulative lineage duration, so it works whether the raw
    per-generation clock resets or continues). Drops the leading nan wcEcoli writes at t=0."""
    if channel not in CHANNELS:
        raise KeyError(channel)
    table, column = CHANNELS[channel]
    ts, vs, offset = [], [], 0.0
    for so in simout_dirs(seed_root):
        t = _col_1d(so, "Main", "time")
        v = _col_1d(so, table, column)
        n = min(t.size, v.size)
        if n == 0:
            continue
        t, v = t[:n], v[:n]
        t = t - t[0] + offset
        ts.append(t); vs.append(v)
        offset = t[-1] + (t[-1] - t[-2] if t.size > 1 else 1.0)   # continue the axis for the next generation
    if not ts:
        return np.array([]), np.array([])
    t_all = np.concatenate(ts); v_all = np.concatenate(vs)
    ok = np.isfinite(v_all)   # the t=0 growth_rate is nan
    return t_all[ok], v_all[ok]


# ---------------- the cross-seed variance band ----------------
def cross_seed_band(design_or_id: str, channel: str, n_points: int = 40) -> dict:
    """The thing the coarse shard can't give: a true CROSS-SEED variance band for `channel` over time-since-birth,
    computed from the raw simOut of every local seed. Each seed's full-resolution trajectory is resampled onto a
    common grid (linear interp within its own time range), then per grid point we take mean, std, sem and CI95
    ACROSS seeds. Grid points are kept only where >=2 seeds have coverage. Returns grounded numbers only."""
    if channel not in CHANNELS:
        return {"error": f"channel '{channel}' has no raw mapping; try {sorted(CHANNELS)}."}
    runs = seed_runs(design_or_id)
    if not runs:
        return {"error": f"no local raw simOut for '{design_or_id}' (check data_availability / the upload ledger)."}
    seeds = []
    for r in runs:
        t, v = seed_channel(r["root"], channel)
        if t.size >= 2:
            seeds.append({"seed": r["seed"], "result_id": r["result_id"], "t": t, "v": v})
    if len(seeds) < 2:
        n = len(seeds)
        return {"error": f"need >=2 readable seeds for a variance band; only {n} local seed(s) had this channel.",
                "n_seeds_readable": n}
    tmax = min(s["t"][-1] for s in seeds)   # common window = shortest lineage (all seeds cover it)
    tmin = max(s["t"][0] for s in seeds)
    if not (tmax > tmin):
        return {"error": "seed time windows do not overlap enough for a common grid."}
    grid = np.linspace(tmin, tmax, max(4, min(int(n_points), 200)))
    stacked = np.vstack([np.interp(grid, s["t"], s["v"]) for s in seeds])   # (n_seeds, n_grid)
    mean = stacked.mean(axis=0)
    std = stacked.std(axis=0, ddof=1)
    n = stacked.shape[0]
    sem = std / math.sqrt(n)
    ci95 = stats.t_critical_95(n - 1) * sem   # t-distribution, not 1.96 — right for n=4-8 seeds (see stats.py)

    def f(x):
        x = float(x)
        return round(x, 6) if math.isfinite(x) else None

    series = [{"t": round(float(grid[i]), 1), "mean": f(mean[i]), "std": f(std[i]),
               "ci95": f(ci95[i]), "lo": f(mean[i] - ci95[i]), "hi": f(mean[i] + ci95[i]),
               "lo_std": f(mean[i] - std[i]), "hi_std": f(mean[i] + std[i])} for i in range(grid.size)]
    return {"channel": channel, "design": design_or_id, "n_seeds": int(n),
            "seeds": [{"seed": s["seed"], "result_id": s["result_id"], "n_points": int(s["t"].size)} for s in seeds],
            "t_window_sec": [round(float(tmin), 1), round(float(tmax), 1)],
            "grounded_from": "raw simOut (local, full-resolution)", "series": series}


def available(design_or_id: str) -> dict:
    """What full-resolution raw data is reachable RIGHT NOW on local disk for a design: which seeds, how many
    generations each, and which channels are readable. The drill-down entry point (distinct from data_availability,
    which is about the HF download path)."""
    runs = seed_runs(design_or_id)
    if not runs:
        return {"design": design_or_id, "n_seeds_local": 0,
                "note": "no raw simOut on local disk for this design — see data_availability for the HF/regenerate path."}
    probe = runs[0]["root"]
    sos = simout_dirs(probe)
    readable = []
    if sos:
        for ch, (table, column) in CHANNELS.items():
            if os.path.exists(os.path.join(sos[0], table, column)):
                readable.append(ch)
    return {"design": design_or_id, "n_seeds_local": len(runs),
            "seeds": [{"seed": r["seed"], "qc": r["qc"], "n_gens": r["n_gens"]} for r in runs],
            "channels_readable": readable,
            "grounded_from": "raw simOut (local, full-resolution)",
            "note": "read_raw_series gives one seed's full-resolution trajectory; variance_band gives the "
                    "cross-seed mean±CI95 band over time (what the coarse shard cannot express)."}
