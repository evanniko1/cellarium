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
                      "beyond making that amino acid. "
                      "[AMENDED 2026-09-11 — the RULE is unchanged and still selects exactly the same "
                      "cells; what was wrong was the sentence that followed it, which called this 'the "
                      "most informative kind of surprise'. The first run returned 7: the five dap genes "
                      "and ilvC/ilvD. Neither group is a surprise. The dap pathway makes "
                      "diaminopimelate, which is a peptidoglycan precursor as well as a lysine precursor, "
                      "so no amino acid rescues it — and DAP is not in the twenty, which is why even the "
                      "all-amino-acid arm stays lethal. ilvC/ilvD serve the valine branch as well as the "
                      "isoleucine one, which is why isoleucine alone fails and the full mix succeeds. So "
                      "what this reason actually detects is a SHARED-PATHWAY enzyme or a non-proteinogenic "
                      "product. That is still a useful signal and still worth simulating — it is simply "
                      "not evidence that the model did anything unexpected, and reporting seven of these "
                      "as seven surprises would have been wrong.]",
    "already_in_corpus": "A whole-cell run already exists, so the FBA verdict can be checked against it "
                         "immediately at no compute cost. Not a reason to simulate; a reason to look.",
}


# ---------------------------------------------------------------------------------------------------------
# "Already in the corpus" has THREE states, not two — found by checking, on the first run.
# ---------------------------------------------------------------------------------------------------------
# The first version of this script asked one question: do rows exist with this gene in the label? For `argG`
# and `thrC` the answer was yes — 4 and 8 rows, every one `qc == "ok"` — and the honest conclusion "a
# whole-cell verdict is available for free" was WRONG. Both carry a NULL `kb_sha256`, so they belong to no
# ARM, and `survey.analysis_rows` correctly refuses to pool them with anything. Rows that are present,
# readable, and `ok`, and that no analysis path will ever use.
#
# That is the project's own silent-absence defect, committed inside a screen whose output is meant to tell
# someone where to spend days of compute. So the state is named rather than flattened:
#
#   analysable   — reportable rows in the current arm; the verdict really is free
#   unusable_arm — rows exist and may even be `ok`, but carry no arm key, so nothing can read them
#   collapsed    — rows exist and the design collapses; the lethality view carries the phenotype
#   absent       — no rows

def corpus_state(gene: str) -> dict:
    from cellarium import store, survey, tools
    rows, _ = survey.analysis_rows()
    analysable = {survey.design_key(r) for r in rows if r.get("reportable")}
    if f"gene_knockout/KO:{gene}" in analysable:
        return {"state": "analysable", "free_verdict": True}

    try:
        leth = {d["design"]: d for d in (tools.lethality_landscape().get("designs") or [])}
    except Exception:
        leth = {}
    hit = next((d for k, d in leth.items() if f"KO:{gene}" in k), None)
    if hit:
        return {"state": "collapsed", "free_verdict": True,
                "collapses_at_generation": hit.get("collapses_at_generation"),
                "reportable_seeds": hit.get("reportable_seeds"),
                "pre_collapse_growth_pct_vs_wt": (hit.get("pre_collapse") or {}).get("growth_pct_vs_wt"),
                "stringent_signature": hit.get("stringent_signature"),
                "true_label": hit.get("true_label"),
                # THE CAVEAT THAT HAS TO TRAVEL WITH THE NUMBER. Both free verdicts in the first run turned
                # out to be OPERON-WIDE knockouts — KO:leuB is really operon_KO:leuLABCD and KO:dapA is
                # really operon_KO:dapA-nlpB — while the FBA arm knocks out ONE gene. They are different
                # experiments, so "the whole-cell model agrees with Keio where FBA does not" is suggestive
                # and not decisive. It also constrains Stage 2: a run meant to be compared against Keio or
                # FBA has to be a genuine single-gene knockout, or it answers a different question.
                "single_gene": not str(hit.get("true_label") or "").startswith(("operon_KO", "TU_KO")),
                "comparability": ("single-gene, directly comparable to the FBA and Keio verdicts"
                                  if not str(hit.get("true_label") or "").startswith(("operon_KO", "TU_KO"))
                                  else "OPERON-WIDE — silences more genes than the FBA knockout, so this is "
                                       "not a like-for-like comparison")}

    raw = [r for r in store.list_results() if f"KO:{gene}" in str(r.get("label") or "")]
    if not raw:
        return {"state": "absent", "free_verdict": False}
    n_ok = sum(1 for r in raw if str(r.get("qc")) == "ok")
    no_arm = sum(1 for r in raw if not r.get("kb_sha256"))
    return {"state": "unusable_arm", "free_verdict": False, "n_rows": len(raw), "n_qc_ok": n_ok,
            "n_without_kb_sha256": no_arm,
            "why": "rows exist (and some are qc=ok) but carry no kb_sha256, so they belong to no arm and no "
                   "analysis path will pool them. Present is not the same as usable."}


