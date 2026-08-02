"""Paired (arm, seed, generation) OLD-vs-NEW deltas for the 3x3x3 matrix, plus a paired t on 27 pairs.

The two matrices are not the same trajectories -- they run on different simData -- but arm, seed and
generation index are matched one-to-one, so pairing removes the arm/seed/generation variance that
dominates the unpaired sd. Reported as: mean delta, sd of the delta, t = mean/(sd/sqrt(n)), df=n-1.

No p-value is printed from a table lookup; the t statistic and df are reported so the reader can
judge. A |t| below ~2.06 is not resolvable at df=26.
"""

import argparse
import json

ARMS = ["fam", "abu", "equ"]


def load(path, prefix):
    out = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("ROW "):
                continue
            r = json.loads(line[4:])
            if r.get("status") != "OK":
                continue
            base = r["run"].rstrip("/").replace("\\", "/").split("/")[-1]
            arm = next((a for a in ARMS if base.startswith(prefix + "_" + a + "_")), "?")
            out[(arm, base.split("_s")[-1], r["generation"])] = r
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    a = ap.parse_args(argv)
    old, new = load(a.old, "mx"), load(a.new, "km3")
    keys = sorted(set(old) & set(new))
    print("paired cells: {} (OLD {} NEW {})".format(len(keys), len(old), len(new)))
    unpaired = sorted(set(old) ^ set(new))
    if unpaired:
        print("UNPAIRED CELLS: {}".format(unpaired))

    print()
    print("{:<32} {:>12} {:>12} {:>12} {:>10} {:>7}".format(
        "quantity", "mean delta", "sd delta", "t", "df", "n"))
    for key, nm in (("charged_raw_mean", "charged fraction (raw)"),
                    ("uncharged_counts_mean", "uncharged tRNA counts"),
                    ("doubling_min_from_rate", "doubling time (min)"),
                    ("duration_min", "observed gen length (min)"),
                    ("ppgpp_conc_mean", "ppgpp_conc (uM)"),
                    ("rela_syn_total_mean", "rela_syn total"),
                    ("cellMass_ratio", "cellMass end/start")):
        d = [new[k][key] - old[k][key] for k in keys]
        n = len(d)
        m = sum(d) / n
        s = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
        t = m / (s / n ** 0.5) if s else float("inf")
        print("{:<32} {:>12.4f} {:>12.4f} {:>12.2f} {:>10d} {:>7d}".format(nm, m, s, t, n - 1, n))

    print()
    print("Same, restricted to the family control arm (9 pairs) -- the arm with no isoacceptor split")
    fk = [k for k in keys if k[0] == "fam"]
    for key, nm in (("charged_raw_mean", "charged fraction (raw)"),
                    ("doubling_min_from_rate", "doubling time (min)"),
                    ("duration_min", "observed gen length (min)"),
                    ("ppgpp_conc_mean", "ppgpp_conc (uM)")):
        d = [new[k][key] - old[k][key] for k in fk]
        n = len(d)
        m = sum(d) / n
        s = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
        t = m / (s / n ** 0.5) if s else float("inf")
        print("{:<32} {:>12.4f} {:>12.4f} {:>12.2f} {:>10d} {:>7d}".format(nm, m, s, t, n - 1, n))

    print()
    print("Doubling time delta BY GENERATION (all arms, 9 pairs each)")
    for g in (0, 1, 2):
        gk = [k for k in keys if k[2] == g]
        d = [new[k]["doubling_min_from_rate"] - old[k]["doubling_min_from_rate"] for k in gk]
        n = len(d)
        m = sum(d) / n
        s = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
        t = m / (s / n ** 0.5) if s else float("inf")
        print("  gen{}  delta {:+.2f} min  sd {:.2f}  t {:.2f}  df {}  n {}".format(
            g, m, s, t, n - 1, n))

    print()
    print("Observed generation length delta BY GENERATION (all arms)")
    for g in (0, 1, 2):
        gk = [k for k in keys if k[2] == g]
        d = [new[k]["duration_min"] - old[k]["duration_min"] for k in gk]
        n = len(d)
        m = sum(d) / n
        s = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
        t = m / (s / n ** 0.5) if s else float("inf")
        print("  gen{}  delta {:+.2f} min  sd {:.2f}  t {:.2f}  n {}".format(g, m, s, t, n))

    print()
    print("GLY and LEU medians in the isoacceptor+equal arm vs the kinetic reference")
    print("{:<8} {:>22} {:>22} {:>26}".format("family", "OLD (N=9)", "NEW (N=9)", "kinetic ref (N=12)"))
    ref = {"GLY[c]": (0.348, 0.032), "LEU[c]": (0.248, 0.014)}
    for fam, (rm, rs) in ref.items():
        ek = [k for k in keys if k[0] == "equ"]
        for tag, src in (("OLD", old), ("NEW", new)):
            pass
        o = [old[k]["per_family_median"][fam] for k in ek]
        n_ = [new[k]["per_family_median"][fam] for k in ek]
        om = sum(o) / len(o)
        os_ = (sum((x - om) ** 2 for x in o) / (len(o) - 1)) ** 0.5
        nm = sum(n_) / len(n_)
        ns = (sum((x - nm) ** 2 for x in n_) / (len(n_) - 1)) ** 0.5
        # z of NEW against the kinetic reference, using the NEW arm's own sd
        z = (nm - rm) / ns if ns else float("inf")
        print("{:<8} {:>10.4f} +/- {:<8.4f} {:>10.4f} +/- {:<8.4f} {:>12.3f} +/- {:<7.3f}  "
              "NEW-vs-ref z={:+.2f}".format(fam, om, os_, nm, ns, rm, rs, z))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
