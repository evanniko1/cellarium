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
    if not mechanistic:
        note = ("This gene is EXPRESSED but its function is NOT mechanistically simulated. A KO will show "
                "little/no phenotype BY CONSTRUCTION; a null reflects MODEL SCOPE, not biological dispensability.")
    elif g["is_metabolic"] and not sole:
        note = ("Metabolic, but NOT the sole catalyst of any reaction — the model has an alternate route, so a KO "
                "is likely rerouted (viable) even if the gene is essential in reality. Weak KO-essentiality test.")
    elif sole:
        note = ("Metabolic AND the sole catalyst of >=1 reaction — a KO removes the only route, so if that "
                "reaction is biomass-required the model should predict lethality/arrest. Strong KO-essentiality test.")
    else:
        note = "Mechanistically simulated (" + role + ") — a KO is a genuine, interpretable prediction."
    return {"symbol": symbol, "known": True, "mechanistic": mechanistic, "role": role,
            "is_sole_catalyst": sole, "ko_index": g["ko_index"], "n_tu": g["n_tu"], "note": note}
