"""PX-2: the capability registry's evidence in four states, none inferred from another.

  technical             the record names source symbols (markers) that the audit probes in the checkout
  development           the record is scored in the 216-question bank (`gate_eval_8framings.json`)
  external_stress       the record is scored in the frozen held-out set (`gate_eval_heldout.json`)
  simulation_confirmed  runs show the model doing what the record says it does instead (cited), or False

The fourth state is PRAXIS-VirtualCell's "scientific validation" adapted: a record describes the model, so runs can
confirm it, while agreement with the organism is a different question (Platform Map, Appendix L, BV-1).

    python evals/evidence_states.py   # writes evals/results/registry_evidence_states.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import capability as C  # noqa: E402

STATES = ("technical", "development", "external_stress", "simulation_confirmed")

SIMULATION_CONFIRMED = {
    "growth_under_phosphate_depletion": "Appendix B: 13 simulations; the phosphate pools never respond",
    "growth_without_a_carbon_source": "Appendix C: known-fault arm E2; biomass continues with no carbon uptake",
    "per_isoacceptor_trna_charging": "Section 13: steady-state runs write 86 charging columns with at most 21 distinct values",
    "response_to_the_glucose_concentration": "the three corpus doses (2, 5 and 20 mM) give the same cell",
    "knockout_of_a_multi_transcription_unit_gene": "murA knockout runs: expression 1.6 against 1.5 in wild type",
    "ppgpp_stringent_response": "the 12 kinetic rows: the GrowthLimits ppGpp and RelA columns read 0.0 throughout",
    "induction_by_a_fitted_transcription_factor": "Appendix J: in plus_nitrate against aerobic basal, narG +2.04 "
                                                  "log2 (q 0.002) and narH +1.57 (q 0.01), the fitted induction",
    # arabinose_induction_of_the_ara_operon is NOT here: the runs move araA, araB and araD the fitted way (8 to 10
    # copies against 34 to 35), but 2 runs against 17 do not reach FDR 0.10, and a direction is not a confirmation.
    "anaerobic_respiration_induction_magnitude": "anaerobic_response.json: 8 no_oxygen runs against 17 basal, frdA "
                                                 "+1.76 log2 (protein) where PRECISE-1K measures +3.21",
    "overflow_and_fermentation_products": "bv6_overflow.json: 37 aerobic glucose runs from 0.53 to 0.92 per hour "
                                          "excrete exactly 0 acetate; 8 no_oxygen runs excrete 0.0002 acetate per "
                                          "glucose",
    "elongation_rate_against_growth_rate": "bv7_elongation.json: across media the effective elongation rate rises as "
                                           "growth slows (acetate 18.7, anaerobic 20.1 against glucose 16.4 aa/s; "
                                           "75 runs, slope p 2e-5)",
    "central_carbon_flux_split": "bv11_fluxes.json: against Toya et al. 2010 on glucose, 2-oxoglutarate dehydrogenase "
                                 "0 against 4.62 mmol/gDCW/h, fumarase and malate dehydrogenase reversed (17 runs)",
    "replication_initiation_after_a_nutrient_shift": "well4cell rc2 index (same replication code as the corpus): "
                                                     "glucose-fitted cells moved into acetate mid-run divide at a "
                                                     "median 2,251 s (2,928 cells, 17% within 10 minutes) against "
                                                     "4,343 s for cells fitted to acetate (32); into no oxygen, "
                                                     "2,238 s (2,758) against 4,627 s (64)",
    # essentiality_of_a_metabolic_gene is NOT here yet: BV-3's whole-cell calls are the model's flux-balance prior
    # (the gene-scope cache), not runs. BV-12's knockouts of lysA, metF, serA and proC (essential in FEBA in all
    # three carbon sources) are the simulations that confirm or refute it.
}


def _bench(name: str) -> set[str]:
    recs = json.loads((REPO / "evals" / "results" / name).read_text(encoding="utf-8"))["records"]
    keys: set[str] = set()
    for r in recs:
        for k in (r.get("capability") or "").split(","):
            if k.strip():
                keys.add(k.strip())
    return keys


def states() -> dict:
    dev, ext = _bench("gate_eval_8framings.json"), _bench("gate_eval_heldout.json")
    return {c.key: {"technical": bool(c.markers), "development": c.key in dev, "external_stress": c.key in ext,
                    "simulation_confirmed": SIMULATION_CONFIRMED.get(c.key, False)}
            for c in C.CAPABILITIES}


def main() -> int:
    from cellarium import provenance
    s = states()
    out = {"spec": "PX-2", "states": list(STATES), "records": s,
           "counts": {st: sum(bool(v[st]) for v in s.values()) for st in STATES},
           "environment": provenance.code_environment()}
    (REPO / "evals" / "results" / "registry_evidence_states.json").write_text(json.dumps(out, indent=1) + "\n",
                                                                              encoding="utf-8")
    print(json.dumps(out["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
