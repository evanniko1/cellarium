"""BV-8: the knowledge base's mRNA half-lives against Bernstein et al. 2002, by provenance class.

The knowledge base's half-lives are BUILT from measurements: wcEcoli's rna_half_lives.tsv takes Chen et al. 2015
(Mol Syst Biol, doi:10.15252/msb.20145794) where it has a gene and Bernstein et al. 2002's M9 column otherwise
(reconstruction/ecoli/scripts/rna_half_lives/convert_to_flat.py). So agreement with Bernstein is calibration by
construction. What the test measures is what ParCa does to its inputs: every mRNA transcription unit's FINAL
half-life is one of four classes (a fit, or on the floor, on the ceiling, or the imputation constant), and the
question is how much of the transcriptome rests on a measurement, and how far the fitted values sit from the
measured ones.

Organism: Bernstein et al. 2002 (PNAS 99:9697, doi:10.1073/pnas.112318199): about 80% of mRNAs have half-lives
between 3 and 8 min; half-lives are similar in rich and defined media. The per-gene table (Supporting Table 5,
LB and M9 columns) ships with the model checkout, so nothing is downloaded.

    WCECOLI_DOCKER=<code image> python evals/bv8_half_lives.py --wcecoli <checkout>      # writes bv8_half_lives.json
    python evals/bv8_half_lives.py --wcecoli <checkout> --units <cached deg_rate_units JSON>
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "evals" / "results" / "bv8_half_lives.json"
BERNSTEIN = "reconstruction/ecoli/scripts/rna_half_lives/data/3181Table5.csv"
LO, HI = 3.0, 8.0


def bernstein(path: Path) -> dict[str, dict]:
    out = {}
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.DictReader(f):
            sym = (row.get("Symbol") or "").strip()
            vals = {}
            for col, key in (("Half-lives in M9", "m9"), ("Half-lives in LB", "lb")):
                try:
                    vals[key] = float(row.get(col) or "")
                except ValueError:
                    continue
            if sym and vals:
                out[sym] = vals
    return out


def band(values: list[float], weights: list[float] | None = None) -> dict:
    """Share inside [3, 8] min, median and quartiles; expression-weighted when weights are given."""
    if not values:
        return {"n": 0}
    if weights is None:
        s = sorted(values)
        q = statistics.quantiles(s, n=4) if len(s) > 1 else [s[0]] * 3
        return {"n": len(s), "share_3_to_8_min": round(sum(LO <= v <= HI for v in s) / len(s), 3),
                "median_min": round(statistics.median(s), 2), "q1_min": round(q[0], 2), "q3_min": round(q[2], 2)}
    tot = sum(weights) or 1.0
    inside = sum(w for v, w in zip(values, weights) if LO <= v <= HI)
    return {"n": len(values), "share_3_to_8_min_expression_weighted": round(inside / tot, 3)}


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 3) if den else None


def analyse(units: dict, bern: dict[str, dict]) -> dict:
    us, cs = units["units"], units["cistrons"]
    organism = {"m9": band([v["m9"] for v in bern.values() if "m9" in v]),
                "lb": band([v["lb"] for v in bern.values() if "lb" in v])}
    by_class = {}
    for c in ("fit", "floor", "ceiling", "imputed"):
        sel = [u for u in us if u["class"] == c]
        by_class[c] = {**band([u["half_life_min"] for u in sel]),
                       "pct_of_mrna_expression": round(sum(u["pct_of_mrna_expression"] for u in sel), 3)}
    model_all = {**band([u["half_life_min"] for u in us]),
                 **band([u["half_life_min"] for u in us], [u["pct_of_mrna_expression"] for u in us])}
    inputs = {"n_mrna_cistrons": len(cs), "measured": sum(c["measured"] for c in cs),
              "imputed": sum(not c["measured"] for c in cs),
              "measured_distribution": band([c["input_half_life_min"] for c in cs if c["measured"]])}
    # per gene: a monocistronic unit's final half-life against Bernstein's M9 value, split by where the input came
    # from (equal to Bernstein's M9 value to the flat file's one decimal: Bernstein; otherwise Chen)
    inp = {}
    for c in cs:
        inp.setdefault(c["symbol"], c)
    pairs = {"input_from_bernstein": [], "input_from_chen": []}
    moved = {"input_from_bernstein": [], "input_from_chen": []}
    for u in us:
        if u["class"] != "fit" or len(u["cistrons"]) != 1:
            continue
        sym = u["cistrons"][0]
        b = bern.get(sym, {}).get("m9")
        c = inp.get(sym)
        if b is None or c is None or not c["measured"]:
            continue
        src = "input_from_bernstein" if abs(round(b, 1) - round(c["input_half_life_min"], 1)) < 0.051 else \
            "input_from_chen"
        pairs[src].append((u["half_life_min"], b))
        moved[src].append(math.log2(u["half_life_min"] / c["input_half_life_min"]))
    per_gene = {}
    for src, pr in pairs.items():
        per_gene[src] = {"n": len(pr), "spearman_model_vs_bernstein_m9": spearman([a for a, _ in pr], [b for _, b in pr]),
                         "median_log2_model_over_bernstein": round(statistics.median(math.log2(a / b) for a, b in pr), 3)
                         if pr else None,
                         "median_abs_log2_final_over_input": round(statistics.median(abs(x) for x in moved[src]), 3)
                         if moved[src] else None}
    return {"organism_bernstein_2002": organism, "model_final_half_lives": model_all, "model_by_class": by_class,
            "knowledge_base_inputs": inputs, "per_gene_monocistronic_fit_units": per_gene,
            "imputation_constant_min": units.get("imputation_constant_min"),
            "rate_floor_as_half_life_min": units.get("rate_floor_as_half_life_min"),
            "rate_ceiling_as_half_life_min": units.get("rate_ceiling_as_half_life_min")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wcecoli", required=True, type=Path)
    ap.add_argument("--units", type=Path, help="a cached reader.deg_rate_units() result")
    a = ap.parse_args(argv)
    from cellarium import provenance
    if a.units:
        units = json.loads(a.units.read_text(encoding="utf-8"))
    else:
        from cellarium import reader
        units = reader.deg_rate_units()
    res = analyse(units, bernstein(a.wcecoli / BERNSTEIN))
    out = {"spec": "BV-8", "knowledge_base": "3b2f8ebd (the corpus fit)",
           "in_sample": ("calibration by construction: the inputs are Chen et al. 2015 and, where Chen lacks a gene, "
                         "Bernstein et al. 2002's M9 column; the test is what ParCa does to them"),
           "source_table": BERNSTEIN + " (in the model checkout; Bernstein et al. 2002 Supporting Table 5)",
           **res, "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("organism_bernstein_2002", "model_final_half_lives", "model_by_class",
                                          "knowledge_base_inputs", "per_gene_monocistronic_fit_units")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
