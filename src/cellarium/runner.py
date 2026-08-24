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
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import envelope, redact
from .capability import DEFAULT_MODE, ELONGATION_MODES, MODE_FLAGS
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
    key = f"{design.perturbation}|{design.condition}|{design.timeline}|{design.params.get('ko_indices')}"
    # The elongation model joins the hash ONLY when it is not the default, so every historical design hashes
    # to exactly the directory it already occupies. Two runs of one design under different elongation models
    # are DIFFERENT EXPERIMENTS that the model would otherwise write to one transit dir — and wcEcoli rmtree's
    # its output dir before every run (wholecell/sim/simulation.py:173-175), so the second run does not
    # mislabel the first, it DELETES it. That is the SCI-TRNA-4 leu-arm race that destroyed generation 0 of
    # four seeds, reproduced exactly on a new axis.
    if design.elongation_model != DEFAULT_MODE:
        key += f"|elong:{design.elongation_model}"
    return int(hashlib.sha1(key.encode()).hexdigest(), 16) % 900000 + 100000  # 6-digit, never collides with idx 0


def _elongation_args(design: Design) -> list[str]:
    """The runSim option(s) selecting the elongation model — EMPTY for the default.

    Emitting nothing for "steady_state" is what preserves byte-identical command lines, and therefore
    byte-identical behaviour, for every design that existed before this axis. These are SIM options like
    `--timeline`, not env vars, so they belong on the command line and never in the per-run exec env.

    Exactly one flag is ever emitted. The two are mutually exclusive alternatives rather than modifiers — with
    both passed, argparse accepts them and `polypeptide_elongation.py` silently picks kinetic while
    `runSim.py` writes BOTH into metadata — which is why the mapping is a string lookup and not a pair of
    bools that can disagree."""
    mode = design.elongation_model
    if mode not in ELONGATION_MODES:   # Design validates this; belt-and-braces for a model_construct bypass
        raise ValueError(f"unknown elongation_model {mode!r} — declared: {list(ELONGATION_MODES)}")
    flag = MODE_FLAGS[mode]
    return [] if not flag.startswith("--") else [flag]


def _variant_args(design: Design) -> list[str]:
    """Map a Design to runSim --variant args (+ --timeline / elongation-model overrides)."""
    if design.perturbation == "multi_gene_knockout":  # index-0 variant + the gene set via --multi-ko-indices
        idxs = [str(i) for i in design.params.get("ko_indices", [])]
        return ["--variant", "multi_gene_knockout", "0", "0", "--multi-ko-indices", *idxs,
                *_elongation_args(design)]
    idx = str(_variant_index(design))
    args = ["--variant", _variant_type(design), idx, idx]
    if design.timeline:
        args += ["--timeline", design.timeline]
    return args + _elongation_args(design)


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


# `design.json` records what was ASKED. `executed.json` records what RAN, and the two are not the same claim.
_EXECUTED_FILE = "executed.json"

# Fields lifted verbatim from the model's own metadata.json. Copied rather than interpreted: `elongation_model`
# there is a CLASS NAME the model itself wrote ("SteadyStateElongationModel"), so a translation model added
# upstream tomorrow appears here without a line changing — which is exactly what an enum of our own would fail
# to do. The flags beside it are how that class was configured.
_EXECUTED_FROM_METADATA = (
    "elongation_model", "kinetic_trna_charging", "coarse_kinetic_elongation", "explicit_trna_charging",
    "trna_charging", "trna_attenuation", "ppgpp_regulation", "mechanistic_aa_transport",
    "variable_elongation_translation", "variable_elongation_transcription",
    "git_hash", "git_branch", "python", "variant", "seed", "timeline", "generations",
)


