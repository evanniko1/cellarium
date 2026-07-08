"""Generation driver — invoke the PUBLIC Covert wcEcoli model to produce simOut.

Fresh, thin orchestration. ParCa, variant generation, and the multi-generation runner are all the public
model's own scripts (`runscripts/manual/{runParca,runSim}.py`); Cellarium just calls them over an
in-envelope design space and records a manifest shard. Nothing here is copied from the private platform.

Requires a wcEcoli model checkout (public) + its Python env, pointed at by WCECOLI_DIR (or run in its Docker
image). See docs/GENERATE.md.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from . import envelope
from .model import Design

WCECOLI_DIR = os.environ.get("WCECOLI_DIR", "")          # your separately-obtained, Stanford-licensed checkout
WCECOLI_DOCKER = os.environ.get("WCECOLI_DOCKER", "")    # optional LOCAL model image (built from that checkout; never published)
PY = os.environ.get("WCECOLI_PY", "python")               # native interpreter when not using Docker
OUT_ROOT = Path(os.environ.get("CELLARIUM_OUT", "runs")).resolve()


def _variant_type(design: Design) -> str:
    # timeline designs execute on the wildtype variant with a --timeline env override
    return "wildtype" if design.timeline else design.perturbation


def _variant_index(design: Design) -> int:
    """Directory-discriminating variant index. Uses a semantic index when given (e.g. a KO gene index);
    otherwise a stable content hash so two *different* designs never share an output dir (the collision bug
    that let a downshift run overwrite the wildtype simOut), while re-running the *same* design is idempotent.
    The wildtype variant ignores its index (see variants/wildtype.py), so this is purely a dir discriminator.
    """
    if "variant_index" in design.params:
        return int(design.params["variant_index"])
    key = f"{design.perturbation}|{design.condition}|{design.timeline}".encode()
    return int(hashlib.sha1(key).hexdigest(), 16) % 900000 + 100000  # 6-digit, never collides with idx 0


def _variant_args(design: Design) -> list[str]:
    """Map a Design to runSim --variant args (+ a --timeline override for timeline designs)."""
    idx = str(_variant_index(design))
    args = ["--variant", _variant_type(design), idx, idx]
    if design.timeline:
        args += ["--timeline", design.timeline]
    return args


def _write_provenance(run_root: Path, design: Design) -> None:
    """Persist the true Design next to its simOut so reads recover it regardless of the opaque variant dir."""
    if run_root.exists():
        (run_root / "design.json").write_text(design.model_dump_json(indent=2), encoding="utf-8")


def _out_root(sim_path: str) -> Path:
    """Where the model's out/<sim_path> lands on the host (a mounted dir in Docker; the checkout natively)."""
    return (OUT_ROOT if WCECOLI_DOCKER else Path(WCECOLI_DIR) / "out") / sim_path


def _exec(script_args: list[str]) -> None:
    """Run a model script (e.g. ['runscripts/manual/runSim.py', ...]).

    Docker mode (WCECOLI_DOCKER set) uses the LOCAL model image — the model + compiled Cython are baked in
    at /wcEcoli. Mount ONLY the host output dir to /wcEcoli/out; do NOT mount the checkout over /wcEcoli
    (that shadows the compiled model). The image is built from your checkout and never published, so nothing
    is redistributed. Native mode runs in WCECOLI_DIR with your interpreter. Pattern mirrors the model's
    standard invocation (bind output, PYTHONPATH=/wcEcoli, -w /wcEcoli).
    """
    if WCECOLI_DOCKER:
        OUT_ROOT.mkdir(parents=True, exist_ok=True)
        cmd = ["docker", "run", "--rm", "-v", f"{OUT_ROOT}:/wcEcoli/out",
               "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli", WCECOLI_DOCKER, "python", *script_args]
        subprocess.run(cmd, check=True)
        return
    if not WCECOLI_DIR:
        raise RuntimeError("Set WCECOLI_DOCKER (local model image) or WCECOLI_DIR (native checkout). "
                           "See docs/GENERATE.md.")
    subprocess.run([PY, *script_args], cwd=WCECOLI_DIR, check=True)


def ensure_parca(sim_path: str = "cellarium") -> None:
    """Run ParCa once; sim_data is cached under out/<sim_path>/kb (persisted to the host output dir)."""
    _exec(["runscripts/manual/runParca.py", sim_path])


def _run_subpath(design: Design, seed: int, sim_path: str) -> Path:
    """The specific <variant>_<idx>/<seed> dir the model writes for this lineage (per-generation dirs beneath)."""
    return _out_root(sim_path) / f"{_variant_type(design)}_{_variant_index(design):06d}" / f"{seed:06d}"


def run_one(design: Design, seed: int, generations: int, sim_path: str = "cellarium") -> Path:
    """Run one (design, seed) lineage. Returns THIS lineage's run root (per-generation dirs beneath it)."""
    v = envelope.check(design)
    if not v.in_envelope:
        raise ValueError(f"Refusing out-of-envelope design: {v.reason}")
    _exec(["runscripts/manual/runSim.py", sim_path, "--seed", str(seed),
           "--generations", str(generations), *_variant_args(design)])
    run_root = _run_subpath(design, seed, sim_path)
    _write_provenance(run_root, design)
    return run_root


if __name__ == "__main__":  # `python -m cellarium.runner` -> run ParCa once (cached)
    ensure_parca()
    print(f"ParCa complete (sim_data cached under {_out_root('cellarium')}/kb).")
