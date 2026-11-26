"""BV-1: the gate against biology. For questions with a published measurement, does the gate's verdict match whether
the model's number would agree with the organism?

The gate is scored elsewhere on agreement with the registry, which says nothing about whether the registry is right.
Here each question carries a measurement of E. coli and the model's own number, read from stored runs, and lands in
one of four cells:

  answered, agrees            the gate admitted it and the model's number agrees with the organism
  answered, misleads          the gate admitted it and the number would mislead: a registry gap
  refused, would mislead      the gate stopped a question whose number would have misled: the gate's purpose
  refused, would have agreed  the gate stopped a question whose number happens to agree: the price of refusing

Verdicts are computed live by `gate.decide` on a hand-built requirement for each question (no language model), with
the corpus's elongation models as the ones holding runs. "Agrees" means the sign agrees and the size is within the
stated band; a calibrated agreement (the fit was given the answer) is marked as such and is not a prediction.

    python evals/bv1_gate_vs_biology.py    # writes evals/results/bv1_gate_vs_biology.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import capability as C  # noqa: E402
from cellarium import gate  # noqa: E402

OUT = REPO / "evals" / "results" / "bv1_gate_vs_biology.json"
RESULTS = REPO / "evals" / "results"


def _load(name):
    f = RESULTS / name
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def _model_numbers() -> dict:
    """The model's side of each question, from stored artefacts only (no run is read here)."""
    reg = _load("regulation_scope.json") or {}
    ess = _load("bv3_essentiality.json") or {}
    ana = _load("anaerobic_response.json") or {}
    ovf = _load("bv6_overflow.json") or {}
    elo = _load("bv7_elongation.json") or {}
    eff = {(e.get("design"), e.get("channel")): e for sec in ("ppgpp_clamps", "rrna_dosage", "carbon_sources")
           for e in reg.get(sec, [])}
    nar = next((r for r in reg.get("gene_level", []) if r.get("regulon") == "nar_nitrate"
                and r.get("reference") == "wildtype/basal"), {})
    clamp = [e for e in reg.get("ppgpp_clamps", []) if e.get("channel") == "growth_rate"]
    dose = [e for e in reg.get("rrna_dosage", []) if e.get("channel") == "growth_rate"]
    carbon = reg.get("carbon_sources", [])
    wc = (ess.get("on_iml1515_metabolic_genes") or {}).get("whole_cell_prior") or {}
    ana_genes = (ana.get("no_oxygen_vs_basal_protein") or {})
    return {
        "growth_law": reg.get("ribosome_growth_law", {}),
        "ppgpp_growth_effects_pct": [e.get("effect_pct") for e in clamp],
        "rrna_growth_effects_pct": [e.get("effect_pct") for e in dose],
        "carbon_growth_effects_pct": [e.get("effect_pct") for e in carbon],
        "whole_cell_metabolic_essentiality": {k: wc.get(k) for k in ("tp", "fn", "recall")},
        "nar_aerobic_nitrate_vs_basal": {g: v.get("log2fc") for g, v in (nar.get("regulon_levels") or {}).items()},
        "anaerobic_vs_basal": ana_genes,
        "overflow": {"aerobic_glucose_acetate_excretion": (ovf.get("fixed_medium_fit_acetate_vs_growth") or {})
                     .get("constant_response"),
                     "aerobic_glucose_runs": (ovf.get("fixed_medium_fit_acetate_vs_growth") or {}).get("n"),
                     "growth_range_per_h": [min((d.get("growth_per_h") for d in (ovf.get("designs") or {}).values()
                                                 if d.get("growth_per_h") is not None), default=None),
                                            max((d.get("growth_per_h") for d in (ovf.get("designs") or {}).values()
                                                 if d.get("growth_per_h") is not None), default=None)]}
        if ovf else None,
        "elongation": ({d: (v.get("growth_per_h"), v.get("elongation_aa_per_s"))
                        for d, v in (elo.get("designs") or {}).items()
                        if d in ("wildtype/basal", "condition/acetate", "condition/succinate", "condition/no_oxygen")}
                       if elo else None),
        "_eff": {f"{k[0]}|{k[1]}": v.get("effect_pct") for k, v in eff.items()},
    }


