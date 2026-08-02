"""Is GLY's spread saturating, and which families carry the charged-fraction drop?"""

import json
import os
import sys

import numpy as np

sys.path.insert(0, "C:/dev/wcEcoli")
from wholecell.io.tablereader import TableReader  # noqa: E402

scratch = sys.argv[1]
kbn = json.load(open(scratch + "/judge_kb_new.json"))
kbo = json.load(open(scratch + "/judge_kb_old.json"))
aft = np.asarray(kbn["aa_from_trna"])
names = kbn["aa_names"]
rows = json.load(open(scratch + "/judge_rows.json"))

DROP = 10


def per_family(rowset, kb, arm=None):
    out = {}
    for r in rowset:
        if r["status"] != "OK" or (arm and r["arm"] != arm):
            continue
        so = r["simOut"]
        bm = TableReader(os.path.join(so, "BulkMolecules"))
        idx = {m: k for k, m in enumerate(bm.readAttribute("objectNames"))}
        counts = bm.readColumn("counts")[DROP:]
        u = counts[:, [idx[m] for m in kb["uncharged_trna_names"]]].astype(float)
        c = counts[:, [idx[m] for m in kb["charged_trna_names"]]].astype(float)
        for i in range(aft.shape[0]):
            cols = np.where(aft[i] > 0)[0]
            if cols.size == 0:
                continue
            uu, cc = u[:, cols].sum(1), c[:, cols].sum(1)
            out.setdefault(names[i], {"u": [], "t": [], "c": []})
            out[names[i]]["u"].append(uu.mean())
            out[names[i]]["c"].append(cc.mean())
            out[names[i]]["t"].append((uu + cc).mean())
    return out


new = [r for r in rows["new"] if r["status"] == "OK"]
old = [r for r in rows["old"] if r["status"] == "OK"]
pn = per_family(new, kbn)
po = per_family(old, kbo)

print("=== WHICH FAMILIES CARRY THE CHARGED-FRACTION DROP (all 27 cells, all arms) ===")
kmN = np.asarray(kbn["trna_kms"], float)
kmO = np.asarray(kbo["trna_kms"], float)
tot_u_o = sum(np.mean(po[f]["u"]) for f in po)
tot_u_n = sum(np.mean(pn[f]["u"]) for f in pn)
tot_t_o = sum(np.mean(po[f]["t"]) for f in po)
tot_t_n = sum(np.mean(pn[f]["t"]) for f in pn)
print("aggregate uncharged counts OLD %.0f -> NEW %.0f  (delta %+.0f)" % (tot_u_o, tot_u_n, tot_u_n - tot_u_o))
print("%-20s %7s %7s %9s %9s %11s %9s" %
      ("family", "Km_old", "Km_new", "chg_old", "chg_new", "d_uncharged", "%of drop"))
recs = []
for i, f in enumerate(names):
    if f not in pn:
        continue
    co = np.mean(po[f]["c"]) / np.mean(po[f]["t"])
    cn = np.mean(pn[f]["c"]) / np.mean(pn[f]["t"])
    du = np.mean(pn[f]["u"]) - np.mean(po[f]["u"])
    recs.append((f, kmO[i], kmN[i], co, cn, du))
recs.sort(key=lambda r: -r[5])
tot_du = sum(r[5] for r in recs)
for f, ko, kn, co, cn, du in recs:
    print("%-20s %7.3f %7.3f %9.4f %9.4f %11.0f %8.1f%%"
          % (f, ko, kn, co, cn, du, 100.0 * du / tot_du))
touched = [r for r in recs if abs(r[2] / r[1] - 1) > 0.2]
print("families whose Km moved >20%%: %s" % [r[0] for r in touched])
print("their share of the uncharged-count increase: %.1f%%"
      % (100.0 * sum(r[5] for r in touched) / tot_du))

print("\n=== IS GLY's SPREAD SATURATING? per-isoacceptor charged fraction, equal arm, NEW ===")
for fam in ("GLY[c]", "LEU[c]", "PRO[c]"):
    i = names.index(fam)
    cols = np.where(aft[i] > 0)[0]
    mins, maxs, meds = [], [], []
    for r in new:
        if r["arm"] != "equ":
            continue
        gl = TableReader(os.path.join(r["simOut"], "GrowthLimits"))
        frac = np.atleast_2d(np.asarray(gl.readColumn("fraction_trna_charged"), float))[DROP:, cols]
        mins.append(np.median(frac.min(1)))
        maxs.append(np.median(frac.max(1)))
        meds.append(np.median(frac, axis=0))
    print("  %-8s n_iso=%d  median-over-time  min %.4f  max %.4f  (n=%d cells)"
          % (fam, cols.size, np.mean(mins), np.mean(maxs), len(mins)))
    print("           per-isoacceptor medians (cell-averaged): %s"
          % " ".join("%.3f" % x for x in np.mean(meds, axis=0)))
    print("           headroom: max possible spread given family charged fraction "
          "%.3f is %.3f ; observed %.3f -> %.0f%% of headroom"
          % (np.mean([np.mean(pn[fam]["c"][k]) / np.mean(pn[fam]["t"][k]) for k in range(len(pn[fam]["c"]))]),
             1.0, np.mean(maxs) - np.mean(mins), 100.0 * (np.mean(maxs) - np.mean(mins))))
