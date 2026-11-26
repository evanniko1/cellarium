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
  inputs    the fold changes the fit USES (cellarium.fitted_fold_changes: fold_changes.tsv, with
            fold_changes_nca.tsv replacing a pair both list, as ParCa merges them): NarL and FNR at nar and frd, and
            FNR's and ArcA's entries at frdA. Until 2026-11-26 this read fold_changes.tsv alone (BV-14 found it).
  synthesis each design's depth-1 runs on the corpus fit, per seed (added 2026-11-26 after BV-14): each operon's
            synthesis probability and the named proteins, beside the fit's own synthesis targets. The nar proteins
            sit at a few copies per cell and arrive in bursts, so the protein readout above cannot resolve them.

The checkout is passed as an argument, not through WCECOLI_DIR, because setting WCECOLI_DIR switches the reader from
the Docker image to a native install.

    WCECOLI_DOCKER=<code image> .venv/Scripts/python.exe evals/anaerobic_response.py --wcecoli <checkout>
"""
from __future__ import annotations

import argparse
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
FLAT = "reconstruction/ecoli/flat"

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
FRD = ("frdA", "frdB", "frdC", "frdD")
KB_PAIRS = {"narL": NAR + FRD, "fnr": NAR + FRD, "arcA": ("frdA",)}
SYNTH_CONTRASTS = (("plus_nitrate_vs_no_oxygen", "condition/plus_nitrate", "condition/no_oxygen"),
                   ("no_oxygen_vs_basal", "condition/no_oxygen", "wildtype/basal"))
FIT_CONDITION = {"condition/plus_nitrate": "plus_nitrate", "condition/no_oxygen": "no_oxygen",
                 "wildtype/basal": "basal"}


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


def kb_fold_changes(flat: Path) -> dict:
    """The fold changes the fit uses for NarL, FNR and ArcA at nar and frd, with fold_changes.tsv's own value where
    the NCA table replaced it, and the pairs only the NCA table supplies."""
    from cellarium import fitted_fold_changes
    m = fitted_fold_changes.merged(flat)
    used, curated = m["used"], m["curated"]
    out = {tf: {g: used[(tf, g)] for g in targets if (tf, g) in used} for tf, targets in KB_PAIRS.items()}
    out["fold_changes_tsv_alone"] = {tf: {g: curated[(tf, g)] for g in targets if (tf, g) in curated}
                                     for tf, targets in KB_PAIRS.items()}
    pairs = {(tf, g) for tf, targets in KB_PAIRS.items() for g in targets}
    out["replaced_by_nca"] = [list(k) for k in m["replaced_by_nca"] if k in pairs]
    out["supplied_by_nca"] = [list(k) for k in m["supplied_by_nca"] if k in pairs]
    return out


def checkout_state(root: Path) -> dict:
    """Which commit the tables were read at, and whether the working tree changes either (the campaign checkout
    carries uncommitted changes elsewhere)."""
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60).stdout.strip()
    files = [f"{FLAT}/{t}" for t in ("fold_changes.tsv", "fold_changes_nca.tsv")]
    return {"files": files, "commit": git("rev-parse", "--short=8", "HEAD"),
            "modified_in_working_tree": bool(git("status", "--porcelain", "--", *files))}


def synthesis_part() -> dict:
    """Depth-1 runs of the corpus fit, per seed: each operon's synthesis probability, the factors' promoter occupancy
    and the named proteins, beside the fit's own synthesis targets for the two conditions."""
    import bv14_nitrate as B14

    from cellarium import differential, reader
    tus, tfs = list(B14.DIAG_TUS.values()), list(B14.DIAG_TFS)
    mono = {sym: m for m, sym in differential._reverse_gene_map().items() if sym in NAR + FRD}
    out = {"depth": 1, "contrasts": {}}
    fit = None
    for key, t, r in SYNTH_CONTRASTS:
        t_roots, r_roots, arm = differential._pair_run_roots(t, r, depth=1)
        if not t_roots or not r_roots:
            raise SystemExit(f"{key}: no depth-1 runs ({len(t_roots)} against {len(r_roots)})")
        if fit is None:
            fit = reader.fit_synthesis(t_roots[0], sorted(set(FIT_CONDITION.values())), tus, tfs)
            if not isinstance(fit, dict) or fit.get("error") or fit.get("missing"):
                raise SystemExit(f"the fit's targets unread: {str(fit)[:300]}")
        arms = {}
        for side, roots in (("target", t_roots), ("reference", r_roots)):
            sy = reader.synthesis_per_run(roots, tus, tfs)
            sp = reader.species_per_run(roots, "protein", [mono[g] for g in NAR + FRD if g in mono])
            rows = []
            for root in roots:
                k = reader._container_path(root)
                got = sy.get(k) if isinstance(sy, dict) else None
                if not got or got.get("error") or got.get("missing") or not isinstance(sp, dict) or k not in sp:
                    raise SystemExit(f"{key}: run {root} unread: {str(got or sy)[:300]}")
                rows.append({**got, "protein": {g: sp[k][mono[g]]["mean"] for g in NAR + FRD if g in mono}})
            arms[side] = rows
        tc, rc = FIT_CONDITION[t], FIT_CONDITION[r]
        fc = fit["conditions"]
        out["contrasts"][key] = {
            "model": f"{t} vs {r}, depth 1, {len(t_roots)} against {len(r_roots)} runs",
            "arm": dict(zip(("kb_sha256", "operons", "elongation_model"), arm)) if arm else "default (largest)",
            "actual_synth_prob": {op: B14._compare_arms([x["actual_synth_prob"][tu] for x in arms["target"]],
                                                        [x["actual_synth_prob"][tu] for x in arms["reference"]])
                                  for op, tu in B14.DIAG_TUS.items()},
            "fitted_log2_synth_ratio": {op: round(math.log2(fc[tc]["synth_prob"][tu] / fc[rc]["synth_prob"][tu]), 3)
                                        for op, tu in B14.DIAG_TUS.items()},
            "promoter_occupancy": {side: {"simulated": {tf: round(sum(x["p_promoter_bound"][tf] for x in arms[side])
                                                                  / len(arms[side]), 3) for tf in tfs},
                                          "fit_assumed": {tf: round(fc[cond]["p_promoter_bound"][tf], 3)
                                                          for tf in tfs}}
                                   for side, cond in (("target", tc), ("reference", rc))},
            "protein_per_seed": {g: B14._compare_arms([x["protein"][g] for x in arms["target"]],
                                                      [x["protein"][g] for x in arms["reference"]], pseudocount=1.0)
                                 for g in NAR + FRD if g in mono},
            "dry_mass_fg": B14._compare_arms([x["dry_mass_fg"] for x in arms["target"]],
                                             [x["dry_mass_fg"] for x in arms["reference"]])}
    return out


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
        "knowledge_base_fold_changes": {**kb_fold_changes(wcecoli / FLAT), "read_from": checkout_state(wcecoli)},
        "synthesis_depth_1": synthesis_part(),
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
