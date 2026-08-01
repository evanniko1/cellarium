"""Turn the ROW json lines emitted by mx_analyze.py into the matrix table and the arm-level summary.

Reads a file of mx_analyze output on stdin or by path. Prints:
  * one line per (arm, seed, generation) cell, including MISSING cells;
  * the arm-level worst spread across every cell, separately for 'worst over timesteps' and
    'at end of generation';
  * a per-generation breakdown so a generation effect would be visible if there is one;
  * the growth / ppGpp / relA columns;
  * an explicit list of missing or failed cells.

Nothing here re-derives a measurement. It only aggregates what mx_analyze measured.
"""

import argparse
import json
import sys

ARM_LABEL = {
    "fam": "family (control)",
    "abu": "isoacceptor + abundance",
    "equ": "isoacceptor + equal",
}
ARM_ORDER = ["fam", "abu", "equ"]


def parse(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("ROW "):
                rows.append(json.loads(line[4:]))
    return rows


def arm_of(run):
    base = run.rstrip("/").split("/")[-1]
    for a in ARM_ORDER:
        if base.startswith("mx_" + a + "_"):
            return a
    return "?"


def seed_of(run):
    return run.rstrip("/").split("/")[-1].split("_s")[-1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path")
    a = ap.parse_args(argv)
    rows = parse(a.path)
    if not rows:
        print("NO ROWS PARSED FROM " + a.path)
        return 1

    for r in rows:
        r["arm"] = arm_of(r["run"])
        r["seed"] = seed_of(r["run"])

    print("=" * 118)
    print("PER-CELL MATRIX  (spread = max-min of GrowthLimits/fraction_trna_charged within a family)")
    print("=" * 118)
    hdr = ("{:24s} {:4s} {:3s} {:9s} {:>6s} {:>8s} {:>12s} {:>12s} {:>9s} {:>9s} {:>10s} {:>9s} {:>4s}"
           .format("arm", "seed", "gen", "status", "steps", "dur_s", "spread_worst", "spread_end",
                   "doubl_min", "massratio", "ppgpp_mean", "relA_mean", "NaN"))
    print(hdr)
    print("-" * 118)
    missing = []
    for arm in ARM_ORDER:
        for seed in ["0", "1", "2"]:
            for gen in [0, 1, 2]:
                sel = [r for r in rows if r["arm"] == arm and r["seed"] == seed
                       and r.get("generation") == gen]
                if not sel:
                    missing.append((arm, seed, gen, "no row emitted"))
                    print("{:24s} {:4s} {:3d} {:9s}".format(ARM_LABEL[arm], seed, gen, "NO-ROW"))
                    continue
                r = sel[0]
                if r["status"] != "OK":
                    missing.append((arm, seed, gen, r.get("why", r["status"])))
                    print("{:24s} {:4s} {:3d} {:9s}  {}".format(
                        ARM_LABEL[arm], seed, gen, r["status"], r.get("why", "")[:60]))
                    continue
                print("{:24s} {:4s} {:3d} {:9s} {:6d} {:8.0f} {:12.3e} {:12.3e} {:9.2f} {:9.4f} "
                      "{:10.3f} {:9.4f} {:>4s}".format(
                          ARM_LABEL[arm], seed, gen, "OK", r["n_steps"], r["duration_s"],
                          r["spread_worst_any_step"], r["spread_worst_at_end"],
                          r["doubling_min_from_rate"], r["cellMass_ratio"],
                          r["ppgpp_conc_mean"], r["rela_syn_total_mean"],
                          "yes" if r["nan_any"] else "no"))

    ok = [r for r in rows if r.get("status") == "OK"]

    print()
    print("=" * 118)
    print("ARM SUMMARY  (worst over every seed and generation in that arm)")
    print("=" * 118)
    print("{:24s} {:6s} {:>14s} {:>14s} {:>12s} {:>12s} {:>12s}".format(
        "arm", "cells", "worst_spread", "worst_at_end", "doubl_min", "ppgpp_mean", "relA_mean"))
    for arm in ARM_ORDER:
        sel = [r for r in ok if r["arm"] == arm]
        if not sel:
            print("{:24s} {:6s}   NO CELLS MEASURED".format(ARM_LABEL[arm], "0"))
            continue
        w = max(r["spread_worst_any_step"] for r in sel)
        e = max(r["spread_worst_at_end"] for r in sel)
        d = sum(r["doubling_min_from_rate"] for r in sel) / len(sel)
        p = sum(r["ppgpp_conc_mean"] for r in sel) / len(sel)
        q = sum(r["rela_syn_total_mean"] for r in sel) / len(sel)
        print("{:24s} {:6d} {:14.3e} {:14.3e} {:12.2f} {:12.3f} {:12.4f}".format(
            ARM_LABEL[arm], len(sel), w, e, d, p, q))

    print()
    print("PER-GENERATION worst spread (does the answer change with generation?)")
    print("{:24s} {:>14s} {:>14s} {:>14s}".format("arm", "gen0", "gen1", "gen2"))
    for arm in ARM_ORDER:
        cells = []
        for gen in [0, 1, 2]:
            sel = [r for r in ok if r["arm"] == arm and r["generation"] == gen]
            cells.append(max((r["spread_worst_any_step"] for r in sel), default=float("nan")))
        print("{:24s} {:14.3e} {:14.3e} {:14.3e}".format(ARM_LABEL[arm], *cells))

    print()
    print("PER-GENERATION mean doubling time (min)")
    print("{:24s} {:>14s} {:>14s} {:>14s}".format("arm", "gen0", "gen1", "gen2"))
    for arm in ARM_ORDER:
        cells = []
        for gen in [0, 1, 2]:
            sel = [r for r in ok if r["arm"] == arm and r["generation"] == gen]
            cells.append(sum(r["doubling_min_from_rate"] for r in sel) / len(sel) if sel
                         else float("nan"))
        print("{:24s} {:14.2f} {:14.2f} {:14.2f}".format(ARM_LABEL[arm], *cells))

    print()
    print("TOP FAMILIES at the isoacceptor+equal arm, per generation (worst over seeds)")
    for gen in [0, 1, 2]:
        sel = [r for r in ok if r["arm"] == "equ" and r["generation"] == gen]
        if not sel:
            print("  gen{}: NO CELLS".format(gen))
            continue
        agg = {}
        for r in sel:
            for fam, v in r["per_family_worst"].items():
                agg[fam] = max(agg.get(fam, 0.0), v)
        top = sorted(agg.items(), key=lambda kv: -kv[1])[:4]
        print("  gen{}: ".format(gen) + ", ".join("{} {:.3e}".format(k, v) for k, v in top))

    print()
    print("DIVIDED / NaN audit")
    nd = [r for r in ok if not r["divided"]]
    nn = [r for r in ok if r["nan_any"]]
    print("  cells that did NOT write daughter state: {}".format(
        len(nd) if nd else 0))
    for r in nd:
        print("    {} gen{}".format(r["run"], r["generation"]))
    print("  cells with any NaN (excluding the undefined row 0 of instantaneous_growth_rate): {}"
          .format(len(nn)))
    for r in nn:
        print("    {} gen{}  fr={} ppgpp={} relA={} gr={} mass={}".format(
            r["run"], r["generation"], r["nan_fraction_trna_charged"], r["nan_ppgpp_conc"],
            r["nan_rela_syn"], r["nan_growth_rate"], r["nan_cellMass"]))

    print()
    if missing:
        print("MISSING OR FAILED CELLS ({}):".format(len(missing)))
        for arm, seed, gen, why in missing:
            print("  {} seed {} generation {}: {}".format(ARM_LABEL[arm], seed, gen, why))
    else:
        print("MISSING OR FAILED CELLS: none -- matrix is complete (3 arms x 3 seeds x 3 gens = 27)")
    print("CELLS_OK {}  CELLS_MISSING {}".format(len(ok), len(missing)))
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
