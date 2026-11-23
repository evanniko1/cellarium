"""BACKLOG M-13: an engine that is down must not be reported as our worker misbehaving.

WHAT WAS WRONG, MEASURED 2026-11-20 against unmodified code. With the engine forced unreachable
(DOCKER_HOST pointed at a pipe that does not exist), `reader._run_cmd` returned

    error:      "reader worker produced no JSON"
    returncode: 1
    stderr:     "failed to connect to the docker API at npipe:////./pipe/... check if the path is correct
                 and if the daemon is running ..."

The cause was captured in stderr and nothing read it. Worse, `errors.PATTERNS` routes "produced no JSON" to
`runtime_fault`, whose remedy is `report_defect` — so the agent acting on the taxonomy was told to report a
bug in Cellarium when the fix was to start Docker. Two layers of misattribution, not one.

The same three-way distinction already existed — in `tests/conftest.py::_docker_reason`, which tells no
client, no responding engine and no image apart so the SUITE skips correctly. The production reader that
users actually hit had none of it. These cases hold the reader to the standard the test layer already met.

They do not need Docker to run. Each feeds `_run_cmd` a command whose failure shape is the one under test,
so the classification is exercised on every machine — including CI, which has no engine at all. A guard that
only runs where Docker is up would never see the down case, which is the case it exists for.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import errors, reader  # noqa: E402


def _fake_run(returncode: int, stderr: str, stdout: str = ""):
    """A subprocess.run stand-in returning one exact failure shape."""
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)
    return run


# The stderr each cause actually produces. Copied from real runs, not composed: the engine-down text is the
# Windows message observed 2026-11-20; the Linux/macOS one is the docker client's other wording for the
# same condition, and both must classify the same way.
ENGINE_DOWN_WINDOWS = ("failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; "
                       "check if the path is correct and if the daemon is running: open "
                       "//./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.")
ENGINE_DOWN_UNIX = ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                    "Is the docker daemon running?")
IMAGE_ABSENT = ("Unable to find image 'cellarium-wcm-code:latest' locally\n"
                "docker: Error response from daemon: pull access denied for cellarium-wcm-code, "
                "repository does not exist or may require 'docker login'.")


def test_an_unreachable_engine_is_named_and_not_blamed_on_the_worker(monkeypatch):
    for stderr in (ENGINE_DOWN_WINDOWS, ENGINE_DOWN_UNIX):
        monkeypatch.setattr(reader.subprocess, "run", _fake_run(1, stderr))
        r = reader._run_cmd(["docker", "run", "x"], None)
        assert "produced no JSON" not in r["error"], (
            f"an engine that is down was reported as our worker producing no JSON: {r['error']!r}")
        assert "engine" in r["error"].lower() and "not" in r["error"].lower()
        assert r["cause"] == "engine_unavailable"


def test_the_taxonomy_tells_the_agent_to_start_the_engine_not_to_report_a_defect(monkeypatch):
    """The second layer. Before the fix `errors.PATTERNS` sent "produced no JSON" to `runtime_fault`, whose
    remedy is `report_defect` — so even a correct message would have been acted on as a code bug."""
    monkeypatch.setattr(reader.subprocess, "run", _fake_run(1, ENGINE_DOWN_WINDOWS))
    r = reader._run_cmd(["docker", "run", "x"], None)
    reason = errors.classify(r["error"]) if hasattr(errors, "classify") else _first_reason(r["error"])
    assert reason == "engine_unavailable", f"classified as {reason!r}"
    assert errors.REASONS["engine_unavailable"] == ("environment", "start_the_engine")


def test_a_missing_image_is_a_missing_artifact_not_a_worker_fault(monkeypatch):
    monkeypatch.setattr(reader.subprocess, "run", _fake_run(125, IMAGE_ABSENT))
    r = reader._run_cmd(["docker", "run", "x"], None)
    assert r["cause"] == "image_absent"
    assert "produced no JSON" not in r["error"]
    assert _first_reason(r["error"]) == "missing_artifact"


def test_a_missing_client_is_a_missing_dependency(monkeypatch):
    def run(cmd, **kw):
        raise FileNotFoundError(2, "No such file or directory", "docker")
    monkeypatch.setattr(reader.subprocess, "run", run)
    r = reader._run_cmd(["docker", "run", "x"], None)
    assert r["cause"] == "client_missing"
    assert _first_reason(r["error"]) == "missing_dependency"


def test_a_worker_that_genuinely_ran_and_printed_nothing_keeps_the_original_verdict(monkeypatch):
    """THE OTHER DIRECTION, and the one that keeps this honest. A container that started, ran the worker,
    and exited without a JSON line IS our fault — that must stay a runtime fault. A fix that reclassified
    every failure as an environment problem would hide real defects behind "start Docker"."""
    monkeypatch.setattr(reader.subprocess, "run",
                        _fake_run(1, "Traceback (most recent call last):\n  ...\nKeyError: 'simOut'"))
    r = reader._run_cmd(["docker", "run", "x"], None)
    assert r["error"] == "reader worker produced no JSON"
    assert r["cause"] == "worker_fault"
    assert _first_reason(r["error"]) == "runtime_fault"


def test_a_stalled_engine_cannot_hang_the_reader(monkeypatch):
    """Found while validating M-13: `_run_cmd` called subprocess.run with NO timeout, so a starting or
    stalled engine blocked the reader indefinitely — observed 2026-11-20, when a reproduction hung for the
    full two minutes the shell allowed while Docker Desktop came up. A bound turns a hang into an answer."""
    def run(cmd, **kw):
        assert kw.get("timeout"), "subprocess.run was called with no timeout"
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(reader.subprocess, "run", run)
    r = reader._run_cmd(["docker", "run", "x"], None)
    assert r["cause"] == "timed_out"
    assert "did not finish" in r["error"]


def test_a_successful_worker_is_unaffected(monkeypatch):
    monkeypatch.setattr(reader.subprocess, "run",
                        _fake_run(0, "", stdout='log line\nCELLARIUM_JSON:{"ok": 1}\n'))
    assert reader._run_cmd(["docker", "run", "x"], None) == {"ok": 1}


def _first_reason(msg: str) -> str | None:
    for pat, reason in errors.PATTERNS:
        if pat.search(msg):
            return reason
    return None


@pytest.mark.parametrize("stderr,cause", [
    (ENGINE_DOWN_WINDOWS, "engine_unavailable"),
    (ENGINE_DOWN_UNIX, "engine_unavailable"),
    (IMAGE_ABSENT, "image_absent"),
    ("KeyError: 'simOut'", "worker_fault"),
    ("", "worker_fault"),
])
def test_the_classifier_alone(stderr, cause):
    assert reader._classify_docker_failure(stderr) == cause
