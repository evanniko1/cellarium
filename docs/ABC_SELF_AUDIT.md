# Agentic Benchmark Checklist: Cellarium's evaluations, item by item

Validation-layer item 10, filled 2026-11-23. The checklist is the Agentic Benchmark Checklist (ABC) of
arXiv:2507.02825 (read at v5): 42 items in three groups: task validity (T), outcome validity (O), reporting (R).
Its authors applied it to ten widely used agent benchmarks and found task-validity flaws in seven,
outcome-validity flaws in seven, and reporting gaps in all ten. The prior that Cellarium's evaluations have
several is high, and this table is the check.

**Surfaces scored.** *Gate*: the pre-dispatch capability gate's evaluation (`scripts/run_gate_eval.py`; the
216-item generated bank and the 60-item held-out set). *Council*: the Socratic Council's role ablation and its A/B
against Cellwright (`evals/ablate.py`, `evals/run_ab.py`). *Selective answering*: the discrimination set of the
Platform Map, section 18.

**What MET means here.** An item is MET only with evidence a reader can rerun. Where the evidence is a test, the
test was broken once on purpose and seen to fail; those plants live in `tests/test_abc_forced_failures.py` and run
with the suite. An item marked MET without that is marked *documented*, which is weaker, and says so.

**A caveat on the R items.** The T and O wording below was read from the paper's body. The R wording was read
from a summary of its appendix, so it is paraphrased with lower confidence; check it against the paper before
citing an R item by number.

## Summary

| Status | Items |
|---|---|
| MET, guarded by a test that was forced to fail | T.1, T.3, T.5, T.6, T.9 (gate), T.10, O.b.3, R.9, R.10 (gate), R.13 (gate) |
| MET, documented or by construction | T.2, T.4, O.h.1, O.h.2, R.1, R.2, R.3, R.5, R.6, R.7, R.8, R.11 |
| PARTLY | T.7, T.8, R.4 |
| NOT MET, open | O.c.1, O.i.1, R.12; and for the Council: R.10, R.13, O.b.2 |
| OUT OF SCOPE, declared | T.9 for the Council: no oracle exists for an open-ended hypothesis |
| NOT APPLICABLE, with the reason | O.a.1-2, O.b.1, O.d.1-2, O.e.1-3, O.f.1-2, O.g.1-3 |

## Task validity

