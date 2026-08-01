"""Build the ROUTE1 CONTROL image: the same tree, with ONLY the occupancy edit reverted.

WHY THIS EXISTS. The first acceptance run compared a freshly rebuilt image against baselines produced
by an image that could no longer be identified under any tag, while the working tree also carried six
non-ROUTE1 changes. The measured effect had exactly the predicted magnitude and the predicted scalar
signature, so it was strong evidence -- but it could not ISOLATE this edit from those six. A control
built from the same tree with only this edit reverted removes that confound completely: the two
images then differ by one expression and nothing else.

WHAT IT DOES, and why it is one script rather than three commands. revert -> build -> re-apply must
be ATOMIC. If it stops after the revert, the working tree is left with the ppGpp arm un-fixed, and
every later run silently uses the wrong code. So the re-apply sits in a `finally`, runs even if the
build raises or is interrupted, and the script VERIFIES the restored file against an md5 captured
before anything was touched. A restore that does not reproduce that hash is a hard error.

    python scripts/build_route1_control_image.py [--tag wcecoli-sim:route1control] [--skip-build]

`--skip-build` exercises the revert/restore cycle without paying for a build, which is how the
round-trip was verified in the first place.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route1_occupancy_patch import REL, revert  # noqa: E402
from route1_occupancy_patch import run as apply_patch  # noqa: E402


def _md5(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wcecoli", default=os.environ.get("WCECOLI", r"C:/dev/wcEcoli"))
    ap.add_argument("--tag", default="wcecoli-sim:route1control")
    ap.add_argument("--dockerfile", default="docker/local/Dockerfile")
    ap.add_argument("--skip-build", action="store_true")
    a = ap.parse_args(argv)

    path = os.path.join(a.wcecoli, REL)
    if not os.path.isfile(path):
        print(f"ERROR: {REL} not found under {a.wcecoli}")
        return 1

    before = _md5(path)
    print(f"patched md5   {before}")

    # Refuse to run against an unpatched tree: the control would then be identical to the treatment
    # and the whole A/B would silently compare an image to itself.
    from route1_occupancy_patch import status
    st = status(a.wcecoli)
    if not (st["occupancy"] and st["docstring"]):
        print(f"ERROR: tree is not in the patched state ({st}) — a control built now would be "
              f"identical to the treatment. Apply the patch first.")
        return 1

    build_rc = None
    try:
        r = revert(a.wcecoli)
        if not r["complete"]:
            print(f"ERROR: revert failed: {r.get('why')}")
            return 1
        print(f"reverted md5  {_md5(path)}")
        for w in r["wrote"]:
            print(f"  {w}")

        if a.skip_build:
            print("--skip-build: not building; exercising the restore path only")
        else:
            cmd = ["docker", "build", "-f", a.dockerfile, "-t", a.tag, "."]
            print(f"building {a.tag} ... ({' '.join(cmd)})")
            proc = subprocess.run(cmd, cwd=a.wcecoli, capture_output=True, text=True)
            build_rc = proc.returncode
            tail = [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()][-12:]
            print("\n".join(f"  | {ln}" for ln in tail))
            print(f"build rc={build_rc}")
    finally:
        # ALWAYS restore, even if the build raised or was interrupted.
        back = apply_patch(a.wcecoli, check=False)
        after = _md5(path)
        print(f"re-applied md5 {after}")
        if after != before:
            print(f"FATAL: restore did NOT reproduce the pre-build file "
                  f"({after} != {before}); wrote={back.get('wrote')} why={back.get('why')}")
            return 1
        print("restore verified byte-identical")

    if a.skip_build:
        return 0
    if build_rc != 0:
        print("BUILD FAILED — no control image was produced")
        return 1

    # Prove the image really contains the reverted code, rather than trusting the build log. The
    # marker must be ABSENT inside the control image and PRESENT in the working tree.
    probe = subprocess.run(
        ["docker", "run", "--rm", a.tag, "grep", "-c", "ROUTE1-21", REL],
        capture_output=True, text=True)
    n = probe.stdout.strip() or "0"
    print(f"ROUTE1-21 occurrences inside {a.tag}: {n} (must be 0)")
    if n != "0":
        print("FATAL: the control image CONTAINS the patch — it is not a control")
        return 1
    print(f"OK: {a.tag} is a true control")
    return 0


if __name__ == "__main__":
    sys.exit(main())
