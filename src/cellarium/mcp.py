"""WELL-11 — the MCP surface. Cellarium behind one call, spawned over stdio, BYOK.

WHAT THIS IS. A user installs the package, downloads all or part of the corpus, and points their own agent
at it. The server is a LOCAL SUBPROCESS their client spawns over stdio — not a network service — so there is
no hosting, no auth, no multi-tenancy, and no "whose API key pays": the key is theirs, already in the OS
keychain (`docs/CREDENTIALS.md`), and it never enters any model's context. Full rationale: `docs/DECISIONS.md`
**D6**; the assessment that survived it, **D6a**.

WHY ONE TOOL AND NOT SEVENTY-TWO. `tools.TOOLS` has 72 entries. Exposing them is the obvious design and it is
wrong here, because **the rigor lives in the system prompt, not in the tools**: survey first, do not anchor,
viability is not growth rate, a benchmark note is not a measurement, `raw_available=0` is not the same as
absent. Hand a naive caller the raw menu and it reads the first design it thinks of and emits a number with
none of the scope caveats — the instrument without the discipline. So the listed surface is
`ask_cellwright`, `convene_council` and `describe_cellarium`, and the other tools stay
available-but-unlisted behind an env var, which is the pattern codegraph uses.

THE SAFETY PROPERTY, STATED EXACTLY. This is open source: anyone can fork this file and delete the checks
below, and that is legitimate — it is their machine. So the guarantee is not a wall against the user, it is
a **shipped default protecting the user from their own agent**:

    a third-party agent connected over MCP must not be able to launch a simulation, write to the user's
    launch queue, fetch from the network, or reach the credential vault, without that human approving it.

Two tiers implement it, and the difference between them is whether a HUMAN GATE exists downstream:
  * `_NEVER` — no CONVENIENCE flag lifts these; only the explicit opt-in below does. `run_experiment`
    starts a simulation with no approval step after it; `download_raw` writes gigabytes; `web_get` makes
    outbound requests; `use_skill` loads instructions into the loop, which is an injection surface. The
    user's own CLI and web app still have every one of them.
  * `_WRITE_GATED` — the `propose_*` / `revise_*` family writes drafts into `data/launch_queue.json`. That
    queue IS the human airlock, so these are defensible over MCP — but not by default, and specifically not
    as a silent side effect of "expose everything". They need their own key. The reason is measured, not
    hypothetical: a probe run in this repo once wrote 8 phantom drafts into that queue in a single sweep.

UNATTENDED MODE. Both tiers assume a human is somewhere behind the call, which stops being true the moment
Cellarium is driven BY another agent — a subagent cannot consent on a person's behalf. So
`CELLARIUM_MCP_DANGEROUSLY_ALLOW_ALL=1` lifts everything this module gates, and the biosecurity screen and
envelope check still hold because they live inside `run_experiment` rather than here. See ALLOW_ALL_ENV.

The credential vault is absent by construction rather than by exclusion — no tool in `tools.TOOLS` touches
`credentials` at all — and `tests/test_mcp_surface.py` fails if one is ever added, because "we checked once"
is not a property.

THE SPLIT THAT MAKES THIS TESTABLE. Everything above is pure Python in this module and needs no MCP SDK:
which tools are listed, which are refused, what a refusal says. `main()` is the only part that imports the
SDK, and it does so lazily. So the entire safety-relevant surface is covered by tests that run in CI on a
machine with no `mcp` installed — which is the case that matters, because a policy nobody can test is a
policy nobody knows the state of.

RUN IT. Add to the client's MCP config (Claude Desktop, Claude Code, or any stdio client):

    {"mcpServers": {"cellarium": {"command": "python", "args": ["-m", "cellarium.mcp"]}}}

`pip install "cellarium[mcp]"` supplies the SDK.
"""

from __future__ import annotations

import os
from typing import Any

from . import tools

# ---------------------------------------------------------------------------------------------------------
# The listed surface.
# ---------------------------------------------------------------------------------------------------------

