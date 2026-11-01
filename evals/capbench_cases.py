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
which fixes the repetition count N, is blocked on ~12 labelled cases — a threshold the second pass cleared,
with 22 here; CAPBENCH-2's seven arms have nothing to be run against. This file is the gating artifact.

WHAT THE BINDING CONSTRAINT ACTUALLY IS, stated plainly because this docstring got it wrong once and the
error is the kind that sends somebody down a dead end. It is NOT that the work is "authoring rather than
compute": no case here launches a simulation, true, but a case can only be written where a GROUNDED
MEASUREMENT already exists to key it against, and that is the scarce thing. The twelve cases of the second
pass exist because two validation campaigns had already been run and analysed
(`evals/results/phosphate_validation.json`, `evals/results/known_faults_validation.json`) and three registry
entries had been written from them. Typing was never the limit; past the measurements in this repository the
next cases need machine time, and writing them without it would mean asserting keys — the thing this
benchmark exists to make impossible.

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
    verdict (`translation_collapse`, `noop_knockout`, `empty`, `no_division`), not a capability. These are the
    "looks like clean data and is not" cases, and they are the ones no amount of documentation retrieval can
    reach. Two of them (C9.1, C10.1) flag a run in a validation artifact rather than a corpus design, so
    `data_defect` names its locus explicitly — see `VALIDATION_ARTIFACTS` below for why that distinction has
    to be in the schema and not inferred.

NEAR-NEIGHBOUR PAIRS ARE WHERE THE POWER IS. Four of the six groups here are pairs differing in EXACTLY ONE
field of `r`, where the correct action flips. A system doing keyword matching sees the same nouns in both
members and responds identically; only a system that reads the changed field and checks it against what the
model computes splits them. The pairs and the field each turns on:

    C1  granularity           amino-acid family -> individual isoacceptor        answer  -> refuse
    C2  intervention          gene_knockout -> graded_gene_knockout              flag    -> qualify
    C3  evidence_coverage     raw still local -> raw deleted to HF               flag    -> qualify
    C4  granularity           terminal generation -> a named intermediate one    answer  -> propose
    C7  intervention          phosphate removed -> amino acids removed           refuse  -> answer
    C8  observable            the dose response -> are the arms distinct cells?  refuse  -> answer
    C9  intervention          cytR held inactive -> cytR held active             flag    -> qualify
    C10 entity                a leucine auxotroph -> the wild type               flag    -> answer
    C12 observable            growth without carbon -> carbon uptake             refuse  -> answer

C8 AND C12 RUN THE SAME WAY ROUND AND IT IS WORTH SAYING WHY. In both, the biological question is refused and
an AUDIT question on the very same rows is answerable — and reading the audit answer is how the refusal gets
justified rather than merely declared. "Is there a glucose dose response?" cannot be answered; "are these
three dose arms three different cells?" can, and the answer (no — nine rows, three distinct channel vectors)
is what makes the first unanswerable. A system that refuses both looks careful and has thrown away the only
check that would have caught a curve fitted across the nine rows. The pairs are therefore not "a hard case
and an easy one"; the easy member is the instrument.

The C3 pair is worth reading twice, because it is the one where the correct behaviour is least intuitive. Both
members ask the same question of the same kind of design; in one the raw was re-read and the cell turns out to
have been translationally dead, in the other the raw is gone and the question simply cannot be settled. The
tempting error is symmetry — either to answer "viable" for the second because its rows are clean, or to call it
collapsed by association with the first. Both are the same mistake, which is treating an unmeasured channel as
a measurement of something.

HONEST STATEMENT OF WHAT THIS IS NOT. `CAPBENCH-1` targets 40-60 cases; there are TWENTY-TWO. That is not a
partial delivery of the same thing — it is a different thing, and saying so matters more than the count. Every
case below is tied to a measurement already in this repository, and each records where its ground truth came
from in `grounding` so a reader can go check it. Cases that would need a new measurement, or that could only be
argued from plausibility, were not written. The balance requirements in `CAPBENCH-1` (~half answerable, the
three `why_not` tokens spread evenly, modes balanced) are still NOT met — `BALANCE` below records the real
distribution rather than claiming the target one — though the answerable side moved from 4 of 10 to 9 of 22.
Reaching 40-60 means either running measurements that do not exist yet or writing cases whose keys are
asserted, and the second is the thing this benchmark exists to make impossible.

WHAT WRITING THE SECOND PASS FOUND, since a case corpus that only restates what was already believed is not
worth the trouble. Recomputing the glucose-dose identity for C8 corrected the capability registry's own prose
twice, and then corrected the correction: it said "the six dose-to-dose pairs available" where NINE are
available (all nine identical, so the conclusion is stronger), and said `basal` differs from each dose "on all
eleven channels" where it differs on AT LEAST TEN — no basal row agrees on more than one, and the only channel
that ever agrees is the saturating `division_rate`, on 10 of the 13 reportable basal rows at those seeds; the
other three are single-generation runs where it is NULL, and a null is not an agreement. The first attempt at
that correction said flatly "ten", read off a print that showed only the rows WITH an agreement, and the check
written for it failed on the NULL rows at once — a filtered print is as bad as a truncated tail. Both of the
registry's sentences had been restated in a test docstring and recomputed by nothing. C11's arithmetic
likewise puts the E4 stop times at 1,433-2,448 s where its own source readout says 1,410-2,448.

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
QC_VERDICTS = ("translation_collapse", "noop_knockout", "empty", "no_division")

# WHERE A FLAGGED ROW LIVES. `data_defect` names its locus, and after C9/C10 there are two kinds: a corpus
# design (`design_key`) and a run in one of the validation artifacts (`validation_file` + `run_key`). Both
# keys are present on every defect with the unused one set to None, so the shape is uniform and the test can
# require exactly one locus rather than guessing from which keys happen to be there. The distinction is not
# cosmetic: a corpus design is in the shipped shards and a reader can query it, while a validation run lives
# in `evals/results/` and `runs_validation*/` and was DELIBERATELY never appended to the manifest (see each
# script's docstring) — so a case flagging one must not be checked against the corpus and silently pass for
# want of a row to contradict it.
VALIDATION_ARTIFACTS = ("phosphate_validation.json", "known_faults_validation.json")

