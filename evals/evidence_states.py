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
