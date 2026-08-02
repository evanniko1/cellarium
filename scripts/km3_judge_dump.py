"""Dump the reconstruction-time facts the judge needs, from simData, to a JSON file.

Runs inside the model image (simData unpickling needs the compiled cython modules).
Independent of km3_analyze.py: this only extracts primitives so the judging arithmetic
can be redone outside the container.
"""

import json
import pickle
import sys

import numpy as np

sys.path.insert(0, "/wcEcoli")


def dump(kb_path, out_path):
    with open(kb_path, "rb") as fh:
        sd = pickle.load(fh)
    tr = sd.process.transcription
    rec = {
        "kb": kb_path,
        "aa_names": [str(x) for x in sd.molecule_groups.amino_acids],
        "aa_from_trna": np.asarray(tr.aa_from_trna).astype(int).tolist(),
        "uncharged_trna_names": [str(x) for x in tr.uncharged_trna_names],
        "charged_trna_names": [str(x) for x in tr.charged_trna_names],
    }
    try:
        rec["trna_kms"] = np.asarray(tr.trna_kms.asNumber()).tolist()
    except Exception:
        try:
            rec["trna_kms"] = np.asarray(tr.trna_kms).astype(float).tolist()
        except Exception as exc:
            rec["trna_kms_error"] = "{}: {}".format(type(exc).__name__, exc)
    with open(out_path, "w") as fh:
        json.dump(rec, fh)
    print("WROTE {} families={} trnas={}".format(
        out_path, len(rec["aa_names"]), len(rec["uncharged_trna_names"])))


if __name__ == "__main__":
    dump(sys.argv[1], sys.argv[2])