LISTED = ("ask_cellwright", "convene_council", "describe_cellarium")

# Refused whatever the environment says. Each entry carries WHY, because a refusal that does not say what it
# is protecting reads as an immature surface rather than a deliberate one.
_NEVER: dict[str, str] = {
    "run_experiment": "starts a simulation immediately — there is no human approval step behind it, unlike "
                      "the propose_* family, which queues for one",
    "download_raw":   "fetches from HuggingFace and writes archives (often gigabytes) into the user's runs "
                      "directory",
    "web_get":        "makes outbound HTTP requests; a third-party agent must not be able to originate "
                      "network traffic from the user's machine",
    "use_skill":      "loads external instruction text into the agent loop, which is an instruction-"
                      "injection surface, not a data read",
}

# Refused by default; CELLARIUM_MCP_ALLOW_WRITES=1 lifts them, because the launch queue they write to IS the
# human airlock — a queued draft runs nothing until a person approves it.
_WRITE_GATED: dict[str, str] = {
    "propose_experiment":  "writes a draft into the user's launch queue",
    "propose_experiments": "writes a whole panel of drafts into the user's launch queue",
    "revise_experiment":   "edits a draft already in the user's launch queue",
    "propose_rebuild":     "queues a knowledge-base rebuild, which mints a new arm",
}

EXPOSE_ALL_ENV = "CELLARIUM_MCP_EXPOSE_ALL"
ALLOW_WRITES_ENV = "CELLARIUM_MCP_ALLOW_WRITES"

# UNATTENDED MODE — the Claude Code `--dangerously-skip-permissions` of this surface.
#
# THE PROBLEM IT SOLVES, and it is a real one rather than a convenience. The tiers above assume a human is
# somewhere behind the call, either approving at the airlock or deciding to set a flag. That assumption
# breaks the moment Cellarium is driven BY ANOTHER AGENT: a subagent cannot grant consent on a person's
# behalf, so `run_experiment` is not merely inconvenient there, it is unreachable, and an autonomous
# investigate-simulate-reread loop cannot be built at all. Refusing to offer a way out would not be safety;
# it would be a capability hole dressed as one.
#
# So this exists, and the name is the warning label — long, explicit, and hard to set by accident. It lifts
# BOTH tiers and lists everything, because a switch that permits without advertising leaves the caller's
# model unable to discover what it may now do.
#
# WHAT IT DOES NOT LIFT, which is the whole reason it can be offered at all. Two checks live INSIDE
# `run_experiment` rather than in this policy, and nothing here can reach them:
#   * the BIOSECURITY screen (`biosecurity.screen`) — it protects the operator, not the operator's consent,
#     and D6 is explicit that it stays server-side;
#   * the validated-ENVELOPE check (`envelope.check`) — a design outside the envelope is refused with a
#     reason, because a number from there is not a measurement.
# `tests/test_mcp_surface.py` pins both: the envelope refusal is observed live with a harmless design, and
# the biosecurity verdict is STUBBED rather than triggered — what needs testing is that a flagged verdict
# is honoured through this path, and that does not require writing a virulence design into the suite.
ALLOW_ALL_ENV = "CELLARIUM_MCP_DANGEROUSLY_ALLOW_ALL"


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def allow_all() -> bool:
    """Unattended mode: every gate this module owns is lifted. See the block above for what remains."""
    return _flag(ALLOW_ALL_ENV)


def expose_all() -> bool:
    """Are the unlisted read/analysis tools advertised to the caller's model?"""
    return _flag(EXPOSE_ALL_ENV) or allow_all()


def allow_writes() -> bool:
    """Is the propose_*/revise_* family permitted? Separate key on purpose — see the module docstring."""
    return _flag(ALLOW_WRITES_ENV) or allow_all()


