"""Mechanistic-scope guardrail — CAN the model even address this hypothesis?

A distinct guardrail axis from the other two:
  - feasibility/envelope: is the perturbation in the *validated* regime? (a carbon-source switch is not)
  - provenance: was the quantity *fitted* (in-sample) or *predicted* (out-of-sample)?
  - **mechanistic scope (here): is the target's function actually *simulated*, so a result is interpretable?**

The whole-cell model simulates genes at very different depths. A gene is MECHANISTIC if its product does
something in a modeled process — catalyses an FBA reaction (metabolic enzyme) or is one of the ~23 modeled
transcription factors (and, more broadly, translation/replication machinery). The *majority* of genes are
expressed and counted but otherwise inert. Knocking out a non-mechanistic gene shows little/no phenotype BY
CONSTRUCTION — a null there is a statement about model scope, NOT about the gene's biological dispensability.
This is why H2 (Mg->ribosome) failed and was *predictable*: Mg->ribosome coupling is not a modeled mechanism.
Classification comes from gene_scope.json (dumped from sim_data via the gene_scope worker mode; gitignored).
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
    role = ("metabolic_enzyme" if g["is_metabolic"]
            else "transcription_factor" if g["is_tf"] else "no_modeled_function")
    mechanistic = role != "no_modeled_function"
    sole = bool(g.get("is_sole_catalyst"))
    kinetic = bool(g.get("is_kinetically_constraining"))
    # KO-growth-effect prediction. The DECISIVE signal (calibrated on the fabI/glmS/gltA nulls) is whether the
    # enzyme's count actually bounds a reaction flux in the kinetics-constrained FBA. If not, a KO cannot affect
    # growth via metabolism, however 'metabolic' or 'sole-catalyst' it looks.
    # CALIBRATED against the KO experiments (all outputs below are priors, not verdicts):
    #   - non-mechanistic KO -> no phenotype by construction (flgB/ymgD).
    #   - metabolic KO (kinetic OR not) -> the model REROUTES. fabI (not kinetic) AND glmS/gltA/pfkA/tpiA
    #     (kinetic + sole) ALL showed no growth effect, because the kinetic layer is a SOFT FBA target, not a
    #     hard bound. So NO structural metabolic flag reliably predicts a KO growth effect in this model.
    if not mechanistic:
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
            "is_sole_catalyst": sole, "is_kinetically_constraining": kinetic, "ko_effect_prior": ko_effect,
            "ko_index": g["ko_index"], "n_tu": g["n_tu"], "note": note,
            "calibration": "structural flags 0/5 at predicting KO growth effect so far — treat as prior, not verdict"}
