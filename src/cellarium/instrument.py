"""Dial labels — the ONLY view of the system the Socratic Council may see.

The quarantine boundary (docs/SOCRATIC_COUNCIL.md D2), auditable in one place. The Council operationalizes a
hypothesis, so it needs to know what the instrument CAN measure and CAN run — the observable namespace and the
validated envelope — but it must never see a READING (a corpus value, a survey result, the answer key in
docs/CORPUS_OBSERVATIONS.md). The principle: give the Council the instrument's dial labels, not its readings.

Per decision D4 this exposes NO gene-scope information (not even a hit-rate-stripped structural check): whether a
knocked-out gene's function is simulated is discovered downstream, in the context of justification, by the
grounded agent's own mechanistic_scope tool. This module therefore does NOT import survey, differential, scope,
or any result-bearing store call, and reads nothing under data/. `check_design` uses only the deterministic
guardrail capabilities (envelope, biosecurity), which are instrument capabilities, not readings.
"""

from __future__ import annotations

from . import biosecurity, envelope
from .model import Design

# Summary channels the instrument measures (names + capability metadata only — NO values). Mirrors
# survey.CHANNELS; a test asserts the two stay in sync without importing survey at runtime.
CHANNELS: dict[str, dict] = {
    "growth_rate":          {"unit": "1/h",   "note": "instantaneous specific growth rate"},
    "ppgpp_conc":           {"unit": "uM",    "note": "guanosine tetraphosphate — stringent-response alarmone"},
    "ribosome_conc":        {"unit": "uM",    "note": "active ribosome concentration"},
    "fraction_trna_charged": {"unit": "frac", "note": "fraction of tRNA aminoacylated"},
    "rela_conc":            {"unit": "uM",    "note": "RelA (ppGpp synthetase) concentration"},
    "dry_mass":             {"unit": "fg",    "note": "cell dry mass"},
    "protein_mass":         {"unit": "fg",    "note": "total protein mass"},
    "rna_mass":             {"unit": "fg",    "note": "total RNA mass"},
    "cell_mass":            {"unit": "fg",    "note": "total cell mass"},
    "fba_objective":        {"unit": "diag",  "note": "FBA solver objective — diagnostic, not a biological readout"},
}

# Arbitrary single molecules are also readable per-run (the ~12k state variables), by kind.
SPECIES_KINDS = ["protein", "mrna", "metabolite", "reaction_flux", "exchange_flux"]

REFERENCE_DESIGN = "wildtype/basal"  # the canonical null/baseline design label

# Short gloss on each validated perturbation so the proposer knows the design vocabulary it may use.
_PERTURBATION_NOTES = {
    "wildtype": "unperturbed reference; vary only seeds/condition",
    "gene_knockout": "delete one gene",
    "multi_gene_knockout": "delete several genes",
    "condition": "a static fitted media condition (e.g. basal, acetate)",
    "tf_activity": "clamp a transcription factor's activity",
    "ppgpp_conc": "clamp ppGpp concentration to a multiple of basal",
    "timeline": "media-shift events over time (glucose cut/ramp, aa/ion/oxygen shift — NOT a carbon-source switch)",
    "amino_acid_shift": "add/remove an amino acid mid-run",
    "rrna_operon_knockout": "delete rRNA operons (ribosome capacity)",
    "new_gene": "introduce a heterologous gene",
}


def dial_labels() -> dict:
    """The full capability view handed to the Council — channels, species kinds, perturbations, the reference,
    the falsification mechanism, and the design schema. Contains NO readings."""
    return {
        "channels": {name: meta for name, meta in CHANNELS.items()},
        "species_kinds": list(SPECIES_KINDS),
        "perturbations": {p: _PERTURBATION_NOTES.get(p, "") for p in sorted(envelope.VALIDATED_PERTURBATIONS)},
        "reference_design": REFERENCE_DESIGN,
        "static_only_carbon": sorted(envelope.STATIC_ONLY_CARBON),  # cannot be a mid-run switch target
        "falsification": {
            "call": "disconfirm(target, reference, channel)",
            "returns": "welch_t (>=2 => beyond replicate noise), effect_pct, effect_z_vs_corpus, per-seed spread",
            "note": "a claim is testable only if it names a target design, a reference, and one of these channels",
        },
        "design_schema": {
            "perturbation": "one of the perturbations above",
            "condition": "static media condition, e.g. basal, acetate",
            "timeline": "media-shift events, e.g. '0 minimal, 1200 minimal_GLC_5mM'",
            "seeds": "int — independent stochastic replicates (isogenic; vary intrinsic noise)",
            "generations": "int — cell-cycle generations to simulate",
            "params": "dict — e.g. {'target_genes': ['acrB']}",
        },
        "note": ("Dial labels only: what the instrument can MEASURE and RUN — never a reading. Operationalize "
                 "every construct onto one of these channels/species and express the null as the reference "
                 "design. Whether a gene's KO is mechanistically simulated is NOT knowable here — that is "
                 "checked downstream during testing."),
    }


def channel_names() -> list[str]:
    return list(CHANNELS)


def check_design(design: dict | Design) -> dict:
    """Feasibility of a candidate design, using deterministic guardrail capabilities only (no readings).

    Returns whether the design is inside the validated envelope and whether it trips the biosecurity screen —
    the evidence the judge needs for the 'feasible' rubric item. A design is usable iff in_envelope and not
    biosecurity-blocked."""
    d = design if isinstance(design, Design) else Design(**design)
    env = envelope.check(d)
    bio = biosecurity.screen(d)
    usable = env.in_envelope and not (bio.flagged and bio.severity == "block")
    return {
        "usable": usable,
        "in_envelope": env.in_envelope,
        "envelope_reason": env.reason,
        "envelope_suggestion": env.suggestion,
        "biosecurity_flagged": bio.flagged,
        "biosecurity_severity": bio.severity,
        "biosecurity_reason": bio.reason,
    }