def gated_tools() -> dict[str, str]:
    """Every tool this surface refuses right now, mapped to the reason. Environment-dependent by design."""
    if allow_all():
        return {}
    out = dict(_NEVER)
    if not allow_writes():
        out.update(_WRITE_GATED)
    return out


def refusal(name: str) -> dict | None:
    """The refusal for `name`, or None if the call is permitted. Pure; no I/O; the whole policy in one place."""
    if allow_all():
        return None
    why = _NEVER.get(name)
    if why:
        return {"error": f"'{name}' is not available over MCP: {why}.",
                "refused_by": "cellarium-mcp-policy",
                "tier": "never",
                "what_you_can_do": "Run it from the Cellarium CLI or web app on this machine — both have it. "
                                   "This surface refuses it so a third-party agent cannot take the action "
                                   "without you.",
                "reference": "docs/DECISIONS.md D6"}
    why = _WRITE_GATED.get(name)
    if why and not allow_writes():
        return {"error": f"'{name}' is write-gated over MCP: {why}.",
                "refused_by": "cellarium-mcp-policy",
                "tier": "write_gated",
                "what_you_can_do": f"Set {ALLOW_WRITES_ENV}=1 in the server's environment to permit it. "
                                   "Nothing it queues runs until you approve it at the airlock.",
                "reference": "docs/DECISIONS.md D6"}
    return None


# ---------------------------------------------------------------------------------------------------------
# What gets advertised.
# ---------------------------------------------------------------------------------------------------------
# NO JSON SCHEMAS ARE WRITTEN HERE, deliberately. The SDK derives each tool's parameter schema from the
# Python signature of the function being registered, which is strictly better than a hand-written blob:
# a hand-written schema is a second description of the same signature and can silently drift from it, and
# this repository has already been bitten once by a hand-maintained declaration disagreeing with the code
# it described. The cost is that per-parameter prose from `tools.TOOLS[*]["input_schema"]` is not carried
# through — the tool-level `description`, which holds the guidance that actually matters, is.

_LISTED_SPECS: list[dict[str, Any]] = [
    {"name": "ask_cellwright",
     "description":
         "Ask a question about the whole-cell E. coli simulation corpus and get a GROUNDED answer: every "
         "number traced to a tool result, with the scope caveats that make it readable (which arm, which "
         "generation depth, how many seeds, whether the condition was in-sample). Runs Cellarium's full "
         "investigator loop locally, so it will REFUSE and say why when the corpus cannot support the "
         "question — a refusal here is a result, not a failure. Use this instead of asking for raw rows."},

    {"name": "convene_council",
     "description":
         "Turn a vague research question into a falsifiable, operationalized hypothesis with a discriminating "
         "experiment behind it. The Council is BLIND BY CONSTRUCTION — it reads no simulation results at all "
         "— so it needs no corpus downloaded and cannot be anchored by what happens to be in one. Use it "
         "before ask_cellwright when the question is still open-ended."},

    {"name": "describe_cellarium",
     "description":
         "What this surface is, what it holds, and — the part worth reading — WHAT IT DELIBERATELY DOES NOT "
         "EXPOSE and why. Call it first if you are deciding whether Cellarium can answer something; the "
         "absences are reported here rather than discovered as failures."},
]


def tool_specs() -> list[dict]:
    """Exactly which tools `tools/list` should carry, given the current environment.

    This is the POLICY answer and it is what `main()` iterates over to decide what to register — so the
    two cannot drift. Pure: no SDK, no I/O, testable on a machine that has never installed either.
    """
    specs = [dict(s) for s in _LISTED_SPECS]
    if expose_all():
        specs += [{"name": t["name"], "description": t.get("description", "")}
                  for t in tools.TOOLS if refusal(t["name"]) is None]
    return specs


# ---------------------------------------------------------------------------------------------------------
# The three listed tools.
# ---------------------------------------------------------------------------------------------------------

