"""The nitrate re-check's anaerobic response: the model against the organism, and against its own fitted inputs.

Three sources, each recomputed here:

  model     `differential.all_gene_lfc` through the simulator's reader (protein; the reader's 20-copy floor), on the
            same corpus runs as evals/results/regulation_scope.json: plus_nitrate against no_oxygen, and no_oxygen
            against basal. The nar proteins sit under the floor in both arms of the second contrast, so the
            differential leaves them out; their change is read from the two arms' means as regulation_scope.json
            records them. That figure is untested, and the artefact says so.
  organism  PRECISE-1K (Lamoureux et al. 2023, doi:10.1093/nar/gkad750) through `sci2.build_reference`: DESeq2,
            unshrunk, MG1655. Two contrasts: anaerobic against aerobic glucose, and anaerobic nitrate against
            anaerobic glucose.
  inputs    the knowledge base's fitted fold changes (fold_changes.tsv in the wcEcoli checkout): NarL and FNR at nar
            and frdA, and whether frdA has an FNR or ArcA entry at all.

The checkout is passed as an argument, not through WCECOLI_DIR, because setting WCECOLI_DIR switches the reader from
the Docker image to a native install.

    WCECOLI_DOCKER=<code image> .venv/Scripts/python.exe evals/anaerobic_response.py --wcecoli <checkout>
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

RES = REPO / "evals" / "results"
OUT = RES / "anaerobic_response.json"
FOLD_CHANGES = "reconstruction/ecoli/flat/fold_changes.tsv"

MODEL_GENES = ("grcA", "nuoA", "nuoB", "nuoE", "nuoF", "nuoG", "narG", "narH", "narJ", "narI", "narK", "frdA", "frdB",
               "frdC", "frdD", "cydA", "cydB", "hcp", "yeaR", "dmsA", "narX", "narL")
NAR = ("narG", "narH", "narJ", "narI")
MEASURED_GENES = ("narG", "narH", "narJ", "narI", "narK", "frdA", "frdB", "nuoA", "cydA", "hcp")
MODEL_CONTRASTS = (("plus_nitrate_vs_no_oxygen_protein", "condition/plus_nitrate", "condition/no_oxygen"),
                   ("no_oxygen_vs_basal_protein", "condition/no_oxygen", "wildtype/basal"))
MEASURED_CONTRASTS = (
    ("anaerobic_vs_aerobic_glucose", {"column": "condition", "cond_A": "wt_glc", "cond_B": "wt_glc_anaero"}),
    ("anaerobic_nitrate_vs_anaerobic", {"column": "condition", "cond_A": "wt_glc_anaero", "cond_B": "no3_anaero"}),
)
KB_PAIRS = {"narL": ("narG", "narH", "narJ", "narI", "frdA"), "fnr": NAR}


def model_part() -> tuple[dict, dict]:
    """Per-gene protein log2 fold changes for both model contrasts, and the run counts behind them."""
    from cellarium import differential
    out, runs = {}, {}
    for key, target, reference in MODEL_CONTRASTS:
        r = differential.all_gene_lfc(target, reference, kind="protein")
        if "error" in r:
            raise SystemExit(f"{target} vs {reference}: {r['error']}")
        by = {str(v.get("symbol")): v for v in (r.get("lfc") or {}).values() if v.get("symbol")}
        out[key] = {g: round(by[g]["log2fc"], 3) for g in MODEL_GENES
                    if by.get(g) and by[g].get("log2fc") is not None}
        runs[target.split("/")[-1]] = r.get("n_target_runs")
        runs.setdefault(reference.split("/")[-1], r.get("n_reference_runs"))
        if runs[reference.split("/")[-1]] != r.get("n_reference_runs"):
            raise SystemExit(f"{reference} has {r.get('n_reference_runs')} runs here and {runs[reference.split('/')[-1]]} "
                             "in the other contrast")
    return out, runs


def below_floor(regulation_scope: dict) -> dict:
    """The nar proteins' anaerobic change from the two arms' means, as regulation_scope.json records them."""
    def levels(reference):
        return next(r for r in regulation_scope["gene_level"]
                    if r["regulon"] == "nar_nitrate" and r["reference"] == reference)["regulon_levels"]
    vs_no2, vs_wt = levels("condition/no_oxygen"), levels("wildtype/basal")
    rows = {}
    for g in NAR:
        a, b = vs_no2[g]["reference"], vs_wt[g]["reference"]        # the no_oxygen mean, the basal mean
        rows[g] = {"no_oxygen_mean": a, "basal_mean": b, "log2fc_from_means": round(math.log2(a / b), 3)}
    return rows


def measured_part() -> dict:
    from cellarium import sci2
    ok, msg = sci2.available()
    if not ok:
        raise SystemExit(msg)
    bmap = json.loads((REPO / "data" / "cache" / "bnumber_map.json").read_text(encoding="utf-8"))
    out = {}
    for key, contrast in MEASURED_CONTRASTS:
        ref = sci2.build_reference(contrast)
        if "error" in ref:
            raise SystemExit(f"{key}: {ref['error']}")
        lfc = ref["reference_lfc"]
        out[key] = {g: round(lfc[bmap[g]]["log2FC"], 2) for g in MEASURED_GENES
                    if bmap.get(g) in lfc and lfc[bmap[g]].get("log2FC") is not None}
    return out


def kb_fold_changes(path: Path) -> dict:
    """NarL's and FNR's fitted fold changes at nar and frdA, and whether frdA has an FNR or ArcA entry."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f, delimiter="\t")]
    mean = {(r["TF"], r["Target"]): float(r["log2 FC mean"]) for r in rows}
    out = {tf: {g: mean[(tf, g)] for g in targets if (tf, g) in mean} for tf, targets in KB_PAIRS.items()}
    out["frdA_has_no_fnr_or_arcA_entry"] = not any((tf, "frdA") in mean for tf in ("fnr", "arcA"))
    return out


