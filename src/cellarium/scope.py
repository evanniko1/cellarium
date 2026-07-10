"""Mechanistic-scope guardrail — CAN the model even address this hypothesis?

A distinct guardrail axis from the other two:
  - feasibility/envelope: is the perturbation in the *validated* regime? (a carbon-source switch is not)
  - provenance: was the quantity *fitted* (in-sample) or *predicted* (out-of-sample)?
  - **mechanistic scope (here): is the target's function actually *simulated*, so a result is interpretable?**

The whole-cell model simulates genes at very different depths. A gene is MECHANISTIC if its product does
something in a modeled process — catalyses an FBA reaction (metabolic enzyme), is one of the ~23 modeled
transcription factors, or is a subunit of the central-dogma machinery (ribosome / RNAP / replisome / aminoacyl-
tRNA synthetase; 89 genes, detected from sim_data's molecule_groups + synthetase set). The *majority* of genes
are expressed and counted but otherwise inert. Knocking out a non-mechanistic gene shows little/no phenotype BY
CONSTRUCTION — a null there is a statement about model scope, NOT about the gene's biological dispensability.
This is why H2 (Mg->ribosome) failed and was *predictable*: Mg->ribosome coupling is not a modeled mechanism.

The three regimes matter for KO experiments (see classify_gene): metabolic single-KOs REROUTE (no phenotype),
machinery single-KOs CRASH the sim (not a clean phenotype), and only GRADED capacity perturbations
(rrna_operon_knockout, ppgpp_conc) yield measurable, interpretable dose-responses. Note: the 89 detected genes
are the core structural machinery; soluble translation factors (EF-Tu/EF-G/IF/RF) have no dedicated molecule
group and are not flagged. Classification comes from gene_scope.json (dumped via the gene_scope worker; gitignored).
"""

from __future__ import annotations

import json
from pathlib import Path

SCOPE_CACHE = Path("data/cache/gene_scope.json")


def _scope() -> dict:
    return json.loads(SCOPE_CACHE.read_text(encoding="utf-8")) if SCOPE_CACHE.exists() else {}


def classify_gene(symbol: str) -> dict:
    g = _scope().get(symbol)
    if not g:
        return {"symbol": symbol, "known": False,
                "note": "gene not in the scope map — run `gene_scope` (python-side) to build it."}
    machinery = bool(g.get("is_machinery"))
    machinery_role = g.get("machinery_role")
    role = ("central_dogma_machinery" if machinery
            else "metabolic_enzyme" if g["is_metabolic"]
            else "transcription_factor" if g["is_tf"] else "no_modeled_function")
    mechanistic = role != "no_modeled_function"
    sole = bool(g.get("is_sole_catalyst"))
    kinetic = bool(g.get("is_kinetically_constraining"))
    # KO-growth-effect prediction, CALIBRATED against the KO experiments (all outputs are priors, not verdicts).
    # The single-gene-KO characterization has THREE regimes; the branch order encodes their priority:
    #   1. machinery (ribosome/RNAP/replisome/aaRS) -> a full KO removes an essential central-dogma subunit and
    #      the sim CRASHES, not reroutes. gltX (aaRS, also metabolic) KO: ribosome_conc collapsed 21->2.15 and
    #      NegativeCountsError in PolypeptideElongation, 4/4 seeds. So machinery is checked FIRST, before metabolic.
    #   2. metabolic (kinetic OR not) -> the model REROUTES. fabI (not kinetic) AND glmS/gltA/pfkA/tpiA (kinetic +
    #      sole) ALL showed no growth effect: the kinetic layer is a SOFT FBA target, not a hard bound. NO
    #      structural metabolic flag reliably predicts a KO growth effect (0/5 hit-rate).
    #   3. non-mechanistic -> no phenotype BY CONSTRUCTION (flgB/ymgD).
    # The clean-phenotype path is NEITHER a metabolic nor a machinery single-KO but a GRADED capacity perturbation
    # (rrna_operon_knockout, ppgpp_conc) — those gave the only measurable, interpretable dose-responses.
    if machinery:
        ko_effect = "lethal_crash"
        note = ("Core central-dogma machinery (" + str(machinery_role) + "). A full single-gene KO removes an "
                "essential subunit of translation/transcription/replication — EMPIRICALLY the sim CRASHES rather "
                "than reaching a phenotype (gltX aaRS KO: ribosome_conc 21->2.15, NegativeCountsError in "
                "PolypeptideElongation, 4/4 seeds). This is a model breakdown, NOT an interpretable result. For a "
                "measurable capacity effect use a GRADED perturbation (rrna_operon_knockout, ppgpp_conc).")
    elif not mechanistic:
        ko_effect = "none_inert"
        note = ("EXPRESSED but function NOT simulated. A KO shows no phenotype BY CONSTRUCTION — model scope, "
                "not biological dispensability.")
    elif g["is_metabolic"] and not kinetic:
        ko_effect = "none_flux_unconstrained"
        note = ("Metabolic but NOT a kinetic-constraint enzyme — its count never enters a flux bound. A KO cannot "
                "affect growth via metabolism (the fabI-type null).")
    elif g["is_metabolic"]:
        ko_effect = "unreliable_model_reroutes"
        note = ("Metabolic AND a kinetic-constraint enzyme, but the kinetic constraints are SOFT FBA targets, not "
                "hard bounds. EMPIRICALLY the model reroutes metabolic single-KOs: glmS/gltA/pfkA/tpiA are all "
                "kinetic+sole-catalyst yet their KOs showed NO growth effect. Do NOT expect a phenotype; the only "
                "reliable test is running the KO or an FBA single-deletion feasibility check (structural flags "
                "have a 0/5 hit-rate here).")
    else:
        ko_effect = "mechanistic_other"
        note = "Mechanistically simulated (" + role + ") — a KO is a genuine, interpretable prediction."
    return {"symbol": symbol, "known": True, "mechanistic": mechanistic, "role": role,
            "is_machinery": machinery, "machinery_role": machinery_role,
            "is_sole_catalyst": sole, "is_kinetically_constraining": kinetic, "ko_effect_prior": ko_effect,
            "ko_index": g["ko_index"], "n_tu": g["n_tu"], "note": note,
            "calibration": ("metabolic structural flags 0/5 at predicting a KO growth effect (model reroutes); the "
                            "machinery flag predicts a lethal crash, not a clean phenotype (gltX 4/4). Prior, not "
                            "verdict — for a measurable KO-adjacent effect use a graded-capacity perturbation.")}
