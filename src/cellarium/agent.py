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
    "- Before interpreting a gene KO, call mechanistic_scope: if the gene is expressed-but-inert (no modeled "
    "function), a null phenotype is model scope, NOT biological dispensability — say so, don't over-read it.\n"
    "- For a KO, judge lethality by VIABILITY (viability tool: does the lineage divide?), NOT growth rate — a "
    "metabolic KO reroutes so growth looks flat even when the gene is essential. And 'viable' is the MODEL; check "
    "mechanistic_scope's benchmark — if agreement=='model_UNDER_predicts', the gene is essential in vivo, so trust "
    "the benchmark over the sim.\n"
    "- To EXPLAIN why a viable metabolic KO shows no phenotype, use reroute_diagnosis: if reroute_is_artifact, the "
    "model bypasses an enzyme real biology can't (the objective never hard-requires that flux). To PROPOSE an "
    "experiment, call design_space first (runnable conditions/variants + the gene's ko_index) — don't guess indices.\n"
    "- READ COLD. Derive conclusions from tool results only. Do not assume anything from earlier conversation, "
    "external notes, or 'what we expected' — if a prior claim conflicts with the tools, the tools win. State "
    "how many runs/designs support each claim; don't generalise from a subset the survey shows is larger.\n"
    "- IN- vs OUT-OF-SAMPLE. Before saying the model 'predicts' or 'validates' anything, call provenance: a "
    "fitted condition (in_sample) agreeing with data is only CONSISTENCY; genuine prediction lives in "
    "out_of_sample perturbations (clamps, KOs, shifts). Never oversell in-sample agreement.\n"
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


def run(question: str, *, hypothesis=None, max_turns: int = 8, verbose: bool = True, on_tool=None) -> str:
    from . import rigor

    rigor.reset()  # fresh coverage tracking per question
    client = anthropic.Anthropic()
    if hypothesis is not None:
        # The Socratic Council has already operationalized the question into a falsifiable hypothesis; hand the
        # grounded agent that brief instead of the raw string. The agent still does ALL grounding itself — the
        # Council supplies a sharpened question, never a result (the docs/SOCRATIC_COUNCIL.md quarantine).
        brief = hypothesis.brief() if hasattr(hypothesis, "brief") else str(hypothesis)
        first = (f"{brief}\n\nTest this hypothesis against the corpus using the tools: survey first, then read "
                 f"exactly the falsifier's channel(s), seek disconfirmation, and report whether the evidence "
                 f"supports or refutes it — grounding every number in a tool result.")
    else:
        first = question
    messages: list[dict] = [{"role": "user", "content": first}]

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
            if on_tool is not None:
                on_tool(tu.name, tu.input, out)   # glass-box hook: stream the grounded tool trace to the interface
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(out)})
        messages.append({"role": "user", "content": results})

    return "(stopped: reached max turns)"
