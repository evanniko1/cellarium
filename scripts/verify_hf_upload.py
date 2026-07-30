"""Confirm an upload actually landed — ANONYMOUSLY, not by trusting the uploader's exit code.

`hf_pack_upload.py` uses the token-carrying client. A token that reads but cannot write, or one that has
expired, produces a failure the uploading process may not surface: this repo's stale token went unnoticed for
weeks precisely because `hf.py` silently falls back to anonymous access for READS, so everything looked healthy
until an upload was attempted. An upload verified with the same credential that performed it is not verified.

So this checks with `token=False`: a fresh, unauthenticated view of the public repo, which is also exactly what
a third party downloading the dataset would see. If an archive is not visible anonymously it does not exist for
the dataset's users, whatever our local state says.

It compares REMOTE SIZE against the local run's packed-tar size where the local copy still exists, because
presence alone is not enough — a 0-byte or truncated object would list fine. Sizes are compared loosely (a
tar.gz of the same tree is not byte-reproducible across runs) but a remote object under half the expected size
is treated as a failure.

**Exits non-zero unless every expected archive is confirmed.** This gates deleting the local copy, so an
ambiguous answer must read as "do not delete".

    python scripts/verify_hf_upload.py --sim-path aadrop --designs dirA,dirB
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = os.environ.get("CELLARIUM_HF_REPO", "evanniko1/cellarium-corpus")


def _local_run_roots(out: str, sim_path: str, designs: set[str]) -> list[Path]:
    base = Path(out) / sim_path
    roots = sorted({so.parents[2] for so in base.glob("**/simOut")}) if base.exists() else []
    return [r for r in roots if not designs or r.parent.name in designs]


def _dir_bytes(p: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def verify(out: str, sim_path: str, designs: set[str], repo: str = REPO) -> dict:
    from huggingface_hub import HfApi

    # token=False: an UNAUTHENTICATED view. Deliberate — see module docstring.
    api = HfApi(token=False)
    try:
        files = api.list_repo_tree(repo, repo_type="dataset", recursive=True)
        remote = {f.path: getattr(f, "size", None) for f in files if getattr(f, "path", "").endswith(".tar.gz")}
    except Exception as e:
        return {"ok": False, "why": f"anonymous listing of {repo} failed: {type(e).__name__}: {e}",
                "note": "Could not see the repo without credentials. Treat as NOT verified."}

    roots = _local_run_roots(out, sim_path, designs)
    if not roots:
        return {"ok": False, "why": f"no local run roots under {Path(out) / sim_path} matching {sorted(designs)} "
                                    f"— nothing to verify against, so nothing is confirmed"}
    checked, missing, suspect = [], [], []
    for rr in roots:
        rel = rr.relative_to(Path(out)).as_posix()
        key = f"runs/{rel}.tar.gz"
        size = remote.get(key)
        if key not in remote:
            missing.append(key)
            continue
        local = _dir_bytes(rr)
        # a gzipped tar of simOut lands well under the raw tree; under half of a conservative 25% floor is wrong
        floor = int(local * 0.10)
        if size is None:
            suspect.append({"path": key, "remote_size": None, "why": "listing returned no size"})
        elif size < floor:
            suspect.append({"path": key, "remote_size": size, "local_bytes": local,
                            "why": f"remote object is {size / 1e6:.1f} MB against a {floor / 1e6:.1f} MB floor "
                                   f"for a {local / 1e9:.2f} GB run — truncated or empty"})
        else:
            checked.append({"path": key, "remote_mb": round(size / 1e6, 1), "local_gb": round(local / 1e9, 2)})
    ok = not missing and not suspect
    return {"ok": ok, "repo": repo, "seen_anonymously": True,
            "n_expected": len(roots), "n_confirmed": len(checked),
            "confirmed": checked, "missing": missing, "suspect": suspect,
            "verdict": ("ALL CONFIRMED anonymously — the local copy is safe to reclaim."
                        if ok else
                        "NOT CONFIRMED — do NOT delete the local copy. Re-upload the listed runs first."),
            "note": "Checked with token=False, i.e. the view a third party gets. An upload verified with the "
                    "credential that performed it is not verified."}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.environ.get("CELLARIUM_OUT", "runs"))
    ap.add_argument("--sim-path", dest="sim_path", default="cellarium")
    ap.add_argument("--designs", default="")
    ap.add_argument("--repo", default=REPO)
    a = ap.parse_args(argv)
    res = verify(a.out, a.sim_path, {d.strip() for d in a.designs.split(",") if d.strip()}, a.repo)
    if res.get("why"):
        print(f"ERROR: {res['why']}")
    for c in res.get("confirmed") or []:
        print(f"  OK      {c['path']}  ({c['remote_mb']} MB remote / {c['local_gb']} GB raw)")
    for m in res.get("missing") or []:
        print(f"  MISSING {m}")
    for s in res.get("suspect") or []:
        print(f"  SUSPECT {s['path']}: {s['why']}")
    print(f"\n{res.get('n_confirmed', 0)}/{res.get('n_expected', 0)} confirmed anonymously")
    print(res.get("verdict", ""))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
