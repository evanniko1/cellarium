"""A2 -- re-verify the aaRS kcat inequality PER FAMILY, from source. Runs INSIDE the container.

    python /wcEcoli/out/_a2_kcat_check.py

For each of the 20 charging amino-acid families this reports:

  kcat_cur   the repo's OWN curated MAX 37C kcat, straight from
             reconstruction/ecoli/flat/trna_charging_kinetics_curated.tsv via
             sim_data.relation.synthetase_to_max_curated_k_cats   (1/s)

  k_req_flux the turnover the model's own synthetase pool must sustain to carry the flux the
             model actually carries:
                 k_req = v_a / E_a,
                 v_a  = GrowthLimits/aasUsed[a] * counts_to_molar / dt      (uM/s)  MEASURED
                 E_a  = GrowthLimits/synthetase_conc[a]                     (uM)    MEASURED
             aasUsed is the realized per-amino-acid incorporation, so at the timestep's steady
             state this IS the charging flux. No rate law is used.

  k_req_rho  the same quantity read off the rate law instead of the outcome:
                 v_a = kS * E_a * rho_a, so k_req = kS * rho_a, with
                 rho_a = [u/KMtf / (1+u/KMtf)] * [a/KMaa / (1+a/KMaa)]
             (the dcdt_jit denominator factorises exactly:
              1 + u/KMtf + a/KMaa + u*a/(KMtf*KMaa) == (1+u/KMtf)(1+a/KMaa),
              polypeptide_elongation.py:2123-2124). Evaluated on the START-OF-STEP listener
             state, which is the ODE's initial condition, NOT its steady state -- so this is the
             weaker of the two estimators and is reported only as a cross-check.

Statistics: median over the timesteps of a generation, then median (and min/max) over the
27 run-generations. N is printed for everything.
"""
import glob
import os
import pickle
import sys

import numpy as np

from wholecell.io.tablereader import TableReader
from wholecell.utils import units

CONC = units.umol / units.L


