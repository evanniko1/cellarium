"""SCI-3 Stage 1 — the cheap, complete pass over the gene × environment grid.

THE TWO-STAGE DESIGN, and why the grid is scored twice at two resolutions. Whole-cell simulation of a full
gene × environment grid is days of compute; FBA over the same grid is seconds. So Stage 1 scores every cell
against iML1515 and Stage 2 simulates only the cells Stage 1 makes interesting. The plan is
`docs/SCIENCE_VALIDATION_PLANS.md` §3.

THE SELECTION RULE IS WRITTEN HERE, ABOVE THE RESULTS, ON PURPOSE. A grid scored cheaply and then sampled
for expensive follow-up is a selection procedure, and a selection made after looking at the numbers is how
a screen becomes a search for agreement. `SELECTION_RULE` below is fixed before the screen runs, and the
cells it selects are reported together with the cells it rejected, so the rejection set is visible rather
than implied.

WHAT STAGE 1 CANNOT DO, stated so its output is not over-read. FBA and the whole-cell model disagree BY
CONSTRUCTION in places — that disagreement is exactly what `metabolic_essentiality` versus `viability`
measures — so "FBA says this cell is boring" is not evidence the whole-cell model would agree. Stage 1
SELECTS; it does not substitute. An FBA verdict reported for an unsimulated cell must travel as an FBA
verdict, never as a result of the model this project is about.

    python scripts/conditional_essentiality_screen.py                 # writes data/sci3_stage1.json
    python scripts/conditional_essentiality_screen.py --top 12        # and prints the shortlist
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "data" / "sci3_stage1.json"

# ---------------------------------------------------------------------------------------------------------
# THE GRID — fixed before the screen runs.
# ---------------------------------------------------------------------------------------------------------
# Amino-acid biosynthesis crossed with amino-acid availability is the clean core: the mechanism is
# unambiguous and the expected answer is known, which is what makes it a TEST rather than an exploration.
# A gene that does not behave as expected here is informative precisely because the expectation was firm.

AA_GENES: dict[str, list[str]] = {
    "arg": ["argA", "argB", "argC", "argD", "argE", "argG", "argH"],
    "his": ["hisA", "hisB", "hisC", "hisD", "hisG"],
    "leu": ["leuA", "leuB", "leuC", "leuD"],
    "ile": ["ilvA", "ilvC", "ilvD", "ilvE"],
    "lys": ["dapA", "dapB", "dapD", "dapE", "dapF", "lysA"],
    "met": ["metA", "metB", "metC", "metE", "metL"],
    "thr": ["thrA", "thrB", "thrC"],
    "trp": ["trpA", "trpB", "trpC", "trpD", "trpE"],
    "phe": ["pheA"],
    "tyr": ["tyrA"],
    "pro": ["proA", "proB", "proC"],
    "ser": ["serA", "serB", "serC"],
    "gly": ["glyA"],
    "cys": ["cysE", "cysK", "cysM"],
    "asn": ["asnA", "asnB"],
    "gln": ["glnA"],
    "glu": ["gltB", "gltD"],
}

# iML1515 exchange ids for the twenty proteinogenic amino acids.
AA_EXCHANGE = {
    "ala": "EX_ala__L_e", "arg": "EX_arg__L_e", "asn": "EX_asn__L_e", "asp": "EX_asp__L_e",
    "cys": "EX_cys__L_e", "gln": "EX_gln__L_e", "glu": "EX_glu__L_e", "gly": "EX_gly_e",
    "his": "EX_his__L_e", "ile": "EX_ile__L_e", "leu": "EX_leu__L_e", "lys": "EX_lys__L_e",
    "met": "EX_met__L_e", "phe": "EX_phe__L_e", "pro": "EX_pro__L_e", "ser": "EX_ser__L_e",
    "thr": "EX_thr__L_e", "trp": "EX_trp__L_e", "tyr": "EX_tyr__L_e", "val": "EX_val__L_e",
}

AA_UPTAKE = 10.0          # mmol/gDW/h, the same order as the glucose bound — not limiting

# ---------------------------------------------------------------------------------------------------------
# THE SELECTION RULE — fixed before the screen runs.
# ---------------------------------------------------------------------------------------------------------
SELECTION_RULE = {
    "disagrees_with_keio": "FBA and the Keio experimental collection disagree about essentiality on "
                           "minimal medium. These are where a mechanistic model can say something a "
                           "stoichiometric one cannot, so they are the highest-value simulations.",
    "conditional_flip": "The gene is essential on minimal and viable when its amino acid is supplied. This "
                        "is the phenomenon the whole plan is about; simulating it shows HOW the cell "
                        "reroutes, which a growth screen cannot report.",
    "rescue_failure": "The gene is essential on minimal AND still essential with its own amino acid "
                      "supplied. The expectation was firm and it did not hold, so the gene does something "
                      "beyond making that amino acid — the most informative kind of surprise.",
    "already_in_corpus": "A whole-cell run already exists, so the FBA verdict can be checked against it "
                         "immediately at no compute cost. Not a reason to simulate; a reason to look.",
}


def media(model_aas: set[str]) -> dict[str, dict]:
    from cellarium import fba
    minimal = dict(fba.M9_GLUCOSE)
    plus_all = dict(minimal)
    for aa, ex in AA_EXCHANGE.items():
        if ex in model_aas:
            plus_all[ex] = AA_UPTAKE
    return {"minimal": minimal, "minimal_plus_aa": plus_all}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0, help="also print the N highest-priority selected cells")
    args = ap.parse_args()

    from cellarium import fba, store, survey
    ok, why = fba.available()
    if not ok:
        print(f"FBA is unavailable: {why}\n  pip install \"cellarium[fba]\"", file=sys.stderr)
        return 2

    genes = [g for gs in AA_GENES.values() for g in gs]
    aa_of = {g: aa for aa, gs in AA_GENES.items() for g in gs}
    print(f"grid: {len(genes)} amino-acid biosynthesis genes x 2 media + 1 own-amino-acid arm per gene")

    # Which exchanges the model actually has — asked, not assumed.
    import cobra
    model = cobra.io.read_sbml_model(str(fba.MODEL_PATH))
    present = {r.id for r in model.exchanges}
    missing_ex = sorted(ex for ex in AA_EXCHANGE.values() if ex not in present)
    if missing_ex:
        print(f"  note: {len(missing_ex)} amino-acid exchange(s) absent from iML1515: {missing_ex}")

    arms = media(present)
    verdicts: dict[str, dict] = {}
    for arm, medium in arms.items():
        res = fba.fba_gene_knockout(genes, medium=medium)
        if "error" in res:
            print(f"  {arm}: FAILED {res['error']}", file=sys.stderr)
            return 1
        print(f"  {arm}: wt growth {res['wt_growth']:.4f}, {len(res['results'])} genes scored"
              + (f", {len(res['unknown_genes'])} not in iML1515: {res['unknown_genes']}"
                 if res.get("unknown_genes") else ""))
        for r in res["results"]:
            verdicts.setdefault(r["gene"], {})[arm] = r

    # The third arm is per-gene: minimal plus ONLY the amino acid this gene's pathway makes. It is the
    # sharpest form of the test — a generic +AA rescue could come from any of the twenty.
    own: dict[str, dict] = {}
    by_aa: dict[str, list[str]] = {}
    for g in genes:
        by_aa.setdefault(aa_of[g], []).append(g)
    for aa, gs in by_aa.items():
        ex = AA_EXCHANGE.get(aa)
        if ex not in present:
            continue
        medium = dict(fba.M9_GLUCOSE)
        medium[ex] = AA_UPTAKE
        res = fba.fba_gene_knockout(gs, medium=medium)
        for r in res.get("results", []):
            own[r["gene"]] = r
    print(f"  own-amino-acid arms: {len(own)} genes scored")

    # Which genes already have a whole-cell run — checked, not guessed.
    rows, _ = survey.analysis_rows()
    in_corpus = {survey.design_key(r).split(":")[-1] for r in rows if "KO:" in survey.design_key(r)}
    all_labels = {str(r.get("label") or "") for r in store.list_results()}

    cells = []
    for g in sorted(verdicts):
        mini, plus = verdicts[g].get("minimal"), verdicts[g].get("minimal_plus_aa")
        if not mini or not plus:
            continue
        o = own.get(g)
        ess_min, ess_plus = mini["fba_essential"], plus["fba_essential"]
        ess_own = o["fba_essential"] if o else None
        reasons = []
        if mini.get("keio_essential") is not None and mini["keio_essential"] != ess_min:
            reasons.append("disagrees_with_keio")
        if ess_min and not ess_plus:
            reasons.append("conditional_flip")
        if ess_min and ess_own is True:
            reasons.append("rescue_failure")
        corpus_hit = g in in_corpus or any(f"KO:{g}" in lb for lb in all_labels)
        if corpus_hit:
            reasons.append("already_in_corpus")
        cells.append({
            "gene": g, "amino_acid": aa_of[g], "b_number": mini.get("b_number"),
            "fba_essential_minimal": ess_min, "fba_essential_plus_all_aa": ess_plus,
            "fba_essential_plus_own_aa": ess_own,
            "growth_frac_minimal": mini.get("fba_growth_frac"),
            "growth_frac_plus_all_aa": plus.get("fba_growth_frac"),
            "keio_essential": mini.get("keio_essential"),
            "wcecoli_prior_essential": mini.get("wcecoli_essential"),
            "diagnosis_minimal": mini.get("diagnosis"),
            "in_corpus": corpus_hit,
            "selected": [r for r in reasons if r != "already_in_corpus"] != [],
            "selection_reasons": reasons,
        })

    sel = [c for c in cells if c["selected"]]
    rejected = [c for c in cells if not c["selected"]]
    payload = {
        "stage": "1 — FBA screen over iML1515; NOT a whole-cell result",
        "selection_rule": SELECTION_RULE,
        "grid": {"genes": len(genes), "amino_acids": len(AA_GENES),
                 "media": ["minimal (M9 glucose)", "minimal + all 20 amino acids",
                           "minimal + the gene's own amino acid"],
                 "aa_uptake_mmol_gdw_h": AA_UPTAKE},
        "counts": {"scored": len(cells), "selected": len(sel), "rejected": len(rejected),
                   "by_reason": {k: sum(1 for c in cells if k in c["selection_reasons"])
                                 for k in SELECTION_RULE}},
        "limit": "FBA and the whole-cell model disagree by construction in places. A cell rejected here is "
                 "rejected as an FBA judgement, not as a whole-cell one. Report unsimulated cells as "
                 "FBA-screened, never as model results.",
        "selected": sel,
        "rejected": rejected,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nscored {len(cells)} genes: {len(sel)} SELECTED, {len(rejected)} rejected")
    for k, n in payload["counts"]["by_reason"].items():
        print(f"    {k:22s} {n}")
    print(f"\nwritten: {OUT.relative_to(ROOT)}")

    if args.top:
        order = {"rescue_failure": 0, "disagrees_with_keio": 1, "conditional_flip": 2}
        ranked = sorted(sel, key=lambda c: min(order.get(r, 9) for r in c["selection_reasons"]))
        print(f"\ntop {args.top} by priority:")
        for c in ranked[:args.top]:
            print(f"  {c['gene']:7s} ({c['amino_acid']}) "
                  f"min={'LETHAL' if c['fba_essential_minimal'] else 'viable':6s} "
                  f"+aa={'LETHAL' if c['fba_essential_plus_all_aa'] else 'viable':6s} "
                  f"keio={c['keio_essential']}  {','.join(c['selection_reasons'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