def _capture_executed(run_root: Path, sim_path: str, expect_seed=None, expect_variant=None) -> dict:
    """Write `executed.json` beside the run: which image, which model class, which model commit.

    WHY THIS IS CAPTURED AT LAUNCH AND CANNOT BE RECOVERED LATER. wcEcoli writes ONE `metadata.json` per
    sim_path and OVERWRITES it on every run. Measured 2026-08-24: after five seeds into one sim_path the file
    records `seed: 1` — whichever finished last. So the executed configuration is readable for exactly as long
    as it takes the next run to start, and for the 363 rows already in the corpus it is simply gone. That is
    the whole reason those rows cannot be back-filled and have to be re-run.

    WHAT THIS FIXES, concretely. On 2026-08-24 `WCECOLI_DOCKER` was found pointing at `wcecoli-sim:latest`, a
    tag made on 2026-05-10 and never re-pointed, which matched Cellarium's overlay on 3 of 45 files and was
    missing two variants that 24 corpus rows use. Every simulation launched from that machine ran a
    3.5-month-old model, and NOTHING COULD HAVE REPORTED IT, because no row recorded an image. `provenance.py`
    already said the gap out loud — "kb_sha256 pins the PARAMETERS. Nothing pinned the CODE."

    Never raises: the simulation finishing is the valuable part, and a provenance write that kills a completed
    run would be a worse bug than the one it documents. A partial record says which fields it could not read
    rather than omitting them silently.
    """
    rec: dict = {"captured_at": time.time(), "sim_path": sim_path, "missing": []}
    try:
        from . import provenance
        rec["image_tag"] = WCECOLI_DOCKER or None
        rec["image_digest"] = provenance.image_digest()
        m = provenance.model_provenance()
        rec["model_sha256"] = m.get("model_sha256")
        rec["model_upstream_commit"] = m.get("model_upstream_commit")
    except Exception as exc:
        rec["missing"].append(f"image/model provenance: {type(exc).__name__}")
    # THE OWNERSHIP CHECK, and it is the whole reason this is not a straight read.
    #
    # The model-dir lock held by `run_one` is keyed on `<out>/<variant>_<index>/<seed>` — PER SEED — while
    # metadata.json is per SIM_PATH. `manifest.campaign(parallel=N)` submits every (design, seed) into one
    # sim_path, so N runs sit in N DIFFERENT critical sections and whichever finishes last owns the file.
    # Serialising here cannot fix that: the competing writer is the model's own process, mid-run, not this
    # code. So VERIFY instead — metadata.json carries `seed` and `variant`, and when they do not match the run
    # being recorded, the file belongs to somebody else and the executed block is dropped with a reason.
    #
    # A partial record is the correct outcome, not a degraded one. The image and model-source fields above
    # come from THIS process and are always right; only the model class and its flags come from the shared
    # file. So a parallel campaign always gets the image, and gets the model class only where it can be proven
    # to belong to that run — which is exactly the trade this project makes everywhere else: never fabricate.
    try:
        # `_out_root(sim_path)` already ends in the sim_path, so this is `<out>/<sim_path>/metadata/…`.
        meta = _out_root(sim_path) / "metadata" / "metadata.json"
        if not meta.is_file():
            meta = Path("runs") / sim_path / "metadata" / "metadata.json"
        if meta.is_file():
            doc = json.loads(meta.read_text(encoding="utf-8"))
            mism = [f"{k}={doc.get(k)!r} but this run is {v!r}"
                    for k, v in (("seed", expect_seed), ("variant", expect_variant))
                    if v is not None and k in doc and str(doc.get(k)) != str(v)]
            if mism:
                rec["missing"].append(
                    "metadata.json describes a DIFFERENT run (" + "; ".join(mism) + ") — it is per-sim_path "
                    "and a concurrent run overwrote it, so the executed block is omitted rather than "
                    "attributed to this row")
                rec["metadata_owner"] = {"seed": doc.get("seed"), "variant": doc.get("variant")}
            else:
                rec["executed"] = {k: doc.get(k) for k in _EXECUTED_FROM_METADATA if k in doc}
                absent = [k for k in _EXECUTED_FROM_METADATA if k not in doc]
                if absent:
                    rec["missing"].append("metadata.json lacks: " + ",".join(absent))
        else:
            rec["missing"].append(f"no metadata.json at {meta}")
    except Exception as exc:
        rec["missing"].append(f"metadata.json: {type(exc).__name__}")
    try:
        if run_root.exists():
            (run_root / _EXECUTED_FILE).write_text(json.dumps(rec, indent=2), encoding="utf-8")
    except Exception:
        pass
    return rec


def read_executed(run_root) -> dict:
    """The `executed.json` beside a run, or `{}` when the run predates this record.

    An empty dict is the honest answer for the 363 rows written before 2026-08-24 and must never be filled in
    with today's values — that would assert a July run used today's image, which is the exact fabrication the
    `_run_prov` guard already refuses to make.
    """
    try:
        p = Path(run_root) / _EXECUTED_FILE
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception:
        return {}


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
# Cellarium's OWN variants (model_patches/variants/, installed into the checkout by
# scripts/apply_model_variants.py) plus the variant registry that names them. These must be MOUNTED into the
# container as well as installed on the host: the image bakes in its own copy of models/, so installing to the
# checkout alone leaves the container running stock code. Measured — the first graded dose run died instantly
# with `graded_gene_knockout is not a valid variant function!` because the applier and the runner were not
# connected. Same read-only single-file discipline as the flat overlays; never mount the directory, which would
# shadow the compiled Cython.
_VARIANT_OVERLAYS = ["models/ecoli/sim/variants/graded_gene_knockout.py",
                     "models/ecoli/sim/variants/__init__.py"]

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
    for rel in (*_FLAT_OVERLAYS, *_VARIANT_OVERLAYS):
        host = Path(src) / rel
        if host.is_file():
            out += ["-v", f"{host.as_posix()}:/wcEcoli/{rel}:ro"]
    return out


