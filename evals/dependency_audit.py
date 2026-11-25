"""Ms-1: every capability record's dependencies (`capability.DEPENDS_ON`), resolved in the model checkout and at its
committed revision.

A reference `path::symbol` resolves when the file exists and the symbol occurs in it as a whole word. It is resolved
twice: in the working tree Cellarium runs against, and at the checkout's HEAD commit. A reference that resolves in the
working tree and not at HEAD lives only in uncommitted changes, and is listed by name.

    python evals/dependency_audit.py    # needs the checkout (WCECOLI_DIR); writes dependency_audit.json
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import capability as C  # noqa: E402

OUT = REPO / "evals" / "results" / "dependency_audit.json"


def resolves(text: str | None, symbol: str) -> bool | None:
    """True when `symbol` occurs as a whole word; None when there is no file to look in (unknown, not absent)."""
    if text is None:
        return None
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(symbol) + r"(?![A-Za-z0-9_])", text) is not None


def _working(checkout: Path, path: str) -> str | None:
    f = checkout / path
    return f.read_text(encoding="utf-8", errors="replace") if f.is_file() else None


def _committed(checkout: Path, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(checkout), "show", f"HEAD:{path}"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else None


def audit(checkout: Path) -> dict:
    refs = [r for refs in C.DEPENDS_ON.values() for r in refs]
    unique = sorted(set(refs))
    work, head = {}, {}
    for r in unique:
        path, symbol = r.split("::")
        work[r] = resolves(_working(checkout, path), symbol)
        head[r] = resolves(_committed(checkout, path), symbol)
    return {"n_references": len(refs), "n_unique": len(unique),
            "resolve_in_checkout": sum(bool(v) for v in work.values()),
            "resolve_at_commit": sum(bool(v) for v in head.values()),
            "missing": sorted(r for r, v in work.items() if not v),
            "only_in_uncommitted_changes": sorted(r for r in unique if work[r] and not head[r]),
            "by_record": {k: [{"ref": r, "checkout": work[r], "commit": head[r]} for r in v]
                          for k, v in C.DEPENDS_ON.items()},
            "no_dependency_reason": C.NO_DEPENDENCY_REASON}


PUBLIC_OUT = OUT.with_name("dependency_audit_public.json")


def public(clone: Path) -> int:
    """Y12: the same resolution in a FRESH CLONE of the public campaign branch, i.e. what a new user gets. Which
    records rest on code no public commit carries, named by record."""
    from cellarium import provenance
    head = subprocess.run(["git", "-C", str(clone), "log", "-1", "--format=%h %s"], capture_output=True, text=True)
    res = audit(clone)
    by = {k: sorted(x["ref"] for x in v if not x["checkout"]) for k, v in res["by_record"].items()}
    out = {"spec": "Y12, a new user's clone", "clone": "MohammedNagdi/wcEcoli feature/wcecoli-platform, fresh "
                                                      "anonymous clone",
           "public_commit": head.stdout.strip() or None,
           "n_references": res["n_references"], "resolve_publicly": res["resolve_in_checkout"],
           "missing_publicly": res["missing"],
           "records_resting_on_unpublished_code": {k: v for k, v in by.items() if v},
           "why": "the kinetic tRNA-charging port is Stanford-derived and its licence request is pending; ROUTE1's "
                  "isoacceptor broadcast reads structures the port builds, so it stays local with the port",
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    PUBLIC_OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(out["public_commit"], out["resolve_publicly"], "of", out["n_references"], out["records_resting_on_unpublished_code"])
    return 0


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--public":
        return public(Path(sys.argv[2]))
    root = os.environ.get("WCECOLI_DIR")
    if not (root and Path(root).is_dir()):
        print("WCECOLI_DIR is not set to a model checkout; nothing can be resolved, and nothing is written.",
              file=sys.stderr)
        return 2
    from cellarium import provenance
    checkout = Path(root)
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    out = {"spec": "Ms-1", "checkout_commit": head.stdout.strip() or None, **audit(checkout),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print({k: out[k] for k in ("n_references", "n_unique", "resolve_in_checkout", "resolve_at_commit")},
          out["only_in_uncommitted_changes"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
