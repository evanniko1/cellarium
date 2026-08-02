"""INDEPENDENT judge of the ROUTE1 stage-8 KMtf matrix.

Written from scratch against raw simOut; it does NOT import or reuse km3_analyze.py.
Reads only:
  * GrowthLimits/fraction_trna_charged, ppgpp_conc, rela_syn
  * BulkMolecules/counts  (raw charged/uncharged tRNA counts)
  * Mass/instantaneous_growth_rate, cellMass
  * Main/time
plus a JSON dump of simData primitives (aa_from_trna, tRNA names) made in the image.

Runs OUTSIDE docker with the cellarium venv python; TableReader is pure python.

Every cell that cannot be read is reported as MISSING or READ_FAIL, never as a zero.
"""

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, "C:/dev/wcEcoli")
from wholecell.io.tablereader import TableReader  # noqa: E402

OUT = "C:/dev/wcEcoli/out"
ARMS = [("fam", "family(control)"), ("abu", "isoacceptor+abundance"), ("equ", "isoacceptor+equal")]
SEEDS = [0, 1, 2]
GENS = [0, 1, 2]


def load_kb(path):
    with open(path) as fh:
        d = json.load(fh)
    d["aa_from_trna"] = np.asarray(d["aa_from_trna"])
    return d


def cell_dirs(prefix, arm, seed):
    run = os.path.join(OUT, "%s_%s_s%d" % (prefix, arm, seed))
    base = os.path.join(run, "wildtype_000000")
    out = []
    if not os.path.isdir(base):
        return [(g, None, "no wildtype_000000 under " + run) for g in GENS]
    seeddirs = sorted(d for d in os.listdir(base) if d.isdigit())
    if not seeddirs:
        return [(g, None, "no numeric seed dir under " + base) for g in GENS]
    sd = seeddirs[0]
    for g in GENS:
        so = os.path.join(base, sd, "generation_%06d" % g, "000000", "simOut")
        if os.path.isdir(so) and os.listdir(so):
            out.append((g, so, None))
        else:
            out.append((g, None, "no non-empty simOut at " + so))
    return out


