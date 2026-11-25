"""Provenance guardrail — is a corpus quantity IN-SAMPLE (fitted) or OUT-OF-SAMPLE (predicted), and who fitted it?

ParCa builds a cell specification for EVERY row of the knowledge base's condition table
(fit_sim_data_1.buildCombinedConditionCellSpecifications): composition is fitted to the row's doubling time, and
the expression of every target of the row's active and inactive transcription factors is set from their fitted
fold changes. So the tag depends on the QUANTITY (Y10, 2026-11-25):

  growth and composition    in-sample for every condition in the table (`GROWTH_COMPOSITION`);
  a fitted factor's target  in-sample in that condition (expression of `fitted_targets`);
  anything else             emergent from the fitted state: out-of-sample;
  a perturbation            (knockout, ppGpp clamp, rRNA dosage, shift, ...) out-of-sample.

Each condition's fit carries its basis, from `data/parca/condition_fits.json` (scripts/condition_fits.py): whether
the upstream simulator ships it ("base", e.g. acetate and succinate, CovertLab PR #895) or the campaign added it
("campaign", with the commit and date), and whether its doubling time is the base model's, a placeholder copied from
another condition, or derived from data. A campaign condition is in-sample only from the date the campaign decided
to fit it; a run before that date is out-of-sample.

The earlier rule (six conditions in-sample, the rest "network-derived") rested on a wrong premise: it tagged acetate
out-of-sample though the base model fits it, and read minus_magnesium's unchanged ribosomes as a model boundary
(H2) when the campaign had fitted that condition to basal's 44 minutes with no factor active.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

from . import paths, redact

FITS_PATH = Path(__file__).resolve().parents[2] / "data" / "parca" / "condition_fits.json"
# Quantities the fit sets for every condition: growth and the composition fitted to the doubling time.
GROWTH_COMPOSITION = {None, "growth", "composition", "growth_rate", "division_rate", "doubling_time",
                      "median_division_time_sec", "cell_mass", "dry_mass", "protein_mass", "rna_mass", "dna_mass",
                      "smallmolecule_mass", "ribosome_conc", "rnap_conc"}
EXPRESSION = {"expression", "mrna", "protein"}

_IN_NOTE = ("Fitted: ParCa set this quantity for this condition (composition to its doubling time, or a fitted "
            "factor's fold change). Agreement with data is CONSISTENCY, not prediction.")
_OUT_NOTE = ("Not fitted: a perturbation, or a quantity emergent from the fitted state. A genuine model prediction; "
             "validation and informative failure live here.")


@functools.lru_cache(maxsize=1)
def condition_fits() -> dict:
    """{condition: fit record} from data/parca/condition_fits.json; {} if the record is missing."""
    try:
        return json.loads(FITS_PATH.read_text(encoding="utf-8"))["conditions"]
    except Exception:                                                     # noqa: BLE001
        return {}


def _verdict(perturbation, condition, quantity=None, gene=None, run_date=None) -> tuple[bool, str, dict]:
    if perturbation not in ("wildtype", "condition"):
        return False, "a perturbation the fit did not target", {}
    cond = condition or "basal"
    fit = condition_fits().get(cond)
    if fit is None:
        return False, f"'{cond}' is not a condition the knowledge base fits", {}
    if run_date and fit.get("fitted_by") == "campaign" and fit.get("date") and str(run_date) < fit["date"]:
        return False, (f"run on {run_date}, before the campaign decided to fit '{cond}' ({fit['date']}, "
                       f"{fit.get('commit')})"), fit
    if quantity in GROWTH_COMPOSITION:
        return True, "growth and composition are fitted for every condition", fit
    if quantity in EXPRESSION and gene:
        if gene in set(fit.get("fitted_targets") or []):
            return True, f"{gene} is a target of a factor this condition fits ({', '.join(fit.get('tf_genes') or [])})", fit
        return False, f"{gene} is not a target of a factor this condition fits: its change is emergent", fit
    return False, f"'{quantity}' is emergent from the fitted state", fit


def classify(perturbation: str, condition: str | None = None, quantity: str | None = None,
             gene: str | None = None, run_date: str | None = None) -> dict:
    ok, why, fit = _verdict(perturbation, condition, quantity, gene, run_date)
    out = {"provenance": "in_sample" if ok else "out_of_sample", "why": why, "note": _IN_NOTE if ok else _OUT_NOTE}
    if fit:
        out.update({"fitted_by": fit.get("fitted_by"), "fit_commit": fit.get("commit"), "fit_date": fit.get("date"),
                    "doubling_min": fit.get("doubling_min"), "doubling_basis": fit.get("doubling_basis"),
                    "doubling_source": fit.get("doubling_source"),
                    "n_fitted_targets": len(fit.get("fitted_targets") or [])})
    return out


def tag(perturbation: str, condition: str | None = None, quantity: str | None = None, gene: str | None = None,
        run_date: str | None = None) -> str:
    """Just the label, for annotating list rows. Without a quantity it is the design-level tag (growth/composition)."""
    return "in_sample" if _verdict(perturbation, condition, quantity, gene, run_date)[0] else "out_of_sample"


# --- H-3: per-run environment provenance (the reproducibility bundle) ---------------------------------------

GIT_TIMEOUT_S = 15


def _git_commit_and_why() -> tuple[str | None, str | None]:
    """The repo's current short commit, run in the repo root (not the process CWD) so it's correct regardless of
    where the app was launched, or None and WHY it is missing. The reason never carries git's own output, which can
    name a local path, and the artefacts are public.

    An absence with no reason reads like a run outside a checkout. It happened to the M1+M2 audit (2026-11-24): git
    took longer than the old 3-second limit while the machine was loaded, and the artefact recorded None."""
    import subprocess
    from pathlib import Path
    try:
        root = Path(__file__).resolve().parents[2]
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(root),
                           capture_output=True, text=True, timeout=GIT_TIMEOUT_S, env=redact.child_env())
    except subprocess.TimeoutExpired:
        return None, f"git did not answer within {GIT_TIMEOUT_S} s"
    except Exception as exc:                                   # noqa: BLE001 - recorded, never raised
        return None, f"git could not run ({type(exc).__name__})"
    if r.returncode != 0:
        return None, f"git exited {r.returncode}"
    out = (r.stdout or "").strip()
    return (out, None) if out else (None, "git printed no commit")


def _git_commit() -> str | None:
    """The repo's current short commit, or None (see `_git_commit_and_why` for the reason)."""
    return _git_commit_and_why()[0]


