"""Provenance guardrail — is a corpus quantity IN-SAMPLE (fitted) or OUT-OF-SAMPLE (predicted)?

The H1/H2 pair proved why this matters: H1 (anaerobic regulon) *looked* like a triumphant confirmation but is
in-sample — ParCa fits condition-specific expression, so the model was calibrated to match it; agreement is
consistency, not predictive validation. H2 (Mg->ribosome) is out-of-sample — the fit never targeted it, so its
failure is a genuine, informative model boundary. Without this tag an agent (or reader) over-credits in-sample
agreement. Coarse per-design classification by perturbation type; see docs/CORPUS_OBSERVATIONS.md §6.1/§F.
"""

from __future__ import annotations

# Steady state of a ParCa-fitted condition is calibrated (in-sample). A perturbation that breaks a fitted
# relationship (a clamp, a knockout, a dynamic shift) elicits a genuine prediction (out-of-sample).
IN_SAMPLE_PERTURBATIONS = {"wildtype", "condition"}

_IN_NOTE = ("Steady state of a ParCa-fitted condition — the model was calibrated to match this. Agreement with "
            "data/literature is CONSISTENCY, not predictive validation; do not cite it as the model predicting.")
_OUT_NOTE = ("A perturbation/response the fit did not target — a genuine model prediction. Predictive validation "
             "(and informative failure, e.g. the Mg->ribosome boundary) lives here.")


def classify(perturbation: str, condition: str | None = None) -> dict:
    if perturbation in IN_SAMPLE_PERTURBATIONS:
        return {"provenance": "in_sample", "note": _IN_NOTE}
    return {"provenance": "out_of_sample", "note": _OUT_NOTE}


def tag(perturbation: str, condition: str | None = None) -> str:
    """Just the label, for annotating list rows."""
    return "in_sample" if perturbation in IN_SAMPLE_PERTURBATIONS else "out_of_sample"