# What the `check` box's `kind` may be. The test module implements one runner per kind and asserts the two sets
# are equal, so a case cannot ship a check nothing executes — which would be an assertion wearing a check's
# clothes, the precise failure §6's "executable where possible" exists to prevent.
CHECK_KINDS = ("registry", "manifest_column", "manifest_design", "scan_json", "scope_ko", "species_panel",
               "scan_coverage", "condition_rows", "dose_identity", "validation_run", "validation_arm",
               "validation_exchange")


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
            "validation_file": None,
            "run_key": None,
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
            "validation_file": None,
            "run_key": None,
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

    # ========================================================================================================
    # C7 · Losing a nutrient — phosphate against amino acids. The pair turns on `intervention` and on nothing
    # else: same cell, same observable, same granularity, and the same regulatory ROLE ("whatever the cell
    # senses the missing nutrient with") rather than a named regulator, because naming PhoB in one member and
    # ppGpp in the other would move a second field and the flip would stop being attributable to either.
    #
    # `evidence_coverage` is likewise IDENTICAL and phrased as a REQUIREMENT, for the reason C2 gives: how
    # many rows each member actually has is a measured fact about the corpus and belongs in `measured`. Here
    # the two could not be further apart — the amino-acid downshift has 4 reportable rows carrying
    # growth_rate, the phosphate design has 4 rows that are all `qc='crashed'` with 0 generations — and that
    # asymmetry is the answer, not the question.
    #
    # WHAT MAKES C7.1 HARD is that the corpus argues for answering it. `condition/minus_phosphate` is a real
    # design with four real rows, and a system that looks for evidence by name finds them. They carry no
    # growth rate at all; and the ten validation runs that DO have phosphate removed stop with ATP exhausted
    # in PolypeptideElongation while ~340,000 free phosphate ions sit in the cytoplasm, which is a model
    # artifact and not a death.
    # ========================================================================================================
    {
        "id": "C7.1",
        "theme": "nutrient removal · phosphate",
        "question": "I take phosphate out of the medium. Does the cell notice and slow down?",
        "r": {
            "entity": "a wild-type cell growing in minimal medium",
            "intervention": "phosphate removed from the medium",       # <-- the field this pair turns on
            "observable": "growth rate across the removal",
            "granularity": "whole_cell",
            "regulatory_dependencies": ("whatever regulator the cell senses the missing nutrient with",),
            "evidence_coverage": "reportable steady_state rows of the removal design carrying growth_rate",
        },
        "governed_by": "capability_registry",
        "requires": ("growth_under_phosphate_depletion",),
        "mode_constraint": None,
        "represented_in": (),
        "admissible_modes": (),
        "action": "refuse",
        "answer_mode": None,
        "why_not": ("no_elongation_model_represents_it",),
        "blocking": {
            "steady_state": {"growth_under_phosphate_depletion": "no_elongation_model_represents_it"},
            "kinetic": {"growth_under_phosphate_depletion": "no_elongation_model_represents_it"},
            "coarse_kinetic": {"growth_under_phosphate_depletion": "no_elongation_model_represents_it"},
        },
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "removing phosphate removes phosphate UPTAKE from the metabolic network and nothing else — the "
            "cytoplasmic and periplasmic pools stay where they were, PhoB is never phosphorylated, and PhoB "
            "is not among the fitted transcription factors, so the Pho regulon is not regulated at all",
            "the runs stop with ATP exhausted in PolypeptideElongation a few minutes after the removal, and "
            "that stop is not a prediction that the cell dies — a real cell survives phosphate starvation",
            "the four condition/minus_phosphate rows in the corpus carry no growth rate: they are crash rows "
            "with zero generations, so finding the design by name is not finding evidence",
        ),
        "must_not_say": (
            "a growth rate, survival time or death time read from any run after phosphate became unavailable",
            "that the flat phosphate pool is the cell holding its reserves — the pool is flat because nothing "
            "consumes or senses it on this path, which is the absence of the mechanism, not its result",
            "that the kinetic runs are the control for this: they stop the same way, about 9 min in instead "
            "of about 5, which locates the stop in metabolism rather than in the elongation solver",
        ),
        "check": {"kind": "condition_rows", "perturbation": "condition", "condition": "minus_phosphate",
                  "elongation_model": "steady_state", "column": "growth_rate", "n_rows": 4,
                  "qc_values": ("crashed",)},
        "measured": {
            "source": "data/manifest/*.parquet via manifest.DEDUP_QUALIFY + evals/results/"
                      "phosphate_validation.json, both recomputed 2026-11-01",
            "corpus_minus_phosphate_rows": 4,
            "corpus_minus_phosphate_reportable": 0,
            "corpus_minus_phosphate_qc": ("crashed",),
            "validation_runs": 13,
            "validation_runs_stopping_with_negative_counts": {"A_absent_from_start": 4,
                                                              "B_removed_at_2400s": 4, "K_absent_kinetic": 2},
            "validation_null_arms_completing": {"C_null_wildtype_minimal": 2, "KC_null_wildtype_kinetic": 1},
            "pi_cytoplasm_removed_vs_control_at_2529s": (673058, 682370),
            "atp_removed_vs_control_at_2529s": (7300683, 13142452),
        },
        "invariants": ("INV-3", "INV-10"),
        "grounding": (
            "capability.py growth_under_phosphate_depletion — present=False, holds_in=(); instead: 'the "
            "cytoplasmic (~340,000) and periplasmic (~68,000) phosphate pools stay at their pre-removal "
            "levels, so PhoR-PhoB is never activated (PHOSPHO-PHOB stays at 0)'",
            "evals/results/phosphate_validation.json — 10 of 13 runs end "
            "NegativeCountsError@wholecell/states/bulk_molecules.py:merge, every one of them an arm with "
            "phosphate absent or removed; all 3 null-arm runs end no_traceback",
            "the same file's molecular_readout_seed0: 'Why ATP is not regenerated while ~340,000 free "
            "phosphate ions remain in the cytoplasm is not diagnosed' — the stop has no mechanism attached",
            "scripts/validate_phosphate.py docstring — the validation runs go to runs_validation*/ and are "
            "never appended to the manifest, so the 4 crash rows are still the corpus's only phosphate rows",
        ),
        "pair": "C7",
        "pair_differs_in": "intervention",
    },
    {
        "id": "C7.2",
        "theme": "nutrient removal · amino acids",
        "question": "I take the amino acids out of the medium. Does the cell notice and slow down?",
        "r": {
            "entity": "a wild-type cell growing in minimal medium",
            "intervention": "the medium's amino acids removed",        # <-- the only field that moved
            "observable": "growth rate across the removal",
            "granularity": "whole_cell",
            "regulatory_dependencies": ("whatever regulator the cell senses the missing nutrient with",),
            "evidence_coverage": "reportable steady_state rows of the removal design carrying growth_rate",
        },
        "governed_by": "capability_registry",
        # The conjunction again, and it is what makes the flip informative rather than lucky: the downshift
        # needs the timeline machinery AND the regulator the downshift acts through. Both hold under
        # steady_state; coarse_kinetic fails BOTH, and for two different reasons — one for want of a run, one
        # because ppGpp lives in another mode — so the blocking table below is the one place the two kinds of
        # obstruction are visible side by side as different things.
        "requires": ("nutrient_shift_timelines", "ppgpp_stringent_response"),
        "mode_constraint": None,
        "represented_in": ("steady_state",),
        "admissible_modes": ("steady_state",),
        "action": "answer",
        "answer_mode": "steady_state",
        "why_not": (),
        "blocking": {
            "kinetic": {"ppgpp_stringent_response": "another_mode_represents_it"},
            "coarse_kinetic": {"nutrient_shift_timelines": "no_run_used_this_mode",
                               "ppgpp_stringent_response": "another_mode_represents_it"},
        },
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "the number comes from the steady_state downshift rows (timeline/0 minimal_plus_amino_acids, "
            "1200 minimal), the only mode that runs the timeline AND solves ppGpp",
            "there are four seeds and the spread across them is the error bar — a single seed is not an "
            "answer",
        ),
        "must_not_say": (
            "a comparison with the phosphate arm presented as the same kind of measurement (C7.1): one has a "
            "regulator in the model and the other does not",
            "a downshift claim drawn from the kinetic rows — nothing synthesises or degrades ppGpp there, so "
            "the regulator the downshift acts through is absent, not quiet",
        ),
        "check": {"kind": "condition_rows", "perturbation": "timeline",
                  "condition": "shift:down:minimal_plus_amino_acids->minimal",
                  "elongation_model": "steady_state", "column": "growth_rate", "n_rows": 4,
                  "qc_values": ("ok",)},
        "measured": {
            "source": "data/manifest/*.parquet via manifest.DEDUP_QUALIFY, recomputed 2026-11-01",
            "corpus_downshift_rows": 4,
            "corpus_downshift_reportable_with_growth_rate": 4,
            "growth_rate_per_seed": (0.00033651239649904043, 0.0003421826792462436, 0.0003099227685675741,
                                     0.0003390578946134909),
            "upshift_rows_for_contrast": 3,
        },
        "invariants": ("INV-2", "INV-3"),
        "grounding": (
            "capability.py nutrient_shift_timelines.holds_in == all three modes and "
            "ppgpp_stringent_response.holds_in == ('steady_state',) — the intersection is steady_state",
            "data/manifest/*.parquet: perturbation='timeline', "
            "condition='shift:down:minimal_plus_amino_acids->minimal' — 4 rows, all qc='ok', all reportable, "
            "all carrying growth_rate, ppgpp_conc and fraction_trna_charged",
            "capability.py MODES_IN_CORPUS == ('steady_state', 'kinetic') — hence coarse_kinetic's second "
            "obstruction is no_run_used_this_mode, a different thing from the mode gap beside it",
        ),
        "pair": "C7",
        "pair_differs_in": "intervention",
    },

    # ========================================================================================================
    # C8 · The glucose dose — a design that runs and answers nothing. Uptake is gated by a binary switch at
    # IMPORT_CONSTRAINT_THRESHOLD = 1e-5 mM, above which the concentration is never read again, so every dose
    # above that threshold gives the same cell. The corpus has nine rows that say so out loud: three doses
    # (2, 5, 20 mM) at three seeds, and all nine within-seed arm pairs are identical on all ELEVEN declared
    # channels (`survey.CHANNELS`) — nine rows holding three distinct channel vectors, one per seed.
    #
    # The pair turns on `observable`, and the second member is the one worth reading. "Is there a dose
    # response?" cannot be answered. "Are these three arms three different cells?" can, from exactly the same
    # nine rows — and answering it is HOW you find out the first is unanswerable. A system that refuses both
    # has not been careful; it has thrown away the only check that would have caught the fitted curve.
    #
    # WRITING THE CHECK CORRECTED THE REGISTRY'S OWN PROSE, twice — and then corrected the correction. The
    # entry said "the six dose-to-dose pairs available" where nine are available (all nine identical, so the
    # conclusion is stronger, not weaker), and said `basal` "differs from each dose on all eleven channels".
    # It differs on AT LEAST TEN: no basal row agrees with a dose row on more than ONE channel, and the only
    # one that ever agrees is `division_rate`, a saturating fraction (divided generations over total) that
    # cannot separate two healthy conditions at all (INV-15). Of the 13 reportable basal rows at the dose
    # seeds, 10 agree on it and 3 agree on nothing — the three are single-generation runs where it is NULL,
    # and a null is not an agreement (INV-4). The first attempt at this correction said flatly "it differs
    # on ten", read off a print that showed only the rows WITH an agreement; the check failed on the NULL
    # rows immediately. Both of the registry's sentences had been restated in a test docstring and
    # recomputed by nothing until this case.
    # ========================================================================================================
    {
        "id": "C8.1",
        "theme": "glucose dose · representation",
        "question": "Does the cell grow more slowly on 2 mM glucose than on 20 mM?",
        "r": {
            "entity": "a wild-type cell in glucose minimal medium",
            "intervention": "glucose supplied at 2, 5 or 20 mM",
            "observable": "how growth rate depends on the glucose concentration",
            "granularity": "whole_cell",
            "regulatory_dependencies": (),
            "evidence_coverage": "the nine condition/glc_* rows — three doses at three seeds — on the eleven "
                                 "channels survey.CHANNELS declares",
        },
        "governed_by": "capability_registry",
        "requires": ("response_to_the_glucose_concentration",),
        "mode_constraint": None,
        "represented_in": (),
        "admissible_modes": (),
        "action": "refuse",
        "answer_mode": None,
        "why_not": ("no_elongation_model_represents_it",),
        "blocking": {
            "steady_state": {"response_to_the_glucose_concentration": "no_elongation_model_represents_it"},
            "kinetic": {"response_to_the_glucose_concentration": "no_elongation_model_represents_it"},
            "coarse_kinetic": {"response_to_the_glucose_concentration": "no_elongation_model_represents_it"},
        },
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "uptake is a binary switch at 1e-5 mM: above it the concentration is read once to decide "
            "present-or-absent and never again, so no elongation model can make a dose matter",
            "the dose arms RUN and produce clean rows — refusing is not a statement that the runs failed",
            "a difference between two dose arms is a difference between two seeds, so a dose-response curve "
            "fitted to them describes the sampler",
        ),
        "must_not_say": (
            "any slope, EC50, or monotone trend across 2/5/20 mM",
            "that the doses agree because the effect is small — they agree to every recorded digit, which is "
            "identity, not a weak effect",
            "that glucose REMOVAL is settled by the same refusal; it is a separate question with its own "
            "entry, also refused (C12.1)",
        ),
        "check": {"kind": "dose_identity", "conditions": ("glc_2mM", "glc_5mM", "glc_20mM"),
                  "n_rows": 9, "n_seeds": 3, "n_distinct_channel_vectors": 3},
        "measured": {
            "source": "data/manifest/*.parquet via manifest.DEDUP_QUALIFY over survey.CHANNELS, recomputed "
                      "2026-11-01",
            "n_declared_channels": 11,
            "rows": 9,
            "within_seed_arm_pairs_identical_on_all_channels": (9, 9),
            "distinct_channel_vectors_across_the_nine_rows": 3,
            # `basal` is NOT the dose medium with a different number in it, and this is the measurement
            # that says so. No basal row agrees with a dose row on more than ONE of the eleven channels;
            # the only one that ever agrees is `division_rate`, which saturates at 1.0 for any fully
            # dividing run; and the three rows agreeing on NOTHING are single-generation runs where it is
            # NULL, because a null compared with 1.0 is not an agreement (INV-4).
            "basal_vs_a_dose_row": {
                "basal_rows_compared": 13,
                "max_channels_agreeing": 1,
                "channels_that_ever_agree": ("division_rate",),
                "tally": ((("division_rate",), 10), ((), 3)),
                "why_the_three": "division_rate is NULL on a single-generation run",
            },
            "registry_prose_before_this_case": "six of six pairs; basal differs on all eleven channels",
        },
        "invariants": ("INV-1", "INV-9", "INV-15"),
        "grounding": (
            "capability.py response_to_the_glucose_concentration — present=False, holds_in=(); instead: "
            "'every glucose concentration above 1e-5 mM gives the SAME cell: uptake is a binary switch "
            "(IMPORT_CONSTRAINT_THRESHOLD, external_state.py)'",
            "data/manifest/*.parquet — 9 rows across condition IN (glc_2mM, glc_5mM, glc_20mM), 3 seeds, all "
            "qc='ok' and reportable; 9 of 9 within-seed pairs identical on all 11 of survey.CHANNELS",
            "provenance.IN_SAMPLE_CONDITIONS contains all three doses — they are in-sample, so even a real "
            "difference between them would not be an out-of-sample prediction (INV-9)",
        ),
        "pair": "C8",
        "pair_differs_in": "observable",
    },
    {
        "id": "C8.2",
        "theme": "glucose dose · independence",
        "question": "Before I fit a dose-response curve to these three glucose arms: are they actually three "
                    "different cells?",
        "r": {
            "entity": "a wild-type cell in glucose minimal medium",
            "intervention": "glucose supplied at 2, 5 or 20 mM",
            "observable": "whether the three dose arms hold distinct cells or copies of the same ones",
            "granularity": "whole_cell",
            "regulatory_dependencies": (),
            "evidence_coverage": "the nine condition/glc_* rows — three doses at three seeds — on the eleven "
                                 "channels survey.CHANNELS declares",
        },
        # NO CAPABILITY GATES THIS, and `requires` is empty on purpose. The derivation then reads "nothing
        # blocks it", which is correct: the question is about what the corpus CONTAINS, not about what the
        # model computes, and the registry has no business answering it. The idiom is the held-out bank's
        # "(none applies) -> answer" row. `mode_constraint` pins the derivation to the mode the rows are
        # actually in, because with no requirement to gate it the registry would otherwise report
        # coarse_kinetic answerable — it never consults the corpus when there is no capability to check.
        "governed_by": "capability_registry",
        "requires": (),
        "mode_constraint": ("steady_state",),
        "represented_in": ("steady_state",),
        "admissible_modes": ("steady_state",),
        "action": "answer",
        "answer_mode": "steady_state",
        "why_not": (),
        "blocking": {},
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "no — the nine rows hold three distinct channel vectors, one per seed; within a seed all three "
            "doses agree on every one of the eleven declared channels",
            "so n is 3, not 9, and the three arms are not independent samples (INV-1)",
            "this is the check that makes C8.1's refusal measurable rather than merely declared",
        ),
        "must_not_say": (
            "that the arms are independent because they are separate designs with separate rows",
            "a dose effect inferred from the seed-to-seed spread, which is what a curve fitted across the "
            "nine rows would be reporting",
        ),
        "check": {"kind": "dose_identity", "conditions": ("glc_2mM", "glc_5mM", "glc_20mM"),
                  "n_rows": 9, "n_seeds": 3, "n_distinct_channel_vectors": 3},
        "measured": {
            "source": "data/manifest/*.parquet via manifest.DEDUP_QUALIFY over survey.CHANNELS, recomputed "
                      "2026-11-01",
            "n_declared_channels": 11,
            "rows": 9,
            "within_seed_arm_pairs_identical_on_all_channels": (9, 9),
            "distinct_channel_vectors_across_the_nine_rows": 3,
            "effective_n": 3,
        },
        "invariants": ("INV-1", "INV-15"),
        "grounding": (
            "data/manifest/*.parquet — the nine dose rows reduce to three distinct channel vectors, "
            "recomputed over survey.CHANNELS (11 names) in tests/test_capbench_cases.py",
            "survey.CHANNELS and instrument.CHANNELS are the same eleven names, kept in sync by a test — so "
            "'the recorded channels' is a declared set here, not a judgement call",
        ),
        "pair": "C8",
        "pair_differs_in": "observable",
    },

    # ========================================================================================================
    # C9 · cytR — the run that never started, reported as no change. `tf_activity` variant 14 holds cytR
    # inactive, which puts the cell in `minimal_plus_cytidine`; Cellarium's condition table has no doubling
    # time for that medium, so the run raises KeyError 'minimal_plus_cytidine' inside
    # chromosome_replication.calculateRequest at t=0. What the audit recorded is one cell: start 0.0 s, end
    # 0.0 s, duration 0.0 s, final_fold 1.0, final_expected 1.0.
    #
    # THAT 1.0 IS THE WHOLE CASE. A fold change of exactly 1.0 against an expectation of exactly 1.0 reads as
    # a measured no-op — the cleanest possible "inactivating this TF changes nothing" — and it is the
    # arithmetic of a zero-length interval. `qc.QCStatus.EMPTY` exists for precisely this ("no readable
    # generation data at all — NOT ok (e.g. a crash before generation 0)"), and the row is shaped so that
    # only the duration tells you to look.
    #
    # The pair turns on `intervention` — variant 14 against variant 13, the same factor held the other way —
    # and the partner is not an `answer` either. Variant 13 ran one generation on one seed and reached fold
    # 1.895 against an expected 1.942. That is a real number, and one seed with one generation is the
    # evidential shape this project has been burned by before, so the caveat IS the answer.
    # ========================================================================================================
    {
        "id": "C9.1",
        "theme": "transcription-factor activity · absent run",
        "question": "Our strain has cytR knocked out of action. How much does that slow the cell down?",
        "r": {
            "entity": "cytR, the cytidine-regulon repressor (PD04028[c], a transcription factor)",
            "intervention": "tf_activity variant 14 — cytR held inactive",  # <-- the field this pair turns on
            "observable": "dry-mass fold change against the fitted expectation",
            "granularity": "whole_cell",
            "regulatory_dependencies": ("cytR's own regulatory activity",),
            "evidence_coverage": "one validation run of the variant, one seed, one generation requested",
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
            "design_key": None,
            "validation_file": "known_faults_validation.json",
            "run_key": "E1_tf_cytR_inactive/s0",
            "qc_verdict": "empty",
            "defect": "the run never produced a timestep. It raised KeyError 'minimal_plus_cytidine' in "
                      "chromosome_replication.calculateRequest at t=0, because the medium the inactive "
                      "variant selects has no doubling time in the condition table. The recorded cell is "
                      "start 0.0 s, end 0.0 s, duration 0.0 s, final_fold 1.0, final_expected 1.0 — a "
                      "no-change result computed over a zero-length interval.",
            "route": "qc.check_result returns QCStatus.EMPTY for a result with no readable generation, which "
                     "is the verdict this row needs. Nothing can be read from the run itself, so answering "
                     "the question needs a doubling time for minimal_plus_cytidine in the condition table "
                     "and a re-run — not a re-read.",
        },
        "storage_gap": None,
        "must_say": (
            "there is no measurement here: the run stopped at t=0 before any generation existed, so the fold "
            "change of 1.0 is the ratio of a mass to itself",
            "the obstruction is a missing medium in the condition table (minimal_plus_cytidine), not a "
            "finding about cytR",
            "the status ledger and the traceback disagree about what went wrong — the ledger records "
            "'failed: RuntimeError' and the innermost frame is a KeyError — so neither alone identifies it",
        ),
        "must_not_say": (
            "that inactivating cytR has no effect on growth, or any paraphrase of final_fold == 1.0",
            "that the variant is unsupported or unimplemented; it runs and selects a medium the condition "
            "table does not describe",
            "that the active-variant run (C9.2) is the control for this one — a control needs two "
            "measurements and there is one",
        ),
        "check": {"kind": "validation_run", "file": "known_faults_validation.json",
                  "run": "E1_tf_cytR_inactive/s0",
                  "identity_key": "KeyError@models/ecoli/processes/chromosome_replication.py:"
                                  "calculateRequest",
                  "n_cells": 1, "duration_s": 0.0, "final_fold": 1.0},
        "measured": {
            "source": "evals/results/known_faults_validation.json, recomputed 2026-11-01",
            "status_ledger_says": "failed: RuntimeError",
            "innermost_frame": "KeyError@models/ecoli/processes/chromosome_replication.py:calculateRequest",
            "message": "'minimal_plus_cytidine'",
            "cells": ({"start_s": 0.0, "end_s": 0.0, "duration_s": 0.0, "final_fold": 1.0,
                       "final_expected": 1.0},),
        },
        "invariants": ("INV-3", "INV-4"),
        "grounding": (
            "evals/results/known_faults_validation.json runs['E1_tf_cytR_inactive/s0'] — one cell, "
            "duration_s 0.0, final_fold 1.0, final_expected 1.0, identity_key "
            "KeyError@models/ecoli/processes/chromosome_replication.py:calculateRequest, message "
            "\"'minimal_plus_cytidine'\"",
            "the same file's readouts['E1'] — 'cytR inactive (variant 14) raised KeyError "
            "'minimal_plus_cytidine' in chromosome_replication.calculateRequest at t=0'",
            "scripts/validate_known_faults.py ARMS — variant 14 is cytR inactive, 'medium "
            "minimal_plus_cytidine, which has no doubling time in Cellarium's condition table'",
            "qc.py QCStatus.EMPTY — 'no readable generation data at all — NOT ok (e.g. a crash before "
            "generation 0)'; check_result returns it for a SimResult with no generations",
            "INVARIANTS.json INV-4 NULL IS NOT FALSE",
        ),
        "pair": "C9",
        "pair_differs_in": "intervention",
    },
    {
        "id": "C9.2",
        "theme": "transcription-factor activity · one seed",
        "question": "Our strain has cytR locked on. How much does that slow the cell down?",
        "r": {
            "entity": "cytR, the cytidine-regulon repressor (PD04028[c], a transcription factor)",
            "intervention": "tf_activity variant 13 — cytR held active",    # <-- the only field that moved
            "observable": "dry-mass fold change against the fitted expectation",
            "granularity": "whole_cell",
            "regulatory_dependencies": ("cytR's own regulatory activity",),
            "evidence_coverage": "one validation run of the variant, one seed, one generation requested",
        },
        "governed_by": "data_quality",
        "requires": (),
        "mode_constraint": None,
        "represented_in": ("steady_state", "kinetic", "coarse_kinetic"),
        "admissible_modes": ("steady_state",),
        "action": "qualify",
        "answer_mode": "steady_state",
        "why_not": (),
        "blocking": {},
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "the number exists and is a 1.895-fold mass gain against a fitted expectation of 1.942, over one "
            "generation of 2,528 s",
            "it rests on ONE seed and ONE generation, so it carries no error bar and no generation-depth "
            "stratum — reporting it bare would be reporting a sample of one as a rate",
            "the natural comparison, the inactive variant, does not exist as a measurement (C9.1), so this "
            "number has no counterpart and is not a cytR effect",
        ),
        "must_not_say": (
            "a cytR effect size, or any difference against the inactive variant",
            "that 1.895 against 1.942 is 'as expected' — one seed cannot separate a 2.4% shortfall from seed "
            "noise, and the corpus's own wild-type spread is wider than that",
        ),
        "check": {"kind": "validation_run", "file": "known_faults_validation.json",
                  "run": "E1_tf_cytR_active/s0", "identity_key": "no_traceback",
                  "n_cells": 1, "duration_s": 2528.0, "final_fold": 1.895},
        "measured": {
            "source": "evals/results/known_faults_validation.json, recomputed 2026-11-01",
            "status_ledger_says": "completed",
            "cells": ({"start_s": 0.0, "end_s": 2528.0, "duration_s": 2528.0, "final_fold": 1.895,
                       "final_expected": 1.942},),
            "n_seeds": 1,
            "n_generations": 1,
            "shortfall_vs_expected_pct": 2.4,
        },
        "invariants": ("INV-5", "INV-14"),
        "grounding": (
            "evals/results/known_faults_validation.json runs['E1_tf_cytR_active/s0'] — identity_key "
            "no_traceback, one cell, duration_s 2528.0, final_fold 1.895, final_expected 1.942",
            "scripts/validate_known_faults.py ARMS — E1_tf_cytR_active is tf_activity variant 13, seeds [0], "
            "1 generation; the arm was written as the CONTROL for variant 14 and is all that survived",
            "INVARIANTS.json INV-5 GENERATION DEPTH IS A STRATUM, NOT NOISE and INV-14 ENVELOPE",
        ),
        "pair": "C9",
        "pair_differs_in": "intervention",
    },

    # ========================================================================================================
    # C10 · The leucine auxotroph — the one seed that finished is the one you must not read. leuB (ko_index
    # 1818, n_tu=1, reference-essential) in minimal medium, four generations requested, four seeds. Three of
    # the four end with ValueError 'array must not contain infs or NaNs' inside
    # polypeptide_elongation.calculate_trna_charging. The fourth completes, and its terminal generation ran
    # the full 10,800 s cap WITHOUT DIVIDING while dry mass went up 5.736-fold — protein x0.95, RNA x1.46,
    # small molecules x7.4. Mass accumulated; the cell did not grow.
    #
    # SO THE OBVIOUS FILTER SELECTS THE DEFECT. "Use the runs that completed" leaves exactly one run, and it
    # is the one whose headline number is a 5.7-fold mass gain in a non-dividing cell. `qc.check_generation`
    # returns NO_DIVISION for it, which is the verdict — and the corpus's own four plain `KO:leuB` rows are
    # no help either: three are `crashed` and one is `no_division`, so none is reportable.
    #
    # The pair turns on `entity`, a field no earlier pair has moved. Same medium, same intervention (none
    # beyond the genotype), same observable, same granularity — swap the auxotroph for the wild type and the
    # correct action goes from "flag this" to a number with thirty-four reportable rows behind it.
    # ========================================================================================================
    {
        "id": "C10.1",
        "theme": "auxotroph · growth that is not growth",
        "question": "How much does a leucine auxotroph grow in minimal medium with no leucine in it?",
        "r": {
            "entity": "a leuB knockout (ko_index 1818) — a leucine auxotroph",  # <-- the field this pair turns on
            "intervention": "none beyond the genotype — minimal medium with no leucine source",
            "observable": "dry-mass fold change per generation",
            "granularity": "whole_cell",
            "regulatory_dependencies": (),
            "evidence_coverage": "reportable steady_state runs of this genotype in minimal medium with a "
                                 "per-generation mass trace",
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
            "design_key": None,
            "validation_file": "known_faults_validation.json",
            "run_key": "E3_leucine_auxotroph_minimal/s3",
            "qc_verdict": "no_division",
            "defect": "the only seed of four that completed ends in a generation that ran the full 10,800 s "
                      "cap without dividing, over which dry mass rose 5.736-fold against a fitted "
                      "expectation of 17.041 while protein went x0.95 and small molecules x7.4. The "
                      "dry-mass number is small-molecule accumulation in a stalled cell, not growth, and "
                      "`divided` is False, so qc.check_generation returns NO_DIVISION.",
            "route": "the three remaining seeds end with ValueError 'array must not contain infs or NaNs' in "
                     "polypeptide_elongation.calculate_trna_charging, so the arm has no clean replicate to "
                     "fall back on; the corpus's four plain gene_knockout/KO:leuB rows are 3 crashed and 1 "
                     "no_division, none reportable. Answering it needs a run that survives the charging "
                     "solver, not a different read of these.",
        },
        "storage_gap": None,
        "must_say": (
            "the fold change is dominated by small molecules (x7.4) in a cell that never divided — the "
            "aggregate hides the shape, and protein actually went DOWN (x0.95)",
            "three of the four seeds never reached this point: they end with a NaN inside the tRNA charging "
            "solver, so the completed seed is not a representative survivor but the only one left",
            "the corpus adds nothing here — all four plain KO:leuB rows are unreportable (3 crashed, 1 "
            "no_division)",
        ),
        "must_not_say": (
            "a growth rate or doubling time for the auxotroph, from this seed or from the arm's mean",
            "that the auxotroph grows 5.7-fold, or that it reaches a third of its expected mass",
            "'three seeds crashed and one worked' as evidence that the working one is the valid one — the "
            "surviving seed carries its own verdict, and it is NO_DIVISION",
        ),
        "check": {"kind": "validation_arm", "file": "known_faults_validation.json",
                  "arm": "E3_leucine_auxotroph_minimal", "n_runs": 4,
                  "identity_keys": {
                      "ValueError@models/ecoli/processes/polypeptide_elongation.py:calculate_trna_charging": 3,
                      "no_traceback": 1},
                  "terminal_generation": {"run": "E3_leucine_auxotroph_minimal/s3", "duration_s": 10800.0,
                                          "final_fold": 5.736, "final_expected": 17.041}},
        "measured": {
            "source": "evals/results/known_faults_validation.json + data/manifest/*.parquet, both recomputed "
                      "2026-11-01",
            "validation_seeds": 4,
            "seeds_ending_in_the_charging_NaN": 3,
            "seeds_completing": 1,
            "terminal_generation_duration_s": 10800.0,
            "terminal_generation_folds": {"dry_mass": 5.736, "protein": 0.95, "rna": 1.46,
                                          "small_molecules": 7.4},
            "terminal_generation_expected_fold": 17.041,
            "corpus_plain_KO_leuB_rows": 4,
            "corpus_plain_KO_leuB_reportable": 0,
            "corpus_plain_KO_leuB_qc": ("crashed", "crashed", "crashed", "no_division"),
        },
        "invariants": ("INV-3", "INV-5", "INV-15"),
        "grounding": (
            "evals/results/known_faults_validation.json runs['E3_leucine_auxotroph_minimal/s3'] cells[3] — "
            "start 20589.0, end 31389.0, duration_s 10800.0, final_fold 5.736, final_expected 17.041",
            "the same file's readouts['E3_seed3_last_generation'] — 'over a further capped 10,800 s, protein "
            "x0.95, RNA x1.46, small molecules x7.4, dry mass x5.7 -- runaway small-molecule accumulation in "
            "a non-dividing cell, not growth'",
            "readouts['E3_leucine_pool'] — 'seeds 0-2 end with the NaN in calculate_trna_charging after a "
            "generation capped at 10,800 s'",
            "qc.py check_generation — `if not gen.divided or gen.division_time_sec is None: return "
            "QCStatus.NO_DIVISION`",
            "scope.py gene_scope: leuB -> ko_index 1818, n_tu 1, essential_ref True",
            "data/manifest/*.parquet: perturbation='gene_knockout', condition='KO:leuB', timeline NULL — 4 "
            "rows, 0 reportable",
        ),
        "pair": "C10",
        "pair_differs_in": "entity",
    },
    {
        "id": "C10.2",
        "theme": "wild type · the number the corpus does carry",
        "question": "How much does the wild type grow in minimal medium with no leucine in it?",
        "r": {
            "entity": "the wild type",                                  # <-- the only field that moved
            "intervention": "none beyond the genotype — minimal medium with no leucine source",
            "observable": "dry-mass fold change per generation",
            "granularity": "whole_cell",
            "regulatory_dependencies": (),
            "evidence_coverage": "reportable steady_state runs of this genotype in minimal medium with a "
                                 "per-generation mass trace",
        },
        # Again no capability gates it, and `mode_constraint` keeps the derivation honest about where the rows
        # are. The contrast with C10.1 is the whole point of the pair: the SAME question, one field changed,
        # and the evidence goes from four unreportable rows to thirty-four reportable ones.
        "governed_by": "capability_registry",
        "requires": (),
        "mode_constraint": ("steady_state",),
        "represented_in": ("steady_state",),
        "admissible_modes": ("steady_state",),
        "action": "answer",
        "answer_mode": "steady_state",
        "why_not": (),
        "blocking": {},
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "34 of the 36 steady_state wildtype/basal rows are reportable and carry growth_rate, so this one "
            "has replicates — the two that are not reportable are `no_division` and must be left out",
            "minimal medium contains no leucine, so the wild type here is making its own: this is the "
            "baseline the auxotroph question (C10.1) wants and cannot have",
        ),
        "must_not_say": (
            "an auxotroph-versus-wild-type effect size — the other arm of that comparison does not exist as "
            "a measurement (C10.1)",
            "a number pooled over the two no_division rows, or over the six kinetic wildtype rows, which are "
            "a different elongation model (INV-2)",
        ),
        "check": {"kind": "condition_rows", "perturbation": "wildtype", "condition": "basal",
                  "elongation_model": "steady_state", "column": "growth_rate", "n_rows": 36,
                  "qc_values": ("no_division", "ok")},
        "measured": {
            "source": "data/manifest/*.parquet via manifest.DEDUP_QUALIFY, recomputed 2026-11-01",
            "steady_state_rows": 36,
            "reportable_with_growth_rate": 34,
            "unreportable_qc": ("no_division",),
            "kinetic_rows_excluded": 6,
            "growth_rate_range_over_the_wildtype_basal_design": (0.0002071064848171679,
                                                                 0.0002642217718874653),
        },
        "invariants": ("INV-2", "INV-3"),
        "grounding": (
            "data/manifest/*.parquet: perturbation='wildtype', condition='basal', "
            "elongation_model='steady_state' — 36 rows, 34 reportable and carrying growth_rate, qc values "
            "{ok, no_division}",
            "the same query with elongation_model='kinetic' returns 6 rows, which INV-2 keeps out of the "
            "same number",
        ),
        "pair": "C10",
        "pair_differs_in": "entity",
    },

    # ========================================================================================================
    # C11 · cysE and metA — the solver, not the cell. Two single-transcription-unit, reference-essential
    # metabolic knockouts (cysE 2087, metA 2021) in minimal medium, two seeds each, four generations
    # requested. All four runs stopped in generation 0 with RuntimeError GLP_ESING — 'Basis matrix is
    # singular' — from the GLPK FBA solver, after GLP_EFAIL/GLP_NOFEAS retries. Growth at the stop was
    # 63-78% of the fitted expectation: slowed, not stalled, and no equilibrium failure occurred at all.
    #
    # WHY THIS IS A `propose` AND NOT A `flag`. There is no defective number to flag — there is no number.
    # And it is not a refusal either, because the obstruction is known to be removable: the large campaign's
    # release branch carries an FBA retry wrapper, and under it the same two knockouts mostly survive
    # generation 0 and run to the 10,800 s cap, with one fba_infeasible. So the honest action is to name the
    # campaign that would answer it — a re-run under that branch — rather than re-read these four runs or
    # declare the model unable.
    # ========================================================================================================
    {
        "id": "C11.1",
        "theme": "essential metabolic knockout · solver failure",
        "question": "Does deleting cysE stop the cell growing in minimal medium?",
        "r": {
            "entity": "cysE (serine O-acetyltransferase, ko_index 2087, n_tu=1, reference-essential)",
            "intervention": "gene_knockout in minimal medium, four generations requested",
            "observable": "growth rate relative to the fitted expectation",
            "granularity": "whole_cell",
            "regulatory_dependencies": (),
            "evidence_coverage": "4 validation runs (cysE and metA, seeds 0-1), all stopping in generation 0",
        },
        "governed_by": "data_quality",
        "requires": (),
        "mode_constraint": None,
        "represented_in": ("steady_state", "kinetic", "coarse_kinetic"),
        "admissible_modes": (),
        "action": "propose",
        "answer_mode": None,
        "why_not": (),
        "blocking": {},
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "no generation completed: all four runs stopped in generation 0 with GLP_ESING (singular basis) "
            "inside the GLPK solver, between 1,433 and 2,448 s",
            "at the stop the cells were at 63-78% of their fitted expected mass — slowed, not stalled — so "
            "the stop is the solver's and the phenotype is undetermined",
            "the campaign to propose is a re-run under the branch carrying the FBA retry wrapper, where the "
            "same two knockouts mostly survive generation 0 and reach the 10,800 s cap; this is a known "
            "removable obstruction, not a model limit",
            "no equilibrium failure occurred in any of the four runs, so only one of the external campaign's "
            "two reported failure modes reproduced here",
        ),
        "must_not_say": (
            "that cysE is lethal, or that the knockout stalls growth — 63-78% of expected is the opposite of "
            "stalled",
            "a growth rate or doubling time from the truncated generation-0 traces",
            "that these runs refute the external campaign's report; the solver failure reproduced and the "
            "equilibrium failure was simply never reached",
        ),
        "check": {"kind": "validation_arm", "file": "known_faults_validation.json", "arm": "E4_",
                  "n_runs": 4,
                  "identity_keys": {"RuntimeError@wholecell/utils/_netflow/nf_glpk.py:_solve": 4},
                  "terminal_generation": None},
        "measured": {
            "source": "evals/results/known_faults_validation.json, recomputed 2026-11-01",
            "runs": 4,
            "runs_stopping_in_generation_0_with_GLP_ESING": 4,
            "generations_completed": 0,
            "stop_times_s": (1433.0, 1907.0, 2445.0, 2448.0),
            "fold_fraction_of_expected_pct": (63.3, 64.4, 72.4, 77.9),
            "equilibrium_failures": 0,
            "the_artifact_readout_said_stop_times_from_s": 1410.0,
        },
        "invariants": ("INV-3", "INV-17"),
        "grounding": (
            "evals/results/known_faults_validation.json — all four E4 runs carry identity_key "
            "RuntimeError@wholecell/utils/_netflow/nf_glpk.py:_solve with message 'GLP_ESING: Basis matrix "
            "is singular', one cell each, none reaching generation 1",
            "the same file's readouts['E4'] — 'growth was 63-78% of expected, not stalled. No equilibrium "
            "failure occurred. In the large campaign's release (branch with an FBA retry wrapper) the same "
            "knockouts mostly survive generation 0 and end at the 10,800 s time limit (one fba_infeasible)'",
            "recomputed from the same file's `cells`: durations 1433/1907/2445/2448 s, so that readout's own "
            "'1,410-2,448 s' understates the minimum by 23 s; its 63-78% band recomputes exactly",
            "scope.py gene_scope: cysE -> ko_index 2087, n_tu 1, is_sole_catalyst True, essential_ref True; "
            "metA -> ko_index 2021, the same shape",
            "qc.py QCStatus.FBA_INFEASIBLE is the verdict such a run would carry once it has a generation to "
            "attach one to — these have none, which is why this is a campaign and not a QC flag",
        ),
        "pair": None,
        "pair_differs_in": None,
    },

    # ========================================================================================================
    # C12 · No carbon source — a cell that grows faster without food, and the audit question that finds it.
    # With glucose absent (`minimal_no_glucose`, whose carbon is CO2 and a trace of L-selenocysteine) the
    # metabolic network takes up no carbon beyond ~0.00015 mmol/gDW/h of selenocysteine, and the cell makes
    # biomass FASTER than the glucose control: dry mass 145.8 -> 529.2 fg in 4,351 s, a 3.725-fold gain
    # against a fitted expectation of 1.676, while secreting CO2 at 15.62 and formate at 2.30 mmol/gDW/h
    # against the control's 1.67 and 0.03. Carbon is not conserved.
    #
    # The pair turns on `observable` and runs the same way round as C8: the biology is refused, and the audit
    # question on the very same run is answerable — reading the exchange fluxes is HOW the refusal is
    # justified. A system that refuses both never finds out the cell is secreting carbon it never took up; a
    # system that answers the first reports a growth rate for a starving cell.
    # ========================================================================================================
    {
        "id": "C12.1",
        "theme": "carbon starvation · representation",
        "question": "With no carbon source in the medium at all, how fast does the cell grow?",
        "r": {
            "entity": "a wild-type cell in minimal medium with no glucose",
            "intervention": "glucose absent from the medium from the start",
            "observable": "growth rate — how fast the cell builds biomass",
            "granularity": "whole_cell",
            "regulatory_dependencies": (),
            "evidence_coverage": "the two E2 glucose-absent validation runs and their wild-type null arm",
        },
        "governed_by": "capability_registry",
        "requires": ("growth_without_a_carbon_source",),
        "mode_constraint": None,
        "represented_in": (),
        "admissible_modes": (),
        "action": "refuse",
        "answer_mode": None,
        "why_not": ("no_elongation_model_represents_it",),
        "blocking": {
            "steady_state": {"growth_without_a_carbon_source": "no_elongation_model_represents_it"},
            "kinetic": {"growth_without_a_carbon_source": "no_elongation_model_represents_it"},
            "coarse_kinetic": {"growth_without_a_carbon_source": "no_elongation_model_represents_it"},
        },
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "the cell keeps making biomass at least as fast as with glucose while taking up no carbon, so "
            "carbon is not conserved and growth after carbon removal is not a response to carbon starvation",
            "the runs complete and divide on the control's schedule — refusing is not a statement that they "
            "failed, which is exactly what makes this one dangerous",
            "glucose DOSE is a separate question with its own entry, also refused (C8.1)",
        ),
        "must_not_say": (
            "a growth rate, doubling time or division time for the no-carbon cell",
            "that removing glucose at 1,200 s left growth unchanged because carbon is not limiting in this "
            "model — the two arms agree because the carbon was never being used",
            "an interpretation of the 3 of 4 removal seeds that completed as survival, or of the fourth "
            "(ATP exhausted in translation 410 s into generation 1) as death",
        ),
        "check": {"kind": "registry"},
        "measured": {
            "source": "capability.py, re-derived by capability.check() in the test, plus "
                      "evals/results/known_faults_validation.json recomputed 2026-11-01",
            "modes_representing_growth_without_a_carbon_source": (),
            "glucose_absent_runs": 2,
            "glucose_removed_runs": 4,
            "glucose_removed_runs_completing_two_generations": 3,
            "dry_mass_fg_start_end": (145.8, 529.2),
            "fold_and_expected_fold": (3.725, 1.676),
        },
        "invariants": ("INV-10",),
        "grounding": (
            "capability.py growth_without_a_carbon_source — present=False, holds_in=(); instead: 'the cell "
            "keeps making biomass at least as fast as with glucose ... Carbon is not conserved'",
            "evals/results/known_faults_validation.json runs['E2_glucose_absent/s0'] — one cell, 4,471 s, "
            "final_fold 3.725 against final_expected 1.676, identity_key no_traceback",
            "the same file's readouts['E2_glucose_removed_s0_vs_control_s0'] — 'identical to 1,180 s; at "
            "1,780 s dry mass 605.81 vs 605.17 fg; both seeds divide on the control schedule'",
            "INVARIANTS.json INV-10 A MISSING MECHANISM IS A REFUSAL, NEVER A ZERO",
        ),
        "pair": "C12",
        "pair_differs_in": "observable",
    },
    {
        "id": "C12.2",
        "theme": "carbon starvation · mass balance",
        "question": "In that no-glucose run, is the cell taking up any carbon at all?",
        "r": {
            "entity": "a wild-type cell in minimal medium with no glucose",
            "intervention": "glucose absent from the medium from the start",
            "observable": "carbon uptake — how much carbon crosses the membrane",  # <-- the only field moved
            "granularity": "whole_cell",
            "regulatory_dependencies": (),
            "evidence_coverage": "the two E2 glucose-absent validation runs and their wild-type null arm",
        },
        "governed_by": "capability_registry",
        "requires": (),
        "mode_constraint": ("steady_state",),
        "represented_in": ("steady_state",),
        "admissible_modes": ("steady_state",),
        "action": "answer",
        "answer_mode": "steady_state",
        "why_not": (),
        "blocking": {},
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "no — the recorded uptake fluxes are ammonium (-9.31), iron, calcium and chloride, and nothing "
            "carbon-bearing; the control takes up glucose at -6.39 mmol/gDW/h",
            "and the same cell SECRETES carbon: CO2 at 15.62 and formate at 2.30 mmol/gDW/h, against the "
            "control's 1.67 and 0.03",
            "that imbalance is the reason the growth question (C12.1) is refused, and it is readable from the "
            "exchange fluxes without any new run",
        ),
        "must_not_say": (
            "a carbon balance closed by invoking the trace selenocysteine — ~0.00015 mmol/gDW/h cannot "
            "supply 15.6 of secreted CO2, and saying it might is arithmetic nobody did",
            "that the secretion proves the cell is consuming internal stores; mass is not conserved here, "
            "which is a different statement and the one the fluxes support",
        ),
        "check": {"kind": "validation_exchange", "file": "known_faults_validation.json",
                  "readout": "E2_glucose_absent_s0_exchange_mmol_per_gDW_h",
                  "carbon_uptake_species": (), "secreted": ("CARBON-DIOXIDE[p]", "FORMATE[p]"),
                  "control_uptake_species": ("GLC[p]",)},
        "measured": {
            "source": "evals/results/known_faults_validation.json readouts, recomputed 2026-11-01",
            "uptake_mmol_per_gDW_h": {"AMMONIUM[c]": -9.31, "FE+2[p]": -0.0128, "CA+2[p]": -0.0094,
                                      "CL-[p]": -0.0092},
            "secretion_mmol_per_gDW_h": {"CARBON-DIOXIDE[p]": 15.62, "FORMATE[p]": 2.3},
            "control_uptake_mmol_per_gDW_h": {"GLC[p]": -6.39},
            "control_secretion_mmol_per_gDW_h": {"CARBON-DIOXIDE[p]": 1.67, "FORMATE[p]": 0.03},
            "carbon_bearing_uptake_species": 0,
            "no_carbon_uptake_flag": True,
        },
        "invariants": ("INV-10", "INV-15"),
        "grounding": (
            "evals/results/known_faults_validation.json "
            "readouts['E2_glucose_absent_s0_exchange_mmol_per_gDW_h'] — uptake {AMMONIUM[c] -9.31, FE+2[p] "
            "-0.0128, CA+2[p] -0.0094, CL-[p] -0.0092}, secretion {CARBON-DIOXIDE[p] 15.62, FORMATE[p] 2.3}, "
            "no_carbon_uptake true, control_C_s0 {GLC[p] -6.39, CARBON-DIOXIDE[p] 1.67, FORMATE[p] 0.03}",
            "capability.py growth_without_a_carbon_source instead — 'the metabolic network takes up no "
            "carbon beyond about 0.00015 mmol/gDW/h of selenocysteine ... while the cell secreted CO2 at "
            "14.5-15.6 mmol/gDW/h'",
        ),
        "pair": "C12",
        "pair_differs_in": "observable",
    },

    # ========================================================================================================
    # C13 · The rescue arm that cannot be rescued — and the second case in this corpus that needs
    # `mode_constraint`. Metabolism builds its amino-acid uptake package from
    # PolypeptideElongation.aa_exchange_rates (metabolism.py:171-176), and only SteadyStateElongationModel
    # ever assigns that attribute. Under either kinetic model it stays the zeros initialize() left behind, so
    # in ANY medium containing amino acids the FBA is told uptake is zero. No exception, no warning.
    #
    # WHY THE MODE HAS TO BE IN THE QUESTION. `amino_acid_uptake_from_the_medium` is present and holds under
    # steady_state, so without the constraint the derivation reads this as answerable and routes it there —
    # which would be answering a different question. The question here is about the KINETIC runs, because
    # that is where isoacceptor resolution lives and therefore where anyone wanting a per-isoacceptor
    # starve-then-rescue experiment has to work. The rescue half of that experiment is structurally inert,
    # and a failed rescue there is the missing transport, not biology.
    # ========================================================================================================
    {
        "id": "C13.1",
        "theme": "amino-acid transport · elongation model",
        "question": "In the kinetic runs, I starve the cell of leucine and then feed leucine back. Does the "
                    "rescue work?",
        "r": {
            "entity": "a wild-type cell under the kinetic elongation model",
            "intervention": "leucine withdrawn, then restored to the medium",
            "observable": "whether the restored amino acid reaches the cell",
            "granularity": "whole_cell",
            "regulatory_dependencies": ("amino-acid supply",),
            "evidence_coverage": "the kinetic rows of the corpus; no kinetic run carries an upshift",
        },
        "governed_by": "capability_registry",
        "requires": ("amino_acid_uptake_from_the_medium",),
        "mode_constraint": ("kinetic",),
        "represented_in": (),
        "admissible_modes": (),
        "action": "refuse",
        "answer_mode": None,
        "why_not": ("another_mode_represents_it",),
        "blocking": {"kinetic": {"amino_acid_uptake_from_the_medium": "another_mode_represents_it"}},
        "data_defect": None,
        "storage_gap": None,
        "must_say": (
            "under either kinetic model the FBA is told amino-acid uptake is zero in every medium, because "
            "aa_exchange_rates is only ever assigned by the steady-state elongation model",
            "so the rescue arm of a starve-then-rescue experiment is structurally inert under kinetic, and a "
            "failed rescue there is the missing transport rather than biology",
            "there is no exception and no warning — the zeros from initialize() are what metabolism reads, "
            "which is why this cannot be caught by looking at the run's own output",
            "the mechanism exists under steady_state, so this is a model-change question (the registry's "
            "draft patch EXT-PORT-A), not a campaign to re-run",
        ),
        "must_not_say": (
            "a rescue result from the kinetic rows, in either direction",
            "that the steady-state rows settle it — they are a different elongation model and the question "
            "named this one (INV-2)",
            "that amino-acid transport is absent from the model; it is present and reachable, just not from "
            "the mode asked about",
        ),
        "check": {"kind": "registry"},
        "measured": {
            "source": "capability.py, re-derived by capability.check() in the test",
            "modes_representing_amino_acid_uptake_from_the_medium": ("steady_state",),
            "mode_asked": ("kinetic",),
            "draft_patch": {"kinetic": "EXT-PORT-A"},
        },
        "invariants": ("INV-2", "INV-10"),
        "grounding": (
            "capability.py amino_acid_uptake_from_the_medium — present=True, holds_in=('steady_state',); "
            "instead (kinetic, coarse_kinetic): 'metabolism builds its amino-acid uptake package from "
            "PolypeptideElongation.aa_exchange_rates (metabolism.py:171-176), and ONLY "
            "SteadyStateElongationModel ever assigns that attribute ... No exception, no warning'",
            "the same entry's consequence — 'the rescue arm of the most obvious tRNA experiment -- starve, "
            "then rescue -- is structurally inert, and a failed rescue is the missing mechanism rather than "
            "biology'",
            "capability.py draft_patch == {'kinetic': 'EXT-PORT-A'} — the obstruction has a named model "
            "change attached, which is why the refusal names one",
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
# Together they are 9 of 22 — up from 4 of 10 — so over-refusal is measurable and the answerable side is now
# within reach of the spec's ~half without a single key being asserted. The 6 unqualified answers are still
# the smaller half, and that is a consequence of grounding every case rather than a choice: the corpus's
# unqualified answers are its least interesting rows, and the ones written here exist because a pair needed
# them (C8.2, C10.2, C12.2 are each the audit question that justifies its partner's refusal).
#
# `pair_fields_exercised` now covers FIVE of r's six fields. The one still unexercised is
# `regulatory_dependencies`, and it is the hardest to move alone: changing which regulator a question depends
# on usually changes the intervention or the observable with it, which is why C7 states the dependency as a
# ROLE identical on both sides rather than naming PhoB against ppGpp. A pair that moves it and nothing else is
# the obvious next one to write.
# ------------------------------------------------------------------------------------------------------------
BALANCE = {
    "n_cases": 22,
    "by_action": {"answer": 6, "qualify": 3, "refuse": 6, "propose": 3, "flag": 4},
    "by_governor": {"capability_registry": 12, "corpus_storage": 2, "data_quality": 8},
    "registry_why_not_covered": ("no_elongation_model_represents_it", "another_mode_represents_it",
                                 "no_run_used_this_mode"),
    "n_pairs": 9,
    "pair_fields_exercised": ("granularity", "intervention", "evidence_coverage", "observable", "entity"),
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