def media(model_aas: set[str]) -> dict[str, dict]:
    from cellarium import fba
    minimal = dict(fba.M9_GLUCOSE)
    plus_all = dict(minimal)
    for aa, ex in AA_EXCHANGE.items():
        if ex in model_aas:
            plus_all[ex] = AA_UPTAKE
    return {"minimal": minimal, "minimal_plus_aa": plus_all}


def _directions(args) -> int:
    """THE CHEAP ANALYSIS, done before spending a day of compute: which WAY does each disagreement point?

    A disagreement between FBA and Keio is not one thing. `fba_false_viable` says the stoichiometric network
    has a bypass the real cell cannot use; `fba_false_lethal` says FBA is missing a route the real cell has.
    They license different Stage-2 questions, and one of the two directions turns out to be mostly an
    artefact — see below — so sorting them costs nothing and changes what is worth simulating.

    ⚠️ THE MEDIUM MISMATCH, which this analysis exists to surface. Keio essentiality is defined by failure to
    obtain a deletion mutant in COMPLEX (LB) MEDIUM (Baba 2006: "328 essential gene candidates for growth in
    complex (LB) medium"). The FBA arm here is scored on MINIMAL. So for amino-acid biosynthesis genes the
    two are not the same experiment, and the mismatch is one-directional: an auxotroph is viable on LB and
    lethal on minimal, which manufactures `fba_false_lethal` disagreements that say nothing about either
    model. The other direction is unaffected, and is in fact SHARPENED by the mismatch: a gene Keio calls
    essential even when every amino acid is supplied, which FBA calls dispensable even when none is, is a
    genuine conflict.
    """
    if not OUT.is_file():
        print(f"no {OUT} — run the screen first", file=sys.stderr)
        return 2
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    cells = payload["selected"] + payload["rejected"]
    groups: dict[str, list] = {"fba_false_viable": [], "fba_false_lethal": [], "other": []}
    for c in cells:
        if "disagrees_with_keio" not in c["selection_reasons"]:
            continue
        if not c["fba_essential_minimal"] and c["keio_essential"]:
            groups["fba_false_viable"].append(c)
        elif c["fba_essential_minimal"] and not c["keio_essential"]:
            groups["fba_false_lethal"].append(c)
        else:
            groups["other"].append(c)

    meaning = {
        "fba_false_viable": ("FBA finds a bypass the real cell cannot use. Keio calls the gene essential ON "
                             "RICH MEDIUM, so the cell needs it even when fed every amino acid — while FBA "
                             "calls it dispensable on minimal. A genuine conflict, and the medium mismatch "
                             "makes it stronger rather than weaker. THESE ARE THE STAGE-2 CELLS."),
        "fba_false_lethal": ("FBA is lethal on MINIMAL and Keio is viable on LB — which is what an "
                             "amino-acid auxotroph looks like when the two arms are grown on different "
                             "media. Mostly an artefact of the comparison, not a finding. Do not spend "
                             "compute here without first scoring Keio's own minimal-medium data."),
        "other": "Neither clean direction — inspect individually.",
    }
    for name, members in groups.items():
        if not members:
            continue
        print("")
        print(f"=== {name}: {len(members)} ===")
        print(f"    {meaning[name]}")
        fams: dict[str, list[str]] = {}
        for c in sorted(members, key=lambda x: x["gene"]):
            fams.setdefault(c["amino_acid"], []).append(c["gene"])
            print(f"      {c['gene']:7s} ({c['amino_acid']})  fba_min="
                  f"{'LETHAL' if c['fba_essential_minimal'] else 'viable':6s}  keio={c['keio_essential']}"
                  f"  corpus={c['corpus']['state']}")
        print(f"    families: {', '.join(f'{k}({len(v)})' for k, v in sorted(fams.items()))}")

    payload["disagreement_directions"] = {
        k: {"genes": [c["gene"] for c in v], "meaning": meaning[k]} for k, v in groups.items() if v}
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("")
    print(f"written back into {OUT.relative_to(ROOT)}")
    return 0


