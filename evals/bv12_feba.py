"""BV-12: condition-specific gene fitness against FEBA (Price et al. 2018), PRAXIS-VirtualCell's own benchmark.

PRAXIS-VirtualCell scored iML1515 flux balance against FEBA's per-condition fitness (median per-condition Spearman
0.22). This test puts the whole-cell model beside iML1515 on the same terms, on a pre-registered pilot panel.

FEBA: the Fitness Browser's table for E. coli BW25113 (orgId Keio; fit.genomics.lbl.gov), downloaded 2026-11-25
through the browser (the site refuses scripted clients), SHA-256 recorded below. Gene fitness is a log2 ratio,
0 for no effect, negative for a defect; genes without insertions (essential in the pool's medium) are absent.
Two replicate experiments per carbon source are averaged: D-glucose (set1IT003/IT004), acetate (set1IT027/IT028),
succinate (set1IT039/IT040), all as the sole carbon source in minimal medium.

Subcommands:
  select   the pilot panel, pre-registered before any run: 20 single-transcription-unit metabolic genes in four
           FEBA patterns (carbon-specific, glucose-specific, defective everywhere, neutral), ranked by effect
           size within each pattern; and which glucose runs already exist in the corpus.
  fba      iML1515 single-gene deletions on each carbon source for every metabolic gene FEBA scores, and the
           per-condition Spearman against FEBA (PRAXIS's metric), on all genes and on the panel.
  score    (after the runs) the whole-cell model's growth effect per condition against FEBA, beside iML1515.

    python -I evals/bv12_feba.py select --feba data/reference/feba/feba_Keio_fitness_values.tsv
    .venv/Scripts/python.exe -I evals/bv12_feba.py fba --feba data/reference/feba/feba_Keio_fitness_values.tsv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
RES = REPO / "evals" / "results"
DESIGN_OUT = RES / "bv12_design.json"
FBA_OUT = RES / "bv12_iml1515.json"

FEBA_SHA256 = "d0ad9db34d966ab05ca50eb37a5d1f5b0e8a46d0697e6552db7e9ad585d14798"
EXPERIMENTS = {"glucose": ("set1IT003 D-Glucose (C)", "set1IT004 D-Glucose (C)"),
               "acetate": ("set1IT027 acetate (C)", "set1IT028 acetate (C)"),
               "succinate": ("set1IT039 succinate (C)", "set1IT040 succinate (C)")}
# The model's condition for each carbon source: the knowledge base's own fitted conditions (shipped with the base
# simulator, Covert lab PR #895 for acetate and succinate), and the media their timelines use.
MODEL_CONDITION = {"glucose": ("basal", "minimal"), "acetate": ("acetate", "minimal_acetate"),
                   "succinate": ("succinate", "minimal_succinate")}
# iML1515 exchange for each carbon source, at the uptake iML1515's paper uses for glucose (10 mmol/gDW/h) and a
# carbon-matched rate for the others (glucose 6 C; acetate 2 C; succinate 4 C).
FBA_CARBON = {"glucose": ("EX_glc__D_e", 10.0), "acetate": ("EX_ac_e", 30.0), "succinate": ("EX_succ_e", 15.0)}
PATTERNS = (("carbon_specific", 6), ("glucose_specific", 4), ("defective_everywhere", 4), ("neutral", 6))
STRONG, CLEAR, NEUTRAL = -1.0, -0.5, 0.3


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_feba(path: Path) -> dict:
    """b-number -> {symbol, glucose, acetate, succinate}: the replicate mean per carbon source."""
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            vals = {}
            for cond, cols in EXPERIMENTS.items():
                xs = [float(row[c]) for c in cols if row.get(c) not in (None, "", "NA")]
                vals[cond] = sum(xs) / len(xs) if xs else None
            out[row["sysName"]] = {"symbol": row["geneName"], **vals}
    return out


def pattern(g: dict) -> str | None:
    """Which pre-registered FEBA pattern a gene shows, or None. Thresholds are FEBA's own scale: below -1 is a
    strong defect, above -0.5 is no clear defect, within +-0.3 is neutral."""
    glc, ac, su = g["glucose"], g["acetate"], g["succinate"]
    if None in (glc, ac, su):
        return None
    if glc > CLEAR and min(ac, su) < STRONG:
        return "carbon_specific"
    if glc < STRONG and ac > CLEAR and su > CLEAR:
        return "glucose_specific"
    if max(glc, ac, su) < STRONG:
        return "defective_everywhere"
    if max(abs(glc), abs(ac), abs(su)) < NEUTRAL:
        return "neutral"
    return None


def effect_size(g: dict, pat: str) -> float:
    if pat == "carbon_specific":
        return g["glucose"] - min(g["acetate"], g["succinate"])
    if pat == "glucose_specific":
        return min(g["acetate"], g["succinate"]) - g["glucose"]
    if pat == "defective_everywhere":
        return -max(g["glucose"], g["acetate"], g["succinate"])
    return -max(abs(g["glucose"]), abs(g["acetate"]), abs(g["succinate"]))   # most neutral first


def eligible(symbol: str, scope: dict, footprint: dict) -> tuple[bool, str]:
    """A panel gene must be a metabolic, non-machinery gene alone on its transcription unit, so the model's
    knockout silences that gene and no other (an operon knockout would confound the comparison)."""
    s, fp = scope.get(symbol), footprint.get(symbol)
    if not s or s.get("ko_index") is None:
        return False, "no knockout index in the model"
    if not s.get("is_metabolic"):
        return False, "not metabolic"
    if s.get("is_machinery"):
        return False, "machinery"
    # ko_footprint lists only genes that share a transcription unit; a gene absent from it, on one unit, is alone
    if s.get("n_tu") != 1 or (fp is not None and fp.get("n_genes_on_tu") != 1):
        return False, "not alone on one transcription unit"
    return True, ""


def select_panel(feba: dict, scope: dict, footprint: dict, bmap: dict) -> dict:
    sym_by_b = {b: s for s, b in bmap.items()}
    pools = {p: [] for p, _ in PATTERNS}
    excluded = {}
    for b, g in feba.items():
        pat = pattern(g)
        if pat is None:
            continue
        sym = sym_by_b.get(b) or g["symbol"]
        ok, why = eligible(sym, scope, footprint)
        if not ok:
            excluded[why] = excluded.get(why, 0) + 1
            continue
        pools[pat].append({"symbol": sym, "bnumber": b, "ko_index": int(scope[sym]["ko_index"]),
                           **{c: round(g[c], 3) for c in EXPERIMENTS}, "pattern": pat,
                           "effect": round(effect_size(g, pat), 3)})
    ranked = {p: sorted(v, key=lambda r: (-r["effect"], r["symbol"])) for p, v in pools.items()}
    take = dict(PATTERNS)
    # A pattern with fewer eligible genes than its quota gives its free slots to the carbon-specific pattern,
    # the one the test is about, so the panel stays at its registered size.
    short = sum(max(0, n - len(ranked[p])) for p, n in PATTERNS)
    take["carbon_specific"] += short
    panel = []
    for pat, _ in PATTERNS:
        panel += ranked[pat][:take[pat]]
    return {"panel": panel, "pool_sizes": {p: len(v) for p, v in pools.items()}, "taken": take,
            "excluded_by_reason": excluded}


def existing_runs(panel: list[dict]) -> dict:
    """Which (gene, carbon source) arms already have runs in the corpus, so none is re-run."""
    import duckdb
    m = (REPO / "data" / "manifest").as_posix()
    con = duckdb.connect()
    rows = con.sql(f"SELECT perturbation, condition, timeline, seed, generations, kb_sha256, elongation_model "
                   f"FROM read_parquet('{m}/*.parquet', union_by_name=true)").fetchall()
    have = {}
    for p in panel:
        tag = f"KO:{p['symbol']}"
        hits = [r for r in rows if r[0] == "gene_knockout" and r[1] == tag and not r[2]
                and (r[6] in (None, "steady_state"))]
        have[p["symbol"]] = {"glucose": sorted({(int(r[3]), int(r[4] or 0)) for r in hits})}
    controls = {}
    for cond in ("acetate", "succinate"):
        hits = [r for r in rows if r[0] == "condition" and r[1] == cond and (r[6] in (None, "steady_state"))]
        controls[cond] = sorted({(int(r[3]), int(r[4] or 0)) for r in hits})
    wt = [r for r in rows if r[0] == "wildtype" and r[1] in ("basal", None, "") and not r[2]
          and (r[6] in (None, "steady_state"))]
    controls["glucose"] = sorted({(int(r[3]), int(r[4] or 0)) for r in wt})
    return {"knockouts": have, "controls": controls,
            "note": "(seed, generations) pairs on the steady-state model with no timeline"}


def cmd_select(a) -> int:
    feba_path = Path(a.feba)
    digest = sha256(feba_path)
    if digest != FEBA_SHA256:
        print(f"FEBA file hash {digest} differs from the registered {FEBA_SHA256}", file=sys.stderr)
        return 2
    cache = REPO / "data" / "cache"
    scope = json.loads((cache / "gene_scope.json").read_text(encoding="utf-8"))
    footprint = json.loads((cache / "ko_footprint.json").read_text(encoding="utf-8"))
    bmap = json.loads((cache / "bnumber_map.json").read_text(encoding="utf-8"))
    sel = select_panel(load_feba(feba_path), scope, footprint, bmap)
    out = {"spec": "BV-12 pilot panel, pre-registered before any run", "feba_sha256": digest,
           "experiments": EXPERIMENTS, "thresholds": {"strong": STRONG, "clear": CLEAR, "neutral": NEUTRAL},
           "patterns": dict(PATTERNS), "model_condition": MODEL_CONDITION, **sel,
           "existing_runs": existing_runs(sel["panel"]),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    DESIGN_OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for p in sel["panel"]:
        print(f"{p['pattern']:22s} {p['symbol']:6s} ko={p['ko_index']:5d} glc {p['glucose']:+.2f} "
              f"ac {p['acetate']:+.2f} su {p['succinate']:+.2f}")
    print("pools:", sel["pool_sizes"])
    return 0


def spearman(xs: list[float], ys: list[float]) -> float | None:
    from scipy.stats import spearmanr
    if len(xs) < 3:
        return None
    r = spearmanr(xs, ys).statistic
    return None if r != r else round(float(r), 3)


def cmd_fba(a) -> int:
    from cellarium import fba
    ok, msg = fba.available()
    if not ok:
        print(msg, file=sys.stderr)
        return 2
    feba = load_feba(Path(a.feba))
    m = fba.load_model()
    genes_in_model = {g.id for g in m.genes}
    scored = sorted(b for b in feba if b in genes_in_model)
    design = json.loads(DESIGN_OUT.read_text(encoding="utf-8")) if DESIGN_OUT.exists() else {"panel": []}
    panel_b = {p["bnumber"] for p in design["panel"]}
    from cobra.flux_analysis import single_gene_deletion
    per = {}
    for cond, (ex, uptake) in FBA_CARBON.items():
        with m:
            for rid in [r.id for r in m.exchanges]:
                if rid in {e for e, _ in FBA_CARBON.values()}:
                    m.reactions.get_by_id(rid).lower_bound = 0.0
            m.reactions.get_by_id(ex).lower_bound = -uptake
            wt = m.slim_optimize()
            res = single_gene_deletion(m, gene_list=scored, processes=1)
        growth = {}
        for ids, val in zip(res["ids"], res["growth"]):
            b = next(iter(ids))
            growth[b] = 0.0 if val != val else float(val) / wt if wt > 1e-9 else None
        xs = [growth[b] for b in scored if growth.get(b) is not None and feba[b][cond] is not None]
        ys = [feba[b][cond] for b in scored if growth.get(b) is not None and feba[b][cond] is not None]
        px = [growth[b] for b in scored if b in panel_b and growth.get(b) is not None]
        py = [feba[b][cond] for b in scored if b in panel_b and growth.get(b) is not None]
        per[cond] = {"wt_growth": round(wt, 4), "n_genes": len(xs), "spearman_all": spearman(xs, ys),
                     "n_panel": len(px), "spearman_panel": spearman(px, py),
                     "panel_growth_ratio": {b: round(growth[b], 3) for b in sorted(panel_b) if growth.get(b) is not None}}
        print(cond, json.dumps({k: v for k, v in per[cond].items() if k != "panel_growth_ratio"}))
    vals = sorted(v["spearman_all"] for v in per.values() if v["spearman_all"] is not None)
    out = {"spec": "BV-12, iML1515 arm", "feba_sha256": sha256(Path(a.feba)), "model": fba.provenance(),
           "carbon_uptake": FBA_CARBON, "per_condition": per,
           "median_spearman_all": vals[len(vals) // 2] if vals else None,
           "praxis_reported_median": 0.22,
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    FBA_OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return 0


PLAN_OUT = REPO / "evals" / "plans" / "bv12.json"
GENERATIONS, SEEDS, VALIDITY_SEED = 3, (0, 1), 100
# Reference growth at generation 0 for the validity controls: the fitted condition's own corpus runs (condition
# variant, knowledge base 3b2f8ebd...): acetate 1.09e-4 to 2.18e-4 /s over 8 seeds, succinate 1.75e-4 to 2.07e-4 /s
# over 3, each widened by about 5% so one seed's noise does not close a group the mechanism has not failed.
GATES = {"acetate": {"growth_rate": [1.0e-4, 2.3e-4]}, "succinate": {"growth_rate": [1.4e-4, 2.4e-4]}}


def _ko_design(p: dict, carbon: str) -> dict:
    cond, media = MODEL_CONDITION[carbon]
    d = {"perturbation": "gene_knockout", "condition": f"KO:{p['symbol']}", "params": {"variant_index": p["ko_index"]}}
    if carbon != "glucose":
        d["timeline"] = f"0 {media}"
        d["params"]["initial_condition"] = cond
    return d


def _wt_design(carbon: str) -> dict:
    cond, media = MODEL_CONDITION[carbon]
    return {"perturbation": "wildtype", "condition": cond, "timeline": f"0 {media}",
            "params": {"initial_condition": cond}}


def cmd_plan(a) -> int:
    design = json.loads(DESIGN_OUT.read_text(encoding="utf-8"))
    runs = []
    for carbon in ("acetate", "succinate"):
        runs.append({"id": f"wt-{carbon}-validity", "design": _wt_design(carbon), "seed": VALIDITY_SEED,
                     "generations": 1, "group": carbon, "role": "control", "stage": 1})
        for seed in SEEDS:
            runs.append({"id": f"wt-{carbon}-s{seed}", "design": _wt_design(carbon), "seed": seed,
                         "generations": GENERATIONS, "group": carbon, "role": "run", "stage": 2})
    for p in design["panel"]:
        for carbon in ("glucose", "acetate", "succinate"):
            for seed in SEEDS:
                runs.append({"id": f"{p['symbol']}-{carbon}-s{seed}", "design": _ko_design(p, carbon), "seed": seed,
                             "generations": GENERATIONS, "group": carbon, "role": "run",
                             "stage": 1 if carbon == "glucose" else 2})
    plan = {"batch": "bv12", "sim_path": "cellarium", "parallel": 6, "min_free_gb": 40, "gates": GATES,
            "glucose_controls": "existing wildtype/basal seeds 0 and 1 (4 generations, knowledge base 3b2f8ebd...)",
            "design_sha256": sha256(DESIGN_OUT), "runs": runs}
    PLAN_OUT.parent.mkdir(parents=True, exist_ok=True)
    PLAN_OUT.write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    print(f"{len(runs)} runs planned -> {PLAN_OUT.relative_to(REPO).as_posix()}")
    return 0


SCORE_OUT = RES / "bv12_score.json"


INTEGRITY_FAILURES = {"crashed", "empty", "degenerate", "truncated", "over_replicated", "implausible_channel"}
CORPUS_KB = "3b2f8ebd"      # the corpus fit every BV-12 run uses (sim_path cellarium)
GEN = 2          # the generation every run is read at: the last of a 3-generation run, depth-matched for longer ones


def _scored_rows() -> dict:
    """{run path: (growth at generation GEN, qc)} for the corpus fit's rows. Read directly, not through the analysis
    boundary: a knockout whose translation collapsed (lysA, serA, proC) is non-reportable there, and its collapse IS
    the fitness phenotype. Integrity failures are excluded; phenotype QC statuses are kept. Growth is the run's own
    per-generation record at generation GEN, so a 4- or 8-generation run (the pilot's pgi) is depth-matched."""
    import duckdb
    m = (REPO / "data" / "manifest").as_posix()
    out = {}
    for path, kb, qc, per in duckdb.connect().sql(
            f"SELECT simout_path, kb_sha256, qc, per_generation FROM read_parquet('{m}/*.parquet', "
            f"union_by_name=true)").fetchall():
        kept = select_row(path, kb, qc, per)
        if kept:
            out[str(path).replace("\\", "/")] = kept
    return out


def select_row(path, kb, qc, per) -> tuple | None:
    """The scoring rule for one manifest row: the corpus fit only, no integrity failure, and a generation-GEN growth
    in the row's own per-generation record. A phenotype QC status (translation_collapse) is kept: it is the effect."""
    if not path or not str(kb or "").startswith(CORPUS_KB) or qc in INTEGRITY_FAILURES:
        return None
    gens = json.loads(per) if isinstance(per, str) else (per or [])
    g = gens[GEN].get("growth") if len(gens) > GEN and isinstance(gens[GEN], dict) else None
    return (g, qc) if g is not None else None


def cmd_score(a) -> int:
    """The pre-registered score: per carbon source, the Spearman correlation between the whole-cell model's knockout
    growth effect (knockout growth over wild-type growth, both at generation 2) and FEBA fitness over the panel,
    beside iML1515's on the same genes; then the median over carbon sources (PRAXIS's metric)."""
    import statistics

    from cellarium import provenance, runner
    from cellarium.generate import Design
    design = json.loads(DESIGN_OUT.read_text(encoding="utf-8"))
    iml = json.loads(FBA_OUT.read_text(encoding="utf-8"))
    plan = json.loads(PLAN_OUT.read_text(encoding="utf-8"))
    amend = json.loads((PLAN_OUT.parent / "bv12_amend1.json").read_text(encoding="utf-8"))
    rows = _scored_rows()
    out_root = runner._out_root("cellarium").parent

    def growth(d: dict, seeds) -> list[float]:
        got = []
        for seed in seeds:
            rel = runner._run_subpath(Design(**d), seed, "cellarium").relative_to(out_root).as_posix()
            got += [g for k, (g, _q) in rows.items() if k.endswith(rel)]
        return got
    seeds = sorted({r["seed"] for r in plan["runs"] if r["role"] == "run"})
    per = {}
    for carbon in ("glucose", "acetate", "succinate"):
        if carbon == "glucose":       # the depth-3 references (bv12_amend1) and the 4-generation seeds 0 and 1, at GEN
            wt = growth({"perturbation": "wildtype", "condition": "basal"}, [r["seed"] for r in amend["runs"]] + seeds)
        else:
            wt = growth(_wt_design(carbon), seeds)
        genes = []
        for g in design["panel"]:
            ko = growth(_ko_design(g, carbon), seeds)
            if not ko or not wt:
                continue
            ratio = statistics.fmean(ko) / statistics.fmean(wt)
            iml_ratio = (iml["per_condition"].get(carbon, {}).get("panel_growth_ratio") or {}).get(g["bnumber"])
            qcs = sorted({q for k, (_g, q) in rows.items() if any(k.endswith(runner._run_subpath(
                Design(**_ko_design(g, carbon)), sd, "cellarium").relative_to(out_root).as_posix()) for sd in seeds)})
            genes.append({"symbol": g["symbol"], "pattern": g["pattern"], "feba": g[carbon], "n_seeds": len(ko),
                          "whole_cell_ratio": round(ratio, 4), "iml1515_ratio": iml_ratio, "qc": qcs})
        both = [x for x in genes if x["iml1515_ratio"] is not None]
        per[carbon] = {"n_wt_seeds": len(wt), "n_genes": len(genes),
                       "spearman_whole_cell": spearman([x["whole_cell_ratio"] for x in genes],
                                                       [x["feba"] for x in genes]),
                       "spearman_iml1515_same_genes": spearman([x["iml1515_ratio"] for x in both],
                                                               [x["feba"] for x in both]),
                       "genes": genes}

    def median(key):
        vals = sorted(v[key] for v in per.values() if v[key] is not None)
        return vals[len(vals) // 2] if vals else None
    out = {"spec": "BV-12 score, as pre-registered", "read_at_generation": GEN,
           "phenotype_qc_kept": "translation_collapse and other non-integrity statuses are the phenotype, kept",
           "metric": "per-condition Spearman over the panel; median over carbon sources (PRAXIS-VirtualCell's metric)",
           "per_condition": per, "median_whole_cell": median("spearman_whole_cell"),
           "median_iml1515_same_genes": median("spearman_iml1515_same_genes"),
           "complete": all(v["n_genes"] == len(design["panel"]) for v in per.values()),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    SCORE_OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({c: {k: v[k] for k in ("n_wt_seeds", "n_genes", "spearman_whole_cell",
                                            "spearman_iml1515_same_genes")} for c, v in per.items()}))
    print("median", out["median_whole_cell"], "vs iML1515", out["median_iml1515_same_genes"], "complete", out["complete"])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("select", "fba"):
        s = sub.add_parser(name)
        s.add_argument("--feba", required=True)
    sub.add_parser("plan")
    sub.add_parser("score")
    a = ap.parse_args(argv)
    return {"select": cmd_select, "fba": cmd_fba, "plan": cmd_plan, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
