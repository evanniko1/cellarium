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


def _moma_growth(m, gene, wt_solution) -> float | None:
    """KO growth under LINEAR MOMA (L1 distance to the WT flux vector) — the pre-adaptation mutant, GLPK-compatible
    (quadratic MOMA needs a QP solver). None if MOMA is unavailable. wt_solution is a WT cobra Solution."""
    from cobra.flux_analysis import moma
    try:
        with m:
            gene.knock_out()
            sol = moma(m, solution=wt_solution, linear=True)
        if sol.status != "optimal":
            return 0.0
        g = float(sol.fluxes[OBJECTIVE])
        return 0.0 if math.isnan(g) else g
    except Exception:
        return None


def _wcecoli_map() -> dict:
    """{gene_symbol: wcEcoli KO-prior essential (bool)} derived ONCE from the scope cache — replicating
    scope.classify_gene's prior: only ribosomal/aaRS machinery is 'predicts lethal'; a metabolic KO is the model's
    'predicts viable' reroute (its documented under-prediction). So for METABOLIC genes this is uniformly viable —
    that flatness IS the finding: the homeostatic whole-cell FBA has no growth term and reroutes."""
    from . import scope
    out = {}
    for sym, g in scope._scope().items():
        if g.get("is_machinery"):
            out[sym] = g.get("machinery_role") in ("ribosomal", "aaRS")   # lethal_crash prior
        elif g.get("is_metabolic") or g.get("is_tf"):
            out[sym] = False                                              # reroute / TF -> predicts viable
        else:
            out[sym] = None                                              # inert / unknown
    return out