| ID | Item (paraphrased) | Status | Evidence, and what is missing |
|---|---|---|---|
| T.1 | Specify tool and package versions for self-hosted tools | MET, forced, for runs from 2026-11-23 | The simulator's image digest and knowledge-base hash are recorded per run (`provenance.py`). `requirements.lock` pins 119 packages and the project's `.venv` matches 117, but a lock says what should run, not what did: the system interpreter the suite runs on differed from it on 70 of 119, `anthropic` 0.92.0 against 0.116.0. Since 2026-11-23 the gate eval, the ablation and every A/B arm record the interpreter, the git commit, the installed versions of the eight packages that can change a result, and where those differ from the lock (`tests/test_eval_artefacts_record_their_environment.py`); the anthropic upper bound is guarded (`tests/test_registry_survivor_guards.py`). Forced: an empty recorded environment turns the guard red. Not covered: every stored artefact predates this and records only its model id. |
| T.2 | API availability; manage rate limits | MET, documented | Every eval path uses the client with retries and backoff (`llm.client(max_retries=4)`); a parser that returned nothing is recorded, not retried silently. |
| T.3 | Detect API interruptions; stop and inform | MET, forced | Since 2026-11-23 the three scored harnesses (gate eval, ablation, A/B) stop at the first run of five consecutive failed model calls, each already retried by the client. No new call starts, the partial records go to `<out>.partial.json` with the reason and no score, the artefact itself is not touched, and the exit code is 3 (`src/cellarium/outage.py`, `tests/test_runs_stop_on_an_outage.py`). It matters most for the gate: its parser proceeds on a blank requirement when its call fails, so an outage would otherwise have been graded as the ignorance rule on every later item; each record now names its parser error. Corrected: this row said a failed call becomes a `no_verdict`, which held only when the harness itself raised, not for a failed parse. No stored run is affected (0 failed parses in all three gate runs). The A/B now retries an errored arm on a re-run, and the ablation no longer writes progress over its artefact. Forced: with a breaker that never trips, the stop test goes red. Not covered: the other paid scripts (judge-panel re-grade, temperature sweep, tool probe, live loop); and a model that answers wrongly on every call is a result, not an interruption. |
| T.4 | Clean state before each task | MET, by construction | One stateless parse and decision per gate item; a fresh `deliberate()` per Council case; a fresh session per A/B case. |
| T.5 | Isolate agents from ground truth | MET, forced | The Council never sees corpus readings (`tests/test_blindness.py`). Its literature search is blocked from the dataset hosts and every URL it saw is audited (`tests/test_blind_external_reads.py`); a brief from a breached search is discarded and the A/B scorer refuses the run. Forced: with the block list emptied the leak reaches the proposer. Not covered: what the model already knows from training (PUB-A4). |
| T.6 | Environment frozen at release, not dynamic | MET, forced | Simulator and knowledge base are hashed per run. Since 2026-11-23 every remote read names a commit. well4cell is pinned in code to its 1.0.0-rc2 commit (4ab4aa37); a corpus with no pin (Cellarium's own deposit, or one a user plugs in) resolves one commit per plan, reads only at it and reports it. The cache knows which commit it holds, from the hub library's own download records, and a cache from another commit reads `stale_cache`; `verify_cache` re-hashes every file against the etag it was served with, and the real well4cell cache verified 24 of 24 files at the pin (`tests/test_remote_reads_are_pinned.py`). Forced: unpinning well4cell, and removing the revision from the real download call, each turn a guard red. Not covered: the deposit is recorded, not frozen, until `CELLARIUM_HF_REVISION` is set at release; three maintenance scripts that check what is on the Hub now (`verify_hf_upload.py`, `verify_dataset_size.py`, `corpus_audit.py`) read the head by design. |
| T.7 | Ground-truth annotation verified | PARTLY | Gate keys are generated from the registry, never hand-labelled, and a second, principled key is reported beside the stored one; the held-out set also carries a judgement key. But 16 of the 216 keys are disputed: the two kinetic tRNA-charging questions imply starvation, which their key ignores (GATE-8b-C). Re-keying waits for held-out set v2, so the benchmark is not fitted to the gate. |
| T.8 | Task setup verified | PARTLY | Registry-deletion twins check the decision step on 16 situations (`tests/test_gate_paired_twins.py`, 16/16). The oracle (T.9) found one cell whose setup no parse can satisfy. |
| T.9 | An oracle solver shows the configuration is correct | MET for the gate; OUT OF SCOPE for the Council | Gate: a perfect parser, handed each cell's canonical requirement, matches the key on 26 of 27 cells; the 27th is GATE-8b-D, so the ceiling on the bank is 208/216 = 0.963 (`tests/test_gate_oracle.py`; forced). Council: no oracle can say a hypothesis is the right one, and none is claimed; this row is the declaration. |
| T.10 | Inspect pilot outliers for bugs | MET, forced | Every one of the 216 run's 27 wrong verdicts is attributed to a registered defect: 25 to GATE-8b-C, 2 to GATE-8b-D (`tests/test_gate_error_causes.py`). An unexplained error now fails the suite. Forced: removing one dependency rule leaves 9 refusals unexplained. |

## Outcome validity

| ID | Item (paraphrased) | Status | Evidence, and what is missing |
|---|---|---|---|
| O.a.1, O.a.2 | Whole-string matching: equivalent and redundant wording | N/A | The gate's outcome is a closed three-value verdict compared exactly; no free text is matched. |
| O.b.1 | Substring matching: negation | N/A | No substring matching is used to score. |
| O.b.2 | Prevent success by listing every possible answer | N/A for the gate; NOT TESTED for the Council | One verdict per gate item. For the Council's judges, an answer that lists every possibility is a named probe (validation item 6) that has not run. |
| O.b.3 | Prevent success by guessing | MET, forced | On the same 216 records, always-refuse scores 0.556 (the best trivial strategy), always-answer 0.333, always-propose 0.111; the gate's 0.875 beats the best by 0.319 (`tests/test_gate_reliability.py`). |
| O.c.1 | LLM-as-judge: accuracy and self-consistency validated | NOT MET | The ablation's Claude and GPT judges disagree (residual defects, r = -0.097) and the Claude judge is about nine times noisier (`tests/test_ablation_mde.py`). No repetition-stability run and no human floor exist (validation item 6: paid runs, two human raters). |
| O.d.1, O.d.2 | Unit-test grading: tests verified; coverage reported | N/A as grading | No evaluation is scored by unit tests. The analogous question, whether the platform's own guard tests would notice a fault, is measured by mutation testing: threshold mutants (tier 0) and the registry operators of validation item 8. Of eleven pre-registered registry faults the suite caught nine and missed two (a record losing its source markers; a loosened dependency pin), each exactly as predicted; both now have a guard (`tests/test_registry_survivor_guards.py`), forced to fail with the fault applied. |
| O.e.1-O.e.3 | Fuzz testing | N/A | No fuzzing is used to score. |
| O.f.1, O.f.2 | End-to-end tests: branch coverage; non-determinism | N/A as grading | No evaluation is scored by an end-to-end test. |
| O.g.1-O.g.3 | State-modification grading | N/A | No evaluation is scored by a final state. |
| O.h.1 | Answer-parser assumptions stated | MET, documented | The parser emits a six-field requirement over a closed vocabulary; anything unrecognised becomes `other`, which routes to the ignorance rule rather than to a refusal (`gate.Requirement.normalised`); parser failures are counted. |
| O.h.2 | A single answer cannot be reached by guessing | MET, with O.b.3 | Three verdicts; the best guessing strategy's score is reported beside the gate's. |
| O.i.1 | Quality metrics track the reasoning, not the format | NOT MET | The Council's six-point quality rubric scores 6/6 in every arm: it measures schema compliance, not framing quality (PUB-A3). The residual-defect measure varies but is underpowered under the Claude judge. |

## Reporting

| ID | Item (paraphrased; lower confidence, see above) | Status | Evidence, and what is missing |
|---|---|---|---|
| R.1 | Open source | MET | The platform is public. |
| R.2 | Open evaluation harness | MET | `evals/` and `scripts/run_gate_eval.py` are public; stored records can be re-scored offline (`--rescore`). |
| R.3 | Contamination measures; a held-out set | MET | Held-out gate set v1 is frozen with a hash lock and refuses to score if edited; v2 refuses until a second reviewer freezes it; the blind-read audit of T.5. |
| R.4 | Challenges updated over time | PARTLY | The bank is generated from the registry, which has grown from 27 to 36 cells; the 9 new cells have not been through the gate eval. |
| R.5 | Relationship between capabilities and outcomes stated | MET, documented | Each surface's construct is named, with what it is not, its unit and sample, the confounds controlled and the error analysis, in the section below (2026-11-23). The gate's, for example: agreement with the registry, not the registry's correctness and not accuracy at answering questions. |
| R.6 | The evaluation subject stated | MET | Every artefact records the model ids and the harness. |
| R.7 | Steps to prevent, find and fix flaws | MET | The GATE-8b ledger, the Platform Map audit, mutation testing, the conformance families, this table. |
| R.8 | Qualitative discussion of unavoidable flaws | MET | Limits are stated in each module and in the Platform Map. |
| R.9 | Quantitative analysis of flaws | MET, forced | The principled-key sensitivity (pilot 0.815 against 0.889); the complete error count and its attribution (25 + 2; oracle ceiling 0.963); a minimum detectable effect beside every ablation null. |
| R.10 | Significance; confidence intervals | MET for the gate and the ablation; NOT for the A/B | Gate: clustered t(26) interval, half-width 0.126, about three times the naive one (forced). Ablation: paired MDE on t(9). The A/B (10 cases) is reported descriptively. |
| R.11 | Guidance for reading results given the flaws | MET, documented | A "reading the number" and a "cannot tell you" paragraph per surface, below: per auditor and never pooled for the ablation; within a set and never across sets for selective answering; descriptively for the A/B. |
| R.12 | Non-AI baselines, such as human experts | NOT MET | No surface has a human baseline; the human floor of validation item 6 needs two raters. |
| R.13 | Results of trivial agents | MET for the gate; NOT for the Council | Gate: the three always-the-same-verdict strategies (forced). Council: no trivial baseline (for example the question restated as a claim) has run; the proposer-only arm is a weaker system, not a trivial one. |

## What each surface measures, and how to read its numbers

Items R.5 and R.11, written 2026-11-23. For each surface: the construct, named narrowly enough to be wrong about;
what it is not; the unit and sample; the confounds the design controls; the error analysis; how to read its
headline number; and what it cannot tell you. Every figure below was re-read from the stored artefact named
beside it on the day this was written.

### The capability gate (`evals/results/gate_eval_8framings.json`, `gate_eval_heldout.json`)

**Construct.** Whether the system declines exactly when the capability registry has no record of what a question
requires, and otherwise answers from the corpus or proposes a run. It is agreement with the registry. It is not
the registry's correctness, and it is not accuracy at answering science questions.

**Unit and sample.** One verdict per question. The bank is 27 situations (a capability in a simulator mode), each
asked in 8 framings: 216 records, but far fewer independent units, because the framings of one situation mostly
agree with each other. The interval is therefore clustered on the situation.

**Confounds controlled.** Wording, by the 8 framings. The key, which is generated from the registry rather than
hand-labelled, with a second, principled key reported beside it. Fitting the benchmark, by a held-out set of 60
items written afterwards and frozen with a hash lock. The decision step on its own, by 16 registry-deletion twins
(16 of 16) that need no model. Guessing, by scoring the trivial strategies on the same records.

**Errors, analysed.** 27 wrong verdicts: 25 too cautious, 2 too permissive. Every one traces to one of two
registered defects: 25 to GATE-8b-C (the parser reads an unstated starvation or amino-acid-supply condition into
the question) and 2 to GATE-8b-D (the gate cannot propose a run in a mode that already has runs). A perfect
parser would score 208 of 216, 0.963.

**Reading the number.** 0.875 (189 of 216) has a clustered 95% interval of plus or minus 0.126, about three
times the naive 0.044. Refusing everything scores 0.556 on the same records, so the margin over the best trivial
strategy is 0.319. The errors are not 27 independent failures: 25 are one defect, and one rule change would
move most of them together. On the held-out set the headline is 45 of 56 (0.804), with 11 errors, 4 of them
answers given where the key says not to (H27, H28, H36, H37). On the 27-item pilot the two keys disagree (0.815
stored, 0.889 principled); on the 216-record run they agree (0.875).

**Cannot tell you.** Whether a registry record is right: a wrong record produces a verdict that scores as
correct. How the gate does on the 9 situations added since the stored run (the registry has 36; 27 were
scored). Which answer is right for the 16 records whose key is disputed, until held-out set v2 is frozen.

### The Council's role ablation (`evals/results/ablation.json`, `ablation_summary.json`)

**Construct.** Whether adversarial deliberation, a skeptic and a judge beside the proposer, produces a
better-operationalised hypothesis than the proposer alone, measured as the defects an independent auditor still
finds in the final hypothesis ("residual defects"; fewer is better).

**Not the construct.** The six-point operationalisation rubric. It scores 6.0 of 6 for `full` and for
`proposer_only` under both judges, and 5.97 at its lowest anywhere: it measures whether the required fields are
present, not how good the framing is. It is not a headline (O.i.1).

**Unit and sample.** 10 cases, 4 arms (`full`, `no_skeptic`, `proposer_only`, `generic_judge`), 3 repetitions:
120 records, 0 errors. Arms are compared case by case, so n is 10.

**Confounds controlled.** The same cases, temperature and graders in every arm; two auditors from different
model families; a minimum detectable effect beside every null (`tests/test_ablation_mde.py`). The answer-key arm
(`leaked`), the positive control, exists in code and has not run.

**Reading a number.** Per auditor, never pooled. Under the Claude auditor `full` leaves 3.37 residual defects
on average and `proposer_only` 4.50, but that auditor is about nine times noisier than the GPT auditor and the
two disagree case by case, so under it no difference between arms is detectable at n = 10. Under the GPT
auditor, removing the critique is detectable. A difference here is a statement about the auditor that scored
it.

**Debate telemetry (stored Council runs, `evals/results/council_telemetry.json`).** Of 43 substantive objections
marked resolved, 2 were resolved with the claim, H1 and H0 word-for-word unchanged. Of 23 runs with a
substantive objection, 1 converged within two rounds anyway. Of 28 converged runs, 0 ended on a draft the judge
had rated below an earlier one. "Unchanged" is measured on the only proposer fields stored per round, so it is an
upper bound on "nothing changed".

**Cannot tell you.** Whether a hypothesis is true or new: no oracle exists, and T.9 is declared out of scope for
this surface. Whether the roles beat the same budget spent on one proposer (validation item 3, a paid run).
What a trivial answer scores (R.13). How a person would grade the same outputs (R.12).

### The Council-versus-Cellwright A/B (`evals/results/ab_ledger.json`)

**Construct.** Whether a hypothesis framed blind (the Council reads no corpus) differs from one framed after
reading the data (Cellwright reads the corpus before committing): the HARKing contrast. The count of corpus
reads is the proxy for having looked.

**Unit and sample.** 25 case cells, one run per arm.

**Reading a number.** Descriptively, case by case. The arms are scored on different instruments, a quality score
for Cellwright and pass-or-fail bars for the Council, so no paired difference or interval exists; and one run per
arm cannot separate the arm from run-to-run variation.

**Cannot tell you.** Which arm is better. The replication with repetitions and one shared rubric is planned
(`docs/PUB_A1_REPLICATION.md`) and is a paid run.

### Selective answering (Platform Map, section 18)

**Construct.** For a system allowed to decline: coverage (the fraction of questions it answered) and risk (of
those it answered, the fraction the selected simulator mode and the available evidence do not support), compared
between systems only at comparable coverage. Risk is not error: a number can be plausible and still unsupported.

**Unit and sample.** Four question sets of different composition: a discrimination set of 9, a capability-grid
pilot of 27, the gate bank of 216, and the held-out headline of 56. Labels for the 9 and the 27 were frozen
before any response, and two independent judges agreed on 9 of 9 and 24 of 27.

**Reading a number.** Within a set, never across sets. On the bank of 216 the gate's coverage is 0.264 and its
risk 0.035 (2 of 57 answers), but 120 of those 216 are keyed refuse, so that coverage is not comparable with any
other row.

**Cannot tell you.** Much at n = 9 or n = 27. One question moves coverage by 0.11 or 0.04, and because risk is
counted over the answered questions only (4 of 9 and 11 of 27 for the language-model arms), one answer moves it
by 0.25 or 0.09. And there is no human reference on any set (R.12).

## What this table changes

Five items are open and cost something to close: O.c.1 and R.12 need human raters and paid judge runs; O.i.1
retires the six-point rubric as a headline; R.13 for the Council needs
one cheap trivial arm; O.b.2 for the Council is one probe. (T.6 was on this list until 2026-11-23, when remote
reads were pinned.) None of them is a property the platform claims today,
and the paper should say so in these words rather than leave the rows blank.
