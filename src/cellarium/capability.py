"""What the model CAN and CANNOT represent — so a missing mechanism reads as a refusal, not as a zero.

This exists because of a specific failure. We measured within-family tRNA charging spread of exactly
`0.00e+00` across leu(8)/arg(7)/ser(5), in starved, amino-acid-rich and minimal runs alike, and reported it as
a scientific result. It was an ALGEBRAIC IDENTITY: `polypeptide_elongation.py:163` does
`np.dot(fraction_charged, aa_from_trna)`, broadcasting one per-amino-acid scalar across every isoacceptor
column, and demand is split back strictly by abundance — so family members cannot differ, in any condition,
ever. The model was not silent about a hard question; it was structurally incapable of the question, and it
answered anyway with a number indistinguishable from a measurement.

The remedy is not more validation on the number. It is that the ABSENCE OF A MECHANISM MUST BE A FIRST-CLASS,
QUERYABLE FACT. A capability that is missing produces a refusal naming what is missing and what would be
needed; it never produces a value.

**Declared AND probed.** Every capability carries `markers`: symbols whose presence in the model checkout
evidences it. `probe()` greps the checkout and `audit()` reports any disagreement between what we declare and
what is actually there. A declaration nobody verifies is a comment, and this codebase has been burned by
comments that were true when written — the whole reason `serialization.py` detects truncation mechanically
instead of trusting a note about it.

Deliberately NOT a fork-selection engine. The investigation into supporting multiple wcEcoli forks concluded
that within a lineage the releases are a clean partial order, across lineages there is no order at all, and
demand for fork choice is currently zero: of 65 rows in docs/CASE_MATRIX.md, five mention tRNA and none need
per-isoacceptor resolution. This module is the cheap 80% of that idea — honest refusals — with no second fork,
no second Docker image, and no second corpus that cannot be pooled with the first.

**Mode-aware since the elongation axis landed.** The checkout now carries THREE elongation models, and a
capability is a property of the model that ran, not of the checkout. `GrowthLimits/fraction_trna_charged` is
86 columns wide under all three and means something different in each: under steady_state one per-amino-acid
scalar broadcast across the family (within-family spread 0.00 as an identity), under kinetic 86 genuinely
independent values, under coarse_kinetic 86 EXACT ZEROS because that model does not solve charging at all.
An unconditional answer to "can the model represent X" is therefore a lie in at least one mode, which is why
`check()` and `refusal()` both take a mode and why every claim here is scoped by `holds_in`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# The elongation axis. Hard-coding these strings at each use site is how a typo makes a capability answerable
# everywhere or nowhere with no error, so every consumer (model.Design's validator, runner's flag mapping,
# manifest's design tag) resolves them from here.
DEFAULT_MODE = "steady_state"
ELONGATION_MODES = ("steady_state", "kinetic", "coarse_kinetic")

# A MODE-level table, deliberately not a per-capability `flag` string: the route out of the ppGpp gap is "go
# back to steady_state", which is the ABSENCE of a flag, and a per-capability flag field cannot express that.
# Both names verified against the checkout (wholecell/utils/scriptBase.py:534-538, dashized by
# define_parameter_bool); they are mutually exclusive alternatives, not modifiers, and selecting either one
# forces trna_charging and translation_supply False (wholecell/sim/simulation.py:148-154).
MODE_FLAGS = {
    "steady_state": "(no flag — the model default)",
    "kinetic": "--kinetic-trna-charging",
    "coarse_kinetic": "--coarse-kinetic-elongation",
}

# What each mode does to the one column that has burned us, in one line — surfaced to the agent so it never
# has to infer the semantics from a column name that is identical across all three.
MODE_SUMMARY = {
    "steady_state": "charging solved as a 20-state ODE indexed by AMINO ACID, then broadcast across the 86 "
                    "isoacceptor columns — within-family spread is 0.00 by construction",
    "kinetic": "per-isoacceptor charging with explicit codon reading (Choi & Covert 2023) — the 86 columns "
               "are genuinely independent (measured spread GLY 0.32, LEU 0.25)",
    "coarse_kinetic": "coarse-grained kinetic elongation that does NOT solve charging — the 86 columns are "
                      "EXACT ZEROS, which is the absence of a model, not total de-acylation",
}

# Every existing row was produced by the steady-state model — that is KNOWN, not unknown (the corpus predates
# the port, and no run could have used a flag whose host process was only just ported). This is the ONE
# declaration here that a routine action — running a campaign — invalidates without anyone touching this file,
# so `audit()` probes it against the manifest rather than trusting it. A new campaign in another mode must
# extend this tuple.
MODES_IN_CORPUS = ("steady_state",)

# How a non-default elongation model is spelled INSIDE a design tag, e.g. `KO:argS#elong:kinetic`. Lives here
# so `manifest._design_tag` (which writes it) and `factors.parse` (which must lift it back out as its own
# field rather than folding it into `base`/`level_raw`) cannot drift apart.
#
# The separator choice is load-bearing. `·` and `/` are how `survey.design_tag` and
# `manifest._design_tag_from_row` split a label into perturbation and tag; `|` is how `factors.parse`
# recognises the compound-dose form `basal|ppGpp:0.6x`; `@` already appends a media to a KO tag. `#` is used
# by none of them, and it survives `_SEED_SUFFIX` stripping untouched.
MODE_TAG_PREFIX = "#elong:"


def mode_tag_suffix(mode: str) -> str:
    """The tag fragment for `mode` — EMPTY for the default.

    Emitting nothing for steady_state is what keeps every existing label, design_key, `count_runs` prefix and
    deterministic crash-row id byte-identical. Changing the tag of ~300 historical rows to say what they
    already implicitly say would have broken invariant D2 (stored design_key vs derived) on all of them."""
    return "" if mode == DEFAULT_MODE else f"{MODE_TAG_PREFIX}{mode}"


def mode_from_tag(tag: str) -> tuple[str, str]:
    """Split a design tag into (tag without the elongation fragment, mode). Inverse of `mode_tag_suffix`."""
    t = str(tag or "")
    if MODE_TAG_PREFIX in t:
        base, _, mode = t.partition(MODE_TAG_PREFIX)
        if mode in ELONGATION_MODES:
            return base, mode
    return t, DEFAULT_MODE


@dataclass(frozen=True)
class Capability:
    """One mechanism the model may or may not represent."""

    key: str
    question: str                       # a scientific question that NEEDS this mechanism
    present: bool                       # the mechanism EXISTS in the checkout Cellarium runs against
    markers: tuple[str, ...] = ()       # symbols in the checkout that evidence it
    # The elongation models under which this mechanism is REAL. Deliberately an ALLOWLIST rather than a
    # `lacks_in` denylist: a fourth elongation model added tomorrow then inherits NO claim from this registry
    # until a human looks at it, whereas a denylist would silently claim every capability for it. `holds_in=()`
    # means no model in this checkout represents it — the old `present=False` entries.
    holds_in: tuple[str, ...] = ELONGATION_MODES
    instead: str = ""                   # what the model does INSTEAD, when absent
    consequence: str = ""               # what a naive read would wrongly conclude
    available_in: str = ""              # where the mechanism does exist, if anywhere
    flag: str = ""                      # a non-elongation switch that enables it (elongation lives in MODE_FLAGS)
    detail: str = ""

    @property
    def default_on(self) -> bool:
        """Kept as a DERIVED view, not a declared field, so the two can never disagree.

        It always asserted two things at once — "the default configuration represents this" AND "runs exist
        that used it" — which was harmless while there was one elongation model and is not now. Deriving it
        makes that contradiction unrepresentable; a safety registry whose fields can contradict each other is
        worse than one field."""
        return self.present and DEFAULT_MODE in self.holds_in and DEFAULT_MODE in MODES_IN_CORPUS

    def other_modes(self) -> tuple[str, ...]:
        """The declared modes that DO represent this, corpus modes first — the route case (b) offers."""
        return tuple(sorted(self.holds_in, key=lambda m: (m not in MODES_IN_CORPUS, ELONGATION_MODES.index(m)
                                                          if m in ELONGATION_MODES else 99)))

    def refusal(self, mode: str = DEFAULT_MODE) -> str:
        """What to say instead of returning a number. Names the gap, the substitute, and the route.

        Three cases, and they are genuinely different answers. (a) nothing in this checkout represents it.
        (b) THIS mode does not, but another one does — the most useful sentence the system can say, and a flat
        refusal here throws it away. (c) this mode does represent it, but no run in the corpus used that mode."""
        if not self.holds_in:
            parts = [f"The model as configured CANNOT represent {self.key}: {self.detail or self.question}"]
            if self.instead:
                parts.append(f"What it does instead: {self.instead}")
            if self.consequence:
                parts.append(f"So do NOT read the output as evidence: {self.consequence}")
            if self.available_in:
                parts.append(f"Where it does exist: {self.available_in}")
            if self.flag:
                parts.append(f"Flag that would enable it here once ported: {self.flag}")
            return " ".join(parts)
        if mode not in self.holds_in:
            other = self.other_modes()[0]
            return (f"{mode} runs CANNOT represent {self.key}: {self.detail or self.question} "
                    + (f"What the {mode} model does instead: {self.instead} " if self.instead else "")
                    + (f"So do NOT read a {mode} run as evidence: {self.consequence} " if self.consequence
                       else "")
                    + f"ANOTHER elongation model in this checkout DOES represent it: {other} — set "
                      f"elongation_model=\"{other}\" ({MODE_FLAGS.get(other, 'see MODE_FLAGS')}). "
                    + ("The corpus IS in that mode — re-issue the query there rather than proposing a run. "
                       if other in MODES_IN_CORPUS else
                       f"No run in the corpus used it (every corpus row is elongation_model="
                       f"\"{DEFAULT_MODE}\"), so this is a NEW RUN to propose, not a query to re-issue. ")
                    + (f"Where it comes from: {self.available_in}" if self.available_in else ""))
        return (f"The mechanism for {self.key} IS present in the model ({self.available_in or 'ported'}) and "
                f"the {mode} elongation model represents it, but NO run in the corpus was produced by that "
                f"model — every corpus row is elongation_model=\"{DEFAULT_MODE}\" — so the corpus CANNOT "
                f"answer this. "
                + (f"What those runs do instead: {self.instead} " if self.instead else "")
                + (f"So do NOT read their output as evidence: {self.consequence} " if self.consequence else "")
                + f"Answering this needs a NEW campaign with elongation_model=\"{mode}\" "
                  f"({MODE_FLAGS.get(mode, 'see MODE_FLAGS')}), and because that changes kb_sha256 such a "
                  f"campaign is not poolable with the existing corpus.")


# The registry. `present=False` entries are the ones that matter — each is a question the model will otherwise
# answer with a plausible number.
CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        key="per_isoacceptor_trna_charging",
        question="Does one tRNA isoacceptor de-charge while another of the SAME amino acid stays charged? "
                 "(Elf et al. 2003 selective charging; validation data Dittmar et al. 2005 Table 1)",
        present=True,       # EXT-PORT-1 applied
        holds_in=("kinetic",),   # ONLY the kinetic model solves charging per isoacceptor
        markers=("KineticTrnaChargingModel", "trnas_to_codons", "codons_to_trnas"),
        instead="charging is solved as a 20-state ODE indexed by AMINO ACID, then broadcast to all 86 "
                "isoacceptor columns via np.dot(fraction_charged, aa_from_trna); demand is split back across "
                "isoacceptors strictly in proportion to abundance",
        consequence="`fraction_trna_charged` columns within an amino-acid family are IDENTICAL BY "
                    "CONSTRUCTION, so a within-family spread of 0.0 is arithmetic, not a measurement of "
                    "uniform charging",
        available_in="CovertLab/WholeCellEcoliRelease v3.0.1 (Choi & Covert 2023, NAR 51(12):5911, "
                     "doi:10.1093/nar/gkad435) — not present in the dev lineage this checkout descends from",
        # The flag itself now lives in MODE_FLAGS. The string that stood here claimed
        # `--kinetic-trna-charging` raises NotImplementedError; EXT-PORT-8 has since landed
        # (`_calculateRequest_codon_aware`/`_evolveState_codon_aware` are ported and dispatched, and both halves
        # of the gate were deleted in that diff — verified: no NotImplementedError survives anywhere in
        # models/ecoli/processes or wholecell/sim). Leaving it would have made the case-(b) redirect talk the
        # operator out of the one experiment that answers the question, which is worse than a flat refusal.
        detail="differential charging BETWEEN isoacceptors of one amino acid",
    ),
    Capability(
        key="codon_level_elongation",
        question="Which CODON is a ribosome waiting on, and does codon identity change elongation rate?",
        present=True,       # EXT-PORT-1 applied: the consumer now exists
        holds_in=("kinetic",),   # codon identity only reaches the elongation rate on the codon-aware path
        # The marker must be the CONSUMER, not the data.  /  are now present
        # because the EXT-PORT relation.py work added them — and the audit caught this declaration going stale,
        # which is what it is for. But the reading matrix existing is necessary and NOT sufficient: nothing
        # elongates by codon until  is ported into polypeptide_elongation.py. Marking
        # this present on the strength of the data alone would have claimed a capability with no consumer.
        markers=("KineticTrnaChargingModel",),
        instead="under steady_state and coarse_kinetic — which is every run in the corpus — elongation draws "
                "from per-amino-acid pools and codon identity has no effect on rate, even though the codon x "
                "anticodon reading matrix and its consumer are both now present in the checkout",
        consequence="any codon-usage or codon-bias claim would be inferred from sequence, not simulated",
        available_in="CovertLab/WholeCellEcoliRelease v3.0.1",
    ),
    Capability(
        key="operon_specific_rrna_knockout",
        question="What happens when a SPECIFIC rRNA operon is deleted?",
        present=False,
        holds_in=(),        # the rRNA rebalance erases operon identity under every elongation model
        markers=(),
        instead="the variant zeroes n rRNA rows, then synth_prob_from_ppgpp(balanced_rRNA_prob=True) reassigns "
                "prob[is_rRNA] to the MEAN over all seven rows including the zeroed ones",
        consequence="the DOSE survives (total rRNA probability 100/73.8/45.9/15.8%) but operon IDENTITY does "
                    "not — no row ends at zero, so these are graded reductions of TOTAL rRNA capacity and "
                    "never operon-deletion strains (docs/KNOCKOUT_SEMANTICS.md)",
        detail="deletion of an individual rRNA operon as a distinguishable genotype",
    ),
    Capability(
        key="per_gene_trna_abundance",
        question="How abundant is the tRNA transcribed from one specific tRNA GENE?",
        present=False,
        holds_in=(),        # a data-provenance defect, upstream of every elongation model
        markers=(),
        instead="trna_ratio_to_16SrRNA_*.tsv carries 86 per-gene values derived from Dong 1996 Table 3's ~44 "
                "SPECIES measurements by dividing each species value by a gene count",
        consequence="the quotients are attached to the WRONG genes — 0.2225x4 = 0.89 is Dong's Leu1 but sits "
                    "on glt/ile/met/pro genes — so a per-gene abundance is not measurement-backed. Use "
                    "anticodon-pooled species values and state the pooling rule (docs/MODEL_EXTENSION.md EXT-3)",
        detail="tRNA abundance resolved to the individual gene",
    ),
    # Present capabilities are declared too, so the registry is a complete picture rather than a defect list.
    Capability(
        key="knockout_of_a_multi_transcription_unit_gene",
        question="Can a gene transcribed from MORE THAN ONE transcription unit actually be knocked out? "
                 "(murA n_tu=2, rpoB n_tu=3, rpmJ n_tu=2, valS n_tu=2)",
        present=True,
        markers=("graded_gene_knockout",),
        instead="`gene_knockout` zeroes ONE transcription unit, so the gene keeps being expressed from the "
                "others — measured murA ko_mean 1.6 vs wt 1.5, i.e. unchanged",
        consequence="a run of such a design under `gene_knockout` is a WILD TYPE wearing a knockout's label, "
                    "and its null result says nothing about the gene (WELL-NOOP-1). Five of seventeen audited "
                    "knockouts were defective this way, and one was propping up a live acceptance gate",
        available_in="Cellarium's own `graded_gene_knockout` variant — resolves the gene's own cistron and "
                     "suppresses every transcription unit carrying it. Verified: murA 1789 copies -> 0 across "
                     "2 generations",
        flag="--variant graded_gene_knockout <ko_index*10 + level>",
        detail="knocking out a gene with n_tu > 1, and graded suppression at 5-99% expression",
    ),
    Capability(
        key="per_amino_acid_trna_charging",
        question="What fraction of an amino acid's tRNA is charged, and how does it respond to starvation?",
        present=True,
        # NOT unconditionally present, which is how it was declared until the elongation axis forced the
        # question. Checked in the model tree rather than assumed: `CoarseKineticTrnaChargingModel.request`
        # returns `self.zero_charged_holder, aa_request` under the comment "Not modeling charging so set
        # fraction charged to 0 for all tRNA", `.evolve` returns `self.zero_charged_holder, {}`, and
        # `zero_charged_holder = np.zeros(len(self.uncharged_trna_names))` is 86 wide — the exact width
        # GrowthLimits/fraction_trna_charged is allocated at. This is the original 0.00 incident with a worse
        # blast radius: steady_state gives a within-family SPREAD of 0.00 (an identity), coarse gives the
        # ABSOLUTE LEVEL 0.00 (no model at all), and a registry vouching for "per-amino-acid charging: present"
        # would green-light reading it as 100% uncharged tRNA — a dramatic, publishable, fabricated starvation
        # phenotype from the one capability this module vouched for.
        holds_in=("steady_state", "kinetic"),
        markers=("SteadyStateElongationModel", "fraction_trna_charged"),
        instead="the coarse model does not solve charging at all — CoarseKineticTrnaChargingModel.request and "
                ".evolve both return np.zeros(86)",
        consequence="`fraction_trna_charged` is IDENTICALLY 0.00 in every column at every timestep, which "
                    "reads as complete de-acylation / total starvation and is the ABSENCE of a charging model",
        detail="charged fraction per amino acid, dynamically coupled to ppGpp and the stringent response",
    ),
    Capability(
        key="ppgpp_stringent_response",
        question="Does ppGpp rise on amino-acid starvation and does that regulate growth?",
        present=True,
        # Absent from BOTH kinetic modes, not just one. Measured in the checkout: ppGpp mentions inside
        # SteadyStateElongationModel = 66; inside KineticTrnaChargingModel = 3 and inside
        # CoarseKineticTrnaChargingModel = 1, and every one of those four is a COMMENT saying ppGpp is not
        # computed on the codon-aware path. This is the mirror image of the isoacceptor trap and strictly more
        # dangerous, because it fails silently in the direction of a NEGATIVE result: "we knocked out the
        # synthetase and ppGpp did not rise" is a publishable claim, and under either kinetic model it is
        # guaranteed by construction.
        holds_in=("steady_state",),
        markers=("ppgpp_conc", "synth_prob_from_ppgpp"),
        instead="nothing synthesises or degrades ppGpp under either kinetic model — only "
                "SteadyStateElongationModel runs those reactions. metabolism.py:52 turns include_ppgpp back on "
                "once trna_charging is False and then HOLDS ppGpp AT A CONSTANT TARGET, and ppGpp-dependent "
                "transcription regulation reads that frozen pool",
        consequence="GrowthLimits/ppgpp_conc still exists and still looks like a measurement, so a flat ppGpp "
                    "trace under starvation is the absence of the mechanism, NOT evidence that the stringent "
                    "response failed to fire. Nothing raises",
        detail="ppGpp dynamics with transcriptional attenuation (Ahn-Horst et al. 2022)",
    ),
    Capability(
        key="amino_acid_uptake_from_the_medium",
        question="Does the cell TAKE UP an amino acid supplied by the medium — e.g. is a starvation rescue "
                 "arm actually rescued?",
        present=True,
        # Split out of nutrient_shift_timelines rather than folded into it as a caveat, because it is a
        # distinct mechanism and one capability that means two things is how a registry starts hedging. The
        # timelines themselves ARE mode-independent (they are upstream of elongation); the UPTAKE is not.
        holds_in=("steady_state",),
        markers=("aa_exchange_rates", "mechanistic_aa_transport"),
        instead="metabolism builds its amino-acid uptake package from PolypeptideElongation.aa_exchange_rates "
                "(metabolism.py:171-176), and ONLY SteadyStateElongationModel ever assigns that attribute; "
                "under either kinetic model it stays the zeros initialised at the end of initialize(), so in "
                "any medium containing amino acids the FBA is told uptake is zero. No exception, no warning",
        consequence="an amino-acid UPSHIFT under a kinetic model is a shift the metabolism cannot take up, so "
                    "the rescue arm of the most obvious tRNA experiment — starve, then rescue — is "
                    "structurally inert, and a failed rescue is the missing mechanism rather than biology",
        detail="mechanistic amino-acid transport, i.e. whether medium supply reaches the FBA",
    ),
    Capability(
        key="nutrient_shift_timelines",
        question="How does the cell respond to a media shift at a chosen time?",
        present=True,
        holds_in=ELONGATION_MODES,   # the timeline machinery is upstream of elongation and genuinely shared
        markers=("make_timeline", "nutrient_to_doubling_time"),
        detail="declared media timelines, including single-amino-acid dropouts (EXT-1). NB the shift is "
               "delivered under every elongation model, but whether the cell can USE an amino acid it "
               "delivers is a separate capability — see amino_acid_uptake_from_the_medium",
    ),
)

_BY_KEY = {c.key: c for c in CAPABILITIES}


def get(key: str) -> Capability | None:
    return _BY_KEY.get(key)


def answerable_in(c: Capability, mode: str = DEFAULT_MODE) -> bool:
    """THE answerability predicate — every other view here is a projection of it.

    Three conjuncts, and dropping any one of them is a distinct historical bug: the mechanism must be in the
    checkout, the elongation model must actually implement it, and some run must have used that model."""
    return c.present and mode in c.holds_in and mode in MODES_IN_CORPUS


def missing(mode: str = DEFAULT_MODE) -> tuple[Capability, ...]:
    """The mechanisms the corpus cannot answer from IN THIS MODE — absent, wrong-model, or never run.

    All three produce a plausible number rather than an error, which is why they share one list. Defaulting to
    DEFAULT_MODE keeps every existing caller's meaning exactly."""
    return tuple(c for c in CAPABILITIES if not answerable_in(c, mode))


