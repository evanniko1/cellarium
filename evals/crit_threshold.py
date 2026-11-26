"""CRIT (2026-11-26): the evidence that the replication threshold jumps at a medium shift, from its sources.

Two parts, written to evals/results/crit_threshold.json:

  well4cell  Median division time by birth medium, fitted condition and kind of shift, from the well4cell rc2 index.
             That index is not in the repository, so this part is recomputed only on a machine that holds it, and the
             stored part is kept otherwise.
  trace      The replication listener through a shift, from short DIAGNOSTIC runs that are not corpus runs: wild type,
             seed 0, oxygen removed at 600 s, 1,500 s. One steady-state on the corpus fit, one kinetic on the kinetic
             port's fit. Recorded at every step from 6 s before the shift to 6 s after, and at every change in the number
             of origins.

    python evals/crit_threshold.py run   <out_dir>   # the two runs, through docker (WCECOLI_DOCKER names the image)
    python evals/crit_threshold.py score <out_dir>   # reads both, writes the result
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "evals" / "results" / "crit_threshold.json"
INDEX = REPO / "data" / "corpora" / "well4cell" / "index.parquet"
SHIFT_AT = 600
LENGTH_S = 1500
TIMELINE = f"0 minimal, {SHIFT_AT} minimal_minus_oxygen"
ARMS = {   # name: (knowledge base dir relative to the repo, extra runSim flags)
    "steady_state": ("runs/cellarium/kb", []),
    "kinetic": ("runs_kinetic_seeds/cellarium/kb", ["--kinetic-trna-charging"]),
}
SIMOUT = "wildtype_000000/000000/generation_000000/000000/simOut"


def _image() -> str:
    img = os.environ.get("WCECOLI_DOCKER")
    if not img:
        raise SystemExit("WCECOLI_DOCKER is not set to the model image; nothing can be run or read.")
    return img


def run(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, (kb, flags) in ARMS.items():
        (out_dir / name).mkdir(exist_ok=True)
        cmd = ["docker", "run", "--rm", "-v", f"{out_dir}:/wcEcoli/out", "-v", f"{REPO / kb}:/wcEcoli/out/{name}/kb:ro",
               "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli", _image(), "python", "runscripts/manual/runSim.py", name,
               "--seed", "0", "--generations", "1", "--variant", "wildtype", "0", "0", "--timeline", TIMELINE,
               "--length-sec", str(LENGTH_S), *flags]
        print(name, "...", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (out_dir / f"{name}.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        # a crashed wcEcoli sim exits 0 (runner._FAILURE_MARKERS), so read the log, not the exit code
        if "Traceback (most recent call last)" in r.stdout + r.stderr:
            print(f"{name}: the simulation raised; see {out_dir / (name + '.log')}", file=sys.stderr)
            return 1
    return 0


def _worker(sim_out: str, shift: float) -> None:
    """Runs INSIDE the model image: the trace as JSON on stdout."""
    import numpy as np
    from wholecell.io.tablereader import TableReader
    t = TableReader(os.path.join(sim_out, "Main")).readColumn("time")
    rep = TableReader(os.path.join(sim_out, "ReplicationData"))
    crit = rep.readColumn("criticalInitiationMass")
    ratio = rep.readColumn("criticalMassPerOriC")
    noric = rep.readColumn("numberOfOric")
    mass = TableReader(os.path.join(sim_out, "Mass")).readColumn("cellMass")
    rows = sorted(set(np.where((t >= shift - 6) & (t <= shift + 6))[0].tolist())
                  | set((np.where(np.diff(noric) != 0)[0] + 1).tolist()) | {len(t) - 1})
    pre = (t > 0) & (t < shift)
    print(json.dumps({
        "steps": int(len(t)), "t_end_s": float(t[-1]),
        "rows": [{"t_s": float(t[i]), "threshold_fg": round(float(crit[i]), 1), "mass_per_oric_over_threshold":
                  round(float(ratio[i]), 3), "n_oric": int(noric[i]), "cell_mass_fg": round(float(mass[i]), 1)}
                 for i in rows],
        "max_ratio_before_shift": round(float(ratio[pre].max()), 3),
        "thresholds_seen_fg": sorted({round(float(x), 1) for x in crit[t > 0]}),
        "initiations": [float(t[i]) for i in (np.where(np.diff(noric) > 0)[0] + 1).tolist()],
    }))


def _trace(out_dir: Path, name: str) -> dict:
    sim_out = f"/wcEcoli/out/{name}/{SIMOUT}"
    cmd = ["docker", "run", "--rm", "-v", f"{out_dir}:/wcEcoli/out:ro", "-v", f"{Path(__file__).resolve()}:/x/crit.py:ro",
           "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli", _image(), "python", "/x/crit.py", "worker", sim_out,
           str(SHIFT_AT)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.startswith("{")), None)
    if line is None:
        raise RuntimeError(f"no trace for {name}: {(r.stderr or r.stdout)[-600:]}")
    return json.loads(line)


def _well4cell() -> dict | None:
    if not INDEX.exists():
        return None
    import duckdb
    con = duckdb.connect()
    release = json.loads((INDEX.parent / "manifest.json").read_text(encoding="utf-8")).get("version")
    q = f"""select medium_at_birth, medium_fitted_for, coalesce(unfitted_shift, 'none') shift, count(*) cells,
                   median(division_time_sec) median_division_s,
                   100.0 * avg(case when division_time_sec < 600 then 1 else 0 end) pct_all_cells_within_10_min
            from read_parquet('{INDEX.as_posix()}')
            where medium_at_birth in ('minimal', 'minimal_acetate', 'minimal_minus_oxygen', 'minimal_succinate')
              and medium_fitted_for in ('minimal', 'minimal_acetate', 'minimal_minus_oxygen', 'minimal_succinate')
            group by 1, 2, 3 having count(*) >= 30 order by 1, 2, 3"""
    cols = ["medium_at_birth", "fitted_for", "shift", "cells", "median_division_s", "pct_all_cells_within_10_min"]
    rows = [dict(zip(cols, r)) for r in con.execute(q).fetchall()]
    for r in rows:
        r["median_division_s"] = round(r["median_division_s"], 1) if r["median_division_s"] is not None else None
        r["pct_all_cells_within_10_min"] = round(r["pct_all_cells_within_10_min"], 1)
    return {"release": release, "rows": rows,
            "note": "median over cells that divided; the percentage over all cells in the group"}


def score(out_dir: Path) -> int:
    from cellarium import provenance
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    w4c = _well4cell()
    out = {
        "spec": "CRIT, 2026-11-26: the replication threshold jumps at a medium shift",
        "timeline": TIMELINE, "length_s": LENGTH_S,
        "trace": {name: {"knowledge_base": kb, "flags": flags, **_trace(out_dir, name)}
                  for name, (kb, flags) in ARMS.items()},
        "well4cell": w4c if w4c is not None else old.get("well4cell"),
        "well4cell_recomputed": w4c is not None,
        "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": provenance.code_environment(),
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for name, tr in out["trace"].items():
        print(name, "thresholds", tr["thresholds_seen_fg"], "initiations at", tr["initiations"],
              "max ratio before the shift", tr["max_ratio_before_shift"])
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[1] == "worker":
        _worker(sys.argv[2], float(sys.argv[3]))
        sys.exit(0)
    sys.path.insert(0, str(REPO / "src"))
    if len(sys.argv) != 3 or sys.argv[1] not in ("run", "score"):
        print(__doc__)
        sys.exit(2)
    sys.exit(run(Path(sys.argv[2]).resolve()) if sys.argv[1] == "run" else score(Path(sys.argv[2]).resolve()))