CONTENT_HASH_CACHE = str(paths.cache("kb_content_hash.json"))


MODEL_SHA_CACHE: dict = {}
IMAGE_DIGEST_CACHE: dict = {}
RECON_SHA_CACHE = str(paths.cache("reconstruction_sha.json"))


def model_provenance() -> dict:
    """WHICH SIMULATOR CODE produced a row — `model_sha256`, plus the two things it is made of (ARM-2).

    `kb_sha256` pins the PARAMETERS. Nothing pinned the CODE, so two rows could share a fit and come from
    different model source — the confound the phnE1 investigation had to rule out by hand, by reproducing a run
    bitwise over 2,529 timesteps.

    THE COLUMN IS NOT A GIT SHA, and that is deliberate. This model tree is assembled from two sources: public
    CovertLab wcEcoli at the commit in `model_overlay/MANIFEST.json`, plus the 45 files that overlay ships. A
    bare upstream commit would compare EQUAL across two different overlay states, which is precisely the false
    agreement the arm keys exist to prevent — a column that says "same code" when the code differs is worse
    than no column. So the value is `<upstream_commit>+<digest over the overlay's own file hashes>`, and it
    changes when either half does. The backlog records this under ARM-2's `model_git_sha`; it ships as
    `model_sha256` because naming it a git sha would mislead the next reader into diffing commits.

    Returns all-None when the overlay manifest is unreadable. None means UNKNOWN, never agreement.
    """
    import hashlib
    import json
    from pathlib import Path
    if MODEL_SHA_CACHE:
        return dict(MODEL_SHA_CACHE)
    out = {"model_sha256": None, "model_upstream_commit": None, "model_overlay_files": None}
    try:
        m = json.loads(Path("model_overlay/MANIFEST.json").read_text(encoding="utf-8"))
        up = str(m.get("upstream_commit") or "")
        # Hash the overlay's RECORDED per-file hashes rather than re-reading the files: the manifest is what the
        # image was built from, so this answers "which overlay is baked in", not "what is on my disk right now".
        shipped = sorted((str(f.get("path")), str(f.get("overlay_sha256") or ""))
                         for f in (m.get("files") or []) if f.get("status") == "ship")
        if up and shipped:
            h = hashlib.sha256("\n".join(f"{p}:{s}" for p, s in shipped).encode()).hexdigest()
            out = {"model_sha256": f"{up}+{h[:16]}", "model_upstream_commit": up,
                   "model_overlay_files": len(shipped)}
    except Exception:
        pass
    MODEL_SHA_CACHE.update(out)
    return dict(out)


