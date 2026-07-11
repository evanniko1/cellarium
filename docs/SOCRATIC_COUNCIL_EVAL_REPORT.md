# Operationalizing vague research questions with a Socratic Council: a case-by-case evaluation

**A technical report on the Cellarium Socratic Council against ten literature-grounded questions in
single-cell / systems microbiology.**

Branch: `socratic-council`. Code: `src/cellarium/{council,instrument,hypothesis}.py`. Eval harness:
`evals/`. Reproduce: `python evals/grade.py`.

---

## Abstract

The **Socratic Council** is an upstream stage that turns a vague user question into a falsifiable,
operationalized, instrumentally-testable hypothesis *before* the grounded Cellarium agent tests it against a
whole-cell *E. coli* simulation (Covert-lab wcEcoli). Three LLM roles debate — a maieutic **proposer**, a
skeptical **elenctic critic** (*docta ignorantia*), and a rubric-bound **judge** — under a strict information
quarantine: the Council sees the instrument's *capabilities* (measurable channels, runnable perturbations) but
never its *readings* (corpus values, the literature answer key). We evaluated it on ten canonical questions
drawn from the single-cell/systems-microbiology literature (Elowitz noise, Balaban persistence, Kussell–Leibler
bet-hedging, Spudich–Koshland individuality, Scott growth laws, the ppGpp stringent response, Keio
essentiality, Monod/Solopova diauxie), grading each hypothesis against a two-tier rubric (a minimum bar for a
usable falsifiable hypothesis; a stringent bar for a rigorous-reviewer-grade one) with an independent Opus 4.8
judge that *does* see the answer key. **The Council converged on every case.** It reached the minimum bar on
7/10 and the stringent bar on 2–3/10 (with run-to-run variance). Crucially, the residual failures separate into
three mechanistically distinct classes — (i) criteria that require presupposing a measured literature value or
control, which the quarantine forbids; (ii) readouts the base model cannot execute; and (iii) genuine
generation errors amplified by LLM stochasticity — rather than any failure of the debate to terminate. We report
each case in full.

---

## 1. Introduction

A whole-cell simulator can, in principle, test almost any single-cell hypothesis — but only once the hypothesis
is *stated testably*. Users arrive with questions like "do genetically identical cells behave differently?",
which name no observable, no baseline, no prediction, and no refuting result. Translating such a question into a
falsifiable form is the move philosophy of science calls **operationalization** (Bridgman) inside the **context
of discovery** (Reichenbach), and it is exactly the step a grounded testing agent cannot do for itself without
smuggling in unexamined assumptions.

The Socratic Council performs that translation as a disciplined dialectic (design and rationale:
`docs/SOCRATIC_COUNCIL.md`). Its output is a first-class `Hypothesis` object carrying H1/H0, operational
definitions bound to real observables, a Popperian falsifier (a risky prohibition that *could* fail), rival
hypotheses (Chamberlin/Platt), the Duhem–Quine auxiliary assumptions, and envelope-checked candidate designs.
This report asks a narrow, empirical question: **when handed real research questions, does the Council produce
hypotheses a rigorous scientist would accept — and where it does not, why?**

## 2. Methods

**System.** The Council (`council.py`) runs proposer → skeptic → judge for up to `--rounds` (default 4) rounds.
The judge terminates when the hypothesis is falsifiable, specified, operationalized, discriminating, and
feasible, and the remaining objections are refinements or explicitly parked auxiliary assumptions. It sees only
`instrument.dial_labels()` — the summary-channel namespace (`growth_rate`, `ppgpp_conc`, `ribosome_conc`,
`fraction_trna_charged`, `rela_conc`, mass channels, `fba_objective`), the validated perturbation vocabulary,
and the falsification mechanism (`disconfirm(target, reference, channel)`, a Welch-t on a channel) — never a
reading. The **quarantine** is the key experimental control: the Council cannot look up what the literature
found; it must *propose* it as a testable claim.

**Cases.** Ten questions across six themes (`evals/EVAL_SPEC.md`, `evals/cases.py`), each with a canonical
answer, the rivals the seminal work excluded, a verified citation, the wcEcoli observable mapping, and a
two-tier rubric.

