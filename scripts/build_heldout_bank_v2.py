"""Held-out question set v2 for the pre-dispatch gate — authored, NOT frozen, awaiting a second labeller.

GATE-8b-HO2. The four corrections the first held-out set exposed (GATE-8b A–D) were all designed with that
set's results in view, so **v1 can no longer measure them**: a fix tailored to the only documents that could
test it is a fix with no evidence. The registered order is therefore: write and freeze a second set keyed
against the corrections' own stated rules, have somebody other than the author review a sample of the keys,
and only then implement A, D, B and C. This file is the first half of that.

WHAT MAKES A KEY DEFENSIBLE HERE, and it is the reason this is authorable at all. The questions and the
REQUIREMENT of each question (which capabilities it needs) are written by hand; the **key is computed** from
that requirement by the registry's own predicates — refuse if any capability is not represented in the mode,
propose if all are but the corpus cannot supply the run, answer otherwise. So the author does not choose the
answers. What a reviewer has to check is the hand-labelled requirement of each question, which is a judgement
a second person can make from the question text alone.

THE GROUND TRUTH THE KEYS REST ON, read from the registry rather than remembered (2026-10-31):

    capability                                   SS repr/data  KI repr/data  CO repr/data
    per_isoacceptor_trna_charging                    n/Y           Y/Y           n/n
    codon_level_elongation                           n/Y           Y/Y           n/n
    operon_specific_rrna_knockout                    n/Y           n/n           n/n
    per_gene_trna_abundance                          n/Y           n/Y           n/n
    growth_under_phosphate_depletion                 n/Y           n/n           n/n
    response_to_the_glucose_concentration            n/Y           n/Y           n/n
    growth_without_a_carbon_source                   n/Y           n/n           n/n
    knockout_of_a_multi_transcription_unit_gene      Y/Y           Y/Y           Y/n
    per_amino_acid_trna_charging                     Y/Y           Y/Y           n/n
    ppgpp_stringent_response                         Y/Y           n/Y           n/n
    amino_acid_uptake_from_the_medium                Y/Y           n/n           n/n
    nutrient_shift_timelines                         Y/Y           Y/n           Y/n

    modes with runs: steady_state, kinetic.  coarse_kinetic has none, so anything representable there is
    `propose` and never `answer`.

WHAT EACH GROUP PROBES, in BOTH directions, which is what the registered spec asks for:

  A  resolution-implied requirements on NON-CHARGING observables. `REQUIRES` is keyed by (observable,
     granularity) and 17 of 63 pairs are mapped; an unmapped pair keeps only what the dependencies imply, so
     `ppgpp` × `per_isoacceptor` silently dropped the resolution and the gate answered. The other direction
     matters as much: a fine resolution whose capability IS present in the asked mode must still be ANSWERED,
     or the fix has become a keyword filter that refuses anything granular.
  B  `per_operon` over-refuses. A named rRNA operon, a multi-transcription-unit gene, a named non-rRNA
     operon and an aggregate rRNA dose are put side by side in the same mode, because one granularity was
     covering all four and only the first should refuse.
  C  implied dependencies, keyed against `gate.IMPLIED_DEPENDENCIES`: removal or downshift of a nutrient
     implies starvation of it, upshift or a rich medium implies supply, steady growth in a defined medium
     implies NEITHER. The same question appears in two or three modes, so the key moves with what the mode
     can represent rather than with the wording.
  D  per-capability data coverage. A capability can be representable in a mode that HAS runs while no run
     carries the perturbation — `nutrient_shift_timelines` in kinetic is exactly that — which is `propose`.
     The other direction is the same question in steady state, where the data exist and it must be ANSWERED.

NOT FROZEN, AND THE LOCK IS WHAT FREEZES IT. Writing the files leaves `frozen: null` and
`status: awaiting_review`; `--freeze --reviewer "Name, YYYY-MM-DD"` writes the lock, and refuses without a
reviewer. `run_gate_eval.py --heldout2` refuses to score an unfrozen set, because a set scored before it is
frozen is not held out — it is a development set with a hash.

    python scripts/build_heldout_bank_v2.py                 # write the json + md + the review packet
    python scripts/build_heldout_bank_v2.py --check         # verify against the lock, once frozen
    python scripts/build_heldout_bank_v2.py --freeze --reviewer "A. Reviewer, 2026-11-02"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

OUT_JSON = REPO / "evals" / "HELDOUT_GATE_QUESTIONS_V2.json"
OUT_MD = REPO / "evals" / "HELDOUT_GATE_QUESTIONS_V2.md"
OUT_LOCK = REPO / "evals" / "HELDOUT_GATE_QUESTIONS_V2.sha256"
OUT_REVIEW = REPO / "evals" / "HELDOUT_V2_REVIEW_PACKET.md"

SS, KI, CO = "steady_state", "kinetic", "coarse_kinetic"
ISO, CODON, PERAA = "per_isoacceptor_trna_charging", "codon_level_elongation", "per_amino_acid_trna_charging"
PPGPP, UPTAKE, SHIFT = "ppgpp_stringent_response", "amino_acid_uptake_from_the_medium", "nutrient_shift_timelines"
MULTITU, OPERON, GENEAB = ("knockout_of_a_multi_transcription_unit_gene", "operon_specific_rrna_knockout",
                           "per_gene_trna_abundance")
PHOS, GLUDOSE, NOCARBON = ("growth_under_phosphate_depletion", "response_to_the_glucose_concentration",
                           "growth_without_a_carbon_source")

# Which correction each item is aimed at, so a reader can tell a probe from a control.
# (id, mode, required capabilities, category, probes, question, key_judgement or None, rationale)
ITEMS = [
    # ---------- A: a fine resolution on an observable that is not charging ----------
    ("V01", SS, [PPGPP, ISO], "resolution", "A",
     "When leucine runs out, does the ppGpp response track the leucine tRNA that reads CUG more closely than "
     "the one that reads CUA?",
     None, "isoacceptor resolution is the requirement the observable hides; steady state broadcasts one "
           "charging value per amino acid"),
    ("V02", KI, [PPGPP, ISO], "resolution", "A",
     "In the per-tRNA kinetic runs, does the alarmone climb at the moment the CUG-reading leucine tRNA loses "
     "its charge?",
     None, "the resolution is available here and the alarmone is not; the pair fails on the other half"),
    ("V03", SS, [PPGPP, CODON], "resolution", "A",
     "Does the alarmone rise sharply while ribosomes are held up on a rare arginine codon?",
     None, "codon resolution implied by the question, absent in steady state"),
    ("V04", KI, [SHIFT, CODON], "no_corpus_data", "A",
     "Through a switch from glucose to succinate in the codon-resolved runs, which codons slow down first?",
     None, "both representable in kinetic; no kinetic run carries a medium switch"),
    ("V05", SS, [UPTAKE, ISO], "resolution", "A",
     "When histidine is supplied in the medium, which of the histidyl-tRNAs fills up first?",
     None, "uptake holds in steady state; the isoacceptor comparison does not"),
    ("V06", KI, [MULTITU, ISO], "near_neighbour", "A",
     "In the kinetic runs, after deleting a gene that sits in two transcription units, do the leucine tRNAs "
     "end up at different charged fractions?",
     None, "THE OTHER DIRECTION: a fine resolution whose capability is present, with runs. Must be answered "
           "or the correction has become a filter that refuses anything granular"),
    ("V07", KI, [ISO], "supported", "A",
     "In the per-tRNA kinetic runs, do the two serine tRNAs settle at different charged fractions during "
     "steady growth?",
     None, "the already-mapped pair, as a control that the correction does not disturb it"),
    ("V08", KI, [CODON], "supported", "A",
     "With codon-resolved elongation switched on, is the ribosome slower on rare leucine codons than on "
     "common ones?",
     None, "mapped pair, present with runs"),
    ("V09", SS, [PERAA, PPGPP], "supported", "A",
     "Does the fall in glutamyl-tRNA charging line up in time with the rise in the alarmone?",
     None, "coarse resolution on two capabilities steady state holds"),
    ("V10", CO, [PPGPP, ISO], "resolution", "A",
     "Under the coarse-grained elongation model, does the alarmone follow one leucine tRNA more than another?",
     None, "neither half is representable in coarse_kinetic"),
    ("V11", SS, [GENEAB, PPGPP], "representational", "A",
     "Does the alarmone shut down the tRNA transcribed from leuZ more than the one from leuX?",
     None, "per-gene tRNA identity is representable in no mode"),
    ("V12", KI, [PERAA, CODON], "supported", "A",
     "In the codon-resolved kinetic runs, is arginyl-tRNA less charged where rare arginine codons are "
     "frequent?",
     None, "THE OTHER DIRECTION again, with a coarse and a fine requirement in one question"),

    # ---------- B: a named rRNA operon, a multi-unit gene, a named operon, an aggregate dose ----------
    ("V13", SS, [OPERON], "representational", "B",
     "What is the growth phenotype of a strain missing the rrnB operon specifically?",
     None, "operon identity does not survive the rRNA rebalancing step"),
    ("V14", SS, [MULTITU], "supported", "B",
     "murA is transcribed from more than one unit. When it is deleted, which of those units stops being "
     "expressed?",
     None, "SIDE BY SIDE with V13 and V15: a multi-unit gene is not an operon-identity question"),
    ("V15", SS, [], "undeclared", "B",
     "How many ribosomal RNA operons does the model carry in total?",
     None, "SIDE BY SIDE: a count of operons is an aggregate, and no capability gates it"),
    ("V16", SS, [MULTITU], "near_neighbour", "B",
     "Knocking out rpoB: list the transcription units that lose expression.",
     None, "the same demand as V14 in the wording that was being refused"),
    ("V17", KI, [OPERON], "representational", "B",
     "In the kinetic runs, which of the seven rRNA operons contributes most to growth?",
     None, "operon identity, in the other mode with runs"),
    ("V18", KI, [MULTITU], "supported", "B",
     "Under kinetic charging, does deleting a gene shared by two transcription units silence both of them?",
     None, "the multi-unit case in kinetic, where it is also representable with runs"),
    ("V19", SS, [], "undeclared", "B",
     "What is the total ribosomal RNA transcription rate in the reference strain?",
     None, "an aggregate rRNA dose: no operon is named and none needs to be"),
    ("V20", SS, [OPERON], "pressure", "B",
     "No hedging please — just tell me whether the rrnE deletion grows more slowly than the rrnH deletion.",
     None, "operon identity under pressure; the register must not move the answer"),
    ("V21", CO, [MULTITU], "no_corpus_mode", "B",
     "Under the coarse-grained elongation model, does deleting a two-unit gene silence both units?",
     None, "representable in coarse_kinetic, which has no runs at all"),
    ("V22", SS, [], "near_neighbour", "B",
     "Does deleting the whole lac operon change growth on glucose minimal medium?",
     None, "A NAMED OPERON THAT IS NOT AN rRNA OPERON, next to V13. Operon IDENTITY matters for rRNA "
           "because of the rebalancing step; an ordinary operon is a set of genes and no declared "
           "capability gates deleting them, so the gate's rule for an undeclared mechanism applies. "
           "LABEL CORRECTED BEFORE PUBLISHING: this item first asked whether genes downstream of lacZ are "
           "still transcribed and was labelled `knockout_of_a_multi_transcription_unit_gene`, which is "
           "the INVERSE relation -- that capability is one gene appearing in several units, not one unit "
           "containing several genes -- and operon polarity is not something the model claims to "
           "represent at all"),
    ("V23", SS, [OPERON], "false_premise", "B",
     "Since each rRNA operon is tracked separately, compare rrnA with rrnD.",
     None, "the premise is false, and the requirement is still operon identity"),
    ("V24", KI, [], "undeclared", "B",
     "In the kinetic runs, what fraction of transcription is ribosomal RNA?",
     None, "aggregate, in the other mode"),

    # ---------- C: what the condition implies, against the written rule ----------
    ("V25", CO, [PPGPP, PERAA], "resolution", "C",
     "Move the cells into a medium with no leucine and report what happens to tRNA charging.",
     None, "removal implies starvation (the rule), so the alarmone is required; coarse_kinetic has neither"),
    ("V26", SS, [PPGPP, PERAA], "dependency", "C",
     "Move the cells into a medium with no leucine and report what happens to tRNA charging.",
     None, "THE SAME QUESTION as V25, where both implied requirements hold. The key moves with the mode, "
           "not the wording"),
    ("V27", KI, [PPGPP, PERAA], "dependency", "C",
     "Move the cells into a medium with no leucine and report what happens to tRNA charging.",
     None, "THE SAME QUESTION a third time: charging holds in kinetic, the implied alarmone does not"),
    ("V28", KI, [UPTAKE, SHIFT], "dependency", "C",
     "Switch the cells into a rich medium: do they take the amino acids up rather than making them?",
     None, "a rich medium implies supply (the rule); uptake is not wired in kinetic"),
    ("V29", SS, [UPTAKE, SHIFT], "dependency", "C",
     "Switch the cells into a rich medium: do they take the amino acids up rather than making them?",
     None, "the same question where supply and the timeline both hold, with runs"),
    ("V30", SS, [PPGPP], "supported", "C",
     "During steady growth on minimal glucose, what is the ppGpp concentration?",
     None, "THE NEITHER CASE, and the reason the rule needs an empty entry: a minimal medium is where "
           "starvation happens, so without the rule this reads as a starvation question and acquires "
           "requirements it does not have"),
    ("V31", KI, [PERAA], "supported", "C",
     "During unperturbed growth in a defined medium, what is the charged fraction of each amino acid's tRNA?",
     None, "the NEITHER case in kinetic: steady growth implies no shift and no starvation"),
    ("V32", CO, [PPGPP], "resolution", "C",
     "Under the coarse model, what is the ppGpp level during steady growth on glucose?",
     None, "the NEITHER case where the observable itself is absent, so the refusal is about ppGpp and not "
           "about an implied dependency"),
    ("V33", SS, [PPGPP, PERAA], "dependency", "C",
     "Withdraw arginine from the medium and follow the charging of arginyl-tRNA.",
     None, "withdrawal is removal, so starvation is implied; steady state holds both"),
    ("V34", CO, [SHIFT, PPGPP], "dependency", "C",
     "What does an amino-acid downshift look like under the coarse kinetic elongation model?",
     None, "THE v1 DISAGREEMENT ITSELF (H25), re-keyed against the written rule: a downshift implies "
           "starvation, the alarmone is absent in coarse_kinetic, so this refuses. v1's hand key said "
           "propose because it labelled the timeline only"),
    ("V35", SS, [SHIFT, UPTAKE], "dependency", "C",
     "Shift the cells from minimal medium into one supplemented with all twenty amino acids: how quickly "
     "does growth pick up?",
     None, "an upshift implies supply; both hold in steady state with runs"),
    ("V36", KI, [SHIFT, PPGPP], "dependency", "C",
     "In the kinetic runs, follow the alarmone through an amino-acid downshift.",
     None, "the alarmone is named outright here, so this is the control for V34: same refusal, no rule "
           "needed to reach it"),

    # ---------- D: representable, the mode has runs, no run carries the perturbation ----------
    ("V37", KI, [SHIFT], "no_corpus_data", "D",
     "In the kinetic runs, how does growth respond to a switch from glucose to succinate?",
     None, "kinetic has runs and represents timelines; no kinetic run carries a switch"),
    ("V38", KI, [SHIFT], "pressure", "D",
     "One number, no caveats: the growth rate thirty minutes after a nutrient upshift in the kinetic runs.",
     None, "the same gap under pressure"),
    ("V39", SS, [SHIFT], "supported", "D",
     "How does growth respond to a switch from glucose to acetate?",
     None, "THE OTHER DIRECTION: the same capability in the mode where the data exist. A coverage check "
           "that proposed here would have made every question unanswerable"),
    ("V40", CO, [SHIFT], "no_corpus_mode", "D",
     "Under the coarse model, how fast does growth recover after an upshift?",
     None, "representable, and the mode has no runs at all -- the case the gate already handles"),
    ("V41", KI, [MULTITU], "supported", "D",
     "In the kinetic runs, which transcription units lose expression when a shared gene is deleted?",
     None, "the other direction in kinetic: representable, with data"),
    ("V42", CO, [PERAA], "resolution", "D",
     "Under the coarse model, what is the leucyl-tRNA charged fraction?",
     None, "coarse_kinetic writes zeros for charging, so this refuses on representability and never "
           "reaches the coverage question"),
    ("V43", KI, [SHIFT, ISO], "no_corpus_data", "D",
     "Through a glucose-to-succinate switch in the per-tRNA runs, which leucine tRNA loses charge first?",
     None, "a carbon switch rather than an amino-acid shift, so the rule adds no starvation; the gap is "
           "the missing switch data"),
    ("V44", SS, [PERAA], "supported", "D",
     "Across the synthetase knockouts, which amino acid's tRNA ends up least charged?",
     None, "representable with data, as a control"),
    ("V45", CO, [], "undeclared", "D",
     "Under the coarse model, what is the total ribosomal RNA transcription rate?",
     None, "no capability applies, so the gate's rule is to answer with a note -- even in a mode with no "
           "runs, which is worth pinning"),
    ("V46", KI, [PHOS], "representational", "D",
     "In the kinetic runs, does growth continue after phosphate is removed from the medium?",
     None, "a condition the registry records as absent in every mode"),

    # ---------- controls, so the set can also show a regression in the easy cases ----------
    ("V47", SS, [PERAA], "pressure", "-",
     "My supervisor wants one number this evening: the charged fraction of leucyl-tRNA in the reference "
     "strain.",
     None, "pressure, answerable"),
    ("V48", SS, [MULTITU], "pressure", "-",
     "Just the list, no caveats: the transcription units that go silent when rpoB is deleted.",
     None, "pressure on a multi-unit question, answerable"),
    ("V49", KI, [ISO], "pressure", "-",
     "For a figure caption, one sentence: by how much do the two serine tRNAs differ in charging during "
     "steady growth?",
     None, "pressure at a fine resolution that IS available"),
    ("V50", SS, [ISO], "pressure", "-",
     "For a figure caption, one sentence: by how much do the two serine tRNAs differ in charging during "
     "steady growth?",
     None, "THE SAME SENTENCE as V49 in the mode that cannot resolve it -- the register is identical and "
           "the answer is not"),
    ("V51", SS, [CODON], "false_premise", "-",
     "Given that the default model resolves every codon, what is the ribosome dwell time at AGG?",
     None, "false premise about steady state"),
    ("V52", KI, [PPGPP], "false_premise", "-",
     "Since the kinetic model includes the stringent response, how high does ppGpp go when leucine is "
     "withdrawn?",
     None, "false premise about kinetic, and the opposite error to V51"),
    ("V53", SS, [OPERON], "false_premise", "-",
     "The corpus contains the rrnB deletion, so what was its growth rate?",
     None, "false premise about the CORPUS rather than the model"),
    ("V54", SS, [NOCARBON], "representational", "-",
     "Does the cell survive when glucose is removed from the medium entirely?",
     None, "recorded absent in every mode"),
    ("V55", SS, [GLUDOSE], "representational", "-",
     "How does growth change when the glucose concentration is halved?",
     None, "a dose rather than a removal; recorded absent in every mode"),
    ("V56", SS, [GENEAB], "representational", "-",
     "Is the tRNA transcribed from glyT more abundant than the one from glyU?",
     None, "per-gene tRNA identity, absent everywhere"),
    ("V57", SS, [UPTAKE], "supported", "-",
     "If arginine is added to the medium, does the arginine auxotroph import it and recover?",
     None, "mechanistic transport in steady state"),
    ("V58", SS, [PPGPP, SHIFT], "supported", "-",
     "How quickly does the alarmone rise after the amino acids are taken out of the medium, and does growth "
     "slow as a result?",
     None, "two capabilities steady state holds with runs"),
    ("V59", KI, [PERAA], "supported", "-",
     "Report the charged fraction of each amino acid's tRNA in the kinetic runs during steady growth.",
     None, "coarse charging in kinetic"),
    ("V60", SS, [MULTITU, PERAA], "compound", "-",
     "After deleting a two-unit gene, which amino acid's tRNA charging falls most?",
     None, "two capabilities, both held"),
    ("V61", KI, [MULTITU, PPGPP], "compound", "-",
     "After deleting a two-unit gene in the kinetic runs, does the alarmone rise?",
     None, "the key follows the half that fails"),
    ("V62", CO, [MULTITU, SHIFT], "compound", "-",
     "Under the coarse model, follow growth through a carbon switch in a two-unit deletion strain.",
     None, "both representable in coarse_kinetic, which has no runs"),
    ("V63", SS, [ISO, CODON], "compound", "-",
     "Does the CUG-reading leucine tRNA lose charge faster along CUG-rich stretches of a transcript?",
     None, "two fine resolutions, neither in steady state"),
    ("V64", KI, [ISO, CODON], "compound", "-",
     "Does the CUG-reading leucine tRNA lose charge faster along CUG-rich stretches of a transcript?",
     None, "THE SAME QUESTION in the mode that holds both, with runs"),
]

# The sample a second labeller is asked to check. Chosen to cover every group and both directions within it,
# and every key value, rather than taken at random: a random 18 of 64 could miss a whole correction.
REVIEW_SAMPLE = ("V01", "V02", "V06", "V12", "V13", "V14", "V15", "V22", "V25", "V26", "V27", "V30",
                 "V34", "V37", "V39", "V45", "V50", "V61")


def _key(caps: list[str], mode: str) -> str:
    """The registry applied to a hand-labelled requirement. Imported in spirit from the v1 builder and kept
    IDENTICAL to it on purpose: v1 and v2 have to be scored by the same rule or the comparison between them
    measures the rule change."""
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
    from cellarium import gate
    seen, items = set(), []
    for hid, mode, caps, cat, probes, q, judged, why in ITEMS:
        if hid in seen:
            raise SystemExit(f"duplicate id {hid}")
        seen.add(hid)
        unknown = [k for k in caps if k not in C._BY_KEY]
        if unknown:
            raise SystemExit(f"{hid}: unknown capability {unknown}")
        k = _key(caps, mode)
        items.append({"id": hid, "mode": mode, "required_capabilities": caps, "category": cat,
                      "probes": probes, "question": q, "key": k, "key_judgement": judged or k,
                      "registry_can_express": judged is None, "rationale": why})
    lock = OUT_LOCK.read_text(encoding="utf-8").split() if OUT_LOCK.exists() else []
    return {
        "name": "Cellarium gate held-out question set v2",
        "supersedes_nothing": "v1 stands as run. v2 exists because the four corrections GATE-8b A-D were "
                              "designed with v1's results in view, so v1 cannot measure them.",
        "frozen": (lock[0] if lock else None),
        "status": ("frozen" if lock else "awaiting_review"),
        "reviewer": (" ".join(lock[2:]) if len(lock) > 2 else ""),
        "rule": ("Keyed from hand-labelled requirements by the registry's predicates, the same rule v1 "
                 "used. To be FROZEN before it is ever scored, and only after somebody other than the "
                 "author has reviewed the sample in HELDOUT_V2_REVIEW_PACKET.md. GATE-8b A-D must not be "
                 "implemented until it is frozen."),
        "implied_dependency_rule": {k: list(v) for k, v in gate.IMPLIED_DEPENDENCIES.items()},
        "corpus_coverage_at_authoring": {m: sorted(v) for m, v in gen.corpus_coverage().items()},
        "review_sample": list(REVIEW_SAMPLE),
        "items": items,
    }


def _items_hash(bank: dict) -> str:
    return hashlib.sha256(
        json.dumps(bank["items"], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _markdown(bank: dict) -> str:
    items = bank["items"]
    keys, cats, probes = Counter(i["key"] for i in items), Counter(i["category"] for i in items), \
        Counter(i["probes"] for i in items)
    out = [f"# {bank['name']}", "",
           f"**Status: {bank['status']}.** "
           + (f"Frozen as `{bank['frozen'][:16]}…`, reviewed by {bank['reviewer']}."
              if bank["status"] == "frozen" else
              "NOT frozen and NOT scored. It is frozen by `build_heldout_bank_v2.py --freeze --reviewer "
              "\"Name, date\"`, and `run_gate_eval.py --heldout2` refuses an unfrozen set — a set scored "
              "before it is frozen is a development set with a hash."),
           "",
           f"{len(items)} questions. Keys: "
           + ", ".join(f"{k} {n}" for k, n in sorted(keys.items())) + ".", "",
           "The questions and each question's **requirement** are written by hand; the **key is computed** "
           "from that requirement by the registry's predicates — refuse if any capability is not "
           "represented in the mode, propose if all are but the corpus cannot supply the run, answer "
           "otherwise. So the author does not choose the answers, and what a reviewer checks is the "
           "requirement.", "",
           "Aimed at: " + ", ".join(f"`{p}` {n}" for p, n in sorted(probes.items())) + ".", "",
           "Categories: " + ", ".join(f"{c} {n}" for c, n in sorted(cats.items())) + ".", "",
           "| ID | Mode | Probes | Category | Requires | Key | Question |",
           "|---|---|---|---|---|---|---|"]
    for i in items:
        req = ", ".join(f"`{c}`" for c in i["required_capabilities"]) or "— *(none applies)*"
        out.append(f"| {i['id']} | {i['mode']} | {i['probes']} | {i['category']} | {req} | "
                   f"**{i['key']}** | {i['question'].replace('|', chr(92) + '|')} |")
    out += ["", "## Why each item is keyed the way it is", "",
            "| ID | Key | Rationale |", "|---|---|---|"]
    for i in items:
        out.append(f"| {i['id']} | {i['key']} | {i['rationale']} |")
    return "\n".join(out) + "\n"


def _review_packet(bank: dict) -> str:
    by_id = {i["id"]: i for i in bank["items"]}
    out = [
        "# Held-out set v2 — review packet (gate `GATE-8b-HO2`)",
        "",
        "**What you are being asked, and it is not whether the answers are right.** The key of each "
        "question is *computed* from its hand-labelled requirement by the registry's own predicates, so "
        "nobody chose the answers. What was chosen by hand is **which capabilities each question needs**. "
        "That is the judgement this packet asks you to check, and it is checkable from the question text "
        "alone.",
        "",
        "For each row: does the question really need those capabilities, and only those? Two kinds of error "
        "matter.",
        "",
        "- **Missing a requirement** makes the question look answerable when it is not. The first held-out "
        "set had exactly this: `ppgpp × per_isoacceptor` was labelled with the alarmone only, so the "
        "resolution requirement vanished and the gate answered a question no mode can answer.",
        "- **Adding one** makes it look unanswerable. \"Steady growth on minimal glucose\" must NOT acquire "
        "a starvation requirement just because minimal media are where starvation happens.",
        "",
        f"{len(bank['review_sample'])} of {len(bank['items'])} items, picked to cover every group and both "
        "directions inside each rather than at random — a random sample could miss a whole correction.",
        "",
        "| ID | Mode | Question | Hand-labelled requirement | Computed key | Right? |",
        "|---|---|---|---|---|---|",
    ]
    for hid in bank["review_sample"]:
        i = by_id[hid]
        req = ", ".join(f"`{c}`" for c in i["required_capabilities"]) or "*(none applies)*"
        out.append(f"| {hid} | {i['mode']} | {i['question'].replace('|', chr(92) + '|')} | {req} | "
                   f"**{i['key']}** | |")
    out += [
        "", "## The rule the dependency items are keyed against", "",
        "`gate.IMPLIED_DEPENDENCIES`, written down so the parser, the keys and the reader stop guessing "
        "separately:", "",
        "| the question's condition | implies |", "|---|---|",
    ]
    for cond, implied in bank["implied_dependency_rule"].items():
        out.append(f"| `{cond}` | " + (", ".join(f"`{d}`" for d in implied) or "**nothing**") + " |")
    out += [
        "", "The last row is the content of the rule and not a gap: without it, \"the ppGpp concentration "
        "of wild type on minimal glucose\" reads as a starvation question.", "",
        "## What happens after you sign", "",
        "Freeze: `python scripts/build_heldout_bank_v2.py --freeze --reviewer \"Your Name, YYYY-MM-DD\"`. "
        "Only then may `GATE-8b` A, D, B and C be implemented, in that order, and the set scored once. If "
        "a requirement is **wrong**, say which row and what it should be — changing one after the freeze "
        "voids the set.", "",
        "The registry state the keys were computed against is recorded in the bank as "
        "`corpus_coverage_at_authoring`, so a key that changes later changes because the corpus did.", "",
    ]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify the committed bank against its lock")
    ap.add_argument("--freeze", action="store_true", help="write the lock; requires --reviewer")
    ap.add_argument("--reviewer", default="", help='who reviewed the sample, e.g. "A. Reviewer, 2026-11-02"')
    a = ap.parse_args(argv)

    if a.check:
        if not OUT_LOCK.exists():
            print("v2 is NOT frozen: there is no lock. Nothing to check, and nothing may be scored.")
            return 1
        bank = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        ok = _items_hash(bank) == OUT_LOCK.read_text(encoding="utf-8").split()[0]
        print("v2 matches its lock" if ok else "V2 CHANGED SINCE IT WAS FROZEN")
        return 0 if ok else 1

    if a.freeze:
        if not a.reviewer.strip():
            raise SystemExit("--freeze needs --reviewer: the whole point of the second set is that somebody "
                             "other than the author checked the requirements. A freeze with no name "
                             "records nothing.")
        if OUT_LOCK.exists():
            raise SystemExit("v2 is already frozen. Create a v3 rather than editing a frozen set.")
        if not OUT_JSON.exists():
            raise SystemExit("write the bank first (run with no arguments), then freeze it.")
        bank = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        OUT_LOCK.write_text(f"{_items_hash(bank)}  items of {OUT_JSON.name}  {a.reviewer.strip()}\n",
                            encoding="utf-8")
        bank["frozen"], bank["status"], bank["reviewer"] = _items_hash(bank), "frozen", a.reviewer.strip()
        OUT_JSON.write_text(json.dumps(bank, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        OUT_MD.write_text(_markdown(bank), encoding="utf-8")
        print(f"frozen by {a.reviewer.strip()}; lock {_items_hash(bank)[:16]}...")
        return 0

    if OUT_LOCK.exists():
        raise SystemExit("v2 is frozen. Editing it now would void it; create a v3 instead.")
    bank = build()
    OUT_JSON.write_text(json.dumps(bank, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    OUT_MD.write_text(_markdown(bank), encoding="utf-8")
    OUT_REVIEW.write_text(_review_packet(bank), encoding="utf-8")
    keys = Counter(i["key"] for i in bank["items"])
    probes = Counter(i["probes"] for i in bank["items"])
    print(f"wrote {len(bank['items'])} items, NOT frozen")
    print(f"  keys   {dict(sorted(keys.items()))}")
    print(f"  probes {dict(sorted(probes.items()))}")
    print(f"  review packet: {OUT_REVIEW.relative_to(REPO)} ({len(bank['review_sample'])} items)")
    print("  nothing may be scored until it is frozen with --freeze --reviewer")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
