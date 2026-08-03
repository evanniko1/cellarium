"""Which amino-acid families de-charge under the throttle, and are they DEGENERATE?

SCI-TRNA-1's degeneracy guard: a species pinned at a constant value with ~zero total variation over
the generation is arithmetic, not a measured response. Report total variation alongside the level.
"""
import glob
import os
import pickle
import sys

import numpy as np

from wholecell.io.tablereader import TableReader

sd = pickle.load(open("/wcEcoli/out/kinetic_parca/kb/simData.cPickle", "rb"))
A = sd.process.transcription.aa_from_trna
aas = [a.split("[")[0] for a in sd.molecule_groups.amino_acids]
fam = A.argmax(0)

for run in sys.argv[1:]:
    so = sorted(glob.glob("/wcEcoli/out/%s/*/*/generation_*/*/simOut" % run))
    if not so:
        print("%s: NO simOut -- could not establish" % run)
        continue
    gl = TableReader(os.path.join(so[0], "GrowthLimits"))
    fc = gl.readColumn("fraction_trna_charged")
    n = fc.shape[0]
    q = slice(int(n * 0.75), n)
    u = 1.0 - fc
    # collapse 86 species to 21 families by mean over the family's members
    out = []
    for a in range(len(aas)):
        idx = np.flatnonzero(fam == a)
        if idx.size == 0:
            continue
        series = u[:, idx].mean(axis=1)
        tv = float(np.abs(np.diff(series)).sum())
        out.append((series[q].mean(), aas[a], tv))
    out.sort(reverse=True)
    print("%s  top de-charged families (uncharged fraction, last quarter; TV = total variation "
          "over the run -- near 0 means pinned/degenerate)" % run)
    for v, nm, tv in out[:10]:
        print("   %-18s uncharged=%.4f   TV=%.4g" % (nm, v, tv))
    print()