def check(key: str, mode: str = DEFAULT_MODE) -> dict:
    """Can the model answer a question needing `key`, in `mode`? Returns a refusal when it cannot.

    The contract Cellwright relies on: a False `can_answer` ALWAYS carries a `refusal`, and never a value.
    `mode` defaults to DEFAULT_MODE so every existing caller keeps its exact current meaning — without it this
    function answers a question it was not asked ("can the model do X" when the only answerable question is
    "can the model do X in the mode this run used").

    Case order is (a) then (b) then (c). When both (b) and (c) apply, (b) wins: "this model does not represent
    it" is the stronger and more permanent fact, and running more sims in that mode would not help.
    """
    c = _BY_KEY.get(key)
    if c is None:
        return {"capability": key, "known": False, "can_answer": None,
                "note": f"'{key}' is not a declared capability. Declared: {sorted(_BY_KEY)}. An undeclared "
                        f"mechanism is not evidence of absence — add it to CAPABILITIES with markers so the "
                        f"answer is probed rather than assumed."}
    if mode not in ELONGATION_MODES:
        # Same treatment as an unknown key, and for the same reason: absence of a declaration is not evidence
        # of absence. Never False, which would read as a confident "no".
        return {"capability": key, "known": True, "known_mode": False, "mode": mode, "can_answer": None,
                "note": f"'{mode}' is not a declared elongation model. Declared: {list(ELONGATION_MODES)}. "
                        f"An undeclared mode is not evidence that the mechanism is absent under it — declare "
                        f"it in ELONGATION_MODES/MODE_FLAGS first."}
    out: dict = {"capability": key, "known": True, "known_mode": True, "mode": mode,
                 "can_answer": answerable_in(c, mode), "question": c.question}
    if out["can_answer"]:
        return out
    out["refusal"] = c.refusal(mode)
    out["report_a_number"] = False
    if not c.holds_in:                                          # (a) nothing in this checkout represents it
        out["why_not"] = "no_elongation_model_represents_it"
    elif mode not in c.holds_in:                                # (b) another model does — route, do not report
        other = c.other_modes()[0]
        out["why_not"] = "another_mode_represents_it"
        out["answerable_in"] = list(c.other_modes())
        # TWO GUARDRAILS make this redirect safe to be non-flat. `can_answer` and `report_a_number` both stay
        # False — the redirect changes what to DO NEXT, never what may be reported now. And `in_corpus` is
        # explicit, because an agent told "the kinetic model represents this" will otherwise go looking for a
        # kinetic run, find steady-state rows, and read them anyway.
        out["switch"] = {"mode": other, "design_field": f'elongation_model="{other}"',
                         "model_flag": MODE_FLAGS.get(other, ""), "in_corpus": other in MODES_IN_CORPUS}
    else:                                                       # (c) this model does, but no run used it
        out["why_not"] = "no_run_used_this_mode"
        out["ported_but_off_by_default"] = True
        out["switch"] = {"mode": mode, "design_field": f'elongation_model="{mode}"',
                         "model_flag": MODE_FLAGS.get(mode, ""), "in_corpus": False}
    return out


