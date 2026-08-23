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

import pytest

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

# ------------------------------------------------------------------------------------------------------------
# NO TEST MAY EVER TOUCH THE REAL CREDENTIAL SLOT.
#
# MEASURED 2026-08-23, after the developer's stored key vanished twice and expiry was (reasonably) suspected:
# running `pytest tests/test_credentials.py` DELETES it. The path is exact and traced:
#
#     TestClient POST /api/settings_key_delete
#       -> apps/server.py:611   lambda: {"key": credentials.clear()}
#       -> credentials.py:224   keyring.delete_password(SERVICE, ACCOUNT)
#
# and `SERVICE`/`ACCOUNT` are the production constants, so the call lands on the user's own Windows Credential
# Manager entry. Nothing about this is accidental in `clear()`: it deliberately deletes REGARDLESS of the
# backend verdict, because "Remove reported success while the credential quietly survived" is the worse bug.
# The file's autouse fixture stubs `backend()`, which is why this was invisible — stubbing the verdict does
# not stop a delete that ignores the verdict, and the endpoint tests never stubbed `sys.modules["keyring"]`
# at all.
#
# So the guard belongs HERE, at session scope, not in one file: it redirects the SERVICE namespace itself, so
# every path — direct call, HTTP handler, worker thread — writes and deletes somewhere disposable. A test that
# wants the real vault must opt in explicitly (see tests/test_credentials.py's `scratch_service`, which sets
# its own namespace on top of this one).
#
# This is also the answer to "did the key expire?". A credential store holds an opaque blob and has no notion
# of an API key's validity window; Anthropic revoking a key cannot reach into Windows Credential Manager. An
# expired key explains a 401, never a missing entry.
# ------------------------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def _never_touch_the_real_keychain():
    import uuid

    try:
        from cellarium import credentials
    except Exception:
        yield                       # nothing importable to protect
        return
    scratch = f"cellarium-pytest-{uuid.uuid4().hex[:12]}"
    real_service, real_account = credentials.SERVICE, credentials.ACCOUNT
    credentials.SERVICE = scratch
    try:
        yield
    finally:
        credentials.SERVICE = real_service
        try:
            import keyring
            keyring.delete_password(scratch, real_account)
        except Exception:
            pass
