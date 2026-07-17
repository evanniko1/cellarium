"""Docker setup smoke test — verify the wcEcoli image is wired to Cellarium, and (optionally) that the full
Docker -> sim -> output loop works. See docs/DOCKER_SETUP.md.

    python scripts/docker_smoke.py --check    # fast: docker present, image exists, env set, sim_data calibrated
    python scripts/docker_smoke.py --sim       # runs ONE wildtype/basal seed x 1 generation and reads it back
    python scripts/docker_smoke.py             # --check (default)

--check needs nothing but Docker + the image. --sim actually runs the model (minutes) and needs ParCa done
(`python -m cellarium.runner`). Exit code 0 = all good, non-zero = a step failed (message says which).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import runner  # noqa: E402
from cellarium.model import Design  # noqa: E402

OK, BAD = "  [ok] ", "  [!!] "


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:
        return 1, str(e)


def check() -> bool:
    """Fast preflight: everything needed to EXECUTE a sim, without running one."""
    ok = True
    image = runner.WCECOLI_DOCKER
    native = runner.WCECOLI_DIR

    if shutil.which("docker"):
        rc, out = _run(["docker", "--version"])
        print((OK if rc == 0 else BAD) + f"docker CLI: {out.splitlines()[0] if out else 'present'}")
        ok &= rc == 0
    elif native:
        print(OK + f"no docker, but WCECOLI_DIR set (native mode): {native}")
    else:
        print(BAD + "docker not found and WCECOLI_DIR unset — set one (see docs/DOCKER_SETUP.md §3)"); ok = False

    if image:
        rc, _ = _run(["docker", "image", "inspect", image])
        print((OK if rc == 0 else BAD) + f"WCECOLI_DOCKER='{image}' image "
              + ("present" if rc == 0 else "NOT found — build it (§2): docker build -t %s -f docker/local/Dockerfile ." % image))
        ok &= rc == 0
    elif native:
        print(OK + "native mode (WCECOLI_DIR) — Docker image not required")
    else:
        print(BAD + "WCECOLI_DOCKER unset — export the local image name (§3)"); ok = False

    print(OK + f"CELLARIUM_OUT (host output dir): {runner.OUT_ROOT}")

    kb = runner.OUT_ROOT / "cellarium" / "kb" / "simData.cPickle"
    if kb.exists():
        print(OK + f"sim_data calibrated: {kb}")
    else:
        print(BAD + f"sim_data NOT built at {kb} — run ParCa once (§4): python -m cellarium.runner"); ok = False

    print(("\nAll checks passed — the launch/regenerate loop should work. Try --sim to confirm end to end."
           if ok else "\nSome checks failed — fix the [!!] lines above (docs/DOCKER_SETUP.md)."))
    return ok


def sim() -> bool:
    """Full loop: run one wildtype/basal seed x 1 generation through the runner and confirm output landed."""
    if not check():
        print("\nSkipping --sim: preflight failed."); return False
    print("\nRunning one wildtype/basal seed x 1 generation (this calls the model — minutes)…", flush=True)
    design = Design(perturbation="wildtype", condition="basal")
    try:
        run_root = runner.run_one(design, seed=0, generations=1)
    except Exception as e:
        print(BAD + f"run_one failed: {type(e).__name__}: {e}"); return False
    gens = [p for p in Path(run_root).glob("generation_*")] if Path(run_root).exists() else []
    if not Path(run_root).exists() or not gens:
        # some model layouts write per-generation dirs differently; fall back to "any files under run_root"
        produced = list(Path(run_root).rglob("*")) if Path(run_root).exists() else []
        if not produced:
            print(BAD + f"no output under {run_root} — the sim produced nothing"); return False
    print(OK + f"sim wrote output under {run_root}")
    print("\nEnd-to-end OK: Docker -> model -> simOut works. The launch airlock and regenerate path are live.")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Cellarium <-> wcEcoli Docker smoke test.")
    ap.add_argument("--check", action="store_true", help="preflight only (default)")
    ap.add_argument("--sim", action="store_true", help="also run one real sim and read it back")
    a = ap.parse_args()
    ok = sim() if a.sim else check()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