def describe_cellarium() -> dict:
    """D6b's T0 pattern applied to Surface A: report the absence INSIDE the surface.

    A caller that finds a capability missing has two readings available — "this project has not built it yet"
    and "this project decided against it" — and it cannot tell them apart by probing. Saying which, here,
    costs a few hundred tokens and removes a whole category of wrong conclusion about the corpus.
    """
    # The counts come from `survey_corpus`'s own coverage block rather than being recomputed here, so this
    # description cannot drift from the survey a caller would actually read. The first version of this
    # function called a `survey.coverage()` that does not exist, swallowed the AttributeError, and reported
    # `n_runs: null` — the silent-absence defect, committed inside the tool whose whole job is to make
    # absences legible. So the failure branch now SAYS what broke.
    corpus: dict[str, Any]
    try:
        cov = tools.survey_corpus().get("coverage") or {}
        corpus = {"n_runs": cov.get("n_runs"),
                  "n_designs": cov.get("n_designs_in_corpus"),
                  "n_designs_reportable": cov.get("n_designs_ranked")}
    except Exception as exc:
        corpus = {"unreadable": f"{type(exc).__name__}: {exc}",
                  "meaning": "The corpus could not be read from this machine — which is NOT the same as "
                             "the corpus being empty. Check that the manifest/shard is downloaded and that "
                             "CELLARIUM_MANIFEST points at it."}
    corpus.update({
        "one_row_is": "one generation of one seed of one design — not one cell, not one experiment, not "
                      "one lineage",
        "datasheet": "docs/DATASHEET.md, whose 'what this dataset cannot support' section is the part to "
                     "read before using any number from here"})
    return {
        "what_this_is": "An agentic workbench over wcEcoli, a MECHANISTIC whole-cell simulation of "
                        "Escherichia coli. Values here are simulated, not measured in a laboratory.",
        "corpus": corpus,
        "listed_tools": list(LISTED),
        "why_only_three": "The rigor lives in the investigator's system prompt, not in the individual tools. "
                          "A menu of 72 read tools lets a caller take a number without the scope caveats "
                          "that make it true.",
        "unlisted_tools": {
            "count": sum(1 for t in tools.TOOLS if refusal(t["name"]) is None),
            "listed_now": expose_all(),
            "how": f"set {EXPOSE_ALL_ENV}=1 in this server's environment",
            "note": "They are read/analysis tools and are callable when listed. This is a local install; "
                    "you already have everything the package has."},
        "deliberately_absent": [
            {"capability": "raw SQL over the corpus",
             "why": "The corpus is a union of per-contributor shards read with union_by_name, and the "
                    "de-duplication rule partitions on a PAIR of columns because neither is unique alone. "
                    "Skipping it once inflated the wildtype reference — the baseline every comparison uses "
                    "— from 26 seeds to 34. A SQL passthrough is the tool that looks most honest and is the "
                    "easiest way to make this corpus lie."},
            {"capability": "launching a simulation, or writing to the launch queue",
             "why": "A third-party agent must not take an action on this machine that the human did not "
                    "approve. See `gated` below for the exact list and how to lift what is liftable."},
            {"capability": "the credential vault",
             "why": "No tool reaches it, by construction rather than by exclusion. Your API key stays in "
                    "the OS keychain and never enters any model's context."},
        ],
        "gated": [{"tool": k, "reason": v, "tier": ("never" if k in _NEVER else "write_gated")}
                  for k, v in sorted(gated_tools().items())],
        "unattended_mode": ({
            "on": True,
            "meaning": "Every gate this surface owns is lifted. Calling run_experiment STARTS A REAL "
                       "SIMULATION on this machine — minutes to hours of compute, writing into the runs "
                       "directory — with no human approving it. download_raw will fetch gigabytes; web_get "
                       "will make outbound requests; the propose_* family writes to the launch queue.",
            "still_enforced": ["the biosecurity screen — a flagged design returns biosecurity_hold and does "
                               "not run", "the validated-envelope check — an out-of-envelope design is "
                               "refused with a reason rather than answered"],
            "how_it_was_enabled": f"{ALLOW_ALL_ENV}=1 in this server's environment",
        } if allow_all() else {"on": False,
                               "what_it_would_do": "lift every gate below, for an agent-driven loop with no "
                                                   "human at the airlock",
                               "how": f"set {ALLOW_ALL_ENV}=1 — and read what it does first"}),
        "before_you_pool_two_rows": "Rows are comparable only within one ARM — the same fitted knowledge "
                                    "base (kb_sha256), operon setting and elongation model. Averaging across "
                                    "arms produces a number that describes neither.",
    }


