"""NMI-1 / NMI-2 — the pre-dispatch capability gate: parse the question, consult the registry, decide.

WHAT WAS MISSING, stated precisely because the paper described it in the present tense before it existed.
`capability.check` has always been correct. What did not exist was anything that CALLED it on a path the
model could not elect to skip: the registry was reachable only through `model_capabilities`, a tool the model
chooses to use. So the system's answer to "can this model represent what you just asked?" was consulted when
the model remembered to consult it. This module is the missing front half, and `orchestrate.investigate` is
where it is placed, between parsing the question and dispatching the first tool.

THE DIVISION OF LABOUR IS THE WHOLE DESIGN. The language model extracts WHAT THE QUESTION ASKS FOR; it never
decides whether that is answerable. Extraction is a reading-comprehension task models are good at. The
decision is a table lookup against records derived from the simulator's source, and it is deterministic, so a
model cannot talk its way past a refusal, cannot be persuaded that a missing mechanism is present, and
produces the same verdict twice for the same requirement. Had the parser been allowed to return a verdict,
the registry would be decoration.

GRANULARITY IS THE FIELD THAT DOES THE WORK. Every failure in the capability registry is a granularity claim:
86 columns carrying 20 distinct values, 86 abundances derived from ~44 measurements. "Charged fraction" is
answerable; "charged fraction PER ISOACCEPTOR" is not. Same entity, same intervention, same observable --
different granularity, opposite verdict. The six-field requirement exists to make that difference
representable, and the near-neighbour pairs in the benchmark differ in exactly this field.

THREE OUTCOMES, NOT TWO, and the third is the one the system handled worst. `answer` when the mechanism is
represented and runs exist. `refuse` when the simulator cannot represent the requirement -- a permanent fact
about the model that more compute will not change. `propose` when the mechanism IS represented but no run
exists to read: a DATA gap, where the honest response is a design rather than a refusal. Collapsing propose
into refuse rewards stonewalling -- on an empty corpus every question becomes this case, and a system that
refused everything would score perfectly.

WHAT THE GATE WILL NOT DO, and this is load-bearing. It never refuses from ignorance. An observable it cannot
map to any declared capability yields `answer` with a note, never `refuse`, because an undeclared mechanism
is not evidence of absence -- the same rule `capability.check` already follows for an unknown key. A gate
that refused whatever it did not recognise would be a keyword filter wearing a registry's clothes, and would
get worse as the registry grew more specific.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from . import capability as C

# ---------------------------------------------------------------------------------------------------------
# The controlled vocabulary. It is SMALL and it is derived from the registry rather than invented alongside
# it: every value below appears on at least one Capability, so the parser cannot name a target the lookup
# cannot resolve. `other` is deliberate and is the escape hatch the ignorance rule above depends on.
# ---------------------------------------------------------------------------------------------------------

OBSERVABLES: tuple[str, ...] = (
    "trna_charging", "trna_abundance", "elongation", "ppgpp", "amino_acid_uptake",
    "rrna_transcription", "media_response", "gene_knockout", "other",
)

GRANULARITIES: tuple[str, ...] = (
    "aggregate",          # one number for the cell
    "per_amino_acid",     # resolved by amino acid (20)
    "per_isoacceptor",    # resolved by tRNA gene / isoacceptor (86)
    "per_codon",          # resolved by codon
    "per_operon",         # resolved by a named operon
    "per_gene",           # resolved by a named gene
    "other",
)

# (observable, granularity) -> the capability keys a question at that resolution REQUIRES.
# Deliberately a table rather than a search over `Capability.question` prose: a lookup that matched on words
# would refuse or admit on phrasing, which is the keyword-filter failure this module exists to avoid.
REQUIRES: dict[tuple[str, str], tuple[str, ...]] = {
    ("trna_charging", "aggregate"): ("per_amino_acid_trna_charging",),
    ("trna_charging", "per_amino_acid"): ("per_amino_acid_trna_charging",),
    ("trna_charging", "per_isoacceptor"): ("per_isoacceptor_trna_charging",),
    ("trna_charging", "per_gene"): ("per_isoacceptor_trna_charging",),
    ("trna_charging", "per_codon"): ("per_isoacceptor_trna_charging", "codon_level_elongation"),
    ("trna_abundance", "per_isoacceptor"): ("per_gene_trna_abundance",),
    ("trna_abundance", "per_gene"): ("per_gene_trna_abundance",),
    ("elongation", "per_codon"): ("codon_level_elongation",),
    ("elongation", "aggregate"): (),
    ("ppgpp", "aggregate"): ("ppgpp_stringent_response",),
    ("amino_acid_uptake", "aggregate"): ("amino_acid_uptake_from_the_medium",),
    ("rrna_transcription", "per_operon"): ("operon_specific_rrna_knockout",),
    ("rrna_transcription", "aggregate"): (),
    # An operon knockout is usually PHRASED as a knockout, so the parser reasonably returns
    # observable=gene_knockout (or, for a question about its effect on translation, elongation). Without
    # these rows the pair is unmapped, the ignorance rule fires, and an unanswerable question is admitted.
    # Found by `scripts/run_gate_eval.py` on its first full run: all 7 under-refusals in 216 items were this
    # one gap, across 4 framings of the same cell.
    ("gene_knockout", "per_operon"): ("operon_specific_rrna_knockout",),
    ("elongation", "per_operon"): ("operon_specific_rrna_knockout",),
    ("media_response", "aggregate"): ("nutrient_shift_timelines",),
    ("gene_knockout", "per_gene"): ("knockout_of_a_multi_transcription_unit_gene",),
}

# A starvation / stringent-response dependency pulls in the alarmone coupling even when the question's own
# observable does not name it. This is the second half of the tRNA case: per-isoacceptor charging UNDER
# STARVATION needs two capabilities that live in different modes, and a gate that checked only the observable
# would admit the question and let the agent discover the conflict downstream, which is too late.
DEPENDENCY_REQUIRES: dict[str, tuple[str, ...]] = {
    "stringent_response": ("ppgpp_stringent_response",),
    "amino_acid_starvation": ("ppgpp_stringent_response",),
    "amino_acid_supply": ("amino_acid_uptake_from_the_medium",),
    "nutrient_shift": ("nutrient_shift_timelines",),
}


@dataclass(frozen=True)
class Requirement:
    """What a question demands OF THE MODEL, as six fields rather than a sentence."""

    entity: str = ""
    intervention: str = ""
    observable: str = "other"
    granularity: str = "other"
    regulatory_dependencies: tuple[str, ...] = ()
    evidence_coverage: str = ""
    raw_question: str = ""
    parser: str = ""                      # which backbone produced this, or "manual"

    def normalised(self) -> "Requirement":
        """Coerce the two controlled fields into the vocabulary; anything unrecognised becomes `other`,
        which routes to the ignorance rule rather than to a refusal."""
        o = self.observable if self.observable in OBSERVABLES else "other"
        g = self.granularity if self.granularity in GRANULARITIES else "other"
        return Requirement(self.entity, self.intervention, o, g,
                           tuple(self.regulatory_dependencies), self.evidence_coverage,
                           self.raw_question, self.parser)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    """The gate's verdict, with everything needed to audit it after the fact."""

    verdict: str                                   # answer | refuse | propose
    mode: str
    requirement: Requirement
    required_capabilities: tuple[str, ...] = ()
    rows: tuple[dict, ...] = ()                    # the capability.check results actually consulted
    blocking: tuple[str, ...] = ()                 # keys whose absence drove a refusal
    reason: str = ""
    route: str = ""                                # the mode that WOULD answer it, when one exists
    proposal: dict | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["requirement"] = self.requirement.to_dict()
        return d


