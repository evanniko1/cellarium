"""WELL-11 — does a simulation actually RUN over the MCP wire, with no human granting permission?

WHY A SCRIPT AND NOT A TEST. `tests/test_mcp_surface.py` proves the policy and `tests/test_mcp_server_wire.py`
proves the wiring, both in-process and in milliseconds. Neither answers the question that matters for the
subagent use case: if another agent connects to this server and asks it to run a simulation, does a
simulation happen? Answering that needs Docker, a real container, and ten-plus minutes per generation — so
it is a script an operator runs deliberately, not something CI should ever start.

WHAT IT CHECKS, in order, and each is a claim that was previously only argued:

  1. DEFAULT — `run_experiment` is neither advertised nor callable. The negative control. Without it a pass
     on (3) would only show that the flag is unnecessary.
  2. VISIBILITY IS NOT PERMISSION — with `CELLARIUM_MCP_EXPOSE_ALL=1` AND `CELLARIUM_MCP_ALLOW_WRITES=1`
     set together, `run_experiment` is STILL absent and still refused. This is the "nobody reaches a launch
     by asking for visibility" claim, checked over the wire rather than against the policy function.
  3. UNATTENDED — with `CELLARIUM_MCP_DANGEROUSLY_ALLOW_ALL=1`, two simulations run to completion and
     return real results. No human approves anything at any point; the only consent is the env var, granted
     in advance.
  4. BIOSECURITY SURVIVES IT — a design the screen flags comes back `biosecurity_hold`, in the same session
     that just launched successfully. The gate that is NOT ours to lift, demonstrated live rather than
     stubbed.

    python scripts/verify_mcp_end_to_end.py            # ~25 min: two 1-generation runs
    python scripts/verify_mcp_end_to_end.py --dry-run  # seconds: everything except the launches
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def _env(**overrides) -> dict:
    """A clean server environment: every gate flag explicitly absent unless this call sets it."""
    from cellarium import mcp
    env = {k: v for k, v in os.environ.items()
           if k not in (mcp.EXPOSE_ALL_ENV, mcp.ALLOW_WRITES_ENV, mcp.ALLOW_ALL_ENV)}
    env["PYTHONPATH"] = str(ROOT / "src")
    env.update(overrides)
    return env


async def _with_server(env: dict, body, timeout_s: float = 60.0):
    """One server subprocess, one session, one body of checks.

    `read_timeout_seconds` takes a NUMBER in SDK 2.x, not the `timedelta` older examples pass — handing it
    a timedelta fails inside anyio with an opaque `float + timedelta` TypeError during initialize, which
    reads like a protocol problem and is not one. It matters here because the default timeout is far
    shorter than a simulation.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=["-m", "cellarium.mcp"], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w, read_timeout_seconds=float(timeout_s)) as s:
            await s.initialize()
            return await body(s)


def _payload(res) -> dict:
    """A tool result as a dict, whichever content shape the SDK used."""
    structured = getattr(res, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    for block in (res.content or []):
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"_text": text}
    return {}


# ---------------------------------------------------------------------------------------------------------

async def step_1_default_is_closed() -> None:
    print("\n1. DEFAULT — the negative control", flush=True)

    async def body(s):
        names = [t.name for t in (await s.list_tools()).tools]
        check("run_experiment is NOT advertised", "run_experiment" not in names, f"{len(names)} tools listed")
        try:
            res = await s.call_tool("run_experiment", {"perturbation": "wildtype"})
            check("calling it anyway does not run a simulation",
                  bool(getattr(res, "is_error", False)) or "status" not in _payload(res),
                  f"is_error={getattr(res, 'is_error', None)}")
        except Exception as exc:
            check("calling it anyway does not run a simulation", True, f"{type(exc).__name__}")

    await _with_server(_env(), body)


async def step_2_visibility_is_not_permission() -> None:
    """The claim the owner asked to see tested rather than asserted."""
    print("\n2. VISIBILITY IS NOT PERMISSION — both convenience flags on at once", flush=True)
    from cellarium import mcp

    async def body(s):
        names = [t.name for t in (await s.list_tools()).tools]
        check("the surface really did widen", len(names) > 50, f"{len(names)} tools listed")
        check("propose_experiment IS now permitted (the write key was set)", "propose_experiment" in names)
        for gated in sorted(mcp._NEVER):
            check(f"{gated} is still withheld", gated not in names)
        # The sharp form of the claim now that `run_experiment` is correctly classified as a lookup:
        # the one tool that can START something must be absent AND refused with both convenience flags on.
        check("run_simulation_now is NOT advertised", "run_simulation_now" not in names)
        try:
            res = await s.call_tool("run_simulation_now", {"perturbation": "wildtype"})
            payload = _payload(res)
            check("run_simulation_now is refused, not run",
                  bool(getattr(res, "is_error", False)) or payload.get("status") != "ran",
                  str(payload)[:110])
        except Exception as exc:
            check("run_simulation_now is refused, not run", True, type(exc).__name__)

        # `run_experiment` IS now reachable here, and that is correct — it launches nothing.
        res = await s.call_tool("run_experiment", {"perturbation": "wildtype", "condition": "basal"})
        status = _payload(res).get("status")
        check("run_experiment is reachable and is only a lookup", status in ("in_corpus",
              "in_envelope_uncached", "refused", "biosecurity_hold"), f"status={status!r}")

    await _with_server(_env(**{mcp.EXPOSE_ALL_ENV: "1", mcp.ALLOW_WRITES_ENV: "1"}), body)


