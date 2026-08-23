"""Load `.env` BEFORE anything freezes its environment. This file exists to close one measured defect class.

WHAT WENT WRONG WITHOUT IT. `reader.py:18` and `runner.py:27` capture their configuration at import:

    WCECOLI_DOCKER = os.environ.get("WCECOLI_DOCKER", "")

Nothing in the suite loaded `.env`, so those constants froze empty — until some test imported
`apps/server.py`, which calls `load_dotenv()` and fills the variable in AFTER the freeze. From that point the
environment and the constants disagreed, and every test that guarded on `os.environ` skipped or ran on the
wrong side of its own gate. `tests/test_parca_rebuild.py` passed alone and raised in the full suite; the
cause belonged to neither test and depended only on collection order.

Loading here removes the divergence at the source: pytest imports conftest before any test module, this file
imports nothing from `cellarium`, so the environment is complete before the first constant is read.

FOUR PROPERTIES THAT MATTER:

  * **Never overrides an exported value.** `override=False` matches `apps/server.py`, so a variable set on
    the command line still wins and a deliberate `WCECOLI_DOCKER= pytest` still means "no image".
  * **Silent when there is nothing to load.** CI has no `.env` and no `python-dotenv` guarantee; both are
    ordinary states here, not failures.
  * **It does not make the guards CORRECT, only consistent.** A guard reading `os.environ` while the code
    reads a frozen constant is still the wrong object — a monkeypatch inside a test re-opens the gap.
    `scripts/check_env_guards.py` is what keeps that from coming back.
  * **It changes what the suite MEASURES on a developer machine**, since tests that skipped without the
    image now run. That is the point: those are the tests the model image exists for, and the two defects
    this closed were both found by running them.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_env_before_anything_freezes_it() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:                      # python-dotenv absent: the environment is whatever was exported
        return
    env = REPO / ".env"
    if env.is_file():
        load_dotenv(env, override=False)


_load_env_before_anything_freezes_it()

# Read AFTER the load, so a reporter or a later fixture sees the same value the modules will freeze.
CONFIGURED_IMAGE = os.environ.get("WCECOLI_DOCKER", "")
CONFIGURED_CHECKOUT = os.environ.get("WCECOLI_DIR", "")
