"""Launch a first in-envelope campaign to seed the corpus (runs the public model; see docs/GENERATE.md).

Requires the model env (WCECOLI_DOCKER or WCECOLI_DIR). Every design here is inside the validated envelope.
Gene-KO panels need per-gene variant indices from the model's sim_data — derive them once with
`python -m cellarium.reader --variant-map`, then `--knockout <rna_id query>`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import manifest
from .model import Design

VARIANT_MAP_CACHE = Path("data/cache/variant_map.json")


def default_designs() -> list[Design]:
    """A small in-envelope trio: two nutrient steady states + one validated transient."""
    return [
        Design(perturbation="wildtype", condition="basal"),                    # minimal-glucose steady state
        Design(perturbation="condition", condition="with_aa",                  # rich (minimal+AA) steady state
               params={"variant_index": 4}),                                   # ordered_conditions[4]=with_aa (verified)
        Design(perturbation="timeline",                                        # AA downshift -> stringent response
               timeline="0 minimal_plus_amino_acids, 1200 minimal"),
    ]


def panel_designs() -> list[Design]:
    """A literature-grounded in-envelope panel extending the default trio with genuinely new science:

    - Carbon/oxygen condition sweep (static, fitted): a glucose-limitation gradient + poor carbon sources +
      anaerobic — the nutrient-growth law across substrate quality (Monod; Schaechter growth law).
    - ppGpp causal titration on minimal media (ppgpp_conc variant clamps [ppGpp] and disables its dynamics):
      turns the ppGpp<->growth *correlation* we saw into a *causal* dose-response (stringent-response biology).
    - AA up-shift (relaxation): the complement of the downshift already in the corpus.
    - rRNA-operon knockout series (1..6 of 7 operons): ribosome-synthesis-capacity limitation of growth.

    All indices verified against the model's own variant_map. basal(0)/with_aa(4)/downshift already in corpus.
    """
    conditions = {1: "glc_20mM", 2: "glc_5mM", 3: "glc_2mM", 5: "acetate", 6: "succinate", 7: "no_oxygen"}
    ppgpp = {0: "0.2x", 2: "0.6x", 7: "1.6x", 9: "2.0x"}   # ppgpp_conc on basal (idx//10==0); 4=control skipped
    rrna = {2: "2op", 4: "4op", 6: "6op"}                   # rrna_operon_knockout: KO n operons in minimal
    designs = [Design(perturbation="condition", condition=lbl, params={"variant_index": i})
               for i, lbl in conditions.items()]
    designs += [Design(perturbation="ppgpp_conc", condition=f"basal|ppGpp:{lbl}", params={"variant_index": i})
                for i, lbl in ppgpp.items()]
    designs.append(Design(perturbation="timeline", timeline="0 minimal, 1200 minimal_plus_amino_acids"))  # up-shift
    designs += [Design(perturbation="rrna_operon_knockout", condition=f"minimal|rRNA_KO:{lbl}",
                       params={"variant_index": i}) for i, lbl in rrna.items()]
    return designs


def essential_ko_designs() -> list[Design]:
    """KNOWN-TO-REROUTE control set (RESOLVED — §J/§K): three Keio/Joyce-ESSENTIAL sole-catalyst metabolic KOs
    (fabI 425, glmS 2795, gltA 2657) + a basal control, run 4 generations. The original prediction (progressive
    growth decline -> arrest) was DISPROVEN: all three are VIABLE at division_rate 1.00 — the metabolism FBA has
    no growth term, so it reroutes, and the enzyme is 0 from gen-0 (no dilution confound). Kept as the canonical
    `model_UNDER_predicts` demonstration (benchmark-essential yet viable in silico). For a real phenotype use a
    GRADED perturbation (rrna_operon_knockout, ppgpp_conc, objective_weight_designs), NOT a single metabolic KO."""
    kos = {"fabI": 425, "glmS": 2795, "gltA": 2657}
    return [Design(perturbation="wildtype", condition="basal")] + \
           [Design(perturbation="gene_knockout", condition=f"KO:{s}", params={"variant_index": i})
            for s, i in kos.items()]


def mechanistic_ko_designs() -> list[Design]:
    """Mechanistic-scope contrast (RESOLVED — §J/§K): metabolic KOs (pfkA 1594, tpiA 1542) vs non-mechanistic
    (flgB 2791, ymgD 397). Established result: BOTH classes are VIABLE — the metabolic KOs reroute (no growth
    term to degrade), the inert ones do nothing by construction. So a single metabolic KO is not a phenotype
    generator here; it's a known-to-reroute control. For a measurable effect use a graded-capacity perturbation."""
    kos = {"pfkA": 1594, "tpiA": 1542, "flgB": 2791, "ymgD": 397}
    return [Design(perturbation="gene_knockout", condition=f"KO:{sym}", params={"variant_index": idx})
            for sym, idx in kos.items()]


