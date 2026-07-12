#!/usr/bin/env python
"""Stand-in for wcEcoli runscripts/manual/runParca.py — writes a sim_data marker and exits."""
import argparse, socket
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("sim_path")
ap.add_argument("--cpus", type=int, default=1)
a = ap.parse_args()

kb = Path("/wcEcoli/out") / a.sim_path / "kb"
kb.mkdir(parents=True, exist_ok=True)
(kb / "simData.cPickle").write_text(f"standin sim_data host={socket.gethostname()} cpus={a.cpus}\n")
print(f"STANDIN_PARCA done sim_path={a.sim_path} cpus={a.cpus}", flush=True)