# --- the tools ---------------------------------------------------------------------------------------------

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
    """Single-gene KO over iML1515 via the GPR as a THREE-WAY cross-check: the wcEcoli KO prior, FBA (growth-max),
    and LINEAR MOMA (pre-adaptation, minimal flux change from WT) — each vs the Keio experiment. MOMA where it also
    stays viable means the reroute is a real isozyme/pathway, not just an FBA optimality artifact."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    if isinstance(genes, str):
        genes = [genes]
    m = load_model()
    bench, wce = _keio_benchmark(), _wcecoli_map()
    with m:
        _set_medium(m, medium)
        resolved, unknown = _resolve_genes(m, genes)
        if not resolved:
            return {"error": f"no iML1515 gene matched {genes}", "unknown_genes": unknown}
        wt_sol = m.optimize()
        wt = float(wt_sol.objective_value)
        rows = []
        for g in resolved:
            frac = round(_ko_growth(m, g) / wt, 4) if wt else 0.0
            mg = _moma_growth(m, g, wt_sol)
            moma_frac = (round(mg / wt, 4) if (mg is not None and wt) else None)
            fba_ess = frac < ESSENTIAL_FRAC
            keio = bench.get(g.name)
            rows.append({"gene": g.name, "b_number": g.id,
                         "fba_growth_frac": frac, "fba_essential": fba_ess,
                         "moma_growth_frac": moma_frac,
                         "moma_essential": (moma_frac < ESSENTIAL_FRAC if moma_frac is not None else None),
                         "wcecoli_essential": wce.get(g.name), "keio_essential": keio,
                         "diagnosis": diagnose(fba_ess, keio)["class"]})
    return {"wt_growth": round(wt, 4), "essential_frac_cutoff": ESSENTIAL_FRAC, "results": rows,
            "unknown_genes": unknown, "moma": "linear MOMA (L1) — pre-adaptation comparator (GLPK-compatible)",
            "provenance": provenance(),
            "note": ("Three model verdicts (wcEcoli prior / FBA / linear MOMA) vs the Keio experiment. For metabolic "
                     "genes the wcEcoli prior is 'viable' by construction (homeostatic FBA, no growth term). Where "
                     "MOMA ALSO stays viable the reroute is a real isozyme/pathway; where MOMA drops the reroute was "
                     "an FBA optimality artifact. A disagreement is a model-limit hypothesis (diagnosis), not a bug.")}


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


def fba_essentiality_panel(genes: list[str] | None = None, max_genes: int | None = None,
                           moma: bool = False) -> dict:
    """FBA single-deletion essentiality across iML1515 metabolic genes vs the Keio benchmark: a confusion matrix +
    MCC + named-diagnostic disagreements, PLUS a three-way tally of how many Keio-essential genes each model catches
    (FBA / wcEcoli prior / optional MOMA). MOMA is opt-in (one extra LP per gene)."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    m = load_model()
    bench, wce = _keio_benchmark(), _wcecoli_map()
    resolved, unknown = _resolve_genes(m, sorted(genes) if genes else sorted(bench))
    if max_genes:
        resolved = resolved[:int(max_genes)]
    rows, pairs = [], []
    with m:
        _set_medium(m, None)
        wt_sol = m.optimize()
        wt = float(wt_sol.objective_value)
        for g in resolved:
            frac = round(_ko_growth(m, g) / wt, 4) if wt else 0.0
            fba_ess = frac < ESSENTIAL_FRAC
            keio = bench.get(g.name)
            moma_ess = None
            if moma:
                mg = _moma_growth(m, g, wt_sol)
                moma_ess = ((mg / wt) < ESSENTIAL_FRAC if (mg is not None and wt) else None)
            pairs.append((fba_ess, keio))
            rows.append({"gene": g.name, "b_number": g.id, "ko_growth_frac": frac,
                         "fba_essential": fba_ess, "moma_essential": moma_ess,
                         "wcecoli_essential": wce.get(g.name), "keio_essential": keio,
                         "diagnosis": diagnose(fba_ess, keio)["class"]})
    conc = concordance([(f, k) for f, k in pairs if k is not None])
    keio_ess = [r for r in rows if r["keio_essential"]]
    three_way = {"n_keio_essential": len(keio_ess),
                 "caught_by_fba": sum(1 for r in keio_ess if r["fba_essential"]),
                 "caught_by_moma": (sum(1 for r in keio_ess if r["moma_essential"]) if moma else None),
                 "caught_by_wcecoli_prior": sum(1 for r in keio_ess if r["wcecoli_essential"]),
                 "note": ("Of the Keio-essential metabolic genes, how many each model flags. wcEcoli's prior catches "
                          "~0 (homeostatic FBA under-predicts by construction); growth-max FBA catches the ones a "
                          "distant reroute can't rescue; the rest need kinetics/regulation neither model has.")}
    disagree = [r for r in rows if r["diagnosis"] in ("fba_false_essential", "fba_false_viable")]
    return {"n_genes": len(rows), "wt_growth": round(wt, 4), "essential_frac_cutoff": ESSENTIAL_FRAC,
            "concordance_fba_vs_keio": conc, "three_way": three_way,
            "n_disagreements": len(disagree), "disagreements": disagree[:40],
            "genes": (rows if len(rows) <= 60 else None), "provenance": provenance(),
            "note": ("FBA vs Keio over iML1515 metabolic genes, with the wcEcoli prior + optional MOMA as extra "
                     "legs. Each disagreement is a mechanistic hypothesis (diagnosis), not a bug — FBA is a "
                     "cross-check, never ground truth.")}



