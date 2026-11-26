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
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
PLAN = REPO / "evals" / "plans" / "bv14.json"
AMEND = REPO / "evals" / "plans" / "bv12_amend1.json"
OUT = REPO / "evals" / "results" / "bv14_nitrate.json"

SIM_PATH = "bv14_no3_anaerobic"
INDEX = {"no_oxygen": 7, "no_oxygen_plus_nitrate": 24}      # read from the refit's ordered_conditions, 2026-11-25
# Validity gates, AMENDED 2026-11-26 after the first evaluation (recorded in the plan and the ledger). The first gates
# were the corpus fit's own runs (kb 3b2f8ebd, min and max widened 10%: basal [1.86e-4, 3.06e-4], anaerobic
# [1.13e-4, 1.80e-4]); the anaerobic control grew at 1.07e-4/s and closed its group. That reference was the wrong model:
# a fresh ParCa from the current tree is not the corpus fit (docs/KB_DIVERGENCE.md: amino-acid kinetics moved up to
# 52%), and this refit is such a build. The amended gate is a sanity check against the fit's OWN fitted growth, its
# condition's doubling time, within 1.5-fold either way: it catches a broken refit, not a different one. Against it the
# controls sit at 1.02x (basal) and 0.93x (anaerobic); the corpus fit's own anaerobic runs sit at 1.22x theirs.
# Consequence, stated wherever BV-14 is reported: BV-14 tests the fresh build's nitrate response, not the corpus fit's.
FITTED = {"bv14_basal": 44.0, "bv14_anaerobic": 100.0}         # doubling time, min (condition_to_doubling_time)
GATES = {g: {"growth_rate": [round(math.log(2) / (m * 60) / 1.5, 7), round(math.log(2) / (m * 60) * 1.5, 7)]}
         for g, m in FITTED.items()}
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
         "keep_raw": True,   # scored from raw protein counts after the runs finish; deposited after scoring
         "gates_amended": ("2026-11-26, after the first evaluation closed the anaerobic group: the reference was the "
                           "corpus fit's runs, a different model from this fresh build (docs/KB_DIVERGENCE.md); now "
                           "each control's growth within 1.5-fold of its own fit's fitted rate (a sanity check). The "
                           "first gates: basal [1.86e-4, 3.06e-4], anaerobic [1.13e-4, 1.80e-4]; the anaerobic control "
                           "grew at 1.07e-4/s."),
         "gates_amendment_decision": "kept by the user, 2026-11-26",
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


GENES = ("narG", "narH", "narJ", "narI", "frdA", "frdB", "frdC", "frdD", "narK", "nirB", "fnr", "narL", "narX")
CONTRASTS = {   # model (target, reference) on the refit -> PRECISE-1K (cond_A reference, cond_B test)
    "nitrate_under_anaerobiosis": (("no_oxygen_plus_nitrate", "no_oxygen"), ("wt_glc_anaero", "no3_anaero")),
    "anaerobic_vs_aerobic": (("no_oxygen", "basal"), ("wt_glc", "wt_glc_anaero")),           # BV-AN on the refit
    "nitrate_anaerobic_vs_aerobic": (("no_oxygen_plus_nitrate", "basal"), ("wt_glc", "no3_anaero")),  # the combination
}


def _design(name: str) -> dict:
    return {"perturbation": "wildtype", "condition": "basal"} if name == "basal" else _cond(name)


def _roots(name: str) -> list:
    """The refit's QC-clean 3-generation runs of one design, from the plan, on this machine (kept local)."""
    from cellarium import runner
    from cellarium.generate import Design
    plan_runs = json.loads(PLAN.read_text(encoding="utf-8"))["runs"]
    out = []
    for r in plan_runs:
        if r["role"] == "run" and r["design"] == _design(name):
            root = runner._run_subpath(Design(**r["design"]), r["seed"], SIM_PATH)
            if (root / f"generation_{r['generations'] - 1:06d}").is_dir():
                out.append(root)
    return out


def score() -> int:
    """Each contrast: the model's protein log2 fold changes on the refit (reader.gene_lfc over explicit run roots,
    both floors) against PRECISE-1K's RNA log2 fold changes (sci2.build_reference, DESeq2 unshrunk); the named nar/frd
    genes side by side, and the all-gene concordance BV-4 uses."""
    import time

    from cellarium import provenance, reader, sci2
    ok, msg = sci2.available()
    if not ok:
        print(msg, file=sys.stderr)
        return 2
    bmap = sci2._bnumber_map()
    out = {"spec": "BV-14", "knowledge_base": "9055ee3b (the BV-14 refit; data/parca/fits.json)",
           "gates_amended": json.loads(PLAN.read_text(encoding="utf-8")).get("gates_amended"),
           "in_sample": ("by construction for the fitted factors' targets: no_oxygen_plus_nitrate's expression is built "
                         "from NarL's and FNR's fitted fold changes; the combination of the two is the test"),
           "contrasts": {}}
    for key, ((t, r), (cond_a, cond_b)) in CONTRASTS.items():
        t_roots, r_roots = _roots(t), _roots(r)
        ref = sci2.build_reference({"column": "condition", "cond_A": cond_a, "cond_B": cond_b})
        org = {g: v["log2FC"] for g, v in (ref.get("reference_lfc") or {}).items()} if "error" not in ref else {}
        row = {"model": f"{t} vs {r} (refit, {len(t_roots)} against {len(r_roots)} runs)",
               "organism": f"PRECISE-1K {cond_b} vs {cond_a}", "organism_error": ref.get("error")}
        for floor in (20.0, 0.05):
            if t_roots and r_roots:
                g = reader.gene_lfc(t_roots, r_roots, kind="protein", floor=floor)
            else:
                g = {"error": "no runs on disk yet"}
            lfc = g.get("lfc") if isinstance(g, dict) else None
            if not isinstance(lfc, dict):
                row[f"floor_{floor}"] = {"error": str(g)[:300]}
                continue
            sim = {}
            named = {}
            for gid, v in lfc.items():
                sym = v.get("symbol") or gid
                if v.get("log2fc") is None:
                    continue
                b = bmap.get(sym, sym)
                sim[b] = v["log2fc"]
                if sym in GENES:
                    named[sym] = {"model": round(v["log2fc"], 3), "organism": round(org[b], 3) if b in org else None,
                                  "model_target": v.get("target"), "model_reference": v.get("reference")}
            conc = sci2.concordance(sim, org) if org else {"error": "no organism reference"}
            row[f"floor_{floor}"] = {"named_genes": named,
                                     **{k: conc.get(k) for k in ("n_genes", "pearson_r", "spearman_rho",
                                                                  "null_pearson_r", "null_pearson_sd", "deming_slope",
                                                                  "sign_concordance", "verdict", "error") if k in conc}}
        out["contrasts"][key] = row
        print(key, json.dumps({k: v for k, v in row.items() if k.startswith("floor_20")}, default=str)[:900])
    out["computed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out["environment"] = provenance.code_environment()
    OUT.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    if sys.argv[1:2] == ["plan"]:
        return plan()
    if sys.argv[1:2] == ["score"]:
        return score()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