# Per-invocation env for the model process, set by run_one around _exec. Not a parameter because _exec is
# called from several places and only one of them needs it — but THREAD-LOCAL, not a module global.
#
# `manifest.campaign(parallel>1)` runs jobs in a ThreadPoolExecutor (manifest.py), so a module global here is
# shared mutable state across concurrent runs. Two `graded_gene_knockout` designs for DIFFERENT genes could
# interleave — A sets GRADED_KO_CISTRON, B overwrites it, A's container then suppresses B's gene — producing a
# complete, plausible run labelled with the wrong knockout. That is the worst failure shape this project has:
# it looks exactly like data. Thread-local storage makes each worker's env private, so the interleaving is
# harmless. (Found 2026-08-03; never triggered, because every graded run so far targeted one gene.)
_EXEC_LOCAL = threading.local()


def _get_exec_env() -> dict | None:
    return getattr(_EXEC_LOCAL, "env", None)


def _set_exec_env(env: dict | None) -> None:
    _EXEC_LOCAL.env = env


def last_argv() -> str | None:
    """The model command line this thread last executed, as a string, or None (ARM-2).

    None on any row built by `record_existing` or a re-index, because those never launched anything — the flags
    are genuinely unknown there and must read as unknown, not as "no flags".
    """
    a = getattr(_EXEC_LOCAL, "argv", None)
    return " ".join(a) if a else None


def _exec(script_args: list[str]) -> None:
    """Run a model script (e.g. ['runscripts/manual/runSim.py', ...]).

    Docker mode (WCECOLI_DOCKER set) uses the LOCAL model image — the model + compiled Cython are baked in
    at /wcEcoli. Mount ONLY the host output dir to /wcEcoli/out; do NOT mount the checkout over /wcEcoli
    (that shadows the compiled model). The image is built from your checkout and never published, so nothing
    is redistributed. Native mode runs in WCECOLI_DIR with your interpreter. Pattern mirrors the model's
    standard invocation (bind output, PYTHONPATH=/wcEcoli, -w /wcEcoli).
    """
    # ARM-2: record the flags this row actually ran with. The elongation model was already stored; nothing else
    # was, so a flag added later would split an arm invisibly — two rows would look identical in every recorded
    # column and be different experiments. Thread-local for the same reason `_EXEC_LOCAL` is: `campaign` runs
    # jobs in a ThreadPoolExecutor, and a module global here would attribute one worker's flags to another's row.
    _EXEC_LOCAL.argv = list(script_args)
    if WCECOLI_DOCKER:
        OUT_ROOT.mkdir(parents=True, exist_ok=True)
        extra_env: list[str] = []
        for k, v in (_get_exec_env() or {}).items():
            extra_env += ["-e", f"{k}={v}"]
        cmd = ["docker", "run", "--rm", "-v", f"{OUT_ROOT}:/wcEcoli/out",
               *_flat_file_mounts(), *(getattr(_EXEC_LOCAL, "mounts", None) or []), *extra_env,
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


RETYPABLE = ("pseudo", "mRNA", "rRNA", "tRNA", "miscRNA")


def read_flat_file(rel: str) -> str:
    """Read a `reconstruction/ecoli/flat/` file OUT OF THE IMAGE.

    Deliberately not from `model_overlay/files/…`, though a copy lives there. The overlay is what we intend the
    image to contain; the image is what ParCa will actually read, and a rebuild that patches the wrong one
    produces a knowledge base nobody can account for. The two agree today — that is a reason to read the
    authoritative one, not a reason it does not matter.
    """
    if not WCECOLI_DOCKER:
        raise RuntimeError("a knowledge-base rebuild needs the model image (WCECOLI_DOCKER)")
    r = subprocess.run(["docker", "run", "--rm", "--entrypoint", "sh", WCECOLI_DOCKER, "-c",
                        "cat reconstruction/ecoli/flat/%s" % rel],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=redact.child_env())
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("could not read reconstruction/ecoli/flat/%s from %s" % (rel, WCECOLI_DOCKER))
    return r.stdout


def retype_rnas(body: str, retypes: dict) -> tuple[str, list[dict]]:
    """Apply `{rna_id: new_type}` to an `rnas.tsv`, returning the new text and what changed.

    RETYPE, NEVER DELETE. Deleting the row breaks referential integrity — `genes.tsv` still points at the RNA
    and the build dies in `getter_functions.py` with a KeyError before any fitting happens. Retyping to
    'pseudo' is also what the phnE1 change itself did, so the perturbation matches the one being investigated.

    Raises on an id that is not in the file. A rebuild is seven minutes and 114 MB; silently skipping an
    unmatched id would spend both and produce a knowledge base identical to the one already on disk, which the
    caller would then compare against as though it were the perturbation.
    """
    lines = body.splitlines()
    hdr = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith('"id"'))
    cols = [c.strip('"') for c in lines[hdr].split("\t")]
    i_id, i_type = cols.index("id"), cols.index("type")
    want = {str(k): str(v) for k, v in (retypes or {}).items()}
    bad = [t for t in want.values() if t not in RETYPABLE]
    if bad:
        raise ValueError("unknown RNA type(s) %s — expected one of %s" % (sorted(set(bad)), list(RETYPABLE)))
    changed: list[dict] = []
    for n in range(hdr + 1, len(lines)):
        parts = lines[n].split("\t")
        if len(parts) <= max(i_id, i_type):
            continue
        rid = parts[i_id].strip('"')
        if rid in want:
            changed.append({"id": rid, "from": parts[i_type].strip('"'), "to": want[rid]})
            parts[i_type] = '"%s"' % want[rid]
            lines[n] = "\t".join(parts)
    missing = sorted(set(want) - {c["id"] for c in changed})
    if missing:
        raise ValueError("no row in rnas.tsv for %s — a rebuild that silently skipped them would produce a "
                         "knowledge base identical to the current one and be compared as if perturbed" % missing)
    return "\n".join(lines) + "\n", changed