@dataclass
class ProbeResult:
    key: str
    declared: bool
    markers_found: dict = field(default_factory=dict)
    agrees: bool = True
    note: str = ""


def probe(wcecoli: str | None = None) -> list[ProbeResult]:
    """Grep the model checkout for each capability's marker symbols and compare against what we declared.

    Declared-only would rot: the checkout can change under us, and a stale `present=True` is exactly the kind
    of confidently-wrong metadata this module exists to prevent."""
    root = wcecoli or os.environ.get("WCECOLI_DIR") or ""
    out: list[ProbeResult] = []
    if not root or not os.path.isdir(root):
        return [ProbeResult(key=c.key, declared=c.present, agrees=True,
                            note="no checkout to probe — declaration UNVERIFIED, not confirmed")
                for c in CAPABILITIES]
    haystack = []
    for sub in ("models", "reconstruction", "wholecell"):
        d = os.path.join(root, sub)
        for dirpath, _dirs, files in os.walk(d):
            for f in files:
                if f.endswith(".py"):
                    haystack.append(os.path.join(dirpath, f))
    blob = ""
    for path in haystack:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                blob += fh.read()
        except OSError:
            continue
    for c in CAPABILITIES:
        if not c.markers:
            out.append(ProbeResult(key=c.key, declared=c.present, agrees=True,
                                   note="no probeable markers — this capability is about DATA semantics or "
                                        "model behaviour, not the presence of a symbol"))
            continue
        found = {m: (m in blob) for m in c.markers}
        # present iff EVERY marker is there: a partial port is not the capability
        actual = all(found.values())
        out.append(ProbeResult(key=c.key, declared=c.present, markers_found=found, agrees=(actual == c.present),
                               note=("" if actual == c.present else
                                     f"DISAGREEMENT: declared present={c.present} but markers say {actual}. "
                                     f"Update CAPABILITIES or investigate the checkout.")))
    return out


