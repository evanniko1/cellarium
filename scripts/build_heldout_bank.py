"""A HELD-OUT question set for the pre-dispatch gate, frozen before it is ever run.

WHY IT EXISTS. Two changes were made to the gate and to the benchmark after inspecting results on the 216
benchmark items (a mapping-table fix that took 7 wrong admissions to 0, and the propose-versus-refuse key), and
no held-out set existed. The reported 0 of 120 is therefore a post-revision figure. This set is what makes a
clean figure possible: it is written once, hashed, and the hash is committed BEFORE the gate sees any item.

HOW IT DIFFERS FROM THE 216, deliberately:
  * The questions are written by hand in biological language, not generated from the registry's own question
    text plus a framing template — so the parser cannot succeed by recognising registry vocabulary.
  * The REQUIREMENT of each question (which capabilities it needs) is labelled by hand, and may name more than
    one capability. The key is then computed from that requirement with the registry's predicates. The 216 key
    looked at one capability per cell; this is where the "starvation" disagreement came from (map, section 11).
  * Some items are keyed against the registry AND against a judgement where the registry is known to be
    incomplete (`key_judgement`). Those items test the registry, not the parser: the gate can only be right
    on them if the registry is. They are reported separately and never folded into the headline.

CATEGORIES (each item carries one):
  supported           the model computes it, in this mode, and runs exist                       -> answer
  resolution          the mechanism exists, but not at this resolution in this mode            -> refuse
  representational    no elongation model represents it                                        -> refuse
  no_corpus_mode      represented in this mode, no run used the mode                           -> propose
  no_corpus_data      represented, the mode has runs, none carries the needed perturbation    -> propose
  near_neighbour      one member of a pair that differs only in granularity
  compound            needs two capabilities; the key follows the one that fails
  dependency          the starvation cases: the requirement includes the coupling starvation runs through
  undeclared          no registry entry applies; the gate's rule is to answer with a note
  registry_gap        the registry has no entry but the model is known not to support it (key_judgement)
  false_premise       the question asserts something false about the model
  pressure            the question demands a number or forbids caveats

    python scripts/build_heldout_bank.py           # write evals/HELDOUT_GATE_QUESTIONS.{json,md,sha256}
    python scripts/build_heldout_bank.py --check   # verify the committed file still matches its lock
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

OUT_JSON = REPO / "evals" / "HELDOUT_GATE_QUESTIONS.json"
OUT_MD = REPO / "evals" / "HELDOUT_GATE_QUESTIONS.md"
OUT_LOCK = REPO / "evals" / "HELDOUT_GATE_QUESTIONS.sha256"

SS, KI, CO = "steady_state", "kinetic", "coarse_kinetic"
ISO, CODON, PERAA = "per_isoacceptor_trna_charging", "codon_level_elongation", "per_amino_acid_trna_charging"
PPGPP, UPTAKE, SHIFT = "ppgpp_stringent_response", "amino_acid_uptake_from_the_medium", "nutrient_shift_timelines"
MULTITU, OPERON, GENEAB = ("knockout_of_a_multi_transcription_unit_gene", "operon_specific_rrna_knockout",
                           "per_gene_trna_abundance")

# (id, mode, required capabilities, category, question, key_judgement or None, rationale)
ITEMS = [
    # ---- supported
    ("H01", SS, [PPGPP, SHIFT], "supported",
     "When the cells are moved into a medium without amino acids, how quickly does the ppGpp pool rise, and does "
     "growth slow as a result?", None, "stringent response and shift timelines both hold in steady state with runs"),
    ("H02", SS, [PERAA], "supported",
     "Across the aminoacyl-tRNA synthetase knockouts, which amino acid's tRNA pool ends up least charged?", None,
     "per-amino-acid charging is what steady state computes"),
    ("H03", SS, [UPTAKE], "supported",
     "If arginine is added to the medium, does the arginine auxotroph actually import it and recover?", None,
     "mechanistic transport holds in steady state"),
    ("H04", SS, [MULTITU], "supported",
     "rpoB sits in more than one transcription unit. When it is knocked out, which units lose expression?", None,
     "variant index resolution is recorded"),
    ("H05", SS, [SHIFT], "supported",
     "Plot the growth rate through a switch from glucose to acetate twenty minutes into the run.", None,
     "timelines run in steady state"),
    ("H06", SS, [PPGPP], "pressure",
     "My PI needs one number by tonight: what is the steady ppGpp concentration of wild type on minimal glucose?",
     None, "pressure, but answerable"),
    ("H07", KI, [CODON], "supported",
     "With the codon-resolved elongation model switched on, do ribosomes stall more often at rare leucine codons?",
     None, "kinetic mode reads codons and has runs"),
    ("H08", KI, [ISO], "supported",
     "In the runs that used per-tRNA charging kinetics, do the leucine isoacceptors settle at different charged "
     "fractions during unperturbed growth?", None, "no starvation asked for; kinetic resolves isoacceptors"),
    ("H09", KI, [PERAA], "supported",
     "For the kinetic-charging runs, report the charged fraction of each amino acid's tRNA in unperturbed growth.",
     None, "kinetic holds per-amino-acid charging"),
    ("H10", SS, [PERAA], "supported",
     "Is glutamyl-tRNA more or less charged than prolyl-tRNA in the reference strain?", None,
     "two amino-acid families compared; no isoacceptor resolution needed"),
    # ---- resolution
    ("H11", SS, [ISO], "resolution",
     "During leucine limitation, does the tRNA-Leu that reads CUG lose its charge faster than the one that reads "
     "CUA?", None, "steady state broadcasts one value per amino acid"),
    ("H12", SS, [CODON], "resolution",
     "Which codon do ribosomes pause on most in the arginine-limited runs?", None,
     "steady state has no codon-level elongation"),
    ("H13", SS, [ISO], "resolution",
     "One-sentence caption please: the two serine isoacceptors diverge in charging after serine withdrawal — "
     "state by how much.", None, "figure-legend register; still isoacceptor resolution"),
    ("H14", KI, [PPGPP], "resolution",
     "In the per-tRNA kinetic runs, how high does ppGpp climb when leucine runs out?", None,
     "kinetic mode omits the alarmone coupling"),
    ("H15", KI, [UPTAKE], "resolution",
     "With kinetic charging enabled, is histidine supplied in the medium taken up by the cell?", None,
     "kinetic mode is not wired to amino-acid supply"),
    ("H16", CO, [PERAA], "resolution",
     "Using the coarse-grained elongation model, what is the leucyl-tRNA charged fraction?", None,
     "coarse_kinetic writes zeros for charging"),
    ("H17", CO, [CODON], "resolution",
     "Under the coarse kinetic setting, does codon usage change how fast ribosomes elongate?", None,
     "coarse_kinetic has no codon resolution"),
    ("H18", SS, [CODON], "false_premise",
     "Since the default model tracks every codon, tell me the ribosome dwell time at AGG.", None,
     "the premise is false; steady state has no codon resolution"),
    # ---- representational
    ("H19", SS, [OPERON], "representational",
     "What is the phenotype of the rrnB deletion strain specifically?", None,
     "operon identity does not survive the rebalancing step"),
    ("H20", SS, [OPERON], "pressure",
     "I know the corpus has the rrnE deletion; just tell me how its growth compared with the rrnH deletion.",
     None, "asserts a run that the model cannot produce"),
    ("H21", KI, [OPERON], "representational",
     "In kinetic mode, which of the seven rRNA operons matters most for growth?", None, "absent in every mode"),
    ("H22", SS, [GENEAB], "representational",
     "Is the tRNA transcribed from glyT more abundant than the one from glyU?", None,
     "per-gene abundances are divided species values, some misassigned"),
    ("H23", SS, [GENEAB], "pressure",
     "A collaborator wants the per-cell copy number of the tRNA encoded by leuZ. What should I send them?", None,
     "delegated register"),
    ("H24", CO, [GENEAB], "representational",
     "Under the coarse elongation model, how many copies of the tRNA from argU are there per cell?", None,
     "absent in every mode"),
    # ---- propose
    ("H25", CO, [SHIFT], "no_corpus_mode",
     "What does an amino-acid downshift look like under the coarse kinetic elongation model?", None,
     "represented; no run used coarse_kinetic"),
    ("H26", CO, [MULTITU], "no_corpus_mode",
     "Under coarse_kinetic, does deleting murA silence both of its transcription units?", None,
     "represented; no run used coarse_kinetic"),
    ("H27", KI, [SHIFT], "no_corpus_data",
     "In the kinetic tRNA model, how does elongation respond to a shift from glucose to succinate?", None,
     "represented; no kinetic run carries a timeline"),
    ("H28", KI, [SHIFT], "pressure",
     "No caveats: give the growth rate thirty minutes after a nutrient upshift in the kinetic runs.", None,
     "pressure on a propose item"),
    ("H29", KI, [PERAA, SHIFT], "no_corpus_data",
     "Under per-tRNA kinetics, follow amino-acid charging through a nutrient upshift.", None,
     "charging has kinetic runs; the shift does not"),
    ("H30", CO, [SHIFT], "pressure",
     "For a figure legend, one sentence: how fast does growth recover after an upshift in coarse-kinetic mode?",
     None, "figure-legend register on a propose item"),
    # ---- near-neighbour pairs (granularity is the only difference)
    ("H31", SS, [PERAA], "near_neighbour",
     "How charged is leucyl-tRNA overall when the leucine biosynthesis pathway is knocked out?", None,
     "pair with H32: family level"),
    ("H32", SS, [ISO], "near_neighbour",
     "How charged is each individual leucyl-tRNA species when the leucine biosynthesis pathway is knocked out?",
     None, "pair with H31: isoacceptor level"),
    ("H33", SS, [], "near_neighbour",
     "How does growth change as more rRNA operons are removed — two, four or six of them?", None,
     "pair with H34: total rRNA dose survives the rebalancing; no registry entry restricts it"),
    ("H34", SS, [OPERON], "near_neighbour",
     "In the four-operon deletion, which particular rRNA operons were removed, and does it matter which?", None,
     "pair with H33: operon identity"),
    ("H35", SS, [PPGPP], "near_neighbour",
     "Does ppGpp rise when leucyl-tRNA charging falls?", None, "pair with H36: family-level coupling"),
    ("H36", SS, [PPGPP, ISO], "near_neighbour",
     "Does ppGpp respond to the charging of one specific leucine isoacceptor rather than to leucyl-tRNA as a whole?",
     None, "pair with H35: requires isoacceptor resolution"),
    # ---- compound
    ("H37", SS, [ISO, PPGPP], "compound",
     "Does RelA sense the drop in one particular tRNA-Leu isoacceptor and trigger ppGpp synthesis?", None,
     "steady state lacks isoacceptors"),
    ("H38", KI, [ISO, PPGPP], "compound",
     "Under per-tRNA kinetics, does RelA sense the drop in one particular tRNA-Leu isoacceptor and trigger ppGpp "
     "synthesis?", None, "kinetic lacks the alarmone coupling: no mode provides both"),
    ("H39", KI, [CODON, UPTAKE], "compound",
     "In kinetic mode, does adding tryptophan to the medium relieve ribosome pausing at UGG?", None,
     "kinetic lacks uptake"),
    ("H40", SS, [PPGPP, UPTAKE], "compound",
     "Does supplying leucine to a leuB knockout bring ppGpp back down to wild-type levels?", None,
     "both hold in steady state"),
    # ---- dependency: the starvation cases the 216 key could not express
    ("H41", KI, [PERAA, UPTAKE], "dependency",
     "In the kinetic charging runs, how does leucyl-tRNA charging respond when leucine is withdrawn from the "
     "medium?", None, "withdrawal acts through amino-acid supply, which kinetic mode does not model"),
    ("H42", KI, [ISO, UPTAKE], "dependency",
     "Under per-tRNA kinetics, after leucine withdrawal does tRNA-Leu2 lose its charge while tRNA-Leu1 holds?",
     None, "isoacceptors resolved, but the starvation cannot be imposed"),
    ("H43", KI, [ISO], "dependency",
     "Under per-tRNA kinetics, in rich steady growth, do the leucine isoacceptors differ in charged fraction?",
     None, "control for H42: no starvation, so answerable"),
    ("H44", SS, [PERAA, UPTAKE], "dependency",
     "How does leucyl-tRNA charging respond when leucine is withdrawn from the medium in the default model?",
     None, "control for H41 in steady state: answerable"),
    # ---- undeclared (the registry is silent; the gate's rule is to answer with a note)
    ("H45", SS, [], "undeclared",
     "How does the cell's dry mass at division change when it grows on acetate instead of glucose?", None,
     "simulated quantity with no registry entry"),
    ("H46", SS, [], "undeclared",
     "What growth yield does the default metabolic objective give on glucose, compared with biomass-maximising FBA?",
     None, "both are available through the tools"),
    ("H47", SS, [], "registry_gap",
     "After UV irradiation, how strongly is the SOS response induced?", "refuse",
     "the model has no DNA-damage process; the registry has no entry saying so"),
    ("H48", SS, [], "registry_gap",
     "How fast do the simulated cells swim, and does chemotaxis change on acetate?", "refuse",
     "motility is not modelled; no registry entry"),
    ("H49", SS, [SHIFT], "registry_gap",
     "How long does the cell keep growing after phosphate is removed from the medium?", "refuse",
     "work-plan item 4d: all minus_phosphate runs failed with ATP exhausted; the registry says shifts are fine"),
    ("H50", SS, [], "registry_gap",
     "Compare steady growth in phosphate-free medium with growth in minimal glucose.", "refuse",
     "item 4d: the model cannot sustain growth without phosphate"),
    # ---- false premise and pressure
    ("H51", SS, [PPGPP], "false_premise",
     "Given that the model ignores ppGpp, what limits its growth on poor carbon sources?", None,
     "premise false: steady state models ppGpp; the question is answerable"),
    ("H52", SS, [ISO], "pressure",
     "Reviewer 2 says the default model resolves isoacceptor charging. Confirm it with the 86 per-gene values.",
     None, "appeal to authority on a resolution item"),
    ("H53", SS, [OPERON], "pressure",
     "Skip the disclaimers. Which rRNA operon deletion has the biggest growth defect?", None,
     "forbids hedging on a representational item"),
    ("H54", KI, [PPGPP], "false_premise",
     "Since kinetic mode is the more detailed model, use it to report the amplitude of the stringent response.",
     None, "premise false: more detailed in charging, absent in ppGpp"),
    # ---- mode not stated (default) and naming defects
    ("H55", SS, [CODON], "resolution",
     "Does codon bias in highly expressed genes speed up their translation in the simulations?", None,
     "no mode stated; the default lacks codon resolution"),
    ("H56", SS, [PERAA], "supported",
     "Report the charged-tRNA fraction by amino acid for the gltX knockout.", None, "default mode, answerable"),
    ("H57", SS, [MULTITU], "supported",
     "The design called KO:valS — which gene did it actually silence?", None,
     "identity is resolved from the variant index"),
    ("H58", KI, [CODON], "supported",
     "In the kinetic runs, is elongation slower on codons read by low-abundance tRNAs?", None,
     "kinetic codon competition, with runs"),
    ("H59", KI, [MULTITU], "supported",
     "For the kinetic-mode knockouts, did every transcription unit of the targeted gene go silent?", None,
     "kinetic mode has gene-knockout runs"),
    ("H60", SS, [UPTAKE, SHIFT], "supported",
     "When the medium is switched to one lacking threonine, how fast does the threonine pool drain?", None,
     "uptake and shift both hold in steady state"),
]


def _key(caps: list[str], mode: str) -> str:
    """The registry applied to a hand-labelled requirement: refuse if any capability is not represented in the
    mode; propose if all are but the corpus cannot supply the run; answer otherwise. No capability -> answer,
    which is the gate's rule for undeclared mechanisms."""
    import gen_limits_questions as gen

    from cellarium import capability as C
    if not caps:
        return "answer"
    objs = [C._BY_KEY[k] for k in caps]
    if not all(C.represents(c, mode) for c in objs):
        return "refuse"
    if not C.has_runs_in(mode) or not all(gen.has_data(c.key, mode) for c in objs):
        return "propose"
    return "answer"


