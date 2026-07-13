"""Hugging Face availability — the two alternatives for data BEYOND the distilled shard.

The committed manifest shards (per-species panel + summary channels + viability, coarse) answer most questions
locally with no download. For FULL granularity — an arbitrary species, full-resolution trajectory, or FBA flux —
a run's raw simOut is needed, which is either (a) on the HF dataset or (b) regenerable locally. This module tells
the agent WHICH, so it can point the user at the right path. It performs NO upload and needs NO network to answer
(the descriptor is config-driven); the actual upload lives in scripts/hf_upload.py and runs under the user's login.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import store
from .runner import OUT_ROOT

HF_REPO = os.environ.get("CELLARIUM_HF_REPO", "evanniko1/cellarium-corpus")
# The raw corpus IS uploaded to the HF dataset, so download_raw / data_availability offer HF pulls by DEFAULT —
# users get that capability out of the box. Per-design HF presence is still checked (a design not on HF reports so
# honestly). Set CELLARIUM_HF_HAS_RAW=0 to force the regenerate-locally path instead.
HF_HAS_RAW = os.environ.get("CELLARIUM_HF_HAS_RAW", "1").strip().lower() in ("1", "true", "yes")
# What the shard carries locally (no raw read) vs what needs raw simOut (HF download or regenerate).
SHARD_ANSWERS = "panel-species terminal+coarse trajectory, summary channels, viability, pathways"
NEEDS_RAW = "arbitrary (non-panel) species, full-resolution trajectories, FBA reaction/exchange fluxes"


def _hf_rel(simout_path: str | None) -> str | None:
    """A run's local path -> its PORTABLE path inside the HF dataset. Derived from the '/cellarium/' suffix (the
    sim_path root), so it resolves for cloners and HF regardless of the absolute prefix or output root — NOT
    Path.relative_to(OUT_ROOT), which only worked on the machine that recorded the absolute path."""
    if not simout_path:
        return None
    s = str(simout_path).replace("\\", "/")
    i = s.rfind("/cellarium/")
    if i >= 0:
        return "runs/cellarium/" + s[i + len("/cellarium/"):] + ".tar.gz"  # the packaged per-run archive (hf_pack_upload)
    return None


def _design_seeds(design: str) -> list[dict]:
    """The manifest rows for a design label ('condition/no_oxygen') or a single result_id."""
    rows = store.list_results()
    by_id = {r.get("id"): r for r in rows}
    if design in by_id:
        return [by_id[design]]
    pert, _, cond = str(design).partition("/")
    return [r for r in rows if r.get("perturbation") == pert
            and ((r.get("condition") or "") == cond or (cond and cond in (r.get("condition") or "")))]


def _repo_sizes(paths: list[str]) -> dict:
    """{hf_path: size_bytes} for the given repo paths that actually exist — one HfApi tree call per design dir.
    Empty dict on any network/API error (caller treats missing as unavailable)."""
    try:
        from huggingface_hub import HfApi
    except Exception:
        return {}
    dirs = sorted({p.rsplit("/", 1)[0] for p in paths})
    sizes: dict[str, int] = {}
    api = HfApi()
    for d in dirs:
        try:
            for f in api.list_repo_tree(HF_REPO, path_in_repo=d, repo_type="dataset", recursive=False):
                p = getattr(f, "path", "")
                if p.endswith(".tar.gz"):
                    sizes[p] = int(getattr(f, "size", 0) or 0)
        except Exception:
            continue
    return sizes


def download_plan(design: str) -> dict:
    """What a download of `design`'s raw simOut would pull from HF: per-seed archive, size, and whether it's already
    local — WITHOUT downloading anything (HF metadata only). The size is the gate: the agent surfaces est_gb before
    pulling."""
    seeds = _design_seeds(design)
    if not seeds:
        return {"error": f"no runs match '{design}'."}
    want = []
    for r in seeds:
        path = store.simout_path(r["id"])
        rel = _hf_rel(path)
        local = bool(path and Path(path).exists())
        want.append({"result_id": r["id"], "seed": r.get("seed"), "hf_path": rel, "local": local})
    need = [w for w in want if w["hf_path"] and not w["local"]]
    sizes = _repo_sizes([w["hf_path"] for w in need]) if need else {}
    for w in need:
        w["size_gb"] = round(sizes.get(w["hf_path"], 0) / 1e9, 2) if w["hf_path"] in sizes else None
        w["on_hf"] = w["hf_path"] in sizes
    to_pull = [w for w in need if w.get("on_hf")]
    est_gb = round(sum((sizes.get(w["hf_path"], 0) for w in to_pull)) / 1e9, 2)
    return {"design": design, "repo": HF_REPO,
            "n_seeds": len(want), "n_local": sum(1 for w in want if w["local"]),
            "n_to_pull": len(to_pull), "est_gb": est_gb,
            "not_on_hf": [w["result_id"] for w in need if not w.get("on_hf")],
            "files": want}


def download_raw(design: str, confirm: bool = False) -> dict:
    """Pull `design`'s missing raw simOut archives from HF into the local runs dir so read_raw_series / variance_band
    can read them. GATED: with confirm=False (default) it only returns the size estimate and asks for approval; it
    downloads NOTHING. Only call again with confirm=True AFTER the user approves the size."""
    plan = download_plan(design)
    if "error" in plan:
        return plan
    if plan["n_to_pull"] == 0:
        msg = ("already local — nothing to download." if plan["n_local"] == plan["n_seeds"]
               else "none of the missing seeds are on HF yet (regenerate locally, or check the upload ledger).")
        return {**plan, "downloaded": [], "note": msg}
    if not confirm:
        return {**plan, "needs_confirmation": True,
                "message": f"This pulls ~{plan['est_gb']} GB from HF ({plan['n_to_pull']} archive(s) for "
                           f"{design}). Confirm with the user before proceeding, then call again with confirm=True."}
    # confirmed: download + extract each missing archive into OUT_ROOT
    try:
        from huggingface_hub import hf_hub_download
    except Exception:
        return {**plan, "error": "huggingface_hub not installed; run the CLI command from data_availability instead."}
    import tarfile
    done, failed = [], []
    for w in plan["files"]:
        if not (w.get("hf_path") and not w["local"] and w.get("on_hf")):
            continue
        try:
            local_tar = hf_hub_download(HF_REPO, w["hf_path"], repo_type="dataset")
            with tarfile.open(local_tar, "r:gz") as tf:
                tf.extractall(str(OUT_ROOT), filter="data")   # arcname is cellarium/<variant>/<seed> -> lands under runs/
            done.append(w["result_id"])
        except Exception as e:
            failed.append({"result_id": w["result_id"], "error": str(e)[:160]})
    return {"design": design, "repo": HF_REPO, "downloaded": done, "failed": failed,
            "est_gb": plan["est_gb"],
            "note": f"pulled {len(done)} archive(s) into {OUT_ROOT}; raw_available/variance_band can now read them."}


def data_availability(result_id: str) -> dict:
    """Where to get FULL-granularity data for a result beyond the distilled shard. Returns BOTH alternatives:
    (1) download the run's raw simOut from the HF dataset, or (2) regenerate it locally (you accept the wcEcoli
    license by running the model yourself). Use when a question needs a species/resolution the shard doesn't carry."""
    path = store.simout_path(result_id)
    design = next((r for r in store.list_results() if r.get("id") == result_id), {})
    rel = _hf_rel(path)
    raw_local = bool(path and Path(path).exists())
    available = HF_HAS_RAW and rel is not None      # only 'available' once the raw corpus is actually uploaded
    download = (f"hf download {HF_REPO} --repo-type dataset --include '{rel}' --local-dir {OUT_ROOT.parent} && "
                f"tar xzf '{OUT_ROOT.parent}/{rel}' -C '{OUT_ROOT}'"
                if available else None)
    hf_alt = {"repo": HF_REPO, "path": rel, "available": available, "command": download}
    if not HF_HAS_RAW:
        hf_alt["status"] = "raw corpus not uploaded to HF yet — use alternative 2 (regenerate) for now"
    return {"result_id": result_id,
            "shard_answers": SHARD_ANSWERS, "needs_raw": NEEDS_RAW,
            "raw_local": raw_local, "raw_local_path": (path if raw_local else None),
            "alternatives": {
                "1_download_from_hf": hf_alt,
                "2_regenerate_locally": {
                    "design": {k: design.get(k) for k in ("perturbation", "condition", "timeline", "seed")},
                    "how": "re-run this design via cellarium.runner.run_one (or the matching generate.py arm); "
                           "running wcEcoli yourself means you accept its Stanford S18-475 license — no data is "
                           "redistributed to you."}},
            "note": "the shard already answers panel-species + summary questions with NO download. Only reach for "
                    "an alternative when the question needs data the shard doesn't carry."}
