"""Generation driver — invoke the PUBLIC Covert wcEcoli model to produce simOut.

Fresh, thin orchestration. ParCa, variant generation, and the multi-generation runner are all the public
model's own scripts (`runscripts/manual/{runParca,runSim}.py`); Cellarium just calls them over an
in-envelope design space and records a manifest shard. Nothing here is copied from the private platform.

Requires a wcEcoli model checkout (public) + its Python env, pointed at by WCECOLI_DIR (or run in its Docker
image). See docs/GENERATE.md.
"""

from __future__ import annotations

import glob
import hashlib
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import envelope, redact
from .model import Design

WCECOLI_DIR = os.environ.get("WCECOLI_DIR", "")          # your separately-obtained, Stanford-licensed checkout
WCECOLI_DOCKER = os.environ.get("WCECOLI_DOCKER", "")    # optional LOCAL model image (built from that checkout; never published)
PY = os.environ.get("WCECOLI_PY", "python")               # native interpreter when not using Docker
OUT_ROOT = Path(os.environ.get("CELLARIUM_OUT", "runs")).resolve()


def _variant_type(design: Design) -> str:
    """The model variant to run. A PURE media-shift design has no genotype of its own, so it executes on the
    wildtype variant with a `--timeline` override.

    But a design can carry BOTH a genotype and a timeline — the SCI-TRNA-4 auxotroph arms are a biosynthesis
    knockout starved of the amino acid it can no longer make. This used to return "wildtype" whenever
    `design.timeline` was set, which SILENTLY DISCARDED the knockout: `KO:leuB` + a leucine dropout emitted
    `--variant wildtype 1818 1818`, and the wildtype variant ignores its index entirely. The media shift would
    have worked, the provenance would have said `KO:leuB`, and the run would have been a plain wild type
    wearing a knockout's label — indistinguishable from a real result and exactly the WELL-NOOP-1 pattern
    (murA/rpoB) already open in the backlog.

    `--timeline` is a SIM option (wholecell/utils/scriptBase.py:489), orthogonal to `--variant`, so a genotype
    variant and a media timeline compose without either being dropped."""
    pure_shift = design.perturbation in ("wildtype", "timeline")
    return "wildtype" if (design.timeline and pure_shift) else design.perturbation


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


def _graded_ko_env(design: Design) -> dict:
    """Env for a `graded_gene_knockout` design: the target cistron and its transcription-unit count.

    Resolved from the DESIGN via `scope.graded_ko_target`, never from the ambient environment. The variant
    needs the cistron because its index names a TRANSCRIPTION UNIT and a multi-gene operon has no single
    implied gene; with the cistron absent it falls back to suppressing ONE unit, which for a multi-TU gene is
    not a knockout at all. That fallback would produce a run that LOOKS graded and is not, so this raises
    rather than letting the design run under-specified."""
    if _variant_type(design) != "graded_gene_knockout":
        return {}
    from . import scope
    symbol = str(design.condition or "").split(":")[-1].strip()
    if not symbol:
        raise ValueError(f"graded_gene_knockout design has no resolvable gene symbol in condition "
                         f"{design.condition!r} — expected the 'KO:<gene>' form.")
    t = scope.graded_ko_target(symbol)
    if not t.get("ok"):
        raise ValueError(t["why"])
    return t["env"]


# Designs that share a variant index share the model's OUTPUT directory, and the model writes there before we
# can move anything. Renaming after the run is therefore not enough on its own: two such designs running
# concurrently race on the transit dir. That is not hypothetical — it destroyed generation 0 of all four
# starved leu seeds (0-byte `Main/time`), the generation holding the shift, while generations 1-3 survived.
# A per-directory lock serialises them; `_evacuate` clears foreign data out of the transit dir first.
_MODEL_DIR_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _model_dir_lock(model_dir: Path) -> threading.Lock:
    key = str(model_dir).lower()
    with _LOCKS_GUARD:
        return _MODEL_DIR_LOCKS.setdefault(key, threading.Lock())