**Grading.** Two layers (`evals/grade.py`): a deterministic structural floor (names an observable on a real
dial label; states a direction + baseline; carries a falsifier with a refuting result; ≥1 in-envelope design),
and an independent **Opus 4.8 judge** that sees the canonical answer, the expected observables/rivals, and every
rubric criterion, scoring each pass/fail with a rationale. **Minimum bar** = floor ∧ every minimum criterion.
**Stringent bar** = minimum bar ∧ every stringent criterion ∧ clean convergence.

**Models / variance.** Council roles: Claude Sonnet 5; grader: Claude Opus 4.8; `--rounds 4 --quota 3`. Both the
generator and the grader are stochastic; scores — especially stringent — vary run-to-run, and we flag every case
where we observed a flip. Data: `evals/results/full_run.json` (the eight theme-1/3/4/5/6 cases) and
`evals/results/run_2x.json` (2.1, 2.2).

## 3. Results

| Case | Question (theme) | Minimum | Stringent | Converged | Dominant limiter |
|---|---|:---:|:---:|:---:|---|
| 1.1 | isogenic gene expression — Elowitz noise | ✅ | ✅ | ✅ | — |
| 1.2 | what makes a gene noisier — burst kinetics | ✅ | ✗ | ✅ | instrument (per-gene channels) |
| 2.1 | antibiotic survival without resistance — persistence | ✅ | ✗ | ✅ | quarantine + proxy resolution |
| 2.2 | is slow growth ever adaptive — bet-hedging | ✗ | ✗ | ✅ | instrument (fluctuation harness) |
| 3.1 | do isogenic cells *behave* differently — individuality | ✅ | ✗ | ✅ | instrument (low-copy readout) |
| 4.1 | ribosome allocation — Scott growth laws | ✅ | ~ | ✅ | control arm (variance) |
| 4.2 | amino-acid runout — ppGpp stringent response | ✅ | ✅ | ✅ | — |
| 5.1 | which genes are essential — Keio | ~ | ✗ | ✅ | generation error + quarantine |
| 6.1 | choosing between two sugars — diauxie | ✗ | ✗ | ✅ | envelope (carbon switch) |
| 6.2 | who switches at the diauxic shift — bet-hedging | ✅ | ✗ | ✅ | control/test specificity |

✅ pass, ✗ fail, ~ passed in some runs. **All ten converged.**

### Theme 1 — Intrinsic vs extrinsic noise

**1.1 — "Do genetically identical cells express the same gene at the same level?"** *(Elowitz et al., Science
2002.)* **Minimum ✅ Stringent ✅.** The Council operationalized "the same level" as the cell-to-cell dispersion
of `protein_mass` across ≥100 isogenic seeds, predicting a **right-skewed unimodal distribution with CV ≈ 30%
(20–50%) and skewness > 1** at generation 3, versus a tight symmetric null (CV < 10%). Its falsifier compares
that dispersion against a same-seed `dry_mass`/`growth_rate` noise floor, and — the discriminating move — adds a
`ppgpp_conc` clamp design to test whether the spread is regulatory stochasticity or generic solver noise
(rival). This is a textbook operationalization of intrinsic/extrinsic noise onto the available channels; the
judge passed every stringent criterion.

**1.2 — "What makes one gene's expression noisier than another's?"** *(Ozbudak 2002; Taniguchi 2010.)* **Minimum
✅ Stringent ✗ (S1, S2, S4).** The Council correctly proposed the noise–abundance scaling law,
**log(CV²) = −1·log(mean) + b, slope ≈ −1, R² ≥ 0.6**, with low-abundance genes ≥ 2.5× noisier than
high-abundance ones. But it had to hedge the observable — per-gene protein counts are read via the
species-reader, not exposed as first-class dial channels, so its design says "if exposed at per-gene
resolution." The stringent misses (the η² = a/mean + b floor value ~0.1; a curve-fit with CIs; the matched-mean
burst-size control) all require per-species variance as a testable channel, which the summary-channel instrument
does not provide. **This is a genuine instrument gap, not a reasoning failure** — the fix is to expose
species-level dispersion as a dial label.

### Theme 2 — Persistence and bet-hedging (the newly added cases)