def parca_rebuild(sim_path: str, retype_cistrons: dict | None = None, operons: str = "on",
                  cpus: int | None = None) -> dict:
    """Build a knowledge base at `sim_path`, optionally with `reconstruction/ecoli/flat/` edits applied.

    This is the executable half of PARCA-3: a rebuild that Cellwright can PROPOSE and a human approves, rather
    than 25 shell invocations by hand. The gate on WHERE it may build lives in `launch.vet_rebuild` — a rebuild
    at a path live rows depend on is the one failure this must never repeat, and it is enforced before the
    approval is offered, not here.

    Edits are applied by mounting a patched copy over the image's file for the life of the container. Nothing
    on the host checkout is touched, so a failed rebuild leaves no partially-edited reconstruction behind.
    """
    import tempfile
    patch_dir = None
    changed: list[dict] = []
    mounts: list[str] = []
    if retype_cistrons:
        body, changed = retype_rnas(read_flat_file("rnas.tsv"), retype_cistrons)
        patch_dir = Path(tempfile.mkdtemp(prefix="cellarium_parca_"))
        (patch_dir / "rnas.tsv").write_text(body, encoding="utf-8", newline="\n")
        mounts = ["-v", "%s:/wcEcoli/reconstruction/ecoli/flat/rnas.tsv:ro"
                  % (patch_dir / "rnas.tsv").as_posix()]
    n = cpus or os.cpu_count() or 1
    prev = getattr(_EXEC_LOCAL, "mounts", None)
    _EXEC_LOCAL.mounts = mounts
    try:
        _exec(["runscripts/manual/runParca.py", sim_path, "--cpus", str(n), "--operons", operons])
    finally:
        _EXEC_LOCAL.mounts = prev
        if patch_dir:
            shutil.rmtree(patch_dir, ignore_errors=True)
    from . import provenance
    prov = provenance.kb_provenance(sim_path)
    return {"sim_path": sim_path, "operons": operons, "retyped": changed,
            "kb_sha256": prov.get("kb_sha256"), "kb_content_sha256": prov.get("kb_content_sha256"),
            "parca_ts": prov.get("parca_ts"), "kb_bytes": prov.get("kb_bytes")}


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