def _run_ids() -> dict:
    """What the answer above actually read, harvested from the turn record the tools already maintain.

    D6 asks `ask_cellwright` to return "the grounded answer plus the run ids behind it". This is that, and it
    is not a re-derivation: `reconcile` records every id and design a tool result carried, which is the same
    ledger the post-hoc provenance check reads. A caller that wants to verify a sentence has the identifiers
    to do it with.
    """
    try:
        from . import reconcile
        rec = reconcile.turn_record()
        return {"run_ids": sorted(rec.get("ids") or ()), "designs": sorted(rec.get("designs") or ()),
                "measurement_calls": rec.get("measurement_calls")}
    except Exception:
        return {}


def ask_cellwright(question: str) -> dict:
    """The full grounded loop over the same `orchestrate` seam the CLI and the web app call (D5)."""
    from . import orchestrate
    inv = orchestrate.investigate(question, use_council=False, verbose=False)
    return {"answer": inv.answer, "grounded_in": _run_ids(),
            "caveat": "Simulated values, not laboratory measurements. Rows pool only within one arm."}


def convene_council(question: str) -> dict:
    """The blind hypothesis-former. Reads no corpus — so it works with nothing downloaded."""
    from . import council
    hyp = council.deliberate(question, verbose=False)
    brief = hyp.brief() if hasattr(hyp, "brief") else None
    return {"brief": brief, "hypothesis": getattr(hyp, "statement", None) or str(hyp),
            "blind": True,
            "blindness": "The Council reads no simulation results by construction — the reading modules are "
                         "import-quarantined from it and tests/test_blindness.py pins that. So this "
                         "hypothesis is not anchored on what the corpus happens to contain."}


_LOCAL = {"ask_cellwright": ask_cellwright, "convene_council": convene_council,
          "describe_cellarium": describe_cellarium}


def call(name: str, args: dict | None = None) -> dict:
    """Dispatch with the policy applied. The ONLY entry point the transport layer uses.

    Order matters and is not arbitrary: the refusal check runs BEFORE the unknown-tool check, so a gated
    tool gets its real reason rather than being reported as if it did not exist. Telling a caller a tool is
    missing when it is actually withheld is the silent-absence defect this project keeps finding in itself.
    """
    args = dict(args or {})
    ref = refusal(name)
    if ref is not None:
        return ref
    fn = _LOCAL.get(name)
    if fn is not None:
        try:
            return fn(**args)
        except TypeError as exc:
            return {"error": f"bad arguments for {name}: {exc}"}
    if name in {t["name"] for t in tools.TOOLS}:
        if not expose_all():
            return {"error": f"'{name}' exists but is not listed on this surface.",
                    "refused_by": "cellarium-mcp-policy", "tier": "unlisted",
                    "what_you_can_do": f"set {EXPOSE_ALL_ENV}=1 to advertise and enable the read/analysis "
                                       f"tools, or ask the same question through ask_cellwright, which "
                                       f"applies the scope discipline for you."}
        return tools.dispatch(name, args)
    return {"error": f"unknown tool '{name}'"}


# ---------------------------------------------------------------------------------------------------------
# Transport. The only part that needs the SDK.
# ---------------------------------------------------------------------------------------------------------

_SDK_MISSING = (
    "The MCP server needs the official SDK, which is not installed.\n\n"
    '    pip install "cellarium[mcp]"\n\n'
    "Everything else in Cellarium — the CLI, the web app, the Python API — works without it.")


