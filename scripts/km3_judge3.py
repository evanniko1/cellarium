"""Why the response is non-uniform: per-family trna_kms, old vs new ParCa."""

import json
import sys

import numpy as np

scratch = sys.argv[1]
kbn = json.load(open(scratch + "/judge_kb_new.json"))
kbo = json.load(open(scratch + "/judge_kb_old.json"))
aft = np.asarray(kbn["aa_from_trna"])
names = kbn["aa_names"]
a = np.asarray(kbn["trna_kms"], float)
b = np.asarray(kbo["trna_kms"], float)
print("trna_kms shape new %s old %s ; names match %s"
      % (a.shape, b.shape, kbn["uncharged_trna_names"] == kbo["uncharged_trna_names"]))
print("global: OLD median %.4f (min %.4f max %.4f) -> NEW median %.4f (min %.4f max %.4f)"
      % (np.median(b), b.min(), b.max(), np.median(a), a.min(), a.max()))
print("per-tRNA ratio new/old: median %.3f  min %.3f  max %.3f ; n unchanged (ratio==1) %d/%d"
      % (np.median(a / b), (a / b).min(), (a / b).max(), int((a == b).sum()), a.size))
print()
print("trna_kms is indexed by AMINO ACID (%d entries), not by tRNA (%d) -- one Km per family."
      % (a.size, len(kbn["uncharged_trna_names"])))
print()
print("%-20s %3s %10s %10s %8s" % ("family", "n_iso", "OLD Km", "NEW Km", "ratio"))
for i, nm in enumerate(names):
    if i >= a.size:
        break
    n_iso = int(aft[i].sum())
    print("%-20s %3d %10.4f %10.4f %8.2f%s"
          % (nm, n_iso, b[i], a[i], a[i] / b[i], "   <-- multi-member" if n_iso > 1 else ""))