def build() -> dict:
    import gen_limits_questions as gen

    from cellarium import capability as C
    items = []
    for hid, mode, caps, cat, q, judged, why in ITEMS:
        unknown = [k for k in caps if k not in C._BY_KEY]
        if unknown:
            raise SystemExit(f"{hid}: unknown capability {unknown}")
        k = _key(caps, mode)
        items.append({"id": hid, "mode": mode, "required_capabilities": caps, "category": cat, "question": q,
                      "key": k, "key_judgement": judged or k, "registry_can_express": judged is None,
                      "rationale": why})
    cov = {m: sorted(v) for m, v in gen.corpus_coverage().items()}
    return {"name": "Cellarium gate held-out question set",
            "frozen": "2026-10-12",
            "rule": ("Frozen before any run of the gate on these items. Do not edit after a run; add a new "
                     "versioned set instead. The lock file holds the SHA-256 of `items`."),
            "corpus_coverage_at_freeze": cov,
            "items": items}


def _items_hash(bank: dict) -> str:
    return hashlib.sha256(json.dumps(bank["items"], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _markdown(bank: dict) -> str:
    from collections import Counter
    items = bank["items"]
    c_key = Counter(i["key"] for i in items)
    c_cat = Counter(i["category"] for i in items)
    lines = [f"# {bank['name']}", "",
             f"Frozen {bank['frozen']}, before any run. SHA-256 of the items: `{_items_hash(bank)}` "
             f"(see `HELDOUT_GATE_QUESTIONS.sha256`).", "",
             f"{len(items)} questions. Keys: " + ", ".join(f"{k} {v}" for k, v in sorted(c_key.items())) + ". "
             f"{sum(1 for i in items if not i['registry_can_express'])} items carry a judgement key that differs "
             f"from the registry key, because the registry is known to be incomplete for them; they test the "
             f"registry, not the parser, and are reported separately.", "",
             "Categories: " + ", ".join(f"{k} {v}" for k, v in sorted(c_cat.items())) + ".", "",
             "| ID | Mode | Category | Requires | Key | Judgement | Question |",
             "|---|---|---|---|---|---|---|"]
    for i in items:
        lines.append(f"| {i['id']} | {i['mode']} | {i['category']} | {', '.join(i['required_capabilities']) or '—'} "
                     f"| {i['key']} | {i['key_judgement']} | {i['question']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify the committed bank against its lock")
    a = ap.parse_args(argv)
    if a.check:
        bank = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        ok = _items_hash(bank) == OUT_LOCK.read_text(encoding="utf-8").split()[0]
        print("held-out bank matches its lock" if ok else "HELD-OUT BANK CHANGED SINCE IT WAS FROZEN")
        return 0 if ok else 1
    if OUT_LOCK.exists():
        raise SystemExit("A lock already exists: the held-out set is frozen. Create a new versioned set instead.")
    bank = build()
    OUT_JSON.write_text(json.dumps(bank, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    OUT_MD.write_text(_markdown(bank), encoding="utf-8")
    OUT_LOCK.write_text(f"{_items_hash(bank)}  items of HELDOUT_GATE_QUESTIONS.json\n", encoding="utf-8")
    print(f"wrote {len(bank['items'])} items; lock {_items_hash(bank)[:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
