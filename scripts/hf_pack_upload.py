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
    python scripts/hf_pack_upload.py --card                   # runs + the card + the parca/ artefacts
    python scripts/hf_pack_upload.py --card-only              # ONLY the card + parca/ artefacts; no archives
    python scripts/hf_pack_upload.py --card-only --dry-run    # list exactly what that would put in the repo
"""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
import tempfile
from pathlib import Path


def _run_roots(out: str, sim_path: str = "cellarium") -> list[Path]:
    """Every lineage run root under <out>/<sim_path> (a run root is a simOut's 3rd parent).

    `sim_path` was hard-coded to "cellarium", so this could not see ANY other campaign — the SCI-TRNA-4
    dropout arms live under `runs/aadrop/` and were simply invisible to the uploader, which reported "no run
    roots found" rather than anything resembling the real problem. Same hard-coded-sim_path class as the bug
    in `manifest.campaign` and `_crash_row`."""
    base = Path(out) / sim_path
    return sorted({so.parents[2] for so in base.glob("**/simOut")}) if base.exists() else []


def main() -> int:
    ap = argparse.ArgumentParser(description="Package raw runs into per-run .tar.gz and upload to a HF dataset.")
    ap.add_argument("--repo", default=os.environ.get("CELLARIUM_HF_REPO", "evanniko1/cellarium-corpus"))
    ap.add_argument("--out", default=os.environ.get("CELLARIUM_OUT", "runs"), help="local output root")
    ap.add_argument("--designs", default="", help="comma-separated design dir names (e.g. gene_knockout_002095) "
                                                   "-- upload only runs under these (for a curated subset)")
    ap.add_argument("--sim-path", dest="sim_path", default="cellarium",
                    help="which campaign under <out>/ to upload (e.g. aadrop for the dropout arms)")
    ap.add_argument("--limit", type=int, default=0, help="upload only the first N runs (0 = all)")
    ap.add_argument("--card", action="store_true", help="also upload data/hf/README.md as the dataset card "
                                                        "plus the parca/ provenance artefacts it describes")
    ap.add_argument("--card-only", dest="card_only", action="store_true",
                    help="upload ONLY the card and the parca/ artefacts; touch no run archives. This is the "
                         "safe way to correct documentation: without it, --card still walks every run and "
                         "re-uploads gigabytes to fix a paragraph.")
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

    if args.card_only:
        args.card = True
    roots = [] if args.card_only else _run_roots(args.out, args.sim_path)
    if args.designs:
        keep = {d.strip() for d in args.designs.split(",") if d.strip()}
        roots = [r for r in roots if r.parent.name in keep]   # <out>/cellarium/<design>/<seed> -> parent = <design>
    if args.limit:
        roots = roots[:args.limit]
    if not roots and not args.card_only:
        print(f"no run roots found under {Path(args.out) / args.sim_path}", file=sys.stderr)
        return 1
    print(f"Logged in as {me.get('name')!r}; {len(roots)} run(s) -> dataset {args.repo}")
    api = HfApi()

    if args.card:
        card = Path("data/hf/README.md")
        if card.exists() and not args.dry_run:
            print("  uploading dataset card -> README.md")
            api.upload_file(path_or_fileobj=str(card), path_in_repo="README.md",
                            repo_id=args.repo, repo_type="dataset")
        # The card's degradation-rate section is only actionable if the index it describes travels with it.
        # A downstream consumer holds the parquet and the tars, never this repo's tool layer, so the 854
        # not-a-fit units reach them here or not at all — the one gap Cellarium's payload marking cannot close.
        for prov in (Path("data/parca/deg_rate_baseline.json"), Path("data/parca/deg_rate_aliases.json")):
            if not prov.exists():
                print(f"  WARNING: {prov} missing — the card describes an index the dataset will not carry",
                      file=sys.stderr)
                continue
            print(f"  {'[dry-run] would upload' if args.dry_run else 'uploading'} "
                  f"{prov} -> parca/{prov.name}")
            if not args.dry_run:
                api.upload_file(path_or_fileobj=str(prov), path_in_repo=f"parca/{prov.name}",
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
