"""Create the ROUTE1 step-2 test-matrix run directories with a HARDLINKED kb/.

One directory per (arm, seed). kb/ is hardlinked from an existing ParCa tree, so simData.cPickle is
byte-identical BY CONSTRUCTION (same inode, not a copy that could drift) and the baseline ParCa
directory is never written to by the sim.

    python mx_setup.py --out C:/dev/wcEcoli/out --parca kinetic_parca
"""

import argparse
import os
import sys

ARMS = ["fam", "abu", "equ"]
SEEDS = [0, 1, 2]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="C:/dev/wcEcoli/out")
    ap.add_argument("--parca", default="kinetic_parca")
    ap.add_argument("--prefix", default="mx")
    a = ap.parse_args(argv)

    src_kb = os.path.join(a.out, a.parca, "kb")
    if not os.path.isdir(src_kb):
        print("ERROR: source kb not found: {}".format(src_kb))
        return 1
    src_files = sorted(f for f in os.listdir(src_kb) if f.endswith(".cPickle"))
    if "simData.cPickle" not in src_files:
        print("ERROR: simData.cPickle not in {}".format(src_kb))
        return 1

    ref_inode = os.stat(os.path.join(src_kb, "simData.cPickle")).st_ino
    print("source kb {}  simData inode {}".format(src_kb, ref_inode))

    made = []
    for arm in ARMS:
        for seed in SEEDS:
            name = "{}_{}_s{}".format(a.prefix, arm, seed)
            d = os.path.join(a.out, name)
            kb = os.path.join(d, "kb")
            os.makedirs(kb, exist_ok=True)
            for f in src_files:
                dst = os.path.join(kb, f)
                if os.path.exists(dst):
                    continue
                os.link(os.path.join(src_kb, f), dst)
            got = os.stat(os.path.join(kb, "simData.cPickle")).st_ino
            same = got == ref_inode
            print("{:14s} kb hardlinked  simData inode {}  IDENTICAL={}".format(name, got, same))
            if not same:
                print("ERROR: {} kb is a COPY, not a hardlink".format(name))
                return 1
            made.append(name)

    print("MX_SETUP_OK {} dirs".format(len(made)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
