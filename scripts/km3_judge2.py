"""Follow-ups to km3_judge.py: ppGpp flux balance, growth-noise structure, GLY/LEU detail."""

import json
import math
import sys

import numpy as np

scratch = sys.argv[1]
with open(scratch + "/judge_rows.json") as fh:
    D = json.load(fh)
new = [r for r in D["new"] if r["status"] == "OK"]
old = [r for r in D["old"] if r["status"] == "OK"]
key = lambda r: (r["arm"], r["seed"], r["gen"])
dn = {key(r): r for r in new}
do = {key(r): r for r in old}
common = sorted(set(dn) & set(do))


def ms(v):
    v = np.asarray(v, float)
    return v.mean(), (v.std(ddof=1) if v.size > 1 else float("nan"))


def tt(d):
    d = np.asarray(d, float)
    m, s = d.mean(), d.std(ddof=1)
    return m, s, m / (s / math.sqrt(d.size)), d.size


print("=== ppGpp FLUX BALANCE  (v_syn = rela_syn.sum() + spot_syn ; v_deg = spot_deg) ===")
print("   source: models/ecoli/processes/polypeptide_elongation.py:1565 v_syn, :1612 return")
for tag, rows in (("OLD", old), ("NEW", new)):
    bal = [(r["rela_total_mean"] + r["spot_syn_mean"]) / r["spot_deg_mean"] for r in rows]
    m, s = ms(bal)
    rel = [r["rela_total_mean"] / (r["rela_total_mean"] + r["spot_syn_mean"]) for r in rows]
    rm, rs = ms(rel)
    vs, _ = ms([r["rela_total_mean"] + r["spot_syn_mean"] for r in rows])
    vd, _ = ms([r["spot_deg_mean"] for r in rows])
    print("  %s n=%d  v_syn %.4f  v_deg %.4f  syn/deg %.4f +/- %.4f  RelA share of synthesis %.3f +/- %.3f"
          % (tag, len(rows), vs, vd, m, s, rm, rs))
d = [(dn[k]["rela_total_mean"] + dn[k]["spot_syn_mean"]) / dn[k]["spot_deg_mean"]
     - (do[k]["rela_total_mean"] + do[k]["spot_syn_mean"]) / do[k]["spot_deg_mean"] for k in common]
m, s, t, n = tt(d)
print("  paired delta syn/deg  %+0.5f  sd %.5f  t %+.2f  n %d" % (m, s, t, n))
for f, lab in (("rela_total_mean", "v_rela_syn"), ("spot_syn_mean", "v_spot_syn"),
               ("spot_deg_mean", "v_deg"), ("ppgpp_mean", "ppgpp_conc")):
    m, s, t, n = tt([dn[k][f] - do[k][f] for k in common])
    a, _ = ms([r[f] for r in old])
    b, _ = ms([r[f] for r in new])
    print("  %-12s OLD %.4f -> NEW %.4f (x%.3f)  paired delta %+.4f sd %.4f t %+.2f n %d"
          % (lab, a, b, b / a, m, s, t, n))
print("  ppgpp_conc per-cell means, NEW, sorted:")
v = sorted(r["ppgpp_mean"] for r in new)
print("    " + " ".join("%.1f" % x for x in v))
print("  NEW cells inside 25-67 uM: %d/27 ; median %.2f ; OLD median %.2f"
      % (sum(25 <= x <= 67 for x in v), np.median(v), np.median([r["ppgpp_mean"] for r in old])))

print("\n=== GROWTH NOISE STRUCTURE ===")
print("  The KMtf change is IDENTICAL in all three arms, so the arm-to-arm scatter of the")
print("  old->new delta is pure noise. Compare the pooled effect against that scatter.")
for f in ("doubling_min", "duration_min", "mass_ratio"):
    arm_means = {}
    for arm in ("fam", "abu", "equ"):
        ks = [k for k in common if k[0] == arm]
        arm_means[arm] = np.mean([dn[k][f] - do[k][f] for k in ks])
    pooled_m, pooled_s, pooled_t, npool = tt([dn[k][f] - do[k][f] for k in common])
    arm_sd = np.std(list(arm_means.values()), ddof=1)
    print("  %-14s pooled %+8.4f (t %+.2f n %d) | arms fam %+8.4f abu %+8.4f equ %+8.4f | arm-sd %.4f -> %s"
          % (f, pooled_m, pooled_t, npool, arm_means["fam"], arm_means["abu"], arm_means["equ"],
             arm_sd, "effect < arm noise" if abs(pooled_m) < arm_sd else "effect > arm noise"))
