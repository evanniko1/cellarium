from __future__ import absolute_import, division, print_function
import os, sys, json
import numpy as np
from wholecell.io.tablereader import TableReader

CTL, TRT = sys.argv[1], sys.argv[2]

def simout(root):
    return os.path.join(root, "wildtype_000000", "000001", "generation_000000", "000000", "simOut")

def read(root, t, c):
    return np.asarray(TableReader(os.path.join(simout(root), t)).readColumn(c))

def bw(a, b):
    a2 = np.atleast_1d(a).reshape(np.atleast_1d(a).shape[0], -1).astype(np.float64)
    b2 = np.atleast_1d(b).reshape(np.atleast_1d(b).shape[0], -1).astype(np.float64)
    return np.all(a2.view(np.uint64) == b2.view(np.uint64), axis=1)

out = {}
for t, c in [("Mass","cellMass"),("Mass","dryMass"),("RibosomeData","actualElongations"),
             ("GrowthLimits","ppgpp_conc"),("GrowthLimits","rela_syn"),
             ("GrowthLimits","spot_deg"),("GrowthLimits","spot_syn")]:
    k = "%s/%s" % (t, c)
    try:
        a = read(CTL, t, c); b = read(TRT, t, c)
    except Exception as e:
        out[k] = "READ_FAILED: %r" % (e,); continue
    e_ = bw(a, b)
    bad = np.where(~e_[1:])[0]
    out[k] = {
        "shape": list(a.shape),
        "ctl_first3": [repr(float(x)) for x in np.atleast_1d(a.reshape(a.shape[0], -1)[1])[:3]],
        "trt_first3": [repr(float(x)) for x in np.atleast_1d(b.reshape(b.shape[0], -1)[1])[:3]],
        "ctl_row1_vs_row120_differs": bool(not np.array_equal(a.reshape(a.shape[0],-1)[1], a.reshape(a.shape[0],-1)[120])),
        "n_differing_evolved_steps": int(bad.size),
        "first_differing_evolved_step": (int(bad[0]+1) if bad.size else None),
        "max_abs_rel_diff": float(np.nanmax(np.abs((b.reshape(b.shape[0],-1)[1:] - a.reshape(a.shape[0],-1)[1:]) / np.where(a.reshape(a.shape[0],-1)[1:]==0, np.nan, a.reshape(a.shape[0],-1)[1:])))) if np.any(a.reshape(a.shape[0],-1)[1:]!=0) else None,
    }

# metadata sanity
for name, root in (("ctl", CTL), ("trt", TRT)):
    p = os.path.join(root, "metadata", "metadata.json")
    if os.path.exists(p):
        m = json.load(open(p))
        out["meta_" + name] = {k: m.get(k) for k in
            ("seed","elongation_model","ppgpp_regulation","trna_charging",
             "translation_supply","explicit_trna_charging","operons","length_sec")}
    else:
        out["meta_" + name] = "MISSING"

print(json.dumps(out, indent=1))