def main(argv):
    pattern = argv[0] if argv else "/wcEcoli/out/mx_*/*/*/generation_*/*/simOut"
    sos = sorted(glob.glob(pattern))
    if not sos:
        print("NO simOut MATCHED %r -- could not establish anything" % pattern)
        return 2
    print("simOut dirs matched: %d" % len(sos))

    kb = "/wcEcoli/out/mx_fam_s0/wildtype_000000/kb/simData_Modified.cPickle"
    if not os.path.exists(kb):
        print("KB NOT ON DISK: %s -- could not establish" % kb)
        return 2
    sd = pickle.load(open(kb, "rb"))
    tr = sd.process.transcription
    rel = sd.relation
    aas = list(sd.molecule_groups.amino_acids)
    n_aa = len(aas)

    kS = sd.constants.synthetase_charging_rate.asNumber(1 / units.s)
    KMaa = tr.aa_kms.asNumber(CONC)
    KMtf = tr.trna_kms.asNumber(CONC)
    nav = sd.constants.n_avogadro.asNumber(1 / units.mol)
    dens = sd.constants.cell_density.asNumber(units.fg / units.L)

    a2s = rel.amino_acid_to_synthetase
    cur = rel.synthetase_to_max_curated_k_cats
    afs = np.asarray(tr.aa_from_synthetase)          # (21, n_synth)
    snames = list(tr.synthetase_names)

    SEL = aas.index("L-SELENOCYSTEINE[c]")
    fams = [i for i in range(n_aa) if i != SEL]

    print("kS = %.6g /s   (sim_data.constants.synthetase_charging_rate)" % kS)
    print("n amino acids = %d, selenocysteine index %d excluded -> %d families"
          % (n_aa, SEL, len(fams)))
    print("curated kcat entries = %d" % len(cur))

    # per-run-generation medians
    kflux = []      # (n_runs, 21)
    krho = []       # (n_runs, 21)
    Es = []
    labels = []
    nsteps = []
    for so in sos:
        try:
            gl = TableReader(os.path.join(so, "GrowthLimits"))
            E = gl.readColumn("synthetase_conc")             # uM, (T,21)
            u = gl.readColumn("uncharged_trna_conc")
            a = gl.readColumn("aa_conc")
            used = gl.readColumn("aasUsed").astype(float)    # counts, (T,21)
            cm = TableReader(os.path.join(so, "Mass")).readColumn("cellMass")
            t = TableReader(os.path.join(so, "Main")).readColumn("time")
        except Exception as e:                               # noqa: BLE001
            print("READ FAILED %s: %r -- could not establish" % (so, e))
            continue
        dt = np.diff(t, prepend=t[0] - (t[1] - t[0]))
        c2m = 1e6 / (nav * (cm / dens))                      # uM per count
        v = used * c2m[:, None] / dt[:, None]                # uM/s per amino acid
        with np.errstate(divide="ignore", invalid="ignore"):
            kf = np.where(E > 0, v / np.where(E > 0, E, 1.0), np.nan)
            thU = (u / KMtf) / (1.0 + u / KMtf)
            thA = (a / KMaa) / (1.0 + a / KMaa)
        kr = kS * thU * thA
        # drop step 0 (initialisation artefacts: dt is synthesised, aasUsed may be 0)
        sl = slice(1, len(t))
        kflux.append(np.nanmedian(kf[sl], axis=0))
        krho.append(np.nanmedian(kr[sl], axis=0))
        Es.append(np.nanmedian(E[sl], axis=0))
        labels.append(so.split("/out/")[1].split("/")[0] + "/" + so.split("generation_")[1][:6])
        nsteps.append(len(t) - 1)

    kflux = np.array(kflux)
    krho = np.array(krho)
    Es = np.array(Es)
    n = len(kflux)
    print("run-generations used: %d   timesteps per run-gen: min %d max %d  (step 0 dropped)"
          % (n, min(nsteps), max(nsteps)))
    print("")

    hdr = ("%-22s %-16s %9s %9s %9s %9s %9s %9s %7s  %s"
           % ("amino acid", "synthetase", "kcat_cur", "E_a(uM)", "kreq_flx", "min", "max",
              "kreq_rho", "ratio", "verdict"))
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for i in fams:
        syn = a2s[aas[i]]
        k_cur = cur.get(syn, None)
        kc = float(k_cur.asNumber(1 / units.s)) if k_cur is not None else float("nan")
        kf = float(np.nanmedian(kflux[:, i]))
        kfmin = float(np.nanmin(kflux[:, i]))
        kfmax = float(np.nanmax(kflux[:, i]))
        kr = float(np.nanmedian(krho[:, i]))
        E = float(np.nanmedian(Es[:, i]))
        ratio = kc / kf if kf > 0 else float("nan")
        verdict = "INSUFFICIENT" if ratio < 1 else "ok"
        n_syn = int(afs[i].sum())
        note = "" if n_syn == 1 else " [%d synthetases pooled: %s]" % (
            n_syn, ",".join([snames[j] for j in np.where(afs[i])[0]]))
        print("%-22s %-16s %9.3f %9.4f %9.4f %9.4f %9.4f %9.4f %7.3f  %s%s"
              % (aas[i], syn, kc, E, kf, kfmin, kfmax, kr, ratio, verdict, note))
        rows.append((aas[i], syn, kc, E, kf, kfmin, kfmax, kr, ratio))

    print("")
    fail = [r for r in rows if r[8] < 1]
    print("INEQUALITY kcat_curated_max < k_req_flux HOLDS (i.e. curated kcat is INSUFFICIENT) "
          "for %d of %d families." % (len(fail), len(rows)))
    for r in sorted(fail, key=lambda x: x[8]):
        print("   %-22s curated %8.3f  required %8.4f  shortfall %6.2fx" % (r[0], r[2], r[4], 1.0 / r[8]))
    ok = [r for r in rows if r[8] >= 1]
    print("Curated kcat is SUFFICIENT for %d families (headroom, curated/required):" % len(ok))
    for r in sorted(ok, key=lambda x: -x[8]):
        print("   %-22s curated %8.3f  required %8.4f  headroom %8.2fx" % (r[0], r[2], r[4], r[8]))

    # Per-family robustness: in how many of the 27 run-generations does the inequality hold?
    print("")
    print("ROBUSTNESS -- fraction of the %d run-generations in which kcat_curated < k_req_flux,"
          " and by arm (fam / abu / equ, 9 run-gens each):" % n)
    arm = np.array([lab.split("_")[1] for lab in labels])
    print("%-22s %10s %8s %8s %8s" % ("amino acid", "all", "fam", "abu", "equ"))
    for i in fams:
        syn = a2s[aas[i]]
        k_cur = cur.get(syn, None)
        kc = float(k_cur.asNumber(1 / units.s)) if k_cur is not None else float("nan")
        hit = kflux[:, i] > kc
        print("%-22s %6d/%-3d %8s %8s %8s"
              % (aas[i], int(hit.sum()), n,
                 "%d/9" % int(hit[arm == "fam"].sum()),
                 "%d/9" % int(hit[arm == "abu"].sum()),
                 "%d/9" % int(hit[arm == "equ"].sum())))

    kreq_all = np.array([r[4] for r in rows])
    kcur_all = np.array([r[2] for r in rows])
    print("")
    print("k_req_flux across 20 families: min %.4f (%s)  median %.4f  max %.4f (%s)"
          % (kreq_all.min(), rows[int(kreq_all.argmin())][0], float(np.median(kreq_all)),
             kreq_all.max(), rows[int(kreq_all.argmax())][0]))
    print("kS = %.1f /s is above the curated max for %d of 20 families."
          % (kS, int((kcur_all < kS).sum())))
    print("cross-check: median |k_req_rho - k_req_flux| / k_req_flux over 20 families = %.4f"
          % float(np.median(np.abs(np.array([r[7] for r in rows]) - kreq_all) / kreq_all)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
