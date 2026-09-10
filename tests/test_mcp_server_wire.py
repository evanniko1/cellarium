"""WELL-11 — the half `tests/test_mcp_surface.py` deliberately cannot reach: the wired server.

That file tests the POLICY, in pure Python, so it runs on any machine. This one tests that the policy is
actually WIRED — that the tools the policy permits are the tools that get registered, that the parameter
schemas the SDK derives are the ones a client would need, and that a call arriving through the server ends
up at the same checkpoint. Two files because they fail for different reasons: a policy bug and a wiring bug
need different fixes, and a single test that covers both tells you neither.

Skipped when the SDK is absent, which is the honest behaviour — but note that CI installs the `mcp` extra
specifically so this does NOT skip there. A test that only ever skips is a test that reports nothing.

The transport itself (a real subprocess, a real stdio handshake) was verified by hand against SDK 2.2.0:
initialize returned protocol 2025-11-25, tools/list returned the three listed tools, the derived schema for
`ask_cellwright` arrived with its `question` property intact, and `describe_cellarium` returned the live
corpus counts over the wire. That is left out of CI on purpose — spawning a subprocess per assertion is
slow and flaky, and everything it proves beyond this file belongs to the SDK rather than to us.
"""

from __future__ import annotations

import inspect

import pytest

from cellarium import mcp

pytest.importorskip("mcp", reason="the MCP SDK is an optional extra: pip install \"cellarium[mcp]\"")


def _tools(server) -> list:
    out = server.list_tools()
    if inspect.isawaitable(out):
        import asyncio
        out = asyncio.run(out)
    return list(out)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for e in (mcp.EXPOSE_ALL_ENV, mcp.ALLOW_WRITES_ENV):
        monkeypatch.delenv(e, raising=False)


def test_what_is_registered_is_exactly_what_the_policy_permits():
    """The wiring assertion. `tool_specs()` is the policy; this is the proof it is the thing consulted."""
    registered = [t.name for t in _tools(mcp.build_server())]
    assert registered == [s["name"] for s in mcp.tool_specs()] == list(mcp.LISTED)


def test_expose_all_widens_the_surface_without_widening_permission(monkeypatch):
    monkeypatch.setenv(mcp.EXPOSE_ALL_ENV, "1")
    registered = {t.name for t in _tools(mcp.build_server())}
    assert len(registered) > 50
    leaked = registered & (set(mcp._NEVER) | set(mcp._WRITE_GATED))
    assert not leaked, f"expose-all registered gated tools: {sorted(leaked)}"


def test_the_derived_schema_is_the_one_a_client_needs():
    """Schemas come from the Python signature rather than a hand-written blob, so this is the check that
    the derivation actually produced something callable — an empty properties dict would mean a client
    invokes `ask_cellwright` with no question and the failure surfaces inside someone else's agent loop."""
    by_name = {t.name: t for t in _tools(mcp.build_server())}

    ask = by_name["ask_cellwright"].input_schema
    assert list(ask["properties"]) == ["question"]
    assert ask["properties"]["question"]["type"] == "string"
    assert ask.get("required") == ["question"]

    # A no-argument tool must still advertise a well-formed object schema, not a bare null.
    describe = by_name["describe_cellarium"].input_schema
    assert describe["type"] == "object" and describe.get("properties") == {}


def test_a_call_arriving_through_the_server_hits_the_policy_checkpoint(monkeypatch):
    """`_handler` wraps every registered tool so the one guarded entry point cannot be bypassed.

    Registering the bare function would give the surface two doors, only one of which is checked. This
    asserts the registered callable really does route through `mcp.call` — by replacing `call` and seeing
    the substitution come back out of the handler.
    """
    seen: list[tuple] = []
    monkeypatch.setattr(mcp, "call", lambda n, a=None: seen.append((n, a)) or {"sentinel": n})

    handler = mcp._handler("describe_cellarium")
    assert handler() == {"sentinel": "describe_cellarium"}
    assert seen == [("describe_cellarium", {})]


def test_the_handler_advertises_the_real_functions_parameters():
    """`functools.wraps` is load-bearing, not tidiness: the SDK reads the signature off what it is handed,
    and a bare `**kwargs` wrapper would advertise a tool that takes nothing."""
    sig = inspect.signature(mcp._handler("ask_cellwright"))
    assert list(sig.parameters) == ["question"]


def test_initialize_time_instructions_name_the_withheld_tools():
    """MCP has no 'withheld' state in tools/list, so a gated tool is indistinguishable over the wire from
    one that was never built. The instructions string is the only place every client is guaranteed to see
    the difference, so the gated names must actually be in it — not merely described as being in it."""
    text = mcp.build_server().instructions or ""
    for name in mcp.gated_tools():
        assert name in text, f"{name} is withheld but never named at initialize time"
    assert "describe_cellarium" in text and "simulated" in text


def test_the_instructions_track_the_environment(monkeypatch):
    monkeypatch.setenv(mcp.ALLOW_WRITES_ENV, "1")
    text = mcp.build_server().instructions or ""
    assert "propose_experiment" not in text, "a permitted tool is still described as withheld"
    assert "run_experiment" in text
