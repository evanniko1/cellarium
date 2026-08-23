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
