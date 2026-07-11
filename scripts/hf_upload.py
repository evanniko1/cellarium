"""Upload the Cellarium corpus to a (private) Hugging Face dataset repo.

Runs UNDER YOUR huggingface CLI login -- it never embeds, reads, or prints a token. Log in first:

    pip install -U huggingface_hub
    hf auth login                 # paste a WRITE-scoped token from huggingface.co/settings/tokens

Then, from the repo root:

    python scripts/hf_upload.py --what manifest          # distilled shards only (small, safe default)
    python scripts/hf_upload.py --what runs              # raw simOut trajectories (large)
    python scripts/hf_upload.py --what all --dry-run     # preview without uploading
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload the Cellarium corpus to a HF dataset repo (under your login).")
    ap.add_argument("--repo", default=os.environ.get("CELLARIUM_HF_REPO", "evanniko1/cellarium-corpus"))
    ap.add_argument("--what", choices=["manifest", "runs", "all"], default="manifest")
    ap.add_argument("--out", default=os.environ.get("CELLARIUM_OUT", "runs"), help="local output root for raw runs")
    ap.add_argument("--dry-run", action="store_true", help="show what would upload without uploading")
    args = ap.parse_args()

    try:
        from huggingface_hub import HfApi, whoami
    except ImportError:
        print("huggingface_hub not installed -> run: pip install -U huggingface_hub", file=sys.stderr)
        return 2

    try:
        me = whoami()                 # verifies your login via the cached token; we never read the token
    except Exception:
        print("Not logged in -> run: hf auth login  (paste a WRITE token). Nothing uploaded.", file=sys.stderr)
        return 2
    print(f"Logged in as {me.get('name')!r}; target dataset: {args.repo}")

    jobs = []
    if args.what in ("manifest", "all"):
        jobs.append(("data/manifest", "data/manifest", "distilled manifest shards"))
    if args.what in ("runs", "all"):
        jobs.append((str(Path(args.out) / "cellarium"), "runs/cellarium", "raw simOut trajectories (LARGE)"))

    api = HfApi()
    for local, dest, desc in jobs:
        if not Path(local).exists():
            print(f"  skip {desc}: {local} not found")
            continue
        verb = "[dry-run] would upload" if args.dry_run else "uploading"
        print(f"  {verb} {desc}: {local} -> {args.repo}:{dest}")
        if not args.dry_run:
            api.upload_folder(folder_path=local, path_in_repo=dest, repo_id=args.repo, repo_type="dataset")
    print("dry-run complete (nothing uploaded)." if args.dry_run else "done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
