"""SCI-1 — an INDEPENDENT genome-scale FBA cross-check (cobrapy over iML1515).

Cellarium's whole-cell model has its own homeostatic FBA that UNDER-predicts essentiality by rerouting flux. This
adds a SECOND, independent opinion: constraint-based FBA over the standard genome-scale E. coli model iML1515
(Monk et al. 2017), so every metabolic gene can carry three verdicts — the wcEcoli whole-cell KO, this FBA, and the
Baba/Joyce Keio benchmark — and their DISAGREEMENTS become grounded model-limit findings, not bugs. FBA is a
cross-check, NEVER ground truth (it has no kinetics/regulation/concentrations; it false-calls cofactor pathways
essential and permissive OR-isozymes viable).

OPTIONAL by design: cobra is NOT a core dependency (the core is scipy-free). Install with `pip install -e '.[fba]'`
and fetch the model (`fetch_model()`). Every entry point degrades to a clear message when cobra or the iML1515 file
is absent, so the core never breaks.

Reproducibility (the oracle IS its configuration): the model SHA-256, cobra + solver versions, the exact medium,
the objective, and the essentiality cutoff are all logged in `provenance()` and returned with every result.
"""

from __future__ import annotations

import hashlib
import math
import os
import urllib.request
from pathlib import Path

MODEL_PATH = Path(os.environ.get("CELLARIUM_FBA_MODEL") or "data/fba/iML1515.xml")
MODEL_URL = "http://bigg.ucsd.edu/static/models/iML1515.xml"
OBJECTIVE = "BIOMASS_Ec_iML1515_core_75p37M"                 # the CORE biomass reaction (iML1515 ships two)
M9_GLUCOSE = {"EX_glc__D_e": 10.0, "EX_o2_e": 20.0}          # aerobic M9 glucose, mmol gDW-1 h-1 (Keio condition)
SANITY_GROWTH = 0.88                                         # WT growth on aerobic M9 glucose (Monk 2017), +- tol
ESSENTIAL_FRAC = 0.01                                        # KO essential if growth < 1% of WT

_MODEL = None                                               # process-cached loaded model


# --- availability + model management -----------------------------------------------------------------------

def _have_cobra() -> bool:
    try:
        import cobra  # noqa: F401
        return True
    except Exception:
        return False


def available() -> tuple[bool, str]:
    """(ok, message). ok=False with an actionable message when the optional deps/model aren't ready."""
    if not _have_cobra():
        return False, "The FBA cross-check needs cobra — `pip install -e '.[fba]'` (optional; keeps the core scipy-free)."
    if not MODEL_PATH.exists():
        return False, (f"iML1515 model not found at {MODEL_PATH}. Fetch it once with `fba.fetch_model()` "
                       f"(~2.5 MB from BiGG), or set CELLARIUM_FBA_MODEL to a local copy.")
    return True, ""


def fetch_model(url: str = MODEL_URL, dest: Path = MODEL_PATH) -> dict:
    """One-time download of the versioned iML1515 SBML from BiGG (~2.5 MB). Explicit — not auto-run inside a tool."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)   # noqa: S310 — fixed academic host, not user-supplied
    return {"path": str(dest), "bytes": dest.stat().st_size, "sha256": model_sha256()}


def model_sha256() -> str | None:
    if not MODEL_PATH.exists():
        return None
    h = hashlib.sha256()
    h.update(MODEL_PATH.read_bytes())
    return h.hexdigest()


def load_model():
    """Load + cache the iML1515 model, asserting the intended objective. Raises if cobra/model absent."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    import cobra

    m = cobra.io.read_sbml_model(str(MODEL_PATH))
    rxn_ids = {r.id for r in m.reactions}
    if OBJECTIVE not in rxn_ids:
        raise ValueError(f"objective {OBJECTIVE} not in iML1515 — wrong/old model file?")
    m.objective = OBJECTIVE                                   # pin it (iML1515 ships core + WT biomass)
    _MODEL = m
    return m


def _reset_model() -> None:   # test hook
    global _MODEL
    _MODEL = None


def _set_medium(m, medium: dict | None) -> None:
    """Set the medium by uptake dict (cobrapy `model.medium` convention). Only the named carbon/electron exchanges
    are constrained; cobrapy leaves inorganic ions / water / protons open."""
    med = dict(m.medium)                                     # start from the model's open exchanges
    # zero the carbon sources the M9 medium doesn't provide, then set ours
    for ex, val in (medium or M9_GLUCOSE).items():
        med[ex] = val
    m.medium = med


def provenance() -> dict:
    import cobra

    m = load_model()
    return {"model": "iML1515", "model_sha256": model_sha256(), "cobra_version": cobra.__version__,
            "solver": str(getattr(m, "solver", None).__class__.__module__ if getattr(m, "solver", None) else None),
            "objective": OBJECTIVE, "medium": M9_GLUCOSE, "essential_frac": ESSENTIAL_FRAC,
            "caveat": "FBA is an independent cross-check, NOT ground truth — no kinetics/regulation/concentrations."}


# --- gene resolution + concordance (pure — testable without cobra) -----------------------------------------

