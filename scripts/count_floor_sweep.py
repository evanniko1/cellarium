"""SCI-2 — where does the abundance floor stop hiding biology and start admitting noise?

THE PROBLEM, measured rather than suspected. The all-gene reader drops any gene below a mean copy number in
either arm. That floor was hard-coded at 20.0, and on the first real run of the acetate-vs-glucose
concordance it left **75 of ~4,300 genes**. The measured contrast has 999 significantly differentially
expressed genes; the simulation could see **34** of them. So the concordance was computed over 3.4% of the
signal, and over the wrong 3.4%: what clears a floor of 20 molecules per cell is the high-abundance head —
ribosomal proteins, translation factors — the genes most dominated by growth rate and least informative
about which carbon source the cell is on.

WHY LOWERING IT IS A TRADE AND NOT A FIX. Most bacterial transcripts are present at single-digit copies per
cell. At a low floor the per-gene ratio is dominated by counting noise across seeds, and a correlation
computed over thousands of noisy genes can look respectable while meaning nothing. There is no obviously
correct setting, so this measures the turnover instead of picking one.

WHAT IT REPORTS PER FLOOR, and why each column is here:
  n_genes            how much of the transcriptome survives
  n_sig_visible      how many of the reference's significant genes the simulation can even see — the number
                     that decides whether this is a test of the model at all
  pearson_r          concordance
  null_pearson_r     the SAME statistic on shuffled gene labels. The decisive column: r rising while null_r
                     rises with it is noise, not signal.
  r_minus_null       what is left after the null is subtracted
  sign_concordance   computed AFTER median-centring, so it is not the global cell-size shift agreeing with
                     itself (which is what made the raw number read 0.971 when the centred one is 0.529)

    python scripts/count_floor_sweep.py                       # the default ladder
    python scripts/count_floor_sweep.py --floors 0.5 2 5 20   # a custom one
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "data" / "sci2_count_floor_sweep.json"
DEFAULT_FLOORS = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", default="condition/acetate")
    ap.add_argument("--reference", default="wildtype/basal")
    ap.add_argument("--cond-a", default="wt_glc")
    ap.add_argument("--cond-b", default="wt_ac")
    ap.add_argument("--floors", type=float, nargs="*", default=DEFAULT_FLOORS)
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")          # the reader runs in the container; it needs WCECOLI_DOCKER
    from cellarium import sci2

    ok, why = sci2.available()
    if not ok:
        print(f"SCI-2 unavailable: {why}", file=sys.stderr)
        return 2

    contrast = {"cond_A": args.cond_a, "cond_B": args.cond_b}
    print(f"reference: DESeq2 {args.cond_b} vs {args.cond_a} (built once, reused for every floor)", flush=True)
    ref = sci2.build_reference(contrast)
    if "error" in ref:
        print(f"reference failed: {ref['error']}", file=sys.stderr)
        return 1
    ref_flat = {g: v["log2FC"] for g, v in ref["reference_lfc"].items()}
    ref_sig = {g for g, v in ref["reference_lfc"].items()
               if v.get("padj") is not None and v["padj"] < sci2.PADJ_SIG and abs(v["log2FC"]) >= sci2.DEG_SIG}
    print(f"  {len(ref_flat)} genes, {len(ref_sig)} significant "
          f"(padj<{sci2.PADJ_SIG}, |log2FC|>={sci2.DEG_SIG})\n", flush=True)

    rows = []
    for floor in sorted(args.floors, reverse=True):
        t0 = time.time()
        detail = sci2.sim_lfc_detail(args.design, args.reference, count_floor=floor)
        sim = detail.get("lfc") or {}
        if not sim:
            print(f"floor {floor:>5}: no genes returned ({detail.get('error')})", flush=True)
            continue
        res = sci2.concordance(sim, ref_flat, ref_sig=ref_sig)
        visible_sig = len(ref_sig & set(sim))
        r, nr = res.get("pearson_r"), res.get("null_pearson_r")
        row = {
            "count_floor": floor,
            "n_genes": len(sim),
            "n_sig_visible": visible_sig,
            "pct_of_significant_visible": round(100 * visible_sig / max(1, len(ref_sig)), 1),
            "pearson_r": r,
            "null_pearson_r": nr,
            "r_minus_null": (None if r is None or nr is None else round(abs(r) - abs(nr), 4)),
            "spearman_rho": res.get("spearman_rho"),
            "deming_slope": res.get("deming_slope"),
            "sign_concordance": res.get("sign_concordance"),
            "median_shift_removed": detail.get("median_shift_removed"),
            "seconds": round(time.time() - t0, 1),
        }
        # A correlation over 75 genes and one over 1,379 are not comparable as point estimates, and reading
        # the ladder without that will pick a spurious optimum: the apparent peak at floor 10 sits at
        # r/SE = 2.9 on n=115 while the bottom of the ladder sits at 7.0 on n=1,379. So each row carries how
        # many standard errors it is from "no relationship" — which is the number the ladder is actually
        # about. SE(r) ~ 1/sqrt(n-3); sign concordance is a proportion, SE ~ sqrt(0.25/n) under the null of
        # 0.5.
        n = row["n_genes"]
        row["se_pearson"] = round(1 / math.sqrt(max(n - 3, 1)), 4)
        row["pearson_over_se"] = (None if r is None else round(r / row["se_pearson"], 2))
        s = row["sign_concordance"]
        se_s = math.sqrt(0.25 / n)
        row["sign_z_vs_coinflip"] = (None if s is None else round((s - 0.5) / se_s, 2))
        rows.append(row)
        print(f"floor {floor:>5}: n={row['n_genes']:>5}  sig_visible={visible_sig:>4} "
              f"({row['pct_of_significant_visible']:>4}%)  r={r} (r/SE={row['pearson_over_se']})  null={nr}  "
              f"sign={row['sign_concordance']} (z={row['sign_z_vs_coinflip']})  [{row['seconds']}s]",
              flush=True)

    payload = {
        "design": args.design, "reference": args.reference, "contrast": contrast,
        "n_reference_genes": len(ref_flat), "n_reference_significant": len(ref_sig),
        "normalisation": "median-centred sim LFC (see sci2.sim_lfc_detail)",
        "rows": rows,
        "how_to_read": (
            "n_sig_visible decides whether the comparison is a test of the MODEL or a test of the "
            "high-abundance head. r_minus_null decides whether a rising correlation is signal: if r and "
            "null_pearson_r rise together as the floor drops, the extra genes are contributing noise that "
            "the statistic is mistaking for agreement."),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwritten: {OUT.relative_to(ROOT)}")

    best = [r for r in rows if r["r_minus_null"] is not None]
    if best:
        top = max(best, key=lambda r: r["r_minus_null"])
        strongest = max(best, key=lambda r: abs(r["pearson_over_se"] or 0))
        med = statistics.median([r["r_minus_null"] for r in best])
        print(f"largest r-minus-null:  floor {top['count_floor']} ({top['r_minus_null']}, n={top['n_genes']})"
              f"  — but at r/SE={top['pearson_over_se']}, which on n={top['n_genes']} is not a reliable "
              "optimum")
        print(f"most SIGNIFICANT:      floor {strongest['count_floor']} (r/SE={strongest['pearson_over_se']}, "
              f"sign z={strongest['sign_z_vs_coinflip']}, n={strongest['n_genes']}, "
              f"{strongest['pct_of_significant_visible']}% of the real signal visible)")
        print(f"median r-minus-null across floors: {round(med, 4)}")
        print("Read the LADDER, not any single row: a point estimate on 75 genes and one on 1,379 are not "
              "comparable, and the largest r is not the most trustworthy r.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