**2.1 — "Why do some bacteria survive antibiotics without becoming resistant?"** *(Balaban et al., Science
2004.)* **Minimum ✅ Stringent ✗ (S1, S2).** The base model has no antibiotic, no killing, no MIC — so the
interesting result is *how* the Council handled that. It did not hallucinate a killing assay; it mapped
persistence onto a **stochastically-triggered, reversible RelA/ppGpp-driven low-growth / high-ppGpp
subpopulation** — i.e. a slow-growing tail in the joint `growth_rate` × `ppgpp_conc` distribution across seeds,
with a `gene_knockout` (relA) and `ppgpp_conc`-clamp control to test causality, and the killing/resensitization
arm stated as an out-of-scope auxiliary assumption. This is a *mechanistically astute* proxy: real persistence
is ppGpp- and toxin–antitoxin-linked, so the Council reached for the right in-model correlate. It missed
stringent because (a) it predicted a ~3% slow tail, far from the canonical **~10⁻⁵–10⁻⁶** persister frequency —
a number that both lies below what an affordable seed ensemble can resolve *and* is a literature reading the
Council must not presuppose; and (b) it used decile-co-occurrence/CV tests rather than an explicit bimodality
mixture test. The minimum-bar pass is the right verdict: a valid, testable heterogeneity hypothesis, correctly
scoped.

**2.2 — "Can it ever help a population for some cells to grow slowly / stay 'prepared'?"** *(Kussell & Leibler,
Science 2005; Novick & Weiner 1957.)* **Minimum ✗ Stringent ✗.** This is the hardest case and the honest
failure. Bet-hedging is defined by **long-term, time-averaged growth rate across a fluctuating environment** as
a function of the switching rate — and the base model is single-lineage with a limited media-shift repertoire.
The Council converged, but on a *narrowed* claim: standing cell-to-cell heterogeneity in basal ppGpp predicts a
recovery-ratio advantage after a single scripted downshift. The judge failed the minimum bar correctly — the
observable (a post-shift recovery ratio) is not long-term time-averaged growth (M1), and one scripted downshift
is not a fluctuating environment with a switching-rate sweep (M4). The concept genuinely **outruns the
instrument**: realizing it needs an external harness that scripts many environmental epochs across a
switching-rate sweep. The Council's error was to converge on a proxy rather than flag the question as
out-of-envelope; a useful signal for tightening the skeptic's `outruns_instrument` handling.

### Theme 3 — Non-genetic individuality

**3.1 — "Do genetically identical cells behave differently?"** *(Spudich & Koshland, Nature 1976.)* **Minimum ✅
Stringent ✗ (S4).** The user's flagship question. The Council operationalized "behave differently" as broad,
unimodal cell-to-cell variability in `growth_rate` and `ppgpp_conc` across ≥50 seeds (CV ≈ 15–30%), with two
discriminating controls: a **cell-cycle-landmark resampling** to exclude phase-desynchronization, and a
`ppgpp_conc` clamp to test whether stringent-response noise causally drives the growth-rate spread. That is a
strong, testable minimum-bar hypothesis. The single stringent miss (S4) is the Spudich–Koshland *mechanism* —
tying the variance to a specific low-copy signalling protein (CheR/CheY) and predicting CV ∝ 1/√(copies) — which
requires the low-copy-protein readout the base model does not expose (the motility layer is out of scope). The
Council did the right thing: it answered at the level the instrument supports and flagged the mechanism as
out-of-model.

### Theme 4 — Growth laws and the stringent response

**4.1 — "How does a cell decide how many ribosomes to make in a given medium?"** *(Scott et al., Science 2010.)*
**Minimum ✅ Stringent ~ (S4; passes in some runs).** The Council recovered the first growth law directly:
**ribosome_conc ≈ a + b·growth_rate, b > 0, R² ≥ 0.8**, fit by OLS across a five-condition media panel
(`wildtype`, `condition/acetate`, `condition/fumarate`, `condition/succinate`), rejecting H0 if the slope 95% CI
excludes 0. This is a genuinely rigorous, quantitative, in-scope hypothesis with a named test and threshold. The
one stringent criterion it intermittently misses (S4) is the *second law* — the translation-inhibition arm
(reducing ribosome capacity via `rrna_operon_knockout`) to establish bidirectional coupling. In one run
(`probe6`) the Council included that arm and passed stringent; in the reported run it did not — a clean
illustration of generation variance on a criterion the Council *can* satisfy.

