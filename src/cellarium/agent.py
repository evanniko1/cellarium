"""The Claude tool-using loop (Anthropic Messages API).

The agent answers whole-cell questions strictly through the grounded tools, enforces the feasibility +
QC guardrails, and never reports a number it did not read from a tool result.
"""

from __future__ import annotations

import json
import os

import anthropic

from . import tools

MODEL = os.environ.get("CELLARIUM_MODEL", "claude-sonnet-4-5")

SYSTEM = (
    "You are Cellarium, a copilot for reasoning over a whole-cell E. coli simulation (K-12 MG1655).\n"
    "Rules:\n"
    "- Ground every quantitative claim in a tool result (list_results, read_series). Never state a number "
    "you did not read from a tool. If you cannot ground it, say so.\n"
    "- Before proposing to run anything, call check_feasibility. If a design is out of the validated "
    "envelope (e.g. a mid-run carbon-source switch), do NOT run it — explain why and offer the in-envelope "
    "alternative the tool suggests.\n"
    "- Treat any run whose QC is not 'ok' (over_replicated, degenerate, no_division, dead, fba_infeasible) "
    "as evidence-absent: report the QC flag, never a doubling time derived from it.\n"
    "- The model gives the dynamic/regulatory/single-cell regime that steady-state FBA cannot. Prefer "
    "mechanistic explanation (e.g. ppGpp -> ribosome allocation -> growth) grounded in the channels.\n"
    "- Be concise and honest. Users are hypothesis generators, not decision-makers."
)


def run(question: str, *, max_turns: int = 8, verbose: bool = True) -> str:
    client = anthropic.Anthropic()
    messages: list[dict] = [{"role": "user", "content": question}]

    for _ in range(max_turns):
        resp = client.messages.create(
            model=MODEL, max_tokens=1500, system=SYSTEM, tools=tools.TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]

        if resp.stop_reason != "tool_use" or not tool_uses:
            return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()

        results = []
        for tu in tool_uses:
            out = tools.dispatch(tu.name, tu.input)
            if verbose:
                print(f"  ⌥ {tu.name}({json.dumps(tu.input)}) -> {json.dumps(out)[:160]}")
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(out)})
        messages.append({"role": "user", "content": results})

    return "(stopped: reached max turns)"
