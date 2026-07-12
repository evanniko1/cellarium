"""Agent rate-limit contract.

Main handles Anthropic rate limits (and transient 5xx) via the SDK's own retry: it constructs the client with
`anthropic.Anthropic(max_retries=...)`, which does exponential backoff, and lets a terminal failure propagate to
the caller (the server surfaces a hint). This test guards that contract — that the retry config isn't silently
dropped in a refactor.

(Adapted from the fix-anthropic-rate-limit-handling branch, which asserted an older, hand-rolled contract where
the agent CAUGHT the error and returned a friendly "rate limit / retry" string. Main doesn't do that — the SDK
retries and the exception propagates — so the assertion is rewritten to main's actual behavior.)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import agent  # noqa: E402


def test_converse_configures_sdk_retry_backoff(monkeypatch):
    """The Anthropic client must be built with max_retries so 429/5xx get exponential backoff."""
    captured = {}

    class _StopBeforeAPICall(Exception):
        pass

    def _fake_anthropic(**kwargs):
        captured.update(kwargs)          # we only care about the construction kwargs
        raise _StopBeforeAPICall()        # stop before any real network call

    monkeypatch.setattr(agent.anthropic, "Anthropic", _fake_anthropic)

    with pytest.raises(_StopBeforeAPICall):
        agent.converse([{"role": "user", "content": "hi"}], model="claude-haiku-4-5-20251001")

    assert captured.get("max_retries", 0) >= 1, \
        "converse must construct anthropic.Anthropic(max_retries=...) for 429/5xx backoff"
