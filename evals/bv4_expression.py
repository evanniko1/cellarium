"""BV-4: simulated expression changes against measured ones (PRECISE-1K), for every contrast the corpus can match.

PRECISE-1K (Lamoureux et al. 2023, doi:10.1093/nar/gkad750) is RNA-seq of MG1655 under one protocol. Two of its
contrasts match a corpus design against basal: acetate against glucose (`wt_ac` vs `wt_glc`, condition/acetate) and
anaerobic against aerobic glucose (`wt_glc_anaero` vs `wt_glc`, condition/no_oxygen). Each is scored by
`sci2.rnaseq_concordance`: per-gene log2 fold changes, simulated (seed-mean over the corpus runs) against DESeq2
(unshrunk), with Pearson and Spearman correlation and sign agreement read against a shuffled-label null.

Run at two abundance floors, because the result depends on it (Platform Map section 17): the reader's default of 20
copies keeps only the most expressed genes (about 75 here), while a floor of 0.05 keeps most of the transcriptome. The
same concordance function scores both; only the simulated side's floor differs.

Both matched conditions are ones the knowledge-base fit is given (doubling time; and for no_oxygen, FNR, ArcA and CRP
switched on with fitted fold changes), so agreement here is partly calibration: this is the organism check the corpus
allows, not a test of prediction. RNA-seq is a cross-check, not ground truth.

    WCECOLI_DOCKER=<code image> .venv/Scripts/python.exe evals/bv4_expression.py    # writes bv4_expression.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "evals" / "results" / "bv4_expression.json"
CONTRASTS = [
    {"design": "condition/acetate", "contrast": {"column": "condition", "cond_A": "wt_glc", "cond_B": "wt_ac"}},
    {"design": "condition/no_oxygen", "contrast": {"column": "condition", "cond_A": "wt_glc", "cond_B": "wt_glc_anaero"}},
]
KEEP = ("verdict", "n_joined", "pearson_r", "spearman_rho", "sign_agreement", "null", "null_pearson_mean",
        "null_pearson_sd", "beats_null", "deming_slope", "n_reference_significant", "sign_agreement_significant",
        "join_qc", "note")


def main() -> int:
    from cellarium import provenance, sci2
    ok, msg = sci2.available()
    if not ok:
        print(msg, file=sys.stderr)
        return 2
    rows = []
    for c in CONTRASTS:
        ref = sci2.build_reference(c["contrast"])
        if "error" in ref:
            rows.append({"design": c["design"], "precise1k_contrast": c["contrast"], "error": ref["error"]})
            continue
        ref_flat = {g: v["log2FC"] for g, v in ref["reference_lfc"].items()}
        ref_sig = {g for g, v in ref["reference_lfc"].items()
                   if v.get("padj") is not None and v["padj"] < sci2.PADJ_SIG and abs(v["log2FC"]) >= sci2.DEG_SIG}
        for floor in (20.0, 0.05):
            detail = sci2.sim_lfc_detail(c["design"], "wildtype/basal", count_floor=floor)
            sim = detail.get("lfc") or {}
            r = sci2.concordance(sim, ref_flat, ref_sig=ref_sig) if sim else {"error": "no simulated log2FC"}
            rows.append({"design": c["design"], "precise1k_contrast": c["contrast"], "count_floor": floor,
                         **({"error": r["error"]} if "error" in r else
                            {k: r.get(k) for k in r if k in KEEP or k.startswith(("pearson", "spearman", "sign",
                                                                                     "null", "n_", "deming"))})})
            print(json.dumps(rows[-1], default=str)[:700])
    out = {"spec": "BV-4", "data": "PRECISE-1K (Lamoureux et al. 2023, doi:10.1093/nar/gkad750), snapshot "
                                   f"{sci2.PRECISE1K_SNAPSHOT['counts_sha256']}", "rows": rows,
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
