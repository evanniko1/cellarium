"""BV-5: protein abundances and their changes against Schmidt et al. 2016's mass-spectrometry proteome.

Schmidt et al. 2016 (Nature Biotechnology 34:104, doi:10.1038/nbt.3418) measured absolute copies per cell for more
than 2,300 proteins in 22 conditions (strain BW25113). Its Supplementary Table S6 (the combined final table) is the
organism side; the file is the publisher's supplementary workbook, downloaded into its own folder and read with an
isolated interpreter:

  data/reference/schmidt2016/41587_2016_BFnbt3418_MOESM18_ESM.xlsx  (16,460,041 bytes, SHA-256 c7c7f918...,
  https://static-content.springer.com/esm/art%3A10.1038%2Fnbt.3418/MediaObjects/41587_2016_BFnbt3418_MOESM18_ESM.xlsx)

The model side is the corpus's protein means through the reader (differential.all_gene_lfc, kind protein, with the
two-component sensor correction), wildtype/basal for glucose and the fitted conditions acetate and succinate. Scored
by sci2.concordance, the function BV-4 uses, at the reader's floor of 20 copies and at 0.05. Every statistic is
split into the condition's FITTED genes (targets of its active factors: crp in acetate; crp and dcuR in succinate)
and the rest, because the fitted ones are calibration by construction.

    WCECOLI_DOCKER=<code image> python -I evals/bv5_proteome.py     # writes evals/results/bv5_proteome.json
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "evals" / "results" / "bv5_proteome.json"
TABLE = REPO / "data" / "reference" / "schmidt2016" / "41587_2016_BFnbt3418_MOESM18_ESM.xlsx"
SHA256 = "c7c7f91849a98207a97d947a1605514269ec1c1ee253ed9cd1e3325cbcbed99f"
CONTRASTS = [("condition/acetate", "acetate", "Acetate"), ("condition/succinate", "succinate", "Succinate")]


def schmidt(path: Path) -> dict[str, dict[str, float]]:
    """b-number -> {condition: copies per cell}, from the first (copies per cell) block of Table S6."""
    from openpyxl import load_workbook
    ws = load_workbook(path, read_only=True, data_only=True)["Table S6"]
    rows = ws.iter_rows(values_only=True)
    for _ in range(2):
        next(rows)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    first = {}
    for i, h in enumerate(header):
        if i >= 7 and h and h not in first:          # the first block: copies per cell
            first[h] = i
    b_idx = header.index("Bnumber")
    out = {}
    for r in rows:
        b = r[b_idx] if b_idx < len(r) else None
        if not b:
            continue
        vals = {}
        for name, i in first.items():
            try:
                vals[name] = float(r[i])
            except (TypeError, ValueError):
                continue
        out[str(b).strip().lower()] = vals
    return out


def _spearman(x, y):
    from scipy import stats
    if len(x) < 3:
        return None
    return round(float(stats.spearmanr(x, y).statistic), 3)


def main() -> int:
    import hashlib

    from cellarium import differential, provenance, sci2
    h = hashlib.sha256(TABLE.read_bytes()).hexdigest()
    if h != SHA256:
        print(f"{TABLE} does not match the recorded SHA-256 ({h}); refusing to score against it", file=sys.stderr)
        return 2
    org = schmidt(TABLE)
    bmap = {k.lower(): v.lower() for k, v in sci2._bnumber_map().items()}
    fits = json.loads((REPO / "data" / "parca" / "condition_fits.json").read_text(encoding="utf-8"))["conditions"]
    rows = []
    for design, cond, col in CONTRASTS:
        fitted = {g.lower() for g in fits.get(cond, {}).get("fitted_targets", [])}
        for floor in (20.0, 0.05):
            out = differential.all_gene_lfc(design, "wildtype/basal", kind="protein", count_floor=floor)
            lfc = out.get("lfc") if isinstance(out, dict) else None
            if not isinstance(lfc, dict):
                rows.append({"design": design, "count_floor": floor, "error": str(out)[:300]})
                continue
            sim, absolute = {}, {"glucose": [], col: []}
            sym_of = {}
            for gid, v in lfc.items():
                sym = str(v.get("symbol") or gid).lower()
                b = bmap.get(sym)
                if not b or b not in org:
                    continue
                sym_of[b] = sym
                if v.get("log2fc") is not None:
                    sim[b] = v["log2fc"]
                o = org[b]
                if v.get("reference") is not None and o.get("Glucose"):
                    absolute["glucose"].append((v["reference"], o["Glucose"]))
                if v.get("target") is not None and o.get(col):
                    absolute[col].append((v["target"], o[col]))
            ref = {b: math.log2(o[col] / o["Glucose"]) for b, o in org.items()
                   if o.get(col) and o.get("Glucose") and o[col] > 0 and o["Glucose"] > 0}
            split = {}
            for name, keep in (("all", lambda b: True), ("fitted", lambda b: sym_of.get(b) in fitted),
                               ("not_fitted", lambda b: sym_of.get(b) not in fitted)):
                s = {b: v for b, v in sim.items() if keep(b)}
                r = sci2.concordance(s, ref) if s else {"error": "no genes"}
                split[name] = {k: r.get(k) for k in ("n_genes", "pearson_r", "spearman_rho", "sign_concordance",
                                                     "null_pearson_r", "null_pearson_sd", "deming_slope", "verdict",
                                                     "error") if k in r}
            rows.append({"design": design, "count_floor": floor, "n_target_runs": out.get("n_target_runs"),
                         "n_reference_runs": out.get("n_reference_runs"),
                         "absolute_spearman": {k: {"n": len(v), "rho": _spearman([a for a, _ in v], [b for _, b in v])}
                                               for k, v in absolute.items()},
                         "fold_change_concordance": split,
                         "n_fitted_genes_in_condition": len(fitted)})
            print(json.dumps(rows[-1], default=str)[:900])
    out = {"spec": "BV-5", "organism": ("Schmidt et al. 2016 (doi:10.1038/nbt.3418), Supplementary Table S6, copies "
                                        "per cell, strain BW25113"),
           "table": {"file": TABLE.relative_to(REPO).as_posix(), "sha256": SHA256, "bytes": TABLE.stat().st_size},
           "model": "corpus fit 3b2f8ebd, steady state, protein means through the reader (sensor-corrected)",
           "in_sample": ("acetate and succinate are base-fitted conditions: growth and composition are fitted, and "
                         "their active factors' targets (the 'fitted' split) are calibration; absolute abundance on "
                         "glucose is calibration (synthesis is set from measured expression)"),
           "rows": rows, "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
