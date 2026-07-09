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
    "- SURVEY FIRST. For any question about results, call survey_corpus BEFORE forming a hypothesis, and "
    "reason from that whole ranked view. Do NOT anchor on the first run you look at or on the biggest single "
    "number — the survey ranks every design by computed effect size so your attention isn't what decides what "
    "matters. Only after the survey, drill in with read_series / read_species.\n"
    "- To interpret a KO/perturbation, use differential (what channels/pathways moved most vs control) and "
    "top_movers (which individual proteins) — do NOT pre-decide which molecules matter; let the data rank them.\n"
    "- READ COLD. Derive conclusions from tool results only. Do not assume anything from earlier conversation, "
    "external notes, or 'what we expected' — if a prior claim conflicts with the tools, the tools win. State "
    "how many runs/designs support each claim; don't generalise from a subset the survey shows is larger.\n"
    "- SEEK DISCONFIRMATION. Before committing to a causal claim, call disconfirm on it (is the effect bigger "
    "than replicate noise? does another design contradict it?), and call coverage_check before generalising — "
    "do not claim beyond the designs you actually deep-read. After forming a hypothesis, name what would "
    "falsify it and read exactly those "
    "channels/designs before concluding (e.g. to test 'ppGpp causes the slowdown', check ribosome_conc AND a "
    "design where ppGpp is decoupled).\n"
    "- Ground every quantitative claim in a tool result. Never state a number you did not read from a tool.\n"
    "- Before proposing to run anything, call check_feasibility AND screen_design. If out of the validated "
    "envelope (e.g. a mid-run carbon-source switch) or flagged by the biosecurity screen, do NOT run it — "
    "explain why and offer the in-envelope alternative. For a design ALREADY in the corpus, also call "
    "screen_phenotype: its simulated proteome can up-regulate a misuse signature (AMR efflux) even if the "
    "design never named those genes — flag that too.\n"
    "- Treat any run whose QC is not 'ok' (over_replicated, degenerate, no_division, dead, fba_infeasible) "
    "as evidence-absent: report the QC flag, never a doubling time derived from it.\n"
    "- The model gives the dynamic/regulatory/single-cell regime that steady-state FBA cannot. Prefer "
    "mechanistic explanation (e.g. ppGpp -> ribosome allocation -> growth) grounded in the channels.\n"
    "- Be concise and honest. Users are hypothesis generators, not decision-makers."
)


def run(question: str, *, max_turns: int = 8, verbose: bool = True) -> str:
    from . import rigor

    rigor.reset()  # fresh coverage tracking per question
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
