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
# Set CELLARIUM_HF_HAS_RAW=1 ONCE the raw corpus is actually uploaded (scripts/hf_upload.py --what runs). Until
# then, HF download is reported as unavailable so the agent honestly points the user to regenerate-locally instead.
HF_HAS_RAW = os.environ.get("CELLARIUM_HF_HAS_RAW", "").strip().lower() in ("1", "true", "yes")
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
        return "runs/cellarium/" + s[i + len("/cellarium/"):]   # mirrors scripts/hf_upload.py's runs/cellarium layout
    return None


def data_availability(result_id: str) -> dict:
    """Where to get FULL-granularity data for a result beyond the distilled shard. Returns BOTH alternatives:
    (1) download the run's raw simOut from the HF dataset, or (2) regenerate it locally (you accept the wcEcoli
    license by running the model yourself). Use when a question needs a species/resolution the shard doesn't carry."""
    path = store.simout_path(result_id)
    design = next((r for r in store.list_results() if r.get("id") == result_id), {})
    rel = _hf_rel(path)
    raw_local = bool(path and Path(path).exists())
    available = HF_HAS_RAW and rel is not None      # only 'available' once the raw corpus is actually uploaded
    download = (f"hf download {HF_REPO} --repo-type dataset --include '{rel}/**' --local-dir {OUT_ROOT.parent}"
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
