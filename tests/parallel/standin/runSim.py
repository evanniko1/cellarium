#!/usr/bin/env python
"""Stand-in for wcEcoli runscripts/manual/runSim.py.

Honors cellarium's exact invocation contract:
    python runscripts/manual/runSim.py <sim_path> --seed S --generations G --variant TYPE IDX IDX [--timeline STR]

It does NOT simulate biology. It (a) proves it is its own isolated container by printing its hostname,
(b) sleeps to create an overlap window so concurrency is observable, and (c) writes a simOut-shaped
output dir at exactly the path cellarium's runner expects, so the "distinct dir per sim" claim is real.
"""
import argparse
import os
import socket
import sys
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("sim_path")
ap.add_argument("--seed", type=int, required=True)
ap.add_argument("--generations", type=int, default=1)
ap.add_argument("--variant", nargs=3)  # TYPE IDX IDX
ap.add_argument("--timeline", default=None)
a = ap.parse_args()

vtype, vidx = a.variant[0], int(a.variant[1])
host = socket.gethostname()  # container id -> proves container isolation
t0 = time.time()
print(f"STANDIN_SIM start host={host} sim_path={a.sim_path} variant={vtype}_{vidx:06d} "
      f"seed={a.seed:06d} gens={a.generations} t={t0:.3f}", flush=True)

# Crash-isolation hook: seed 4242 always fails (env can't be forwarded through cellarium's runner,
# which only passes -e PYTHONPATH), simulating a degenerate/crashing sim.
if a.seed == 4242 or os.environ.get("STANDIN_FAIL_SEED") == str(a.seed):
    print(f"STANDIN_SIM intentional-failure host={host} seed={a.seed:06d}", flush=True)
    sys.exit(7)

time.sleep(float(os.environ.get("STANDIN_SLEEP", "5")))  # overlap window

# Write simOut at the model's layout: out/<sim_path>/<variant>_<idx6>/<seed6>/generation_000000/000000/simOut
run_root = Path("/wcEcoli/out") / a.sim_path / f"{vtype}_{vidx:06d}" / f"{a.seed:06d}"
simout = run_root / "generation_000000" / "000000" / "simOut"
simout.mkdir(parents=True, exist_ok=True)
(simout / "Main").write_text(f"standin host={host} seed={a.seed} t0={t0}\n")
t1 = time.time()
print(f"STANDIN_SIM done host={host} seed={a.seed:06d} dir={run_root} t={t1:.3f} dur={t1-t0:.2f}s", flush=True)
