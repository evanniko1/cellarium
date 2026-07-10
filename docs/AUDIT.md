# Harness audit — code, methodology, conceptual (2026-07-10)

Empirical audit of the Cellarium harness: 17 agent tools, 19 modules, 16 tests. Stress-test (edge cases across
every tool) found **no crashes** and **semantically-correct guardrails** (`screen_design` flags marA up-regulation
but exempts an acrB knockout; `check_feasibility` flags the mid-sim carbon switch; `mechanistic_scope` refuses to
classify an unknown gene; `provenance` tags a KO out-of-sample). Benchmark is authoritative: 402 essential genes
loaded from wcEcoli's own `validation/ecoli/flat/essential_genes.tsv` (Baba/Joyce). Findings below, then the
implementation order (with tests + sim needs).

## Code audit
| # | Sev | Finding | Fix |
|---|---|---|---|
| C1 | low | Viability verdict thresholds duplicated (`_reader_worker.py` mode_viability + `store._viability_verdict`) — currently identical, a DRY *risk* not a live bug. | Extract to one pure `viability_rules.verdict(...)`; import in both; consistency test. |
| C2 | low | `_reader_worker.py` is 729 LOC, container-only, largely un-unit-testable on host. | Move pure aggregation host-side over time. |
| C3 | low | `gene_scope.json` is gitignored + rebuilt manually; `classify_gene` silently uses a stale cache. | Add a version/hash guard + a staleness note in the tool result. |
| C4 | low | `essential_ref` depends on `WCECOLI_DIR`/the validation file at build time; absent ⇒ benchmark silently disabled. | Warn when disabled; document the dependency. |

No injection/crash surfaces; channel names are regex-guarded. The debt is DRY + staleness, not correctness.

## Methodology audit
| # | Sev | Finding | Fix |
|---|---|---|---|
| M1 | **med** | Viability verdict thresholds (0.9 viable / 0.6 inviable) calibrated on **n=1 machinery** (gltX); the "impaired" band is a guess. | Re-calibrate against a machinery + graded-KO panel (**needs sims**). |
| M2 | low | CIs use normal-approx `1.96·SE` (survey + rigor), not the t-distribution; for n=4–8 seeds ~20–60% too narrow, `\|t\|≥2` slightly liberal. | Use `scipy.stats.t` (already a dep). |
| M3 | low | Survey z-score uses population stdev across few designs — `\|z\|≥2` weakly grounded in a small corpus. | Note the caveat; consider robust z / min design count. |

Strengths: Benjamini-Hochberg FDR on `top_movers`, correct Welch SE, seed-averaging + count-floor + reproducibility
on `differential`. Core statistics are sound; gaps are small-n refinements.

## Conceptual audit — what Coli can't reason about
| # | Sev | Gap |
|---|---|---|
| F1 | **HIGH** | **No design-space awareness** — can't enumerate runnable conditions / variant types / valid gene-KO indices (`variant_map` is cached but not a tool). Blocks "generate hypotheses + run sims" (it would guess indices). |
| F2 | **med-high** | **No one-step hypothesis vetting** — vet-before-run (feasibility + provenance + scope + viability-prior + biosecurity + power) is manual chaining. |
| F3 | med | **No model-validation summary** — essentiality agreement vs the 402-gene ground truth (a `model_UNDER_predicts` rate) so Coli can calibrate trust in a verdict. |
| F4 | med | **No power guidance** — "is this comparison powered / how many seeds needed." |
| F5 | low | **Integration polish** — viability not in `survey` CHANNELS; `reroute_diagnosis` not in the agent KO-prompt. |
| F6 | — | **Boundary (by design):** `run_experiment` doesn't launch sims — Coli reasons over the existing corpus only; new data needs an offline campaign. This is *why* F1/F2 matter. |

## Recorded roadmap vs feasibility
| Item | Feasible? | Sims? | Note |
|---|---|---|---|
| P3.1 order-randomization + self-consistency | yes | no | Reasoning-layer, token-costly; hardens the analyst, not the design-space blindness. |
| P3.2 heterogeneous adversarial pass | yes | no | Token-costly; gate to high-stakes. |
| P4.2 metabolic-essentiality verdict (EcoCyc oracle) | yes | no | **Lower value than recorded** — the 402-gene benchmark already covers the binary verdict. |
| P4.2 multi-gene reduced-genome generator | yes | **yes** | `multi_gene_knockout` variant exists. **Deprioritized (may not ship).** |
| P4.2 ML surrogate | yes | **yes** | Data-hungry; downstream of the reduced-genome campaign. **Deprioritized (may not ship).** |

## Implementation order
No new sims are needed for any priority item — only M1 (and the two deprioritized items).

1. **F1 — design-space enumeration tool** (HIGH · no sim). Expose conditions + variant types + gene→ko_index.
   *Test:* returns conditions and resolves a known gene to its ko_index; unknown gene → graceful.
2. **F5 — integration polish** (low · no sim). Add `division_rate` to `survey` CHANNELS; add `reroute_diagnosis` to
   the agent KO-guidance. *Test:* survey ranks `division_rate`.
3. **C1 — DRY the viability verdict** (low · no sim). `viability_rules.verdict(...)` shared by worker + store.
   *Test:* both call sites agree across the three regimes.
4. **M2 — t-distribution CIs** (low · no sim). `scipy.stats.t` in survey + rigor. *Test:* CI wider than the normal
   approx at n=4.
5. **F2 — hypothesis-vetting tool** (med-high · no sim · needs F1). One `vet_hypothesis` go/no-go composing the
   guardrails. *Test:* flags out-of-envelope + biosecurity; passes a clean in-envelope design.
6. **F3 — model-validation summary** (med · no sim). Corpus essentiality agreement vs the 402-gene benchmark.
   *Test:* returns counts for the four agreement classes; `model_UNDER_predicts` includes fabI/glmS/gltA.
7. **F4 — statistical-power guidance** (med · no sim). Seeds-needed estimate for a target effect. *Test:* more
   seeds required for a smaller effect.
8. **M1 — calibrate the viability thresholds** (med · **NEEDS SIMS**). Offline panel: more machinery KOs (rpoB,
   rplA, an aaRS) + graded KOs, then fit 0.9/0.6 empirically.
9. **P3.1 / P3.2** — analyst-robustness (token-costly; gate to final conclusions).
10. **P4.2 EcoCyc oracle** (optional; lower value; needs EcoCyc data access, no sim).

**Deprioritized (may not ship in the hackathon):** multi-gene reduced-genome generator, ML surrogate.
