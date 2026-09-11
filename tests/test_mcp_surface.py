"""WELL-11 — the MCP surface's POLICY, pinned. No SDK required, deliberately.

WHY THESE TESTS AND NOT AN INTEGRATION TEST. The wire protocol is the SDK's job and is exercised by
thousands of other users; what is ours, and what nobody else can get right for us, is the answer to *what
may a third-party agent do on this machine*. That answer is pure Python in `cellarium.mcp` — no sockets, no
subprocess, no `mcp` package — so it is testable everywhere, including on a CI runner that has never
installed the SDK. A policy that can only be checked on a developer's laptop is a policy of unknown state.

The property being defended, from `docs/DECISIONS.md` D6:

    a third-party agent connected over MCP must not be able to launch a simulation, write to the user's
    launch queue, fetch from the network, or reach the credential vault, without that human approving it.

Note what is NOT asserted: that a fork cannot remove these checks. It can, and that is legitimate — the
guarantee is a shipped default protecting the user from their own agent, not a wall against the user.
"""

from __future__ import annotations

import inspect
import re

import pytest

from cellarium import mcp, tools

ENVS = (mcp.EXPOSE_ALL_ENV, mcp.ALLOW_WRITES_ENV, mcp.ALLOW_ALL_ENV)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test states its own environment. Inheriting the developer's would make results unrepeatable."""
    for e in ENVS:
        monkeypatch.delenv(e, raising=False)


# ---------------------------------------------------------------------------------------------------------
# The listed surface
# ---------------------------------------------------------------------------------------------------------

def test_only_three_tools_are_listed_by_default():
    """The whole design rests on this. 72 read tools exist; three are advertised."""
    assert [s["name"] for s in mcp.tool_specs()] == list(mcp.LISTED)


def test_the_policy_carries_names_and_guidance_and_no_hand_written_schema():
    """`tool_specs()` answers *which* tools and *what they are for* — never *what shape their arguments are*.

    An earlier version of this module did write JSON schemas here, and this test checked that they used
    MCP's `inputSchema` spelling rather than the Anthropic `input_schema` one that `tools.TOOLS` uses.
    That whole class of bug was removed rather than tested: the SDK now derives each schema from the
    function's own signature, so there is no second description of the arguments to drift from the first.
    What is left to pin is that nobody re-introduces one — and that every advertised tool carries the
    prose a caller decides on. `tests/test_mcp_server_wire.py` checks the derived schemas themselves.
    """
    for spec in mcp.tool_specs():
        assert set(spec) == {"name", "description"}, f"{spec['name']} carries an unexpected key"
        assert len(spec["description"]) > 60, f"{spec['name']} has no usable description"
        assert "input_schema" not in spec and "inputSchema" not in spec


def test_the_unlisted_tier_appears_only_when_asked_for(monkeypatch):
    monkeypatch.setenv(mcp.EXPOSE_ALL_ENV, "1")
    names = [s["name"] for s in mcp.tool_specs()]
    assert names[:3] == list(mcp.LISTED)
    assert len(names) > 50, "expose-all should advertise the read/analysis tools"
    assert "survey_corpus" in names


# ---------------------------------------------------------------------------------------------------------
# The safety property
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(mcp._NEVER))
def test_no_CONVENIENCE_flag_lifts_the_never_tier(name, monkeypatch):
    """`expose all` must not be a synonym for `permit everything`.

    ⚠️ THIS INVARIANT WAS NARROWED, 2026-09-11, and the narrowing is the point rather than a concession.
    It used to read "no environment variable lifts this tier". That was too strong and it removed a real
    capability: an agent driving Cellarium cannot grant consent on a person's behalf, so under that rule an
    autonomous simulate-and-reread loop was impossible rather than merely gated. The guarantee is now that
    only an EXPLICIT, self-describing opt-in lifts it — `CELLARIUM_MCP_DANGEROUSLY_ALLOW_ALL`, whose name is
    the warning — and never a flag someone set for a different reason. Which is the property that was
    actually worth defending: nobody should reach a launch by asking for visibility.
    """
    for e in (mcp.EXPOSE_ALL_ENV, mcp.ALLOW_WRITES_ENV):
        monkeypatch.setenv(e, "1")
    ref = mcp.refusal(name)
    assert ref is not None and ref["tier"] == "never", f"{name} became callable with both flags set"
    assert name not in [s["name"] for s in mcp.tool_specs()], f"{name} was advertised"


