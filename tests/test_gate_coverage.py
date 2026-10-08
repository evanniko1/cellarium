"""Every surface that drives the agent must pass the capability gate first — enumerated, not asserted.

THE FAILURE THIS EXISTS FOR, and it is not hypothetical. The pre-dispatch gate shipped on 2026-10-08 inside
`orchestrate.investigate`, and the claim written down was that every entry point reached it. Two of four did.
`apps/server.py` — the web application, the surface most users meet — called `council.deliberate` and built
`agent` messages itself, so it never touched the seam and never touched the gate. Two docstrings in the
package asserted otherwise. The gate was correct, well tested, and absent from the path that mattered most.

WHY `tests/test_gate.py` COULD NOT CATCH IT. That module tests the gate and its placement inside
`investigate`: given a refused question, `investigate` must not reach the agent. Every one of those tests
passes while a second caller drives the agent directly, because they are tests ABOUT `investigate`. The
property that was false is a property of the CODEBASE — "no module reaches the agent without gating" — and a
property of the codebase needs a test that looks at the codebase.

HOW IT CHECKS. Statically, by parsing each module and walking its syntax tree for a call to `agent.converse`
or `agent.run`; such a module must also call `gate_question` (or be `orchestrate` itself, which defines it).
It parses rather than greps for a reason found on the first run: a text scan flagged `hypothesis.py`, whose
only mention of `agent.run(...)` is a sentence in its module docstring explaining what happens next. A check
that cannot tell a call from a description of a call would have had to be weakened or exempted around, and
either would have cost it the thing it is for. Static analysis also means no API key, no network and no
running server, so it holds on every CI runner.

ITS LIMIT, stated because an unstated limit is how the last one survived. A module could call
`gate_question` and ignore the verdict. That is behaviour, and `tests/test_gate.py` covers it for
`investigate` by removal; for the web application the equivalent is
`test_the_web_app_returns_without_dispatching_on_a_refusal` below, which reads the handler and checks it
returns rather than falling through. Neither is a substitute for the other.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Where a natural-language question can enter and reach the agent loop.
SEARCH_ROOTS = (ROOT / "src" / "cellarium", ROOT / "apps")

# Driving the agent loop. `agent.converse` is the multi-turn form an interface uses; `agent.run` is the
# single-shot form. Either dispatches tools.
DRIVES = {("agent", "converse"), ("agent", "run")}
GATE_NAME = "gate_question"

# Modules allowed to drive the agent without gating, each for a stated reason.
EXEMPT = {
    "src/cellarium/orchestrate.py": "defines gate_question; gating itself would be circular",
    "src/cellarium/agent.py": "is the agent",
}


def _py_files():
    for root in SEARCH_ROOTS:
        if not root.is_dir():
            continue
        for f in root.rglob("*.py"):
            if "__pycache__" not in f.parts:
                yield f


def _rel(f: pathlib.Path) -> str:
    return str(f.relative_to(ROOT)).replace("\\", "/")


def _calls(path: pathlib.Path) -> set:
    """Every call made in a module, as (receiver, method) pairs and bare function names, from its AST."""
    out: set = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute):
            recv = f.value.id if isinstance(f.value, ast.Name) else "*"
            out.add((recv, f.attr))
        elif isinstance(f, ast.Name):
            out.add(f.id)
    return out


def _gates(called: set) -> bool:
    return GATE_NAME in called or any(isinstance(c, tuple) and c[1] == GATE_NAME for c in called)


def test_every_module_that_drives_the_agent_also_gates():
    """THE headline. A new interface that forgets the gate fails here rather than in production."""
    offenders = []
    for f in _py_files():
        rel = _rel(f)
        if rel in EXEMPT:
            continue
        called = _calls(f)
        if (DRIVES & called) and not _gates(called):
            offenders.append(rel)
    assert not offenders, (
        "these modules drive the agent loop without passing the capability gate first: "
        + ", ".join(sorted(offenders))
        + ". Call `orchestrate.gate_question(question)` before dispatching, and return "
          "`gate.render(decision)` when the verdict is not 'answer'. If a module legitimately needs no gate, "
          "add it to EXEMPT here with the reason — the point is that the exception is written down.")


def test_the_detector_can_tell_a_call_from_a_mention():
    """The check that keeps the check honest. `hypothesis.py` describes `agent.run(...)` in its docstring and
    calls it nowhere; a text scan flagged it, which is how a coverage test acquires a false exemption."""
    f = ROOT / "src" / "cellarium" / "hypothesis.py"
    if not f.exists():
        pytest.skip("hypothesis.py not present")
    assert "agent.run(" in f.read_text(encoding="utf-8"), "fixture assumption: the prose mention is there"
    assert not (DRIVES & _calls(f)), "the detector is matching prose, not calls"


def test_the_known_surfaces_are_all_covered():
    """The positive direction. Without this the headline test is satisfied by a codebase that drives the
    agent nowhere at all, which is how a coverage check quietly stops covering anything."""
    expected = {
        "src/cellarium/cli.py": "the command line",
        "src/cellarium/mcp.py": "the third-party agent interface",
        "apps/server.py": "the web application",
    }
    for rel, what in expected.items():
        f = ROOT / rel
        if not f.exists():
            pytest.skip(f"{rel} not present in this checkout")
        called = _calls(f)
        reaches = _gates(called) or any(c == "investigate" or (isinstance(c, tuple) and c[1] == "investigate")
                                        for c in called)
        assert reaches, f"{rel} ({what}) no longer reaches the gate"


def test_the_web_app_returns_without_dispatching_on_a_refusal():
    """Behaviour, not just presence: the handler must stop, not gate and then carry on regardless."""
    f = ROOT / "apps" / "server.py"
    if not f.exists():
        pytest.skip("apps/server.py not present in this checkout")
    src = f.read_text(encoding="utf-8")
    i = src.index("gate_question(")
    j = src.index("agent.converse(", i)
    between = src[i:j]
    assert 'decision.verdict != "answer"' in between, \
        "the web app calls the gate but does not branch on the verdict before converse"
    assert re.search(r"\n\s+return\b", between), \
        "the web app branches on the verdict but does not return before dispatching"


def test_the_gate_entry_point_is_documented_as_the_invariant():
    """`gate_question` carries the property; if it is removed or renamed this must break loudly rather than
    the enumeration above silently matching nothing."""
    src = (ROOT / "src" / "cellarium" / "orchestrate.py").read_text(encoding="utf-8")
    assert "def gate_question(" in src
    assert "gate.Decision" in src, "the contract (what a caller does with the verdict) is not stated"