def measure(so, kb, drop):
    rec = {}
    gl = TableReader(os.path.join(so, "GrowthLimits"))
    frac = np.atleast_2d(np.asarray(gl.readColumn("fraction_trna_charged"), dtype=float))
    rec["n_steps"] = int(frac.shape[0])
    rec["nan_frac"] = int(np.isnan(frac).sum())

    aft = kb["aa_from_trna"]
    names = kb["aa_names"]
    fam_med, fam_end, fam_max = {}, {}, {}
    for i in range(aft.shape[0]):
        cols = np.where(aft[i] > 0)[0]
        if cols.size < 2:
            continue
        sub = frac[:, cols]
        span = sub.max(axis=1) - sub.min(axis=1)
        fam_med[names[i]] = float(np.nanmedian(span))
        fam_max[names[i]] = float(np.nanmax(span))
        fam_end[names[i]] = float(sub[-1].max() - sub[-1].min())
    rec["fam_med"] = fam_med
    rec["fam_max"] = fam_max
    rec["fam_end"] = fam_end
    rec["spread_med_worst"] = max(fam_med.values())
    rec["spread_max_worst"] = max(fam_max.values())
    rec["spread_end_worst"] = max(fam_end.values())

    bm = TableReader(os.path.join(so, "BulkMolecules"))
    idx = {m: k for k, m in enumerate(bm.readAttribute("objectNames"))}
    counts = bm.readColumn("counts")
    ui = np.array([idx[m] for m in kb["uncharged_trna_names"]])
    ci = np.array([idx[m] for m in kb["charged_trna_names"]])
    u_all = counts[:, ui].astype(float)
    c_all = counts[:, ci].astype(float)
    lo = min(drop, max(counts.shape[0] - 1, 0))
    U = u_all[lo:].sum(axis=1)
    C = c_all[lo:].sum(axis=1)
    per_t = C / (U + C)
    rec["charged_raw_mean"] = float(np.nanmean(per_t))
    rec["charged_raw_nodrop"] = float(np.nanmean(c_all.sum(1) / (u_all.sum(1) + c_all.sum(1))))
    rec["charged_raw_last"] = float(per_t[-1])
    rec["uncharged_counts_mean"] = float(U.mean())
    rec["total_trna_counts_mean"] = float((U + C).mean())
    rec["charged_listener_mean"] = float(np.nanmean(frac[lo:]))
    # per-family uncharged FRACTION (for the linearity test in item 2)
    ufrac = {}
    for i in range(aft.shape[0]):
        cols = np.where(aft[i] > 0)[0]
        if cols.size < 2:
            continue
        uu = u_all[lo:][:, cols].sum(1)
        cc = c_all[lo:][:, cols].sum(1)
        ufrac[names[i]] = float(np.nanmean(uu / (uu + cc)))
    rec["fam_uncharged_frac"] = ufrac

    ppgpp = np.asarray(gl.readColumn("ppgpp_conc"), dtype=float)
    rela = np.atleast_2d(np.asarray(gl.readColumn("rela_syn"), dtype=float))
    rec["ppgpp_mean"] = float(np.nanmean(ppgpp))
    rec["ppgpp_last"] = float(ppgpp[-1])
    rec["ppgpp_min"] = float(np.nanmin(ppgpp))
    rec["ppgpp_max"] = float(np.nanmax(ppgpp))
    rec["nan_ppgpp"] = int(np.isnan(ppgpp).sum())
    rec["rela_total_mean"] = float(np.nanmean(rela.sum(axis=1)))
    rec["nan_rela"] = int(np.isnan(rela).sum())
    for col in ("spot_syn", "spot_deg", "spot_deg_inhibited"):
        try:
            v = np.asarray(gl.readColumn(col), dtype=float)
            v = v.sum(axis=1) if v.ndim > 1 else v
            rec[col + "_mean"] = float(np.nanmean(v))
        except Exception as exc:
            rec[col + "_err"] = "{}: {}".format(type(exc).__name__, exc)

    mass = TableReader(os.path.join(so, "Mass"))
    igr = np.asarray(mass.readColumn("instantaneous_growth_rate"), dtype=float)
    cell = np.asarray(mass.readColumn("cellMass"), dtype=float)
    rec["nan_igr_after_row0"] = int(np.isnan(igr[1:]).sum())
    rec["nan_cellMass"] = int(np.isnan(cell).sum())
    g = float(np.nanmean(igr))
    rec["growth_rate_mean_per_s"] = g
    rec["doubling_min"] = float(math.log(2) / g / 60.0) if g > 0 else float("nan")
    rec["mass_ratio"] = float(cell[-1] / cell[0]) if cell[0] else float("nan")

    t = np.asarray(TableReader(os.path.join(so, "Main")).readColumn("time"), dtype=float)
    rec["duration_min"] = float((t[-1] - t[0]) / 60.0)
    rec["divided"] = bool(os.path.isfile(os.path.join(so, "Daughter1_inherited_state.cPickle")))
    rec["nan_any"] = bool(rec["nan_frac"] or rec["nan_ppgpp"] or rec["nan_rela"]
                          or rec["nan_igr_after_row0"] or rec["nan_cellMass"])
    return rec


def collect(prefix, kb, drop):
    rows = []
    for arm, label in ARMS:
        for seed in SEEDS:
            for g, so, why in cell_dirs(prefix, arm, seed):
                r = {"prefix": prefix, "arm": arm, "label": label, "seed": seed, "gen": g}
                if so is None:
                    r["status"] = "MISSING"
                    r["why"] = why
                else:
                    r["simOut"] = so
                    try:
                        r.update(measure(so, kb, drop))
                        r["status"] = "OK"
                    except Exception as exc:
                        r["status"] = "READ_FAIL"
                        r["why"] = "{}: {}".format(type(exc).__name__, exc)
                rows.append(r)
    return rows


def ms(v):
    v = np.asarray(v, dtype=float)
    return float(v.mean()), float(v.std(ddof=1)) if v.size > 1 else float("nan")