def _evacuate(model_dir: Path, run_root: Path, sim_path: str) -> dict | None:
    """If the transit dir already holds ANOTHER design's output, move it to its own canonical dir first.

    Reads the stranded run's `design.json` to work out where it belongs, so historical data written before
    this scheme existed is rescued rather than overwritten. Refuses to guess: output with no provenance is
    left in place and reported, because silently deleting someone's simOut is worse than a failed run."""
    if model_dir == run_root or not model_dir.exists():
        return None
    prov = model_dir / "design.json"
    if not prov.is_file():
        return {"evacuated": False, "why": f"{model_dir} holds output with no design.json — refusing to move "
                                           f"or overwrite data whose identity cannot be established"}
    try:
        other = Design.model_validate_json(prov.read_text(encoding="utf-8"))
    except Exception as e:
        return {"evacuated": False, "why": f"unreadable provenance in {model_dir}: {type(e).__name__}: {e}"}
    seed = int(model_dir.name)
    dest = _run_subpath(other, seed, sim_path)
    if dest == model_dir:
        return None
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for child in list(model_dir.iterdir()):
        target = dest / child.name
        if not target.exists():
            shutil.move(str(child), str(target))
            moved.append(child.name)
    try:
        model_dir.rmdir()
    except OSError:
        pass
    return {"evacuated": True, "from": str(model_dir), "to": str(dest), "moved": moved}


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
_FLAT_OVERLAYS = ["reconstruction/ecoli/flat/condition/media_recipes.tsv",
                  # Not optional, and not obvious: the media alone let the sim START but it dies on ENTERING
                  # one, because nutrient_to_doubling_time is keyed by media yet built from the conditions
                  # table. Mounting one without the other is the worst of both worlds — it fails 1200 s in.
                  "reconstruction/ecoli/flat/condition/condition_defs.tsv"]


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


# Per-invocation env for the model process, set by run_one around _exec. A module global rather than a
# parameter because _exec is called from several places and only one of them needs it.
_EXEC_ENV: dict | None = None


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
        extra_env: list[str] = []
        for k, v in (_EXEC_ENV or {}).items():
            extra_env += ["-e", f"{k}={v}"]
        cmd = ["docker", "run", "--rm", "-v", f"{OUT_ROOT}:/wcEcoli/out",
               *_flat_file_mounts(), *extra_env,
               "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli", WCECOLI_DOCKER, "python", *script_args]
        _run_checked(cmd, None)   # the docker CLI has no use for a credential
        return
    if not WCECOLI_DIR:
        raise RuntimeError("Set WCECOLI_DOCKER (local model image) or WCECOLI_DIR (native checkout). "
                           "See docs/GENERATE.md.")
    _run_checked([PY, *script_args], WCECOLI_DIR)


# A crashed wcEcoli sim EXITS ZERO. FireWorks catches the process exception, marks the task FIZZLED, and the
# wrapper script returns 0, so `check=True` is blind to it. Measured: a timeline naming a medium absent from
# `nutrient_to_doubling_time` raised KeyError inside chromosome_replication, and `run_one` returned a run root
# and reported success — with a simOut on disk that simply stopped at the shift. A truncated-but-present run is
# the worst failure mode this project has: it looks like data.
_FAILURE_MARKERS = ("Traceback (most recent call last)", "FIZZLED", "KeyError", "raise ",
                    "ValueError:", "RuntimeError:", "AssertionError")


def _run_checked(cmd: list[str], cwd: str | None) -> None:
    """Run a model script, streaming its output, and FAIL on a traceback even when the exit code says 0."""
    proc = subprocess.Popen(cmd, cwd=cwd or None, env=redact.child_env(),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")                      # keep the model's own progress visible
        tail.append(line)
        if len(tail) > 400:
            del tail[:200]
    rc = proc.wait()
    blob = "".join(tail)
    hit = next((m for m in _FAILURE_MARKERS if m in blob), None)
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd, output=blob)
    if hit:
        raise RuntimeError(
            f"The model script exited 0 but its output contains {hit!r} — the run FAILED and any simOut it "
            f"left behind is truncated, not data. wcEcoli's FireWorks wrapper swallows the exception and "
            f"returns 0, so the exit code cannot be trusted here.\n--- last output ---\n{blob[-2000:]}")


def ensure_parca(sim_path: str = "cellarium", cpus: int | None = None) -> None:
    """Run ParCa once; sim_data is cached under out/<sim_path>/kb (persisted to the host output dir).

    ParCa's dominant stages (per-TF and per-condition fitting) are multiprocessing-parallel but default to
    serial (--cpus 1). Pass cpus (default: all host cores) to parallelize — the main lever when re-fitting,
    e.g. retargeting to a new strain. The container clamps to its available CPUs, so over-requesting is safe.
    """
    n = cpus or os.cpu_count() or 1
    _exec(["runscripts/manual/runParca.py", sim_path, "--cpus", str(n)])


