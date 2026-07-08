"""Generation driver — invoke the PUBLIC Covert wcEcoli model to produce simOut.

Fresh, thin orchestration. ParCa, variant generation, and the multi-generation runner are all the public
model's own scripts (`runscripts/manual/{runParca,runSim}.py`); Cellarium just calls them over an
in-envelope design space and records a manifest shard. Nothing here is copied from the private platform.

Requires a wcEcoli model checkout (public) + its Python env, pointed at by WCECOLI_DIR (or run in its Docker
image). See docs/GENERATE.md.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import envelope
from .model import Design

WCECOLI_DIR = os.environ.get("WCECOLI_DIR", "")          # path to the public wcEcoli model checkout
PY = os.environ.get("WCECOLI_PY", "python")               # interpreter inside the model env / container
OUT_ROOT = Path(os.environ.get("CELLARIUM_OUT", "runs")).resolve()


def _variant_args(design: Design) -> list[str]:
    """Map a Design to runSim --variant args. Timeline runs execute as wildtype with an env timeline."""
    if design.timeline:
        return ["--variant", "wildtype", "0", "0", "--timeline", design.timeline]
    idx = str(int(design.params.get("variant_index", 0)))
    return ["--variant", design.perturbation, idx, idx]


def _run(cmd: list[str]) -> None:
    if not WCECOLI_DIR:
        raise RuntimeError("Set WCECOLI_DIR to a public wcEcoli model checkout (see docs/GENERATE.md).")
    subprocess.run(cmd, cwd=WCECOLI_DIR, check=True)


def ensure_parca(sim_path: str = "cellarium") -> None:
    """Run ParCa once to build sim_data (cached by the model under out/<sim_path>/)."""
    _run([PY, "runscripts/manual/runParca.py", sim_path])


def run_one(design: Design, seed: int, generations: int, sim_path: str = "cellarium") -> Path:
    """Run one (design, seed) lineage. Returns the run's simOut root (per-generation dirs beneath it)."""
    v = envelope.check(design)
    if not v.in_envelope:
        raise ValueError(f"Refusing out-of-envelope design: {v.reason}")
    _run([PY, "runscripts/manual/runSim.py", sim_path, "--seed", str(seed),
          "--generations", str(generations), *_variant_args(design)])
    # The model writes under WCECOLI_DIR/out/<sim_path>/... ; the manifest step locates the simOut dirs.
    return Path(WCECOLI_DIR) / "out" / sim_path
