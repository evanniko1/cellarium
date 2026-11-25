"""Deposit local runs to the Hugging Face corpus one at a time, and reclaim the disk only after the archive is seen.

For each run root under <out>/<sim_path>/<design>/<seed>:
  1. if the anonymous listing already holds runs/<rel>.tar.gz at no less than 10% of the raw tree, it is not
     uploaded again;
  2. otherwise the run is packed (development-only files such as sim.log left out, as hf_pack_upload does) and
     uploaded under your login;
  3. an UNAUTHENTICATED listing must then show the object at exactly the packed size (retried, since the listing
     can lag); an upload verified with the credential that made it is not verified;
  4. only then, and only with --reclaim, the local run root is deleted. Every step is a row in the ledger.

It refuses the whole deposit while the campaign has a crashed run whose failure nobody has named (FAIL-1d), as
hf_pack_upload does. Runs are restored on demand by `cellarium.hf.download_raw`.

    python scripts/hf_deposit.py --repo <org/corpus> --prefixes gene_knockout --dry-run
    python scripts/hf_deposit.py --repo <org/corpus> --prefixes gene_knockout --reclaim
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
_spec = importlib.util.spec_from_file_location("hf_pack_upload", HERE / "hf_pack_upload.py")
_pack = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pack)

FLOOR = 0.10                     # an existing remote archive under 10% of the raw tree is treated as truncated


def _dir_bytes(p: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def _remote_sizes(anon_api, repo: str) -> dict:
    files = anon_api.list_repo_tree(repo, repo_type="dataset", recursive=True)
    return {f.path: getattr(f, "size", None) for f in files if getattr(f, "path", "").endswith(".tar.gz")}


def _rmtree(p: Path) -> None:
    def _writable(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(p, onerror=_writable)


def run_roots(out: str, sim_path: str, prefixes: tuple[str, ...] = ()) -> list[Path]:
    roots = _pack._run_roots(out, sim_path)
    if prefixes:
        roots = [r for r in roots if r.parent.name.startswith(prefixes)]
    return roots


def deposit(*, out: str, sim_path: str, repo: str, upload_api, anon_api, ledger: Path, reclaim: bool,
            prefixes: tuple[str, ...] = (), limit: int = 0, dry_run: bool = False,
            failures=None, sleep=time.sleep, tmpdir: str | None = None, retries: int = 6) -> list[dict]:
    bad = (failures or _pack.unnamed_failures)(sim_path)
    if bad:
        raise SystemExit(f"REFUSING: {len(bad)} crashed run(s) in {sim_path!r} have a failure nobody has named")
    roots = run_roots(out, sim_path, prefixes)
    if limit:
        roots = roots[:limit]
    rows = []
    ledger.parent.mkdir(parents=True, exist_ok=True)
    for rr in roots:
        rows.append(deposit_one(rr, out=out, repo=repo, upload_api=upload_api, anon_api=anon_api, ledger=ledger,
                                reclaim=reclaim, dry_run=dry_run, sleep=sleep, tmpdir=tmpdir, retries=retries))
    return rows


def deposit_one(rr: Path, *, out: str, repo: str, upload_api, anon_api, ledger: Path, reclaim: bool,
                dry_run: bool = False, sleep=time.sleep, tmpdir: str | None = None, retries: int = 6) -> dict:
    """One run root: upload unless the hub already holds it, verify anonymously, reclaim only when verified.
    The caller is responsible for the FAIL-1d check (deposit() does it once per campaign)."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    rel = rr.relative_to(Path(out)).as_posix()
    key = f"runs/{rel}.tar.gz"
    row = {"rel": rel, "key": key, "local_bytes": _dir_bytes(rr), "uploaded": False, "verified": False,
           "reclaimed": False, "why": "", "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not rr.is_dir():
        # another depositor listed the same run and reclaimed it first: 0 local bytes must not pass the size
        # floor as "verified", and there is nothing to reclaim
        row["why"] = "run root not on disk (reclaimed by another process?); nothing checked or deleted"
        _log(ledger, row)
        return row
    try:
        before = _remote_sizes(anon_api, repo)
    except Exception as e:                                   # noqa: BLE001  a failed listing confirms nothing
        row["why"] = f"anonymous listing failed before upload: {type(e).__name__}"
        _log(ledger, row)
        return row
    if dry_run:
        row["why"] = "dry run: on the hub" if key in before else "dry run: would upload"
        _log(ledger, row)
        return row
    if key in before:
        size = before[key]
        row["remote_bytes"] = size
        row["verified"] = size is not None and size >= FLOOR * row["local_bytes"]
        row["why"] = "already on the hub" + ("" if row["verified"] else ": under the size floor, not trusted")
    else:
        with tempfile.TemporaryDirectory(dir=tmpdir) as td:
            tarp = Path(td) / (rr.name + ".tar.gz")
            _pack.pack_run(rr, rel, tarp)
            row["tar_bytes"] = tarp.stat().st_size
            upload_api.upload_file(path_or_fileobj=str(tarp), path_in_repo=key, repo_id=repo, repo_type="dataset")
            row["uploaded"] = True
        for attempt in range(retries):
            try:
                size = _remote_sizes(anon_api, repo).get(key)
            except Exception as e:                           # noqa: BLE001
                row["why"] = f"anonymous listing failed after upload: {type(e).__name__}"
                size = None
            row["remote_bytes"] = size
            if size == row["tar_bytes"]:
                row["verified"], row["why"] = True, ""
                break
            if size is not None:
                row["why"] = f"remote size {size} differs from the packed {row['tar_bytes']}"
            sleep(min(60, 5 * 2 ** attempt))
    if reclaim and row["verified"]:
        _rmtree(rr)
        row["reclaimed"] = True
    _log(ledger, row)
    return row


def _log(ledger: Path, row: dict) -> None:
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=os.environ.get("CELLARIUM_HF_REPO"), required=not os.environ.get("CELLARIUM_HF_REPO"))
    ap.add_argument("--out", default=os.environ.get("CELLARIUM_OUT", "runs"))
    ap.add_argument("--sim-path", dest="sim_path", default="cellarium")
    ap.add_argument("--prefixes", default="", help="comma-separated design-name prefixes, e.g. gene_knockout")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reclaim", action="store_true", help="delete each local run once the hub shows it")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ledger", default="data/hf/deposit_ledger.jsonl")
    ap.add_argument("--tmpdir", default=None, help="where to pack each archive (one at a time)")
    a = ap.parse_args(argv)
    from huggingface_hub import HfApi
    rows = deposit(out=a.out, sim_path=a.sim_path, repo=a.repo, upload_api=HfApi(), anon_api=HfApi(token=False),
                   ledger=Path(a.ledger), reclaim=a.reclaim, dry_run=a.dry_run, limit=a.limit, tmpdir=a.tmpdir,
                   prefixes=tuple(p.strip() for p in a.prefixes.split(",") if p.strip()))
    ok = [r for r in rows if r["verified"]]
    print(f"{len(rows)} run(s): {len(ok)} verified anonymously, {sum(r['reclaimed'] for r in rows)} reclaimed, "
          f"{sum(r['local_bytes'] for r in rows if r['reclaimed']) / 1e9:.1f} GB freed")
    for r in rows:
        if not r["verified"] and not a.dry_run:
            print(f"  NOT VERIFIED {r['rel']}: {r['why']}")
    return 0 if a.dry_run or len(ok) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
