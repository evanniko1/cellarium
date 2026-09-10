"""AG-2b — the targeted probe that decides which tools have actually earned their place.

WHY A SECOND SWEEP RATHER THAN A CULL. The 2026-09-08 A/B sweep (`evals/results/ag2_tool_selection.json`)
called 45 of 72 tools and left 27 untouched, which reads like a mandate to delete 27 tools. It is not, and
the reason is a property of that sweep rather than of the tools: it answers science questions from the
existing corpus, so it never proposes an experiment, never launches one, never vets or prunes anything, and
never asks what is free on the machine. **13 of the 27 were unreachable by construction.** The remaining 14
were reachable, but none of the 25 canonical questions goes anywhere near flux-balance analysis or
charged-tRNA families, so their zeros say "nobody asked", not "nobody needs this".

WHAT THIS FILE IS. One question per never-selected tool, written so that the tool is the obvious instrument
for a question a scientist would actually ask. **Never "call tool X"** — that would measure instruction
following, which is not in doubt. The measurement is SELECTION: given a question squarely in a tool's
domain, does the agent reach for it?

THE DISTINCTION THAT MAKES THE RESULT READABLE, and the one AG-2 got wrong by counting instead of reading:
**selection and success are different outcomes.** ~26 of the 35 errors in the first sweep were
`no local raw simOut` — the agent picked the right tool and the machine did not have the data. A tool that
is selected and then fails on data locality has PASSED this probe; it is the tool nobody reaches for that
has failed. `evals/tool_probe.py` records the two separately and never merges them.

A tool that stays unselected HERE, with the question aimed straight at it, is the one that has earned
removal — and even then the honest reading is "the agent does not know when to use this", which is as often
a description problem as a tool problem.
"""

from __future__ import annotations

