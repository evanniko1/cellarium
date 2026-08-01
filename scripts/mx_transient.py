"""Is the 'worst over all timesteps' spread a sustained level or a one-step transient?

The matrix reports worst-over-timesteps spread of 1.294e-3 for isoacceptor+abundance at seed 1
generation 2, against ~1e-5 elsewhere in that arm, and 7.375e-1 for isoacceptor+equal at the same
cell against ~7e-2 elsewhere. A maximum over ~3000 timesteps is destroyed by a single excursion, so
this reports the DISTRIBUTION: median, 99th percentile, maximum, and how many timesteps exceed a
threshold. A level that shows up in one step out of 3000 is a transient, not a spread.
"""

import argparse
import os
import pickle
import sys

import numpy as np

sys.path.insert(0, "/wcEcoli")

from wholecell.io.tablereader import TableReader  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="/wcEcoli/out")
    ap.add_argument("--kb", default="/wcEcoli/out/kinetic_parca/kb/simData.cPickle")
    a = ap.parse_args(argv)

    with open(a.kb, "rb") as fh:
        sd = pickle.load(fh)
    aft = sd.process.transcription.aa_from_trna
    multi = [i for i in range(aft.shape[0]) if aft[i].sum() > 1]

    print("{:6s} {:4s} {:3s} {:>7s} {:>11s} {:>11s} {:>11s} {:>11s} {:>9s} {:>9s}".format(
        "arm", "seed", "gen", "steps", "median", "p99", "max", "last",
        ">10x_med", ">1e-2"))
    for arm in ["fam", "abu", "equ"]:
        for seed in ["0", "1", "2"]:
            for gen in [0, 1, 2]:
                so = os.path.join(a.out, "mx_{}_s{}".format(arm, seed), "wildtype_000000",
                                  "%06d" % int(seed), "generation_%06d" % gen, "000000", "simOut")
                if not os.path.isdir(so):
                    print("{:6s} {:4s} {:3d}  MISSING {}".format(arm, seed, gen, so))
                    continue
                frac = np.atleast_2d(
                    TableReader(os.path.join(so, "GrowthLimits")).readColumn(
                        "fraction_trna_charged"))
                # Worst family spread AT EACH timestep, then describe that series.
                per_t = np.zeros(frac.shape[0])
                for i in multi:
                    cols = np.where(aft[i] > 0)[0]
                    sub = frac[:, cols]
                    per_t = np.maximum(per_t, sub.max(1) - sub.min(1))
                med = float(np.median(per_t))
                thr = max(med * 10.0, 1e-12)
                print("{:6s} {:4s} {:3d} {:7d} {:11.3e} {:11.3e} {:11.3e} {:11.3e} {:9d} {:9d}"
                      .format(arm, seed, gen, len(per_t), med,
                              float(np.percentile(per_t, 99)), float(per_t.max()),
                              float(per_t[-1]), int((per_t > thr).sum()),
                              int((per_t > 1e-2).sum())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
