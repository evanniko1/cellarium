"""Magnitude of the family-vs-isoacceptor divergence through generation 0, and when division fires.

mx_diverge.py showed the arms differ from row 0 of cellMass while Main/time is identical. "Differs"
was a boolean there, which cannot tell float noise from a real offset, so this prints the actual
values and the relative difference at a ladder of timesteps, plus the replication/division events
that set the generation length.
"""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, "/wcEcoli")

from wholecell.io.tablereader import TableReader  # noqa: E402


def col(so, table, name):
    return np.asarray(TableReader(os.path.join(so, table)).readColumn(name), dtype=float)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="/wcEcoli/out")
    ap.add_argument("--seed", default="2")
    ap.add_argument("--gen", type=int, default=0)
    a = ap.parse_args(argv)

    p = {}
    for arm in ["fam", "abu", "equ"]:
        p[arm] = os.path.join(a.out, "mx_{}_s{}".format(arm, a.seed), "wildtype_000000",
                              "%06d" % int(a.seed), "generation_%06d" % a.gen, "000000", "simOut")

    f = col(p["fam"], "Mass", "cellMass")
    b = col(p["abu"], "Mass", "cellMass")
    e = col(p["equ"], "Mass", "cellMass")
    n = len(f)
    print("seed {} generation {}: {} rows".format(a.seed, a.gen, n))
    print("{:>7s} {:>16s} {:>16s} {:>12s} {:>16s} {:>12s}".format(
        "step", "fam cellMass", "abu cellMass", "rel(abu)", "equ cellMass", "rel(equ)"))
    for i in [0, 1, 2, 5, 10, 50, 100, 300, 600, 1200, 2000, n - 1]:
        if i >= n:
            continue
        print("{:7d} {:16.10g} {:16.10g} {:12.3e} {:16.10g} {:12.3e}".format(
            i, f[i], b[i], abs(b[i] - f[i]) / f[i], e[i], abs(e[i] - f[i]) / f[i]))

    # What actually terminates the generation? Print the replication/division-relevant series ends.
    for arm in ["fam", "abu", "equ"]:
        try:
            rd = TableReader(os.path.join(p[arm], "ReplicationData"))
            names = rd.allAttributeNames()
            has = [x for x in ("criticalMassPerOriC", "criticalInitiationMass", "numberOfOric")
                   if x in rd.columnNames()]
            t = col(p[arm], "Main", "time")
            out = ["{} end_time={:.0f}".format(arm, t[-1])]
            for h in has:
                v = np.atleast_2d(col(p[arm], "ReplicationData", h))
                out.append("{}[last]={:.6g}".format(h, float(v[-1].max())))
            print("  " + "  ".join(out))
        except Exception as exc:
            print("  {}: ReplicationData read failed: {}".format(arm, exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