# ---------------------------------------------------------------------------------------------------------
# 1. the lookup -- deterministic, and the only thing permitted to decide answerability
# ---------------------------------------------------------------------------------------------------------

# A narrow fallback on GRANULARITY ALONE, for granularities whose resolution the simulator does not preserve
# whatever quantity is being asked about. Only `per_operon` qualifies: operon identity is destroyed by the
# rebalancing step after the variant runs, so a question at that resolution is unanswerable regardless of
# which observable it names. It is deliberately not extended to the finer tRNA granularities, because those
# ARE answerable under the kinetic model and a blanket rule would turn the gate into a keyword filter --
# refusing on the resolution word rather than on what the model computes.
GRANULARITY_FALLBACK: dict[str, tuple[str, ...]] = {
    "per_operon": ("operon_specific_rrna_knockout",),
}


def required_capabilities(req: Requirement) -> tuple[str, ...]:
    """Which registry keys this requirement needs. Order is stable so a decision is reproducible."""
    req = req.normalised()
    pair = (req.observable, req.granularity)
    keys: list[str] = list(REQUIRES.get(pair) or GRANULARITY_FALLBACK.get(req.granularity, ()))
    for dep in req.regulatory_dependencies:
        for k in DEPENDENCY_REQUIRES.get(dep, ()):
            if k not in keys:
                keys.append(k)
    return tuple(keys)


def modes_with_runs() -> tuple[str, ...]:
    """Elongation models the corpus actually holds runs in. Corpus-dependent, and deliberately separate from
    representability: `capability.check` must stay corpus-independent or a fresh clone would be walled."""
    return tuple(getattr(C, "MODES_IN_CORPUS", ("steady_state",)))