@pytest.mark.parametrize("name", sorted(mcp._WRITE_GATED))
def test_the_write_family_is_refused_by_default_and_liftable_by_its_own_key(name, monkeypatch):
    """Queue writes have a human airlock behind them, so they are liftable — but never as a side effect of
    the expose-all key, which is about visibility, not permission."""
    assert mcp.refusal(name)["tier"] == "write_gated"

    monkeypatch.setenv(mcp.EXPOSE_ALL_ENV, "1")
    assert mcp.refusal(name) is not None, "expose-all must not grant write permission"

    monkeypatch.setenv(mcp.ALLOW_WRITES_ENV, "1")
    assert mcp.refusal(name) is None


def test_a_gated_call_never_reaches_the_dispatcher(monkeypatch):
    """A refusal that still executes the tool is worse than no refusal, because it reads as safe.

    `tools.dispatch` is replaced by a recorder: the assertion is about what was RUN, not about what was
    returned.
    """
    ran: list[str] = []
    monkeypatch.setattr(tools, "dispatch", lambda n, a: ran.append(n) or {"ok": True})
    monkeypatch.setenv(mcp.EXPOSE_ALL_ENV, "1")

    for name in sorted(set(mcp._NEVER) | set(mcp._WRITE_GATED)):
        out = mcp.call(name, {})
        assert out.get("refused_by") == "cellarium-mcp-policy", f"{name} was not refused"
    assert ran == [], f"a gated tool executed anyway: {ran}"


# ---------------------------------------------------------------------------------------------------------
# Unattended mode
# ---------------------------------------------------------------------------------------------------------

def test_unattended_mode_lifts_every_gate_this_module_owns(monkeypatch):
    """The capability the tiers would otherwise remove entirely.

    A subagent cannot grant consent on a person's behalf, so under the default policy an agent-driven
    investigate-simulate-reread loop is not merely inconvenient — it is impossible. Refusing to offer a way
    out would be a capability hole dressed as safety.
    """
    monkeypatch.setenv(mcp.ALLOW_ALL_ENV, "1")
    assert mcp.gated_tools() == {}
    for name in set(mcp._NEVER) | set(mcp._WRITE_GATED):
        assert mcp.refusal(name) is None, f"{name} still refused in unattended mode"
    assert "run_experiment" in [s["name"] for s in mcp.tool_specs()]


def test_unattended_mode_implies_listing_because_permission_without_discovery_is_useless(monkeypatch):
    """One switch, not three. A caller that may now launch but cannot see `run_experiment` gains nothing."""
    monkeypatch.setenv(mcp.ALLOW_ALL_ENV, "1")
    assert mcp.expose_all() and mcp.allow_writes()
    assert len([s["name"] for s in mcp.tool_specs()]) == len(tools.TOOLS) + len(mcp.LISTED)


def test_neither_weaker_flag_implies_unattended_mode(monkeypatch):
    """The dangerous switch must never be reachable by setting a convenience one."""
    for env in (mcp.EXPOSE_ALL_ENV, mcp.ALLOW_WRITES_ENV):
        monkeypatch.setenv(env, "1")
        assert not mcp.allow_all(), f"{env} leaked into unattended mode"
        assert mcp.refusal("run_experiment") is not None
        monkeypatch.delenv(env)


def test_the_biosecurity_screen_is_not_ours_to_lift(monkeypatch):
    """The line that makes unattended mode offerable at all.

    The gates in this module are about a HUMAN'S CONSENT, and consent is exactly what an unattended operator
    has chosen to give in advance. The biosecurity screen is about something else — it protects the operator
    rather than their agreement — and D6 is explicit that it stays server-side. It lives inside
    `run_experiment`, so no flag here can reach it; this asserts that rather than trusting where the code
    happens to sit today.

    The screen's verdict is stubbed rather than triggered with a real signature: what needs testing is that
    a flagged verdict is HONOURED through the MCP path, and that does not require writing a virulence design
    into the test suite.
    """
    from cellarium import biosecurity

    monkeypatch.setenv(mcp.ALLOW_ALL_ENV, "1")
    monkeypatch.setattr(biosecurity, "screen", lambda design: biosecurity.BiosecurityVerdict(
        True, "stubbed_signature", ["stub"], "block", "stubbed for the test"))

    out = mcp.call("run_experiment", {"perturbation": "wildtype", "condition": "basal",
                                      "seeds": 1, "generations": 1})
    assert out.get("status") == "biosecurity_hold", f"a flagged design was not held: {out}"