def _annotate_only(args) -> int:
    """Refresh the corpus classification in place, leaving every FBA number exactly as it was."""
    if not OUT.is_file():
        print(f"no {OUT} to annotate — run the screen first", file=sys.stderr)
        return 2
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    cells = payload["selected"] + payload["rejected"]
    for c in cells:
        cs = corpus_state(c["gene"])
        c["corpus"] = cs
        reasons = [r for r in c["selection_reasons"] if r != "already_in_corpus"]
        if cs["free_verdict"]:
            reasons.append("already_in_corpus")
        c["selection_reasons"] = reasons
        c["selected"] = [r for r in reasons if r != "already_in_corpus"] != []
    payload["selected"] = [c for c in cells if c["selected"]]
    payload["rejected"] = [c for c in cells if not c["selected"]]
    payload["selection_rule"] = SELECTION_RULE
    payload["counts"] = {"scored": len(cells), "selected": len(payload["selected"]),
                         "rejected": len(payload["rejected"]),
                         "by_reason": {k: sum(1 for c in cells if k in c["selection_reasons"])
                                       for k in SELECTION_RULE},
                         "by_corpus_state": {s: sum(1 for c in cells if c["corpus"]["state"] == s)
                                             for s in ("analysable", "collapsed", "unusable_arm", "absent")}}
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"re-annotated {len(cells)} cells (FBA numbers untouched)")
    for s, n in payload["counts"]["by_corpus_state"].items():
        print(f"    {s:14s} {n}")
    free = [c for c in cells if c["corpus"]["free_verdict"]]
    print("")
    print(f"whole-cell verdict available at NO compute cost: {len(free)}")
    for c in free:
        cs = c["corpus"]
        wc = ("collapses at gen %s (growth %s%% vs WT pre-collapse)"
              % (cs.get("collapses_at_generation"), cs.get("pre_collapse_growth_pct_vs_wt"))
              if cs["state"] == "collapsed" else "reportable in the current arm")
        print(f"  {c['gene']:7s} FBA={'LETHAL' if c['fba_essential_minimal'] else 'viable':6s} "
              f"Keio={str(c['keio_essential']):5s}  whole-cell: {wc}")
        if cs.get("single_gene") is False:
            print(f"          ! {cs['true_label']} — {cs['comparability']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0, help="also print the N highest-priority selected cells")
    ap.add_argument("--directions", action="store_true",
                    help="sort the Keio disagreements by WHICH WAY they point, and flag the ones that are "
                         "an artefact of Keio being scored on rich medium. Costs nothing; changes what is "
                         "worth simulating.")
    ap.add_argument("--annotate-only", action="store_true",
                    help="re-run ONLY the corpus classification over an existing result file. The corpus "
                         "grows; the FBA verdicts over a pinned iML1515 do not, and re-solving 168 MOMA "
                         "problems to refresh a lookup would be twenty minutes to learn nothing new.")
    args = ap.parse_args()

    if args.annotate_only:
        return _annotate_only(args)
    if args.directions:
        return _directions(args)

    from cellarium import fba
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

    # Which genes already have a whole-cell verdict — classified into the four states above, not guessed.

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
        cs = corpus_state(g)
        if cs["free_verdict"]:
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
            "corpus": cs,
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
