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
| MET, guarded by a test that was forced to fail | T.5, T.9 (gate), T.10, O.b.3, R.9, R.10 (gate), R.13 (gate) |
| MET, documented or by construction | T.2, T.4, O.h.1, O.h.2, R.1, R.2, R.3, R.6, R.7, R.8 |
| PARTLY | T.1, T.3, T.6, T.7, T.8, R.4, R.5, R.11 |
| NOT MET, open | O.c.1, O.i.1, R.12; and for the Council: R.10, R.13, O.b.2 |
| OUT OF SCOPE, declared | T.9 for the Council: no oracle exists for an open-ended hypothesis |
| NOT APPLICABLE, with the reason | O.a.1-2, O.b.1, O.d.1-2, O.e.1-3, O.f.1-2, O.g.1-3 |

## Task validity

| ID | Item (paraphrased) | Status | Evidence, and what is missing |
|---|---|---|---|
| T.1 | Specify tool and package versions for self-hosted tools | PARTLY | The simulator's image digest and knowledge-base hash are recorded per run (`provenance.py`), and every eval artefact records the model id. Python dependencies are ranges, not pins, and the registry-mutation plan predicts that loosening one goes unnoticed (mutant R1). |
| T.2 | API availability; manage rate limits | MET, documented | Every eval path uses the client with retries and backoff (`llm.client(max_retries=4)`); a parser that returned nothing is recorded, not retried silently. |
| T.3 | Detect API interruptions; stop and inform | PARTLY | A failed call becomes an explicit record and is counted (`no_verdict` in the gate's error count since 2026-11-23). The harness does not stop on a burst of failures. |
| T.4 | Clean state before each task | MET, by construction | One stateless parse and decision per gate item; a fresh `deliberate()` per Council case; a fresh session per A/B case. |
| T.5 | Isolate agents from ground truth | MET, forced | The Council never sees corpus readings (`tests/test_blindness.py`). Its literature search is blocked from the dataset hosts and every URL it saw is audited (`tests/test_blind_external_reads.py`); a brief from a breached search is discarded and the A/B scorer refuses the run. Forced: with the block list emptied the leak reaches the proposer. Not covered: what the model already knows from training (PUB-A4). |
| T.6 | Environment frozen at release, not dynamic | PARTLY | Simulator and knowledge base are hashed per run. The remote corpora are read at the Hub's current revision: the registry records the revision measured (well4cell 4ab4aa37, 2026-11-21), but reads do not pin it. Open. |
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
| O.d.1, O.d.2 | Unit-test grading: tests verified; coverage reported | N/A as grading | No evaluation is scored by unit tests. The analogous question, whether the platform's own guard tests would notice a fault, is measured by mutation testing: threshold mutants (tier 0) and the registry operators of validation item 8. |
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
| R.5 | Relationship between capabilities and outcomes stated | PARTLY | `run_gate_eval.py` states its construct: whether the system declines exactly when the registry lacks a capability, not "accuracy". A construct statement per surface is not yet written for the paper. |
| R.6 | The evaluation subject stated | MET | Every artefact records the model ids and the harness. |
| R.7 | Steps to prevent, find and fix flaws | MET | The GATE-8b ledger, the Platform Map audit, mutation testing, the conformance families, this table. |
| R.8 | Qualitative discussion of unavoidable flaws | MET | Limits are stated in each module and in the Platform Map. |
| R.9 | Quantitative analysis of flaws | MET, forced | The principled-key sensitivity (pilot 0.815 against 0.889); the complete error count and its attribution (25 + 2; oracle ceiling 0.963); a minimum detectable effect beside every ablation null. |
| R.10 | Significance; confidence intervals | MET for the gate and the ablation; NOT for the A/B | Gate: clustered t(26) interval, half-width 0.126, about three times the naive one (forced). Ablation: paired MDE on t(9). The A/B (10 cases) is reported descriptively. |
| R.11 | Guidance for reading results given the flaws | PARTLY | The Map says the ablation must be read per judge and is underpowered; a reader's guide per surface is not written. |
| R.12 | Non-AI baselines, such as human experts | NOT MET | No surface has a human baseline; the human floor of validation item 6 needs two raters. |
| R.13 | Results of trivial agents | MET for the gate; NOT for the Council | Gate: the three always-the-same-verdict strategies (forced). Council: no trivial baseline (for example the question restated as a claim) has run; the proposer-only arm is a weaker system, not a trivial one. |

## What this table changes

Six items are open and cost something to close: O.c.1 and R.12 need human raters and paid judge runs; O.i.1
retires the six-point rubric as a headline; T.6 needs remote reads pinned to a revision; R.13 for the Council needs
one cheap trivial arm; O.b.2 for the Council is one probe. None of them is a property the platform claims today,
and the paper should say so in these words rather than leave the rows blank.
