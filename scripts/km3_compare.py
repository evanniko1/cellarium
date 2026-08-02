"""Before/after comparison of the 3x3x3 matrix: OLD KMtf (mx_*) vs NEW stage-8 KMtf (km3_*).

Both sides are measured by the SAME code (km3_analyze.py), so the comparison is not between two
metric definitions. Reports mean +/- sd over the 9 cells of each arm, and separately per generation,
and the per-family GLY/LEU medians that the kinetic reference speaks to.
"""

import argparse
import json

ARMS = ["fam", "abu", "equ"]
LABEL = {"fam": "family (control)", "abu": "isoacceptor + abundance",
         "equ": "isoacceptor + equal"}


def load(path, prefix):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("ROW "):
                continue
            r = json.loads(line[4:])
            base = r["run"].rstrip("/").replace("\\", "/").split("/")[-1]
            r["arm"] = next((a for a in ARMS if base.startswith(prefix + "_" + a + "_")), "?")
            r["seed"] = base.split("_s")[-1]
            rows.append(r)
    return [r for r in rows if r.get("status") == "OK"]


def ms(v):
    v = [x for x in v if x == x]
    if not v:
        return float("nan"), float("nan"), 0
    m = sum(v) / len(v)
    s = (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5 if len(v) > 1 else 0.0
    return m, s, len(v)


def line(name, old, new, fmt="{:.4f}"):
    om, os_, on = ms(old)
    nm, ns, nn = ms(new)
    ratio = nm / om if om else float("nan")
    print(("{:<34} OLD " + fmt + " +/- " + fmt + " (N={})   NEW " + fmt + " +/- " + fmt
           + " (N={})   ratio {:.3f}").format(name, om, os_, on, nm, ns, nn, ratio))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    a = ap.parse_args(argv)
    old = load(a.old, "mx")
    new = load(a.new, "km3")
    print("cells OK: OLD {}  NEW {}".format(len(old), len(new)))

    for arm in ARMS:
        o = [r for r in old if r["arm"] == arm]
        n = [r for r in new if r["arm"] == arm]
        print()
        print("=" * 118)
        print("{}   OLD n={} cells   NEW n={} cells".format(LABEL[arm], len(o), len(n)))
        print("=" * 118)
        for key, nm, fmt in (
                ("charged_raw_mean", "charged fraction (raw counts)", "{:.4f}"),
                ("spread_median_worst_family", "within-family spread, median", "{:.3e}"),
                ("spread_worst_at_end", "within-family spread, at end", "{:.3e}"),
                ("spread_worst_any_step", "within-family spread, max", "{:.3e}"),
                ("doubling_min_from_rate", "doubling time (min)", "{:.2f}"),
                ("duration_min", "observed generation length (min)", "{:.2f}"),
                ("ppgpp_conc_mean", "ppgpp_conc (uM)", "{:.2f}"),
                ("rela_syn_total_mean", "rela_syn total", "{:.4f}"),
                ("uncharged_counts_mean", "uncharged tRNA counts", "{:.0f}")):
            line(nm, [r[key] for r in o], [r[key] for r in n], fmt)

    print()
    print("=" * 118)
    print("PER-FAMILY median-over-timesteps spread, isoacceptor+equal arm, mean +/- sd over 9 cells")
    print("Kinetic reference (N=12): GLY 0.348 +/- 0.032, LEU 0.248 +/- 0.014")
    print("=" * 118)
    oe = [r for r in old if r["arm"] == "equ"]
    ne = [r for r in new if r["arm"] == "equ"]
    fams = sorted(ne[0]["per_family_median"]) if ne else []
    agg = []
    for fam in fams:
        om, os_, _ = ms([r["per_family_median"][fam] for r in oe])
        nm, ns, _ = ms([r["per_family_median"][fam] for r in ne])
        agg.append((nm, fam, om, os_, ns))
    agg.sort(reverse=True)
    print("{:<22} {:>20} {:>20} {:>9}".format("family", "OLD median", "NEW median", "ratio"))
    for nm, fam, om, os_, ns in agg:
        print("{:<22} {:>9.4f} +/- {:<7.4f} {:>9.4f} +/- {:<7.4f} {:>9.2f}".format(
            fam, om, os_, nm, ns, nm / om if om else float("nan")))

    print()
    print("PER-GENERATION within-family median spread, isoacceptor+equal")
    print("{:<8} {:>22} {:>22}".format("gen", "OLD", "NEW"))
    for g in (0, 1, 2):
        om, os_, on = ms([r["spread_median_worst_family"] for r in oe if r["generation"] == g])
        nm, ns, nn = ms([r["spread_median_worst_family"] for r in ne if r["generation"] == g])
        print("{:<8} {:>10.4e}+/-{:<9.2e} {:>10.4e}+/-{:<9.2e}".format(g, om, os_, nm, ns))

    print()
    print("PER-GENERATION raw charged fraction, ALL arms pooled")
    print("{:<8} {:>22} {:>22}".format("gen", "OLD", "NEW"))
    for g in (0, 1, 2):
        om, os_, on = ms([r["charged_raw_mean"] for r in old if r["generation"] == g])
        nm, ns, nn = ms([r["charged_raw_mean"] for r in new if r["generation"] == g])
        print("{:<8} {:>10.4f}+/-{:<7.4f}(N={}) {:>10.4f}+/-{:<7.4f}(N={})".format(
            g, om, os_, on, nm, ns, nn))

    print()
    print("POOLED over all 27 cells")
    for key, nm, fmt in (("charged_raw_mean", "charged fraction (raw counts)", "{:.4f}"),
                         ("doubling_min_from_rate", "doubling time (min)", "{:.2f}"),
                         ("ppgpp_conc_mean", "ppgpp_conc (uM)", "{:.2f}"),
                         ("rela_syn_total_mean", "rela_syn total", "{:.4f}"),
                         ("uncharged_counts_mean", "uncharged tRNA counts", "{:.0f}")):
        line(nm, [r[key] for r in old], [r[key] for r in new], fmt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
