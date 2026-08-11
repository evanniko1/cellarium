"""Run the suite the way CI will, so an environment-dependent test fails HERE instead of six days later.

WHY THIS EXISTS. On 2026-08-11 the remote had been red for six days and 59 consecutive runs while every local
run was green. Both failures were invisible locally and for the same reason — this developer's machine has
things CI does not:

  * a test called DuckDB's `.df()`, which needs **pandas**. Pandas is deliberately NOT a dependency here (the
    core stays pandas- and scipy-free; they arrive only through the opt-in `fba`/`rnaseq` extras) but it is
    present in this venv because cobra pulls it in;
  * another asserted against a knowledge base under `runs/`, which is **gitignored**, so a CI checkout has no
    such tree and every row resolved to None.

Neither is a code defect and no amount of ordinary local testing would surface either. The difference is the
ENVIRONMENT, so this reproduces the two axes that differ:

  1. **PACKAGES.** CI installs `.[dev,hf,surrogate]` and nothing else. Anything reachable only through the
     `fba`/`rnaseq`/`keyvault` extras is made to raise ImportError, via a shim directory placed first on
     `PYTHONPATH`. Note `scipy` is NOT shimmed: scikit-learn pulls it, so CI genuinely has it.
  2. **FILES.** `runs/` does not exist in a checkout, so `CELLARIUM_OUT` is pointed at an empty directory.
     The manifest under `data/` IS committed and stays exactly as it is.

    python scripts/check_like_ci.py            # the full suite, CI-shaped
    python scripts/check_like_ci.py tests/test_arm2_columns.py -q    # extra args pass through to pytest

WHAT IT STILL WILL NOT CATCH: Linux-vs-Windows behaviour (path separators, case sensitivity, file locking),
the Python patch version, and anything about the runner itself. It closes the two axes that have actually
bitten, and says so rather than implying it makes CI redundant. **The authoritative check remains the CI run
after the push.**
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Present in a developer venv via the opt-in extras; absent in CI. `scipy` is deliberately NOT here —
# scikit-learn depends on it, and CI installs `surrogate`, so CI really does have scipy.
NOT_IN_CI = ["pandas", "cobra", "pydeseq2", "anndata", "keyring", "matplotlib", "optlang", "statsmodels"]


def _shim_dir(base: Path) -> Path:
    """A directory of modules that raise on import, mimicking 'not installed'."""
    d = base / "ci_shim"
    d.mkdir(parents=True, exist_ok=True)
    for mod in NOT_IN_CI:
        (d / f"{mod}.py").write_text(
            f'raise ImportError("check_like_ci: {mod!r} is not installed in CI '
            f'(it reaches this venv only through an opt-in extra)")\n',
            encoding="utf-8")
    return d


def main(argv: list[str]) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        shim = _shim_dir(base)
        empty_runs = base / "empty_runs"
        empty_runs.mkdir()

        env = dict(os.environ)
        env["PYTHONPATH"] = str(shim) + os.pathsep + env.get("PYTHONPATH", "")
        env["CELLARIUM_OUT"] = str(empty_runs)
        env.setdefault("PYTHONIOENCODING", "utf-8")

        print(f"CI-shaped run: {len(NOT_IN_CI)} package(s) shimmed to ImportError; "
              f"CELLARIUM_OUT -> an empty directory")
        print(f"  shimmed: {', '.join(NOT_IN_CI)}")
        print("  NOT shimmed: scipy (scikit-learn pulls it, so CI has it)\n")

        cmd = [sys.executable, "-m", "pytest", *(argv or [])]
        proc = subprocess.run(cmd, cwd=str(REPO), env=env)
        if proc.returncode == 0:
            print("\nCI-shaped suite passed. This closes the PACKAGE and FILE axes only — "
                  "the CI run after the push is still the authoritative check.")
        else:
            print("\nFAILED under CI-shaped conditions. This would have been a red remote run; "
                  "fix it before pushing.")
        return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