async def step_3_unattended_actually_runs(n_runs: int, timeout_s: float) -> None:
    """⚠️ THE FIRST VERSION OF THIS STEP PASSED WITHOUT RUNNING ANYTHING.

    It called `run_experiment`, which sounds like the launcher, and accepted any status other than
    `refused`/`biosecurity_hold` as a launch. The real reply was `status: in_corpus` in 0.0 minutes:
    `run_experiment` is a LOOKUP — it validates a design, screens it, and reports whether the corpus already
    answers the question. Nothing in `tools.TOOLS` starts a simulation at all. A green check for a claim
    that was false, which is worse than no check. `run_simulation_now` was written in response and is the
    only tool on the surface that launches; the assertion below now demands `status == "ran"` and a
    non-trivial wall time rather than merely "not a refusal".
    """
    print("")
    print(f"3. UNATTENDED — {n_runs} real simulation(s), nobody approving anything", flush=True)
    from cellarium import mcp

    async def body(s):
        names = [t.name for t in (await s.list_tools()).tools]
        check("run_simulation_now is advertised", "run_simulation_now" in names, f"{len(names)} tools listed")

        for i in range(n_runs):
            t0 = time.time()
            res = await s.call_tool("run_simulation_now", {
                "perturbation": "wildtype", "condition": "basal", "seeds": 1, "generations": 1,
                # A real run, kept OUT of the corpus: the claim being tested is that a simulation happened,
                # not that the corpus grew, and a verification should not quietly add rows to a curated
                # artifact.
                "append_manifest": False})
            payload = _payload(res)
            mins = (time.time() - t0) / 60
            ran = payload.get("status") == "ran" and (payload.get("n_runs") or 0) > 0
            check(f"simulation {i + 1} of {n_runs} RAN over the wire", ran,
                  f"status={payload.get('status')!r}, n_runs={payload.get('n_runs')}, {mins:.1f} min")
            if ran:
                check(f"simulation {i + 1} took real compute (not a cache hit)", mins > 0.25,
                      f"{mins:.1f} min")
                print(f"        ids: {payload.get('result_ids')}", flush=True)
            else:
                print(f"        payload: {json.dumps(payload, default=str)[:500]}", flush=True)

    await _with_server(_env(**{mcp.ALLOW_ALL_ENV: "1"}), body, timeout_s=timeout_s)


async def step_4_biosecurity_survives_unattended_mode() -> None:
    """Live, in the same configuration that just launched.

    ⚠️ ALSO CORRECTED. The first version used `KO:marR` as the flagged design and passed — on the ENVELOPE
    check, because `KO:marR` is not a valid perturbation NAME (the vocabulary is `gene_knockout` with the
    gene in params), so the screen never ran. A check named "biosecurity" that demonstrates the envelope is
    mislabelled evidence. The design below passes the envelope and trips the screen: `tf_activity` targeting
    `marA` is an UP direction on the amr_efflux signature, where a knockout would be exempt.
    """
    print("")
    print("4. BIOSECURITY — the gate unattended mode cannot lift", flush=True)
    from cellarium import biosecurity, envelope, mcp
    from cellarium.model import Design

    design = Design(perturbation="tf_activity", condition="basal", seeds=1, generations=1,
                    params={"target_tfs": ["marA"]})
    check("the probe design is INSIDE the envelope (so the screen is what fires)",
          envelope.check(design).in_envelope)
    v = biosecurity.screen(design)
    check("the probe design trips the screen locally", v.flagged,
          f"signature={v.signature!r} severity={getattr(v, 'severity', None)!r}")

    async def body(s):
        res = await s.call_tool("run_simulation_now", {
            "perturbation": "tf_activity", "condition": "basal", "seeds": 1, "generations": 1,
            "params": {"target_tfs": ["marA"]}, "append_manifest": False})
        payload = _payload(res)
        check("the launcher holds it BEFORE running", payload.get("status") == "biosecurity_hold",
              f"status={payload.get('status')!r} signature={payload.get('signature')!r}")
        check("and it is held for the right reason", payload.get("signature") == v.signature,
              f"{payload.get('signature')!r} vs {v.signature!r}")

    await _with_server(_env(**{mcp.ALLOW_ALL_ENV: "1"}), body, timeout_s=300)


async def main_async(args) -> int:
    try:
        import mcp as _sdk  # noqa: F401
    except ImportError:
        print('needs the SDK: pip install "cellarium[mcp]"', file=sys.stderr)
        return 2

    await step_1_default_is_closed()
    await step_2_visibility_is_not_permission()
    if args.dry_run:
        print("\n3. UNATTENDED — SKIPPED (--dry-run)")
        print("4. BIOSECURITY — SKIPPED (--dry-run)")
    else:
        await step_3_unattended_actually_runs(args.runs, args.timeout)
        await step_4_biosecurity_survives_unattended_mode()

    print("\n" + "=" * 78)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"MCP END-TO-END: {passed}/{len(RESULTS)} checks passed")
    for n, ok, _ in RESULTS:
        if not ok:
            print(f"  FAIL  {n}")
    return 0 if passed == len(RESULTS) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2, help="how many real simulations to launch (default 2)")
    ap.add_argument("--timeout", type=float, default=3600, help="per-call timeout in seconds")
    ap.add_argument("--dry-run", action="store_true", help="everything except the launches")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
