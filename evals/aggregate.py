"""Aggregate the ablation records (evals/results/ablation.json) into the paper's statistics.

Per config: operationalization-quality (Claude & GPT graders) as case-clustered mean +/- 95% CI, convergence
and feasibility rates (Wilson intervals), mean rounds. Paired full-vs-ablation comparison across cases
(Wilcoxon signed-rank on per-case means). Inter-rater reliability (Claude vs GPT): Pearson r on scores +
per-criterion percent agreement. Robust to partial/streaming input. Run: python evals/aggregate.py [in.json].
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

try:
    from scipy.stats import pearsonr, wilcoxon
except Exception:  # scipy optional
    pearsonr = wilcoxon = None

Q = ["q1_falsifiable", "q2_operationalized", "q3_discriminating", "q4_quantitative", "q5_specified",
     "q6_consistent"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(p, 3), round(max(0, c - h), 3), round(min(1, c + h), 3))


def case_clustered_mean(records, key):
    """Mean of per-case means (each case = mean over its reps), + a normal 95% CI across cases."""
    by_case = defaultdict(list)
    for r in records:
        v = (r.get(key) or {}).get("score") if key in ("claude", "gpt") else r.get(key)
        if v is not None:
            by_case[r["id"]].append(v)
    case_means = [float(np.mean(v)) for v in by_case.values() if v]
    if not case_means:
        return None
    m = float(np.mean(case_means))
    se = float(np.std(case_means, ddof=1) / math.sqrt(len(case_means))) if len(case_means) > 1 else 0.0
    return {"mean": round(m, 3), "ci95": [round(m - 1.96 * se, 3), round(m + 1.96 * se, 3)],
            "n_cases": len(case_means), "per_case": {cid: round(float(np.mean(v)), 3) for cid, v in by_case.items()}}


def paired_vs_full(per_case_full: dict, per_case_other: dict):
    cids = sorted(set(per_case_full) & set(per_case_other))
    diffs = [per_case_full[c] - per_case_other[c] for c in cids]
    out = {"n_paired_cases": len(cids), "mean_diff_full_minus_config": round(float(np.mean(diffs)), 3) if diffs else None,
           "cases_full_better": sum(d > 0 for d in diffs), "cases_worse": sum(d < 0 for d in diffs),
           "cases_tie": sum(d == 0 for d in diffs)}
    if wilcoxon is not None and len([d for d in diffs if d != 0]) >= 1:
        try:
            out["wilcoxon_p"] = round(float(wilcoxon(diffs).pvalue), 4)
        except Exception:
            out["wilcoxon_p"] = None
    return out


def interrater(records):
    cs, gs, per_crit = [], [], {q: [0, 0] for q in Q}  # [agree, total]
    for r in records:
        c, g = r.get("claude"), r.get("gpt")
        if not c or not g:
            continue
        if c.get("score") is not None and g.get("score") is not None:
            cs.append(c["score"]); gs.append(g["score"])
        for q in Q:
            if q in c and q in g:
                per_crit[q][1] += 1
                per_crit[q][0] += int(bool(c[q]) == bool(g[q]))
    out = {"n": len(cs)}
    if pearsonr is not None and len(cs) >= 3 and np.std(cs) > 0 and np.std(gs) > 0:
        out["pearson_r_scores"] = round(float(pearsonr(cs, gs)[0]), 3)
    out["mean_abs_score_diff"] = round(float(np.mean(np.abs(np.array(cs) - np.array(gs)))), 3) if cs else None
    out["per_criterion_pct_agreement"] = {q: (round(a / t, 3) if t else None) for q, (a, t) in per_crit.items()}
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "evals/results/ablation.json"
    d = json.loads(Path(src).read_text())
    recs = [r for r in d["results"] if "error" not in r]
    n_err = len(d["results"]) - len(recs)
    by_cfg = defaultdict(list)
    for r in recs:
        by_cfg[r["config"]].append(r)

    summary = {"source": src, "n_records": len(recs), "n_errors": n_err, "configs": {}}
    q_full = None
    for cfg in ["full", "no_skeptic", "proposer_only", "generic_judge"]:
        rs = by_cfg.get(cfg)
        if not rs:
            continue
        qc = case_clustered_mean(rs, "claude")
        qg = case_clustered_mean(rs, "gpt")
        conv = wilson(sum(bool(r.get("converged")) for r in rs), len(rs))
        feas = wilson(sum(bool(r.get("feasible")) for r in rs), len(rs))
        rounds = round(float(np.mean([r.get("rounds_used", 0) for r in rs])), 2)
        entry = {"n": len(rs), "quality_claude": qc, "quality_gpt": qg,
                 "convergence_rate": {"p": conv[0], "ci95": conv[1:]},
                 "feasible_rate": {"p": feas[0], "ci95": feas[1:]}, "mean_rounds": rounds}
        if cfg == "full":
            q_full = qc
        elif q_full and qc:
            entry["vs_full_quality_claude"] = paired_vs_full(q_full["per_case"], qc["per_case"])
        summary["configs"][cfg] = entry
    summary["interrater_claude_vs_gpt"] = interrater(recs)

    # --- residual-defect audit (the sensitive primary mechanism metric) ---
    aud_path = Path(src).with_name("audited.json")
    if aud_path.exists():
        aud = {(a["id"], a["config"], a["rep"]): a for a in json.loads(aud_path.read_text())["results"]}
        by_cfg_def = defaultdict(list)
        for r in recs:
            a = aud.get((r["id"], r["config"], r["rep"]))
            if a:
                r["_claude_defects"] = a.get("claude_defects")
                r["_gpt_defects"] = a.get("gpt_defects")
                by_cfg_def[r["config"]].append(r)
        dsum, dfull_c, dfull_g = {}, None, None
        for cfg in ["full", "no_skeptic", "proposer_only", "generic_judge"]:
            rs = by_cfg_def.get(cfg)
            if not rs:
                continue
            dc = case_clustered_mean(rs, "_claude_defects")
            dg = case_clustered_mean(rs, "_gpt_defects")
            e = {"n": len(rs), "defects_claude": dc, "defects_gpt": dg}
            if cfg == "full":
                dfull_c, dfull_g = dc, dg
            else:
                for lab, dcfg, dfl in (("claude", dc, dfull_c), ("gpt", dg, dfull_g)):
                    if not (dcfg and dfl):
                        continue
                    cids = sorted(set(dcfg["per_case"]) & set(dfl["per_case"]))
                    diffs = [dcfg["per_case"][c] - dfl["per_case"][c] for c in cids]  # config - full; >0 => full better
                    cmp = {"n_paired_cases": len(cids),
                           "mean_defects_reduced_by_full": round(float(np.mean(diffs)), 3) if diffs else None,
                           "cases_full_fewer": sum(d > 0 for d in diffs), "cases_full_more": sum(d < 0 for d in diffs)}
                    if wilcoxon is not None and any(d != 0 for d in diffs):
                        try:  # one-sided: full has fewer defects
                            cmp["wilcoxon_p_full_fewer"] = round(float(
                                wilcoxon(diffs, alternative="greater").pvalue), 4)
                        except Exception:
                            cmp["wilcoxon_p_full_fewer"] = None
                    e[f"vs_full_{lab}"] = cmp
            dsum[cfg] = e
        summary["residual_defects"] = dsum
        print("\n=== residual defects (lower is better; sensitive mechanism metric) ===")
        print(f"{'config':14s} {'defects_claude':>18s} {'defects_gpt':>18s}   full-reduces-by (claude p / gpt p)")
        for cfg, e in dsum.items():
            dc, dg = e["defects_claude"], e["defects_gpt"]
            dcs = f"{dc['mean']} {dc['ci95']}" if dc else "-"
            dgs = f"{dg['mean']} {dg['ci95']}" if dg else "-"
            vc, vg = e.get("vs_full_claude", {}), e.get("vs_full_gpt", {})
            red = (f"c:{vc.get('mean_defects_reduced_by_full')}(p={vc.get('wilcoxon_p_full_fewer')}) "
                   f"g:{vg.get('mean_defects_reduced_by_full')}(p={vg.get('wilcoxon_p_full_fewer')})") if vc or vg else ""
            print(f"{cfg:14s} {dcs:>18s} {dgs:>18s}   {red}")

    out = Path(src).with_name("ablation_summary.json")
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"records={len(recs)} errors={n_err}")
    print(f"{'config':14s} {'q_claude':>16s} {'q_gpt':>16s} {'conv':>6s} {'feas':>6s} {'rounds':>6s}  vs_full(Δ, p)")
    for cfg, e in summary["configs"].items():
        qc = e["quality_claude"]; qg = e["quality_gpt"]
        qcs = f"{qc['mean']} {qc['ci95']}" if qc else "-"
        qgs = f"{qg['mean']} {qg['ci95']}" if qg else "-"
        vf = e.get("vs_full_quality_claude", {})
        vfs = f"Δ={vf.get('mean_diff_full_minus_config')} p={vf.get('wilcoxon_p')}" if vf else ""
        print(f"{cfg:14s} {qcs:>16s} {qgs:>16s} {e['convergence_rate']['p']:>6} {e['feasible_rate']['p']:>6} "
              f"{e['mean_rounds']:>6}  {vfs}")
    ir = summary["interrater_claude_vs_gpt"]
    print(f"\ninter-rater (Claude vs GPT): n={ir['n']} pearson_r={ir.get('pearson_r_scores')} "
          f"mean|Δscore|={ir.get('mean_abs_score_diff')}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