def power_designs() -> list[Design]:
    """High-replicate set to test two literature-first hypotheses and power the existing results.
    H1 (expect PASS): O2 limitation reproduces the FNR/ArcA anaerobic regulon (no_oxygen).
    H2 (expect FAIL): Mg limitation reduces ribosomal proteome fraction + growth (Pontes 2016) — likely absent.
    Plus basal/with_aa/acetate to power the growth law (ribosomal fraction vs growth) and top_movers reproducibility.
    Run with --seeds 8."""
    return [
        Design(perturbation="wildtype", condition="basal"),
        Design(perturbation="condition", condition="with_aa", params={"variant_index": 4}),
        Design(perturbation="condition", condition="acetate", params={"variant_index": 5}),
        Design(perturbation="condition", condition="no_oxygen", params={"variant_index": 7}),
        Design(perturbation="condition", condition="minus_magnesium", params={"variant_index": 11}),
    ]


def stress_designs() -> list[Design]:
    """Nutrient / ion / electron-acceptor stress — hypotheses distinct from the ppGpp + carbon/O2 panels.
    Each engages a different pathway: phosphate starvation (pho regulon), Mg limitation (translation/ribosome),
    nitrate respiration (electron-transport rewiring), arabinose (alt sugar), indole (signalling/persistence).
    Indices verified against variant_map; all are static, in-envelope conditions."""
    conditions = {12: "minus_phosphate", 11: "minus_magnesium", 17: "plus_nitrate",
                  14: "plus_arabinose", 16: "plus_indole"}
    return [Design(perturbation="condition", condition=lbl, params={"variant_index": i})
            for i, lbl in conditions.items()]


def confounded_designs() -> list[Design]:
    """The three panel arms that were confounded at 1 generation — they are steady-state effects the inherited
    parent state masks in gen 0. Re-run these with --generations 4 to let them reach steady state: the ppGpp
    clamp (does the low-side Zhu downturn emerge once metabolic proteins dilute?), the rRNA-operon KO series,
    and the AA up-shift (later generations sit in the post-shift media)."""
    ppgpp = {0: "0.2x", 2: "0.6x", 7: "1.6x", 9: "2.0x"}
    rrna = {2: "2op", 4: "4op", 6: "6op"}
    designs = [Design(perturbation="ppgpp_conc", condition=f"basal|ppGpp:{lbl}", params={"variant_index": i})
               for i, lbl in ppgpp.items()]
    designs += [Design(perturbation="rrna_operon_knockout", condition=f"minimal|rRNA_KO:{lbl}",
                       params={"variant_index": i}) for i, lbl in rrna.items()]
    designs.append(Design(perturbation="timeline", timeline="0 minimal, 1200 minimal_plus_amino_acids"))
    return designs


def overnight_designs() -> list[Design]:
    """Overnight batch Arms A + C (run --generations 4). ARM A = essentiality landscape + the redundancy test:
    does the model CRASH on Keio-NON-essential machinery (rpmE/rpmJ/lysS/selA — resolves keep-caveat vs detect-
    redundancy) as it does on essential machinery? Plus under-predicted metabolic essentials (murA/lpxC/dapA) to
    confirm the reroute. ARM C = graded phenotypes (objective-weight + ppGpp + rRNA sweeps) — the clean-signal
    path. Arm B (gen-depth, 8 gens) is a separate --gendepth run. All indices vetted via design_space."""
    armA = {"rpmE": 1943, "rpmJ": 2829, "lysS": 2819, "selA": 2840,   # redundant machinery (Keio non-essential)
            "murA": 1027, "lpxC": 84, "dapA": 2776}                    # under-predicted metabolic essentials
    designs = [Design(perturbation="wildtype", condition="basal")]
    designs += [Design(perturbation="gene_knockout", condition=f"KO:{s}", params={"variant_index": i})
                for s, i in armA.items()]
    designs += objective_weight_designs()                              # Arm C: objective levers
    ppgpp = {0: "0.2x", 2: "0.6x", 7: "1.6x", 9: "2.0x"}
    rrna = {2: "2op", 4: "4op", 6: "6op"}
    designs += [Design(perturbation="ppgpp_conc", condition=f"basal|ppGpp:{l}", params={"variant_index": i})
                for i, l in ppgpp.items()]
    designs += [Design(perturbation="rrna_operon_knockout", condition=f"minimal|rRNA_KO:{l}", params={"variant_index": i})
                for i, l in rrna.items()]
    return designs


