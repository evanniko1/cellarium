"""The first-class Hypothesis object — the Socratic Council's deliverable.

A user's question enters vague; the Council (council.py) runs a proposer/skeptic/judge elenchus and emits ONE
of these: a falsifiable, operationalized, instrumentally-testable hypothesis that carries the whole
discovery->justification bridge. `agent.run(question, hypothesis=...)` then does the actual testing.

See docs/SOCRATIC_COUNCIL.md for the philosophy-of-science rationale (Popper falsifiability, Bridgman
operationalism, Platt/Chamberlin rival hypotheses, Duhem-Quine auxiliary assumptions).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .model import Design


class OperationalDef(BaseModel):
    """A construct bound to a measurement — Bridgman operationalism: the construct MEANS these operations."""

    model_config = ConfigDict(populate_by_name=True)

    # `construct` is the natural word (and the LLM-facing key) but shadows BaseModel.construct; alias keeps the
    # external name while the attribute is `term`.
    term: str = Field(alias="construct")   # the informal term, e.g. "behave differently"
    observable: str                        # a real Cellarium dial label — a channel name or species id
    measure: str                           # the operation on it, e.g. "coefficient of variation across seeds"


class Falsifier(BaseModel):
    """What result would refute the hypothesis — a rigor.disconfirm(target, reference, channel) call spec plus
    the decision rule that reads its output. This is Popper's risky prohibition, made executable."""

    target: str             # design label 'perturbation/condition'
    reference: str          # the null/baseline design label
    channel: str            # the observable tested (a dial label)
    decision_rule: str      # e.g. "reject H0 if welch_t >= 2 AND effect direction is positive"
    refuting_result: str    # the concrete outcome that would falsify H1, e.g. "welch_t < 2 (within replicate noise)"


class Rival(BaseModel):
    """A competing explanation that the decisive test must exclude — Chamberlin's multiple working hypotheses /
    Platt's strong inference. `distinguishing_result` is what the sim would show if THIS rival were true."""

    claim: str
    distinguishing_result: str


class Hypothesis(BaseModel):
    """The Council's output: a justification-ready hypothesis handed to the Cellarium agent."""

    question: str                                                   # the raw user question
    claim: str                                                      # natural-language H1
    h1: str                                                         # formalized alternative
    h0: str                                                         # formalized null
    operational_defs: list[OperationalDef] = Field(default_factory=list)
    predicted_effect: str = ""                                      # direction + rough magnitude
    falsifier: Falsifier | None = None
    rivals: list[Rival] = Field(default_factory=list)
    auxiliary_assumptions: list[str] = Field(default_factory=list)  # the Duhem-Quine belt, made explicit
    candidate_designs: list[Design] = Field(default_factory=list)   # already envelope/biosecurity-checked
    residual_ambiguities: list[str] = Field(default_factory=list)   # empty on clean convergence
    converged: bool = True                                          # False => returned at the round cap, best-effort

    def brief(self) -> str:
        """Compact justification brief injected into the grounded agent's context (agent.run)."""
        lines = [
            f"OPERATIONALIZED HYPOTHESIS (from the Socratic Council):",
            f"  Question:   {self.question}",
            f"  Claim (H1): {self.claim}",
            f"  H1: {self.h1}",
            f"  H0: {self.h0}",
            f"  Predicted effect: {self.predicted_effect}",
        ]
        for od in self.operational_defs:
            lines.append(f"  Operationalize: '{od.term}' -> {od.observable} ({od.measure})")
        if self.falsifier:
            f = self.falsifier
            lines.append(f"  Falsifier: disconfirm(target='{f.target}', reference='{f.reference}', "
                         f"channel='{f.channel}'); {f.decision_rule}; refuted if {f.refuting_result}")
        for r in self.rivals:
            lines.append(f"  Rival: {r.claim} -> distinguished by: {r.distinguishing_result}")
        for a in self.auxiliary_assumptions:
            lines.append(f"  Assumes (ceteris paribus): {a}")
        for d in self.candidate_designs:
            lines.append(f"  Candidate design: perturbation={d.perturbation} condition={d.condition} "
                         f"timeline={d.timeline} seeds={d.seeds} generations={d.generations} params={d.params}")
        if self.residual_ambiguities:
            lines.append("  Residual ambiguities (Council did NOT fully converge): "
                         + "; ".join(self.residual_ambiguities))
        return "\n".join(lines)
