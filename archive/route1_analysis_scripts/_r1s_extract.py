"""Per-timestep extraction for the ROUTE1-21 two-arm starvation matrix. Runs INSIDE the container.

    python /wcEcoli/out/_r1s_extract.py <kb_pickle> <out_npz_dir> <run> [<run> ...]

For every run it writes out/<npz_dir>/<run>.npz with one row per timestep:

  t, dt                     Main/time
  ppgpp_conc                GrowthLimits/ppgpp_conc                       (uM)
  elong                     RibosomeData/effectiveElongationRate          (aa/s)
  rela_syn_tot              GrowthLimits/rela_syn summed over 21 AAs
  rela_syn                  GrowthLimits/rela_syn, per amino acid (21)
  v_real                    actualElongations * counts_to_molar / dt      (uM/s)
  v_law                     max_elong_rate * ribosome_conc / D            (uM/s)
  phi                       v_real / v_law
  D                         1 + sum_a f_a (krta/c_a)(1 + u_a/krtf)
  kmax                      get_ribosome_elongation_rate_by_ppgpp(ppgpp)  (aa/s)
  rbu_new, rbu_old          RECONSTRUCTED ribosomes_bound_to_uncharged, per AA (21).
                            There is NO listener for this quantity (it is a local at
                            models/ecoli/processes/polypeptide_elongation.py:1547), so these are
                            rebuilt from the REQUEST-side GrowthLimits columns under each form.
  unch_raw                  per-species uncharged fraction from RAW BulkMolecules counts,
                            u_j / (u_j + c_j) over the 86 tRNA species -- NOT the
                            GrowthLimits/fraction_trna_charged listener.
  unch_raw_mean85           mean of unch_raw over the 85 non-selC species
  unch_raw_fam              per-amino-acid uncharged fraction from RAW counts, aggregated by family
  cellMass, dryMass, actualElongations

Also prints a one-line-per-run health summary: step count, NaN counts, exit condition.
"""
import glob
import os
import pickle
import sys

import numpy as np

from wholecell.io.tablereader import TableReader
from wholecell.utils import units

CONC = units.umol / units.L


def find_simout(run):
    hits = sorted(glob.glob("/wcEcoli/out/%s/*/*/generation_*/*/simOut" % run))
    return hits