# `expect` is the tool this question is aimed at. `also_ok` are tools whose selection is a REASONABLE
# alternative reading of the same question -- recorded so a near-miss is visible as a near-miss rather than
# scored as a failure. `family` says which of the three unreachability arguments the case tests.
CASES = [
    # --- Family A: reachable in the first sweep, simply never asked about ----------------------------
    {
        "id": "P-A1", "family": "reachable", "expect": "read_species",
        "also_ok": ["read_raw_series", "raw_available", "data_availability", "list_results"],
        "question": "I want the actual time course of a single molecule in one run — GapA protein copy "
                    "number, every timestep, for one wild-type seed. Not a summary or a mean: the "
                    "trajectory itself. Can you get it?",
    },
    {
        "id": "P-A2", "family": "reachable", "expect": "rnaseq_concordance",
        "also_ok": ["differential", "top_movers"],
        "question": "How well does this model's simulated transcriptome actually agree with real measured "
                    "E. coli RNA-seq? I want the per-gene fold-change agreement for a matched condition "
                    "contrast, against a null baseline — not a hand-wave that it 'looks reasonable'.",
    },
    {
        "id": "P-A3", "family": "reachable", "expect": "scan_series",
        "also_ok": ["read_raw_series", "shift_response", "raw_available"],
        "question": "After a nutrient downshift, is there a short ppGpp transient that a coarse "
                    "sixteen-point view of the trajectory would flatten out and hide? I need every "
                    "timestep scanned for spikes and level shifts, with the false-discovery rate controlled.",
    },
    {
        "id": "P-A4", "family": "reachable", "expect": "screen_phenotype",
        "also_ok": ["top_movers", "differential", "screen_design"],
        "question": "Set aside what the designs were meant to do — do any of their simulated proteomes "
                    "actually come out up-regulating antimicrobial-resistance efflux relative to wild type? "
                    "I want the phenotype screened, not the stated intent.",
    },
    {
        "id": "P-A5", "family": "reachable", "expect": "selective_charging",
        "also_ok": ["trna_families", "differential"],
        "question": "In the argS knockout, which tRNA families lose charged fraction the most — and is that "
                    "drop bigger than what two wild-type lineages already show against each other?",
    },
    {
        "id": "P-A6", "family": "reachable", "expect": "serialization_check",
        "also_ok": ["experiment_integrity", "provenance"],
        "question": "Before I quote anything from the stored simulation output: is there a risk some of it "
                    "was silently truncated when it was written to disk? I am worried about values that "
                    "were cut short with no error raised.",
    },
    {
        "id": "P-A7", "family": "reachable", "expect": "similar_designs",
        "also_ok": ["comparable_designs", "differential"],
        "question": "Which other designs in the corpus came out looking like KO:argS — similar by the "
                    "mechanism of their response profile, not merely because they are equally sick?",
    },
    {
        "id": "P-A8", "family": "reachable", "expect": "viability_surrogate",
        "also_ok": ["lethality_landscape", "check_feasibility", "design_space"],
        "question": "A single knockout simulation costs hours. Before I spend that, can you predict from "
                    "cheap a-priori gene properties whether knocking out murA is likely to be viable, so I "
                    "can triage what is worth running?",
    },

    # --- Family B: the FBA cluster -- reachable, but no canonical question is flux-shaped -------------
    {
        "id": "P-B1", "family": "fba", "expect": "fba_qc",
        "also_ok": ["model_validation", "experiment_integrity"],
        "question": "Before I trust a single flux-balance number: is the metabolic model itself sane? With "
                    "every nutrient uptake closed it should not be able to make ATP or biomass out of "
                    "nothing, and its internal reactions should mass-balance.",
    },
    {
        "id": "P-B2", "family": "fba", "expect": "fba_gene_knockout",
        "also_ok": ["fba_growth", "fba_flux", "metabolic_essentiality"],
        "question": "What does genome-scale flux-balance analysis say about deleting pgi on its own, and "
                    "does that call agree with the Keio experimental knockout collection?",
    },
    {
        "id": "P-B3", "family": "fba", "expect": "fba_gene_deletion",
        "also_ok": ["fba_synthetic_lethal", "fba_growth"],
        "question": "If I delete tpiA, pfkA and pgi all together in one strain, does it still grow? I mean "
                    "all three at once, not three separate single deletions.",
    },
    {
        "id": "P-B4", "family": "fba", "expect": "fba_synthetic_lethal",
        "also_ok": ["fba_gene_deletion", "fba_gene_knockout"],
        "question": "Among the glycolysis genes pgi, pfkA, tpiA, fbaA and gapA, are there any pairs that are "
                    "each fine on their own but lethal together? I am looking for backup pathways that only "
                    "show up when both routes are removed.",
    },
    {
        "id": "P-B5", "family": "fba", "expect": "fba_essentiality_panel",
        "also_ok": ["fba_gene_knockout", "metabolic_essentiality"],
        "question": "Across the metabolic gene set as a whole, how well do the model's essentiality calls "
                    "match the Keio benchmark? Give me the overall agreement properly — most genes are "
                    "non-essential, so raw accuracy would flatter it.",
    },
    {
        "id": "P-B6", "family": "fba", "expect": "fba_sensitivity",
        "also_ok": ["fba_growth", "robustness_check"],
        "question": "How much does the flux-balance growth prediction actually move if I vary glucose "
                    "uptake and the maintenance ATP terms by twenty percent either way? I want to know "
                    "whether a conclusion survives that spread before I rely on it.",
    },

    # --- Family C: the proposal/launch path -- unreachable in a corpus-reading arm BY CONSTRUCTION ----
    {
        "id": "P-C1", "family": "proposal", "expect": "propose_experiment",
        "also_ok": ["check_feasibility", "design_space", "run_experiment"],
        "question": "The corpus has nothing on how this organism handles a sudden shift into nitrate "
                    "respiration. I want that data. What single experiment should I run to get it?",
    },
    {
        "id": "P-C2", "family": "proposal", "expect": "propose_experiments",
        "also_ok": ["propose_experiment", "design_panel", "generate_designs"],
        "question": "I want to settle whether ribosomal-protein knockouts share a common collapse "
                    "signature. Give me a whole panel of experiments to run, in one go, not one at a time.",
    },
    {
        "id": "P-C3", "family": "proposal", "expect": "design_panel",
        "also_ok": ["power_check", "propose_experiments", "coverage_check"],
        "question": "I need to falsify a claim properly rather than guess at a run count. How many seeds and "
                    "how many generations should the panel have, laid out as a real design of experiments?",
    },
    {
        "id": "P-C4", "family": "proposal", "expect": "estimate_sim_resources",
        "also_ok": ["system_resources", "check_feasibility"],
        "question": "I am considering a sweep of twenty designs at five seeds each. Would that even fit on "
                    "this machine — memory and disk — or am I about to fill the drive?",
    },
    {
        "id": "P-C5", "family": "proposal", "expect": "generate_designs",
        "also_ok": ["design_space", "propose_experiments", "prune_candidates"],
        "question": "Generate some candidate reduced-genome strains for me — multi-gene knockout sets — and "
                    "rank them by how likely they are to stay viable.",
    },
    {
        "id": "P-C6", "family": "proposal", "expect": "prune_candidates",
        "also_ok": ["corpus_audit", "coverage_check"],
        "question": "I am short of disk. Which run directories are genuinely safe to delete — the redundant "
                    "extra seeds — without losing anything the corpus depends on?",
    },
    {
        "id": "P-C7", "family": "proposal", "expect": "propose_rebuild",
        "also_ok": ["deg_rate_provenance", "provenance", "operon_mode_advice"],
        "question": "The fitted parameters themselves are what I want to change, not the simulation — I want "
                    "the knowledge base refitted with different assumptions. How do I propose that?",
    },
    {
        "id": "P-C8", "family": "proposal", "expect": "run_experiment",
        "also_ok": ["check_feasibility", "vet_hypothesis", "screen_design"],
        "question": "I want to run a knockout of lpxC in minimal glucose. Before anything launches, check it "
                    "is within what the model can legitimately do and that it is not already in the corpus.",
    },
    {
        "id": "P-C9", "family": "proposal", "expect": "screen_design",
        "also_ok": ["vet_hypothesis", "screen_phenotype", "run_experiment"],
        "question": "Here is a proposed design: knock out the efflux repressor and grow under sub-lethal "
                    "antibiotic. Screen the intent of that design for misuse before I go any further.",
    },
    {
        "id": "P-C10", "family": "proposal", "expect": "vet_hypothesis",
        "also_ok": ["check_feasibility", "run_experiment", "power_check"],
        "question": "I have a proposed experiment and I want it vetted in one pass — safety, whether the "
                    "model can actually represent it, and whether it is worth the compute.",
    },
    {
        "id": "P-C11", "family": "proposal", "expect": "system_resources",
        "also_ok": ["estimate_sim_resources"],
        "question": "What is actually free on this machine right now — memory, disk, cores? I want to know "
                    "before I start anything.",
    },
    {
        "id": "P-C12", "family": "proposal", "expect": "corpus_audit",
        "also_ok": ["survey_corpus", "coverage_check", "prune_candidates"],
        "question": "Give me an inventory of the whole corpus: what is covered, where the redundancy is, and "
                    "where the gaps are. I am trying to decide what to run next.",
    },
    {
        # revise_experiment edits a PENDING draft, so it is only reachable after one exists. The question is
        # phrased as the second half of that exchange; if it is unreachable in a single turn, that is a fact
        # about the tool's precondition and is reported as such rather than as a selection failure.
        "id": "P-C13", "family": "proposal", "expect": "revise_experiment",
        "also_ok": ["propose_experiment", "run_experiment"],
        "question": "That experiment you just drafted — change it to use five seeds instead of one, and "
                    "leave everything else alone.",
    },
]


def by_id(ids: list[str] | None) -> list[dict]:
    if not ids:
        return CASES
    keep = set(ids)
    return [c for c in CASES if c["id"] in keep]


def expected_tools() -> set[str]:
    return {c["expect"] for c in CASES}
