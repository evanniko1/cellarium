"""Aggregate the ROW json lines from km3_analyze.py into the matrix table and arm-level summary.

Same shape as mx_report.py but takes --prefix (so the new-ParCa matrix km3_* can be reported without
touching the old mx_* report) and reports the MEDIAN within-family spread alongside the max and the
end-of-generation value, plus the raw-count charged fraction.

Nothing here re-derives a measurement; it only aggregates what km3_analyze measured.
"""

import argparse
import json

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


def mean(v):
    v = [x for x in v if x == x]
    return sum(v) / len(v) if v else float("nan")


def sd(v):
    v = [x for x in v if x == x]
    if len(v) < 2:
        return float("nan")
    m = sum(v) / len(v)
    return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path")
    ap.add_argument("--prefix", default="km3")
    a = ap.parse_args(argv)
    rows = parse(a.path)
    if not rows:
        print("NO ROWS PARSED FROM " + a.path)
        return 1

    def arm_of(run):
        base = run.rstrip("/").replace("\\", "/").split("/")[-1]
        for arm in ARM_ORDER:
            if base.startswith(a.prefix + "_" + arm + "_"):
                return arm
        return "?"

    for r in rows:
        r["arm"] = arm_of(r["run"])
        r["seed"] = r["run"].rstrip("/").replace("\\", "/").split("/")[-1].split("_s")[-1]

    print("=" * 132)
    print("PER-CELL MATRIX  (spread = max-min of GrowthLimits/fraction_trna_charged within a family)")
    print("=" * 132)
    print("{:24s} {:4s} {:3s} {:8s} {:>6s} {:>7s} {:>11s} {:>11s} {:>11s} {:>8s} {:>8s} {:>8s} {:>9s} {:>8s} {:>4s}"
          .format("arm", "seed", "gen", "status", "steps", "dur_min", "spread_med", "spread_max",
                  "spread_end", "chg_raw", "doubl_m", "massrat", "ppgpp", "relA", "NaN"))
    print("-" * 132)
    missing = []
    for arm in ARM_ORDER:
        for seed in ["0", "1", "2"]:
            for gen in [0, 1, 2]:
                sel = [r for r in rows if r["arm"] == arm and r["seed"] == seed
                       and r.get("generation") == gen]
                if not sel:
                    missing.append((arm, seed, gen, "no row emitted"))
                    print("{:24s} {:4s} {:3d} {:8s}".format(ARM_LABEL[arm], seed, gen, "NO-ROW"))
                    continue
                r = sel[0]
                if r["status"] != "OK":
                    missing.append((arm, seed, gen, r.get("why", r["status"])))
                    print("{:24s} {:4s} {:3d} {:8s}  {}".format(
                        ARM_LABEL[arm], seed, gen, r["status"], r.get("why", "")[:70]))
                    continue
                print("{:24s} {:4s} {:3d} {:8s} {:6d} {:7.1f} {:11.3e} {:11.3e} {:11.3e} "
                      "{:8.4f} {:8.2f} {:8.4f} {:9.3f} {:8.4f} {:>4s}".format(
                          ARM_LABEL[arm], seed, gen, "OK", r["n_steps"], r["duration_min"],
                          r["spread_median_worst_family"], r["spread_worst_any_step"],
                          r["spread_worst_at_end"], r["charged_raw_mean"],
                          r["doubling_min_from_rate"], r["cellMass_ratio"],
                          r["ppgpp_conc_mean"], r["rela_syn_total_mean"],
                          "yes" if r["nan_any"] else "no"))

    ok = [r for r in rows if r.get("status") == "OK"]

    print()
    print("=" * 132)
    print("ARM SUMMARY")
    print("=" * 132)
    print("{:24s} {:>5s} {:>13s} {:>13s} {:>13s} {:>17s} {:>10s} {:>10s} {:>10s}".format(
        "arm", "cells", "med_spread*", "max_spread", "end_spread", "charged_raw", "doubl_m",
        "ppgpp", "relA"))
    print("  * med_spread is the WORST family's median-over-timesteps, averaged over cells")
    for arm in ARM_ORDER:
        sel = [r for r in ok if r["arm"] == arm]
        if not sel:
            print("{:24s} {:>5s}   NO CELLS MEASURED".format(ARM_LABEL[arm], "0"))
            continue
        print("{:24s} {:5d} {:13.3e} {:13.3e} {:13.3e} {:9.4f}+/-{:6.4f} {:10.2f} {:10.3f} {:10.4f}"
              .format(ARM_LABEL[arm], len(sel),
                      mean([r["spread_median_worst_family"] for r in sel]),
                      max(r["spread_worst_any_step"] for r in sel),
                      mean([r["spread_worst_at_end"] for r in sel]),
                      mean([r["charged_raw_mean"] for r in sel]),
                      sd([r["charged_raw_mean"] for r in sel]),
                      mean([r["doubling_min_from_rate"] for r in sel]),
                      mean([r["ppgpp_conc_mean"] for r in sel]),
                      mean([r["rela_syn_total_mean"] for r in sel])))

    for label, key, fmt in (
            ("PER-GENERATION median within-family spread (worst family, mean over seeds)",
             "spread_median_worst_family", "{:14.3e}"),
            ("PER-GENERATION end-of-generation spread (worst family, mean over seeds)",
             "spread_worst_at_end", "{:14.3e}"),
            ("PER-GENERATION raw-count charged fraction (mean over seeds)",
             "charged_raw_mean", "{:14.4f}"),
            ("PER-GENERATION doubling time from growth rate, min (mean over seeds)",
             "doubling_min_from_rate", "{:14.2f}"),
            ("PER-GENERATION ppgpp_conc uM (mean over seeds)", "ppgpp_conc_mean", "{:14.3f}"),
            ("PER-GENERATION rela_syn total (mean over seeds)", "rela_syn_total_mean",
             "{:14.4f}")):
        print()
        print(label)
        print("{:24s} {:>14s} {:>14s} {:>14s}".format("arm", "gen0", "gen1", "gen2"))
        for arm in ARM_ORDER:
            cells = []
            for gen in [0, 1, 2]:
                sel = [r for r in ok if r["arm"] == arm and r["generation"] == gen]
                cells.append(mean([r[key] for r in sel]) if sel else float("nan"))
            print(("{:24s} " + fmt + " " + fmt + " " + fmt).format(ARM_LABEL[arm], *cells))

    print()
    print("TOP FAMILIES by median-over-timesteps spread, per arm per generation (worst over seeds)")
    for arm in ARM_ORDER:
        for gen in [0, 1, 2]:
            sel = [r for r in ok if r["arm"] == arm and r["generation"] == gen]
            if not sel:
                print("  {:24s} gen{}: NO CELLS".format(ARM_LABEL[arm], gen))
                continue
            agg = {}
            for r in sel:
                for fam, v in r["per_family_median"].items():
                    agg[fam] = max(agg.get(fam, 0.0), v)
            top = sorted(agg.items(), key=lambda kv: -kv[1])[:4]
            print("  {:24s} gen{}: ".format(ARM_LABEL[arm], gen)
                  + ", ".join("{} {:.3e}".format(k, v) for k, v in top))

    print()
    print("DIVIDED / NaN audit")
    nd = [r for r in ok if not r["divided"]]
    nn = [r for r in ok if r["nan_any"]]
    print("  cells that did NOT write daughter state: {}".format(len(nd)))
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
        print("MISSING OR FAILED CELLS: none -- matrix complete (3 arms x 3 seeds x 3 gens = 27)")
    print("CELLS_OK {}  CELLS_MISSING {}".format(len(ok), len(missing)))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