def gendepth_designs() -> list[Design]:
    """Overnight Arm B (run --generations 8): confirm the RNAP/replisome LATE crash (rpoB/dnaN survive <=4 gens,
    predicted to crash as the inherited pool depletes) AND resolve minus_phosphate div=0.0 (real starvation-arrest
    vs a 4-gen time-budget artifact). Small + long — run separately from the 4-gen Arms A+C."""
    return [Design(perturbation="wildtype", condition="basal"),
            Design(perturbation="gene_knockout", condition="KO:rpoB", params={"variant_index": 2095}),
            Design(perturbation="gene_knockout", condition="KO:dnaN", params={"variant_index": 58}),
            Design(perturbation="condition", condition="minus_phosphate", params={"variant_index": 12})]


def multi_gene_ko_designs(gene_sets: list[list[str]]) -> list[Design]:
    """Multi-gene KO designs (the `multi_gene_knockout` variant) — knock out a SET of genes at once. Motivation
    (not the ML surrogate): metabolism REROUTES around single KOs because it has alternative flux paths, so a
    single-KO null is uninformative. A set that removes the enzyme AND its alternatives can BLOCK the reroute and
    expose the true dependency — the council can suggest reroute-minimizing sets. Each set resolves to ko_indices
    via gene_scope. Runs one lineage per set (the variant uses index 0; run_one gives each set a unique dir)."""
    from . import scope
    designs = []
    for genes in gene_sets:
        idxs, labels = [], []
        for g in genes:
            c = scope.classify_gene(g)
            if c.get("ko_index"):
                idxs.append(int(c["ko_index"])); labels.append(g)
        if len(idxs) >= 2:
            designs.append(Design(perturbation="multi_gene_knockout", condition="KO:" + "+".join(labels),
                                  params={"ko_indices": idxs}))
    return designs


def machinery_calibration_designs() -> list[Design]:
    """M1 viability-threshold calibration (DRAFT — vet before launching). A machinery-KO battery spanning all four
    central-dogma subtypes, to populate the INVIABLE/impaired end of the viability scale. Rationale: every existing
    metabolic KO + graded run (rRNA-operon 2/4/6, ppGpp 0.2-2.0x) is VIABLE (min_divrate 1.0 — they slow growth,
    not division), so we have ZERO clean inviable points besides gltX (impaired, 0.667). Only machinery reaches the
    crash end. This validates scope.py's machinery->lethal_crash rule on n=7 (was n=1: gltX) and tests whether the
    aaRS crash generalizes across synthetases (argS = the Choi & Covert 2023 ArgRS case).
      rpoB 2095 (RNAP; = rpoBC operon)   rplB 2835 (ribosomal; = S10 r-protein operon)   dnaN 58 (replisome)
      argS 644 / alaS 2078 / pheS 1340   (three aminoacyl-tRNA synthetases)
    NOTE: ko_index is a TU index, so rpoB/rplB KOs remove the whole operon (documented, fine for a crash test).
    Expect CRASHES (partial lineages) — the runner/batch must tolerate a failing variant. Run --generations 4."""
    kos = {"rpoB": 2095, "rplB": 2835, "argS": 644, "alaS": 2078, "pheS": 1340, "dnaN": 58}
    return [Design(perturbation="wildtype", condition="basal")] + \
           [Design(perturbation="gene_knockout", condition=f"KO:{s}", params={"variant_index": i})
            for s, i in kos.items()]


def objective_weight_designs() -> list[Design]:
    """The LEGITIMATE objective levers (§K): sweep the metabolism FBA's kinetic-objective weight and secretion
    penalty — GRADED metabolic-behaviour perturbations the wcEcoli team ships analyses for, and the only sanctioned
    way to touch the objective (changing its TYPE to biomass-max would break the whole-cell coupling; see D4).
    weight=0 is pure homeostatic (no kinetic targets); larger binds the kinetic targets harder. Unlike a single
    metabolic KO (reroutes -> viable), these tune the network's behaviour continuously. Indices index the model's
    own arrays: KINETIC_OBJECTIVE_WEIGHT=[0,1e-8..1], SECRETION_PENALTY=[0,1e-5..0.05]."""
    kw = {0: "0", 5: "1e-4", 8: "0.1", 9: "1"}
    sp = {0: "0", 4: "1e-3", 7: "0.01", 9: "0.05"}
    designs = [Design(perturbation="metabolism_kinetic_objective_weight", condition=f"minimal|kin_w:{lbl}",
                      params={"variant_index": i}) for i, lbl in kw.items()]
    designs += [Design(perturbation="metabolism_secretion_penalty", condition=f"minimal|sec_pen:{lbl}",
                       params={"variant_index": i}) for i, lbl in sp.items()]
    return designs


