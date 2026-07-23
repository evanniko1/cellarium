# PUB-A1 — Replication plan for the headline A/B

**Goal.** Turn the Council-vs-Cellwright comparison from an **n=1 anecdote into a powered, error-barred result**, so the paper's load-bearing claim (a blind Socratic dialectic adds scientific value over a single grounded pass) is defensible under review. This is the #1 publication-readiness gate the adversarial audit (`wf_57388055`) identified.

## First, a critical scope clarification (this is NOT memory-bound)

There are **two different Phase-2 activities**, and the memory/disk concern applies to only one:

| Activity | What it runs | Bound by |
|---|---|---|
| **PUB-A1 replication** *(this doc)* | `run_ab` — the Council (blind LLM debate) + Cellwright (reads the **existing** corpus). **No new sims.** | **API cost + rate limits.** Light on local RAM/disk. |
| **Growing the corpus** *(DD-SCI-5a etc.)* | wcEcoli Docker **sim sweeps** — ~1 GB raw + ~1-2 GB RAM per parallel worker | **RAM + disk.** This is where chunking + the new `estimate_sim_resources` guard matter. |

So PUB-A1 is **safe on this machine memory-wise** — it reads the corpus and makes model calls; it doesn't launch the simulator. The blocker for PUB-A1 is simply that **`ANTHROPIC_API_KEY` is not set** (and, for the cross-family judge in PUB-A2, `OPENAI_API_KEY`). The "manageable chunks" for PUB-A1 are about **API budget + resumability**, not RAM.

## Design

1. **Replicates.** Run each of the ~14 canonical cases **k times per arm** (start `k=5`; `k=8-10` if the API budget allows). Extend `run_ab.py` with `--reps N` (loop each case N times, tag each row with `rep`), or wrap it. Council temperature is already pinned (`DD-MTH-2`), so the replicate variance is the *sampling* variance we want to measure, named and reproducible.
2. **A comparable metric.** The two arms currently report *different* things. Fix a **single graded endpoint scored identically for both arms** (the ablation's 6-criterion operationalization rubric in `evals/ablate.py` applied to each arm's final hypothesis/answer), plus the deterministic structural floor (`grade.py:37-59`). Report *that* metric per arm, per rep.
3. **The judge (coordinate with PUB-A2).** Do **not** decide passes with a single same-family Opus judge. Score each hypothesis with a **pre-registered cross-family panel** (≥2 judges from different model families, e.g. Opus + GPT-4o + one more), report **inter-rater reliability** (Krippendorff's α / Cohen's κ), and **human-validate a subset** (`evals/human_packet.py` already builds the blinded packet). Pin every judge's temperature; where a reasoning model forces temp=1, sample the judge **m=3** times and majority-vote (record the vote spread).
4. **Statistics + error bars.** Per case × arm: mean ± 95% CI of the metric across the k reps (case-clustered — reps within a case are not independent of the case). Compare arms with a **paired test at the case level** (Wilcoxon signed-rank on the per-case arm means, or a mixed-effects model: `metric ~ arm + (1|case)`), and report the **effect size + CI**, not just a p-value. Because the primary rubric may saturate (`PUB-A3`: it scored ~6/6 for every config, Wilcoxon p=1.0), **pre-register a discriminating secondary endpoint** (e.g. the audit's residual-defect metric in `evals/audit.py`, or falsifier-quality) as the real comparison.
5. **Blindness caveat (`PUB-A4`).** Scope the claim to what's genuinely out-of-sample to the model's weights. **Timestamp-lock the rubric** (commit + tag it before running) to kill the hindsight-shaping concern, and separate the ~23/25 cases whose answer the model already knows from the genuinely-unknowable sim-vs-textbook divergences (argS etc.), which are the honest core.

## Execution — in manageable (API) chunks

Prereqs on **your** machine: `export ANTHROPIC_API_KEY=...` (and `OPENAI_API_KEY` for the cross-family judge). No Docker needed.

Chunk by **case-batch with checkpoint/resume** so a rate-limit or a laptop sleep never loses work and the spend is paced:

```bash
# implement `--reps` first (see below), then, e.g., 5 reps, cases in batches of ~3:
python evals/run_ab.py 1.1 4.1 4.2 --reps 5 --out evals/results/ab_rep.json     # batch 1
python evals/run_ab.py 5.2 5.3 5.5 --reps 5 --out evals/results/ab_rep.json     # batch 2  (append)
# ... continue; --force only to overwrite. run_ab already persists incrementally per row.
python evals/aggregate_ab.py evals/results/ab_rep.json                          # per-case mean±CI + the paired test
```

**Budget estimate (rough).** ~14 cases × 5 reps × 2 arms ≈ 140 arm-runs; a Council deliberation is ~4 rounds × 3 roles ≈ 12 calls, a Cellwright arm ~10-20 tool-turns. Order ~2-4k model calls → hours of wall-clock and a real (but modest) API bill. Chunking by case-batch keeps each session bounded and resumable.

## Implementation steps (code owed, all offline-testable except the live run)

- [ ] `run_ab.py --reps N` + a `rep` tag on each persisted row (small; the per-row persistence already exists).
- [ ] A shared graded endpoint applied to **both** arms (reuse `ablate.py`'s rubric + the structural floor).
- [ ] `evals/aggregate_ab.py` — per-case mean±CI, case-clustered, + the paired test + effect size (pure stats; unit-testable now with synthetic rows).
- [ ] Cross-family judge panel + IRR (PUB-A2) — pre-registered.
- [ ] Timestamp-lock the rubric (PUB-A4).

The **aggregation + `--reps` plumbing can be built and unit-tested now** (no key needed); only the live sweep needs the API key on your machine.