def probe_corpus_modes() -> dict:
    """Check MODES_IN_CORPUS against the manifest, the way `probe` checks markers against the checkout.

    This is the one declaration here that a ROUTINE action — running a campaign — invalidates without anyone
    touching this file, so it must be probed rather than trusted. The two rot directions are NOT symmetric and
    this must not treat them as such:

      * stale-NARROW (a campaign ran in a mode this tuple omits) makes `check()` refuse a question that is now
        answerable. Loud, conservative, recoverable — a warning.
      * stale-WIDE (a mode is declared before any run used it) makes `check()` green-light a question with no
        runs behind it. That is the dangerous direction and it fails the audit.

    An unreadable manifest reports UNVERIFIED. It does NOT fall back to assuming steady-state-only: a "could
    not read" reported as a fact is the silent-absence bug this repo keeps re-encountering.
    """
    from . import manifest
    seen = manifest.corpus_elongation_modes()
    if not seen.get("verified"):
        return {"ok": True, "verified": False, "declared": list(MODES_IN_CORPUS),
                "note": f"UNVERIFIED — {str(seen.get('why') or '').rstrip('.')}. The declaration is neither "
                        f"confirmed nor refuted."}
    found = tuple(seen["modes"])
    undeclared = [m for m in found if m not in MODES_IN_CORPUS]      # stale-NARROW: warn
    unused = [m for m in MODES_IN_CORPUS if m not in found]          # stale-WIDE: fail
    return {"ok": not unused, "verified": True, "declared": list(MODES_IN_CORPUS), "in_manifest": list(found),
            "undeclared_modes_in_corpus": undeclared, "declared_modes_with_no_runs": unused,
            "note": ("MODES_IN_CORPUS declares which elongation models actually produced rows. A declared mode "
                     "with NO runs behind it makes check() green-light an unanswerable question, so it fails "
                     "the audit; an undeclared mode that HAS runs only makes check() over-refuse, so it is a "
                     "warning — update MODES_IN_CORPUS in either case.")}


def audit(wcecoli: str | None = None) -> dict:
    """Every declaration checked against the checkout AND the corpus. `ok` false means the registry is lying."""
    res = probe(wcecoli)
    bad = [r for r in res if not r.agrees]
    modes = probe_corpus_modes()
    bad_modes = [c.key for c in CAPABILITIES if any(m not in ELONGATION_MODES for m in c.holds_in)]
    return {"ok": (not bad) and modes["ok"] and not bad_modes,
            "n_capabilities": len(CAPABILITIES), "n_missing": len(missing()),
            "disagreements": [{"key": r.key, "declared": r.declared, "markers": r.markers_found, "note": r.note}
                              for r in bad],
            "undeclared_holds_in_modes": bad_modes,
            "corpus_modes": modes,
            "probed": [{"key": r.key, "declared": r.declared, "markers": r.markers_found, "note": r.note}
                       for r in res],
            "note": "Capabilities are DECLARED and PROBED. A disagreement means the registry no longer matches "
                    "the model, which is worse than no registry — it is confidently wrong metadata."}
