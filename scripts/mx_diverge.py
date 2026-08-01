"""Where, exactly, do the three arms diverge within generation 0?

The matrix report shows generation 0 has the SAME number of steps and the SAME duration in all three
arms for a given seed, but DIFFERENT cellMass ratios. Those two facts are in tension, so this checks
the series directly rather than attributing the difference to anything.

Compares family / isoacceptor+abundance / isoacceptor+equal at the same seed, timestep by timestep,
and reports the first index at which each series differs at all, plus the magnitude at the end.
"""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, "/wcEcoli")

from wholecell.io.tablereader import TableReader  # noqa: E402


def series(so, table, col):
    return np.asarray(TableReader(os.path.join(so, table)).readColumn(col), dtype=float)


def first_diff(a, b):
    n = min(len(a), len(b))
    d = np.abs(np.atleast_2d(a[:n]) - np.atleast_2d(b[:n]))
    if d.ndim > 1:
        d = d.max(axis=1)
    nz = np.where(d > 0)[0]
    return (int(nz[0]) if len(nz) else None, n)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="/wcEcoli/out")
    ap.add_argument("--seeds", nargs="+", default=["0", "1", "2"])
    ap.add_argument("--gen", type=int, default=0)
    a = ap.parse_args(argv)

    cols = [("Mass", "cellMass"), ("Mass", "dryMass"), ("Main", "time"),
            ("Main", "timeStepSec"), ("GrowthLimits", "ppgpp_conc")]

    for seed in a.seeds:
        paths = {}
        for arm in ["fam", "abu", "equ"]:
            paths[arm] = os.path.join(
                a.out, "mx_{}_s{}".format(arm, seed), "wildtype_000000",
                "%06d" % int(seed), "generation_%06d" % a.gen, "000000", "simOut")
        print("=== seed {} generation {} ===".format(seed, a.gen))
        for table, col in cols:
            try:
                f = series(paths["fam"], table, col)
                b = series(paths["abu"], table, col)
                e = series(paths["equ"], table, col)
            except Exception as exc:
                print("  {}/{}: READ FAILED {}".format(table, col, exc))
                continue
            i_ab, n_ab = first_diff(f, b)
            i_ae, n_ae = first_diff(f, e)
            print("  {:12s}/{:14s} len f/b/e = {}/{}/{}".format(
                table, col, len(f), len(b), len(e)))
            print("      fam vs abu: first differing index {} of {}   last values {:.6g} / {:.6g}"
                  .format("NONE (identical)" if i_ab is None else i_ab, n_ab,
                          float(np.atleast_1d(f[-1]).max()), float(np.atleast_1d(b[-1]).max())))
            print("      fam vs equ: first differing index {} of {}   last values {:.6g} / {:.6g}"
                  .format("NONE (identical)" if i_ae is None else i_ae, n_ae,
                          float(np.atleast_1d(f[-1]).max()), float(np.atleast_1d(e[-1]).max())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
