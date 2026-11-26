"""BV-14d: why does the fit's NarL effect shrink in simulation? Occupancy-clamped runs on the BV-14 refit.

BV-14 found nitrate raising nar synthesis +0.25 log2 under anaerobiosis where the fit asked +1.29. The runs bind FNR
at 0.99 where the fit assumed 0.78, so the first question is whether holding occupancy at the fit's values restores
the effect. A pre-analysis with the model's own equations (scratch, recorded in the plan) predicts it does not: the
simulation adds each factor's effect inside one multiplier, basal(ppGpp) x (1 + sum(delta * bound)), while ParCa built
the anaerobic-nitrate condition's target by multiplying the factors' fold changes, so FNR's large term dilutes
NarL's. The second question tests that account directly: hold FNR off (the fnr-mutant state Walker and DeMoss 1992
measured) and NarL's effect should grow about threefold.

A 2 x 2 on the refit (kb 9055ee3b): FNR at the fit's occupancy or held off, by NarL off (anaerobic) or at the
fit's occupancy (nitrate); 3 seeds x 3 generations per cell, two 1-generation controls that gate their groups.
Every run is tested before it counts (`validity`): failed QC, an undivided generation, a clamp that did not hold
(bound fraction off target), or, in the fit arms, growth outside 1.5-fold of the fitted rate, and it is discarded
with its reasons.

    WCECOLI_DOCKER=<code image> python evals/bv14d_clamp.py plan     # writes evals/plans/bv14d.json
    WCECOLI_DOCKER=<code image> .venv/Scripts/python.exe evals/bv14d_clamp.py score
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))
PLAN = REPO / "evals" / "plans" / "bv14d.json"
OUT = REPO / "evals" / "results" / "bv14d_clamp.json"
LEDGER = REPO / "evals" / "results" / "bv14d_ledger.jsonl"
SIM_PATH = "bv14_no3_anaerobic"
KB = "9055ee3b2b7b029edf99af6fd5c0bc435f19f47e3ce28e0f020d7cfb0e3e8ef6"
FNR, NARL = "FNR-4FE-4S-CPLX", "PHOSPHO-NARL"
CLAMP_FIT = {FNR: "fit", NARL: "fit"}
CLAMP_OFF = {FNR: 0, NARL: "fit"}
CONDITION = {"no_oxygen": 7, "no_oxygen_plus_nitrate": 24}
FITTED_DOUBLING_MIN = {"no_oxygen": 100.0, "no_oxygen_plus_nitrate": 82.0}
TOL = 0.05                     # a clamp held: the bound fraction within this of its target (exactly 0 when off)
ARMS = {"F1": ("no_oxygen", CLAMP_FIT, "bv14d_fit", (300, 301, 302)),
        "F2": ("no_oxygen_plus_nitrate", CLAMP_FIT, "bv14d_fit", (300, 301, 302)),
        "O1": ("no_oxygen", CLAMP_OFF, "bv14d_fnroff", (330, 331, 332)),
        "O2": ("no_oxygen_plus_nitrate", CLAMP_OFF, "bv14d_fnroff", (330, 331, 332))}
CONTROLS = {"bv14d-ctl-fit": ("no_oxygen_plus_nitrate", CLAMP_FIT, "bv14d_fit", 310),
            "bv14d-ctl-off": ("no_oxygen_plus_nitrate", CLAMP_OFF, "bv14d_fnroff", 340)}
# The model's own equations, expected values (scratch pre-analysis, 2026-11-26): nitrate against anaerobic, log2
PREDICTED = {"FNR_at_fit": {"narGHJI": 0.549, "frdABCD": -0.324}, "FNR_off": {"narGHJI": 1.454, "frdABCD": -1.128},
             "as_run_bv14": {"narGHJI": 0.45, "frdABCD": -0.297},
             "note": ("expected-value algebra over all transcription units, with the runs' ppGpp (anaerobic 61.7, "
                      "nitrate 40.4 uM); it over-predicted BV-14's observed nar ratio by 0.20 and under-predicted frd's "
                      "by 0.17, so the decision rules use differences, which that offset largely cancels")}


def _design(condition: str, clamp: dict) -> dict:
    return {"perturbation": "condition", "condition": condition,
            "params": {"variant_index": CONDITION[condition], "tf_occupancy_clamp": dict(clamp)}}


def _rate(doubling_min: float) -> float:
    return math.log(2) / (doubling_min * 60)


def _targets(clamp: dict, condition: str, fit: dict) -> dict:
    """A clamp's numeric targets: "fit" resolved to the refit's own occupancy for the condition."""
    return {tf: float(fit[condition][tf]) if v == "fit" else float(v) for tf, v in clamp.items()}


def validity(run: dict, targets: dict, growth_range=None, tol: float = TOL) -> list[str]:
    """Why a run is discarded; [] when it counts. `run` = {qc, divided, growth_per_s, bound_fraction}."""
    why = []
    if run.get("qc") != "ok":
        why.append(f"QC {run.get('qc')}")
    if not run.get("divided"):
        why.append("a generation did not divide")
    got = run.get("bound_fraction") or {}
    for tf, t in targets.items():
        v = got.get(tf)
        if v is None:
            why.append(f"{tf} bound fraction unread")
        elif (t == 0 and v != 0) or (t > 0 and abs(v - t) > tol):
            why.append(f"{tf} bound fraction {v:.3f} against its clamp {t:.3f} (tolerance {0 if t == 0 else tol})")
    if growth_range is not None:
        g = run.get("growth_per_s")
        if g is None or not growth_range[0] <= g <= growth_range[1]:
            why.append(f"growth {g} outside [{growth_range[0]:.3g}, {growth_range[1]:.3g}] per s")
    return why


def interaction(o2: list, o1: list, f2: list, f1: list) -> dict:
    """NarL's effect with FNR held off minus with FNR at the fit, on per-seed log2 values:
    (mean O2 - mean O1) - (mean F2 - mean F1), with its standard error. None when any arm has under two seeds."""
    arms = (o2, o1, f2, f1)
    n = [len(a) for a in arms]
    if min(n) < 2:
        return {"estimate": None, "se": None, "z": None, "n": n}
    mean = [sum(a) / len(a) for a in arms]
    var = [sum((x - m) ** 2 for x in a) / (len(a) - 1) for a, m in zip(arms, mean)]
    est = (mean[0] - mean[1]) - (mean[2] - mean[3])
    se = math.sqrt(sum(v / k for v, k in zip(var, n)))
    return {"estimate": round(est, 3), "se": round(se, 3), "z": round(est / se, 2) if se else None, "n": n}


def plan() -> int:
    from cellarium import reader
    fit_raw = reader.fit_synthesis(REPO / "runs" / SIM_PATH, list(CONDITION), [], [FNR, NARL])
    if not isinstance(fit_raw, dict) or fit_raw.get("error") or fit_raw.get("missing"):
        print(f"the refit's occupancies are unread: {str(fit_raw)[:300]}", file=sys.stderr)
        return 2
    fit = {c: v["p_promoter_bound"] for c, v in fit_raw["conditions"].items()}
    t_fit = _targets(CLAMP_FIT, "no_oxygen_plus_nitrate", fit)
    t_off = _targets(CLAMP_OFF, "no_oxygen_plus_nitrate", fit)
    g = _rate(FITTED_DOUBLING_MIN["no_oxygen_plus_nitrate"])
    gates = {"bv14d_fit": {"growth_rate": [round(g / 1.5, 7), round(g * 1.5, 7)],
                           "occupancy": {tf: [round(max(0.0, t - TOL), 3), round(min(1.0, t + TOL), 3)]
                                         for tf, t in t_fit.items()}},
             "bv14d_fnroff": {"occupancy": {tf: ([0.0, 0.0] if t == 0 else
                                                 [round(max(0.0, t - TOL), 3), round(min(1.0, t + TOL), 3)])
                                            for tf, t in t_off.items()}}}
    runs = [{"id": rid, "design": _design(cond, clamp), "seed": seed, "generations": 1, "group": group,
             "role": "control", "stage": 1} for rid, (cond, clamp, group, seed) in CONTROLS.items()]
    runs += [{"id": f"bv14d-{arm}-s{s}", "design": _design(cond, clamp), "seed": s, "generations": 3,
              "group": group, "role": "run", "stage": 2}
             for arm, (cond, clamp, group, seeds) in ARMS.items() for s in seeds]
    rules = {
        "validity": ("a run counts only if: QC ok and every generation divided; each clamped factor's bound fraction "
                     f"within {TOL} of its target (exactly 0 for a factor held off); in the fit arms, growth within "
                     "1.5-fold of the condition's fitted rate. Otherwise it is discarded, listed with its reasons, and "
                     "never averaged. An arm left with fewer than two valid seeds reports no contrast."),
        "D1_occupancy": ("phi = (R_F - R_BV14) / (R_fit - R_BV14), the share of BV-14's nar attenuation the clamp "
                         "restores (R_F: nar synthesis, nitrate against anaerobic, FNR and NarL at the fit). "
                         "Predicted about 0.1. phi >= 0.5: occupancy is the main cause and the pre-analysis is wrong"),
        "D2_additive_dilution": ("I = NarL's nar effect with FNR held off minus with FNR at the fit (log2). Predicted "
                                 "about +0.9. I >= 0.5 with z >= 2 supports the additive account; I < 0.25 rejects it"),
        "readout": "per-seed time-mean synthesis probability (RnaSynthProb), last generation, as BV-14's diagnostic",
    }
    p = {"batch": "bv14d", "sim_path": SIM_PATH, "parallel": 6, "min_free_gb": 40, "priority": -2, "gates": gates,
         "keep_raw": True, "kb_sha256": KB,
         "clamp_targets": {"FNR_at_fit": t_fit, "FNR_off": t_off,
                           "anaerobic_FNR_at_fit": _targets(CLAMP_FIT, "no_oxygen", fit),
                           "anaerobic_FNR_off": _targets(CLAMP_OFF, "no_oxygen", fit)},
         "fit_occupancy": fit, "predictions": PREDICTED, "rules": rules,
         "decided_by": ("the user, 2026-11-26: \"Go for the BV-14d occupancy-clamped runs. Make sure that test "
                        "failures and defective runs are discarded.\""),
         "why": ("BV-14's NarL effect is a fifth of the fit's; the pre-analysis puts most of the gap in how the "
                 "simulation combines factors, not in occupancy, and these runs test both"),
         "runs": runs}
    p["design_sha256"] = hashlib.sha256(json.dumps({k: p[k] for k in ("gates", "runs", "rules", "predictions",
                                                                        "clamp_targets")},
                                                   sort_keys=True).encode()).hexdigest()
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(p, indent=1) + "\n", encoding="utf-8")
    print(f"{PLAN.relative_to(REPO)}: {len(runs)} runs, design_sha256 {p['design_sha256'][:12]}")
    return 0


def _ledger_summaries() -> dict:
    out = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("event") in ("finished", "adopted") and r.get("summary"):
                out[r["id"]] = r["summary"]
    return out


def score() -> int:
    import bv14_nitrate as B14

    from cellarium import provenance, reader, runner
    from cellarium.generate import Design
    p = json.loads(PLAN.read_text(encoding="utf-8"))
    targets = {"F": p["clamp_targets"], "fit": p["fit_occupancy"]}
    summaries = _ledger_summaries()
    tus, tfs = list(B14.DIAG_TUS.values()), [FNR, NARL, "PHOSPHO-ARCA", "CPLX0-226", "PHOSPHO-DCUR"]
    runs, discarded = {}, []
    roots = {}
    for r in p["runs"]:
        s = summaries.get(r["id"])
        root = runner._run_subpath(Design(**r["design"]), r["seed"], SIM_PATH)
        if not s:
            discarded.append({"id": r["id"], "why": ["did not finish (no summary in the ledger)"]})
            continue
        roots[r["id"]] = root
        runs[r["id"]] = {"spec": r, "qc": s.get("qc"),
                         "divided": all(g.get("divided") for g in s.get("generations") or [{}]),
                         "growth_per_s": (s.get("channels") or {}).get("growth_rate"),
                         "ppgpp_uM": (s.get("channels") or {}).get("ppgpp_conc")}
    got = reader.synthesis_per_run(list(roots.values()), tus, tfs) if roots else {}
    if roots and (not isinstance(got, dict) or got.get("error")):
        print(f"synthesis unread: {str(got)[:300]}", file=sys.stderr)
        return 2
    valid = {arm: [] for arm in ARMS}
    for rid, run in runs.items():
        rec = got.get(reader._container_path(roots[rid])) or {}
        run.update({k: rec.get(k) for k in ("actual_synth_prob", "p_promoter_bound", "bound_fraction", "dry_mass_fg")})
        if rec.get("error") or rec.get("missing"):
            run["why"] = [f"raw output unread: {rec.get('error') or rec.get('missing')}"]
        else:
            cond = run["spec"]["design"]["condition"]
            clamp = run["spec"]["design"]["params"]["tf_occupancy_clamp"]
            t = _targets(clamp, cond, targets["fit"])
            fit_arm = run["spec"]["group"] == "bv14d_fit"
            g = _rate(FITTED_DOUBLING_MIN[cond])
            run["why"] = validity(run, t, growth_range=(g / 1.5, g * 1.5) if fit_arm else None)
        if run["why"]:
            discarded.append({"id": rid, "why": run["why"]})
        elif run["spec"]["role"] == "run":
            arm = rid.split("-")[1]
            valid[arm].append(run)
    out = {"spec": "BV-14d", "plan_design_sha256": p["design_sha256"], "knowledge_base": KB[:8],
           "valid_seeds": {a: [r["spec"]["seed"] for r in v] for a, v in valid.items()},
           "discarded": discarded, "predictions": p["predictions"], "rules": p["rules"],
           "clamp_targets": p["clamp_targets"], "contrasts": {}, "decisions": {}}
    bv14 = json.loads((REPO / "evals" / "results" / "bv14_nitrate.json").read_text(encoding="utf-8"))
    d14 = bv14["diagnostic_post_hoc"]["contrasts"]["nitrate_under_anaerobiosis"]
    for op, tu in B14.DIAG_TUS.items():
        vals = {a: [r["actual_synth_prob"][tu] for r in v] for a, v in valid.items()}
        row = {}
        for name, (t, r) in {"NarL_effect_FNR_at_fit": ("F2", "F1"), "NarL_effect_FNR_off": ("O2", "O1")}.items():
            row[name] = (B14._compare_arms(vals[t], vals[r]) if len(vals[t]) >= 2 and len(vals[r]) >= 2
                         else {"log2_ratio": None, "why": "fewer than two valid seeds in an arm"})
        lg = {a: [math.log2(x) for x in v] for a, v in vals.items()}
        row["interaction"] = interaction(lg["O2"], lg["O1"], lg["F2"], lg["F1"])
        r_f, r_u, r_fit = (row["NarL_effect_FNR_at_fit"].get("log2_ratio"),
                           d14["actual_synth_prob"][op]["log2_ratio"], d14["fitted_log2_synth_ratio"][op])
        row["phi_share_of_bv14_attenuation_restored"] = (round((r_f - r_u) / (r_fit - r_u), 3)
                                                         if r_f is not None and r_fit != r_u else None)
        out["contrasts"][op] = row
    nar = out["contrasts"]["narGHJI"]
    phi, inter = nar["phi_share_of_bv14_attenuation_restored"], nar["interaction"]
    out["decisions"] = {
        "D1_occupancy": (None if phi is None else
                         "occupancy is the main cause (phi >= 0.5)" if phi >= 0.5 else
                         f"occupancy restores a minor share (phi {phi})"),
        "D2_additive_dilution": (None if inter["estimate"] is None else
                                 "supported (I >= 0.5, z >= 2)" if inter["estimate"] >= 0.5 and (inter["z"] or 0) >= 2
                                 else "rejected (I < 0.25)" if inter["estimate"] < 0.25 else
                                 f"not settled (I {inter['estimate']}, z {inter['z']})"),
    }
    out["occupancy_achieved"] = {rid: {"bound_fraction": r.get("bound_fraction"), "growth_per_h":
                                       round(r["growth_per_s"] * 3600, 3) if r.get("growth_per_s") else None,
                                       "ppgpp_uM": r.get("ppgpp_uM")} for rid, r in runs.items()}
    out["computed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out["environment"] = provenance.code_environment()
    OUT.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"valid_seeds": out["valid_seeds"], "discarded": len(discarded), "decisions": out["decisions"]}))
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