def image_digest(tag: str | None = None) -> str | None:
    """The container digest ACTUALLY EXECUTED (ARM-2).

    `WCECOLI_DOCKER` is a mutable tag: `wcecoli-sim:kinetic` today and last month need not be the same image,
    and nothing in the corpus recorded which one ran. Uses the image ID (content-addressable, always present
    for a locally-built image) rather than RepoDigests, which is empty for anything never pushed to a registry.
    """
    import os
    import subprocess
    tag = tag or os.environ.get("WCECOLI_DOCKER") or ""
    if not tag:
        return None
    if tag in IMAGE_DIGEST_CACHE:
        return IMAGE_DIGEST_CACHE[tag]
    val = None
    try:
        r = subprocess.run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
                           capture_output=True, text=True, timeout=30, env=redact.child_env())
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out.startswith("sha256:"):
            val = out
    except Exception:
        pass
    if val:                                # only a SUCCESS is cached; a failure must stay retryable
        IMAGE_DIGEST_CACHE[tag] = val
    return val


def reconstruction_sha() -> str | None:
    """A hash over the EFFECTIVE `reconstruction/ecoli/flat/` — the INPUT a knowledge base is built from (ARM-2).

    A KB rebuild is triggered by editing those files, so this is the input whose change EXPLAINS why a new arm
    exists. `kb_content_sha256` says two fits differ; this says which reconstruction inputs they came from.

    "Effective" is the load-bearing word. `runner._flat_file_mounts` bind-mounts host overlays over the image's
    flat files when a checkout is present, so the image's own flat dir is NOT necessarily what ParCa read. This
    computes the hash with the SAME mounts applied, so it describes the state a run would actually see.

    KNOWN LIMIT, stated because the alternative is a column that quietly overclaims: it cannot see a mutation
    applied INSIDE the container after startup. `scripts/refit_sweep.py` does exactly that (`cp /patch/rnas.tsv
    …`) before running ParCa, and those runs would carry the pristine hash. They are throwaway rebuilds and
    never enter the corpus, but the limit is real — `kb_content_sha256` stays the authority on what a fit IS,
    and this column is evidence about its inputs, not a substitute.
    """
    import json
    import subprocess
    from pathlib import Path

    from . import runner
    if not runner.WCECOLI_DOCKER:
        return None
    mounts = runner._flat_file_mounts()
    key = "%s|%s" % (image_digest() or runner.WCECOLI_DOCKER, "|".join(mounts))
    cache = Path(RECON_SHA_CACHE)
    try:
        store = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    except Exception:
        store = {}
    if key in store:
        return store[key] or None
    val = None
    try:
        r = subprocess.run(["docker", "run", "--rm", *mounts, "--entrypoint", "sh", runner.WCECOLI_DOCKER,
                            "-c", "cd /wcEcoli/reconstruction/ecoli/flat && find . -type f -print0 | sort -z "
                                  "| xargs -0 sha256sum | sha256sum | cut -d' ' -f1"],
                           capture_output=True, text=True, timeout=180, env=redact.child_env())
        out = (r.stdout or "").strip().splitlines()
        if r.returncode == 0 and out and len(out[-1].strip()) == 64:
            val = out[-1].strip()
    except Exception:
        pass
    if val:
        try:
            store[key] = val
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(store, indent=1), encoding="utf-8")
        except Exception:
            pass
    return val


def _cached_content_hash(sim_path: str, kb_sha256: str) -> str | None:
    """The sim_data CONTENT hash, computed at most once per knowledge base, ever.

    Computing it means spawning the model image and unpickling ~90 MB, so it must not run on every call:
    `manifest` asks for provenance on the first row of every process, and an unconditional ~30 s container
    spawn there would be a silent tax on every CLI invocation. Keyed by `kb_sha256` because a byte-identical
    pickle always has identical content — the one direction the file hash IS sound in — so the cache can never
    serve a stale answer for a changed kb.

    Returns None when it cannot be computed (no Docker, no model image, no checkout). None means UNKNOWN and
    `same_kb` treats it as undecidable; it is never silently read as agreement."""
    import json
    from pathlib import Path
    cache = Path(CONTENT_HASH_CACHE)
    try:
        store = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    except Exception:
        store = {}
    if kb_sha256 in store:
        return store[kb_sha256] or None
    try:
        from . import reader
        ch = reader.kb_content_hash(sim_path)
        value = ch.get("kb_content_sha256") if isinstance(ch, dict) else None
    except Exception:
        value = None
    if value:                              # only a SUCCESS is cached; a failure must stay retryable
        try:
            store[kb_sha256] = value
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except Exception:
            pass
    return value