print("  largest per-cell doubling-time deltas (new-old):")
dd = sorted(((dn[k]["doubling_min"] - do[k]["doubling_min"], k, dn[k]["n_steps"], do[k]["n_steps"])
             for k in common), key=lambda x: -abs(x[0]))[:5]
for delta, k, ns, os_ in dd:
    print("    %-4s s%d g%d  %+8.2f min   steps NEW %d OLD %d" % (k[0], k[1], k[2], delta, ns, os_))
ks = [k for k in common if not (k[0] == "fam" and k[1] == 2 and k[2] == 2)]
m, s, t, n = tt([dn[k]["doubling_min"] - do[k]["doubling_min"] for k in ks])
print("  doubling_min with fam_s2_g2 dropped: %+.4f sd %.4f t %+.2f n %d" % (m, s, t, n))

print("\n=== GLY / LEU DETAIL, isoacceptor+equal, per cell ===")
ref = {"GLY[c]": (0.348, 0.032), "LEU[c]": (0.248, 0.014)}
for fam in ("GLY[c]", "LEU[c]"):
    nv = [r["fam_med"][fam] for r in new if r["arm"] == "equ"]
    ov = [r["fam_med"][fam] for r in old if r["arm"] == "equ"]
    rm, rs = ref[fam]
    m, s = ms(nv)
    se = s / math.sqrt(len(nv))
    print("  %-8s OLD %.4f+/-%.4f -> NEW %.4f+/-%.4f (n=%d each)  ref %.3f+/-%.3f"
          % (fam, np.mean(ov), np.std(ov, ddof=1), m, s, len(nv), rm, rs))
    print("           per-cell NEW: " + " ".join("%.3f" % x for x in nv))
    print("           NEW/ref = %.2f ; z vs ref using arm sd %+.2f ; using ref sd %+.2f ; "
          "using SEM of arm mean %+.2f ; within factor 2 of ref: %s"
          % (m / rm, (m - rm) / s, (m - rm) / rs, (m - rm) / se, "YES" if 0.5 <= m / rm <= 2.0 else "NO"))
    un = [r["fam_uncharged_frac"][fam] for r in new if r["arm"] == "equ"]
    uo = [r["fam_uncharged_frac"][fam] for r in old if r["arm"] == "equ"]
    print("           uncharged fraction OLD %.4f -> NEW %.4f (x%.2f)"
          % (np.mean(uo), np.mean(un), np.mean(un) / np.mean(uo)))

print("\n=== how many families rose / fell, equal arm ===")
eqn = [r for r in new if r["arm"] == "equ"]
eqo = [r for r in old if r["arm"] == "equ"]
rat = {f: np.mean([r["fam_med"][f] for r in eqn]) / np.mean([r["fam_med"][f] for r in eqo])
       for f in eqn[0]["fam_med"] if np.mean([r["fam_med"][f] for r in eqo]) > 0}
up = {f: v for f, v in rat.items() if v > 1.5}
down = {f: v for f, v in rat.items() if v < 1.0}
print("  rose >1.5x: %d families %s" % (len(up), sorted(up, key=lambda f: -rat[f])))
print("  FELL      : %d families %s" % (len(down), sorted(down, key=lambda f: rat[f])))
print("  worst-family identity, equal arm: OLD %s ; NEW %s"
      % (max(eqo[0]["fam_med"], key=eqo[0]["fam_med"].get), max(eqn[0]["fam_med"], key=eqn[0]["fam_med"].get)))