def test_the_validated_envelope_is_not_ours_to_lift_either(monkeypatch):
    """Same separation, second check — and this one needs no stub, because an unrecognised perturbation is
    refused by the envelope with a reason. Observed live rather than asserted: the call reaches
    `run_experiment`, which declines before launching anything."""
    monkeypatch.setenv(mcp.ALLOW_ALL_ENV, "1")
    out = mcp.call("run_experiment", {"perturbation": "not_a_real_variant", "condition": "basal",
                                      "seeds": 1, "generations": 1})
    assert out.get("status") == "refused"
    assert "envelope" in (out.get("note") or "").lower()


def test_describe_announces_unattended_mode_loudly_and_says_what_survives(monkeypatch):
    """An agent connected to a permission-less server must be able to find that out from the server."""
    off = mcp.describe_cellarium()["unattended_mode"]
    assert off["on"] is False and mcp.ALLOW_ALL_ENV in off["how"]

    monkeypatch.setenv(mcp.ALLOW_ALL_ENV, "1")
    on = mcp.describe_cellarium()["unattended_mode"]
    assert on["on"] is True
    assert "STARTS A REAL SIMULATION" in on["meaning"]
    assert any("biosecurity" in s for s in on["still_enforced"])
    assert any("envelope" in s for s in on["still_enforced"])


def test_a_withheld_tool_is_not_reported_as_a_missing_one():
    """The silent-absence defect, in its MCP form.

    'unknown tool' and 'withheld tool' lead a caller to opposite conclusions — one says the project never
    built it, the other says the project decided against it — and a caller cannot distinguish them by
    probing. So the refusal check runs BEFORE the unknown-name check, and the message says which.
    """
    withheld = mcp.call("run_experiment", {})
    assert "unknown" not in withheld["error"].lower()
    assert withheld["tier"] == "never" and "what_you_can_do" in withheld

    unlisted = mcp.call("survey_corpus", {})
    assert unlisted["tier"] == "unlisted" and "exists" in unlisted["error"]

    assert mcp.call("no_such_tool", {})["error"].startswith("unknown tool")


# ---------------------------------------------------------------------------------------------------------
# The vault, and the general side-effect guard
# ---------------------------------------------------------------------------------------------------------

_SIDE_EFFECT = re.compile(
    r"(subprocess|urlopen|requests\.|httpx|docker\.|shutil\.|os\.remove|os\.unlink|rmtree"
    r"|write_text|write_bytes|credentials|keyring)")


def _reachable_sources(fn, depth: int = 2, seen: set | None = None) -> list[tuple]:
    """Source of `fn` plus, to `depth` levels, the cellarium functions it calls by a resolvable name."""
    import ast
    import sys
    import types
    seen = seen if seen is not None else set()
    if depth < 0 or fn in seen:
        return []
    seen.add(fn)
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return []
    out = [(fn, src)]
    mod = sys.modules.get(fn.__module__)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f, target = node.func, None
        if isinstance(f, ast.Name):
            target = getattr(mod, f.id, None)
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            base = getattr(mod, f.value.id, None)
            if base is not None:
                target = getattr(base, f.attr, None)
        if isinstance(target, types.FunctionType) and target.__module__.startswith("cellarium"):
            out += _reachable_sources(target, depth - 1, seen)
    return out


