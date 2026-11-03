"""Two checks CI *can* run for a defect class CI otherwise cannot see.

THE STRUCTURAL PROBLEM. Two of the last five review failures were skip-guards that read a different object
from the code they guarded. Neither was reachable in CI, and not by accident: CI has no model image, so
every one of those guards skips on every run. The failure only appears where the image IS configured — a
developer machine, running the whole suite. A green CI is therefore silent about the entire class, and
adding another CI job does not help, because the job would skip too.

What CI *can* do is check the two things that need no image:

  (a) `test_no_guard_reads_a_different_object_than_the_code_it_guards` — a static scan
      (`scripts/check_env_guards.py`). Frozen module constants and the tests that guard on the environment
      instead are both visible in the source.
  (b) `test_the_ci_skip_census_matches_the_committed_baseline` — the SKIP CENSUS. A skip is invisible today:
      a test that always skips in CI looks exactly like a test that passes. Recording which tests skip, and
      diffing that against a committed list, turns "this is never exercised here" into a fact CI can report.
      A test that starts skipping — because a guard broke, an import moved, or a fixture changed — becomes a
      visible change rather than a silent loss of coverage.

`data/CI_SKIPS.json` holds the baseline. It is a LEDGER, not a target: growing it is allowed, and doing so
knowingly is the whole point.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CENSUS = REPO / "data" / "CI_SKIPS.json"


def test_no_guard_reads_a_different_object_than_the_code_it_guards():
    """The static half. Fails on a new divergence, with the file and line."""
    sys.path.insert(0, str(REPO / "scripts"))
    import check_env_guards as chk

    res = chk.scan()
    assert not res["divergences"], "\n".join(
        f"{d['file']}:{d['line']} guards on os.environ[{d['var']}] but the code it reaches reads "
        f"{', '.join(d['frozen_in'])}" for d in res["divergences"])


def test_the_scan_would_notice_a_new_frozen_constant():
    """INJECTION for (a). Without this, the scan could return an empty divergence list because it found no
    constants at all — a pass that means "I looked at nothing", which is the shape this repo keeps
    re-learning to distrust."""
    sys.path.insert(0, str(REPO / "scripts"))
    import check_env_guards as chk

    frozen = chk._module_env_constants()
    assert "WCECOLI_DOCKER" in frozen, "the scan sees no module-level env constants — it is not reading src/"
    assert any(m == "runner" for m, _ in frozen["WCECOLI_DOCKER"])


@pytest.mark.skipif(not CENSUS.is_file(), reason="no committed skip census yet")
def test_the_ci_skip_census_matches_the_committed_baseline():
    """The census half.

    Deliberately compares the SET of gated FILES, not per-test skip results: per-test skips depend on the
    machine (image present or not), and a check that failed on a developer machine for being better
    configured than CI would be switched off within a week. What is stable, and what actually broke twice, is
    WHICH FILES gate themselves on the model environment.

    It counts both spellings — `os.environ["WCECOLI_*"]` and `reader/runner.WCECOLI_*` — because fixing a
    guard to read the module constant removes a divergence without changing what CI executes. Built from
    divergences alone, this census would have reported the blind spot shrinking at the moment the guards were
    corrected. It did, on the first run, and that is why `gated_files` exists separately.
    """
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    sys.path.insert(0, str(REPO / "scripts"))
    import check_env_guards as chk

    live = sorted(chk.gated_files())
    recorded = sorted(census["files_gated_on_the_model_environment"])
    added = sorted(set(live) - set(recorded))
    removed = sorted(set(recorded) - set(live))
    assert not added and not removed, (
        f"the set of test files gating on the model environment changed.\n"
        f"  newly gated (these tests are now invisible to CI): {added}\n"
        f"  no longer gated: {removed}\n"
        f"Update data/CI_SKIPS.json deliberately — it is a ledger of what CI does not exercise, and it is "
        f"allowed to grow, but not by accident.")


def test_the_census_records_why_ci_cannot_see_this_class():
    """The census is only useful if it says what it is FOR. A bare list of filenames is a file nobody reads."""
    if not CENSUS.is_file():
        pytest.skip("no committed skip census yet")
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    assert census.get("why"), "the census does not say why it exists"
    assert "model image" in census["why"] or "WCECOLI" in census["why"]


def test_every_test_module_imports_WITHOUT_another_module_having_moved_sys_path():
    """A test module's importability must be a property of the tree, not of collection order.

    MEASURED 2026-11-01: of the test modules that import `cellarium`, 31 carried no `sys.path.insert` of
    their own and passed only because some earlier-imported module had already mutated `sys.path`. Run one
    alone and it failed with `ModuleNotFoundError: No module named 'cellarium'` on a checkout where
    cellarium is plainly present -- this repository's own silent-absence defect wearing an import error's
    clothes, and a message that sends a reader to install a package they already have. `conftest.py` now
    appends `src/` once for everybody, and this is the check that keeps it there.

    WHY A SUBPROCESS, and why only one. The defect is invisible in-process: by the time this test runs,
    `sys.path` has been mutated many times over and every module imports fine. The only way to observe it
    is a fresh interpreter collecting ONE module. Collecting all 31 that way would cost 31 interpreter
    starts for a property one witness establishes, so this picks the module that actually cost a detour --
    and asserts the WITNESS still lacks its own insert, because if somebody adds one the test would go on
    passing while measuring nothing.

    `--collect-only` is enough: the failure was at import, so collection either reaches the tests or does
    not."""
    import subprocess

    witness = REPO / "tests" / "test_openai_compat.py"
    assert witness.is_file(), f"{witness.name} is gone; pick another module with no sys.path insert of its own"
    text = witness.read_text(encoding="utf-8")
    assert "sys.path.insert" not in text, (
        f"{witness.name} now inserts src itself, so it no longer witnesses anything. Point this test at a "
        "module that does not -- `_bare_modules()` below lists them.")
    assert "from cellarium" in text or "import cellarium" in text, (
        f"{witness.name} no longer imports cellarium and cannot witness the path at all")

    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                        str(witness)], capture_output=True, text=True, cwd=str(REPO))
    out = r.stdout + r.stderr
    # THE CRITERION IS THE IMPORT, not the exit code. An earlier version asserted `returncode == 0`, and a
    # one-off sweep over all 31 modules then reported `test_mcp_server_wire.py` as a failure -- it is not.
    # That module carries a module-level `pytest.importorskip("mcp")` for an optional extra, collects zero
    # tests, and pytest exits 5 ("no tests collected"), which it does inside the full suite too. The exit
    # code was a proxy for "could it import cellarium" and answered a different question. Measured with the
    # right criterion: 31 of 31 import cleanly -- 30 collecting tests, 1 skipping wholesale.
    assert "No module named 'cellarium'" not in out, (
        f"{witness.name} cannot import cellarium on its own. conftest.py is supposed to put src/ on the "
        f"path for every module; without it a reader running one test file gets 'No module named "
        f"cellarium' on a tree that plainly has it. Tail of the run: {out[-900:]}")
    assert r.returncode in (0, 5), (
        f"{witness.name} failed to collect for a reason other than a missing import (exit "
        f"{r.returncode}). Tail: {out[-900:]}")


def _bare_modules() -> list[str]:
    """Test modules that import `cellarium` and do NOT put src on the path themselves."""
    out = []
    for f in sorted((REPO / "tests").glob("test_*.py")):
        t = f.read_text(encoding="utf-8", errors="replace")
        if "sys.path.insert" not in t and ("from cellarium" in t or "import cellarium" in t):
            out.append(f.name)
    return out


def test_the_count_of_modules_relying_on_conftest_is_recorded_not_discovered():
    """How many modules depend on conftest for their path, recorded so the number is a fact rather than an
    impression. It may move in either direction -- a new module without an insert, or one gaining its own --
    and either is fine; what is not fine is nobody knowing. The figure was arrived at by counting, after a
    first pass subtracted 89 from 133 and said 44, which counted modules that import no cellarium at all."""
    bare = _bare_modules()
    assert bare, (
        "no module relies on conftest for its path any more. That is a real improvement rather than a "
        "failure -- update the count here and in conftest's docstring, and retarget the witness above")
    assert len(bare) == 32, (
        f"{len(bare)} test modules now rely on conftest for their path, not 32:\n  "
        + "\n  ".join(bare)
        + "\nUpdate the count here and in conftest._put_src_on_the_path's docstring")
