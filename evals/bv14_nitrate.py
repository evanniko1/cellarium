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


def _join(lfc: dict, bmap: dict, org: dict) -> tuple[dict, dict]:
    """(model log2 fold changes keyed by b-number, the named nar/frd genes side by side) from a symbol-annotated
    `lfc` (differential.annotate_lfc). Refuses a join that matched no gene: the first scoring (2026-11-26) passed the
    reader's bare monomer ids, joined nothing, and the concordance reported INDETERMINATE instead of failing."""
    sim, named = {}, {}
    for v in lfc.values():
        sym = v.get("symbol")
        if not sym or v.get("log2fc") is None:
            continue
        b = bmap.get(sym, sym)
        sim[b] = v["log2fc"]
        if sym in GENES:
            named[sym] = {"model": round(v["log2fc"], 3), "organism": round(org[b], 3) if b in org else None,
                          "model_target": v.get("target"), "model_reference": v.get("reference")}
    if not set(sim) & set(org):
        raise ValueError(f"the model's {len(lfc)} ids joined no gene of the organism's {len(org)} "
                         f"({len(sim)} carried a symbol); annotate them first (differential.annotate_lfc)")
    return sim, named


def _compare_arms(t_vals: list, r_vals: list, pseudocount: float = 0.0) -> dict:
    """Two arms' per-seed values side by side: the log2 ratio of the arm means (with `pseudocount`, 1.0 for counts
    as reader.gene_lfc uses) and Welch's t across seeds. Seeds are not biological replicates; the t says whether the
    seeds' spread could hide the difference, not that the organism would show it. One seed per arm reports no t."""
    t_vals, r_vals = [float(x) for x in t_vals], [float(x) for x in r_vals]
    mt, mr = sum(t_vals) / len(t_vals), sum(r_vals) / len(r_vals)
    tstat = p = None
    if len(t_vals) > 1 and len(r_vals) > 1:
        from scipy import stats
        w = stats.ttest_ind(t_vals, r_vals, equal_var=False)
        tstat, p = round(float(w.statistic), 3), round(float(w.pvalue), 4)
    return {"target": [float(f"{x:.4g}") for x in t_vals], "reference": [float(f"{x:.4g}") for x in r_vals],
            "n": [len(t_vals), len(r_vals)],
            "log2_ratio": round(math.log2((mt + pseudocount) / (mr + pseudocount)), 3), "welch_t": tstat, "p": p}


# Post-hoc diagnostic (added 2026-11-26, after the pre-registered readout): transcription units and factors, ids read
# from the refit's sim_data (TU00044 narGHJI, TU0-45225 frdABCD, TU00046 nirBDC, narK alone).
DIAG_TUS = {"narGHJI": "TU00044[c]", "frdABCD": "TU0-45225[c]", "nirBDC": "TU00046[c]", "narK": "EG10642_RNA[c]"}
DIAG_TFS = ("PHOSPHO-NARL", "FNR-4FE-4S-CPLX", "PHOSPHO-ARCA", "CPLX0-226", "PHOSPHO-DCUR")
DIAG_GENES = ("narG", "narH", "narJ", "narI", "frdA", "frdB", "frdC", "frdD", "nirB", "narK")


