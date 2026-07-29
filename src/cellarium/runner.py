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
import shutil
import subprocess
from pathlib import Path

from . import envelope, redact
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
    # multi-gene KO: the variant is index-0-only, so hash the gene SET for a unique output dir (run_one moves the
    # sim's _000000 output into it). Single-gene KO / conditions use their semantic index.
    if "variant_index" in design.params and design.perturbation != "multi_gene_knockout":
        return int(design.params["variant_index"])
    key = f"{design.perturbation}|{design.condition}|{design.timeline}|{design.params.get('ko_indices')}".encode()
    return int(hashlib.sha1(key).hexdigest(), 16) % 900000 + 100000  # 6-digit, never collides with idx 0


def _variant_args(design: Design) -> list[str]:
    """Map a Design to runSim --variant args (+ a --timeline override for timeline designs)."""
    if design.perturbation == "multi_gene_knockout":  # index-0 variant + the gene set via --multi-ko-indices
        idxs = [str(i) for i in design.params.get("ko_indices", [])]
        return ["--variant", "multi_gene_knockout", "0", "0", "--multi-ko-indices", *idxs]
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
    """Where the model's out/<sim_path> lands on the host (a mounted dir in Docker; the checkout natively).

    An EXPLICIT `CELLARIUM_OUT` wins in both modes. Without that, output location was coupled to whether Docker
    was in use, so any host-side tool that reads runs without needing a container — `manifest.reconcile_disk`,
    a native-reader analysis — silently scanned `$WCECOLI_DIR/out` and found NOTHING, reporting "0 runs on disk"
    for a corpus of 154. A silent zero is the worst failure shape for a reconciliation, so the explicit setting
    is honoured regardless of transport."""
    if os.environ.get("CELLARIUM_OUT"):
        return OUT_ROOT / sim_path
    return (OUT_ROOT if WCECOLI_DOCKER else Path(WCECOLI_DIR) / "out") / sim_path


# Flat-file overlays: model DATA files Cellarium adds that the baked image predates. Read-only, one file at a
# time, and never a directory — the image bakes in the compiled Cython, so mounting the checkout over /wcEcoli
# shadows the built extensions and the model stops importing. A single .tsv is inert data and carries none of
# that risk. Currently just the SCI-TRNA-3 dropout media (see scripts/apply_model_patches.py).
_FLAT_OVERLAYS = ["reconstruction/ecoli/flat/condition/media_recipes.tsv"]


def _flat_file_mounts() -> list[str]:
    """`-v host:container:ro` args for each overlay that EXISTS on the host checkout and actually differs from
    what the image ships. Silent when there is no checkout, so Docker-only users are unaffected.

    Mounting is a stopgap, deliberately chosen over rebuilding the image: the rebuild is the correct long-term
    fix and belongs in the image, but it is expensive and this keeps the model's own file as the single source
    of truth in the meantime. A mounted file changes what ParCa FITS, so anything it produces carries a
    different kb_sha256 than the corpus — that is recorded, not hidden."""
    src = os.environ.get("WCECOLI_DIR") or WCECOLI_DIR
    if not src:
        return []
    out: list[str] = []
    for rel in _FLAT_OVERLAYS:
        host = Path(src) / rel
        if host.is_file():
            out += ["-v", f"{host.as_posix()}:/wcEcoli/{rel}:ro"]
    return out


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
               *_flat_file_mounts(),
               "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli", WCECOLI_DOCKER, "python", *script_args]
        subprocess.run(cmd, check=True, env=redact.child_env())   # the docker CLI has no use for a credential
        return
    if not WCECOLI_DIR:
        raise RuntimeError("Set WCECOLI_DOCKER (local model image) or WCECOLI_DIR (native checkout). "
                           "See docs/GENERATE.md.")
    subprocess.run([PY, *script_args], cwd=WCECOLI_DIR, check=True, env=redact.child_env())


def ensure_parca(sim_path: str = "cellarium", cpus: int | None = None) -> None:
    """Run ParCa once; sim_data is cached under out/<sim_path>/kb (persisted to the host output dir).

    ParCa's dominant stages (per-TF and per-condition fitting) are multiprocessing-parallel but default to
    serial (--cpus 1). Pass cpus (default: all host cores) to parallelize — the main lever when re-fitting,
    e.g. retargeting to a new strain. The container clamps to its available CPUs, so over-requesting is safe.
    """
    n = cpus or os.cpu_count() or 1
    _exec(["runscripts/manual/runParca.py", sim_path, "--cpus", str(n)])


def _run_subpath(design: Design, seed: int, sim_path: str) -> Path:
    """The specific <variant>_<idx>/<seed> dir the model writes for this lineage (per-generation dirs beneath)."""
    return _out_root(sim_path) / f"{_variant_type(design)}_{_variant_index(design):06d}" / f"{seed:06d}"


def run_one(design: Design, seed: int, generations: int, sim_path: str = "cellarium") -> Path:
    """Run one (design, seed) lineage. Returns THIS lineage's run root (per-generation dirs beneath it)."""
    v = envelope.check(design)
    if not v.in_envelope:
        raise ValueError(f"Refusing out-of-envelope design: {v.reason}")
    run_root = _run_subpath(design, seed, sim_path)
    run_root.mkdir(parents=True, exist_ok=True)  # write provenance BEFORE the sim so a CRASH still leaves labels (G3)
    _write_provenance(run_root, design)
    _exec(["runscripts/manual/runSim.py", sim_path, "--seed", str(seed),
           "--generations", str(generations), *_variant_args(design)])
    if design.perturbation == "multi_gene_knockout":
        # the index-0 variant writes to multi_gene_knockout_000000/<seed>; move its generations into the hashed
        # run_root so distinct gene sets don't overwrite each other. Run multi-gene batches with --parallel 1.
        src = _out_root(sim_path) / "multi_gene_knockout_000000" / f"{seed:06d}"
        if src.exists():
            for child in list(src.iterdir()):
                dest = run_root / child.name
                if not dest.exists():
                    shutil.move(str(child), str(dest))
    return run_root


if __name__ == "__main__":  # `python -m cellarium.runner [--cpus N]` -> run ParCa once (cached)
    import argparse

    ap = argparse.ArgumentParser(description="Run ParCa once (compile reconstruction -> sim_data, cached).")
    ap.add_argument("--cpus", type=int, default=None, help="parallel fitting processes (default: all cores)")
    ensure_parca(cpus=ap.parse_args().cpus)
    print(f"ParCa complete (sim_data cached under {_out_root('cellarium')}/kb).")
