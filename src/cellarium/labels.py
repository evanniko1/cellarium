"""J-2b: what a design IS, in one sentence, for every surface that names one (survey, Council, interface, dataset).

A label is shorthand: a condition's name says what was added or removed, the medium holds the rest; a knockout's
name says which gene, the variant's index decides what is silenced. Read at face value, two kinds mislead:

  acceptor_added_under_oxygen          `plus_nitrate` keeps oxygen, the preferred acceptor: aerobic growth with
                                       nitrate present, not nitrate respiration
  carbon_source_added_beside_glucose   `plus_arabinose` keeps glucose: growth on glucose with arabinose present
  no_carbon_source                     `no_glucose` takes up no carbon; the registry refuses growth there
  misnamed / operon_wide / dose        what a knockout or rRNA design silences differs from its name
                                       (factors.identity)

Conditions are read from the knowledge base's own tables, as recorded in data/parca/condition_fits.json
(scripts/condition_fits.py), together with who fitted each one and on what basis (Y10).
"""
from __future__ import annotations

from . import provenance

ELECTRON_ACCEPTORS = {"NITRATE": "nitrate", "NITRITE": "nitrite", "TRIMETHYLAMINE-N-O": "TMAO", "DMSO": "DMSO"}


def condition_hazards(medium: dict | None) -> list[dict]:
    """The readings a condition's label invites and its medium rules out; [] when there are none."""
    if not medium:
        return [{"class": "unverified", "reading_ruled_out": "no medium on record to compare"}]
    out = []
    for a in medium.get("added") or []:
        if a in ELECTRON_ACCEPTORS and medium.get("oxygen"):
            name = ELECTRON_ACCEPTORS[a]
            out.append({"class": "acceptor_added_under_oxygen",
                        "reading_ruled_out": f"not {name} respiration: the medium keeps oxygen, the preferred "
                                             f"acceptor, so the run is aerobic growth with {name} present"})
    carbon = medium.get("carbon") or []
    if "glucose" in carbon:
        for c in carbon:
            if c != "glucose":
                out.append({"class": "carbon_source_added_beside_glucose",
                            "reading_ruled_out": f"not growth on {c}: the medium keeps glucose, so the run grows on "
                                                 f"glucose with {c} present"})
    if not carbon:
        out.append({"class": "no_carbon_source",
                    "reading_ruled_out": "not growth on anything: the medium has no carbon source, and the model "
                                         "takes up none yet goes on making biomass (registry: "
                                         "growth_without_a_carbon_source)"})
    return out


def _fit_clause(fit: dict) -> str:
    tfs = ", ".join(fit.get("tf_genes") or [])
    who = ("fitted by the base model" if fit.get("fitted_by") == "base"
           else f"fitted by the campaign ({fit.get('commit')})")
    if fit.get("doubling_basis") == "placeholder":
        dt = f"doubling time {fit.get('doubling_min'):g} min, a placeholder ({fit.get('doubling_source')})"
    elif fit.get("doubling_basis") == "derived":
        dt = f"doubling time {fit.get('doubling_min'):g} min, derived from data"
    else:
        dt = f"doubling time {fit.get('doubling_min'):g} min"
    return f"{who}; {tfs + ' fitted on; ' if tfs else ''}{dt}"


def describe(design: str) -> dict:
    """{design, true_label, hazards, medium?, fit?} for a design key ('perturbation/tag')."""
    from . import model
    family, _, tag = str(design).partition("/")
    base_tag = tag.split("#", 1)[0]
    if family in ("condition", "wildtype") and not model.knockout_genes(design):
        cond = base_tag or "basal"
        fit = provenance.condition_fits().get(cond)
        if fit is None:
            return {"design": design, "true_label": design, "hazards": condition_hazards(None)}
        medium = fit.get("medium") or {}
        return {"design": design, "medium": medium, "hazards": condition_hazards(medium),
                "fit": {k: fit.get(k) for k in ("fitted_by", "commit", "doubling_min", "doubling_basis",
                                                "doubling_source", "tf_genes")},
                "true_label": f"{design}: {medium.get('description', cond)}; {_fit_clause(fit)}"}
    from . import factors
    ident = factors.identity(design)
    integrity = ident.get("label_integrity")
    hazards = [] if integrity in (None, "ok") else [{"class": integrity, "notes": list(ident.get("notes") or [])[:3]}]
    return {"design": design, "true_label": ident.get("true_label") or design, "hazards": hazards}
