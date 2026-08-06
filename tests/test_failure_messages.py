"""A campaign failure must never report nothing.

MEASURED 2026-08-06: sixteen graded-knockout jobs printed "FAILED:" with an empty string after the colon,
because `print(f"FAILED: {exc}")` renders as nothing when str(exc) is empty. The real cause — a run root with
no fitted simData.cPickle — only surfaced when one design was re-run outside the campaign, costing a launch
cycle. An error that reports nothing is indistinguishable from an error that reports a reason, which is the
silent-absence failure this project keeps re-encountering.
"""
import subprocess

import pytest

from src.cellarium.manifest import _exc_text


def test_empty_message_still_names_the_exception():
    for exc in (ValueError(), RuntimeError(""), OSError(), KeyError()):
        text = _exc_text(exc)
        assert text.strip(), f"{type(exc).__name__} produced an empty failure message"
        assert type(exc).__name__ in text, f"{text!r} does not name the exception type"


def test_message_is_kept_when_present():
    assert "no fitted knowledge base" in _exc_text(FileNotFoundError("no fitted knowledge base"))


def test_subprocess_stderr_is_surfaced():
    """CalledProcessError carries the child's real message on .stderr, not in str()."""
    exc = subprocess.CalledProcessError(1, ["runSim.py"], output=b"", stderr=b"Missing file simData.cPickle")
    text = _exc_text(exc)
    assert "simData.cPickle" in text, f"the child's stderr was dropped: {text!r}"


def test_traceback_location_is_included():
    try:
        raise RuntimeError()
    except RuntimeError as exc:
        text = _exc_text(exc)
    assert "test_failure_messages.py:" in text, f"no source location in {text!r}"


def test_respects_the_length_limit():
    assert len(_exc_text(ValueError("x" * 5000), limit=120)) <= 120