def _dir_discriminator(design: Design) -> str:
    """The suffix that separates designs the MODEL would otherwise write to one directory — '' when none is
    needed.

    Two independent clauses, and each records a way data was destroyed rather than mislabelled.

    A `variant_index` is the gene index the model needs, so two designs that knock out the same gene get the
    same directory — even when a timeline makes them different experiments. That is exactly the SCI-TRNA-4
    leu arm: `KO:leuB` un-starved and `KO:leuB` starved both resolved to `gene_knockout_001818/<seed>`, ran
    concurrently at parallel=6, and destroyed each other. `_variant_index`'s content hash exists to prevent
    this but is short-circuited whenever an explicit index is supplied.

    The elongation model is the same shape of collision and needed its own clause: a plain KO design carries
    an explicit index and NO timeline, so it bypassed both the hash and the timeline test — a kinetic and a
    steady-state knockout of one gene landed in one directory with nothing anywhere forcing them apart, and
    wcEcoli rmtree's its output dir before every run.

    Both clauses are silent for a default-elongation design with no timeline, which is what keeps every
    pre-existing run path byte-identical."""
    suffix = ""
    if design.timeline and "variant_index" in design.params:
        suffix += "__tl" + hashlib.sha1(design.timeline.encode()).hexdigest()[:6]
    if design.elongation_model != DEFAULT_MODE:
        suffix += "__el" + design.elongation_model
    return suffix


def _needs_distinct_dir(design: Design) -> bool:
    """True when this design shares the model's output directory with a DIFFERENT design. Defined in terms of
    `_dir_discriminator` rather than restating its rules, so the predicate and the path cannot drift apart."""
    return bool(_dir_discriminator(design))


def _run_subpath(design: Design, seed: int, sim_path: str) -> Path:
    """The CANONICAL run root for this lineage — unique per design, which the model's own dir is not.

    Every path this produced before the elongation axis existed is byte-identical today, and that is not
    cosmetic: `_evacuate`, `_crash_row` and `reconcile_disk` all RECOMPUTE this path for runs already on
    disk, so a changed spelling would strand ~300 of them."""
    base = _model_output_dir(design, seed, sim_path)
    suffix = _dir_discriminator(design)
    if not suffix:
        return base
    return base.parent.parent / f"{base.parent.name}{suffix}" / base.name


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
        _set_exec_env(_graded_ko_env(design))   # raises if a graded design cannot be fully specified
        try:
            _exec(["runscripts/manual/runSim.py", sim_path, "--seed", str(seed),
                   "--generations", str(generations), *_variant_args(design)])
        finally:
            _set_exec_env(None)
        # IMMEDIATELY after the run and INSIDE the lock, because the model keeps ONE metadata.json per sim_path
        # and overwrites it on the next run. Outside the lock a concurrent worker's run would already have
        # replaced it, and this would record that run's configuration against this run's output.
        _capture_executed(run_root, sim_path, expect_seed=seed, expect_variant=_variant_type(design))
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
    if design.perturbation == "multi_gene_knockout":
        # the index-0 variant writes to multi_gene_knockout_000000/<seed>; move its generations into the hashed
        # run_root so distinct gene sets don't overwrite each other. Run multi-gene batches with --parallel 1.
        src = _out_root(sim_path) / "multi_gene_knockout_000000" / f"{seed:06d}"
        if src.exists():
            for child in list(src.iterdir()):
                dest = run_root / child.name
                if not dest.exists():
                    shutil.move(str(child), str(dest))
    # Record what this run ACTUALLY cost, so `estimate_sim_resources` stops guessing. Wall-clock per generation
    # and GB per generation were both hard constants; a campaign that never reports its own cost can never
    # correct them. Never allowed to break a completed run — the sim finishing is the valuable part.
    #
    # MUST run AFTER the multi_gene_knockout move above, not before it. `observe_run` sizes `run_root`, and for a
    # multi-gene KO the output is still sitting in the transit dir at that point — so measuring first recorded
    # gb_per_generation = 3.26e-07 for a run that wrote ~0.5 GB, i.e. every multi-gene KO fed the resource
    # estimator a value ~1.5e6x too small. Measured 2026-08-03; the polluted observations were discarded.
    # `_reached` is counted here too, for the same reason: before the move it would count zero simOut dirs and
    # fall back to `generations`, hiding a partial run behind the requested depth.
    try:
        from . import calibration
        _reached = len(glob.glob(os.path.join(str(run_root), "**", "simOut"), recursive=True)) or generations
        calibration.observe_run(str(run_root), generations=_reached, elapsed_sec=time.time() - _t0,
                                arrested=bool(_reached < generations))
    except Exception:
        pass
    return run_root


if __name__ == "__main__":  # `python -m cellarium.runner [--cpus N]` -> run ParCa once (cached)
    import argparse

    ap = argparse.ArgumentParser(description="Run ParCa once (compile reconstruction -> sim_data, cached).")
    ap.add_argument("--cpus", type=int, default=None, help="parallel fitting processes (default: all cores)")
    ensure_parca(cpus=ap.parse_args().cpus)
    print(f"ParCa complete (sim_data cached under {_out_root('cellarium')}/kb).")
