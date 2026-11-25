"""BV-3: gene essentiality against the Keio collection, the whole-cell model beside iML1515 flux balance.

Two models are scored on the same metabolic genes against the same labels: iML1515 (growth-maximising flux balance,
PRAXIS-VirtualCell's E. coli model) and the whole-cell model's knockout prior (its homeostatic flux balance, read from
the gene-scope cache). Over the whole genome, the whole-cell model is scored against the 400-gene essential benchmark.
Keio essentiality is the label (Baba et al. 2006, doi:10.1038/msb4100050); it is a measurement of BW25113, not the
truth of MG1655, and a gene Keio could not delete is "essential" here by that convention.

    .venv/Scripts/python.exe evals/bv3_essentiality.py    # needs cobra (the fba extra); writes bv3_essentiality.json
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "evals" / "results" / "bv3_essentiality.json"


def confusion(pairs) -> dict:
    """pairs: (predicted_essential, keio_essential), None excluded."""
    tp = sum(1 for p, k in pairs if p and k)
    tn = sum(1 for p, k in pairs if p is False and k is False)
    fp = sum(1 for p, k in pairs if p and k is False)
    fn = sum(1 for p, k in pairs if p is False and k)
    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) or float("nan")
    return {"n": tp + tn + fp + fn, "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "mcc": round((tp * tn - fp * fn) / denom, 3) if denom == denom else None}


def main() -> int:
    from cellarium import fba, provenance, scope
    ok, msg = fba.available()
    if not ok:
        print(msg, file=sys.stderr)
        return 2
    bench = sorted(fba._keio_benchmark())
    rows = []
    for i in range(0, len(bench), 60):
        r = fba.fba_essentiality_panel(genes=bench[i:i + 60])
        if "error" in r:
            print(r["error"], file=sys.stderr)
            return 1
        rows += r.get("genes") or []
    fba_pairs = [(r["fba_essential"], r["keio_essential"]) for r in rows if r.get("keio_essential") is not None]
    wce_pairs = [(r["wcecoli_essential"], r["keio_essential"]) for r in rows
                 if r.get("keio_essential") is not None and r.get("wcecoli_essential") is not None]
    whole = scope.model_validation_summary()
    out = {"spec": "BV-3",
           "on_iml1515_metabolic_genes": {"n_genes": len(rows), "iml1515_fba": confusion(fba_pairs),
                                          "whole_cell_prior": confusion(wce_pairs),
                                          "n_without_a_whole_cell_call": len(rows) - len(wce_pairs)},
           "whole_cell_on_the_genome": {k: whole.get(k) for k in ("n_genes", "n_benchmark_essential",
                                                                  "agreement_counts", "essentiality_recall")},
           "labels": "Keio collection (Baba et al. 2006, doi:10.1038/msb4100050), BW25113",
           "fba_provenance": fba.provenance(),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out["on_iml1515_metabolic_genes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
