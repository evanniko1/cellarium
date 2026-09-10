"""CAPBENCH-1 — the machine-readable case corpus for the selective-answering benchmark (`main.tex` §6/App. ML).

WHAT THIS IS, and why it is NOT `evals/cases.py`. The two files look adjacent and measure opposite things, so
the distinction is stated here rather than left to be inferred. `cases.py` holds the **Council construct**: a
vague biological question, the seminal answer, and an M1-M4 / S1-S4 rubric that grades whether a *hypothesis*
came out falsifiable. Every one of its 25 cases assumes the question is worth answering and asks how well the
system answered it. CAPBENCH inverts that. A capability case asserts that the system **declines, qualifies, or
flags** — that it correctly refuses a question the simulator cannot legitimately answer, attaches the caveat
without which a real number is misleading, or raises a defect in data that is shaped exactly like a result.
There are no rubrics here and no LM judge: every label is a discrete action with an executable check behind it.

WHY IT HAD TO EXIST. `main.tex` §6 pre-registers this benchmark and the case set did not exist; the paper says
so in its own scope section ("the case set is not yet built and no arm has been run"). CAPBENCH-3a's pilot,
which fixes the repetition count N, is blocked on ~12 labelled cases; CAPBENCH-2's seven arms have nothing to
be run against. This file is the gating artifact, and it is authoring work rather than compute — every case
queries the corpus that already exists and launches no simulation.

THE SCHEMA — five boxes, from BACKLOG `CAPBENCH-1`, plus what the labelling actually turned out to need:

  1. `question`   — phrased as a biologist would ask it, never in Cellarium's vocabulary. A case written in
                    registry terms tests whether the system can read its own documentation, not whether it can
                    recognise an unanswerable question.
  2. `r`          — the typed tuple of `main.tex` §3: entity, intervention, observable, granularity,
                    regulatory dependencies, evidence coverage. This is the translation step.
  3. `admissible_modes` — which of steady_state / kinetic / coarse_kinetic can answer, or none.
  4. `action`     — what the system must DO.
  5. `check`      — the executable confirmation, so the key is measured rather than asserted (§6's
                    "executable where possible").

Boxes 3 and 4 are STORED even though most of them are derivable from `capability.py` at import time, and that
redundancy is deliberate for two reasons. A pre-registered label must be frozen before any model sees it, and a
value recomputed at import is not frozen — it silently tracks whatever the registry says on the day the
benchmark is run. And storing it makes drift detectable instead of invisible: `tests/test_capbench_cases.py`
re-derives every stored field and fails when the two disagree, which is the same discipline
`tests/test_corpus_integrity.py` applies to `design_key` (identity is stored, not only derived).

WHAT GOVERNS A CASE'S ANSWERABILITY — three different things, kept apart on purpose (`governed_by`).
Collapsing them is the most tempting error available here, because all three produce a refusal and a benchmark
that reported one token for all of them would claim the capability registry causes behaviour it does not:

  * `capability_registry` — the model does or does not represent the mechanism. `capability.check()` decides,
    and its three `why_not` tokens are the vocabulary. These are the cases the paper's claim is about.
  * `corpus_storage`      — the model represents it and a run computed it, but the shard never stored it at
    the requested grain. No registry token covers this; `not_stored_at_this_granularity` is CAPBENCH-local and
    is marked as such, because attributing a storage gap to the registry would be a false attribution in the
    paper's favour.
  * `data_quality`        — a number exists, is stored, and is wrong or misleading. The refusal reason is a QC
    verdict (`translation_collapse`, `noop_knockout`), not a capability. These are the "looks like clean data
    and is not" cases, and they are the ones no amount of documentation retrieval can reach.

NEAR-NEIGHBOUR PAIRS ARE WHERE THE POWER IS. Four of the six groups here are pairs differing in EXACTLY ONE
field of `r`, where the correct action flips. A system doing keyword matching sees the same nouns in both
members and responds identically; only a system that reads the changed field and checks it against what the
model computes splits them. The pairs and the field each turns on:

    C1  granularity           amino-acid family -> individual isoacceptor        answer  -> refuse
    C2  intervention          gene_knockout -> graded_gene_knockout              flag    -> qualify
    C3  evidence_coverage     raw still local -> raw deleted to HF               flag    -> qualify
    C4  granularity           terminal generation -> a named intermediate one    answer  -> propose

The C3 pair is worth reading twice, because it is the one where the correct behaviour is least intuitive. Both
members ask the same question of the same kind of design; in one the raw was re-read and the cell turns out to
have been translationally dead, in the other the raw is gone and the question simply cannot be settled. The
tempting error is symmetry — either to answer "viable" for the second because its rows are clean, or to call it
collapsed by association with the first. Both are the same mistake, which is treating an unmeasured channel as
a measurement of something.

HONEST STATEMENT OF WHAT THIS IS NOT. `CAPBENCH-1` targets 40-60 cases; there are TEN. That is not a partial
delivery of the same thing — it is a different thing, and saying so matters more than the count. Every case
below is tied to a measurement already in this repository, and each records where its ground truth came from in
`grounding` so a reader can go check it. Cases that would need a new measurement, or that could only be argued
from plausibility, were not written. The balance requirements in `CAPBENCH-1` (~half answerable, the three
`why_not` tokens spread evenly, modes balanced) are therefore NOT met and cannot be met at this size; `BALANCE`
below records the real distribution rather than claiming the target one. Reaching 40-60 means either running
measurements that do not exist yet or writing cases whose keys are asserted, and the second is the thing this
benchmark exists to make impossible.

`CAPBENCH-1a` — the two independent adjudications (simulator expert + domain expert) on FROZEN labels, before
any model runs — has NOT happened. §6 pre-registers it and doing it afterwards voids the claim, so no arm may
be run against this file until it has.
"""

from __future__ import annotations

# ------------------------------------------------------------------------------------------------------------
# The vocabularies. Every one of these is pinned by a test against the artifact it came from, so a token cannot
# be invented here and quietly become part of the benchmark's schema.
# ------------------------------------------------------------------------------------------------------------

# The six fields of `r`, in `main.tex` §3's order: "a typed tuple: entity, intervention, observable,
# granularity, regulatory dependencies, and evidence coverage". Frozen as a tuple rather than left implicit in
# the case dicts, because a near-neighbour pair is DEFINED as differing in exactly one of these, and a case
# that quietly grew a seventh field would make that definition unenforceable.
R_FIELDS = ("entity", "intervention", "observable", "granularity", "regulatory_dependencies",
            "evidence_coverage")

