"""Copy Cellarium's finished wcEcoli files over a clean CovertLab/wcEcoli checkout.

    git clone https://github.com/CovertLab/wcEcoli
    git -C wcEcoli checkout a4497e17
    python scripts/apply_model_overlay.py --wcecoli ./wcEcoli --check   # verify, write nothing
    python scripts/apply_model_overlay.py --wcecoli ./wcEcoli          # apply

WHY OVERLAY AND NOT PATCH. The previous mechanism (`apply_trna_port.py` and friends) transformed a
checkout by matching TEXT ANCHORS. Measured against upstream `a4497e17`, that recipe aborted four
separate times and replayed on NO committed tree — so the only place it had ever fully "worked" was
one incrementally-hand-patched working copy. An overlay ships the finished file and copies it. There
are no anchors to drift and no CRLF sensitivity.

The cost is VERSION PINNING, and this script is where that cost is paid. Every file the overlay
REPLACES has its pre-overlay upstream SHA256 recorded in `model_overlay/MANIFEST.json`. Before
writing, this script hashes what is actually on disk:

    matches upstream_sha256  -> safe to overwrite; upstream has not moved
    matches overlay_sha256   -> already applied; nothing to do (idempotent)
    matches neither          -> STOP, and name the file

The third case is the whole reason this design beats patching. It means either upstream changed the
file (our copy is now stale and may be missing a real upstream fix) or someone edited the checkout by
hand. Both are things you must decide about, not things a tool should silently overwrite. `--force`
proceeds anyway and says so per file; there is no way to get that behaviour by accident.

BLOCKED ENTRIES. The manifest also carries files the overlay knows Cellarium needs but deliberately
does NOT ship — currently five, all of which still carry ROUTE1 isoacceptor code that was extracted
to a separate repository (BACKLOG.md:176). They are reported by name on every run, and a run with
blocked entries NEVER reports success, because a checkout missing them is not a working checkout.
Silence about a known gap is the defect class this repo keeps being bitten by.

LINE ENDINGS. All hashing is over CRLF-normalised bytes, so a Windows checkout (where `git` applies
the repo's eol attributes and produces CRLF) and a Linux checkout hash identically. Files are written
as LF, which is what the model image consumes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OVERLAY = os.path.join(REPO, "model_overlay")
FILES = os.path.join(OVERLAY, "files")
MANIFEST = os.path.join(OVERLAY, "MANIFEST.json")


def read_lf(path: str) -> bytes | None:
    if not os.path.isfile(path):
        return None
    return io.open(path, "rb").read().replace(b"\r\n", b"\n")


def sha256(blob: bytes | None) -> str | None:
    return hashlib.sha256(blob).hexdigest() if blob is not None else None


def load_manifest() -> dict:
    if not os.path.isfile(MANIFEST):
        raise SystemExit("no manifest at %s — run scripts/build_model_overlay.py first" % MANIFEST)
    with io.open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def classify(rec: dict, wcecoli: str) -> dict:
    """Decide what to do with one manifest entry. Reads only; returns a verdict."""
    rel = rec["path"]
    target = os.path.join(wcecoli, rel.replace("/", os.sep))
    source = os.path.join(FILES, rel.replace("/", os.sep))
    out = {"path": rel, "action": rec["action"], "category": rec["category"]}

    body = read_lf(source)
    if body is None:
        return dict(out, verdict="MISSING-OVERLAY",
                    why="model_overlay/files/%s is absent — the overlay tree and the manifest "
                        "disagree; rebuild with scripts/build_model_overlay.py" % rel)
    if sha256(body) != rec["overlay_sha256"]:
        return dict(out, verdict="CORRUPT-OVERLAY",
                    why="model_overlay/files/%s does not match its manifest sha256 — the overlay "
                        "tree was edited without rebuilding the manifest" % rel)

    on_disk = read_lf(target)

    if on_disk is not None and sha256(on_disk) == rec["overlay_sha256"]:
        return dict(out, verdict="ALREADY", why="already identical to the overlay")

    if rec["action"] == "create":
        if on_disk is None:
            return dict(out, verdict="CREATE", why="new file, absent from the target as expected")
        return dict(out, verdict="CONFLICT",
                    why="the overlay declares this a NEW file, but the target already has one that "
                        "differs. Upstream may have added it since %s."
                        % rec.get("_commit", "the pinned commit"))

    # action == "modify"
    if on_disk is None:
        return dict(out, verdict="CONFLICT",
                    why="the overlay declares this a MODIFY of an existing upstream file, but the "
                        "target does not have it — is this a wcEcoli checkout?")
    if sha256(on_disk) == rec["upstream_sha256"]:
        return dict(out, verdict="REPLACE", why="target matches the pinned upstream file")
    return dict(out, verdict="STALE",
                why="target matches neither the pinned upstream file nor the overlay. Either "
                    "upstream changed it (our copy is stale and may be missing a real fix) or the "
                    "checkout was edited by hand.")


def apply(wcecoli: str, check: bool = False, force: bool = False) -> int:
    man = load_manifest()
    pinned = man["upstream_commit"]
    records = man["files"]
    shipped = [r for r in records if r["status"] == "ship"]
    blocked = [r for r in records if r["status"] == "blocked"]

    print("overlay manifest: %d shipped, %d blocked; upstream pinned at %s (%s)"
          % (len(shipped), len(blocked), pinned, man["upstream_repo"]))
    print("target: %s" % os.path.abspath(wcecoli))
    print()

    verdicts = [classify(dict(r, _commit=pinned), wcecoli) for r in shipped]
    by = {}
    for v in verdicts:
        by.setdefault(v["verdict"], []).append(v)

    fatal = by.get("STALE", []) + by.get("CONFLICT", []) + \
        by.get("MISSING-OVERLAY", []) + by.get("CORRUPT-OVERLAY", [])

    for kind in ("MISSING-OVERLAY", "CORRUPT-OVERLAY", "STALE", "CONFLICT"):
        for v in by.get(kind, []):
            print("!! %-16s %s" % (kind, v["path"]))
            print("     %s" % v["why"])

    n_replace = len(by.get("REPLACE", []))
    n_create = len(by.get("CREATE", []))
    n_already = len(by.get("ALREADY", []))
    print("%d to replace, %d to create, %d already applied, %d problems"
          % (n_replace, n_create, n_already, len(fatal)))

    if fatal and not force:
        print()
        print("REFUSING TO WRITE. %d file(s) above are not in a state this overlay knows how to "
              "replace." % len(fatal))
        print("This is the staleness detector, and it is the reason the overlay replaced the old "
              "anchor-matching appliers.")
        print("Fix it by one of:")
        print("  * check out the pinned commit:  git -C %s checkout %s" % (wcecoli, pinned))
        print("  * re-pin the overlay against newer upstream (rebuild the manifest and re-review "
              "each file), or")
        print("  * --force, which overwrites them and prints each one it overwrote.")
        return 1

    wrote = 0
    if not check:
        for v in verdicts:
            if v["verdict"] == "ALREADY":
                continue
            if v["verdict"] in ("MISSING-OVERLAY", "CORRUPT-OVERLAY"):
                continue  # never writable, force or not
            if v["verdict"] in ("STALE", "CONFLICT"):
                print("FORCED  %-62s (%s)" % (v["path"], v["verdict"]))
            src = os.path.join(FILES, v["path"].replace("/", os.sep))
            dst = os.path.join(wcecoli, v["path"].replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            wrote += 1
        print("wrote %d file(s)" % wrote)
    else:
        print("--check: nothing written")

    if blocked:
        print()
        print("!! %d file(s) Cellarium NEEDS are NOT in this overlay:" % len(blocked))
        for r in blocked:
            print("   %-62s %s" % (r["path"], r.get("reason", "").split(".")[0] + "."))
        print("   A checkout built from this overlay is INCOMPLETE until these are resolved.")
        return 1

    if by.get("MISSING-OVERLAY") or by.get("CORRUPT-OVERLAY"):
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    _wc = os.environ.get("WCECOLI_PATH") or os.environ.get("WCECOLI_DIR")
    ap.add_argument("--wcecoli", default=_wc, required=_wc is None,
                    help="the wcEcoli checkout to act on (or set WCECOLI_PATH / WCECOLI_DIR). No default: a hard-coded path silently targeted whichever checkout happened to sit there.")
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    ap.add_argument("--force", action="store_true",
                    help="write even where the target matches neither the pinned upstream file nor "
                         "the overlay; each such file is named as it is overwritten")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.wcecoli):
        print("ERROR: --wcecoli %r is not a directory" % a.wcecoli, file=sys.stderr)
        return 2
    return apply(a.wcecoli, check=a.check, force=a.force)


if __name__ == "__main__":
    sys.exit(main())