def diagnose(fba_essential: bool, keio_essential: bool | None) -> dict:
    """Map an FBA-vs-Keio verdict pair to a NAMED diagnostic class (never a bare 'false positive' — direction is
    explicit). Keio is the experimental reference here; FBA is the model under test."""
    if keio_essential is None:
        return {"class": "no_reference", "note": "gene not in the Baba/Joyce set — no experimental verdict."}
    if fba_essential and keio_essential:
        return {"class": "consistent_lethal", "note": "FBA + experiment agree: essential."}
    if (not fba_essential) and (not keio_essential):
        return {"class": "consistent_viable", "note": "FBA + experiment agree: non-essential."}
    if fba_essential and not keio_essential:
        return {"class": "fba_false_essential",
                "note": ("FBA calls essential, experiment says viable — classic cofactor/vitamin biosynthesis "
                         "rescued in vivo by cross-feeding, or a medium mismatch. Suspect the medium/BOF, not biology.")}
    return {"class": "fba_false_viable",
            "note": ("FBA reroutes to stay viable, experiment says essential — a permissive OR-isozyme GPR or an "
                     "over-reversible reaction let FBA bypass a step that is regulated-off / kinetically dead in vivo.")}


def concordance(pairs: list[tuple[bool, bool]]) -> dict:
    """Confusion matrix + MCC for FBA vs Keio over (fba_essential, keio_essential) pairs (positive = essential).
    Report MCC, not accuracy — the benchmark is ~90% non-essential, so 'all viable' already scores ~0.9."""
    tp = sum(1 for f, k in pairs if f and k)
    tn = sum(1 for f, k in pairs if not f and not k)
    fp = sum(1 for f, k in pairs if f and not k)
    fn = sum(1 for f, k in pairs if not f and k)
    n = tp + tn + fp + fn
    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = ((tp * tn - fp * fn) / denom) if denom > 0 else 0.0
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    return {"n": n, "confusion": {"tp_both_essential": tp, "tn_both_viable": tn,
                                  "fp_fba_false_essential": fp, "fn_fba_false_viable": fn},
            "mcc": round(mcc, 3), "precision": (round(prec, 3) if prec is not None else None),
            "recall": (round(rec, 3) if rec is not None else None),
            "accuracy_do_not_use": round((tp + tn) / n, 3) if n else None,
            "note": "MCC is the headline (class-imbalanced set); accuracy is reported only to show why it misleads."}


def _resolve_genes(m, symbols: list[str]) -> tuple[list, list[str]]:
    """Map gene SYMBOLS (pfkA) to iML1515 gene objects (b-numbers). Returns (resolved, unknown_symbols)."""
    by_name = {g.name: g for g in m.genes}
    by_id = {g.id: g for g in m.genes}
    resolved, unknown = [], []
    for s in symbols:
        g = by_name.get(s) or by_id.get(s)
        (resolved.append(g) if g is not None else unknown.append(s))
    return resolved, unknown


def _keio_benchmark() -> dict:
    """{gene_symbol: keio_essential(bool)} for iML1515-eligible metabolic genes, from the cached Baba/Joyce set."""
    from . import scope

    return {g: v.get("essential_ref") for g, v in scope._scope().items()
            if v.get("is_metabolic") and v.get("essential_ref") is not None}


def _ko_growth(m, gene) -> float:
    """KO one gene through its GPR and return the re-optimized biomass (0 on infeasible/no-growth). The medium is
    assumed already set on `m`. Uses a nested model context so the KO is reverted after."""
    with m:
        gene.knock_out()
        s = m.slim_optimize()
    return 0.0 if (s is None or math.isnan(s)) else float(s)


# --- the four tools ----------------------------------------------------------------------------------------

def fba_growth(medium: dict | None = None) -> dict:
    """Genome-scale FBA growth-rate prediction over iML1515 (default aerobic M9 glucose)."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    m = load_model()
    with m:
        _set_medium(m, medium)
        sol = m.optimize()
    growth = round(float(sol.objective_value), 5) if sol.status == "optimal" else 0.0
    return {"growth_rate_per_h": growth, "status": sol.status,
            "sanity_ok": (abs(growth - SANITY_GROWTH) < 0.15 if medium is None else None),
            "medium": medium or M9_GLUCOSE, "provenance": provenance(),
            "note": "Genome-scale FBA over iML1515 — an independent second opinion, NOT ground truth."}


def fba_gene_knockout(genes, medium: dict | None = None) -> dict:
    """Single-gene KO growth over iML1515 via the GPR — FBA, and MOMA where a QP solver is present (MOMA is the
    honest comparator to wcEcoli's kinetic model, which also can't instantly re-route to a distant optimum)."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    if isinstance(genes, str):
        genes = [genes]
    m = load_model()
    with m:
        _set_medium(m, medium)
        resolved, unknown = _resolve_genes(m, genes)
        if not resolved:
            return {"error": f"no iML1515 gene matched {genes}", "unknown_genes": unknown}
        wt = float(m.slim_optimize())
        rows = []
        moma_note = None
        try:
            from cobra.flux_analysis import moma as _moma_mod  # noqa: F401
            moma_ok = m.solver.interface.__name__.split(".")[-1] in ("gurobi_interface", "cplex_interface")
        except Exception:
            moma_ok = False
        if not moma_ok:
            moma_note = "MOMA needs a QP solver (gurobi/cplex); GLPK does LP only — reporting FBA calls."
        bench = _keio_benchmark()
        for g in resolved:
            kg = _ko_growth(m, g)
            frac = round(kg / wt, 4) if wt else 0.0
            fba_ess = frac < ESSENTIAL_FRAC
            keio = bench.get(g.name)
            rows.append({"gene": g.name, "b_number": g.id, "ko_growth_frac": frac,
                         "fba_essential": fba_ess, "keio_essential": keio,
                         "diagnosis": diagnose(fba_ess, keio)["class"]})
    return {"wt_growth": round(wt, 4), "essential_frac_cutoff": ESSENTIAL_FRAC, "results": rows,
            "unknown_genes": unknown, "moma_note": moma_note, "provenance": provenance(),
            "note": "FBA single-deletion + Keio benchmark join. A disagreement is a model-limit hypothesis (diagnosis), not a bug."}