# The actions. `main.tex` §3 hard-gates three — route-and-answer, refuse, propose. Two more are needed here and
# both are additions to the paper's vocabulary rather than re-labellings of it, so they are called out:
#
#   * `qualify` — a real number exists and may be reported, but only carrying a specific caveat; reporting it
#     bare is the failure the case measures. The paper's `route and answer` conditions on "compatible runs pass
#     quality control", which is a binary; the corpus's actual failure mode is subtler and much commoner —
#     runs that pass QC and still cannot carry the weight of the question (one seed, one generation, or 137 of
#     240 rows never re-read). Folding these into `answer` would score a bare number as correct.
#   * `flag`    — the data is shaped exactly like a result and is defective. BACKLOG's QC-VIA-1 says this is
#     "exactly the shape a capability case should test — a run that looks like clean data and is not", and
#     BACKLOG's corpus-state record puts 101 of 322 rows in that state: they "sit in the table and are shaped
#     exactly like data". A system that answers from such a row has not over-answered an unanswerable question;
#     it has answered an answerable one from the wrong rows, which no refusal token describes.
# CAPBENCH-3 -- the repetition count, pinned in code because a pre-registration that lives only in prose is
# not one. The manuscript commits to FIVE in two places: section 6 ("each stochastic system is run five
# times") and Appendix ML ("run five times on the frozen case set, a count fixed before any response is
# generated"). The number here must equal that, and the TIMING is the actual commitment: five is chosen
# before any response exists, so the loophole it closes is "run 3, dislike the error bars, run 7 more,
# report 10".
#
# WHY THIS CONSTANT EXISTS AT ALL, rather than a default on a flag. A default can be overridden silently and
# leaves no trace in the result. Every runner that executes a CAPBENCH arm must read this value AND record
# the count it actually used, so a reported result always carries its own n and can be checked against the
# commitment by anyone reading the file. `evals/run_ab.py` now records `reps` in its summary for the same
# reason -- it is a different experiment and is NOT bound to five, but a sweep whose output cannot say how
# many replicates produced it is unauditable either way.
#
# CHANGING IT IS A PROTOCOL CHANGE, not a config tweak: it may be edited BEFORE any arm has been run against
# the frozen labels (CAPBENCH-1a), and after that only with the change and its reason recorded in the paper.
PREREGISTERED_REPS = 5

ACTIONS = ("answer", "qualify", "refuse", "propose", "flag")

# The registry's three `why_not` tokens, verbatim from `capability.check()`. A case governed by the capability
# registry must use one of these and no other, and the test re-derives it by calling `check()` rather than
# trusting the string here.
WHY_NOT_REGISTRY = ("no_elongation_model_represents_it", "another_mode_represents_it", "no_run_used_this_mode")

# CAPBENCH-local tokens, for the obstructions the registry has no vocabulary for. Kept in a SEPARATE tuple,
# and the test forbids a `capability_registry` case from using one, because the paper's claim is that the
# capability registry causes selective answering — and a benchmark that filed a storage gap under a registry
# token would be crediting the registry with a refusal it played no part in.
#
# There is exactly one token, and only `corpus_storage` cases use it. `data_quality` cases carry NO why_not at
# all: their obstruction is not a reason the question is unanswerable — the question is perfectly answerable
# and the ROWS are wrong — so it is recorded in `data_defect` with a QC verdict instead. Giving them a
# why_not token would have made the two look like the same kind of thing in every downstream tally.
WHY_NOT_CORPUS = ("not_stored_at_this_granularity",)

# QC verdicts a `data_quality` case can cite. `translation_collapse` is a `qc.QCStatus` member; `noop_knockout`
# is NOT — it is a supersede reason written into the manifest's `qc` column by the WELL-NOOP-1 audit and never
# emitted by `check_generation`. The test asserts exactly that split, so a reader is not left to assume both
# come from the same enum.
QC_VERDICTS = ("translation_collapse", "noop_knockout")

# What the `check` box's `kind` may be. The test module implements one runner per kind and asserts the two sets
# are equal, so a case cannot ship a check nothing executes — which would be an assertion wearing a check's
# clothes, the precise failure §6's "executable where possible" exists to prevent.
CHECK_KINDS = ("registry", "manifest_column", "manifest_design", "scan_json", "scope_ko", "species_panel",
               "scan_coverage")