def kb_provenance(sim_path: str = "cellarium") -> dict:
    """Which knowledge base a run was produced against, and — critically — whether OPERONS were on.

    This closes a real gap. Every knockout semantic in this project depends on `rna_data` rows being
    transcription units rather than cistrons, and that is true ONLY when the kb was built operons-ON. Nothing
    recorded it: not the manifest, not the run metadata. "Operons ON" was filesystem inference — one
    simData.cPickle on disk, TU ids in the cached variant map — which is not provenance a reviewer can check.

    So this records the EVIDENCE, not an assertion: the kb file's SHA-256 and size, plus how the operon mode was
    determined. `rna_ids` that look like `TU…` mean transcription units (operons on); ids matching the cistron
    table mean operons off, and every gene_knockout would then be a true single-gene knockout.
    """
    import hashlib
    import json
    from pathlib import Path

    # `kb_sha256` is the FILE hash and is sound in exactly one direction. MEASURED 2026-08-03: two ParCa runs of
    # the same image, same inputs, same `--cpus 14`, minutes apart produced different file hashes
    # (`94325a1e…` / `9881c39e…`) whose `exp_ppgpp` was bit-identical (0/3276) and whose simulations were
    # bitwise identical over all 2530 timesteps. So `same hash => same kb` HOLDS; `different hash => different
    # experiment` DOES NOT. Anything deciding COMPARABILITY must use `kb_content_sha256` (see
    # `reader.kb_content_hash`, computed in-container because it has to unpickle sim_data) and fall back to the
    # file hash only to prove identity. `same_kb()` below is that predicate.
    # `parca_ts` (ARM-2): WHEN this knowledge base was built, from the fitted pickle's mtime. It lets a reader
    # order the arms CAUSALLY — which fit came first — instead of inferring order from the earliest run that
    # happens to use each one, which is only a lower bound and is wrong whenever a kb sat unused for a while.
    out: dict = {"kb_sha256": None, "kb_bytes": None, "kb_content_sha256": None, "parca_ts": None,
                 "operons": None, "operons_evidence": None}
    try:
        from . import runner
        kb = runner._out_root(sim_path).parent / sim_path / "kb" / "simData.cPickle"
        if not kb.exists():
            kb = Path("runs") / sim_path / "kb" / "simData.cPickle"
        if kb.exists():
            h = hashlib.sha256()
            with kb.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            out["kb_sha256"] = h.hexdigest()
            st = kb.stat()
            out["kb_bytes"] = st.st_size
            out["parca_ts"] = st.st_mtime
    except Exception:
        pass
    if out["kb_sha256"]:                   # content hash: DISK-cached, keyed by the file hash
        out["kb_content_sha256"] = _cached_content_hash(sim_path, out["kb_sha256"])
    try:                                   # the variant map was dumped FROM this kb, so its ids settle the mode
        vm = json.loads(paths.cache("variant_map.json").read_text(encoding="utf-8"))
        genes = vm.get("genes") or []
        tu_like = sum(1 for e in genes if str(e.get("rna_id", "")).startswith("TU"))
        n = len(genes)
        if n:
            try:
                n_genes = len(json.loads(paths.cache("gene_scope.json").read_text(encoding="utf-8")))
            except Exception:
                n_genes = None
            out["operons"] = "on" if tu_like else "off"
            out["operons_evidence"] = (
                f"{tu_like}/{n} variant_map rna_ids are TU ids"
                + (f"; {n} knockout rows for {n_genes} genes — fewer rows than genes means polycistronic "
                   f"transcription units" if n_genes else "")
                + ". The remainder are orphan cistrons no TU covers, which is exactly how rna_data is built.")
    except Exception:
        pass
    return out


# The installed packages whose version can change an evaluation's result: the two model SDKs (request shape,
# retries, parsing), the schema layer, the numeric and statistics stack, the corpus readers, and the hub client.
EVAL_PACKAGES = ("anthropic", "openai", "pydantic", "numpy", "scipy", "duckdb", "pyarrow", "huggingface_hub")