# (id, question, requirement, biology, model-side reader, judgement of agreement)
QUESTIONS = [
    {"id": "isoacceptor_charging_under_starvation",
     "question": "Under leucine starvation, are the leucine tRNA isoacceptors charged to different extents?",
     "requirement": {"observable": "trna_charging", "granularity": "per_isoacceptor",
                     "regulatory_dependencies": ["amino_acid_starvation"]},
     "biology": {"finding": "selective charging: during starvation some isoacceptors of the starved family stay "
                            "charged and others fall", "source": "Dittmar et al. 2005", "doi": "10.1038/sj.embor.7400341"},
     "model": "the default model writes one value per amino-acid family to every isoacceptor (at most 21 distinct "
              "values across 86 columns), so the within-family spread is exactly zero; the kinetic model resolves "
              "isoacceptors but has no ppGpp (Platform Map section 13)",
     "agreement": "misleads"},
    {"id": "pho_regulon_under_phosphate_limitation",
     "question": "Does phosphate limitation switch on the Pho regulon (pstSCAB, phoA)?",
     "requirement": {"observable": "other", "granularity": "per_gene",
                     "regulatory_dependencies": ["phosphate_depletion"]},
     "biology": {"finding": "Pi limitation activates PhoR/PhoB and induces the Pho regulon",
                 "source": "Hsieh and Wanner 2010", "doi": "10.1016/j.mib.2010.01.014"},
     "model": "removing phosphate leaves the phosphate pools unchanged, PhoB is never phosphorylated and is not a "
              "fitted factor, so no Pho gene moves (Appendix B, 13 simulations)",
     "agreement": "misleads"},
    {"id": "growth_after_carbon_removal",
     "question": "Does the cell keep growing after glucose, its only carbon source, is removed?",
     "requirement": {"observable": "other", "granularity": "aggregate",
                     "regulatory_dependencies": ["carbon_source_removal"]},
     "biology": {"finding": "no: biomass cannot be made without a carbon source", "source": "mass conservation",
                 "doi": None},
     "model": "biomass keeps rising 3.6-fold with almost no carbon taken up; carbon is not conserved (Appendix C)",
     "agreement": "misleads"},
    {"id": "growth_across_saturating_glucose_doses",
     "question": "Does growth rate differ between 2, 5 and 20 mM glucose?",
     "requirement": {"observable": "other", "granularity": "aggregate",
                     "regulatory_dependencies": ["carbon_source_concentration"]},
     "biology": {"finding": "no: the half-saturation constant for glucose is 40 to 88 micrograms per litre (about "
                            "0.2 to 0.5 micromolar), so all three doses saturate growth",
                 "source": "Senn et al. 1994", "doi": "10.1016/0304-4165(94)90072-8"},
     "model": "the three doses give the same cell: uptake is a binary switch above 1e-5 mM (registry record W4C-1)",
     "agreement": "agrees"},
    {"id": "ribosome_growth_law",
     "question": "Across perturbations, does ribosome content rise with growth rate?",
     "requirement": {"observable": "rrna_transcription", "granularity": "aggregate", "regulatory_dependencies": []},
     "biology": {"finding": "yes: the ribosomal fraction rises linearly with growth rate across nutrient conditions",
                 "source": "Scott et al. 2010", "doi": "10.1126/science.1192588"},
     "model_key": "growth_law",
     "agreement": "agrees"},
    {"id": "ppgpp_optimum",
     "question": "Is growth slower when ppGpp is held both below and above its normal level?",
     "requirement": {"observable": "ppgpp", "granularity": "aggregate", "regulatory_dependencies": []},
     "biology": {"finding": "yes: raising and lowering (p)ppGpp both suppress growth",
                 "source": "Zhu and Dai 2019", "doi": "10.1093/nar/gkz211"},
     "model_key": "ppgpp_growth_effects_pct",
     "agreement": "agrees"},
    {"id": "rrna_operon_dosage",
     "question": "Does losing rRNA operons slow growth?",
     "requirement": {"observable": "rrna_transcription", "granularity": "aggregate", "regulatory_dependencies": []},
     "biology": {"finding": "yes, moderately, once at least two operons are deleted; one operon makes as much as "
                            "56% of wild-type rRNA", "source": "Asai et al. 1999",
                 "doi": "10.1128/JB.181.12.3803-3809.1999"},
     "model_key": "rrna_growth_effects_pct",
     "agreement": "agrees"},
    {"id": "carbon_source_growth",
     "question": "Does E. coli grow more slowly on acetate than on glucose?",
     "requirement": {"observable": "media_response", "granularity": "aggregate", "regulatory_dependencies": []},
     "biology": {"finding": "yes: 0.257 against 0.649 per hour in PRECISE-1K's matched samples, 60% slower",
                 "source": "Lamoureux et al. 2023 (PRECISE-1K)", "doi": "10.1093/nar/gkad750"},
     "model_key": "carbon_growth_effects_pct",
     "agreement": "agrees, calibrated: the fit is given each condition's doubling time; the model's slowdown is "
                  "33%, about half the measured 60%"},
    {"id": "metabolic_gene_essentiality",
     "question": "Which metabolic genes are essential?",
     # BV-G2 (2026-11-25): the parser now attaches metabolic_gene_essentiality to this question (gate.py)
     "requirement": {"observable": "gene_knockout", "granularity": "per_gene",
                     "regulatory_dependencies": ["metabolic_gene_essentiality"]},
     "biology": {"finding": "214 of 1,357 iML1515 metabolic genes are essential by the Keio collection",
                 "source": "Baba et al. 2006", "doi": "10.1038/msb4100050"},
     "model_key": "whole_cell_metabolic_essentiality",
     "agreement": "misleads"},
    {"id": "arabinose_induction",
     "question": "Does arabinose switch on araBAD?",
     "requirement": {"observable": "other", "granularity": "per_gene",
                     "regulatory_dependencies": ["arabinose_induction"]},
     "biology": {"finding": "yes: AraC activates araBAD when arabinose binds it", "source": "Schleif 2010",
                 "doi": "10.1111/j.1574-6976.2010.00226.x"},
     "model": "AraC is fitted to repress araA, araB and araD (-0.70, -0.64, -0.35 log2) in a medium that keeps "
              "glucose; the runs move them down (8 to 10 copies against 34 to 35), not significantly",
     "agreement": "misleads"},
    {"id": "nitrate_induction_aerobic",
     "question": "Does nitrate raise narGHJI in aerobic glucose medium?",
     "requirement": {"observable": "other", "granularity": "per_gene", "regulatory_dependencies": ["inducer_response"]},
     "biology": {"finding": "yes, from a low aerobic baseline: NarL stimulates nar transcription aerobically and "
                            "anaerobically, without FNR; under anaerobiosis nitrate raises narGHJI 3.2 to 3.7 log2",
                 "source": "Walker and DeMoss 1992; PRECISE-1K no3_anaero vs wt_glc_anaero",
                 "doi": "10.1128/jb.174.4.1119-1123.1992"},
     "model_key": "nar_aerobic_nitrate_vs_basal",
     # the fold changes the fit uses (fold_changes_nca.tsv replacing fold_changes.tsv's +2.57 to +2.80; 2026-11-26)
     "agreement": "agrees, calibrated: NarL's fold changes are fitted (+0.58 to +1.75); the aerobic magnitude has no "
                  "measurement here"},
    {"id": "anaerobic_induction_nar_frd",
     "question": "Does removing oxygen switch on narGHJI and frdABCD?",
     # BV-AN (2026-11-25): "switch on" asks how strongly; the parser now attaches anaerobic_respiration (gate.py)
     "requirement": {"observable": "other", "granularity": "per_gene",
                     "regulatory_dependencies": ["anaerobic_respiration"]},
     "biology": {"finding": "yes: narG +3.98 and frdA +3.21 log2 anaerobic against aerobic glucose (PRECISE-1K); "
                            "the nar transcript is repressed aerobically and induced anaerobically through FNR",
                 "source": "Lamoureux et al. 2023 (PRECISE-1K); Li and DeMoss 1987",
                 "doi": "10.1093/nar/gkad750"},
     "model_key": "anaerobic_vs_basal",
     "agreement": None},                 # judged from the stored numbers below
    # BV-OF (2026-11-25): BV-6 found the model excretes no acetate at any growth rate; added with the record that
    # now refuses it, so the record's effect is measured here like BV-G2's and BV-AN's
    {"id": "acetate_overflow_on_glucose", "added_after": "BV-6",
     "question": "Does E. coli excrete acetate when it grows on glucose with oxygen, and more so the faster it grows?",
     "requirement": {"observable": "media_response", "granularity": "aggregate",
                     "regulatory_dependencies": ["overflow_metabolism"]},
     "biology": {"finding": "yes: aerobic acetate excretion on glucose rises with growth rate above a threshold "
                            "(overflow metabolism)",
                 "source": "Basan et al. 2015", "doi": "10.1038/nature15765"},
     "model_key": "overflow",
     "agreement": "misleads: the model excretes exactly 0 acetate in all 37 aerobic glucose runs from 0.53 to 0.92 "
                  "per hour (BV-6), so no reading shows overflow or its rise with growth"},
    # BV-EL (2026-11-25): BV-7 found the elongation rate rising as growth slows across media
    {"id": "elongation_rate_falls_with_growth", "added_after": "BV-7",
     "question": "Does the translation elongation rate fall as growth slows on poorer carbon sources?",
     "requirement": {"observable": "elongation", "granularity": "aggregate",
                     "regulatory_dependencies": ["elongation_growth_dependence"]},
     "biology": {"finding": "yes: the elongation rate decreases as growth slows, though an appreciable rate is "
                            "maintained towards zero growth",
                 "source": "Dai et al. 2016", "doi": "10.1038/nmicrobiol.2016.231"},
     "model_key": "elongation",
     "agreement": "misleads: across media the model's elongation rate rises as growth slows (acetate 18.7, "
                  "succinate 18.3, anaerobic 20.1 against glucose 16.4 aa/s; BV-7)"},
]


