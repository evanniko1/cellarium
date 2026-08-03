"""A1 -- REALISED per-family charging under a uniform aaRS capacity throttle. Runs INSIDE the container.

    python /wcEcoli/out/_a1_readout.py <ctl_glob> <trt_glob>

Everything family-resolved is derived from RAW BulkMolecules/counts, not from the
GrowthLimits convenience columns:

  charged fraction  f_a = sum_{i in a} C_i / sum_{i in a} (C_i + U_i)
                    C_i, U_i = raw counts of transcription.charged_trna_names /
                    transcription.uncharged_trna_names (reconstruction/ecoli/dataclasses/
                    process/transcription.py:1283-1285), grouped by aa_from_trna.
  concentrations    conc = counts * 1e6 / (N_A * V),  V = Mass/cellVolume  -> uM
  rho_a             u_a / (KMtf_a + u_a)          -- the ROUTE1-77/79 saturation term
  theta_a           A_a / (KMaa_a + A_a)
  v_a               kS * E_a * theta_a * rho_a     (uM/s), the charging flux the rate law carries

The listener columns are read too, and the two are cross-checked, so a disagreement is
visible rather than silently averaged away.

Scalars traced for the feedback path: GrowthLimits/ppgpp_conc, RibosomeData/
effectiveElongationRate, and the rate-law v_rib
    D     = 1 + sum_a f_a * (krta/c_a + u_a/c_a * krta/krtf)
    v_rib = max_elong_rate * ribosome_conc / D
with max_elong_rate = get_ribosome_elongation_rate_by_ppgpp(ppgpp_conc, basal) under
ppgpp_regulation (polypeptide_elongation.py:1046-1055, :2274-2276).
"""
import glob
import json
import os
import pickle
import sys

import numpy as np

from wholecell.io.tablereader import TableReader
from wholecell.utils import units

CONC = units.umol / units.L


def collect(sim, sd, aa_from_trna, ct_idx, ut_idx, KMtf, KMaa, kS, nav, krta, krtf,
            basal_rate, rate_by_ppgpp, fams):
    bm = TableReader(os.path.join(sim, "BulkMolecules"))
    mass = TableReader(os.path.join(sim, "Mass"))
    gl = TableReader(os.path.join(sim, "GrowthLimits"))
    rd = TableReader(os.path.join(sim, "RibosomeData"))
    main = TableReader(os.path.join(sim, "Main"))

    t = main.readColumn("time")
    V = mass.readColumn("cellVolume")          # fL
    C = bm.readColumn("counts", ct_idx).astype(float)   # (T, 85 or 86)
    U = bm.readColumn("counts", ut_idx).astype(float)
    # counts -> uM
    c2m = 1e6 / (nav * (V * 1e-15))            # uM per count
    Cc = C * c2m[:, None]
    Uc = U * c2m[:, None]
    # group to 21 amino-acid families
    Cf = Cc @ aa_from_trna.T                   # (T, 21)
    Uf = Uc @ aa_from_trna.T
    Cn = C @ aa_from_trna.T                    # raw counts per family
    Un = U @ aa_from_trna.T

    A = gl.readColumn("aa_conc")               # (T,21) uM
    E = gl.readColumn("synthetase_conc")
    f = gl.readColumn("fraction_aa_to_elongate")
    rib = gl.readColumn("ribosome_conc")
    ppgpp = gl.readColumn("ppgpp_conc")
    eer = rd.readColumn("effectiveElongationRate")
    fc_listener = gl.readColumn("fraction_trna_charged")   # per tRNA species

    sl = slice(2, len(t))                       # drop init transient, as rho_decomp.py:20 does
    out = {}
    out["n_steps"] = int(len(t) - 2)
    out["t_end"] = float(t[-1])

    with np.errstate(divide="ignore", invalid="ignore"):
        f_raw = Cn / np.where((Cn + Un) > 0, Cn + Un, np.nan)
        rho = Uf / (KMtf + Uf)
        theta = A / (KMaa + A)
    out["f_raw"] = np.nanmedian(f_raw[sl], 0)          # (21,)
    out["rho"] = np.nanmedian(rho[sl], 0)
    out["theta"] = np.nanmedian(theta[sl], 0)
    out["T"] = np.nanmedian((Cf + Uf)[sl], 0)
    out["u"] = np.nanmedian(Uf[sl], 0)
    out["E"] = np.nanmedian(E[sl], 0)
    out["v"] = np.nanmedian((kS * E * theta * rho)[sl], 0)
    out["counts_T"] = np.nanmedian((Cn + Un)[sl], 0)
    # pool-weighted charged fraction from raw counts, over the 20 charging families
    tot_c = Cn[sl][:, fams].sum(1)
    tot_t = (Cn + Un)[sl][:, fams].sum(1)
    out["pool_raw"] = float(np.median(tot_c / tot_t))

    # listener cross-check: aa_from_trna-weighted mean of fraction_trna_charged
    fcl = np.zeros((fc_listener.shape[0], aa_from_trna.shape[0]))
    for a in range(aa_from_trna.shape[0]):
        idx = np.flatnonzero(aa_from_trna[a] > 0)
        if idx.size:
            fcl[:, a] = fc_listener[:, idx].mean(1)
    out["f_listener"] = np.nanmedian(fcl[sl], 0)

    # ---- feedback-path scalars
    out["ppgpp"] = float(np.median(ppgpp[sl]))
    out["ppgpp_min"] = float(np.min(ppgpp[sl]))
    out["ppgpp_max"] = float(np.max(ppgpp[sl]))
    out["eer"] = float(np.median(eer[sl]))
    out["eer_min"] = float(np.min(eer[sl]))
    out["rib"] = float(np.median(rib[sl]))
    out["V"] = float(np.median(V[sl]))

    mer = np.array([float(rate_by_ppgpp(p * (units.umol / units.L), basal_rate)
                          .asNumber(units.aa / units.s)) for p in ppgpp])
    with np.errstate(divide="ignore", invalid="ignore"):
        D = 1.0 + np.nansum(f * (krta / Cf + Uf / Cf * krta / krtf), axis=1)
        v_rib = mer * rib / D
    out["max_elong"] = float(np.median(mer[sl]))
    out["D"] = float(np.median(D[sl]))
    out["v_rib"] = float(np.median(v_rib[sl]))
    out["v_rib_min"] = float(np.nanmin(v_rib[sl]))
    out["n_v_rib_zero"] = int(np.sum(v_rib[sl] == 0))
    out["n_v_rib_nonfinite"] = int(np.sum(~np.isfinite(v_rib[sl])))
    out["n_eer_zero"] = int(np.sum(eer[sl] == 0))
    # arrest check: did any family's charged COUNT hit zero?
    out["n_zero_charged_steps"] = int(np.sum(Cn[sl][:, fams] == 0))
    return out


