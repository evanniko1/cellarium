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

Each gene also carries a GROUND-TRUTH essentiality flag (`essential_reference`) from an external benchmark (Baba
2006 Keio + Joyce 2006, glucose-minimal — wcEcoli's own validation set), and `classify_gene` reports a `benchmark`
comparison of the model's KO prior against it. The decisive case: the metabolic 'reroute' prior UNDER-predicts for
benchmark-essential enzymes (fabI/glmS/gltA are essential yet the model KO is viable) — so a 'no effect' KO is a
model-scope statement, and the benchmark, not the sim, is the essentiality authority.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCOPE_CACHE = Path("data/cache/gene_scope.json")


@lru_cache(maxsize=1)
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
        aaRS_lit = (" This is documented, expected behavior for aaRS: Choi & Covert 2023 (NAR, doi:10.1093/nar/"
                    "gkad435) found aaRS kcats must be fit ~7.6x above in vitro just to sustain the proteome, and "
                    "perturbing aaRS activity is 'catastrophic' — a full KO is the extreme of that."
                    if machinery_role == "aaRS" else "")
        note = ("Core central-dogma machinery (" + str(machinery_role) + "). A full single-gene KO removes an "
                "essential subunit of translation/transcription/replication — EMPIRICALLY the sim CRASHES rather "
                "than reaching a phenotype (gltX aaRS KO: ribosome_conc 21->2.15, NegativeCountsError in "
                "PolypeptideElongation, 4/4 seeds). This is a model breakdown, NOT an interpretable result." + aaRS_lit +
                " For a measurable capacity effect use a GRADED perturbation (rrna_operon_knockout, ppgpp_conc).")
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
        note = ("Metabolic AND a kinetic-constraint enzyme, but the metabolism FBA objective is deviation-"
                "minimizing over concentration ranges + kinetic targets with NO growth/biomass term (objectiveType "
                "'homeostatic_kinetics_mixed'), so a KO has nothing to degrade — the solver just reroutes to keep "
                "pools in range. The gene_knockout variant zeroes transcription, and since initial counts derive "
                "from expression the enzyme is 0 from gen-0 (verified fabI/glmS/gltX) — so this is the pure reroute, "
                "NOT a dilution artifact. EMPIRICALLY glmS/gltA/pfkA/tpiA "
                "(all kinetic+sole-catalyst) showed NO growth effect. Do NOT expect a phenotype; the only reliable "
                "gene-specific essentiality test is a SEPARATE biomass/feasibility FBA single-deletion on the "
                "metabolic network (structural flags have a 0/5 hit-rate here).")
    else:
        ko_effect = "mechanistic_other"
        note = "Mechanistically simulated (" + role + ") — a KO is a genuine, interpretable prediction."
    # GROUND-TRUTH comparison: the model's KO prior vs an external essentiality benchmark (Baba 2006 Keio + Joyce
    # 2006, glucose-minimal). This turns the self-reported "0/5 hit-rate" into a benchmarked statement, and flags
    # the decisive failure mode: model expects a viable KO (reroute/inert) where the gene is actually ESSENTIAL.
    ess = g.get("essential_ref")  # True / False / None(=not in the reference list)
    predicts_viable = ko_effect in ("none_inert", "none_flux_unconstrained", "unreliable_model_reroutes")
    predicts_lethal = ko_effect == "lethal_crash"
    if ess is None:
        benchmark = {"essential_reference": None, "agreement": "not_in_reference"}
    elif ess and predicts_viable:
        benchmark = {"essential_reference": True, "agreement": "model_UNDER_predicts",
                     "note": ("Benchmark: ESSENTIAL, but the model prior expects a viable KO (reroute/inert). The "
                              "model under-predicts essentiality here — the KO looks viable in silico yet is lethal "
                              "in vivo (fabI/glmS/gltA are exactly this case). Trust the benchmark, not the sim.")}
    elif ess and predicts_lethal:
        benchmark = {"essential_reference": True, "agreement": "consistent_lethal",
                     "note": "Benchmark: ESSENTIAL; the model prior expects a lethal crash — consistent."}
    elif (not ess) and predicts_viable:
        benchmark = {"essential_reference": False, "agreement": "consistent_viable",
                     "note": "Benchmark: non-essential; the model prior expects a viable KO — consistent."}
    elif (not ess) and predicts_lethal:
        benchmark = {"essential_reference": False, "agreement": "model_OVER_predicts",
                     "note": "Benchmark: non-essential, but the model prior expects a crash — over-predicts."}
    else:
        benchmark = {"essential_reference": bool(ess), "agreement": "unclear"}
    if "note" in benchmark:
        benchmark["source"] = "Baba 2006 (Keio) + Joyce 2006, glucose-minimal (wcEcoli validation set)"
    return {"symbol": symbol, "known": True, "mechanistic": mechanistic, "role": role,
            "is_machinery": machinery, "machinery_role": machinery_role,
            "is_sole_catalyst": sole, "is_kinetically_constraining": kinetic, "ko_effect_prior": ko_effect,
            "essential_reference": ess, "benchmark": benchmark,
            "ko_index": g["ko_index"], "n_tu": g["n_tu"], "note": note,
            "calibration": ("model KO priors vs the Baba/Joyce essentiality benchmark: the metabolic 'reroute' prior "
                            "UNDER-predicts for benchmark-essential enzymes (fabI/glmS/gltA are essential yet the "
                            "model KO is viable — the FBA objective has no growth term); the machinery prior expects "
                            "a lethal crash (consistent). Prior, not verdict — when `benchmark.agreement` says "
                            "under-predicts, trust the benchmark; for a measurable in-silico effect use a graded-"
                            "capacity perturbation.")}


def model_validation_summary() -> dict:
    """Corpus-level essentiality agreement of the model's KO prior vs the 402-gene ground-truth benchmark — so a
    KO 'viable' verdict can be trusted or not. Headline: how many benchmark-essential genes the model UNDER-predicts
    (calls viable). No sims — reads gene_scope. See CORPUS_OBSERVATIONS §K / AUDIT F3."""
    scope = _scope()
    if not scope:
        return {"error": "gene_scope cache missing — build it (gene_scope worker) first."}
    from collections import Counter
    counts: Counter = Counter()
    under = []
    for sym in scope:
        b = classify_gene(sym).get("benchmark") or {}
        ag = b.get("agreement", "unknown")
        counts[ag] += 1
        if ag == "model_UNDER_predicts" and len(under) < 25:
            under.append(sym)
    n_ref = sum(v for k, v in counts.items() if k != "not_in_reference")
    n_essential = counts["model_UNDER_predicts"] + counts["consistent_lethal"]
    return {
        "n_genes": len(scope), "n_in_benchmark": n_ref, "n_benchmark_essential": n_essential,
        "agreement_counts": dict(counts),
        "model_UNDER_predicts": counts["model_UNDER_predicts"],   # essential in vivo, model calls viable
        "consistent_lethal": counts["consistent_lethal"],          # essential in vivo, model predicts crash
        "model_OVER_predicts": counts["model_OVER_predicts"],      # non-essential, model predicts crash
        "essentiality_recall": (round(counts["consistent_lethal"] / n_essential, 3) if n_essential else None),
        "example_under_predicted": sorted(under),
        "interpretation": (
            "The model correctly flags only the machinery-essential genes (consistent_lethal); it UNDER-predicts "
            "the (mostly metabolic) essential genes as viable, because the homeostatic FBA has no growth term and "
            "reroutes. So a 'viable' KO verdict is UNRELIABLE for essential-gene candidates — defer to the "
            "benchmark. Recall = fraction of benchmark-essential genes the model calls lethal."),
    }