def _norm(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _lock_pins(lock) -> dict | None:
    """{normalised name: version} from a pip-freeze lock file, or None when there is no lock to compare with."""
    import re
    from pathlib import Path
    try:
        text = Path(lock).read_text(encoding="utf-8")
    except OSError:
        return None
    return {_norm(m.group(1)): m.group(2) for m in
            (re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;#]+)", line.strip()) for line in text.splitlines()) if m}


def code_environment(lock=None) -> dict:
    """What an evaluation artefact records about the stack that produced it (checklist T.1): the interpreter, whether
    it is a virtual environment, the git commit, the INSTALLED versions of EVAL_PACKAGES, and where they differ from
    requirements.lock. A lock says what should run; this says what did — on 2026-11-23 the system interpreter differed
    from the lock on 70 of 119 pins, `anthropic` among them. `differs_from_lock` is None when there is no lock to
    compare with, which is not the same as no difference. No path is recorded: the artefacts are public."""
    import platform
    import sys
    from importlib import metadata as _md
    from pathlib import Path

    packages: dict = {}
    for pkg in EVAL_PACKAGES:
        try:
            packages[pkg] = _md.version(pkg)
        except Exception:
            packages[pkg] = None
    pins = _lock_pins(lock if lock is not None else Path(__file__).resolve().parents[2] / "requirements.lock")
    differs = None if pins is None else {
        p: {"locked": pins[_norm(p)], "installed": v} for p, v in packages.items()
        if _norm(p) in pins and pins[_norm(p)] != v}
    commit, why = _git_commit_and_why()
    env = {"python": platform.python_version(), "in_a_venv": sys.prefix != sys.base_prefix,
           "git_commit": commit, "packages": packages,
           "lock_file": None if pins is None else "requirements.lock", "differs_from_lock": differs}
    if why:
        env["git_commit_unavailable"] = why
    return env


def run_environment() -> dict:
    """The reproducibility bundle for a run (H-3): `code_environment()` — the interpreter, the repo's git commit, the
    installed versions of the load-bearing dependencies and where they differ from requirements.lock — plus the
    knowledge-base provenance, recorded per Council run alongside the model + temperature (M-2/LLM-3) so a result
    can be reproduced against the exact code + library stack. Best-effort: any lookup that fails degrades to None,
    never raising."""
    return {**code_environment(), **kb_provenance()}


def same_kb(a: dict, b: dict) -> dict:
    """Are two runs on the SAME knowledge base — i.e. may their channels be compared directly?

    Takes two provenance-shaped mappings (anything carrying `kb_sha256` and, ideally, `kb_content_sha256`) and
    returns `{"same": True|False|None, "basis": ..., "why": ...}`. `None` means UNDECIDABLE, and undecidable is
    never silently treated as "same" — that is the silent-absence failure this codebase keeps re-learning.

    The ordering of evidence is the whole point:

      1. `kb_content_sha256` on both -> decisive for "is this the same KNOWLEDGE BASE", in both directions.
         It is NOT a prediction that two runs will agree. MEASURED 2026-08-03: the fork kb and a native kb
         with phnE1 reverted hash differently (`c1bd1018…` vs `624d5a9f…`) yet produce BITWISE IDENTICAL
         simulations over all 2529 timesteps for `gltX+relA+spoT` — they differ in fields that design never
         reads (the tRNA-charging kinetics tables exist only in the ported tree). Same-content implies
         same-output; different-content does not imply different-output, because whether a difference matters
         depends on which fields the chosen design touches. Use it to decide POOLING, not to predict a result.
      2. Only file hashes, and they MATCH -> same. A byte-identical pickle is the same knowledge base.
      3. Only file hashes, and they DIFFER -> UNDECIDABLE, not "different". MEASURED 2026-08-03: two ParCa
         runs of identical code, inputs and cpu count produced different file hashes whose `exp_ppgpp` was
         bit-identical (0/3276) and whose simulations matched bitwise over all 2530 timesteps. Reading a
         hash difference as an experimental difference refuses valid pooling and inflates the count of
         distinct baselines.
      4. Anything missing -> UNDECIDABLE.
    """
    ca, cb = (a or {}).get("kb_content_sha256"), (b or {}).get("kb_content_sha256")
    fa, fb = (a or {}).get("kb_sha256"), (b or {}).get("kb_sha256")
    if ca and cb:
        return {"same": ca == cb, "basis": "kb_content_sha256",
                "why": ("identical sim_data content" if ca == cb else
                        "sim_data content differs — these are different knowledge bases")}
    if fa and fb and fa == fb:
        return {"same": True, "basis": "kb_sha256",
                "why": "byte-identical simData.cPickle — the same knowledge base"}
    if fa and fb:
        return {"same": None, "basis": "kb_sha256",
                "why": ("file hashes differ, but that does NOT establish a different experiment: ParCa's "
                        "serialisation is not reproducible while its behaviour is (measured 2026-08-03 — two "
                        "fits, different file hashes, bitwise-identical simulations over 2530 timesteps). "
                        "Compute kb_content_sha256 (reader.kb_content_hash) on both before concluding.")}
    return {"same": None, "basis": None,
            "why": "at least one side has no kb hash at all — this is an ABSENCE, not a match"}