def representable(key: str, mode: str) -> bool | None:
    """Does the MODEL compute this under `mode` — independent of whether anyone has run it?

    THIS IS NOT `capability.answerable_in`, and the difference is the reason this function exists.
    `answerable_in` is a conjunction of three things: the mechanism is in the checkout, the mode implements
    it, AND the corpus holds runs in that mode. That is the right predicate for "can the agent answer this
    right now", which is what it was written for. It is the wrong one here, because folding data coverage
    into representability collapses `propose` into `refuse`: every capability reads as absent under
    `coarse_kinetic` purely because no run has used that mode, and the gate would tell a user the simulator
    cannot represent a nutrient shift when it represents it in all three modes.

    None means undetermined — an unknown key or an undeclared mode — and is never treated as absent.
    """
    cap = C._BY_KEY.get(key)
    if cap is None or mode not in C.ELONGATION_MODES:
        return None
    return bool(cap.present and mode in cap.holds_in)


def _modes_representing_all(keys: tuple[str, ...]) -> tuple[str, ...]:
    """Every elongation model under which ALL of `keys` are represented at once."""
    return tuple(m for m in C.ELONGATION_MODES
                 if all(representable(k, m) for k in keys if k in C._BY_KEY))


def decide(req: Requirement, mode: str | None = None) -> Decision:
    """Requirement -> answer / refuse / propose. No model is consulted here, by design."""
    req = req.normalised()
    mode = mode or C.DEFAULT_MODE
    keys = required_capabilities(req)
    d = Decision(verdict="answer", mode=mode, requirement=req, required_capabilities=keys)

    if not keys:
        d.notes.append(
            f"no declared capability covers observable={req.observable!r} at granularity={req.granularity!r}; "
            "proceeding, because an undeclared mechanism is not evidence of absence")
        return d

    # `check` is consulted for its PROSE — the mode-keyed sentence describing what the model does instead,
    # which is the part a refusal must carry. The VERDICT comes from `representable`, which does not fold in
    # data coverage.
    d.rows = tuple(C.check(k, mode) for k in keys)

    verdicts = {k: representable(k, mode) for k in keys}
    blocking = [k for k, v in verdicts.items() if v is False]
    unknown = [k for k, v in verdicts.items() if v is None]
    if unknown:
        d.notes.append(f"undetermined for {unknown} (unknown key or mode) — not treated as absent")

    if blocking:
        d.verdict = "refuse"
        d.blocking = tuple(blocking)
        d.reason = "\n\n".join(
            str(r.get("refusal") or f"{r['capability']} is not represented in {mode}")
            for r in d.rows if r["capability"] in blocking)

        # A route must satisfy EVERY requirement at once. Naming a mode that fixes one blocker while
        # breaking another is the tRNA case, and reporting it as a route would be worse than silence.
        common = _modes_representing_all(keys)
        with_runs = [m for m in common if m in modes_with_runs()]
        if with_runs:
            d.route = with_runs[0]
            d.notes.append(f"all required capabilities are represented together in {d.route}, "
                           "and the corpus holds runs in it")
        elif common:
            d.route = common[0]
            d.notes.append(f"all required capabilities are represented together in {d.route}, "
                           "but no run exists in that mode — answering would need a new simulation")
        else:
            d.notes.append("no single elongation model represents every requirement at once")
        return d

    # Represented. Is there anything to read?
    runs = modes_with_runs()
    if mode not in runs:
        d.verdict = "propose"
        d.reason = (f"every required capability is represented under {mode}, but the corpus holds no runs in "
                    f"that mode (runs exist in: {', '.join(runs) or 'none'}). This is a data gap, not a "
                    f"limit of the model.")
        d.proposal = {"elongation_model": mode, "needs": list(keys),
                      "why": "the question is representable here; what is missing is a run to read"}
        return d

    d.reason = f"all required capabilities are represented in {mode} and the corpus holds runs in it"
    return d


# ---------------------------------------------------------------------------------------------------------
# 2. the parser -- the only place a language model is involved, and it never returns a verdict
# ---------------------------------------------------------------------------------------------------------