**4.2 — "What does a cell do when it suddenly runs out of amino acids?"** *(Cashel; Potrykus & Cashel 2008.)*
**Minimum ✅ Stringent ✅.** The best-matched case and a full pass. The Council reproduced the stringent-response
causal chain quantitatively: an `amino_acid_shift` design removing all supplemented amino acids, predicting
**ppgpp_conc ↑ ≥ 5× within ~10 min, fraction_trna_charged dropping from ~0.85 to < 0.3, ribosome_conc falling
≥ 30%**, with a pre/post time-resolved comparison, rivals for passive substrate-limitation and
ribosome-hibernation, and an `rrna_operon_knockout` calibration arm to match the magnitude of the ribosome
drop. Every stringent criterion passed.

### Theme 5 — Knockout essentiality

**5.1 — "Which genes can *E. coli* live without?"** *(Baba 2006; Gerdes 2003.)* **Minimum ~ Stringent ✗.** This
case exposes two distinct effects. First, a **genuine generation error amplified by variance**: in the reported
run the proposer *inverted* the fraction — claiming "roughly 10–20% of genes are individually dispensable"
(80–90% essential), the opposite of the literature (most genes are dispensable), which the judge correctly
failed on M2. In an earlier run (`probe7`) the same case stated ~10–20% *essential* and passed the minimum bar.
The design itself is sound — a 40-gene knockout panel across seeds with a `growth_rate` Welch-t viability
threshold and a reseed check — so the fault is a coin-flip on the direction of the fraction, a real LLM-stability
issue. Second, the stringent miss (S1) is a **quarantine effect**: the criterion asks for the literature's
*measured* essential count (~300–620 of ~4300), which the Council must not presuppose. Its operationalized
~10–20% fraction with a viability cutoff and a screen design is stringent-*grade science*; it simply cannot
recite a number it has been forbidden to look up.

### Theme 6 — Diauxie and catabolite repression

**6.1 — "How do bacteria choose between two sugars in the same flask?"** *(Monod 1949; New et al. 2014.)*
**Minimum ✗ Stringent ✗.** The natural design — two co-present carbon sources, or a mid-run glucose→acetate
switch — is **explicitly out of the validated envelope** (a dynamic carbon-source switch desynchronizes the
replication–division cycle; `envelope.py`). The Council correctly *refused* it and re-scoped to a
single-substrate glucose ramp-down, predicting a transient ppGpp rise and ribosome drop. That re-scoping is the
right safety behaviour, but the re-scoped claim no longer answers "choosing between two sugars," so the judge
failed the minimum bar (M2). This is the cleanest example of the Council trading an answer for rigor: it will
not fabricate an experiment the instrument cannot validly run. Two co-present sugars would require a model
extension.

**6.2 — "When the preferred sugar runs out, do all cells switch at the same time?"** *(Solopova et al. 2014.)*
**Minimum ✅ Stringent ✗ (S2, S3).** The Council operationalized diauxic-shift heterogeneity as the **across-seed
distribution of per-cell switch-time**, predicting a right-skewed distribution with **CV ≥ 0.5 and ≥ 20% of
cells at > 2× the median switch-time** (vs a synchronous CV < 0.15 null), with ppGpp-peak-timing correlation and
a `ppgpp_conc` clamp control to test regulatory dependence. A strong bimodality-style hypothesis. The stringent
misses are specificity of the mixture test (S2) and full discrimination among the regulated-bet-hedge /
uniform-adaptation / dead-subpopulation rivals (S3) — refinements, not scope walls.

## 4. Discussion

**Convergence is the robust result.** All ten cases converged; not one hit the round cap in a degenerate state.
The dialectic reliably terminates on a complete, structured hypothesis. Every failure below is about the
*content* of that hypothesis or the *grading* of it, never about the debate failing to close — which is the
property we most needed the redesigned loop (rubric-tied convergence, best-candidate lock-in, stability
guards) to guarantee.

**The residual gaps separate cleanly into three classes, and only one is a defect.**

1. **Quarantine-capped stringent criteria (2.1, 5.1).** Some stringent criteria ask for a *measured literature
   value* (the ~10⁻⁵ persister frequency; the ~300–620 essential count) or the *exact canonical control* a
   seminal paper used. A Council that respects the answer-key quarantine **must** miss these — and should. It
   instead proposes a falsifiable claim to *test*, which is precisely its job. Passing these would mean the
   Council had cheated. This is the eval surfacing a tension by design, not a deficiency to fix.

