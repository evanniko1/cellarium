"""The single orchestration seam — what the CLI and the hackathon interface both call.

Two entrypoints, ONE Cellarium agent behind them:

  - use_council=True  (TOP entry): the Socratic Council sharpens the raw question into a falsifiable,
    operationalized Hypothesis, then hands that brief to the grounded agent. The Council never sees a
    reading — instrument.py is quarantined from every result-bearing surface (docs/SOCRATIC_COUNCIL.md).
  - use_council=False (DIRECT entry): the raw question goes straight to the agent — for targeted
    read/analysis and the bottom-up, tool-refinement loop where the developer already knows what to measure.

Invariants this seam encodes:
  * Reading/analysing results is ALWAYS the agent's job, NEVER the Council's. The Council only shapes the
    QUESTION; it is architecturally forbidden from touching results. So no flow ever routes reads "through"
    the Council — the only thing that varies is whether the question was operationalized first.
  * Launching simulations is a SEPARATE action from asking a question. Its gating lives downstream and is
    orthogonal to this entry (see launch.py for the human-approval airlock, and model.run_live for the
    ungated, operator/eval path). Reads are never gated; launches may be, per policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Investigation:
    """The structured result the interface unpacks: the agent's grounded answer, plus the sharpened
    Hypothesis when the Council ran (None on the direct path)."""
    question: str
    used_council: bool
    answer: str
    hypothesis: Any | None = None       # a hypothesis.Hypothesis when used_council, else None
    brief: str | None = None            # hypothesis.brief() convenience, for interface display
    # The pre-dispatch capability decision (NMI-2). Always present when the gate ran, whatever it decided —
    # an `answer` verdict is as much a result as a refusal, and a caller that only sees refusals cannot tell
    # "the gate passed it" from "the gate never ran".
    decision: Any | None = None         # a gate.Decision
    gated: bool = False                 # True when the gate STOPPED the investigation before any tool call


def investigate(question: str, *, use_council: bool = True, rounds: int = 4, quota: int = 3,
                ask_user: Callable[[str], str] | None = None, on_hypothesis: Callable[[Any], None] | None = None,
                on_tool: Callable | None = None, max_turns: int = 8, verbose: bool = True,
                use_gate: bool = True, elongation_model: str | None = None,
                gate_parser: Callable[[str], Any] | None = None,
                on_decision: Callable[[Any], None] | None = None) -> Investigation:
    """Run one question end-to-end and return a structured result.

    use_council=True routes through the Socratic Council first (open questions that benefit from being
    operationalized); use_council=False hands the raw question straight to the agent (targeted analysis /
    tool-refinement). Either way the SAME grounded agent does all the reading — grounding every number in a
    tool result. Imports are lazy so callers can set env (ANTHROPIC_API_KEY) before this fires.

    on_hypothesis, if given, is called with the converged Hypothesis after the Council runs but BEFORE the
    agent starts — so a CLI can stream the brief, or the interface can render it in its own panel.

    use_gate=False disables the pre-dispatch capability check. It exists for the ablation that measures what
    the gate buys and for offline tests, NOT as a way to get an answer the registry would refuse: the same
    refusal remains reachable through `model_capabilities` downstream. `elongation_model` conditions the
    decision on the mode the run would use (default: the mode every corpus row was produced in).
    `gate_parser` substitutes the question→requirement step, which is how a test runs the gate with no
    network and how the eval scores a parser against frozen labels.
    """
    hyp = None
    if use_council:
        from .council import deliberate
        hyp = deliberate(question, max_rounds=rounds, quota=quota, ask_user=ask_user, verbose=verbose)
        if on_hypothesis is not None:
            on_hypothesis(hyp)

    # ---- the pre-dispatch capability gate (NMI-2) --------------------------------------------------------
    # PLACEMENT IS THE POINT. This sits between the question and `agent.run`, which is the only thing that
    # dispatches tools, so there is no path through this seam that reaches a tool without having been
    # decided. Previously the registry was reachable only through `model_capabilities` — a tool the model
    # elects to call — so "the language model cannot override a refusal" was not true as written.
    #
    # The Council runs BEFORE the gate deliberately. It reads no results and touches no corpus, so it cannot
    # smuggle an answer past anything; and letting it sharpen a vague question first means the gate decides
    # on an operationalised requirement rather than on a paraphrase, which is the harder and fairer test.
    decision = None
    if use_gate:
        from . import gate as _gate
        decision = _gate.gate(question, mode=elongation_model, parser=gate_parser)
        if on_decision is not None:
            on_decision(decision)
        if decision.verdict != "answer":
            # Stop here. Not a failure and not an error: a refusal naming the missing mechanism, or a
            # proposal naming the run that would settle it, is the result.
            return Investigation(question=question, used_council=use_council,
                                 answer=_gate.render(decision), hypothesis=hyp,
                                 brief=hyp.brief() if (hyp is not None and hasattr(hyp, "brief")) else None,
                                 decision=decision, gated=True)

    from .agent import run  # imported late so the API key is present in env
    answer = run(question, hypothesis=hyp, max_turns=max_turns, verbose=verbose, on_tool=on_tool)

    brief = hyp.brief() if (hyp is not None and hasattr(hyp, "brief")) else None
    return Investigation(question=question, used_council=use_council, answer=answer,
                         hypothesis=hyp, brief=brief, decision=decision, gated=False)
