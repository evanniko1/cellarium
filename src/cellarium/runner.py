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

WCECOLI_DIR = os.environ.get("WCECOLI_DIR", "")          # your separately-obtained, Stanford-licensed checkout
WCECOLI_DOCKER = os.environ.get("WCECOLI_DOCKER", "")    # optional LOCAL model image (built from that checkout; never published)
PY = os.environ.get("WCECOLI_PY", "python")               # native interpreter when not using Docker
OUT_ROOT = Path(os.environ.get("CELLARIUM_OUT", "runs")).resolve()


def _variant_args(design: Design) -> list[str]:
    """Map a Design to runSim --variant args. Timeline runs execute as wildtype with an env timeline."""
    if design.timeline:
        return ["--variant", "wildtype", "0", "0", "--timeline", design.timeline]
    idx = str(int(design.params.get("variant_index", 0)))
    return ["--variant", design.perturbation, idx, idx]


def _exec(script_args: list[str]) -> None:
    """Run a model script (e.g. ['runscripts/manual/runSim.py', ...]).

    Native mode runs it in-place in WCECOLI_DIR. Docker mode bind-mounts the (licensed) checkout into a
    LOCAL image and runs there — the model is never baked into or shipped inside any image, so nothing is
    redistributed. `out/` is written back to the host through the same bind mount.
    """
    if not WCECOLI_DIR:
        raise RuntimeError("Set WCECOLI_DIR to your separately-obtained, Stanford-licensed wcEcoli checkout "
                           "(see docs/GENERATE.md).")
    if WCECOLI_DOCKER:
        cmd = ["docker", "run", "--rm", "-v", f"{WCECOLI_DIR}:/wcEcoli", "-w", "/wcEcoli",
               WCECOLI_DOCKER, "python", *script_args]
        subprocess.run(cmd, check=True)
    else:
        subprocess.run([PY, *script_args], cwd=WCECOLI_DIR, check=True)


def ensure_parca(sim_path: str = "cellarium") -> None:
    """Run ParCa once to build sim_data (cached by the model under out/<sim_path>/)."""
    _exec(["runscripts/manual/runParca.py", sim_path])


def run_one(design: Design, seed: int, generations: int, sim_path: str = "cellarium") -> Path:
    """Run one (design, seed) lineage. Returns the run's simOut root (per-generation dirs beneath it)."""
    v = envelope.check(design)
    if not v.in_envelope:
        raise ValueError(f"Refusing out-of-envelope design: {v.reason}")
    _exec(["runscripts/manual/runSim.py", sim_path, "--seed", str(seed),
           "--generations", str(generations), *_variant_args(design)])
    # The model writes under WCECOLI_DIR/out/<sim_path>/... ; the manifest step locates the simOut dirs.
    return Path(WCECOLI_DIR) / "out" / sim_path


if __name__ == "__main__":  # `python -m cellarium.runner` -> run ParCa once (cached)
    ensure_parca()
    print("ParCa complete (sim_data cached under $WCECOLI_DIR/out/cellarium/).")