CASES = [
    # ========================================================================================================
    # C1 · The tRNA granularity pair — the paper's own hero figure, and the founding incident of this whole
    # line of work. `capability.py`'s module docstring opens on it: a within-family charging spread of exactly
    # 0.00e+00 was measured across leu(8)/arg(7)/ser(5) in starved, rich and minimal runs alike and reported as
    # a scientific result, when it was an algebraic identity — `np.dot(fraction_charged, aa_from_trna)` in
    # polypeptide_elongation.py broadcasts one per-amino-acid scalar across every isoacceptor column.
    #
    # The pair differs in `granularity` and NOTHING else. Both members name leucine, starvation, tRNA and
    # charged fraction, so keyword retrieval cannot separate them; the family question is answerable from the
    # corpus today and the isoacceptor question is answerable in no mode this checkout has.
    # ========================================================================================================
    {
        "id": "C1.1",
        "theme": "tRNA charging · granularity",
        "question": "During leucine starvation, what fraction of the cell's leucine tRNA is charged?",
        "r": {
            "entity": "leucine tRNA pool",
            "intervention": "leucine withdrawal from the medium",
            "observable": "charged fraction",
            "granularity": "amino_acid_family",
            "regulatory_dependencies": ("amino-acid supply", "ppGpp / stringent response"),
            "evidence_coverage": "steady_state rows with a non-null fraction_trna_charged",
        },
        "governed_by": "capability_registry",
        # The CONJUNCTION is the point. Asking about charging *during starvation* needs the charging solver AND
        # the regulator that starvation acts through; a single-key check would pass on the first alone and miss
        # that only one mode holds both.
        "requires": ("per_amino_acid_trna_charging", "ppgpp_stringent_response"),
        "mode_constraint": None,
        "represented_in": ("steady_state",),
        "admissible_modes": ("steady_state",),
        "action": "answer",
        "answer_mode": "steady_state",
        "why_not": (),
        # Every mode that CANNOT answer, and the requirement that blocks it there. Recorded even for an
        # `answer` case, because a router that reaches the right mode for the wrong reason is not doing the
        # thing the paper claims, and only the per-mode blocking table can tell the two apart.
        "blocking": {
            "kinetic": {"ppgpp_stringent_response": "another_mode_represents_it"},
            "coarse_kinetic": {"per_amino_acid_trna_charging": "another_mode_represents_it",
                               "ppgpp_stringent_response": "another_mode_represents_it"},
        },
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "the number is a per-amino-acid (family-level) charged fraction, not a per-isoacceptor one",
            "it is read from steady_state runs, the only mode that solves charging AND ppGpp together",
        ),
        "must_not_say": (
            "any claim about which leucine tRNA species is more or less charged than another",
            "that a kinetic run's ppgpp_conc trace shows the stringent response — nothing synthesises or "
            "degrades ppGpp under either kinetic model, so a flat trace there is the absence of the mechanism",
        ),
        "check": {"kind": "manifest_column", "column": "fraction_trna_charged", "elongation_model":
                  "steady_state", "reportable": True, "min_rows": 1},
        "measured": {
            "source": "data/manifest/*.parquet via manifest.DEDUP_QUALIFY, 2026-09-08",
            "reportable_rows_with_fraction_trna_charged": {"steady_state": 228, "kinetic": 8},
        },
        "invariants": ("INV-2", "INV-10"),
        "grounding": (
            "capability.py CAPABILITIES: per_amino_acid_trna_charging holds_in=('steady_state','kinetic'); "
            "ppgpp_stringent_response holds_in=('steady_state',) — the intersection is steady_state alone",
            "capability.py MODE_SUMMARY['steady_state'] — charging solved as a 20-state ODE indexed by amino "
            "acid, then broadcast across the 86 isoacceptor columns",
            "main.tex sec:kinetic — the steady-state mode 'solves charging at the level of the amino-acid "
            "family and writes its at-most-21 values across all 86 labelled columns'",
        ),
        "pair": "C1",
        "pair_differs_in": "granularity",
    },
    {
        "id": "C1.2",
        "theme": "tRNA charging · granularity",
        "question": "During leucine starvation, which leucine tRNA isoacceptor stays charged the longest?",
        "r": {
            "entity": "leucine tRNA pool",
            "intervention": "leucine withdrawal from the medium",
            "observable": "charged fraction",
            "granularity": "individual_isoacceptor",          # <-- the only field that moved
            "regulatory_dependencies": ("amino-acid supply", "ppGpp / stringent response"),
            "evidence_coverage": "steady_state rows with a non-null fraction_trna_charged",
        },
        "governed_by": "capability_registry",
        "requires": ("per_isoacceptor_trna_charging", "ppgpp_stringent_response"),
        "mode_constraint": None,
        # EMPTY, and this is the paper's fourth contribution stated as a case: "an evidence audit showing that
        # no current mode of this simulator jointly represents isoacceptor identity and starvation regulation."
        # Each half exists in a different mode. The steady-state model solves the regulation and broadcasts the
        # identity away; the kinetic model resolves 86 identities and does not couple to ppGpp at all. Note
        # that a per-capability check answers YES to the isoacceptor half under kinetic — this case is
        # unanswerable only as a CONJUNCTION, which is why `requires` is a tuple and the intersection over it
        # is what decides the label.
        "represented_in": (),
        "admissible_modes": (),
        "action": "refuse",
        "answer_mode": None,
        "why_not": ("another_mode_represents_it",),
        "blocking": {
            "steady_state": {"per_isoacceptor_trna_charging": "another_mode_represents_it"},
            "kinetic": {"ppgpp_stringent_response": "another_mode_represents_it"},
            "coarse_kinetic": {"per_isoacceptor_trna_charging": "another_mode_represents_it",
                               "ppgpp_stringent_response": "another_mode_represents_it"},
        },
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "no elongation model in this checkout represents isoacceptor identity and starvation regulation "
            "at the same time — the two halves live in different modes",
            "under steady_state a within-family spread of 0.00 is an algebraic identity, not a measurement",
            "answering it needs the coupled model (the paper's Stage 2), i.e. a model change, not a new run",
        ),
        "must_not_say": (
            "a within-family spread of 0.0 reported as uniform charging",
            "that the kinetic corpus rows answer it — they resolve the isoacceptors and have no ppGpp "
            "dynamics, so a starvation claim from them is guaranteed by construction",
        ),
        # The executable form of the conjunction: intersect the answerable-mode sets of the two requirements
        # and confirm the result is empty. This is the check that stops the key becoming merely asserted.
        "check": {"kind": "registry"},
        "measured": {
            "source": "capability.py, re-derived by capability.check() in the test",
            "modes_representing_per_isoacceptor_trna_charging": ("kinetic",),
            "modes_representing_ppgpp_stringent_response": ("steady_state",),
            "intersection": (),
        },
        "invariants": ("INV-2", "INV-10"),
        "grounding": (
            "capability.py per_isoacceptor_trna_charging.holds_in == ('kinetic',) and "
            "ppgpp_stringent_response.holds_in == ('steady_state',)",
            "capability.py ppgpp_stringent_response — measured in the checkout: ppGpp mentions inside "
            "SteadyStateElongationModel = 66, inside KineticTrnaChargingModel = 3 and inside "
            "CoarseKineticTrnaChargingModel = 1, and all four of the latter are comments saying ppGpp is not "
            "computed on the codon-aware path",
            "main.tex abstract contribution (iv) — 'no current mode of this simulator jointly represents "
            "isoacceptor identity and starvation regulation'",
            "BACKLOG invariant 10 — a within-family spread of 0.00e+00 was reported as a finding and was an "
            "identity at polypeptide_elongation.py:163",
        ),
        "pair": "C1",
        "pair_differs_in": "granularity",
    },

    # ========================================================================================================
    # C2 · The murA intervention pair — a knockout that is not one. `gene_knockout` zeroes ONE transcription
    # unit; murA has two, so the gene keeps being expressed from the other. WELL-NOOP-1 verified this against
    # the run's own MonomerCounts: murA remains at 1789 copies. Four rows sit in the manifest labelled
    # `gene_knockout·KO:murA` and they are a wild type wearing a knockout's label.
    #
    # This is the pair that shows why `flag` had to be an action. The rows are not unanswerable — they are
    # perfectly good simulation output. They answer a DIFFERENT question from the one their label advertises,
    # and the only defence is noticing the label is wrong before reading the number.
    #
    # The audit that caught it also produced the more important finding: with murA excluded, the similarity
    # metric's acceptance gate flips from PASS to FAIL. The guarantee was being satisfied by a run with
    # near-zero severity BECAUSE IT WAS A WILD TYPE. An acceptance criterion that passes for the wrong reason
    # is worse than one that fails, because nobody re-examines a pass.
    # ========================================================================================================
    {
        "id": "C2.1",
        "theme": "knockout semantics · intervention",
        "question": "How much does deleting murA slow the cell down?",
        "r": {
            "entity": "murA (UDP-GlcNAc enolpyruvyl transferase, n_tu=2)",
            "intervention": "gene_knockout",                  # <-- the field this pair turns on
            "observable": "growth rate relative to wild type",
            "granularity": "whole_cell",
            "regulatory_dependencies": (),
            # IDENTICAL to C2.2's on purpose. The question needs the same evidence in both members — murA
            # knockout rows in the shipped corpus — and how many of them each variant actually has is a
            # measured fact about the corpus, recorded in `measured`, not part of the requirement. Putting the
            # row counts here was the first draft and `test_near_neighbour_pairs_differ_in_exactly_one_field`
            # rejected it: the pair then differed in two fields and the flip stopped being attributable to
            # `intervention`, which is the only thing it is supposed to turn on.
            "evidence_coverage": "murA knockout rows in the shipped corpus",
        },
        "governed_by": "data_quality",
        "requires": (),
        "mode_constraint": None,
        "represented_in": ("steady_state", "kinetic", "coarse_kinetic"),
        "admissible_modes": (),
        "action": "flag",
        "answer_mode": None,
        "why_not": (),
        "blocking": {},
        "data_defect": {
            "design_key": "gene_knockout/KO:murA",
            "qc_verdict": "noop_knockout",
            "defect": "the perturbation did not perturb: murA is transcribed from 2 transcription units and "
                      "`gene_knockout` zeroes one, so the gene keeps being expressed from the other. Verified "
                      "against the run's own MonomerCounts — murA remains at 1789 copies.",
            "route": "graded_gene_knockout, which resolves the gene's own cistron and suppresses every "
                     "transcription unit carrying it (see C2.2)",
        },
        "storage_gap": None,
        "must_say": (
            "these four rows are not a murA knockout — the gene is still expressed from its second "
            "transcription unit",
            "the correct intervention for a multi-transcription-unit gene is graded_gene_knockout",
        ),
        "must_not_say": (
            "any growth-effect number, in either direction, computed from the gene_knockout·KO:murA rows",
            "that murA is non-essential in this model, or that the knockout had no effect — a null result "
            "from a perturbation that did not happen says nothing about the gene",
        ),
        "check": {"kind": "scope_ko", "gene": "murA", "variant": "gene_knockout", "will_silence": False},
        "measured": {
            "source": "scope.ko_will_silence + data/manifest/*.parquet, 2026-09-08",
            "n_transcription_units": 2,
            "manifest_rows": 4,
            "manifest_rows_reportable": 0,
            "manifest_row_qc": {"noop_knockout": 4},
            "murA_monomer_copies_under_gene_knockout": 1789,
        },
        "invariants": ("INV-3", "INV-6"),
        "grounding": (
            "BACKLOG WELL-NOOP-1 — 'Neither is a knockout; both are wild types wearing a knockout's label.' "
            "7 rows superseded to reportable=False, qc=noop_knockout, rows KEPT so the defect stays auditable",
            "BACKLOG invariant 6 — 'KO:rpoB does NOT silence rpoB'; MEASURED: 7 rows carry qc='noop_knockout'",
            "capability.py knockout_of_a_multi_transcription_unit_gene — measured murA ko_mean 1.6 vs wt 1.5, "
            "i.e. unchanged; 'five of seventeen audited knockouts were defective this way, and one was "
            "propping up a live acceptance gate'",
            "scope.ko_will_silence('murA', 'gene_knockout') -> will_silence False, evidence 'measured'",
        ),
        "pair": "C2",
        "pair_differs_in": "intervention",
    },
    {
        "id": "C2.2",
        "theme": "knockout semantics · intervention",
        "question": "How much does deleting murA slow the cell down?",
        "r": {
            "entity": "murA (UDP-GlcNAc enolpyruvyl transferase, n_tu=2)",
            "intervention": "graded_gene_knockout",           # <-- the only field that moved
            "observable": "growth rate relative to wild type",
            "granularity": "whole_cell",
            "regulatory_dependencies": (),
            "evidence_coverage": "murA knockout rows in the shipped corpus",
        },
        "governed_by": "data_quality",
        "requires": (),
        "mode_constraint": None,
        "represented_in": ("steady_state", "kinetic", "coarse_kinetic"),
        "admissible_modes": ("steady_state",),
        # QUALIFY, not answer, and the distinction is the whole reason that action exists. The intervention is
        # now the right one and the rows pass QC — but each dose is a single seed at a single generation, under
        # both `support.MIN_SEEDS = 2` and `MIN_GENERATIONS = 2`. Reporting the number bare would clear every
        # gate the system has and still be an n=1 claim.
        "action": "qualify",
        "answer_mode": "steady_state",
        "why_not": (),
        "blocking": {},
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "graded_gene_knockout suppresses every transcription unit carrying the cistron, so unlike "
            "gene_knockout it does silence murA",
            "each dose rests on 1 seed x 1 generation, below support.MIN_SEEDS=2 and MIN_GENERATIONS=2",
            "propose additional seeds before any quantitative dose claim",
        ),
        "must_not_say": (
            "a dose-response relationship across 0.1/0.5/0.9 stated as established, from one seed per dose",
            "a comparison against the gene_knockout·KO:murA rows as though they were the same experiment",
        ),
        "check": {"kind": "scope_ko", "gene": "murA", "variant": "graded_gene_knockout", "will_silence": True},
        "measured": {
            "source": "scope.ko_will_silence + data/manifest/*.parquet, 2026-09-08",
            "reportable_rows": 3,
            "expression_levels": (0.1, 0.5, 0.9),
            "seeds_per_level": 1,
            "generations_per_row": 1,
            "min_seeds_floor": 2,
            "min_generations_floor": 2,
        },
        "invariants": ("INV-1", "INV-6"),
        "grounding": (
            "scope.ko_will_silence('murA', 'graded_gene_knockout') -> will_silence True, evidence "
            "'variant_suppresses_all_tus'; measured murA 1403 copies -> 0",
            "capability.py knockout_of_a_multi_transcription_unit_gene.available_in — 'Verified: murA 1789 "
            "copies -> 0 across 2 generations'",
            "BACKLOG (graded_gene_knockout verification) — 'The dose values are 1 seed x 1 generation and do "
            "not clear support.MIN_SEEDS/MIN_GENERATIONS; the ZERO does (0 is 0 at any seed)'",
            "support.MIN_SEEDS == 2, support.MIN_GENERATIONS == 2",
        ),
        "pair": "C2",
        "pair_differs_in": "intervention",
    },

    # ========================================================================================================
    # C3 · THE SEED CASE and its coverage twin. This is the documented instance of a run that looks like clean
    # data and is not, and it is the reason `flag` is in ACTIONS at all.
    #
    # The pair turns on `evidence_coverage` and on nothing else: both members ask whether a knockout lineage
    # that divided repeatedly is a viable knockout, of a design the model really does silence. For KO:rpmE the
    # raw is still on this machine, it was re-read, and the answer is that the cell was translationally dead.
    # For KO:glmS the local raw was deleted to reclaim disk (`data/hf_reclaim_manifest.json`), no shard carries
    # an elongation column, and so the same question cannot be answered the same way — not because the answer
    # is different, but because the channel it would be answered from was never recorded and is now a
    # re-download away. That is `qualify`, and treating it as `flag` OR as `answer` would both be wrong: the
    # first invents a defect, the second reports viability from a divided chromosome all over again.
    #
    # The pair is sharper than it first looks, and the direction is the uncomfortable one. KO:glmS is the
    # CLEANER-LOOKING of the two by every stored signal — 16 of 16 generations divided and scored `ok`, all
    # four rows reportable — while KO:rpmE managed 8 of 15 and was already non-reportable. So the design where
    # nothing can be checked is exactly the design that invites a confident answer, and the design that was
    # checked is the one that turned out to be dead. A benchmark that only tested refusal on questions that
    # LOOK doubtful would never find that.
    #
    # `divided` is `full_chromosome_end == 2 and n_steps > 10` — chromosome count and nothing else. DNA
    # replication proceeds without functioning translation, so a cell whose ribosomes had stopped dead scored
    # divided=True and fell through every remaining generation check to `ok`. `IMPLAUSIBLE_GROWTH` is a
    # CEILING; there was no floor until commit 423a227 added one.
    #
    # A CORRECTION TO HOW THIS CASE IS USUALLY SUMMARISED, made here because the case must assert what is
    # actually true rather than the memorable version. The claim "so it scored qc=ok" is right at the
    # GENERATION level and wrong at the ROW level. Per-generation: 9 of the 15 KO:rpmE generations recorded
    # divided=True and 8 of those recorded generation_qc == 'ok', at exactly 0.0 aa/s. Per row: all four seeds
    # are `reportable=False` and always were — three caught by `over_replicated` and one by
    # `implausible_channel`, neither of which has anything to do with translation. So the exposure this case
    # describes is real and the corpus was not in fact serving these rows as evidence. The scan's own note and
    # BACKLOG's QC-VIA-1 step-1 result both say so: zero currently-reportable rows flip. Writing the case the
    # other way round would have been a case whose key is false, in a benchmark about not asserting things.
    # ========================================================================================================
    {
        "id": "C3.1",
        "theme": "QC · a divided cell that had stopped translating",
        # The phrasing is measured, not rhetorical: 8 of this design's 15 generations both divided and came
        # back `ok`, and they are the first two of every seed. An earlier draft said "divided in every
        # generation", which is false here — the later generations failed on unrelated grounds — and a case
        # whose QUESTION overstates the data is no better than one whose key does.
        "question": "The rpmE knockout divided and passed its per-generation quality checks in the first two "
                    "generations of every seed — is it a viable knockout? (rpmE is ribosomal protein L31)",
        "r": {
            "entity": "a single-gene knockout lineage the model does silence",
            "intervention": "gene_knockout",
            "observable": "viability / division",
            "granularity": "per_generation",
            "regulatory_dependencies": (),
            # <-- the field this pair turns on: this design's raw is still local, so the elongation channel
            # could be recovered by re-opening it.
            "evidence_coverage": "raw still local — every generation re-read for effectiveElongationRate",
        },
        "governed_by": "data_quality",
        "requires": (),
        "mode_constraint": None,
        "represented_in": ("steady_state", "kinetic", "coarse_kinetic"),
        "admissible_modes": (),
        "action": "flag",
        "answer_mode": None,
        "why_not": (),
        "blocking": {},
        "data_defect": {
            "design_key": "gene_knockout/KO:rpmE",
            "qc_verdict": "translation_collapse",
            "defect": "every one of the design's 15 locally-readable generation dirs measured a mean effective "
                      "elongation rate of exactly 0.0 aa/s. The chromosome finished — which is all `divided` "
                      "tests — so 8 of the 15 generations recorded generation_qc == 'ok'. The cell was "
                      "translationally dead throughout.",
            "route": "qc.check_generation now applies TRANSLATION_COLLAPSE_AA_PER_S = 1.0 (commit 423a227), so "
                     "runs produced after it carry the verdict; rows written before it cannot self-correct, "
                     "because no shard carries an elongation column and the raw has to be opened.",
        },
        "storage_gap": None,
        "must_say": (
            "division is not viability here — `divided` is chromosome count and nothing else, and DNA "
            "replication proceeds without functioning translation",
            "the measured elongation rate is 0.0 aa/s in every generation of the design, against a 1.0 aa/s "
            "floor anchored to Dai et al. 2016 (PMID 27941827) and this model's own wild type at 16.72 aa/s",
            "no channel in any shard would have revealed this — the raw had to be re-opened",
        ),
        "must_not_say": (
            "that the rpmE knockout is viable, or that L31 is dispensable, because the lineage divided",
            "that qc='ok' at the row level was the failure — all four rows were already reportable=False, "
            "caught by over_replicated (3) and implausible_channel (1); the near-miss was at generation level",
        ),
        # THE CHECK THAT MATTERS. Every number in `measured` below is recomputed from the scan JSON, so this
        # case cannot drift from the scan it was derived from.
        "check": {"kind": "scan_json", "scan": "data/qc_via_1_scan.json", "design_dir": "gene_knockout_001943",
                  "gene": "rpmE", "ko_index": 1943},
        "measured": {
            "source": "data/qc_via_1_scan.json (scripts/qc_via_1_scan.py, run in the model container)",
            "floor_aa_per_s": 1.0,
            "generation_dirs_read": 286,
            "below_floor": 15,
            "above_floor": 271,
            "unknown": 0,
            "below_floor_designs": ("gene_knockout_001943",),
            "design_generation_dirs": 15,
            "design_dirs_below_floor": 15,
            "design_elongation_mean_aa_per_s": 0.0,
            # From the manifest's per-generation record, not from the scan: how close this came to being read
            # as evidence. 9 generations recorded divided=True; 8 of those recorded generation_qc == 'ok'.
            "generations_divided": 9,
            "generations_recorded_generation_qc_ok": 8,
            "manifest_rows": 4,
            "manifest_rows_reportable": 0,
            "manifest_row_qc": {"over_replicated": 3, "implausible_channel": 1},
            "wildtype_elongation_aa_per_s": 16.72,
        },
        "invariants": ("INV-3", "INV-13"),
        "grounding": (
            "data/qc_via_1_scan.json — floor_aa_per_s 1.0, n_read 286, counts {ok: 271, translation_collapse: "
            "15}; every below-floor row is under cellarium/gene_knockout_001943 at elongation_mean 0.0",
            "scripts/qc_via_1_scan.py module docstring — the floor's provenance: 20-21 aa/s above one "
            "doubling/h (Forchhammer & Lindahl 1971, JMB 55:563), 17 fast / 12 at 0.67 doublings/h (Young & "
            "Bremer 1976, Biochem J 160:185), and decisively Dai et al. 2016 (Nat Microbiol 2:16231, PMID "
            "27941827) — the rate does NOT collapse as growth slows, so 'it was just growing slowly' is not "
            "an available reading of 0.0 aa/s",
            "qc.py TRANSLATION_COLLAPSE_AA_PER_S == 1.0, checked BEFORE the division test in check_generation",
            "BACKLOG QC-VIA-1 step-1 result — 'All 15 are one design, gene_knockout_001943 = KO:rpmE "
            "(ribosomal protein L31) at exactly 0.0 aa/s across four seeds'",
            "data/cache/gene_scope.json — rpmE ko_index 1943, n_tu 1, machinery_role 'ribosomal'; this is what "
            "links the directory name to the gene",
        ),
        "pair": "C3",
        "pair_differs_in": "evidence_coverage",
    },
    {
        "id": "C3.2",
        "theme": "QC · a divided cell that had stopped translating",
        "question": "The glmS knockout divided and passed its per-generation quality checks in every one of "
                    "its sixteen generations — is it a viable knockout? (glmS is "
                    "glutamine-fructose-6-phosphate aminotransferase)",
        "r": {
            "entity": "a single-gene knockout lineage the model does silence",
            "intervention": "gene_knockout",
            "observable": "viability / division",
            "granularity": "per_generation",
            "regulatory_dependencies": (),
            # <-- the only field that moved. The local raw for all four seeds was deleted to reclaim disk and
            # is on HuggingFace; no shard carries an elongation column, so the channel that answered C3.1
            # cannot be reached for this design without a re-download.
            "evidence_coverage": "raw deleted to HF — no elongation channel was ever recorded for these rows",
        },
        "governed_by": "data_quality",
        "requires": (),
        "mode_constraint": None,
        "represented_in": ("steady_state", "kinetic", "coarse_kinetic"),
        "admissible_modes": ("steady_state",),
        # QUALIFY. All 16 generations recorded generation_qc == 'ok' and all four rows are reportable=True, so
        # a system may report what the shard says. What it may not do is repeat C3.1's mistake in the other
        # direction: these rows are `ok` on a test that never looked at translation, and the only channel that
        # would settle it was never recorded. The caveat IS the answer here.
        "action": "qualify",
        "answer_mode": "steady_state",
        "why_not": (),
        "blocking": {},
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "these rows were scored before the 1.0 aa/s translation floor existed, and no shard carries an "
            "elongation column — the check that caught KO:rpmE cannot be run on them",
            "the local raw for all four seeds was deleted to reclaim disk and is on HuggingFace; answering to "
            "the same standard as KO:rpmE requires re-downloading it (data/hf_reclaim_manifest.json carries a "
            "`download` per entry)",
            "absence of the channel is not evidence of viability, and it is not evidence of collapse either — "
            "a row that cannot be re-read must not be relabelled in either direction",
        ),
        "must_not_say": (
            "that this knockout is viable because every generation divided and every generation_qc is 'ok' — "
            "that is the exact reading KO:rpmE falsified, on rows that passed the same tests",
            "that it is translationally dead, or lumping it in with KO:rpmE; nothing was measured either way",
            "a corpus-wide rate of translational collapse computed as if the 137 unread reportable rows had "
            "been measured",
        ),
        "check": {"kind": "scan_coverage", "scan": "data/qc_via_1_scan.json",
                  "design_dir": "gene_knockout_002795", "gene": "glmS", "ko_index": 2795,
                  "expect_in_scan": False, "expect_in_reclaim_manifest": True},
        "measured": {
            "source": "data/manifest/*.parquet, data/qc_via_1_scan.json and data/hf_reclaim_manifest.json "
                      "joined on the normalised run root, 2026-09-08",
            "manifest_rows": 4,
            "manifest_rows_reportable": 4,
            "manifest_row_qc": {"ok": 4},
            "generations_per_row": 4,
            "generations_divided": 16,
            "generations_recorded_generation_qc_ok": 16,
            "generation_dirs_in_the_scan": 0,
            "run_roots_in_the_reclaim_manifest": 4,
            # The corpus-level bound the same scan puts on any answer of this shape, carried here because it
            # is what stops a system generalising from the 103 rows it can see to the 240 it cannot.
            "reportable_rows": 240,
            "reportable_rows_with_local_raw": 103,
            "reportable_rows_unread": 137,
            "reportable_rows_that_flip": 0,
            "scanned_run_roots": 100,
            "reclaimed_run_roots": 60,
        },
        "invariants": ("INV-3", "INV-13"),
        "grounding": (
            "data/hf_reclaim_manifest.json — all four runs/cellarium/gene_knockout_002795/* roots are in "
            "`deleted`; 'Local raw deleted to reclaim disk. Every entry is CONFIRMED present on HF; "
            "`download` restores it. The manifest rows are unaffected — only the local trace is gone'",
            "data/qc_via_1_scan.json note — 'COVERAGE: 103 of the 240 reportable rows have local raw; the "
            "other 137 are on HF or gone and remain unknown, which is not evidence of viability'",
            "BACKLOG QC-VIA-1 step 4 — 'Rows whose raw is gone stay unknown. A row that cannot be re-read "
            "must NOT be silently relabelled in either direction'; the exposure table records 0 shards "
            "carrying an elongation column",
            "data/cache/gene_scope.json — glmS ko_index 2795, n_tu 1, essential_ref True; and "
            "docs/KNOCKOUT_SEMANTICS.md lists glmS among the 10 designs verified `knocked_out`, so this is a "
            "real knockout whose viability reading is the thing in question",
            "INV-13 in data/INVARIANTS.json — RAW-LOCAL != INDEXED != DOWNLOADABLE; unverified is never "
            "'absent'",
        ),
        "pair": "C3",
        "pair_differs_in": "evidence_coverage",
    },

    # ========================================================================================================
    # C4 · The storage-granularity pair. Neither member is a capability question — the model computes the
    # quantity in both, and a run really did produce it. What differs is whether the SHARD kept it at the grain
    # asked for. `_reader_worker._species_panel` is built from `gs[-1]`, the LAST generation only, so the panel
    # holds {mean, last, series} per species with no generation axis at all.
    #
    # This pair exists to keep the benchmark honest about attribution. Both members produce refusal-shaped
    # behaviour, and a benchmark that filed C4.2 under one of `capability.check()`'s tokens would be crediting
    # the capability registry with a refusal it plays no part in — which is exactly the over-claim the arms in
    # CAPBENCH-2 are designed to detect. `governed_by` and the separate WHY_NOT_CORPUS token are the guards.
    # ========================================================================================================
    {
        "id": "C4.1",
        "theme": "corpus storage · granularity",
        "question": "How many copies of ribosomal protein L31 does a wild-type cell end up with?",
        "r": {
            "entity": "L31 monomer (EG10889-MONOMER[c], the rpmE product)",
            "intervention": "none (wildtype, basal medium)",
            "observable": "monomer count",
            "granularity": "terminal_generation",
            "regulatory_dependencies": (),
            "evidence_coverage": "the 199-species curated panel, stored per row for reportable runs",
        },
        "governed_by": "corpus_storage",
        "requires": (),
        # Every elongation model produces MonomerCounts — translation writes them whatever solves charging —
        # so nothing about this question is a capability gap in ANY mode. That is the whole point of the pair:
        # the obstruction in C4.2 arrives after the model has already computed the number.
        "mode_constraint": None,
        "represented_in": ("steady_state", "kinetic", "coarse_kinetic"),
        "admissible_modes": ("steady_state", "kinetic"),
        "action": "answer",
        "answer_mode": "steady_state",
        "why_not": (),
        "blocking": {},
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "the stored value is the LAST generation's — mean over its timesteps, plus a terminal count",
            "it comes from the curated 199-species panel, not from a raw read",
        ),
        "must_not_say": (
            "that the stored number is an average over the lineage's generations — a channel is the last "
            "generation's time-mean, and depth selects which generation you read",
        ),
        "check": {"kind": "species_panel", "monomer": "EG10889-MONOMER[c]", "expect_present": True},
        "measured": {
            "source": "data/manifest/*.parquet species_panel column, 2026-09-08",
            "panel_species": 199,
            "reportable_rows_with_a_panel": {"steady_state": 206, "kinetic": 8},
            "panel_entry_keys": ("mean", "last", "series"),
        },
        "invariants": ("INV-5", "INV-15"),
        "grounding": (
            "_reader_worker.py _species_panel — 'per-SPECIES (monomer) mean, terminal count, and a coarse k=16 "
            "trajectory for the curated panel proteins ... batched over the panel from the LAST generation'",
            "data/cache/gene_scope.json — rpmE monomer_id EG10889-MONOMER[c]",
            "docs/DECISIONS.md D7 point 3 — 'The fast layer holds a CURATED species panel per (gen, seed)'",
        ),
        "pair": "C4",
        "pair_differs_in": "granularity",
    },
    {
        "id": "C4.2",
        "theme": "corpus storage · granularity",
        "question": "How many copies of L31 did that wild-type cell have at its second division?",
        "r": {
            "entity": "L31 monomer (EG10889-MONOMER[c], the rpmE product)",
            "intervention": "none (wildtype, basal medium)",
            "observable": "monomer count",
            "granularity": "named_intermediate_generation",   # <-- the only field that moved
            "regulatory_dependencies": (),
            "evidence_coverage": "the 199-species curated panel, stored per row for reportable runs",
        },
        "governed_by": "corpus_storage",
        "requires": (),
        "mode_constraint": None,
        "represented_in": ("steady_state", "kinetic", "coarse_kinetic"),
        "admissible_modes": (),
        # PROPOSE rather than refuse. The model computed this number and a run really did produce it; the raw
        # simOut for a locally-held run still contains it. What is missing is a stored path to it, and D7's
        # action item WELL-1x is the per-generation panel expansion that would provide one. Refusing outright
        # would be a stronger statement than the evidence supports.
        "action": "propose",
        "answer_mode": None,
        "why_not": ("not_stored_at_this_granularity",),
        "blocking": {},
        "data_defect": None,
        "storage_gap": {
            "artifact": "species_panel",
            "stored_grain": "last generation only",
            "requested_grain": "a named intermediate generation",
            "route": "a raw simOut drill-down for runs whose raw is still local, or the per-generation panel "
                     "expansion (BACKLOG WELL-1x); neither is a query against the shard as it stands",
        },
        "must_say": (
            "the shard stores the panel for the terminal generation only — there is no generation axis in it",
            "answering needs either a raw read of that run or the per-generation panel expansion",
        ),
        "must_not_say": (
            "the terminal-generation number reported as though it were generation 2's",
            "that the model cannot represent per-generation species counts — it computes them every timestep; "
            "this is a storage gap, not a capability gap",
        ),
        "check": {"kind": "species_panel", "monomer": "EG10889-MONOMER[c]", "expect_generation_axis": False},
        "measured": {
            "source": "_reader_worker.py and the manifest's species_panel column, 2026-09-08",
            "panel_entry_keys": ("mean", "last", "series"),
            "generation_keyed_entries": 0,
        },
        "invariants": ("INV-5", "INV-15"),
        "grounding": (
            "_reader_worker.py:237 — species_panel is built from gs[-1]",
            "docs/DECISIONS.md D7 point 3 — 'The 199-species panel is last-generation only today; "
            "generation-resolved species retrieval requires either raw simOut or a per-generation panel "
            "expansion (WELL-1x). Tool output must state this boundary, or Cellwright will answer \"species X "
            "at generation 3\" from data the manifest never stored'",
            "BACKLOG invariant 5 — a channel is the LAST generation's time-mean; growth_rate == "
            "per_generation[-1] on 91/91 rows and == the mean over generations on 0/91",
        ),
        "pair": "C4",
        "pair_differs_in": "granularity",
    },

    # ========================================================================================================
    # C5 · The rRNA operon singleton — a refusal the corpus actively argues against. Seventeen rows carry
    # design keys of the form `rrna_operon_knockout/minimal|rRNA_KO:4op`, so a system that looks for evidence
    # will find rows whose very NAME says they answer this question. They do not: the variant zeroes n rRNA
    # rows and `synth_prob_from_ppgpp(balanced_rRNA_prob=True)` then reassigns prob[is_rRNA] to the mean over
    # all seven rows INCLUDING the zeroed ones, so no row ends at zero. The dose survives; operon identity does
    # not. `holds_in=()` — no elongation model can restore it, because the erasure happens in transcript
    # initiation, upstream of elongation entirely.
    # ========================================================================================================
    {
        "id": "C5.1",
        "theme": "rRNA operons · representation",
        "question": "Which of the seven rRNA operons hurts the cell most when you delete it?",
        "r": {
            "entity": "an individual rRNA operon (rrnA..rrnH)",
            "intervention": "operon deletion",
            "observable": "growth rate relative to wild type",
            "granularity": "individual_operon",
            "regulatory_dependencies": ("ppGpp-dependent rRNA synthesis probability",),
            "evidence_coverage": "17 rrna_operon_knockout rows at three doses (2op/4op/6op)",
        },
        "governed_by": "capability_registry",
        "requires": ("operon_specific_rrna_knockout",),
        "mode_constraint": None,
        "represented_in": (),
        "admissible_modes": (),
        "action": "refuse",
        "answer_mode": None,
        "why_not": ("no_elongation_model_represents_it",),
        "blocking": {
            "steady_state": {"operon_specific_rrna_knockout": "no_elongation_model_represents_it"},
            "kinetic": {"operon_specific_rrna_knockout": "no_elongation_model_represents_it"},
            "coarse_kinetic": {"operon_specific_rrna_knockout": "no_elongation_model_represents_it"},
        },
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "the rRNA rebalance erases operon identity before elongation is reached, so no elongation model "
            "can restore it",
            "the existing rrna_operon_knockout designs are graded reductions of TOTAL rRNA capacity, not "
            "operon-deletion strains — the dose survives, the identity does not",
        ),
        "must_not_say": (
            "a per-operon ranking, or any statement that one named operon matters more than another",
            "that the rRNA_KO:2op/4op/6op rows are deletions of specific operons because their labels say so",
        ),
        "check": {"kind": "manifest_design", "design_key_prefix": "rrna_operon_knockout/",
                  "min_designs": 1, "must_exist": True},
        "measured": {
            "source": "data/manifest/*.parquet via store.list_results + survey.design_key, 2026-09-08",
            "design_keys": ("rrna_operon_knockout/minimal|rRNA_KO:2op",
                            "rrna_operon_knockout/minimal|rRNA_KO:4op",
                            "rrna_operon_knockout/minimal|rRNA_KO:6op"),
            "rows": 17,
            "total_rrna_probability_by_dose_pct": (100.0, 73.8, 45.9, 15.8),
        },
        "invariants": ("INV-10",),
        "grounding": (
            "capability.py operon_specific_rrna_knockout — present=False, holds_in=(); 'the variant zeroes n "
            "rRNA rows, then synth_prob_from_ppgpp(balanced_rRNA_prob=True) reassigns prob[is_rRNA] to the "
            "MEAN over all seven rows including the zeroed ones'; consequence: 'the DOSE survives (total rRNA "
            "probability 100/73.8/45.9/15.8%) but operon IDENTITY does not'",
            "docs/KNOCKOUT_SEMANTICS.md",
        ),
        "pair": None,
        "pair_differs_in": None,
    },

    # ========================================================================================================
    # C6 · The empty-mode singleton — the only clean instance of `no_run_used_this_mode` this corpus affords,
    # and the one case here whose question a modeller asks rather than a biologist. That is not a defect in the
    # case, it is a property of the token: `no_run_used_this_mode` fires when the code supports a mode and no
    # run has used it, and the only such mode is coarse_kinetic, which exists to cap elongation by synthetase
    # k_cat without solving charging at all. A question that lands there necessarily names the elongation model.
    #
    # Written as the model-artifact question a reviewer actually asks — "is this phenotype a property of the
    # cell or of the elongation solver you chose?" — because that is the honest form and it is a question the
    # corpus genuinely cannot answer: 0 of 369 rows are coarse_kinetic.
    # ========================================================================================================
    {
        "id": "C6.1",
        "theme": "elongation model · corpus coverage",
        "question": "Is the growth collapse you see after an amino-acid downshift a property of the cell, or "
                    "an artifact of the elongation solver these runs happened to use?",
        "r": {
            "entity": "the coarse-kinetic elongation model's downshift response",
            "intervention": "amino-acid downshift timeline (minimal_plus_amino_acids -> minimal)",
            "observable": "growth rate across the shift",
            "granularity": "whole_cell",
            "regulatory_dependencies": ("amino-acid supply",),
            "evidence_coverage": "0 of 369 corpus rows were produced by the coarse-kinetic model",
        },
        "governed_by": "capability_registry",
        "requires": ("nutrient_shift_timelines",),
        # The question NAMES the mode — it is asking about that model's behaviour, not about the cell's. This
        # field is what stops the derivation reading the case as answerable: nutrient_shift_timelines is
        # represented under all three models and answerable under the two the corpus contains, so without the
        # constraint the derived label would be `answer` and would be answering a different question.
        "mode_constraint": ("coarse_kinetic",),
        "represented_in": ("coarse_kinetic",),
        "admissible_modes": (),
        "action": "propose",
        "answer_mode": None,
        "why_not": ("no_run_used_this_mode",),
        "blocking": {"coarse_kinetic": {"nutrient_shift_timelines": "no_run_used_this_mode"}},
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "the timeline machinery works under every elongation model, but no run in the corpus used the "
            "coarse-kinetic one — this is a campaign to propose, not a query to re-issue",
            "such a campaign runs against the same fitted knowledge base (the elongation model is a runSim "
            "flag, not a refit, so kb_sha256 is unchanged) and its rows still must not be pooled with the "
            "corpus — separate them on elongation_model, not on the KB hash",
        ),
        "must_not_say": (
            "an answer drawn from the steady_state rows presented as settling the artifact question — those "
            "rows are the thing being questioned",
            "that the coarse-kinetic model is unavailable or unported; it is in the checkout and off by "
            "default",
        ),
        "check": {"kind": "manifest_column", "column": "elongation_model", "elongation_model":
                  "coarse_kinetic", "reportable": False, "min_rows": 0, "expect_zero": True},
        "measured": {
            "source": "data/manifest/*.parquet via manifest.DEDUP_QUALIFY, 2026-09-08",
            "rows_by_elongation_model": {"steady_state": 355, "kinetic": 14, "coarse_kinetic": 0},
            "modes_in_corpus": ("steady_state", "kinetic"),
        },
        "invariants": ("INV-2",),
        "grounding": (
            "capability.py MODES_IN_CORPUS == ('steady_state', 'kinetic'); check('nutrient_shift_timelines', "
            "'coarse_kinetic')['why_not'] == 'no_run_used_this_mode'",
            "capability.py MODE_FLAGS['coarse_kinetic'] == '--coarse-kinetic-elongation'",
            "capability.py refusal() case (c) — 'Such a campaign runs against the SAME fitted knowledge base "
            "... but its rows still must not be pooled with the corpus'; MEASURED 2026-08-06, two roots hash "
            "identically on 90,404,578 bytes",
            "main.tex sec:kinetic — 'Coarse kinetic caps elongation by synthetase k_cat without solving "
            "charging at all, writing 86 zeros that the registry refuses as absence'",
        ),
        "pair": None,
        "pair_differs_in": None,
    },
]


