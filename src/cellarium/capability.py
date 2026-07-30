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
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Capability:
    """One mechanism the model may or may not represent."""

    key: str
    question: str                       # a scientific question that NEEDS this mechanism
    present: bool                       # the mechanism EXISTS in the checkout Cellarium runs against
    markers: tuple[str, ...] = ()       # symbols in the checkout that evidence it
    # PORTED is not the same as ON, and conflating them is how a safety registry starts lying. After EXT-PORT-1
    # the kinetic tRNA charging code is in the checkout, so `markers` find it and `present` is honestly True —
    # but it is behind `--kinetic-trna-charging`, which is GATED — it raises NotImplementedError,
    # because the host process was never ported — and which NO run in the existing corpus
    # used. Reporting a per-isoacceptor number off a steady-state run would be exactly the confidently-wrong
    # answer this module exists to prevent, so `check()` still refuses unless the capability is on by default.
    default_on: bool = True
    instead: str = ""                   # what the model does INSTEAD, when absent
    consequence: str = ""               # what a naive read would wrongly conclude
    available_in: str = ""              # where the mechanism does exist, if anywhere
    flag: str = ""                      # the model flag that would enable it, once ported
    detail: str = ""

    def refusal(self) -> str:
        """What to say instead of returning a number. Names the gap, the substitute, and the route."""
        if self.present and not self.default_on:
            return (f"The mechanism for {self.key} IS present in the model ({self.available_in or 'ported'}), "
                    f"but it is behind {self.flag or 'a non-default flag'}, which defaults OFF, so the corpus "
                    f"CANNOT answer this: no simulation in it was run with the flag. "
                    + (f"What those runs do instead: {self.instead} " if self.instead else "")
                    + (f"So do NOT read their output as evidence: {self.consequence} " if self.consequence
                       else "")
                    + "Answering this needs a NEW campaign run with that flag — and because the port changes "
                      "kb_sha256, such a campaign is not poolable with the existing corpus.")
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


# The registry. `present=False` entries are the ones that matter — each is a question the model will otherwise
# answer with a plausible number.
CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        key="per_isoacceptor_trna_charging",
        question="Does one tRNA isoacceptor de-charge while another of the SAME amino acid stays charged? "
                 "(Elf et al. 2003 selective charging; validation data Dittmar et al. 2005 Table 1)",
        present=True,       # EXT-PORT-1 applied
        default_on=False,   # ...--kinetic-trna-charging is gated (EXT-PORT-8) and no corpus run used it
        markers=("KineticTrnaChargingModel", "trnas_to_codons", "codons_to_trnas"),
        instead="charging is solved as a 20-state ODE indexed by AMINO ACID, then broadcast to all 86 "
                "isoacceptor columns via np.dot(fraction_charged, aa_from_trna); demand is split back across "
                "isoacceptors strictly in proportion to abundance",
        consequence="`fraction_trna_charged` columns within an amino-acid family are IDENTICAL BY "
                    "CONSTRUCTION, so a within-family spread of 0.0 is arithmetic, not a measurement of "
                    "uniform charging",
        available_in="CovertLab/WholeCellEcoliRelease v3.0.1 (Choi & Covert 2023, NAR 51(12):5911, "
                     "doi:10.1093/nar/gkad435) — not present in the dev lineage this checkout descends from",
        flag="--kinetic-trna-charging — NOT RUNNABLE YET: it raises NotImplementedError. The elongation models and their knowledge base are ported (ParCa is green), but the host PolypeptideElongation process still uses the steady-state calling convention. See BACKLOG EXT-PORT-8.",
        detail="differential charging BETWEEN isoacceptors of one amino acid",
    ),
    Capability(
        key="codon_level_elongation",
        question="Which CODON is a ribosome waiting on, and does codon identity change elongation rate?",
        present=True,       # EXT-PORT-1 applied: the consumer now exists
        default_on=False,   # ...and --kinetic-trna-charging, which would enable it, is gated (EXT-PORT-8)
        # The marker must be the CONSUMER, not the data.  /  are now present
        # because the EXT-PORT relation.py work added them — and the audit caught this declaration going stale,
        # which is what it is for. But the reading matrix existing is necessary and NOT sufficient: nothing
        # elongates by codon until  is ported into polypeptide_elongation.py. Marking
        # this present on the strength of the data alone would have claimed a capability with no consumer.
        markers=("KineticTrnaChargingModel",),
        instead="with the flag OFF — which is every run in the corpus — elongation draws from per-amino-acid "
                "pools and codon identity has no effect on rate, even though the codon x anticodon reading "
                "matrix and its consumer are both now present in the checkout",
        consequence="any codon-usage or codon-bias claim would be inferred from sequence, not simulated",
        available_in="CovertLab/WholeCellEcoliRelease v3.0.1",
        flag="--kinetic-trna-charging (ported by scripts/apply_trna_port.py; defaults OFF)",
    ),
    Capability(
        key="operon_specific_rrna_knockout",
        question="What happens when a SPECIFIC rRNA operon is deleted?",
        present=False,
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
        markers=("SteadyStateElongationModel", "fraction_trna_charged"),
        detail="charged fraction per amino acid, dynamically coupled to ppGpp and the stringent response",
    ),
    Capability(
        key="ppgpp_stringent_response",
        question="Does ppGpp rise on amino-acid starvation and does that regulate growth?",
        present=True,
        markers=("ppgpp_conc", "synth_prob_from_ppgpp"),
        detail="ppGpp dynamics with transcriptional attenuation (Ahn-Horst et al. 2022)",
    ),
    Capability(
        key="nutrient_shift_timelines",
        question="How does the cell respond to a media shift at a chosen time?",
        present=True,
        markers=("make_timeline", "nutrient_to_doubling_time"),
        detail="declared media timelines, including single-amino-acid dropouts (EXT-1)",
    ),
)