def _verdict(req: dict) -> str:
    saved = gate.modes_with_runs
    gate.modes_with_runs = lambda: tuple(C.MODES_IN_CORPUS)
    try:
        r = gate.Requirement(observable=req["observable"], granularity=req["granularity"],
                             regulatory_dependencies=tuple(req["regulatory_dependencies"]))
        d = gate.decide(r, mode=C.DEFAULT_MODE)
        return d.verdict + (" (calibrated)" if any(n.startswith("calibrated") for n in d.notes) else "") + (
            " (no record covers it)" if any("no declared capability" in n for n in d.notes) else "")
    finally:
        gate.modes_with_runs = saved


def _anaerobic_judgement(numbers: dict) -> str | None:
    a = numbers.get("anaerobic_vs_basal") or {}
    nar, frd = a.get("narG"), a.get("frdA")
    if nar is None or frd is None:
        return None
    if frd < 2.0 or nar < 2.0:
        # FNR's numbers are the ones the fit uses (fold_changes_nca.tsv replacing fold_changes.tsv; corrected
        # 2026-11-26, D15: this line said +0.8 to +1.5 and "frdA has no FNR entry")
        return (f"misleads: the model raises narG {nar:+.2f} and frdA {frd:+.2f} log2 against measured +3.98 and "
                "+3.21, so a sixteen-fold induction of nitrate reductase reads as under two-fold in protein (about "
                "fourfold in transcription); the fold changes the fit uses for FNR (+0.52 to +0.80 at nar, +0.68 "
                "to +1.43 at frd) are far below the measured induction")
    return f"agrees: narG {nar:+.2f}, frdA {frd:+.2f} against +3.98, +3.21"


