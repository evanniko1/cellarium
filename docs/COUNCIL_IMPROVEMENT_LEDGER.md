# Socratic Council — improvement workstream & defect ledger

**Goal.** Go step-by-step through the Council's proposer / skeptic / judge on the ten debate cases
(`evals/results/debate/PXX.md`) and localize where the three roles fail *together*, so we can improve how they
work as a unit — not just the output hypothesis.

**Method.** Two evidence streams:
1. **Retrospective** — the `PXX` debate files show each finished operationalization and an adversarial
   cross-examination that surfaces its concrete defects. The *shape* of the surviving hypothesis tells us where
   each role spent its effort.
2. **Process (faithful hand-run)** — the Council's real per-round transcript is *not* stored (`ablation.json`
   keeps only counts: `rounds_used`, `substantive_objections`, `converged`). So for a case we re-run the
   deliberation **by hand, in-conversation, under the exact role charters and the information quarantine (dial
   labels only) — no API, no `council.py`**, and read the proposer→skeptic→judge dynamics directly.

Status: **P08 done** (below). Next: P01. One case at a time.

**Structured issues registry:** [`docs/council_issues.yaml`](council_issues.yaml) — the machine-gatherable
list of discrete issues (id / severity / roles / symptom / root cause / per-role fix / status), built to be
aggregated across all cases for a single architecture-refinement pass. This document is the narrative companion.

---

## Cross-cutting defect ledger

Each defect: what it is · where first seen · root cause · which role should own the fix.

### D1 — Claim ↔ falsifier hypothesis-identity confusion *(most serious)*
**What.** The hypothesis never commits to a single H1. In P08 three incompatible framings coexisted:
(A) "a **non-trivial** fraction is dispensable" vs a **≈0%** null; (B) "**10–20%** dispensable" (an interval);
(C) "a **minority** (<50%) are dispensable." The proposer *narrated* C, *predicted* B, and *built the decision
rule* for A. The single rule `reject if <3/30 nonessential` is a coherent test of **A only** — it is *half* a
test of B and the **wrong-tailed (inverted)** test of C: under "minority," the negation is "a **majority** are
dispensable" (p ≥ 0.5, ≥15/30), yet the rule rejects H1 at p < 0.10 — *deep inside the region where C is true.*
So the rule declares H1 false exactly where H1 is most obviously true.
**Root cause.** The schema lets `claim`, `predicted_effect`, `h0`, and `falsifier.refuting_result` be filled
**independently**; nothing forces them to describe the same quantity *p* and the same direction. Anchoring the
null at the bottom (≈0%) points all the test machinery at the lower tail while the prose drifts to an
upper-bounded ("minority") claim.
**Fix owner.** Proposer must emit one internally-consistent hypothesis; skeptic must run a standing
`claim ↔ falsifier` directional-consistency check; judge must gate that the refuting region is the logical
negation of the claim (see role fixes below).

### D2 — Interval claim, one-sided rule (unguarded far bound)
**What.** H1 claims the bounded interval "10–20%" (= 3–6 of 30) but the rule only rejects from **below**
(`<3/30`). A result of 15/30 (50%) violates "10–20%" yet **passes** the stated rule. The claim is only half
falsifiable. Present in the *shipped* P08 hypothesis too (its falsifier guards `<3/30` and the positive
controls — both lower/validity-facing; no upper guard).
**Why the upper guard matters.** A too-high dispensable fraction is the *more diagnostic* failure: it both
refutes the interval **and** is the signature of the **model-artifact rival** (the simulator can't properly kill
cells). Omitting it weakens two things at once.
**Fix.** Two-sided rule against the claim: *reject H1 if the 95% binomial CI for p excludes [0.10, 0.20]* — and
treat a significantly-high fraction as also tripping the model-validity check.
**Fix owner.** Proposer (guard both bounds, or rewrite the claim to a one-sided form); judge (consistency gate).

