"""A Docker engine that is up but not answering must never hang Cellarium or its test suite.

FOUND 2026-11-21. The full suite sat for seventeen hours on one child process, `docker image inspect
python:3.12-slim`, started at COLLECTION time by a `skipif` in tests/test_failures.py while Docker Desktop was
running but answering nothing. Five CPU-seconds in seventeen hours: no test had run, none had failed, nothing
reported anything. That engine state is also exactly when a production call hangs, and two production calls had
no bound either -- one of them inside the wall-clock kill that exists to stop hung runs, where an unanswered
`docker kill` held the timer thread so the client process was never killed.

The static scan below sees calls to subprocess.run / check_output / check_call / call whose first argument is a
list or tuple LITERAL beginning with "docker". It does NOT see, and these are declared limits rather than
passes: an argv built in a variable (`reader._run_cmd`, `runner._exec`), bounded by its caller and covered by
tests/test_reader_engine_faults.py and tests/test_failures.py; and `Popen`, which takes no timeout and is
bounded by the wall-clock timer.

The behavioural tests use a fake engine that answers a BOUNDED call with TimeoutExpired -- the bound firing --
and an UNBOUNDED one by blocking. So the unfixed code is red on elapsed time and on what it reports.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))      # self-sufficient, as tests/test_reader_engine_faults.py is
SCANNED = ("src", "tests", "apps", "scripts", "evals")
_SUBPROCESS_API = {"run", "check_output", "check_call", "call"}
_BLOCK_S = 20          # how long the fake engine blocks an unbounded call
_FAST_S = 12           # a bounded call must come back well inside the block


def _docker_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name not in _SUBPROCESS_API:
            continue
        a0 = node.args[0]
        if (isinstance(a0, (ast.List, ast.Tuple)) and a0.elts and isinstance(a0.elts[0], ast.Constant)
                and a0.elts[0].value == "docker"):
            yield node


def _unbounded(tree: ast.AST) -> list[int]:
    return [n.lineno for n in _docker_calls(tree) if not any(k.arg == "timeout" for k in n.keywords)]


def _scan() -> tuple[int, list[str]]:
    n, bad = 0, []
    for base in SCANNED:
        for f in sorted((REPO / base).rglob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            n += sum(1 for _ in _docker_calls(tree))
            bad += [f"{f.relative_to(REPO).as_posix()}:{ln}" for ln in _unbounded(tree)]
    return n, bad


def test_the_scan_flags_an_unbounded_call_and_passes_a_bounded_one():
    """The positive control: a scan that matched nothing would pass every tree, including the one that hung."""
    assert _unbounded(ast.parse('subprocess.run(["docker", "image", "inspect", "x"], capture_output=True)')) == [1]
    assert _unbounded(ast.parse('subprocess.run(["docker", "kill", c], capture_output=True, timeout=60)')) == []
    assert _unbounded(ast.parse('subprocess.run(["git", "status"])')) == []


def test_every_literal_docker_call_has_a_timeout():
    n, bad = _scan()
    assert n >= 10, f"the scan found only {n} docker calls -- it is looking in the wrong place"
    assert bad == [], ("docker calls with no timeout; a stalled engine holds each one forever:\n  "
                       + "\n  ".join(bad))


def _stalled_engine(real_run, verbs: tuple[str, ...]):
    def fake(cmd, *a, **kw):
        if isinstance(cmd, (list, tuple)) and len(cmd) > 1 and cmd[0] == "docker" and cmd[1] in verbs:
            if "timeout" in kw:
                raise subprocess.TimeoutExpired(cmd, kw["timeout"])
            time.sleep(_BLOCK_S)                     # unbounded: the engine never answers
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if isinstance(cmd, (list, tuple)) and cmd[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(cmd, 0, "27.0\n", "")
        return real_run(cmd, *a, **kw)
    return fake


def test_a_stalled_engine_cannot_hold_the_wall_clock_kill_open(tmp_path, monkeypatch):
    """The limit kills the container, then the client. An unbounded `docker kill` against a silent engine held
    the timer thread, so the client was never killed and the limit failed in exactly the state where runs
    hang. The log must also say the container kill was not confirmed, because the container may outlive it."""
    from cellarium import failures as F
    from cellarium import runner

    monkeypatch.setattr(runner.subprocess, "run", _stalled_engine(subprocess.run, ("kill",)))
    script = "import time\nprint('started', flush=True)\ntime.sleep(60)\n"
    log = tmp_path / F.SIM_LOG
    t0 = time.time()
    with pytest.raises(TimeoutError):
        runner._run_checked([sys.executable, "-c", script], None, log, wall_limit_s=1.5,
                            container="cellarium-stalled")
    assert time.time() - t0 < _FAST_S
    text = log.read_text(encoding="utf-8")
    assert F.WALL_MARK in text
    assert "cellarium-stalled" in text and "may still be running" in text


def test_a_stalled_engine_fails_a_flat_file_read_instead_of_hanging_it(monkeypatch):
    """And the failure names the engine, not the knowledge base: reading one small file cannot legitimately
    take minutes, so unlike the reader's timeout this one IS attributable, and the agent is told to start the
    engine rather than to report a defect (the M-13 misattribution, in a second place)."""
    from cellarium import errors, runner

    monkeypatch.setattr(runner, "WCECOLI_DOCKER", "wcecoli-sim:stalled")
    monkeypatch.setattr(runner.subprocess, "run", _stalled_engine(subprocess.run, ("run",)))
    t0 = time.time()
    with pytest.raises(RuntimeError, match="did not answer") as exc:
        runner.read_flat_file("rnas.tsv")
    assert time.time() - t0 < _FAST_S
    assert errors.classify(str(exc.value)) == "engine_unavailable"


def test_the_suites_image_probe_skips_with_a_reason_rather_than_hanging(monkeypatch):
    """conftest's probe bounded `docker version` but not the `docker image inspect` after it, so an engine that
    answered the first and then stalled held the whole session. It must come back with a skip REASON."""
    import shutil

    import conftest

    from src.cellarium import runner as src_runner

    monkeypatch.setattr(src_runner, "WCECOLI_DOCKER", "wcecoli-sim:stalled")
    monkeypatch.setattr(shutil, "which", lambda name: "docker")
    monkeypatch.setattr(subprocess, "run", _stalled_engine(subprocess.run, ("image",)))
    t0 = time.time()
    why = conftest._docker_reason.__wrapped__()
    assert time.time() - t0 < _FAST_S
    assert "did not answer" in why and "wcecoli-sim:stalled" in why
