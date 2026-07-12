"""Package the raw simOut corpus into per-run archives and upload to a HF dataset (under YOUR login).

Why: the raw corpus is ~139k files, over HF's <100k-files/repo limit. This packs each run (lineage) into ONE
`.tar.gz` -> ~187 archives at `runs/cellarium/<variant>/<seed>.tar.gz`, well under the file-count and 10k/folder
limits. It STREAMS (tar one run -> upload -> delete the local tar), so it never needs disk for all archives at once.

Runs under your huggingface CLI login -- never embeds or prints a token.

    pip install -U huggingface_hub
    hf auth login
    python scripts/hf_pack_upload.py --dry-run                # list what would be packaged/uploaded
    python scripts/hf_pack_upload.py --limit 5                # a small representative subset first
    python scripts/hf_pack_upload.py                          # package + upload ALL runs (large, slow)
    python scripts/hf_pack_upload.py --card                   # also upload data/hf/README.md as the dataset card
"""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
import tempfile
from pathlib import Path


def _run_roots(out: str) -> list[Path]:
    """Every lineage run root under <out>/cellarium (a run root is a simOut's 3rd parent)."""
    base = Path(out) / "cellarium"
    return sorted({so.parents[2] for so in base.glob("**/simOut")}) if base.exists() else []


def main() -> int:
    ap = argparse.ArgumentParser(description="Package raw runs into per-run .tar.gz and upload to a HF dataset.")
    ap.add_argument("--repo", default=os.environ.get("CELLARIUM_HF_REPO", "evanniko1/cellarium-corpus"))
    ap.add_argument("--out", default=os.environ.get("CELLARIUM_OUT", "runs"), help="local output root")
    ap.add_argument("--designs", default="", help="comma-separated design dir names (e.g. gene_knockout_002095) "
                                                   "-- upload only runs under these (for a curated subset)")
    ap.add_argument("--limit", type=int, default=0, help="upload only the first N runs (0 = all)")
    ap.add_argument("--card", action="store_true", help="also upload data/hf/README.md as the dataset card")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        from huggingface_hub import HfApi, whoami
    except ImportError:
        print("huggingface_hub not installed -> pip install -U huggingface_hub", file=sys.stderr)
        return 2
    try:
        me = whoami()
    except Exception:
        print("Not logged in -> hf auth login (paste a WRITE token). Nothing uploaded.", file=sys.stderr)
        return 2

    roots = _run_roots(args.out)
    if args.designs:
        keep = {d.strip() for d in args.designs.split(",") if d.strip()}
        roots = [r for r in roots if r.parent.name in keep]   # <out>/cellarium/<design>/<seed> -> parent = <design>
    if args.limit:
        roots = roots[:args.limit]
    if not roots:
        print(f"no run roots found under {Path(args.out) / 'cellarium'}", file=sys.stderr)
        return 1
    print(f"Logged in as {me.get('name')!r}; {len(roots)} run(s) -> dataset {args.repo}")
    api = HfApi()

    if args.card:
        card = Path("data/hf/README.md")
        if card.exists() and not args.dry_run:
            print("  uploading dataset card -> README.md")
            api.upload_file(path_or_fileobj=str(card), path_in_repo="README.md",
                            repo_id=args.repo, repo_type="dataset")

    for i, rr in enumerate(roots, 1):
        rel = rr.relative_to(Path(args.out).resolve() if rr.is_absolute() else Path(args.out)).as_posix()
        dest = f"runs/{rel}.tar.gz"                      # -> runs/cellarium/<variant>/<seed>.tar.gz
        verb = "[dry-run] would pack+upload" if args.dry_run else "packing+uploading"
        print(f"  [{i}/{len(roots)}] {verb} {rel} -> {args.repo}:{dest}", flush=True)
        if args.dry_run:
            continue
        with tempfile.TemporaryDirectory() as td:        # stream: one tar at a time, then discard
            tarp = Path(td) / (rr.name + ".tar.gz")
            with tarfile.open(tarp, "w:gz") as tf:
                tf.add(str(rr), arcname=rel)
            api.upload_file(path_or_fileobj=str(tarp), path_in_repo=dest,
                            repo_id=args.repo, repo_type="dataset")
    print("dry-run complete (nothing uploaded)." if args.dry_run else "done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
