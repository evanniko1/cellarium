"""Provenance guardrail — is a corpus quantity IN-SAMPLE (fitted) or OUT-OF-SAMPLE (predicted)?

The H1/H2 pair proved why this matters: H1 (anaerobic regulon) *looked* like a triumphant confirmation but is
in-sample — ParCa fits condition-specific expression, so the model was calibrated to match it; agreement is
consistency, not predictive validation. H2 (Mg->ribosome) is out-of-sample — the fit never targeted it, so its
failure is a genuine, informative model boundary. Without this tag an agent (or reader) over-credits in-sample
agreement. Coarse per-design classification by perturbation type; see docs/CORPUS_OBSERVATIONS.md §6.1/§F.
"""

from __future__ import annotations

# IN-SAMPLE = a condition the model was actually fit to. wcEcoli's fit uses measured RNA-seq for a small set of
# media (M9 Glucose +/-AAs, N-/P-limited, glycerol) plus the modeled-TF regulons (e.g. FNR/ArcA -> anaerobic).
# CRITICAL (audit M4): most named `condition`s are NOT fit to measured data — their expression is network-DERIVED
# from the media definition, so they are OUT-of-sample (e.g. minus_magnesium: H2's Mg->ribosome boundary). The
# old rule tagged every `condition` in-sample and OVER-credited these. We classify conservatively — in-sample only
# for the clearly-fitted conditions; when unsure, out-of-sample (under-crediting is the safe error here).
IN_SAMPLE_CONDITIONS = {"basal", "glc_20mM", "glc_5mM", "glc_2mM", "with_aa", "no_oxygen"}

_IN_NOTE = ("A ParCa-fitted condition (measured RNA-seq or a modeled-TF regulon) — the model was calibrated to "
            "match this. Agreement with data/literature is CONSISTENCY, not predictive validation.")
_OUT_NOTE = ("The fit did not target this (a perturbation, or a stress/media condition whose expression is network-"
             "DERIVED, not fit to measured data — e.g. the Mg->ribosome boundary). A genuine model prediction; "
             "predictive validation AND informative failure live here.")


def _is_in_sample(perturbation: str, condition: str | None) -> bool:
    if perturbation == "wildtype":
        return True
    if perturbation == "condition":
        return condition in IN_SAMPLE_CONDITIONS
    return False  # gene_knockout / ppgpp_conc / timeline / objective-weight / ... are perturbations the fit didn't target


def classify(perturbation: str, condition: str | None = None) -> dict:
    in_sample = _is_in_sample(perturbation, condition)
    return {"provenance": "in_sample" if in_sample else "out_of_sample", "note": _IN_NOTE if in_sample else _OUT_NOTE}


def tag(perturbation: str, condition: str | None = None) -> str:
    """Just the label, for annotating list rows."""
    return "in_sample" if _is_in_sample(perturbation, condition) else "out_of_sample"
