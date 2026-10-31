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
    # ENUM-2. Three channels are NOT written in every configuration, and a capability view that lists them
    # unconditionally invites a hypothesis whose readout does not exist. That is what happened on 2026-10-27:
    # under kinetic charging these columns hold the listener's initial zeros, the corpus reported 0.0 ± 0.0,
    # and a run called the value non-physical when the truth was "never recorded". `recorded_when` is the
    # capability form of that fact, so it reaches the Council with the channel rather than after it.
    "ppgpp_conc":           {"unit": "uM",    "note": "guanosine tetraphosphate — stringent-response alarmone",
                             "recorded_when": "steady-state charging always; kinetic charging ONLY with the "
                                              "RelA/SpoT ppGpp module on"},
    "ribosome_conc":        {"unit": "uM",    "note": "active ribosome concentration",
                             "recorded_when": "steady-state charging only — NEVER written under kinetic "
                                              "charging; use ribosomal-protein counts there"},
    "fraction_trna_charged": {"unit": "frac", "note": "fraction of tRNA aminoacylated",
                              "recorded_when": "always, but it means 20 per-amino-acid values broadcast over "
                                               "86 columns under steady state, and 86 independent species "
                                               "under kinetic charging"},
    "rela_conc":            {"unit": "uM",    "note": "RelA (ppGpp synthetase) concentration",
                             "recorded_when": "steady-state charging always; kinetic charging ONLY with the "
                                              "RelA/SpoT ppGpp module on"},
    "dry_mass":             {"unit": "fg",    "note": "cell dry mass"},
    "protein_mass":         {"unit": "fg",    "note": "total protein mass"},
    "rna_mass":             {"unit": "fg",    "note": "total RNA mass"},
    "cell_mass":            {"unit": "fg",    "note": "total cell mass"},
    "division_rate":        {"unit": "frac",  "note": "fraction of generations that divide — the §J viability readout for KO lethality; <1 flags a division defect the growth rate can hide"},
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
    "timeline": "media-shift events over time (aa/ion/oxygen shift — NOT a carbon-source switch, and NOT a glucose dose: uptake is a binary switch, so every glucose concentration gives the same cell)",
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
            "returns": "welch_t (>=2 => beyond replicate noise; the significance test), effect_pct, z_vs_corpus_spread (descriptive positioning, NOT significance), per-seed spread",
            "note": "a claim is testable only if it names a target design, a reference, and one of these channels",
        },
        "design_schema": {
            "perturbation": "one of the perturbations above",
            "condition": "static media condition, e.g. basal, acetate",
            "timeline": "media-shift events, e.g. '0 minimal, 1200 minimal_plus_amino_acids'",
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
    ko = _knockout_reaches_its_target(d)
    if ko.get("refuses"):
        usable = False
    return {
        "usable": usable,
        "in_envelope": env.in_envelope,
        "envelope_reason": env.reason,
        "envelope_suggestion": env.suggestion,
        "biosecurity_flagged": bio.flagged,
        "biosecurity_severity": bio.severity,
        "biosecurity_reason": bio.reason,
        **({"knockout": ko} if ko else {}),
    }


# W4C-11. The Council was picking multi-transcription-unit genes for `gene_knockout` panels -- leuS, thrS,
# ileS, miaA, ilvA, hisB, hisG, trpC, argH, rpsA, rplA, relA -- and this function, which is the feasibility
# evidence its judge reads, consulted the envelope and the biosecurity screen and nothing else. The
# registry already knew: `knockout_of_a_multi_transcription_unit_gene` says the capability exists only
# through `graded_gene_knockout`, because the stock variant zeroes ONE transcription unit and the gene
# keeps being expressed from the others (murA 1403 copies -> 0 only under the graded variant). The
# information was in the repo and unread, which is this project's recurring shape rather than a new bug.
#
# WHAT IT REFUSES ON, and the line matters more than the check. `scope.ko_will_silence` reports its
# EVIDENCE, and only `measured` is trustworthy here:
#   * measured            -- the footprint cache measured this gene's copy number under the variant.
#                            murA (n_tu=2) and rpoB (n_tu=3) come back `will_silence: False`; pheS
#                            (n_tu=2) comes back TRUE. Refusing on this is reading a measurement.
#   * predicted_from_n_tu -- the `n_tu > 1 -> not silenced` rule, which scope.py records as 23 fit and 5
#                            refute, about 82%. bamC and prfB are two of the named refutations and the
#                            prediction still says False for them, so refusing on it would block exactly
#                            the knockouts that work -- a mistake this project has already made once and
#                            written down ("My refusal would have blocked exactly the knockouts that
#                            work"). So a prediction is REPORTED and not refused.
def _knockout_reaches_its_target(d: Design) -> dict:
    """Whether a knockout design's variant actually silences its target. Reported; refused only if
    MEASURED not to."""
    from . import model, scope
    if "knockout" not in (d.perturbation or ""):
        return {}
    # The CONDITION string, not the Design object: `knockout_genes` takes a label, a design key or a corpus
    # row, and handing it a pydantic object made it stringify the repr and match nothing -- a silent empty
    # answer, which is the shape this whole check exists to stop.
    genes = model.knockout_genes({"condition": d.condition or "", "label": d.condition or ""}) or []
    if not genes:
        return {}
    checked = [scope.ko_will_silence(g, d.perturbation) for g in genes]
    measured_noop = [c for c in checked if c.get("will_silence") is False
                     and c.get("evidence") == "measured"]
    predicted_noop = [c for c in checked if c.get("will_silence") is False
                      and c.get("evidence") != "measured"]
    unknown = [c for c in checked if c.get("will_silence") is None]
    out = {"genes": genes, "variant": d.perturbation,
           "silences": [c.get("symbol") for c in checked if c.get("will_silence") is True],
           "measured_no_op": [c.get("symbol") for c in measured_noop],
           "predicted_no_op": [c.get("symbol") for c in predicted_noop],
           "unknown": [c.get("symbol") for c in unknown],
           "refuses": bool(measured_noop)}
    if measured_noop:
        out["reason"] = (
            f"MEASURED no-op: {', '.join(c['symbol'] for c in measured_noop)} is transcribed from more "
            f"than one transcription unit and `{d.perturbation}` zeroes ONE, so the gene keeps being "
            f"expressed. A run of this design is not a knockout of it. Use `graded_gene_knockout`, which "
            f"resolves the gene's own cistron and suppresses every transcription unit carrying it "
            f"(capability `knockout_of_a_multi_transcription_unit_gene`).")
    elif predicted_noop:
        out["warning"] = (
            f"PREDICTED no-op, not measured: {', '.join(c['symbol'] for c in predicted_noop)} has more "
            f"than one transcription unit, and the n_tu rule that predicts a no-op from that fits 23 "
            f"genes and is refuted by 5 (about 82%). NOT refused on a prediction -- bamC and prfB are "
            f"among the refutations -- but a knockout claim about this design should say which it is, and "
            f"`graded_gene_knockout` removes the doubt.")
    elif unknown:
        out["warning"] = (
            f"{', '.join(str(c.get('symbol')) for c in unknown)} is not in the gene registry, so whether "
            f"this variant silences it is genuinely unknown -- which is not the same as a no-op.")
    return out