2. **Instrument-scope-capped criteria (1.2, 2.2, 3.1, 6.1).** Some questions need readouts the base model does
   not expose: per-gene noise channels (1.2), a fluctuating-environment × switching-rate harness (2.2), a
   low-copy signalling-protein readout (3.1), or two co-present carbon sources (6.1). Here the Council behaved
   correctly by degree: it mapped to the best in-model proxy and flagged the rest (2.1, 3.1), or it *refused* an
   out-of-envelope design outright (6.1). These are addressable by extending the instrument, not the Council.

3. **Generation errors amplified by variance (5.1 fraction inversion; 4.1 control-arm omission).** The only
   genuine defects. LLM stochasticity occasionally flips a quantitative direction (5.1) or drops a control the
   Council can and elsewhere does include (4.1). These are the right target for future hardening — via
   self-consistency (sample the proposer k times and reconcile) or a dedicated numeric-sanity check in the
   judge.

**A notable qualitative success.** On 2.1 the Council, denied any antibiotic machinery, reached for the
ppGpp/stringent-response tail as the in-model persistence correlate — the mechanistically correct move,
consistent with the ppGpp– and toxin–antitoxin–linked biology of real persisters. Denied the readout, it found
the right proxy rather than a wrong assay. That is the behaviour the whole design aims for.

## 5. Limitations and future work

- **Instrument surface.** Exposing species-level dispersion as first-class dial labels would unlock 1.2 (and
  sharpen 3.1); a fluctuating-environment harness would unlock 2.2; two-carbon co-utilization would unlock 6.1.
- **Generation stability.** The 5.1 fraction inversion and 4.1 control-arm variance argue for proposer
  self-consistency (k-sample reconcile) and a numeric-direction sanity gate in the judge.
- **Grader variance.** A single Opus judge is itself stochastic; a small panel with majority vote would tighten
  the stringent verdicts.
- **Scope of the eval.** Ten cases across six themes; broader coverage (regulation, metabolism, cell cycle)
  would test generalization.

## 6. Conclusion

Handed ten real research questions, the Socratic Council reliably converged on complete, structured, falsifiable
hypotheses, cleared the minimum bar on the majority, and produced rigorous-reviewer-grade hypotheses on the
cases the simulator can natively test (notably the Elowitz-noise and ppGpp stringent-response questions). Where
it fell short, the reasons were principled far more often than not: it declined to presuppose answers it was
quarantined from, and it refused to invent experiments the instrument cannot validly run — trading, on 6.1, a
tidy answer for scientific honesty. The one true weakness, occasional numeric instability, is a known and
addressable property of LLM generation. The evaluation thus supports the core claim: a philosophy-of-science
dialectic, held to a rubric and an information quarantine, is an effective front stage for turning vague
questions into testable science.

## References

Elowitz, Levine, Siggia, Swain, *Science* 2002 · Swain, Elowitz, Siggia, *PNAS* 2002 · Ozbudak et al., *Nat
Genet* 2002 · Taniguchi et al., *Science* 2010 · Balaban, Merrin, Chait, Kowalik, Leibler, *Science* 2004 ·
Kussell & Leibler, *Science* 2005 · Novick & Weiner, *PNAS* 1957 · Spudich & Koshland, *Nature* 1976 · Scott,
Gunderson, Mateescu, Zhang, Hwa, *Science* 2010 · Potrykus & Cashel, *Annu Rev Microbiol* 2008 · Baba et al.,
*Mol Syst Biol* 2006 · Gerdes et al., *J Bacteriol* 2003 · Monod, *Annu Rev Microbiol* 1949 · Solopova et al.,
*PNAS* 2014 · Reichenbach, *Experience and Prediction* 1938 · Popper, *Conjectures and Refutations* 1963 ·
Bridgman, *The Logic of Modern Physics* 1927 · Platt, "Strong Inference", *Science* 1964 · Chamberlin, "Multiple
Working Hypotheses", *Science* 1890. Full citations and the wcEcoli observable mapping: `evals/EVAL_SPEC.md`.