### D3 — Severity mis-classification: construct-validity flaw parked as a "concession"
**What.** P08 mapped the *relational* construct "live **without**" onto an **absolute** viability floor
(`growth_rate > 0.05 /h`), which labels a strain growing ~12× slower than wildtype "dispensable." The debate
judged this the decisive defect (Council **lost** the case). Crucially the Council **half-caught it** — its
Concession #1 states "the 0.05 /h threshold is pragmatic, not canonical … sensitivity analysis … is not
included" — but **parked it as a pragmatic caveat instead of treating it as a rubric-breaking flaw.** The judge's
convergence rule explicitly lets parked auxiliaries/refinements not block convergence, so the weaker hypothesis
shipped. The failure is *severity classification*, not a missing capability: a faithful hand-run's skeptic **does**
fire `conflated_construct` at the primary measure and the proposer then fixes it (two-tier + sensitivity sweep).
**Fix owner.** Skeptic (a faithfulness failure on the *primary* measure is always `substantive`, never `minor`);
judge (a construct-faithfulness flaw cannot be parked to reach convergence).

### D4 — Relational construct → absolute measure default
**What.** For comparative constructs ("live **without**", "**noisier** than", "behave **differently**") the
proposer reaches for an absolute threshold rather than a **wildtype-normalized** one. "Without X" is inherently
relative to *having X*.
**Fix owner.** Proposer: default to a normalized measure + a threshold **sensitivity sweep** for relational
constructs; commit to one absolute cutoff only with justification.

### D5 — Falsifier schema friction: pairwise slots can't express a screen
**What.** `falsifier.target` / `.reference` hold a **single** design pair (built for one `disconfirm()` call),
but a genome-wide question needs a **loop over a panel** of ≥30 knockouts aggregated into a fraction. The panel
gets smuggled into the `decision_rule` prose. Schema (pairwise) and question (population-scale) mismatch.
**Fix owner.** Architecture: a first-class "screen" falsifier that takes a design **set** and an aggregation
rule, so population-scale tests are structured, not prose.

### D6 — Systemic: over-investment in armor, under-examination of the primary mapping
**What.** Across P08 the Council spends its effort (and the skeptic's capped ≤3 objection budget) on **defensive
armor** — positive controls, extra rivals, an explicit auxiliary belt — while the **decisive flaw sits in the
primary construct mapping** (the threshold). Good rigor aimed at the perimeter; the centre goes unchecked.
**Fix owner.** Skeptic ordering (faithfulness-first, below) is the lever.

---

## Per-role improvement summary (accumulating)

**Proposer**
- Emit **one internally-consistent hypothesis**: `claim`, `predicted_effect`, `h0`, and
  `falsifier.refuting_result` must all describe the **same magnitude p and the same direction** (fixes D1).
- **Interval/bounded claims guard both bounds** (or rewrite to a one-sided claim) (fixes D2).
- **Relational constructs → wildtype-normalized measure + threshold sensitivity sweep** (fixes D4).

**Skeptic**
- **Faithfulness-first pass:** rule on the **primary** operationalization *before* objecting to rivals /
  feasibility; a faithfulness failure on the primary measure is **always `substantive`** (fixes D3, D6).
- Standing **`claim ↔ falsifier` directional-consistency** objection (`unfalsifiable`/`conflated_construct`):
  does the refuting region actually negate the claim, and cover every asserted bound? (fixes D1, D2).

**Judge**
- Add gated rubric item **`faithful`**: no strictly-more-faithful mapping of the construct is available (or a
  sensitivity analysis brackets the threshold) — and it **cannot be parked** to reach convergence (fixes D3).
- Add **`claim–falsifier consistency`**: the refuting region is the logical negation of the claim, and every
  bound asserted in the claim has a corresponding refuting condition (fixes D1, D2).

**Architecture / schema**
- First-class **screen falsifier** over a design set (fixes D5).

---

## Case log

### P08 — "Which genes can E. coli live without?"  (Council **lost** the debate)
Faithful hand-run converged in 2 rounds; the honest skeptic **does** fire `conflated_construct` at the 0.05 /h
threshold and the proposer fixes it (two-tier viability/dispensability + sensitivity sweep + positive-control
validity gate) — producing a hypothesis **stronger** than the single-shot agent. The shipped rep-0 hypothesis
lost because the same flaw was **parked as a concession** rather than fixed (D3). Falsifier also exhibits D1
(claim/rule identity confusion), D2 (one-sided interval rule), D5 (screen smuggled into pairwise slots).
Defects surfaced: **D1, D2, D3, D4, D5, D6.**
