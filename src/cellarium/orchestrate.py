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


def investigate(question: str, *, use_council: bool = True, rounds: int = 4, quota: int = 3,
                ask_user: Callable[[str], str] | None = None, on_hypothesis: Callable[[Any], None] | None = None,
                max_turns: int = 8, verbose: bool = True) -> Investigation:
    """Run one question end-to-end and return a structured result.

    use_council=True routes through the Socratic Council first (open questions that benefit from being
    operationalized); use_council=False hands the raw question straight to the agent (targeted analysis /
    tool-refinement). Either way the SAME grounded agent does all the reading — grounding every number in a
    tool result. Imports are lazy so callers can set env (ANTHROPIC_API_KEY) before this fires.

    on_hypothesis, if given, is called with the converged Hypothesis after the Council runs but BEFORE the
    agent starts — so a CLI can stream the brief, or the interface can render it in its own panel.
    """
    hyp = None
    if use_council:
        from .council import deliberate
        hyp = deliberate(question, max_rounds=rounds, quota=quota, ask_user=ask_user, verbose=verbose)
        if on_hypothesis is not None:
            on_hypothesis(hyp)

    from .agent import run  # imported late so the API key is present in env
    answer = run(question, hypothesis=hyp, max_turns=max_turns, verbose=verbose)

    brief = hyp.brief() if (hyp is not None and hasattr(hyp, "brief")) else None
    return Investigation(question=question, used_council=use_council, answer=answer,
                         hypothesis=hyp, brief=brief)
