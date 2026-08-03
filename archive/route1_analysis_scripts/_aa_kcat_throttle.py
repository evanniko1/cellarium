"""Make a STARVED knowledge base by throttling de-novo amino-acid synthesis capacity.

Runs INSIDE the model container (python 3.10, numpy that wrote the pickle).

    python /wcEcoli/out/_aa_kcat_throttle.py <src_kb_dir> <dst_kb_dir> <factor> [aa_index]

`sim_data.process.metabolism.aa_kcats_fwd` is the per-amino-acid forward kcat vector that
`amino_acid_synthesis_jit` multiplies LINEARLY into the synthesis rate
(reconstruction/ecoli/dataclasses/process/metabolism.py:2213). With the run options the ROUTE1 A/B
already used (mechanistic_translation_supply=True, aa_supply_in_charging=True, media "0 minimal"
so amino-acid import is zero), that vector is the ONLY amino-acid source the charging ODE sees
(models/ecoli/processes/polypeptide_elongation.py:2360-2366). Scaling it by `factor` is therefore a
graded, global amino-acid limitation with one scalar knob and no medium change, no new flat file and
no ParCa refit.

With an optional `aa_index`, only that one amino acid is throttled (selective limitation).
"""
import os
import pickle
import shutil
import sys

import numpy as np


def main(argv):
    src, dst, factor = argv[0], argv[1], float(argv[2])
    aa_index = int(argv[3]) if len(argv) > 3 else None
    os.makedirs(dst, exist_ok=True)
    src_pkl = os.path.join(src, "simData.cPickle")
    dst_pkl = os.path.join(dst, "simData.cPickle")

    with open(src_pkl, "rb") as fh:
        sd = pickle.load(fh)
    k = sd.process.metabolism.aa_kcats_fwd
    before = np.array(k, dtype=float, copy=True)
    print("aa_kcats_fwd shape={} dtype={}".format(np.shape(k), np.asarray(k).dtype))
    print("before: min={:.6g} max={:.6g} sum={:.6g}".format(before.min(), before.max(), before.sum()))

    if factor == 1.0 and aa_index is None:
        # identity: copy the bytes rather than re-pickling, so the control kb is byte-identical
        shutil.copyfile(src_pkl, dst_pkl)
        print("factor 1.0 -> byte copy, no re-pickle")
        return 0

    if aa_index is None:
        sd.process.metabolism.aa_kcats_fwd = before * factor
    else:
        new = before.copy()
        new[aa_index] *= factor
        sd.process.metabolism.aa_kcats_fwd = new
    after = np.asarray(sd.process.metabolism.aa_kcats_fwd, dtype=float)
    print("after : min={:.6g} max={:.6g} sum={:.6g}".format(after.min(), after.max(), after.sum()))
    ratio = np.where(before > 0, after / np.where(before > 0, before, 1.0), np.nan)
    print("ratio : min={:.6g} max={:.6g}".format(np.nanmin(ratio), np.nanmax(ratio)))

    with open(dst_pkl, "wb") as fh:
        pickle.dump(sd, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print("wrote {} ({} bytes)".format(dst_pkl, os.path.getsize(dst_pkl)))

    # read back and verify the throttle survived the round trip
    with open(dst_pkl, "rb") as fh:
        chk = pickle.load(fh)
    got = np.asarray(chk.process.metabolism.aa_kcats_fwd, dtype=float)
    ok = np.allclose(got, after, rtol=0, atol=0)
    print("roundtrip exact: {}".format(ok))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