def knockout_designs(query: str, limit: int = 8) -> list[Design]:
    """Gene-knockout designs whose rna_id matches `query`, using the cached variant map
    (run `python -m cellarium.reader --variant-map` first). Each -> --variant gene_knockout <idx>."""
    if not VARIANT_MAP_CACHE.exists():
        raise RuntimeError("run `python -m cellarium.reader --variant-map` first to derive gene indices")
    genes = json.loads(VARIANT_MAP_CACHE.read_text(encoding="utf-8")).get("genes", [])
    hits = [g for g in genes if query.lower() in g["rna_id"].lower()][:limit]
    if not hits:
        raise RuntimeError(f"no gene rna_id matched '{query}' in the variant map")
    return [Design(perturbation="gene_knockout", condition=f"KO:{g['rna_id']}",
                   params={"variant_index": g["ko_index"]}) for g in hits]


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed the Cellarium corpus with an in-envelope campaign.")
    ap.add_argument("--seeds", type=int, default=4, help="number of stochastic replicate seeds")
    ap.add_argument("--generations", type=int, default=1)
    ap.add_argument("--parallel", type=int, default=1,
                    help="run this many sims concurrently (each loads ~1GB sim_data — size to host RAM)")
    ap.add_argument("--knockout", default=None,
                    help="run a gene-KO panel matching this rna_id query instead of the default trio "
                         "(needs the cached variant map)")
    ap.add_argument("--panel", action="store_true",
                    help="run the extended literature-grounded panel (carbon/O2 sweep, ppGpp titration, "
                         "AA up-shift, rRNA-operon KO) instead of the default trio")
    ap.add_argument("--confounded", action="store_true",
                    help="re-run the arms that need multiple generations (ppGpp clamp, rRNA KO, up-shift); "
                         "pair with --generations 4")
    ap.add_argument("--stress", action="store_true",
                    help="run the nutrient/ion/electron-acceptor stress panel (distinct from ppGpp/carbon)")
    ap.add_argument("--power", action="store_true",
                    help="high-replicate set (basal, with_aa, acetate, no_oxygen, minus_magnesium) to test H1/H2 "
                         "and power the growth law; run with --seeds 8")
    ap.add_argument("--mechanistic-ko", action="store_true", dest="mechanistic_ko",
                    help="single-gene KO experiment: mechanistic (pfkA, tpiA) vs non-mechanistic (flgB, ymgD)")
    ap.add_argument("--essential-ko", action="store_true", dest="essential_ko",
                    help="essential sole-catalyst KOs (fabI, glmS, gltA) + basal control; KNOWN-TO-REROUTE control")
    ap.add_argument("--objective-weight", action="store_true", dest="objective_weight",
                    help="graded objective levers: kinetic-objective-weight + secretion-penalty sweeps (§K/D4)")
    ap.add_argument("--machinery-calibration", action="store_true", dest="machinery_calibration",
                    help="M1: machinery-KO battery (RNAP/ribosomal/aaRS/replisome) to calibrate viability thresholds")
    ap.add_argument("--overnight", action="store_true",
                    help="overnight batch Arms A+C (essentiality landscape + redundancy test + graded); run --generations 4")
    ap.add_argument("--gendepth", action="store_true",
                    help="overnight Arm B: rpoB/dnaN late-crash + minus_phosphate arrest; run --generations 8")
    ap.add_argument("--multi-gene-ko", dest="multi_gene_ko", default=None,
                    help="multi-gene KO sets, genes '+'-joined within a set and ';'-separated across sets "
                         "(default: pfkA+pfkB). Run with --parallel 1.")
    args = ap.parse_args()

    if args.panel:
        designs = panel_designs()
    elif args.overnight:
        designs = overnight_designs()
    elif args.gendepth:
        designs = gendepth_designs()
    elif args.multi_gene_ko is not None:
        spec = args.multi_gene_ko or "pfkA+pfkB"
        designs = multi_gene_ko_designs([s.split("+") for s in spec.split(";") if s])
    elif args.machinery_calibration:
        designs = machinery_calibration_designs()
    elif args.objective_weight:
        designs = objective_weight_designs()
    elif args.essential_ko:
        designs = essential_ko_designs()
    elif args.mechanistic_ko:
        designs = mechanistic_ko_designs()
    elif args.power:
        designs = power_designs()
    elif args.stress:
        designs = stress_designs()
    elif args.confounded:
        designs = confounded_designs()
    elif args.knockout:
        designs = knockout_designs(args.knockout)
    else:
        designs = default_designs()
    shard = manifest.campaign(designs, list(range(args.seeds)), args.generations, args.parallel)
    print(f"Wrote manifest shard: {shard}")


if __name__ == "__main__":
    main()