def test_nothing_in_the_read_tier_reaches_a_side_effect_or_the_vault():
    """A static reachability scan over every tool this surface would permit.

    WHAT IT PROVES AND WHAT IT DOES NOT. It follows statically-resolvable calls two levels deep and flags
    filesystem writes, subprocesses, outbound HTTP, and any mention of the credential modules. It cannot
    follow a call through a dict of callables, a getattr, or a third level of indirection, so it is a
    tripwire rather than a proof — which is exactly why it is worth having: the realistic way a write
    enters the read tier is someone adding a tool that writes a file, and that is precisely what this
    catches. Measured at 0 hits across all 64 permitted tools when written.
    """
    offenders: dict[str, list[str]] = {}
    for spec in tools.TOOLS:
        name = spec["name"]
        if mcp.refusal(name) is not None:
            continue
        hits = set()
        for fn, src in _reachable_sources(tools._DISPATCH[name]):
            for m in _SIDE_EFFECT.finditer(src):
                hits.add(f"{fn.__module__.split('.')[-1]}.{fn.__name__} -> {m.group(1)}")
        if hits:
            offenders[name] = sorted(hits)
    assert not offenders, (
        "these tools are permitted over MCP but reach a side effect or the credential vault: "
        f"{offenders}. Either the tool belongs in mcp._NEVER / mcp._WRITE_GATED, or — if the match is "
        "benign — say so explicitly here rather than widening the pattern until it matches nothing.")


def test_no_tool_is_named_or_described_as_touching_a_key():
    """A cheap second angle on the same property, from the caller's side rather than the code's."""
    for spec in mcp.tool_specs():
        blob = f"{spec['name']} {spec.get('description', '')}".lower()
        assert "api key" not in blob and "keychain" not in blob, spec["name"]


# ---------------------------------------------------------------------------------------------------------
# describe_cellarium — the absence report
# ---------------------------------------------------------------------------------------------------------

def test_describe_reports_the_corpus_or_says_why_it_cannot():
    """It must never answer `n_runs: null`, which is how the first version of it failed.

    Reporting a null count is the silent-absence bug committed inside the tool built to prevent it: a
    caller reads "0 runs / unknown" and concludes the corpus is empty, when the truth was that a helper had
    been renamed and the exception was swallowed.
    """
    c = mcp.describe_cellarium()["corpus"]
    if "unreadable" in c:
        assert "meaning" in c and "not the same as" in c["meaning"]
    else:
        assert isinstance(c["n_runs"], int) and c["n_runs"] > 0
        assert isinstance(c["n_designs"], int) and c["n_designs"] > 0


def test_describe_names_every_currently_gated_tool_with_its_reason():
    """D6b's T0 pattern: the absence is reported INSIDE the surface, so it is read as a decision."""
    d = mcp.describe_cellarium()
    named = {g["tool"]: g for g in d["gated"]}
    assert set(named) == set(mcp.gated_tools())
    for tool, entry in named.items():
        assert entry["reason"] and entry["tier"] in ("never", "write_gated"), tool
    assert any("SQL" in a["capability"] for a in d["deliberately_absent"])
    assert any("credential" in a["capability"] for a in d["deliberately_absent"])


def test_describe_tracks_the_environment_rather_than_asserting_a_fixed_state(monkeypatch):
    """If the write family is enabled, describe must stop claiming it is gated."""
    before = {g["tool"] for g in mcp.describe_cellarium()["gated"]}
    assert before == set(mcp._NEVER) | set(mcp._WRITE_GATED)

    monkeypatch.setenv(mcp.ALLOW_WRITES_ENV, "1")
    still = {g["tool"] for g in mcp.describe_cellarium()["gated"]}
    assert still == set(mcp._NEVER)


# ---------------------------------------------------------------------------------------------------------
# The transport's one testable edge
# ---------------------------------------------------------------------------------------------------------

def test_a_missing_sdk_is_an_instruction_not_a_traceback(monkeypatch, capsys):
    """The most likely first experience of this module is running it without `pip install cellarium[mcp]`.

    An ImportError traceback there tells the user their install is broken. It is not — every other surface
    works — so the message says which extra to install and that nothing else is affected.
    """
    import builtins
    real = builtins.__import__

    def blocked(name, *a, **k):
        if name.startswith("mcp.") or name == "mcp":
            raise ImportError("simulated: SDK not installed")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert mcp.main() == 2
    err = capsys.readouterr().err
    assert "cellarium[mcp]" in err and "works without it" in err