def cell(verdict: str, agreement: str | None) -> str:
    answered = verdict.startswith("answer")
    if agreement is None:
        return "unjudged"
    agrees = agreement.startswith("agrees")
    return ("answered, agrees" if answered and agrees else "answered, misleads" if answered else
            "refused, would have agreed" if agrees else "refused, would mislead")


def main() -> int:
    from cellarium import provenance
    numbers = _model_numbers()
    rows = []
    for q in QUESTIONS:
        v = _verdict(q["requirement"])
        agreement = q["agreement"] if q["id"] != "anaerobic_induction_nar_frd" else _anaerobic_judgement(numbers)
        model = q.get("model") or numbers.get(q.get("model_key"))
        rows.append({"id": q["id"], "question": q["question"], "requirement": q["requirement"], "verdict": v,
                     "biology": q["biology"], "model": model, "agreement": agreement,
                     "cell": cell(v, agreement), **({"added_after": q["added_after"]} if q.get("added_after") else {})})
    tally, tally_pre = {}, {}
    for r in rows:
        tally[r["cell"]] = tally.get(r["cell"], 0) + 1
        if not r.get("added_after"):
            tally_pre[r["cell"]] = tally_pre.get(r["cell"], 0) + 1
    out = {"spec": "BV-1", "rows": rows, "tally": tally,
           # the test is the twelve questions chosen before any result; questions added after a test found a failure
           # check only that the record built from that failure is wired, so they are counted apart
           "tally_original_twelve": tally_pre,
           "first_run_original_twelve": {"refused, would mislead": 4, "refused, would have agreed": 1,
                                         "answered, agrees": 5, "answered, misleads": 2},
           "reading_of_the_added": ("questions written after BV-6 and BV-7 found the failure; the record that refuses "
                                    "them was built from the same finding, so they are a wiring check, not a test "
                                    "of the gate's judgment"),
           "reading": "refused-would-mislead is the gate working; answered-misleads is a registry gap; "
                      "refused-would-have-agreed is what refusing costs",
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(tally))
    for r in rows:
        print(f"  {r['cell']:28s} {r['verdict']:34s} {r['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
