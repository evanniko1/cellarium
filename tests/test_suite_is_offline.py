"""The test suite cannot reach a model provider: an accidental model call fails in seconds, it does not wait.

FOUND 2026-11-23 (see the guard in tests/conftest.py): the full suite hung at 18% on a live model request that a
test had let through, because the developer's ANTHROPIC_BASE_URL named an endpoint that had stopped answering.
The guard points every provider base URL at a port where nothing listens for the whole session; these tests pin
that it is in place and that a call through the real SDK fails fast against it.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conftest  # noqa: E402


def test_every_provider_base_url_points_at_a_dead_port_during_the_suite():
    for var in conftest.PROVIDER_URL_VARS:
        assert os.environ.get(var) == conftest.UNREACHABLE_PROVIDER, var


def test_an_accidental_model_call_fails_in_seconds_rather_than_waiting():
    anthropic = pytest.importorskip("anthropic")
    client = anthropic.Anthropic(api_key="sk-ant-test-not-a-real-key", max_retries=0)
    t0 = time.time()
    with pytest.raises(anthropic.APIConnectionError):
        client.messages.create(model="claude-opus-4-8", max_tokens=8,
                               messages=[{"role": "user", "content": "x"}])
    assert time.time() - t0 < 20