def ttest(d):
    d = np.asarray(d, dtype=float)
    n = d.size
    m = d.mean()
    s = d.std(ddof=1)
    return m, s, (m / (s / math.sqrt(n)) if s > 0 else float("inf")), n


def main():
    scratch = sys.argv[1]
    drop = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    kbn = load_kb(os.path.join(scratch, "judge_kb_new.json"))
    kbo = load_kb(os.path.join(scratch, "judge_kb_old.json"))
    print("KB new: %d aa, %d trna; multi-member families %d"
          % (len(kbn["aa_names"]), len(kbn["uncharged_trna_names"]),
             int((kbn["aa_from_trna"].sum(1) > 1).sum())))
    same = (kbn["aa_from_trna"] == kbo["aa_from_trna"]).all()
    print("aa_from_trna identical old vs new: %s" % same)
    if "trna_kms" in kbn and "trna_kms" in kbo:
        a = np.asarray(kbn["trna_kms"], dtype=float)
        b = np.asarray(kbo["trna_kms"], dtype=float)
        print("trna_kms  new median %.4f min %.4f max %.4f | old median %.4f min %.4f max %.4f | "
              "max|diff| %.4f  ratio(median) %.3f"
              % (np.median(a), a.min(), a.max(), np.median(b), b.min(), b.max(),
                 np.abs(a - b).max(), np.median(a) / np.median(b)))

    new = collect("km3", kbn, drop)
    old = collect("mx", kbo, drop)
    with open(os.path.join(scratch, "judge_rows.json"), "w") as fh:
        json.dump({"new": new, "old": old}, fh)

    for tag, rows in (("NEW km3", new), ("OLD mx", old)):
        bad = [r for r in rows if r["status"] != "OK"]
        print("%s: %d/%d OK; not-OK: %s" % (tag, len(rows) - len(bad), len(rows),
                                            [(r["arm"], r["seed"], r["gen"], r["status"]) for r in bad] or "none"))
    ok_new = [r for r in new if r["status"] == "OK"]
    ok_old = [r for r in old if r["status"] == "OK"]
    print("NaN cells NEW %d ; undivided NEW %d" % (sum(r["nan_any"] for r in ok_new),
                                                   sum(not r["divided"] for r in ok_new)))
    print("NaN cells OLD %d ; undivided OLD %d" % (sum(r["nan_any"] for r in ok_old),
                                                   sum(not r["divided"] for r in ok_old)))

    print("\n=== 1. AGGREGATE CHARGED FRACTION (raw BulkMolecules) ===")
    for tag, rows in (("NEW", ok_new), ("OLD", ok_old)):
        m, s = ms([r["charged_raw_mean"] for r in rows])
        m0, s0 = ms([r["charged_raw_nodrop"] for r in rows])
        ml, sl = ms([r["charged_listener_mean"] for r in rows])
        mu, su = ms([r["uncharged_counts_mean"] for r in rows])
        print("%s N=%d  raw(drop=%d) %.4f +/- %.4f | raw(no drop) %.4f +/- %.4f | listener %.4f +/- %.4f"
              % (tag, len(rows), drop, m, s, m0, s0, ml, sl))
        print("      uncharged counts %.0f +/- %.0f" % (mu, su))
    key = lambda r: (r["arm"], r["seed"], r["gen"])
    dn = {key(r): r for r in ok_new}
    do = {key(r): r for r in ok_old}
    common = sorted(set(dn) & set(do))
    print("paired cells: %d" % len(common))
    for field in ("charged_raw_mean", "uncharged_counts_mean", "ppgpp_mean", "rela_total_mean",
                  "doubling_min", "duration_min", "mass_ratio"):
        d = [dn[k][field] - do[k][field] for k in common]
        m, s, t, n = ttest(d)
        print("  delta %-22s %+10.4f  sd %9.4f  t %+7.2f  n %d" % (field, m, s, t, n))
    tgt = 0.788
    m_new, _ = ms([r["charged_raw_mean"] for r in ok_new])
    m_old, _ = ms([r["charged_raw_mean"] for r in ok_old])
    print("  gap closed toward %.3f : (%.4f-%.4f)/(%.4f-%.4f) = %.1f%%"
          % (tgt, m_old, m_new, m_old, tgt, 100.0 * (m_old - m_new) / (m_old - tgt)))
    for g in GENS:
        a = [r["charged_raw_mean"] for r in ok_new if r["gen"] == g]
        b = [r["charged_raw_mean"] for r in ok_old if r["gen"] == g]
        print("  gen%d charged NEW %.4f (n=%d)  OLD %.4f (n=%d)"
              % (g, np.mean(a), len(a), np.mean(b), len(b)))

    print("\n=== 2. PER-FAMILY SPREAD, isoacceptor+equal arm ===")
    ref = {"GLY[c]": (0.348, 0.032), "LEU[c]": (0.248, 0.014)}
    eq_new = [r for r in ok_new if r["arm"] == "equ"]
    eq_old = [r for r in ok_old if r["arm"] == "equ"]
    fams = sorted(eq_new[0]["fam_med"], key=lambda f: -np.mean([r["fam_med"][f] for r in eq_new]))
    print("%-22s %18s %18s %7s %10s %10s" % ("family", "OLD med", "NEW med", "ratio", "unch_frac_old", "unch_frac_new"))
    for f in fams:
        on, os_ = ms([r["fam_med"][f] for r in eq_old])
        nn, ns = ms([r["fam_med"][f] for r in eq_new])
        uo, _ = ms([r["fam_uncharged_frac"][f] for r in eq_old])
        un, _ = ms([r["fam_uncharged_frac"][f] for r in eq_new])
        extra = ""
        if f in ref:
            rm, rs = ref[f]
            z_arm = (nn - rm) / ns if ns > 0 else float("nan")
            z_ref = (nn - rm) / rs
            extra = "   REF %.3f+/-%.3f  z(arm sd)=%+.2f  z(ref sd)=%+.2f  ratio_to_ref=%.2f" % (
                rm, rs, z_arm, z_ref, nn / rm)
        print("%-22s %8.4f+/-%.4f %8.4f+/-%.4f %7.2f %10.4f %10.4f%s"
              % (f, on, os_, nn, ns, (nn / on if on > 0 else float("inf")), uo, un, extra))
    # linearity check: spread ratio vs uncharged-fraction ratio, per family
    print("\n  LINEARITY: does spread scale with the uncharged fraction?")
    xs, ys, labs = [], [], []
    for f in fams:
        on, _ = ms([r["fam_med"][f] for r in eq_old])
        nn, _ = ms([r["fam_med"][f] for r in eq_new])
        uo, _ = ms([r["fam_uncharged_frac"][f] for r in eq_old])
        un, _ = ms([r["fam_uncharged_frac"][f] for r in eq_new])
        if on > 0 and uo > 0:
            xs.append(un / uo)
            ys.append(nn / on)
            labs.append(f)
    xs, ys = np.asarray(xs), np.asarray(ys)
    print("  uncharged-fraction ratio: median %.2f  range %.2f-%.2f (n=%d families)"
          % (np.median(xs), xs.min(), xs.max(), xs.size))
    print("  spread ratio            : median %.2f  range %.2f-%.2f" % (np.median(ys), ys.min(), ys.max()))
    if xs.size > 2:
        r = np.corrcoef(xs, ys)[0, 1]
        print("  Pearson r(uncharged ratio, spread ratio) = %.3f  n=%d" % (r, xs.size))
    agg_u_new, _ = ms([r["uncharged_counts_mean"] / r["total_trna_counts_mean"] for r in ok_new])
    agg_u_old, _ = ms([r["uncharged_counts_mean"] / r["total_trna_counts_mean"] for r in ok_old])
    print("  aggregate uncharged fraction OLD %.4f -> NEW %.4f  ratio %.2f"
          % (agg_u_old, agg_u_new, agg_u_new / agg_u_old))
    for tag, rows in (("OLD", eq_old), ("NEW", eq_new)):
        m, s = ms([r["spread_med_worst"] for r in rows])
        me, se = ms([r["spread_end_worst"] for r in rows])
        print("  %s equal-arm worst-family median spread %.4e +/- %.4e ; end %.4e +/- %.4e (n=%d)"
              % (tag, m, s, me, se, len(rows)))

    print("\n=== 3. CONTROLS ===")
    for arm in ("fam", "abu"):
        for tag, rows in (("OLD", ok_old), ("NEW", ok_new)):
            sel = [r for r in rows if r["arm"] == arm]
            allmed = np.array([v for r in sel for v in r["fam_med"].values()])
            allmax = np.array([v for r in sel for v in r["fam_max"].values()])
            allend = np.array([v for r in sel for v in r["fam_end"].values()])
            print("  %s %-4s n_cells=%d  every-family med max=%.3e | max-over-steps max=%.3e | end max=%.3e"
                  % (tag, arm, len(sel), allmed.max(), allmax.max(), allend.max()))
            print("       exactly-zero family-medians: %d / %d" % (int((allmed == 0).sum()), allmed.size))

    print("\n=== 4. ppGpp ===")
    for tag, rows in (("OLD", ok_old), ("NEW", ok_new)):
        m, s = ms([r["ppgpp_mean"] for r in rows])
        lo = min(r["ppgpp_min"] for r in rows)
        hi = max(r["ppgpp_max"] for r in rows)
        rm, rs = ms([r["rela_total_mean"] for r in rows])
        print("  %s ppgpp_conc %.2f +/- %.2f uM  (per-cell means %.2f - %.2f; instantaneous %.2f - %.2f)"
              % (tag, m, s, min(r["ppgpp_mean"] for r in rows), max(r["ppgpp_mean"] for r in rows), lo, hi))
        print("     rela_syn total %.4f +/- %.4f" % (rm, rs))
        inside = [r for r in rows if 25.0 <= r["ppgpp_mean"] <= 67.0]
        print("     cells with mean ppgpp in 25-67 uM: %d / %d" % (len(inside), len(rows)))
    for tag, rows in (("OLD", ok_old), ("NEW", ok_new)):
        keys = [k for k in ("spot_syn_mean", "spot_deg_mean", "spot_deg_inhibited_mean") if k in rows[0]]
        if keys:
            print("  %s %s" % (tag, "  ".join("%s %.4f" % (k, np.mean([r[k] for r in rows])) for k in keys)))

    print("\n=== 5. GROWTH, with the degenerate abundance arm as the noise control ===")
    for field in ("doubling_min", "duration_min", "mass_ratio", "growth_rate_mean_per_s"):
        print("  %s:" % field)
        for arm, label in ARMS:
            ks = [k for k in common if k[0] == arm]
            d = [dn[k][field] - do[k][field] for k in ks]
            m, s, t, n = ttest(d)
            print("    %-22s delta %+9.4f  sd %8.4f  t %+6.2f  n %d" % (label, m, s, t, n))
        ks = [k for k in common if k[0] == "abu"]
        noise = abs(np.mean([dn[k][field] - do[k][field] for k in ks]))
        for arm, label in ARMS:
            if arm == "abu":
                continue
            ks = [k for k in common if k[0] == arm]
            m = np.mean([dn[k][field] - do[k][field] for k in ks])
            print("    %-22s |delta| %.4f vs abundance-noise %.4f -> %s"
                  % (label, abs(m), noise, "LARGER" if abs(m) > noise else "within noise"))

    print("\n  gen0 timestep-count invariance check:")
    for arm, _ in ARMS:
        for s_ in SEEDS:
            k = (arm, s_, 0)
            if k in dn and k in do:
                print("    %s s%d gen0 steps NEW %d OLD %d  same=%s ; charged NEW %.4f OLD %.4f"
                      % (arm, s_, dn[k]["n_steps"], do[k]["n_steps"],
                         dn[k]["n_steps"] == do[k]["n_steps"],
                         dn[k]["charged_raw_mean"], do[k]["charged_raw_mean"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