_PARSE_TOOL = {
    "name": "state_requirement",
    "description": "State what the question REQUIRES OF THE SIMULATOR. Do not judge whether it is answerable.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity": {"type": "string", "description": "what the question is about (a gene, a tRNA family, the cell)"},
            "intervention": {"type": "string", "description": "the perturbation or condition applied, '' if none"},
            "observable": {"type": "string", "enum": list(OBSERVABLES),
                           "description": "the quantity to be read. 'other' when none of these fits -- say "
                                          "other rather than forcing a near match."},
            "granularity": {"type": "string", "enum": list(GRANULARITIES),
                            "description": "the RESOLUTION the question demands of that quantity. This is the "
                                           "field that decides most questions: 'what fraction of leucine tRNA "
                                           "is charged' is per_amino_acid, 'which leucine isoacceptor stays "
                                           "charged' is per_isoacceptor. Choose the FINEST resolution the "
                                           "question actually requires, never finer."},
            "regulatory_dependencies": {"type": "array", "items": {"type": "string",
                                        "enum": list(DEPENDENCY_REQUIRES)},
                                        "description": "mechanisms the answer rides on even if unnamed, e.g. a "
                                                       "starvation question depends on stringent_response"},
            "evidence_coverage": {"type": "string",
                                  "description": "what would have to exist to support an answer, in one clause"},
        },
        "required": ["entity", "intervention", "observable", "granularity", "regulatory_dependencies",
                     "evidence_coverage"],
    },
}

_PARSE_SYSTEM = (
    "You extract what a scientific question REQUIRES OF A SIMULATOR. You do not answer the question, and you "
    "do not decide whether it can be answered -- a separate deterministic check does that, and it will be "
    "wrong if you pre-empt it. Extract only what was asked.\n\n"
    "The field that matters most is `granularity`: the resolution the question demands. Pick the finest "
    "resolution the question genuinely needs and no finer. A question about a whole amino-acid family is "
    "per_amino_acid; a question that compares two tRNAs carrying the SAME amino acid is per_isoacceptor; a "
    "question about one named gene's own transcript is per_gene. If the question names no resolution, it is "
    "aggregate."
)


def parse(question: str, *, model: str | None = None, client: Any = None) -> Requirement:
    """Question -> Requirement via one structured model call. Falls back to an `other` requirement on any
    failure, which routes to the ignorance rule and proceeds, rather than refusing because parsing broke."""
    model = model or os.environ.get("CELLARIUM_GATE_MODEL", "claude-opus-4-8")
    try:
        if client is None:
            from . import llm
            # Through the seam rather than constructing a provider client here: the seam carries the
            # provider choice and the agent's retry policy, and `test_llm_seam` pins that no runtime
            # module reaches past it.
            client = llm.client(max_retries=4)
        resp = client.messages.create(
            model=model, max_tokens=1024, system=_PARSE_SYSTEM, tools=[_PARSE_TOOL],
            tool_choice={"type": "tool", "name": "state_requirement"},
            messages=[{"role": "user", "content": question}])
        block = next(b for b in resp.content if getattr(b, "type", "") == "tool_use")
        d = block.input if isinstance(block.input, dict) else json.loads(block.input)
        return Requirement(
            entity=str(d.get("entity", "")), intervention=str(d.get("intervention", "")),
            observable=str(d.get("observable", "other")), granularity=str(d.get("granularity", "other")),
            regulatory_dependencies=tuple(d.get("regulatory_dependencies") or ()),
            evidence_coverage=str(d.get("evidence_coverage", "")),
            raw_question=question, parser=model).normalised()
    except Exception as e:                                       # noqa: BLE001 -- the cause belongs in the note
        return Requirement(raw_question=question, parser=f"{model} (failed: {type(e).__name__})").normalised()


# ---------------------------------------------------------------------------------------------------------
# 3. the gate -- parse, decide, and say it in one call
# ---------------------------------------------------------------------------------------------------------

def gate(question: str, *, mode: str | None = None, model: str | None = None, client: Any = None,
         parser: Callable[[str], Requirement] | None = None) -> Decision:
    """The entry point `orchestrate` calls before dispatching anything."""
    req = (parser(question) if parser is not None else parse(question, model=model, client=client))
    return decide(req, mode=mode)


def render(d: Decision) -> str:
    """The user-facing text for a decision that stops the investigation. Names the mechanism, never the
    phrasing -- a refusal that blamed the question would be the over-refusal failure in a new costume."""
    if d.verdict == "answer":
        return ""
    head = {"refuse": "This model cannot represent what the question asks.",
            "propose": "This model can represent what the question asks, but no run exists to read."}[d.verdict]
    out = [head, "", f"Requirement: {d.requirement.observable} at {d.requirement.granularity}"
                     f" under elongation model '{d.mode}'."]
    if d.reason:
        out += ["", d.reason]
    if d.verdict == "refuse" and d.route:
        out += ["", f"It is representable under the '{d.route}' elongation model."]
    elif d.verdict == "refuse" and d.blocking:
        out += ["", "No single elongation model in this checkout satisfies every requirement at once."]
    if d.verdict == "propose" and d.proposal:
        out += ["", f"What would answer it: a run with elongation_model={d.proposal['elongation_model']}."]
    for n in d.notes:
        out += ["", f"Note: {n}"]
    return "\n".join(out)