def main(argv):
    # km_parca, NOT kinetic_parca. The two differ (90404883 vs 90389857 bytes) and the difference
    # is trna_kms: km_parca carries the KMtf fix (ASN/GLY/TYR 1.0 -> 10.0, PRO 1.0 -> 14.14),
    # kinetic_parca still has the 1 uM defaults. Every ROUTE1-77/79 number reproduces only against
    # km_parca -- median KMtf/T = 0.1250 and median rho/(1-rho) = 0.1729 come out exactly.
    kb = "/wcEcoli/out/km_parca/kb/simData.cPickle"
    if not os.path.exists(kb):
        print("KB NOT ON DISK: %s -- could not establish anything" % kb)
        return 2
    sd = pickle.load(open(kb, "rb"))
    tr = sd.process.transcription
    aas = list(sd.molecule_groups.amino_acids)
    names = [a[:-3] for a in aas]
    SEL = aas.index("L-SELENOCYSTEINE[c]")
    fams = [i for i in range(len(aas)) if i != SEL]

    kS_base = float(sd.constants.synthetase_charging_rate.asNumber(1 / units.s))
    KMtf = tr.trna_kms.asNumber(CONC)
    KMaa = tr.aa_kms.asNumber(CONC)
    krta = sd.constants.Kdissociation_charged_trna_ribosome.asNumber(CONC)
    krtf = sd.constants.Kdissociation_uncharged_trna_ribosome.asNumber(CONC)
    nav = sd.constants.n_avogadro.asNumber(1 / units.mol)
    # polypeptide_elongation.py:893 -- basal_elongation_rate is a bare float (asNumber), and
    # :1052 passes that float as max_rate. Passing the Unum instead squares the units.
    basal_rate = float(sd.constants.ribosome_elongation_rate_basal.asNumber(units.aa / units.s))
    rate_by_ppgpp = sd.growth_rate_parameters.get_ribosome_elongation_rate_by_ppgpp
    A = np.asarray(tr.aa_from_trna, dtype=float)      # (21, 86)

    bm_names = None
    arms = {}
    for label, pat in [("ctl", argv[0]), ("trt", argv[1])]:
        sims = sorted(glob.glob(pat))
        if not sims:
            print("%s: NO simOut MATCHED %r -- could not establish" % (label, pat))
            return 2
        recs = []
        for sim in sims:
            bm = TableReader(os.path.join(sim, "BulkMolecules"))
            obj = list(bm.readAttribute("objectNames"))
            ct_idx = np.array([obj.index(n) for n in tr.charged_trna_names])
            ut_idx = np.array([obj.index(n) for n in tr.uncharged_trna_names])
            kS = kS_base / (2.2 if label == "trt" else 1.0)
            r = collect(sim, sd, A, ct_idx, ut_idx, KMtf, KMaa, kS, nav, krta, krtf,
                        basal_rate, rate_by_ppgpp, fams)
            r["sim"] = sim
            recs.append(r)
            print("%s  %s   steps=%d  t_end=%.0fs" % (label, sim, r["n_steps"], r["t_end"]))
        arms[label] = recs

    print("")
    print("kS control = %.6g /s ; kS throttled = %.6g /s (divisor 2.2)"
          % (kS_base, kS_base / 2.2))
    print("N control run-generations = %d ; N throttled = %d"
          % (len(arms["ctl"]), len(arms["trt"])))
    print("")

    def med(label, key):
        return np.median(np.array([r[key] for r in arms[label]]), axis=0)

    # ---------- scalars
    print("=== FEEDBACK-PATH SCALARS (median over timesteps, then median over the 3 seeds) ===")
    hdr = "%-22s %14s %14s %10s" % ("quantity", "control(N=3)", "throttle(N=3)", "ratio")
    print(hdr); print("-" * len(hdr))
    for key, nm in [("ppgpp", "ppgpp_conc (uM)"), ("eer", "effElongRate (aa/s)"),
                    ("max_elong", "max_elong_rate (aa/s)"), ("v_rib", "v_rib ratelaw (uM/s)"),
                    ("D", "ribosome denom D"), ("rib", "ribosome_conc (uM)"),
                    ("V", "cellVolume (fL)"), ("pool_raw", "pool charged (raw)")]:
        c = float(np.median([r[key] for r in arms["ctl"]]))
        t = float(np.median([r[key] for r in arms["trt"]]))
        print("%-22s %14.5g %14.5g %10.4f" % (nm, c, t, (t / c) if c else float("nan")))
    print("")
    for label in ("ctl", "trt"):
        print("%s per-seed: ppgpp=%s  effElong=%s  v_rib_min=%s  n(v_rib==0)=%s  "
              "n(nonfinite)=%s  n(effElong==0)=%s  n(zero charged count)=%s  steps=%s"
              % (label,
                 ["%.1f" % r["ppgpp"] for r in arms[label]],
                 ["%.2f" % r["eer"] for r in arms[label]],
                 ["%.3g" % r["v_rib_min"] for r in arms[label]],
                 [r["n_v_rib_zero"] for r in arms[label]],
                 [r["n_v_rib_nonfinite"] for r in arms[label]],
                 [r["n_eer_zero"] for r in arms[label]],
                 [r["n_zero_charged_steps"] for r in arms[label]],
                 [r["n_steps"] for r in arms[label]]))
    print("")

    # ---------- per-family table
    fc = med("ctl", "f_raw"); ft = med("trt", "f_raw")
    rc = med("ctl", "rho"); rt = med("trt", "rho")
    thc = med("ctl", "theta"); tht = med("trt", "theta")
    Tc = med("ctl", "T"); Tt = med("trt", "T")
    Ec = med("ctl", "E"); Et = med("trt", "E")
    vc = med("ctl", "v"); vt = med("trt", "v")
    flc = med("ctl", "f_listener"); flt = med("trt", "f_listener")

    # static prediction, recomputed on THIS control's own rho/T/KMtf (analyze5.py:63-72 arithmetic)
    r2 = np.minimum(rc * 2.2, 1 - 1e-6)
    u2 = np.minimum(KMtf * r2 / (1 - r2), Tc)
    fpred = 1 - u2 / Tc

    print("=== PER-FAMILY REALISED CHARGED FRACTION (raw BulkMolecules counts), ALL 20 FAMILIES ===")
    print("f_ctl / f_trt: median over timesteps then over 3 seeds. f_pred: the ROUTE1-79 static")
    print("substitution recomputed on this control's own rho, T, KMtf at divisor 2.20.")
    hdr = ("%-16s %8s %8s %8s %9s %9s %8s %8s %8s %8s"
           % ("family", "f_ctl", "f_trt", "f_pred", "trt-pred", "trt-ctl", "rho_ctl",
              "rho_trt", "rho_x", "theta_x"))
    print(hdr); print("-" * len(hdr))
    order = sorted(fams, key=lambda i: ft[i])
    for i in order:
        print("%-16s %8.4f %8.4f %8.4f %+9.4f %+9.4f %8.4f %8.4f %8.3f %8.3f"
              % (names[i], fc[i], ft[i], fpred[i], ft[i] - fpred[i], ft[i] - fc[i],
                 rc[i], rt[i], rt[i] / rc[i] if rc[i] else float("nan"),
                 tht[i] / thc[i] if thc[i] else float("nan")))
    print("")
    print("pool-weighted charged (raw counts): control %.4f -> throttled %.4f ; static prediction %.4f"
          % (float(np.median([r["pool_raw"] for r in arms["ctl"]])),
             float(np.median([r["pool_raw"] for r in arms["trt"]])),
             1 - u2[fams].sum() / Tc[fams].sum()))
    print("listener cross-check (aa_from_trna mean of fraction_trna_charged): "
          "max |raw - listener| over 20 families = ctl %.2e, trt %.2e"
          % (np.nanmax(np.abs(fc[fams] - flc[fams])), np.nanmax(np.abs(ft[fams] - flt[fams]))))
    print("")

    # ---------- did rho move?
    print("=== DID rho MOVE? (the bound assumed rho scales by exactly the divisor, 2.200) ===")
    ratio = rt[fams] / rc[fams]
    print("rho_trt/rho_ctl over 20 families: min %.3f (%s)  median %.3f  max %.3f (%s)"
          % (ratio.min(), names[fams[int(ratio.argmin())]], float(np.median(ratio)),
             ratio.max(), names[fams[int(ratio.argmax())]]))
    print("families where rho rose by LESS than the divisor (demand fell): %d of 20"
          % int(np.sum(ratio < 2.2)))
    print("families where rho FELL: %d of 20 : %s"
          % (int(np.sum(ratio < 1.0)),
             ", ".join("%s=%.3f" % (names[fams[k]], ratio[k])
                       for k in np.where(ratio < 1.0)[0])))
    print("")
    print("max realised rho: control %.4f (%s) -> throttled %.4f (%s)"
          % (rc[fams].max(), names[fams[int(rc[fams].argmax())]],
             rt[fams].max(), names[fams[int(rt[fams].argmax())]]))
    print("implied max uniform divisor before a family loses all charge, 1/max(rho):"
          " control %.3f -> throttled(measured, already at 2.2) %.3f"
          % (1 / rc[fams].max(), 1 / rt[fams].max()))
    print("")
    print("g_a = (KMtf/T)*rho/(1-rho), the ROUTE1-77 two-factor identity, per family:")
    hdr = ("%-16s %9s %9s %9s %9s %9s %9s"
           % ("family", "KMtf/T_c", "KMtf/T_t", "r/(1-r)_c", "r/(1-r)_t", "g_ctl", "g_trt"))
    print(hdr); print("-" * len(hdr))
    for i in order:
        gc = (KMtf[i] / Tc[i]) * rc[i] / (1 - rc[i])
        gt = (KMtf[i] / Tt[i]) * rt[i] / (1 - rt[i])
        print("%-16s %9.4f %9.4f %9.4f %9.4f %9.4f %9.4f"
              % (names[i], KMtf[i] / Tc[i], KMtf[i] / Tt[i],
                 rc[i] / (1 - rc[i]), rt[i] / (1 - rt[i]), gc, gt))
    print("")
    print("=== FLUX / CAPACITY per family (uM/s) ===")
    hdr = "%-16s %10s %10s %8s %10s %10s %8s %8s" % (
        "family", "v_ctl", "v_trt", "v_x", "E_ctl", "E_trt", "E_x", "T_x")
    print(hdr); print("-" * len(hdr))
    for i in order:
        print("%-16s %10.4f %10.4f %8.3f %10.4f %10.4f %8.3f %8.3f"
              % (names[i], vc[i], vt[i], vt[i] / vc[i] if vc[i] else float("nan"),
                 Ec[i], Et[i], Et[i] / Ec[i] if Ec[i] else float("nan"),
                 Tt[i] / Tc[i] if Tc[i] else float("nan")))

    dump = dict(names=names, fams=fams,
                f_ctl=fc.tolist(), f_trt=ft.tolist(), f_pred=fpred.tolist(),
                rho_ctl=rc.tolist(), rho_trt=rt.tolist(),
                theta_ctl=thc.tolist(), theta_trt=tht.tolist(),
                T_ctl=Tc.tolist(), T_trt=Tt.tolist(),
                E_ctl=Ec.tolist(), E_trt=Et.tolist(),
                v_ctl=vc.tolist(), v_trt=vt.tolist(), KMtf=KMtf.tolist(),
                scalars={k: {lab: [r[k] for r in arms[lab]] for lab in ("ctl", "trt")}
                         for k in ("ppgpp", "eer", "max_elong", "v_rib", "D", "rib", "V",
                                   "pool_raw", "n_v_rib_zero", "n_v_rib_nonfinite",
                                   "n_eer_zero", "n_zero_charged_steps", "n_steps", "t_end")})
    with open("/wcEcoli/out/_a1_readout.json", "w") as fh:
        json.dump(dump, fh, indent=1)
    print("")
    print("wrote /wcEcoli/out/_a1_readout.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