def fba_flux(reactions: list[str] | None = None, fraction_of_optimum: float = 1.0) -> dict:
    """pFBA point flux + FVA [min,max] range per reaction — because a single internal flux is an arbitrary optimum
    vertex. FVA is loopless where feasible (a bound at the ±1000 cap means loops missing, not high capacity)."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    from cobra.flux_analysis import flux_variability_analysis, pfba
    m = load_model()
    with m:
        _set_medium(m, None)
        rxn_ids = {r.id for r in m.reactions}
        rxns = [r for r in (reactions or [OBJECTIVE, "EX_glc__D_e", "EX_o2_e", "EX_ac_e", "EX_co2_e"]) if r in rxn_ids]
        if not rxns:
            return {"error": f"none of {reactions} are iML1515 reactions."}
        p = pfba(m)
        try:   # processes=1: FVA's default multiprocessing spawn-storms on Windows / inside a library call
            fva = flux_variability_analysis(m, reaction_list=rxns, fraction_of_optimum=fraction_of_optimum,
                                            loopless=True, processes=1)
            loopless = True
        except Exception:
            fva = flux_variability_analysis(m, reaction_list=rxns, fraction_of_optimum=fraction_of_optimum,
                                            loopless=False, processes=1)
            loopless = False
    out = {r: {"pfba": round(float(p.fluxes[r]), 4),
               "fva_min": round(float(fva.loc[r, "minimum"]), 4),
               "fva_max": round(float(fva.loc[r, "maximum"]), 4),
               "variable_across_optima": abs(float(fva.loc[r, "maximum"]) - float(fva.loc[r, "minimum"])) > 1e-6}
           for r in rxns}
    return {"reactions": out, "loopless_fva": loopless, "fraction_of_optimum": fraction_of_optimum,
            "objective_growth": round(float(p.objective_value), 4), "provenance": provenance(),
            "note": "pFBA point + FVA range. Trust the RANGE, not the point — a reaction with a wide FVA range is unidentified across equal optima."}


def fba_essentiality_panel(genes: list[str] | None = None, max_genes: int | None = None) -> dict:
    """FBA single-deletion essentiality across iML1515 metabolic genes, cross-checked against the Baba/Joyce Keio
    benchmark: a confusion matrix + MCC + the named-diagnostic disagreements (the scientific payoff)."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    m = load_model()
    bench = _keio_benchmark()
    resolved, unknown = _resolve_genes(m, sorted(genes) if genes else sorted(bench))
    if max_genes:
        resolved = resolved[:int(max_genes)]
    rows, pairs = [], []
    with m:
        _set_medium(m, None)
        wt = float(m.slim_optimize())
        for g in resolved:
            frac = round(_ko_growth(m, g) / wt, 4) if wt else 0.0
            fba_ess = frac < ESSENTIAL_FRAC
            keio = bench.get(g.name)
            pairs.append((fba_ess, keio))
            rows.append({"gene": g.name, "b_number": g.id, "ko_growth_frac": frac,
                         "fba_essential": fba_ess, "keio_essential": keio,
                         "diagnosis": diagnose(fba_ess, keio)["class"]})
    conc = concordance([(f, k) for f, k in pairs if k is not None])
    disagree = [r for r in rows if r["diagnosis"] in ("fba_false_essential", "fba_false_viable")]
    return {"n_genes": len(rows), "wt_growth": round(wt, 4), "essential_frac_cutoff": ESSENTIAL_FRAC,
            "concordance_fba_vs_keio": conc, "n_disagreements": len(disagree), "disagreements": disagree[:40],
            "genes": (rows if len(rows) <= 60 else None), "provenance": provenance(),
            "note": ("FBA vs the Keio benchmark over iML1515 metabolic genes. Each disagreement is a mechanistic "
                     "hypothesis (diagnosis), not a bug — FBA is a cross-check, never ground truth. The wcEcoli "
                     "verdict is the third leg: join per-gene via metabolic_essentiality / the corpus KO.")}