def checkout_state(root: Path) -> dict:
    """Which commit the table was read at, and whether the working tree changes it (the campaign checkout carries
    uncommitted changes elsewhere)."""
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60).stdout.strip()
    return {"file": FOLD_CHANGES, "commit": git("rev-parse", "--short=8", "HEAD"),
            "modified_in_working_tree": bool(git("status", "--porcelain", "--", FOLD_CHANGES))}


def build(wcecoli: Path) -> dict:
    from cellarium import provenance
    reg = json.loads((RES / "regulation_scope.json").read_text(encoding="utf-8"))
    model, runs = model_part()
    floor = below_floor(reg)
    for g, row in floor.items():
        model["no_oxygen_vs_basal_protein"].setdefault(g, row["log2fc_from_means"])
    return {
        "spec": "nitrate re-check, 2026-11-25",
        "source": "differential.all_gene_lfc through the simulator's reader (protein; count floor 20), the same runs as "
                  "evals/results/regulation_scope.json; generated by evals/anaerobic_response.py",
        "runs": {"plus_nitrate": runs["plus_nitrate"], "no_oxygen": runs["no_oxygen"], "basal": runs["basal"]},
        **model,
        "below_the_count_floor": {"note": "nar proteins sit under 20 copies in both arms, so the differential leaves "
                                          "them out; their anaerobic change is read from the two arms' means, untested",
                                  **floor},
        "measured_precise1k": {"note": "DESeq2, unshrunk, MG1655 (Lamoureux et al. 2023, doi:10.1093/nar/gkad750)",
                               **measured_part()},
        "knowledge_base_fold_changes": {**kb_fold_changes(wcecoli / FOLD_CHANGES),
                                        "read_from": checkout_state(wcecoli)},
        "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": provenance.code_environment(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wcecoli", required=True, type=Path, help="the wcEcoli checkout the knowledge base is read from")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    out = build(a.wcecoli)
    a.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("runs", "no_oxygen_vs_basal_protein")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
