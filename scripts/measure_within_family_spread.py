"""Measure the within-family charged-fraction spread from finished simulations.

This is the script behind section 9.3 of docs/ROUTE1_VERIFICATION.md. It exists so the degeneracy
claim is reproducible rather than quoted: the claim is that at the DEFAULT demand split ('abundance')
the within-family charged fraction is uniform BY CONSTRUCTION, and that spread appears only at
'equal'. Both are checked here against the production listener column, not against a re-derivation.

WHAT IT READS. `GrowthLimits/fraction_trna_charged`, which is 86-wide at BOTH resolutions -- stage 5
changed its MEANING at isoacceptor resolution (genuine per-species values) without changing its
shape, so the same column is comparable across configurations. For each multi-member amino-acid
family it takes max - min across that family's isoacceptors at every timestep, then the worst over
all timesteps.

WHY THE FAMILY CONTROL MATTERS. At family resolution the 86 columns are a broadcast of 21 values, so
the spread must be EXACTLY 0.0. If it is not, the measurement is reading the wrong thing and the
isoacceptor numbers mean nothing either.

RUN IT INSIDE THE MODEL IMAGE -- it needs wcEcoli's TableReader and the ParCa pickle:

    docker run --rm -v C:/dev/wcEcoli/out:/wcEcoli/out -e PYTHONPATH=/wcEcoli -w /wcEcoli \
        <image> python /wcEcoli/out/measure_within_family_spread.py <sim_dir> [<sim_dir> ...]

SCOPE, stated so the numbers are not overread: whatever seeds and generations the given directories
contain. The runs this was first used on were single-seed, generation 0, 20 s. The STRUCTURAL results
(KMtf broadcast; the proportional fixed point) do not depend on that; the MAGNITUDES do.
"""

import argparse
import os
import pickle
import sys

import numpy as np

sys.path.insert(0, "/wcEcoli")

from wholecell.io.tablereader import TableReader  # noqa: E402

DEFAULT_KB = "/wcEcoli/out/kinetic_parca/kb/simData.cPickle"


def find_simouts(root):
    """Every non-empty simOut under root. A directory with none is a MISSING measurement."""
    out = []
    if not os.path.isdir(root):
        return out
    for d, _sub, files in os.walk(root):
        if os.path.basename(d) == "simOut" and files:
            out.append(d)
    return sorted(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sim_dirs", nargs="+")
    ap.add_argument("--kb", default=DEFAULT_KB)
    ap.add_argument("--top", type=int, default=3)
    a = ap.parse_args(argv)

    with open(a.kb, "rb") as fh:
        sd = pickle.load(fh)
    aa_from_trna = sd.process.transcription.aa_from_trna
    aa_names = list(sd.molecule_groups.amino_acids)
    multi = [i for i in range(aa_from_trna.shape[0]) if aa_from_trna[i].sum() > 1]
    print(f"aa_from_trna {aa_from_trna.shape}; multi-member families: {len(multi)}")

    missing = 0
    for root in a.sim_dirs:
        simouts = find_simouts(root)
        if not simouts:
            # Never print a missing directory as a zero. That confusion is the whole point of this
            # branch existing separately from the measurement.
            print(f"{root}: NOT MEASURED -- no non-empty simOut found")
            missing += 1
            continue
        for so in simouts:
            frac = TableReader(os.path.join(so, "GrowthLimits")).readColumn("fraction_trna_charged")
            per_fam = []
            for i in multi:
                cols = np.where(aa_from_trna[i] > 0)[0]
                sub = frac[:, cols]
                per_fam.append((float(np.nanmax(sub.max(1) - sub.min(1))), aa_names[i]))
            per_fam.sort(reverse=True)
            top = ", ".join(f"{n} {s:.3e}" for s, n in per_fam[: a.top])
            rel = os.path.relpath(so, root)
            print(f"{root} [{rel}]  T={frac.shape[0]} cols={frac.shape[1]}  "
                  f"worst={per_fam[0][0]:.3e}   top{a.top}: {top}")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
