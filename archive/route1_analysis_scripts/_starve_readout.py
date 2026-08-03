"""Starvation depth + Phi readout for the aa_kcats_fwd throttle ladder. Runs INSIDE the container.

Phi = v_rib_realized / v_rib_ratelaw, the quantity the ROUTE1-21 claim turns on.

  v_rib_realized = actualElongations * counts_to_molar / dt          (evolve path, uM/s)
  v_rib_ratelaw  = max_elong_rate * ribosome_conc / D                (the charging rate law)
  D              = 1 + sum_a f_a * (krta/c_a) * (1 + u_a/krtf)       over the 21 amino acids

max_elong_rate is elongation_rate(): under ppgpp_regulation it is
get_ribosome_elongation_rate_by_ppgpp(ppgpp_conc, basal_elongation_rate)
(models/ecoli/processes/polypeptide_elongation.py:1046-1055).

All the tRNA/ribosome/f inputs are the REQUEST-side listener columns, which is the state the request
call used; the realized elongations are the evolve-side outcome of that same step. Phi therefore
measures exactly the request-vs-evolve mismatch the claim is about.
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
    runs = argv
    sd = pickle.load(open("/wcEcoli/out/kinetic_parca/kb/simData.cPickle", "rb"))
    tr = sd.process.transcription
    A = tr.aa_from_trna
    aas = list(sd.molecule_groups.amino_acids)
    SEL = aas.index("L-SELENOCYSTEINE[c]")
    fam = A.argmax(0)
    m21 = np.ones(len(aas), bool)
    m21[SEL] = False
    m86 = m21[fam]
    krta = sd.constants.Kdissociation_charged_trna_ribosome.asNumber(CONC)
    krtf = sd.constants.Kdissociation_uncharged_trna_ribosome.asNumber(CONC)
    nav = sd.constants.n_avogadro.asNumber(1 / units.mol)
    rho = sd.constants.cell_density.asNumber(units.fg / units.L)
    # polypeptide_elongation.py:893 -- BaseElongationModel.basal_elongation_rate
    basal_rate = sd.constants.ribosome_elongation_rate_basal.asNumber(units.aa / units.s)
    rate_by_ppgpp = sd.growth_rate_parameters.get_ribosome_elongation_rate_by_ppgpp

    hdr = ("%-9s %6s %8s %8s %6s %8s %8s %10s %10s %10s %10s"
           % ("run", "f", "unch85", "unchmax", "n>20%", "elong", "D", "maxElong", "Phi_med",
              "Phi_p10", "relaSyn"))
    print(hdr)
    print("-" * len(hdr))
    for run, f in runs:
        so = sorted(glob.glob("/wcEcoli/out/%s/*/*/generation_*/*/simOut" % run))
        if not so:
            print("%-9s  NO simOut ON DISK -- could not establish" % run)
            continue
        so = so[0]
        gl = TableReader(os.path.join(so, "GrowthLimits"))
        fc = gl.readColumn("fraction_trna_charged")
        c21 = gl.readColumn("charged_trna_conc")
        u21 = gl.readColumn("uncharged_trna_conc")
        f21 = gl.readColumn("fraction_aa_to_elongate")
        rconc = gl.readColumn("ribosome_conc")
        ppg = gl.readColumn("ppgpp_conc")
        rela = gl.readColumn("rela_syn").sum(axis=1)
        rd = TableReader(os.path.join(so, "RibosomeData"))
        act = rd.readColumn("actualElongations").astype(float)
        er = rd.readColumn("effectiveElongationRate")
        cm = TableReader(os.path.join(so, "Mass")).readColumn("cellMass")
        t = TableReader(os.path.join(so, "Main")).readColumn("time")
        dt = np.diff(t, prepend=t[0] - (t[1] - t[0]))

        c2m = 1e6 / (nav * (cm / rho))          # uM per count
        v_real = act * c2m / dt                  # uM/s
        D = 1.0 + np.sum((f21 * (krta / np.maximum(c21, 1e-30)) * (1 + u21 / krtf))[:, m21], axis=1)
        kmax = np.array([rate_by_ppgpp(p * CONC, basal_rate).asNumber(units.aa / units.s)
                         for p in ppg])
        v_law = kmax * rconc / D
        phi = v_real / np.maximum(v_law, 1e-300)

        n = len(t)
        q = slice(int(n * 0.75), n)             # last quarter, past the initial transient
        u = 1.0 - fc
        u85 = u[:, m86]
        print("%-9s %6.2f %8.4f %8.4f %6.1f %8.3f %8.3f %10.3f %10.5f %10.5f %10.4g"
              % (run, f, u85[q].mean(), u85[q].max(), (u85[q] > 0.2).sum(axis=1).mean(),
                 er[q].mean(), D[q].mean(), kmax[q].mean(),
                 np.median(phi[q]), np.percentile(phi[q], 10), rela[q].mean()))
    return 0


if __name__ == "__main__":
    pairs = []
    for a in sys.argv[1:]:
        r, v = a.split("=")
        pairs.append((r, float(v)))
    sys.exit(main(pairs))
