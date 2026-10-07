"""NMI-4 — the ONE authoritative size of the published dataset, measured rather than asserted.

THE PROBLEM THIS EXISTS FOR. Two committed documents disagreed about how large the public dataset is.
`README.md` said "about 198 GB across 96 run archives"; `data/hf/UPLOAD_LEDGER.md` said "13 designs / 55 runs
(~90-100 GB compressed)". Neither cited a measurement. For a platform paper that is the most load-bearing
unverified number in the submission -- it is what a reader uses to judge the dataset claim -- and a reviewer
who checks the deposit and finds a third number has reason to doubt every number they cannot check.

WHY IT IS MEASURED ANONYMOUSLY. The question is not "what did we upload" but "what can a third party
actually get", and those differ whenever a token grants more than the public does. `token=False` is a fresh
unauthenticated view of the public repo -- exactly what a downloader sees. An archive not visible that way
does not exist for the dataset's users, whatever the local state says. This is the same reasoning as
`verify_hf_upload.py`, applied to the whole repo instead of one batch.

WHAT IT WRITES, and why a file rather than a printout. `data/hf/DATASET_SIZE.json` is the single artifact both
documents cite, so a disagreement between them becomes impossible rather than merely discouraged:
`tests/test_dataset_size.py` reads the numbers back out of the prose and fails if either document drifts from
it. The failure mode being defended against is not a wrong number, it is TWO numbers.

OFFLINE / RATE-LIMITED BEHAVIOUR, stated because it decides what CI can assert. With no network the listing
fails, and this script exits non-zero WITHOUT writing -- it never overwrites a real measurement with an empty
one, which would convert "could not check" into "the dataset is empty". That is the silent-absence failure
this repository keeps finding in itself. The committed artifact therefore stays the last real measurement, and
the consistency test runs against it in CI with no network at all.

    python scripts/verify_dataset_size.py              # measure, print, write the artifact
    python scripts/verify_dataset_size.py --check      # measure and compare to the artifact; write nothing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "hf" / "DATASET_SIZE.json"
REPO = os.environ.get("CELLARIUM_HF_REPO", "evanniko1/cellarium-corpus")

GB = 1024 ** 3


def measure(repo: str = REPO) -> dict:
    """List the public dataset anonymously and total it. Raises on any failure; never returns zeros."""
    from huggingface_hub import HfApi

    api = HfApi()
    files = list(api.list_repo_tree(repo, repo_type="dataset", recursive=True, token=False))
    archives = [f for f in files if getattr(f, "path", "").endswith(".tar.gz")]
    if not archives:
        raise RuntimeError(f"{repo}: listed {len(files)} entries and found no .tar.gz archives -- "
                           "refusing to record a zero, because 'could not see it' is not 'it is not there'")

    total = 0
    designs: set[str] = set()
    sims: set[str] = set()
    missing_size = 0
    for f in archives:
        sz = getattr(f, "size", None) or getattr(f, "lfs", None) and getattr(f.lfs, "size", None)
        if sz:
            total += int(sz)
        else:
            missing_size += 1
        parts = f.path.split("/")
        # runs/<sim>/<design>/<seed>.tar.gz -- one archive is one SEED, i.e. one run; the directory
        # holding it is the design. Counting archives and counting designs answer different questions
        # and were two of the three numbers in circulation, so both are recorded.
        if len(parts) >= 3:
            designs.add("/".join(parts[:-1]))
            sims.add(parts[1])

    parquet = [f for f in files if getattr(f, "path", "").endswith(".parquet")]
    return {
        "repo": repo,
        "measured_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "huggingface_hub list_repo_tree(recursive=True, token=False) -- anonymous, as a downloader sees it",
        "n_runs": len(archives),          # one .tar.gz is one seed of one design, i.e. one run
        "n_archives": len(archives),      # retained: the README's unit, identical to n_runs
        "n_designs": len(designs),
        "sim_paths": sorted(sims),
        "total_bytes": total,
        "total_gb": round(total / GB, 1),
        "archives_without_reported_size": missing_size,
        "n_parquet_files": len(parquet),
        "n_entries_total": len(files),
    }


def _fmt(m: dict) -> str:
    return (f"{m['repo']}\n"
            f"  runs (.tar.gz)     : {m['n_runs']}\n"
            f"  designs            : {m['n_designs']}  across sim paths {', '.join(m['sim_paths'])}\n"
            f"  total size         : {m['total_gb']} GB ({m['total_bytes']} bytes)\n"
            f"  parquet files      : {m['n_parquet_files']}\n"
            f"  entries listed     : {m['n_entries_total']}\n"
            f"  measured           : {m['measured_utc']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="measure and compare against the committed artifact; write nothing")
    args = ap.parse_args()

    try:
        m = measure()
    except Exception as e:                                      # noqa: BLE001 -- the cause is the message
        print(f"could not measure the dataset: {e}", file=sys.stderr)
        print("NOTHING written. The committed artifact stands as the last real measurement.", file=sys.stderr)
        return 2

    print(_fmt(m))

    if args.check:
        if not OUT.exists():
            print(f"\nno committed artifact at {OUT.relative_to(ROOT)} to compare against", file=sys.stderr)
            return 1
        old = json.loads(OUT.read_text(encoding="utf-8"))
        drift = [k for k in ("n_archives", "total_gb") if old.get(k) != m[k]]
        if drift:
            for k in drift:
                print(f"\nDRIFT {k}: committed {old.get(k)} -> measured {m[k]}", file=sys.stderr)
            print("Re-run without --check to record the new measurement, and update the prose that cites it.",
                  file=sys.stderr)
            return 1
        print("\nmatches the committed artifact")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