def _model_output_dir(design: Design, seed: int, sim_path: str) -> Path:
    """Where the MODEL writes: it derives the directory from the variant type + index, so we cannot rename it."""
    return _out_root(sim_path) / f"{_variant_type(design)}_{_variant_index(design):06d}" / f"{seed:06d}"


def _needs_distinct_dir(design: Design) -> bool:
    """True when this design shares the model's output directory with a DIFFERENT design.

    A `variant_index` is the gene index the model needs, so two designs that knock out the same gene get the
    same directory — even when a timeline makes them different experiments. That is exactly the SCI-TRNA-4
    leu arm: `KO:leuB` un-starved and `KO:leuB` starved both resolved to `gene_knockout_001818/<seed>`, ran
    concurrently at parallel=6, and destroyed each other. `_variant_index`'s content hash exists to prevent
    this but is short-circuited whenever an explicit index is supplied."""
    return bool(design.timeline) and "variant_index" in design.params


def _run_subpath(design: Design, seed: int, sim_path: str) -> Path:
    """The CANONICAL run root for this lineage — unique per design, which the model's own dir is not."""
    base = _model_output_dir(design, seed, sim_path)
    if not _needs_distinct_dir(design):
        return base
    tag = hashlib.sha1((design.timeline or "").encode()).hexdigest()[:6]
    return base.parent.parent / f"{base.parent.name}__tl{tag}" / base.name


def run_one(design: Design, seed: int, generations: int, sim_path: str = "cellarium") -> Path:
    """Run one (design, seed) lineage. Returns THIS lineage's run root (per-generation dirs beneath it)."""
    v = envelope.check(design)
    if not v.in_envelope:
        raise ValueError(f"Refusing out-of-envelope design: {v.reason}")
    run_root = _run_subpath(design, seed, sim_path)
    run_root.mkdir(parents=True, exist_ok=True)  # write provenance BEFORE the sim so a CRASH still leaves labels (G3)
    _write_provenance(run_root, design)
    model_dir = _model_output_dir(design, seed, sim_path)
    _t0 = time.time()
    # Hold the transit dir for the whole run+move. The model always writes to <variant>_<idx>/<seed>, so two
    # designs sharing a variant index race there no matter what we rename afterwards. That race destroyed
    # generation 0 of all four starved leu seeds — 0-byte `Main/time`, the generation containing the shift —
    # while generations 1-3 survived, which is the worst shape: a run that still looks complete on disk.
    with _model_dir_lock(model_dir):
        evac = _evacuate(model_dir, run_root, sim_path)      # rescue any other design's data sitting there
        if evac and not evac.get("evacuated"):
            raise RuntimeError(
                f"Refusing to run: {evac['why']}. Running would overwrite it. Move or delete it deliberately.")
        global _EXEC_ENV
        _EXEC_ENV = _graded_ko_env(design)      # raises if a graded design cannot be fully specified
        try:
            _exec(["runscripts/manual/runSim.py", sim_path, "--seed", str(seed),
                   "--generations", str(generations), *_variant_args(design)])
        finally:
            _EXEC_ENV = None
        # Move the model's output into the CANONICAL dir, mirroring what multi_gene_knockout already does.
        if model_dir != run_root and model_dir.exists():
            for child in list(model_dir.iterdir()):
                dest = run_root / child.name
                if not dest.exists():
                    shutil.move(str(child), str(dest))
            try:
                model_dir.rmdir()                  # only when empty — never remove another design's output
            except OSError:
                pass
    # Record what this run ACTUALLY cost, so `estimate_sim_resources` stops guessing. Wall-clock per generation
    # and GB per generation were both hard constants; a campaign that never reports its own cost can never
    # correct them. Never allowed to break a completed run — the sim finishing is the valuable part.
    try:
        from . import calibration
        _reached = len(glob.glob(os.path.join(str(run_root), "**", "simOut"), recursive=True)) or generations
        calibration.observe_run(str(run_root), generations=_reached, elapsed_sec=time.time() - _t0,
                                arrested=bool(_reached < generations))
    except Exception:
        pass
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