def diagnose() -> dict:
    """Post hoc, beside (never instead of) the pre-registered readout. The pre-registered protein readout came back
    opposite in sign to the organism at nar and frd. The model transcribes these operons rarely (narG protein rose at
    all in 4 of 12 generations per arm), so a per-cell protein mean over four seeds records when bursts fell. This
    reads, per arm and seed (last generation): the named proteins, each operon's synthesis probability (the function
    of the TF-bound state that the bursts sample), each factor's promoter occupancy, and the dry mass."""
    from cellarium import differential, reader
    mono = {}
    for m, sym in differential._reverse_gene_map().items():
        if sym in DIAG_GENES:
            mono[sym] = m
    arms = {}
    for name in ("basal", "no_oxygen", "no_oxygen_plus_nitrate"):
        roots = _roots(name)
        sp = reader.species_per_run(roots, "protein", [mono[g] for g in DIAG_GENES if g in mono])
        sy = reader.synthesis_per_run(roots, list(DIAG_TUS.values()), list(DIAG_TFS))
        for res in (sp, sy):
            if not isinstance(res, dict) or res.get("error") or res.get("_unreachable"):
                raise SystemExit(f"diagnose {name}: {str(res)[:300]}")
        rows = []
        for r in roots:
            k = reader._container_path(r)                 # the key the container wrote, as bv6/bv7 read it
            if sy.get(k) is None or sp.get(k) is None or sy[k].get("error") or sy[k].get("missing"):
                raise SystemExit(f"diagnose {name}: run {r.name} unread or incomplete: {sy.get(k)}")
            rows.append({"protein": {g: sp[k][mono[g]]["mean"] for g in DIAG_GENES if g in mono},
                         **{f: sy[k][f] for f in ("actual_synth_prob", "target_synth_prob", "p_promoter_bound",
                                                  "dry_mass_fg")}})
        arms[name] = rows
    fit = reader.fit_synthesis(_roots("no_oxygen_plus_nitrate")[0], ["basal", "no_oxygen", "no_oxygen_plus_nitrate"],
                               list(DIAG_TUS.values()), list(DIAG_TFS))
    if not isinstance(fit, dict) or fit.get("error") or fit.get("missing"):
        raise SystemExit(f"diagnose: the fit's own targets unread: {str(fit)[:300]}")
    fc = fit["conditions"]
    d = {"added": "2026-11-26, after the pre-registered protein readout; it does not replace that readout",
         "why": diagnose.__doc__.split(". ", 1)[1].replace("\n    ", " "),
         "n_seeds": {a: len(v) for a, v in arms.items()},
         "promoter_occupancy": {a: {"simulated": {tf: round(sum(r["p_promoter_bound"][tf] for r in v) / len(v), 3)
                                                  for tf in DIAG_TFS},
                                    "fit_assumed": {tf: round(fc[a]["p_promoter_bound"][tf], 3) for tf in DIAG_TFS}}
                                for a, v in arms.items()},
         "contrasts": {}}
    for key, ((t, r), _org) in CONTRASTS.items():
        tv, rv = arms[t], arms[r]
        d["contrasts"][key] = {
            "dry_mass_fg": _compare_arms([x["dry_mass_fg"] for x in tv], [x["dry_mass_fg"] for x in rv]),
            "actual_synth_prob": {op: _compare_arms([x["actual_synth_prob"][tu] for x in tv],
                                                    [x["actual_synth_prob"][tu] for x in rv])
                                  for op, tu in DIAG_TUS.items()},
            "fitted_log2_synth_ratio": {op: round(math.log2(fc[t]["synth_prob"][tu] / fc[r]["synth_prob"][tu]), 3)
                                        for op, tu in DIAG_TUS.items()},
            "protein_per_seed": {g: _compare_arms([x["protein"][g] for x in tv], [x["protein"][g] for x in rv],
                                                  pseudocount=1.0) for g in DIAG_GENES if g in mono}}
    return d


def score() -> int:
    """Each contrast: the model's protein log2 fold changes on the refit (reader.gene_lfc over explicit run roots,
    both floors) against PRECISE-1K's RNA log2 fold changes (sci2.build_reference, DESeq2 unshrunk); the named nar/frd
    genes side by side, and the all-gene concordance BV-4 uses."""
    import time

    from cellarium import differential, provenance, reader, sci2
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
                g = differential.annotate_lfc(reader.gene_lfc(t_roots, r_roots, kind="protein", floor=floor),
                                              "protein")
            else:
                g = {"error": "no runs on disk yet"}
            lfc = g.get("lfc") if isinstance(g, dict) else None
            if not isinstance(lfc, dict):
                row[f"floor_{floor}"] = {"error": str(g)[:300]}
                continue
            if not org:
                raise SystemExit(f"{key}: no organism reference ({ref.get('error')})")
            sim, named = _join(lfc, bmap, org)
            conc = sci2.concordance(sim, org)
            read = (g.get("n_target_runs"), g.get("n_reference_runs"))
            if read != (len(t_roots), len(r_roots)):      # the reader omits an unreachable run rather than failing
                raise SystemExit(f"{key}: read {read} runs of {(len(t_roots), len(r_roots))}: "
                                 f"{g.get('_unreachable_runs')}")
            row[f"floor_{floor}"] = {"named_genes": named, "n_runs_read": list(read),
                                     **{k: conc.get(k) for k in ("n_genes", "pearson_r", "spearman_rho",
                                                                  "null_pearson_r", "null_pearson_sd", "deming_slope",
                                                                  "sign_concordance", "verdict", "error") if k in conc}}
        out["contrasts"][key] = row
        print(key, json.dumps({k: v for k, v in row.items() if k.startswith("floor_20")}, default=str)[:900])
    out["diagnostic_post_hoc"] = diagnose()
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
