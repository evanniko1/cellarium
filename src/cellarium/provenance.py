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
    # A wildtype OR `condition` run is in-sample ONLY when its CONDITION is one the fit actually targeted (M-3):
    # `wildtype` in an unfitted medium (e.g. wildtype/acetate) is a genuine out-of-sample prediction, NOT in-sample
    # by virtue of being 'wildtype'. condition defaults to 'basal' (the canonical wildtype/basal baseline).
    if perturbation in ("wildtype", "condition"):
        return (condition or "basal") in IN_SAMPLE_CONDITIONS
    return False  # gene_knockout / ppgpp_conc / timeline / objective-weight / ... are perturbations the fit didn't target


def classify(perturbation: str, condition: str | None = None) -> dict:
    in_sample = _is_in_sample(perturbation, condition)
    return {"provenance": "in_sample" if in_sample else "out_of_sample", "note": _IN_NOTE if in_sample else _OUT_NOTE}


def tag(perturbation: str, condition: str | None = None) -> str:
    """Just the label, for annotating list rows."""
    return "in_sample" if _is_in_sample(perturbation, condition) else "out_of_sample"


# --- H-3: per-run environment provenance (the reproducibility bundle) ---------------------------------------

def _git_commit() -> str | None:
    """The repo's current short commit, run in the repo root (not the process CWD) so it's correct regardless of
    where the app was launched. None when git is absent, this isn't a checkout, or the call errors/times out."""
    import subprocess
    from pathlib import Path
    try:
        root = Path(__file__).resolve().parents[2]
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(root),
                           capture_output=True, text=True, timeout=3)
        return (r.stdout.strip() or None) if r.returncode == 0 else None
    except Exception:
        return None


def run_environment() -> dict:
    """The reproducibility bundle for a run (H-3): the interpreter, the repo's git commit, and the pinned versions of
    the load-bearing dependencies — recorded per Council run alongside the model + temperature (M-2/LLM-3) so a result
    can be reproduced against the exact code + library stack (see requirements.lock for the full pin set). Best-effort:
    any lookup that fails degrades to None, never raising."""
    import platform
    from importlib import metadata as _md

    packages: dict = {}
    for pkg in ("anthropic", "pydantic", "numpy", "duckdb", "pyarrow"):
        try:
            packages[pkg] = _md.version(pkg)
        except Exception:
            packages[pkg] = None
    return {"python": platform.python_version(), "git_commit": _git_commit(), "packages": packages}
