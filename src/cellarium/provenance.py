"""Provenance guardrail — is a corpus quantity IN-SAMPLE (fitted) or OUT-OF-SAMPLE (predicted)?

The H1/H2 pair proved why this matters: H1 (anaerobic regulon) *looked* like a triumphant confirmation but is
in-sample — ParCa fits condition-specific expression, so the model was calibrated to match it; agreement is
consistency, not predictive validation. H2 (Mg->ribosome) is out-of-sample — the fit never targeted it, so its
failure is a genuine, informative model boundary. Without this tag an agent (or reader) over-credits in-sample
agreement. Coarse per-design classification by perturbation type; see docs/CORPUS_OBSERVATIONS.md §6.1/§F.
"""

from __future__ import annotations

from . import redact

# IN-SAMPLE = a condition the model was actually fit to. wcEcoli's fit uses measured RNA-seq for a small set of
# media (M9 Glucose +/-AAs, N-/P-limited, glycerol) plus the modeled-TF regulons (e.g. FNR/ArcA -> anaerobic).
# CRITICAL (audit M4): most named `condition`s are NOT fit to measured data — their expression is network-DERIVED
# from the media definition, so they are OUT-of-sample (e.g. minus_magnesium: H2's Mg->ribosome boundary). The
# old rule tagged every `condition` in-sample and OVER-credited these. We classify conservatively — in-sample only
# for the clearly-fitted conditions; when unsure, out-of-sample (under-crediting is the safe error here).
# M-4: this set is the SOURCE OF TRUTH for the in/out-of-sample tag, so it is PINNED by a test
# (test_provenance.test_in_sample_set_is_pinned) — any edit here must consciously update that test with a
# justification, so the fit set can't SILENTLY DRIFT out of sync with what ParCa actually fits. The authoritative
# set is the media wcEcoli's ParCa calibrates measured RNA-seq against (M9 glucose at the fitted concentrations,
# ±amino acids, anaerobic via the FNR/ArcA regulon); it's deliberately CONSERVATIVE — a condition whose expression
# is network-derived rather than fit to data stays OUT-of-sample (under-crediting is the safe error). If the model's
# fit set changes, re-derive from its condition definitions and update both this set and the pinning test.
IN_SAMPLE_CONDITIONS = {"basal", "glc_20mM", "glc_5mM", "glc_2mM", "with_aa", "no_oxygen"}

_IN_NOTE = ("A ParCa-fitted condition (measured RNA-seq or a modeled-TF regulon) — the model was calibrated to "
            "match this. Agreement with data/literature is CONSISTENCY, not predictive validation.")
_OUT_NOTE = ("The fit did not target this (a perturbation, or a stress/media condition whose expression is network-"
             "DERIVED, not fit to measured data — e.g. the Mg->ribosome boundary). A genuine model prediction; "
             "predictive validation AND informative failure live here.")


def _is_in_sample(perturbation: str, condition: str | None) -> bool:
    # A wildtype OR `condition` run is in-sample ONLY when its CONDITION is one the fit actually targeted (M-3):
    # `wildtype` in an unfitted medium (e.g. wildtype/acetate) is a genuine out-of-sample prediction, NOT in-sample
    # by virtue of being 'wildtype'. condition defaults to 'basal' (the canonical wildtype/basal baseline).
    if perturbation in ("wildtype", "condition"):
        return (condition or "basal") in IN_SAMPLE_CONDITIONS
    return False  # gene_knockout / ppgpp_conc / timeline / objective-weight / ... are perturbations the fit didn't target


def classify(perturbation: str, condition: str | None = None) -> dict:
    in_sample = _is_in_sample(perturbation, condition)
    return {"provenance": "in_sample" if in_sample else "out_of_sample", "note": _IN_NOTE if in_sample else _OUT_NOTE}


def tag(perturbation: str, condition: str | None = None) -> str:
    """Just the label, for annotating list rows."""
    return "in_sample" if _is_in_sample(perturbation, condition) else "out_of_sample"


# --- H-3: per-run environment provenance (the reproducibility bundle) ---------------------------------------

def _git_commit() -> str | None:
    """The repo's current short commit, run in the repo root (not the process CWD) so it's correct regardless of
    where the app was launched. None when git is absent, this isn't a checkout, or the call errors/times out."""
    import subprocess
    from pathlib import Path
    try:
        root = Path(__file__).resolve().parents[2]
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(root),
                           capture_output=True, text=True, timeout=3, env=redact.child_env())
        return (r.stdout.strip() or None) if r.returncode == 0 else None
    except Exception:
        return None


CONTENT_HASH_CACHE = "data/cache/kb_content_hash.json"


MODEL_SHA_CACHE: dict = {}
IMAGE_DIGEST_CACHE: dict = {}
RECON_SHA_CACHE = "data/cache/reconstruction_sha.json"


def model_provenance() -> dict:
    """WHICH SIMULATOR CODE produced a row — `model_sha256`, plus the two things it is made of (ARM-2).

    `kb_sha256` pins the PARAMETERS. Nothing pinned the CODE, so two rows could share a fit and come from
    different model source — the confound the phnE1 investigation had to rule out by hand, by reproducing a run
    bitwise over 2,529 timesteps.

    THE COLUMN IS NOT A GIT SHA, and that is deliberate. This model tree is assembled from two sources: public
    CovertLab wcEcoli at the commit in `model_overlay/MANIFEST.json`, plus the 44 files that overlay ships. A
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
        vm = json.loads(Path("data/cache/variant_map.json").read_text(encoding="utf-8"))
        genes = vm.get("genes") or []
        tu_like = sum(1 for e in genes if str(e.get("rna_id", "")).startswith("TU"))
        n = len(genes)
        if n:
            try:
                n_genes = len(json.loads(Path("data/cache/gene_scope.json").read_text(encoding="utf-8")))
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


def run_environment() -> dict:
    """The reproducibility bundle for a run (H-3): the interpreter, the repo's git commit, and the pinned versions of
    the load-bearing dependencies — recorded per Council run alongside the model + temperature (M-2/LLM-3) so a result
    can be reproduced against the exact code + library stack (see requirements.lock for the full pin set). Best-effort:
    any lookup that fails degrades to None, never raising."""
    import platform
    from importlib import metadata as _md

    packages: dict = {}
    for pkg in ("anthropic", "pydantic", "numpy", "duckdb", "pyarrow"):
        try:
            packages[pkg] = _md.version(pkg)
        except Exception:
            packages[pkg] = None
    return {"python": platform.python_version(), "git_commit": _git_commit(), "packages": packages,
            **kb_provenance()}


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