# ------------------------------------------------------------------------------------------------------------
# The honest balance record. `CAPBENCH-1` asks for ~half answerable, the three registry `why_not` tokens spread
# across the unanswerable half, and modes balanced. This corpus does not meet that and this constant says so in
# a form a test can check, rather than leaving the docstring's admission to rot next to a corpus that grew.
#
# Read `answer` as "a number, no caveat required" and `qualify` as "a number, but the caveat is the answer".
# Together they are 4 of 10, so over-refusal is measurable; but only 2 are unqualified, well under the ~half
# the spec asks for. That is a consequence of grounding every case: the corpus's unqualified answers are its
# least interesting rows, and there was no reason to write more of them than the pairs needed.
# ------------------------------------------------------------------------------------------------------------
BALANCE = {
    "n_cases": 10,
    "by_action": {"answer": 2, "qualify": 2, "refuse": 2, "propose": 2, "flag": 2},
    "by_governor": {"capability_registry": 4, "corpus_storage": 2, "data_quality": 4},
    "registry_why_not_covered": ("no_elongation_model_represents_it", "another_mode_represents_it",
                                 "no_run_used_this_mode"),
    "n_pairs": 4,
    "pair_fields_exercised": ("granularity", "intervention", "evidence_coverage"),
    "target_from_backlog": "40-60 cases, ~half answerable, why_not tokens balanced — NOT met, see the module "
                           "docstring",
}


def by_id(ids: list[str] | None) -> list[dict]:
    """Select cases by id, or all of them. Same signature and semantics as `cases.by_id`, so a runner can take
    either corpus without special-casing which one it was handed."""
    if not ids:
        return CASES
    keep = set(ids)
    return [c for c in CASES if c["id"] in keep]


def pairs() -> dict[str, list[dict]]:
    """The near-neighbour pairs, grouped by `pair`. Singletons are excluded, not returned as one-member groups.

    Exists because the pairs are the measurement and every consumer needs them together: scoring a pair is a
    JOINT question (did the system split them?), not two independent ones, and a runner that shuffled the case
    list would otherwise have to reconstruct the grouping from ids."""
    out: dict[str, list[dict]] = {}
    for c in CASES:
        if c["pair"]:
            out.setdefault(c["pair"], []).append(c)
    return {k: v for k, v in out.items() if len(v) > 1}