def _handler(name: str):
    """A registered tool: the real function's SIGNATURE, and a body that goes through `call()`.

    `functools.wraps` is load-bearing rather than tidy. The SDK derives the parameter schema by inspecting
    what it is handed, and `inspect.signature` follows `__wrapped__`, so the wrapper advertises the real
    tool's parameters while every invocation still passes through the one policy checkpoint. Register the
    bare function instead and the surface has two entry points, only one of which is guarded.
    """
    import functools
    real = _LOCAL.get(name) or tools._DISPATCH[name]

    @functools.wraps(real)
    def handler(**kwargs):
        return call(name, kwargs)

    return handler


def build_server(server_cls=None):
    """The wired server, with exactly the tools `tool_specs()` permits. Separated from `main()` so a test
    can inspect what was registered without opening a stdio transport."""
    from mcp.server import MCPServer
    from mcp.types import ToolAnnotations
    server_cls = server_cls or MCPServer

    # The gated names are spelled out at INITIALIZE time, not only inside describe_cellarium.
    # MCP has no "withheld" state in tools/list: an unadvertised tool is indistinguishable over the wire
    # from one that was never built, and calling it returns a generic unknown-tool error. That is the
    # silent-absence failure in its protocol-level form, and the protocol gives no way to fix it properly
    # — so the next best thing is to say it once, up front, where every client sees it.
    gated = ", ".join(sorted(gated_tools()))
    if gated:
        policy = (
            f"WITHHELD BY POLICY, not missing: {gated}. These exist in the package and are reachable from "
            "the user's own CLI and web app; this surface refuses them so a third-party agent cannot launch "
            "a simulation, write to the launch queue, or originate network traffic without the human "
            "agreeing. Calling one returns an unknown-tool error because the protocol has no way to say "
            "'withheld' — describe_cellarium gives the reason for each.")
    else:
        policy = (
            "UNATTENDED MODE IS ON. Every gate this surface owns has been lifted deliberately by whoever "
            "started this server. run_experiment STARTS A REAL SIMULATION — minutes to hours of compute on "
            "this machine, with nobody approving it — and download_raw will fetch gigabytes. Two checks are "
            "still enforced and are not yours to skip: a biosecurity-flagged design returns biosecurity_hold "
            "and does not run, and a design outside the validated envelope is refused with a reason. "
            "Before launching anything, use estimate_sim_resources and say what you are about to start.")
    server = server_cls("cellarium", version="0.1.0", instructions=(
        "Cellarium answers questions about a MECHANISTIC whole-cell simulation of E. coli. Values are "
        "simulated, never laboratory measurements, and two rows are comparable only within one arm "
        "(same fitted knowledge base, operon setting and elongation model).\n\n"
        "Call describe_cellarium first if you are deciding whether a question is answerable here: it "
        "reports what this surface deliberately does not expose, so an absence is read as a decision "
        "rather than an omission.\n\n" + policy))

    for spec in tool_specs():
        server.add_tool(_handler(spec["name"]), name=spec["name"], description=spec["description"],
                        # Honest, not decorative: the write family is gated above and never reaches here,
                        # so everything registered really is a read.
                        annotations=ToolAnnotations(readOnlyHint=True))
    return server


def main() -> int:
    """Serve over stdio. The SDK is imported lazily so this module stays importable, and its policy stays
    testable, on a machine that has never installed it."""
    try:
        import mcp.server  # noqa: F401
    except ImportError:
        import sys
        print(_SDK_MISSING, file=sys.stderr)
        return 2

    # Sync tool functions are offloaded by the SDK (`anyio.to_thread.run_sync`), which matters here: an
    # `ask_cellwright` turn is minutes of blocking model and DuckDB work, and running it on the event loop
    # would stall the server's own protocol handling — pings, cancellations — for the whole turn.
    build_server().run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