_BY_KEY = {c.key: c for c in CAPABILITIES}


def get(key: str) -> Capability | None:
    return _BY_KEY.get(key)


def missing() -> tuple[Capability, ...]:
    """The mechanisms the corpus cannot answer from — absent OR ported-but-off. Both produce wrong numbers."""
    return tuple(c for c in CAPABILITIES if not (c.present and c.default_on))


def check(key: str) -> dict:
    """Can the model answer a question needing `key`? Returns a refusal when it cannot.

    The contract Cellwright relies on: a False `can_answer` ALWAYS carries a `refusal`, and never a value."""
    c = _BY_KEY.get(key)
    if c is None:
        return {"capability": key, "known": False, "can_answer": None,
                "note": f"'{key}' is not a declared capability. Declared: {sorted(_BY_KEY)}. An undeclared "
                        f"mechanism is not evidence of absence — add it to CAPABILITIES with markers so the "
                        f"answer is probed rather than assumed."}
    answerable = c.present and c.default_on
    out = {"capability": key, "known": True, "can_answer": answerable, "question": c.question}
    if c.present and not c.default_on:
        out["ported_but_off_by_default"] = True
        out["flag"] = c.flag
    if not answerable:
        out["refusal"] = c.refusal()
        out["report_a_number"] = False
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


def audit(wcecoli: str | None = None) -> dict:
    """Every declaration checked against the checkout. `ok` false means the registry is lying."""
    res = probe(wcecoli)
    bad = [r for r in res if not r.agrees]
    return {"ok": not bad, "n_capabilities": len(CAPABILITIES), "n_missing": len(missing()),
            "disagreements": [{"key": r.key, "declared": r.declared, "markers": r.markers_found, "note": r.note}
                              for r in bad],
            "probed": [{"key": r.key, "declared": r.declared, "markers": r.markers_found, "note": r.note}
                       for r in res],
            "note": "Capabilities are DECLARED and PROBED. A disagreement means the registry no longer matches "
                    "the model, which is worse than no registry — it is confidently wrong metadata."}
