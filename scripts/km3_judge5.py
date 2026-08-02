"""Remaining checks: N for the family-control zero, per-generation stability, band counts."""

import json
import sys

import numpy as np

scratch = sys.argv[1]
rows = json.load(open(scratch + "/judge_rows.json"))
new = [r for r in rows["new"] if r["status"] == "OK"]
old = [r for r in rows["old"] if r["status"] == "OK"]

fam_new = [r for r in new if r["arm"] == "fam"]
fam_old = [r for r in old if r["arm"] == "fam"]
print("=== family control, N of the 'exactly 0.0' claim ===")
for tag, rows_ in (("OLD", fam_old), ("NEW", fam_new)):
    steps = sum(r["n_steps"] for r in rows_)
    nfam = len(rows_[0]["fam_med"])
    worst = max(max(r["fam_max"].values()) for r in rows_)
    print("  %s %d cells x %d multi-member families, %d timesteps total (%d family-timesteps);"
          " largest span seen at ANY timestep = %.3e"
          % (tag, len(rows_), nfam, steps, steps * nfam, worst))

abu_new = [r for r in new if r["arm"] == "abu"]
abu_old = [r for r in old if r["arm"] == "abu"]
print("\n=== abundance control ===")
for tag, rows_ in (("OLD", abu_old), ("NEW", abu_new)):
    m = np.mean([r["spread_med_worst"] for r in rows_])
    s = np.std([r["spread_med_worst"] for r in rows_], ddof=1)
    print("  %s worst-family median spread %.4e +/- %.4e (n=%d)" % (tag, m, s, len(rows_)))
r_ = np.mean([r["spread_med_worst"] for r in abu_new]) / np.mean([r["spread_med_worst"] for r in abu_old])
eq = np.mean([r["spread_med_worst"] for r in new if r["arm"] == "equ"])
print("  ratio NEW/OLD %.1f ; still %.0fx below the equal arm (%.4e)"
      % (r_, eq / np.mean([r["spread_med_worst"] for r in abu_new]), eq))

print("\n=== per-generation stability, equal arm ===")
for g in (0, 1, 2):
    a = [r["fam_med"]["GLY[c]"] for r in new if r["arm"] == "equ" and r["gen"] == g]
    b = [r["fam_med"]["LEU[c]"] for r in new if r["arm"] == "equ" and r["gen"] == g]
    w = [r["spread_med_worst"] for r in new if r["arm"] == "equ" and r["gen"] == g]
    ao = [r["fam_med"]["GLY[c]"] for r in old if r["arm"] == "equ" and r["gen"] == g]
    print("  gen%d n=%d  GLY NEW %.4f (OLD %.4f)  LEU NEW %.4f  worst-family %.4f"
          % (g, len(a), np.mean(a), np.mean(ao), np.mean(b), np.mean(w)))

print("\n=== charged fraction per generation, all arms ===")
for g in (0, 1, 2):
    a = [r["charged_raw_mean"] for r in new if r["gen"] == g]
    b = [r["charged_raw_mean"] for r in old if r["gen"] == g]
    print("  gen%d NEW %.4f +/- %.4f  OLD %.4f +/- %.4f (n=%d each)"
          % (g, np.mean(a), np.std(a, ddof=1), np.mean(b), np.std(b, ddof=1), len(a)))
print("  NEW min/max over 27 cells: %.4f / %.4f ; any cell inside 0.71-0.86? %s"
      % (min(r["charged_raw_mean"] for r in new), max(r["charged_raw_mean"] for r in new),
         any(0.71 <= r["charged_raw_mean"] <= 0.86 for r in new)))