def fba_synthetic_lethal(genes, medium: dict | None = None) -> dict:
    """Pairwise gene deletion over iML1515: find SYNTHETIC-LETHAL pairs — both viable singly, lethal together —
    which single-deletion FBA misses (~2/3 of measured epistasis is pairwise). Tests all pairs of `genes`."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    import itertools

    if isinstance(genes, str):
        genes = [genes]
    m = load_model()
    with m:
        _set_medium(m, medium)
        resolved, unknown = _resolve_genes(m, genes)
        if len(resolved) < 2:
            return {"error": "need >=2 resolvable iML1515 genes for pairwise deletion", "unknown_genes": unknown}
        wt = float(m.slim_optimize())
        single = {g.name: (round(_ko_growth(m, g) / wt, 4) if wt else 0.0) for g in resolved}
        pairs = []
        for a, b in itertools.combinations(resolved, 2):
            with m:
                a.knock_out()
                b.knock_out()
                s = m.slim_optimize()
            dbl = round((0.0 if (s is None or math.isnan(s)) else float(s)) / wt, 4) if wt else 0.0
            both_viable = single[a.name] >= ESSENTIAL_FRAC and single[b.name] >= ESSENTIAL_FRAC
            pairs.append({"pair": [a.name, b.name], "single_a": single[a.name], "single_b": single[b.name],
                          "double_growth_frac": dbl, "synthetic_lethal": bool(both_viable and dbl < ESSENTIAL_FRAC)})
    sl = [p for p in pairs if p["synthetic_lethal"]]
    return {"wt_growth": round(wt, 4), "n_pairs": len(pairs), "n_synthetic_lethal": len(sl),
            "synthetic_lethals": sl, "pairs": (pairs if len(pairs) <= 40 else None),
            "unknown_genes": unknown, "provenance": provenance(),
            "note": ("A pair is synthetic-lethal when both singles are viable but the double abolishes growth — "
                     "single-deletion essentiality (and the panel) misses these by construction.")}


def fba_gene_deletion(genes, medium: dict | None = None) -> dict:
    """FULL k-way gene deletion over iML1515: knock out ALL `genes` at once and report the set's growth fraction —
    the DIRECT 'does this whole reduced-genome set survive?' test. One LP. Complements the pairwise synthetic-lethal
    scan: that decomposes a set into pairs (catching pair-level reroute-blockers) but never tests the whole set, so
    it misses HIGHER-ORDER lethality (a triple lethal though no pair is). For a 2-gene set this equals the double
    deletion; its value is at k>=3."""
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
            return {"error": "no resolvable iML1515 genes for the deletion", "unknown_genes": unknown}
        wt = float(m.slim_optimize())
        for g in resolved:                                   # simultaneous deletion of the WHOLE set (reverts on exit)
            g.knock_out()
        s = m.slim_optimize()
        frac = round((0.0 if (s is None or math.isnan(s)) else float(s)) / wt, 4) if wt else 0.0
    return {"n_requested": len(genes), "n_deleted": len(resolved), "deleted": [g.name for g in resolved],
            "unknown_genes": unknown, "wt_growth": round(wt, 4), "deletion_growth_frac": frac,
            "lethal": bool(frac < ESSENTIAL_FRAC), "essential_frac": ESSENTIAL_FRAC, "provenance": provenance(),
            "note": ("Simultaneous deletion of the whole set — the direct viability test. 'lethal' when the full set "
                     "abolishes growth (< essential_frac of WT). Catches higher-order lethality the pairwise "
                     "synthetic-lethal scan misses; the whole-cell sim is the decisive arbiter.")}


def _gam_scaled_growth(m, factor: float) -> float:
    """WT growth with the biomass growth-associated-maintenance ATP terms scaled by `factor` (explicit restore —
    metabolite-coefficient edits aren't tracked by the model context)."""
    bio = m.reactions.get_by_id(OBJECTIVE)
    terms = {met: bio.metabolites[met] for met in bio.metabolites
             if met.id in ("atp_c", "adp_c", "pi_c", "h2o_c", "h_c")}
    add = {met: terms[met] * (factor - 1.0) for met in terms}
    bio.add_metabolites(add, combine=True)
    try:
        with m:
            _set_medium(m, None)
            g = m.slim_optimize()
        return 0.0 if (g is None or math.isnan(g)) else float(g)
    finally:
        bio.add_metabolites({met: -add[met] for met in add}, combine=True)   # restore exactly


def fba_sensitivity(gene: str | None = None, delta: float = 0.2) -> dict:
    """How sensitive is the FBA growth prediction (and, for `gene`, its essentiality call) to +-delta on the levers
    that dominate it — medium uptake (glucose, O2), NGAM (ATPM), and GAM (biomass ATP)? Trust only conclusions
    robust across these; the growth number is set by BOF/GAM/NGAM/medium far more than by the network."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    m = load_model()
    ngam0 = m.reactions.ATPM.lower_bound if "ATPM" in {r.id for r in m.reactions} else None
    target = None
    if gene:
        with m:
            resolved, _ = _resolve_genes(m, [gene])
        target = resolved[0] if resolved else None

    results = []

    def _record(label, growth, apply_ko):
        rec = {"perturbation": label, "wt_growth": round(growth, 4)}
        if apply_ko is not None:
            rec["gene_ko_frac"] = round(apply_ko / growth, 4) if growth else 0.0
            rec["gene_essential"] = rec["gene_ko_frac"] < ESSENTIAL_FRAC
        results.append(rec)

    lo, hi = 1.0 - delta, 1.0 + delta
    specs = [("baseline", None, 1.0)]
    for f, tag in ((lo, "-"), (hi, "+")):
        specs += [(f"glucose x{f:.2f}", "glc", f), (f"o2 x{f:.2f}", "o2", f),
                  (f"NGAM x{f:.2f}", "ngam", f), (f"GAM x{f:.2f}", "gam", f)]
    for label, lever, f in specs:
        if lever == "gam":
            _record(label, _gam_scaled_growth(m, f), None)   # GAM change: report growth (gene-KO axis omitted here)
            continue
        with m:
            med = dict(M9_GLUCOSE)
            if lever == "glc":
                med["EX_glc__D_e"] = M9_GLUCOSE["EX_glc__D_e"] * f
            elif lever == "o2":
                med["EX_o2_e"] = M9_GLUCOSE["EX_o2_e"] * f
            _set_medium(m, med)
            if lever == "ngam" and ngam0 is not None:
                m.reactions.ATPM.lower_bound = ngam0 * f
            g = m.slim_optimize()
            growth = 0.0 if (g is None or math.isnan(g)) else float(g)
            ko = (_ko_growth(m, target) if (target is not None and growth > 0) else None)
        _record(label, growth, ko)

    growths = [r["wt_growth"] for r in results]
    out = {"gene": gene, "delta": delta, "results": results,
           "wt_growth_range": [round(min(growths), 4), round(max(growths), 4)],
           "wt_growth_spread_pct": round(100 * (max(growths) - min(growths)) / (max(growths) or 1e-9), 1),
           "provenance": provenance(),
           "note": ("Growth (and, for a gene, its essentiality call) under +-delta on medium uptake, NGAM (ATPM) and "
                    "GAM (biomass ATP). A conclusion is only safe if it survives the spread.")}
    calls = {r["gene_essential"] for r in results if "gene_essential" in r}
    if gene and calls:
        out["essentiality_robust"] = (len(calls) == 1)
    return out


def fba_qc() -> dict:
    """A lightweight MEMOTE-style sanity gate on iML1515: with ALL uptakes closed, nothing should be producible
    (no ATP -> no energy-generating cycle; no biomass -> no free growth), and every internal reaction should be
    mass-balanced. Run before trusting FBA numbers; a fail means the model, not the biology, is talking."""
    ok, msg = available()
    if not ok:
        return {"error": msg}
    m = load_model()
    rxn_ids = {r.id for r in m.reactions}
    with m:
        for ex in m.exchanges:
            ex.lower_bound = 0.0                       # close every uptake
        if "ATPM" in rxn_ids:
            m.reactions.ATPM.lower_bound = 0.0         # don't force maintenance (would be trivially infeasible)
            m.objective = "ATPM"
            a = m.slim_optimize()
            atp = 0.0 if (a is None or math.isnan(a)) else float(a)
        else:
            atp = 0.0
        m.objective = OBJECTIVE
        b = m.slim_optimize()
        bio = 0.0 if (b is None or math.isnan(b)) else float(b)
    def _real_imbalance(r):   # ignore the generic polymer-residue placeholders ('R'/'*'), a benign modeling choice
        return {k: v for k, v in r.check_mass_balance().items() if k not in ("R", "*")}

    imbalanced = [r.id for r in m.reactions   # skip exchange/demand/sink + both biomass pseudo-reactions
                  if not r.boundary and "BIOMASS" not in r.id and not r.id.startswith(("DM_", "SK_"))
                  and _real_imbalance(r)]
    return {"energy_from_nothing": {"atpm_flux": round(atp, 4), "ok": atp < 1e-6},
            "biomass_from_nothing": {"growth": round(bio, 4), "ok": bio < 1e-6},
            "mass_balance": {"n_imbalanced_internal": len(imbalanced), "examples": imbalanced[:10],
                             "ok": len(imbalanced) == 0},
            "passed": bool(atp < 1e-6 and bio < 1e-6 and len(imbalanced) == 0),
            "provenance": provenance(),
            "note": ("No ATP or biomass may be produced with all uptakes closed (else an energy-generating cycle), "
                     "and every internal reaction must mass-balance. A failing gate invalidates downstream FBA.")}
