"""BV-14: anaerobic nitrate respiration, against PRECISE-1K (Platform Map M.6).

The corpus has no anaerobic nitrate condition, so the claim July meant to test ("nitrate induces nar under
anaerobiosis") had never been run. The condition was added to the knowledge base (no_oxygen_plus_nitrate: NarL and
FNR active, ArcA active, 82-min doubling derived from PRECISE-1K) and refit locally (data/parca/fits.json, kb
9055ee3b). Its expression is BUILT from NarL's and FNR's fitted fold changes, so the nar response is calibrated by
construction; what is tested is how the model COMBINES two factors at one promoter against the organism, where
nitrate under anaerobiosis raises narGHJI 3.2 to 3.7 log2 and lowers frdA/frdB 4.5/4.9 log2 (anaerobic nitrate
against anaerobic glucose).

    python evals/bv14_nitrate.py plan     # writes evals/plans/bv14.json (and the BV-12 depth amendment)
    WCECOLI_DOCKER=<code image> python evals/bv14_nitrate.py score    # after the runs: writes bv14_nitrate.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
PLAN = REPO / "evals" / "plans" / "bv14.json"
AMEND = REPO / "evals" / "plans" / "bv12_amend1.json"
OUT = REPO / "evals" / "results" / "bv14_nitrate.json"

SIM_PATH = "bv14_no3_anaerobic"
INDEX = {"no_oxygen": 7, "no_oxygen_plus_nitrate": 24}      # read from the refit's ordered_conditions, 2026-11-25
# validity gates: the corpus fit's own runs (kb 3b2f8ebd), qc ok, growth_rate min and max widened 10%
GATES = {"bv14_basal": {"growth_rate": [1.86e-4, 3.06e-4]},      # 26 runs, 2.07e-4 to 2.78e-4
         "bv14_anaerobic": {"growth_rate": [1.13e-4, 1.80e-4]}}  # 8 runs, 1.26e-4 to 1.64e-4
# the organism: PRECISE-1K (Lamoureux et al. 2023), no3_anaero against wt_glc_anaero, RNA log2 (Map M.1)
MEASURED = {"narG": (3.2, 3.7), "narH": (3.2, 3.7), "narJ": (3.2, 3.7), "narI": (3.2, 3.7),
            "frdA": -4.48, "frdB": -4.87}


def _cond(name: str) -> dict:
    return {"perturbation": "condition", "condition": name, "params": {"variant_index": INDEX[name]}}


def plan() -> int:
    runs = [
        {"id": "bv14-ctl-basal", "design": {"perturbation": "wildtype", "condition": "basal"}, "seed": 100,
         "generations": 1, "group": "bv14_basal", "role": "control", "stage": 1},
        {"id": "bv14-ctl-anaerobic", "design": _cond("no_oxygen"), "seed": 100, "generations": 1,
         "group": "bv14_anaerobic", "role": "control", "stage": 1}]
    for name in ("no_oxygen", "no_oxygen_plus_nitrate"):
        runs += [{"id": f"bv14-{name}-s{s}", "design": _cond(name), "seed": s, "generations": 3,
                  "group": "bv14_anaerobic", "role": "run", "stage": 2} for s in range(4)]
    runs += [{"id": f"bv14-basal-s{s}", "design": {"perturbation": "wildtype", "condition": "basal"}, "seed": s,
              "generations": 3, "group": "bv14_basal", "role": "run", "stage": 2} for s in range(2)]
    p = {"batch": "bv14", "sim_path": SIM_PATH, "parallel": 6, "min_free_gb": 40, "priority": -1, "gates": GATES,
         "kb_sha256": "9055ee3b2b7b029edf99af6fd5c0bc435f19f47e3ce28e0f020d7cfb0e3e8ef6",
         "why_first": "the user asked for BV-12 to BV-14 to run on this machine; BV-14 is 12 runs, BV-12 126, so "
                      "BV-14 goes first and its result does not wait a day behind BV-12",
         "runs": runs}
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(p, indent=1) + "\n", encoding="utf-8")
    amend = {"batch": "bv12", "sim_path": "cellarium", "parallel": 6, "min_free_gb": 40, "priority": -1,
             "amends": "evals/plans/bv12.json (pre-registered, design_sha256 98bcdb94...)",
             "why": ("BV-12's glucose knockouts run 3 generations, and the corpus fit's wildtype/basal exists at "
                     "depths 1, 4 and 7 only. The survey reads a run's LAST generation, so a knockout at depth 3 "
                     "has no depth-matched reference (tests/test_generation_depth.py fails on the live corpus). "
                     "Two depth-3 wildtype/basal seeds are added; seeds 16 and 17 because 0 to 15 are taken at "
                     "other depths and a seed directory holds one depth. The panel, the knockouts and the "
                     "scoring are unchanged."),
             "runs": [{"id": f"wt-glucose-depth3-s{s}", "design": {"perturbation": "wildtype", "condition": "basal"},
                       "seed": s, "generations": 3, "group": "glucose", "role": "run", "stage": 1}
                      for s in (16, 17)]}
    AMEND.write_text(json.dumps(amend, indent=1) + "\n", encoding="utf-8")
    print(f"{PLAN.relative_to(REPO)}: {len(runs)} runs; {AMEND.relative_to(REPO)}: {len(amend['runs'])} runs")
    return 0


def main() -> int:
    if sys.argv[1:2] == ["plan"]:
        return plan()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