def main(argv):
    kb_pkl, npz_dir, runs = argv[0], argv[1], argv[2:]
    os.makedirs(npz_dir, exist_ok=True)
    sd = pickle.load(open(kb_pkl, "rb"))
    tr = sd.process.transcription
    A = np.asarray(tr.aa_from_trna)                       # (21, 86)
    aas = list(sd.molecule_groups.amino_acids)
    SEL = aas.index("L-SELENOCYSTEINE[c]")
    fam = A.argmax(0)                                     # family index of each of the 86 species
    m21 = np.ones(len(aas), bool)
    m21[SEL] = False
    m86 = m21[fam]
    unch_names = list(tr.uncharged_trna_names)
    chg_names = list(tr.charged_trna_names)
    krta = sd.constants.Kdissociation_charged_trna_ribosome.asNumber(CONC)
    krtf = sd.constants.Kdissociation_uncharged_trna_ribosome.asNumber(CONC)
    nav = sd.constants.n_avogadro.asNumber(1 / units.mol)
    rho = sd.constants.cell_density.asNumber(units.fg / units.L)
    basal = sd.constants.ribosome_elongation_rate_basal.asNumber(units.aa / units.s)
    rate_by_ppgpp = sd.growth_rate_parameters.get_ribosome_elongation_rate_by_ppgpp

    print("%-14s %6s %7s %9s %9s %9s %9s  %s"
          % ("run", "steps", "gens", "nan_rela", "nan_phi", "nan_ppgpp", "nan_mass", "status"))
    for run in runs:
        sos = find_simout(run)
        if not sos:
            print("%-14s  NO simOut ON DISK -- could not establish" % run)
            continue
        so = sos[0]
        try:
            gl = TableReader(os.path.join(so, "GrowthLimits"))
            c21 = gl.readColumn("charged_trna_conc")
            u21 = gl.readColumn("uncharged_trna_conc")
            f21 = gl.readColumn("fraction_aa_to_elongate")
            rconc = gl.readColumn("ribosome_conc")
            ppg = gl.readColumn("ppgpp_conc")
            rela = gl.readColumn("rela_syn")
            fc_lis = gl.readColumn("fraction_trna_charged")
            rd = TableReader(os.path.join(so, "RibosomeData"))
            act = rd.readColumn("actualElongations").astype(float)
            er = rd.readColumn("effectiveElongationRate")
            ms = TableReader(os.path.join(so, "Mass"))
            cm = ms.readColumn("cellMass")
            dm = ms.readColumn("dryMass")
            t = TableReader(os.path.join(so, "Main")).readColumn("time")
            bm = TableReader(os.path.join(so, "BulkMolecules"))
            ids = list(bm.readAttribute("objectNames"))
            iu = np.array([ids.index(n) for n in unch_names])
            ic = np.array([ids.index(n) for n in chg_names])
            counts = bm.readColumn("counts")
            uc = counts[:, iu].astype(float)
            cc = counts[:, ic].astype(float)
        except Exception as e:                                    # noqa: BLE001
            print("%-14s  READ FAILED: %r -- could not establish" % (run, e))
            continue

        dt = np.diff(t, prepend=t[0] - (t[1] - t[0]))
        c2m = 1e6 / (nav * (cm / rho))                            # uM per count
        v_real = act * c2m / dt
        with np.errstate(divide="ignore", invalid="ignore"):
            theta = (krta / c21) * (1.0 + u21 / krtf)
        D = 1.0 + np.sum(np.where(np.isfinite(theta), f21 * theta, 0.0)[:, m21], axis=1)
        kmax = np.array([rate_by_ppgpp(p * CONC, basal).asNumber(units.aa / units.s) for p in ppg])
        v_law = kmax * rconc / D
        phi = v_real / np.where(v_law != 0, v_law, np.nan)

        # RECONSTRUCTED ribosomes_bound_to_uncharged (no listener exists for it).
        num = 1.0 + c21 / krta + u21 / krtf
        sat_c = (c21 / krta) / num
        sat_u = (u21 / krtf) / num
        with np.errstate(divide="ignore", invalid="ignore"):
            w = f21 / sat_c
        w_fin = np.where(np.isfinite(w), w, 0.0)
        denom = w_fin.sum(axis=1, keepdims=True)
        rbu_new = (rconc[:, None] * w / denom) * sat_u
        with np.errstate(divide="ignore", invalid="ignore"):
            rbu_old = (f21 * v_real[:, None] / (sat_c * kmax[:, None])) * sat_u

        tot = uc + cc
        with np.errstate(divide="ignore", invalid="ignore"):
            unch_raw = np.where(tot > 0, uc / np.where(tot > 0, tot, 1.0), np.nan)
        uc_f = np.zeros((len(t), len(aas)))
        tt_f = np.zeros((len(t), len(aas)))
        for j in range(len(fam)):
            uc_f[:, fam[j]] += uc[:, j]
            tt_f[:, fam[j]] += tot[:, j]
        unch_raw_fam = np.where(tt_f > 0, uc_f / np.where(tt_f > 0, tt_f, 1.0), np.nan)

        rela_tot = rela.sum(axis=1)
        np.savez_compressed(
            os.path.join(npz_dir, run + ".npz"),
            t=t, dt=dt, ppgpp_conc=ppg, elong=er, rela_syn=rela, rela_syn_tot=rela_tot,
            v_real=v_real, v_law=v_law, phi=phi, D=D, kmax=kmax, ribosome_conc=rconc,
            rbu_new=rbu_new, rbu_old=rbu_old, unch_raw=unch_raw,
            unch_raw_mean85=np.nanmean(unch_raw[:, m86], axis=1),
            unch_raw_fam=unch_raw_fam, unch_listener=1.0 - fc_lis,
            cellMass=cm, dryMass=dm, actualElongations=act,
            m86=m86, m21=m21, fam=fam, aas=np.array(aas), n_gens=len(sos))

        st = "ok"
        if len(sos) != 1:
            st = "%d generations on disk (used the first)" % len(sos)
        print("%-14s %6d %7d %9d %9d %9d %9d  %s"
              % (run, len(t), len(sos), int(np.isnan(rela_tot).sum()), int(np.isnan(phi).sum()),
                 int(np.isnan(ppg).sum()), int(np.isnan(cm).sum()), st))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
