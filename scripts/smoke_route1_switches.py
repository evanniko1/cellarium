"""Smoke-test the ROUTE1 switch plumbing: does a simulation still start, and is the choice recorded?

WHY THIS EXISTS. The plumbing adds two names to `SIM_KEYS` in scriptBase.py, and `data.select_keys`
looks those up with `mapping[key]` and NO default. A name present in one list and missing from the
other therefore raises `KeyError` on EVERY simulation invocation, not just isoacceptor ones — the
plumbing is a no-op by design, so nothing else would reveal the break. Static checks cannot catch it;
only starting a simulation can.

It also checks the other half of the point: that the selected values reach `metadata.json`. A switch
that runs but is not recorded leaves a corpus whose runs cannot be told apart afterwards.

WHAT IT RUNS. Two short simulations against an existing ParCa output (ParCa is NOT rebuilt — the
plumbing does not touch reconstruction):

  1. defaults                          -> must start, and record family / abundance
  2. --trna-demand-split equal         -> must start, and record the CHANGED value

and one negative case:

  3. --trna-demand-split nonsense      -> must FAIL, with the ValueError naming the allowed values

Case 3 is the load-bearing one. A validation that never rejects anything is indistinguishable from no
validation, and this switch's whole purpose is that a typo stops the run instead of silently
producing a mislabelled campaign.

    python scripts/smoke_route1_switches.py [--image wcecoli-sim:route1plumb] [--skip-build]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

WC = os.environ.get("WCECOLI", r"C:/dev/wcEcoli")
PARCA = "out/kinetic_parca"


def _docker_run(image: str, args: list[str]) -> subprocess.CompletedProcess:
    # -w /wcEcoli is passed via a list, not a shell string: Git Bash rewrites bare /wcEcoli into a
    # Windows path when it reaches a shell, which silently changes the working directory inside the
    # container. Passing argv directly avoids the shell entirely.
    cmd = ["docker", "run", "--rm",
           "-v", f"{WC}/out:/wcEcoli/out",
           "-e", "PYTHONPATH=/wcEcoli",
           "-w", "/wcEcoli", image] + args
    return subprocess.run(cmd, capture_output=True, text=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--image", default="wcecoli-sim:route1plumb")
    ap.add_argument("--dockerfile", default="docker/local/Dockerfile")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--length-sec", default="20")
    a = ap.parse_args(argv)

    if not a.skip_build:
        print(f"building {a.image} ...")
        b = subprocess.run(["docker", "build", "-f", a.dockerfile, "-t", a.image, "."],
                           cwd=WC, capture_output=True, text=True)
        print(f"build rc={b.returncode}")
        if b.returncode != 0:
            print("\n".join((b.stdout + b.stderr).splitlines()[-15:]))
            return 1

    # Prove the plumbing is actually inside the image rather than only in the working tree.
    probe = _docker_run(a.image, ["grep", "-c", "trna_demand_split",
                                  "wholecell/utils/scriptBase.py"])
    n = probe.stdout.strip()
    print(f"trna_demand_split occurrences in image scriptBase.py: {n} (expect 3)")
    if n != "3":
        print("FATAL: the image does not carry the plumbing")
        return 1

    # runSim.py consumes an EXISTING ParCa output directory: it looks for <sim_dir>/kb/simData.cPickle
    # and refuses a bare new name. Each case therefore gets its own sim_dir whose kb is HARDLINKED
    # from the reference ParCa — same inode, so the pickle is byte-identical by construction, no
    # 90 MB copy per case, and the reference tree is never written to.
    def _prepare(out_dir: str) -> str | None:
        # BOTH kb dirs are needed: <sim_dir>/kb/simData.cPickle AND
        # <sim_dir>/wildtype_000000/kb/simData_Modified.cPickle, the per-variant pickle that
        # makeVariants would normally produce. Linking only the first lets runSim start, write
        # metadata, and exit 0 while every variant fails — which is exactly how the first version of
        # this smoke reported two false passes.
        for rel in ("kb", os.path.join("wildtype_000000", "kb")):
            src = os.path.join(WC, PARCA, rel)
            dst = os.path.join(WC, out_dir, rel)
            if not os.path.isdir(src):
                return f"reference ParCa dir not found at {src}"
            os.makedirs(dst, exist_ok=True)
            for name in os.listdir(src):
                s, d = os.path.join(src, name), os.path.join(dst, name)
                if os.path.exists(d) or not os.path.isfile(s):
                    continue
                try:
                    os.link(s, d)
                except OSError:
                    import shutil
                    shutil.copy2(s, d)
        return None

    def _really_ran(out_dir: str, blob: str) -> str | None:
        """rc == 0 is NOT evidence a simulation ran: runSim reports failed variants and still
        exits 0. Require positive evidence — a simOut directory with listener output — and treat
        the failed-variant banner as a failure regardless of exit code."""
        if "variant(s) failed" in blob:
            return "runSim reported failed variants despite exit 0"
        hits = []
        for root, dirs, files in os.walk(os.path.join(WC, out_dir)):
            if os.path.basename(root) == "simOut" and files:
                hits.append(root)
        if not hits:
            return "no non-empty simOut directory was produced"
        return None

    failures = []

    cases = [
        ("defaults", [], "family", "abundance", True),
        ("equal split", ["--trna-demand-split", "equal"], "family", "equal", True),
        ("bad value", ["--trna-demand-split", "nonsense"], None, None, False),
    ]
    for label, extra, want_res, want_split, want_ok in cases:
        out_dir = "out/smoke_" + label.replace(" ", "_")
        why = _prepare(out_dir)
        if why:
            print(f"[{label}] SETUP FAILED: {why}")
            failures.append(f"{label}: {why}")
            continue
        args = ["python", "runscripts/manual/runSim.py", out_dir,
                "--require-variants", "--length-sec", a.length_sec] + extra
        r = _docker_run(a.image, args)
        blob = r.stdout + r.stderr
        # "Did it work" is rc == 0 AND positive evidence of a simulation, never rc alone.
        ran_problem = _really_ran(out_dir, blob)
        ok = r.returncode == 0 and ran_problem is None
        print(f"\n[{label}] rc={r.returncode} ran_ok={ok}"
              f"{'' if ran_problem is None else ' (' + ran_problem + ')'}"
              f" (expected {'ran' if want_ok else 'rejected'})")
        if ok != want_ok:
            tail = "\n".join((r.stdout + r.stderr).splitlines()[-12:])
            print(tail)
            failures.append(f"{label}: rc={r.returncode}, expected {'0' if want_ok else 'nonzero'}")
            continue

        if not want_ok:
            # The negative case must fail for the RIGHT reason. A run that dies of a typo in the
            # output path would satisfy "rejected" while telling us nothing about the validation.
            if "trna_demand_split must be one of" not in blob:
                failures.append(f"{label}: failed, but not with the validation ValueError")
                print("  FAIL: rejected for the wrong reason")
            else:
                print("  OK: rejected by the validation, with the allowed values named")
            continue

        meta = os.path.join(WC, out_dir, "metadata", "metadata.json")
        if not os.path.isfile(meta):
            failures.append(f"{label}: no metadata.json at {meta}")
            print(f"  FAIL: no metadata.json at {meta}")
            continue
        with open(meta) as fh:
            m = json.load(fh)
        got_res = m.get("trna_charging_resolution")
        got_split = m.get("trna_demand_split")
        print(f"  metadata: trna_charging_resolution={got_res!r} trna_demand_split={got_split!r}")
        if got_res != want_res or got_split != want_split:
            failures.append(f"{label}: metadata {got_res!r}/{got_split!r}, expected "
                            f"{want_res!r}/{want_split!r}")
            print("  FAIL: metadata does not record the selected values")
        else:
            print("  OK: started and recorded the selection")

    print("\n" + ("SMOKE PASSED" if not failures else "SMOKE FAILED"))
    for f in failures:
        print(f"  - {f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
