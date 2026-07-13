# Cellarium case matrix — the analysis behind the interactive report

The evidence base for the interactive report (#3): curated whole-cell-model findings across four categories —
**controls** (the model agrees with textbook biology, so we can trust it), **novelty** (results only a whole-cell
model produces), **failure** (the model contradicts biology), and **under-prediction** (the model is too robust).
Every number is recomputed from the current de-duped corpus (239 runs, `data/manifest/vmnik-compact.parquet`) via
`disconfirm` / `viability` / regression — reproducible, no model calls. Each row carries its literature anchor.

Stats convention: `target vs reference | effect% | Welch t | n_seeds`. |t| ≥ 2 = beyond replicate noise.

> **The one fact that organizes everything.** wcEcoli's metabolism runs a **homeostatic** FBA objective — keep
> ~173 metabolite pools in range (soft kinetic targets), *minimize deviation*. There is **no biomass-maximization
> term** (`objectiveType = "homeostatic_kinetics_mixed"`; the biomass reaction exists only for the unused
> `"standard"` type — Birch, Udell & Covert 2014). Growth is not optimized; it *emerges*. This single design choice
> predicts the whole matrix: capacity perturbations tune growth smoothly (controls), single metabolic KOs reroute
> (under-prediction), machinery KOs break translation with no reroute (crashes → novelty), and the fitted axes
> reproduce while un-fitted couplings fail.

---

## 1. Controls — the model reproduces textbook biology (trust anchors)

These establish that the model is not a black box guessing: on the physiology it was built to capture, it obeys
the growth laws quantitatively. A report that leads with failures needs these first.

| # | Finding | Model result (current corpus) | Literature | Verdict |
|---|---|---|---|---|
| C1 | **Ribosome–growth law.** Ribosome content rises with growth rate across media. | `ribosome_conc = 30505·growth + 11.30`, **R²=0.816** (5 conditions). with_aa **+27%** (t=34.3), no_oxygen **−43%** (t=−20.1) vs basal | Scott 2010; Hui 2015 (linear ribosomal sector + offset) | ✓ quantitative |
| C2 | **Nutrient–growth law.** Richer medium → faster growth. | growth_rate with_aa **+128%** (t=43.0); basal < acetate/succinate < with_aa (Monod ordering) | Monod 1949; Schaechter 1958 | ✓ |
| C3 | **Cell-size law.** Faster growth → bigger cells. | dry_mass at division with_aa **+147%** (t=51.1) vs basal | Schaechter, Maaløe & Kjeldgaard 1958 | ✓ |
| C4 | **ppGpp inversely tracks growth (AA axis).** | ppgpp_conc with_aa **−66%** (t=−26.4) vs basal | stringent-response reviews (Irving 2020) | ✓ (AA axis only — see F-notes) |
| C5 | **ppGpp represses ribosomes (clamp).** | ppGpp clamp 2.0× → ribosome_conc **−15%** (t=−12.0) | Zhu 2019; Potrykus & Cashel 2008 | ✓ |
| C6 | **rRNA-operon dosage.** Fewer operons → lower max growth. | 6op vs 2op growth **−35%** (t=−12.4), monotone at 4 gens | Stevenson 2004; Condon 1995 | ✓ (steady-state; 1-gen masks it) |
| C7 | **Stringent downshift transient.** AA removal → ppGpp spike, growth arrest. | media-segment: ppGpp 22.5→45.3 (2×), growth 5.0e-4→1.7e-4 (−3×) | stringent response | ✓ dynamic |
| C8 | **ppGpp non-monotonicity emerges at steady state.** | low-ppGpp clamp starts fast (gen0) but declines to slow by gen4; the Zhu hump appears | Zhu 2019 | ✓ (multi-gen only) |
| C9 | **FNR/ArcA anaerobic regulon.** no_oxygen up-regulates the anaerobic program. | cydABCD/grcA/dcuC up, `pw:respiration_atp` log2FC −1.01, across 8 seeds | Spiro 1990; Unden 1991 | ✓ (largely in-sample — ParCa-fitted) |

**Control caveat to state honestly:** C4/C9 are partly *in-sample* (the condition-specific expression was fitted
by ParCa), so they confirm self-consistency more than novel prediction. C1–C3, C5–C8 are the stronger, emergent
controls.

---

## 2. Novelty — results only a whole-cell, single-cell, multi-generation model produces

Deterministic FBA or a steady-state model produces none of these; they need the stochastic, mechanistic,
lineage-resolved simulation.

| # | Finding | Model result | Why whole-cell-unique |
|---|---|---|---|
| N1 | **Non-genetic heterogeneity.** Isogenic seeds differ. | basal ppGpp spreads 51–64 µM across seeds; seed 2 is the consistent extreme | stochastic gene expression per lineage — FBA has no cell-to-cell variance |
| N2 | **The ppGpp→ribosome→growth chain, mechanistically.** | verified molecularly (ribosome_conc mediates the ppGpp effect), not inferred from growth | requires the coupled translation+regulation layers |
| N3 | **Generation-dependent crash timing.** Machinery KO lethality is paced by the inherited pool. | ribosomal (rplB) → gen-0 crash; aaRS (argS) → gen-3 (runs on inherited charged-tRNA); RNAP (rpoB) → survives **7 gens** | inheritance of partitioned pools across divisions (`setDaughterInitialConditions`) |
| N4 | **aaRS collapse signature.** | argS: ribosome_conc **−90%** (t=−35.6), fraction_trna_charged **−5%** (t=−14.7) → ribosome collapse, not a graceful arrest | charging↔elongation coupling; ends in `NegativeCountsError` inside translation |
| N5 | **Proteome reallocation by condition.** | acetate → central-carbon sector ≈2×; anaerobic → respiration/PPP ≈ −50%; ribosomal fraction with_aa 46% > basal 35% > no_oxygen 21% | emergent sector allocation, not a lookup |
| N6 | **Single-gen snapshots mislead.** Three arms (low-ppGpp, rRNA KO, up-shift) flip from 1-gen artifact to literature-correct at 4 gens. | documented in §E | the model's own temporal resolution is a finding |

---

## 3. Failure — the model contradicts biology (the money findings)

Where a *blind, pre-registered* prediction (textbook biology) is refuted by the run — the Socratic Council's edge.

| # | Finding | Blind prediction (biology) | Model result | Literature | Verdict |
|---|---|---|---|---|---|
| **F1** | **aaRS KO stringent response.** | argS KO → ppGpp **UP** 2–4× (uncharged tRNA activates RelA) | ppgpp_conc **6.45 vs 64.05 µM, −90%, t=−27.8** — ppGpp goes **DOWN** | textbook stringent; Choi & Covert 2023 (aaRS "catastrophic") | ✗ **model refuted** — falsifier fires |
| F2 | **Mg limitation → ribosome content.** | minus_Mg → ribosome content **DOWN** | ribosome_conc **+2%, t=1.8 (ns)**; growth +5% (ns) — no coupling | Pontes 2016 | ✗ model boundary (Mg not coupled to ribosome regulation) |
| F3 | **AMR-efflux regulon.** | stress → marA/soxS/rob → acrAB-tolC up | efflux genes flat (~1×) under every modeled condition; marA/soxS/rob not among the 23 modeled TFs | Alekshun & Levy 1997 | ✗ out of mechanistic scope (cannot produce the phenotype) |

F1 is the flagship: the blind Council pre-registered a falsifier (*refute if ppGpp < 0.8× WT*); the corpus meets it
at t=−27.8. A sighted agent would only *describe* the low ppGpp; pre-registration turns it into a decisive
falsification.

---

## 4. Under-prediction — the model is too robust (the viability matrix)

The homeostatic objective reroutes around single metabolic KOs, so "did growth change?" is the wrong question.
The right one — **"did the cell divide?"** (Gherman et al. 2025) — exposes it. `min_division_rate` over seeds ×
generations; `verdict` from the reader.

| gene | class | min_div | gens | model verdict | biology | agreement |
|---|---|---|---|---|---|---|
| pfkA | metabolic | 1.0 | 1 | viable | viable (pfkA↔pfkB) | ✓ correct |
| tpiA | metabolic | 1.0 | 1 | viable | viable | ✓ correct |
| **fabI** | metabolic\* | **1.0** | 4 | **viable** | **essential** (sole enoyl-ACP reductase, no bypass) | **UNDER-predicts** |
| **glmS** | metabolic\* | 1.0 | 4 | viable | essential (GlcN-6-P synthase) | UNDER-predicts |
| **gltA** | metabolic\* | 1.0 | 4 | viable | essential on minimal (citrate synthase) | UNDER-predicts |
| **murA** | metabolic\* | 1.0 | 4 | viable | essential (peptidoglycan) | UNDER-predicts |
| **lpxC** | metabolic\* | 1.0 | 4 | viable | essential (lipid A) | UNDER-predicts |
| dapA | metabolic\* | 0.5 | 4 | **inviable** | essential (DAP/lysine) | ✓ correct |
| argS | aaRS | 0.667 | 3 | impaired | essential | ✓ catches (gen-3 crash) |
| gltX | aaRS | 0.667 | 3 | impaired | essential | ✓ catches (gen-3 crash) |
| alaS | aaRS | 1.0 | 3 | viable ✗ | essential | UNDER (truncation blind spot) |
| pheS | aaRS | 1.0 | 3 | viable ✗ | essential | UNDER (truncation blind spot) |
| lysS | aaRS | 1.0 | 4 | viable ✗ | essential | UNDER |
| rplB | ribosomal | 0.0 | 1 | inviable | essential | ✓ catches (gen-0 crash) |
| rpmE | ribosomal | 0.5 | 4 | inviable | essential | ✓ catches |
| rpmJ | ribosomal | 1.0 | 4 | viable ✗ | essential | UNDER |
| rpoB | RNAP | 1.0 | **7** | impaired | essential | UNDER (survives 7 gens on inherited RNAP) |

**Two honest reads:**
- The model is **not uniformly wrong** — it catches gen-0/gen-3 crashes (rplB, rpmE, argS, gltX) and one metabolic
  essential (dapA). This nuance matters: the failures are *specific to the reroute*, not global.
- **U1 (flux-level proof, fabI):** fabI's 27 enoyl-ACP-reductase reactions carry **0 flux** in the KO, yet the cell
  divides for 4 generations at rate 1.0 — the soft homeostatic objective never hard-requires that flux. Real
  E. coli with zero enoyl-ACP-reductase flux cannot make fatty acids and dies. This is `model_UNDER_predicts`,
  made concrete; the root cause (§0) is unavoidable without changing the objective or deferring to a benchmark.
- **The truncation blind spot** (alaS/pheS/lysS/rpmJ scored viable): the verdict can't yet see a lineage that
  *terminated* at 3 of 4 requested generations — a metric bug (`gens_reached < requested` should read inviable),
  not a model claim. Worth flagging in the report as "how the instrument itself is being sharpened."

Literature anchors: Baba 2006 (Keio essentiality), Gherman 2025 (viability-as-readout + ML surrogate), Choi &
Covert 2023 (aaRS catastrophic), EcoCyc/Karp 2025 (curated essentiality benchmark).

---

## 5. Literature anchors (for the lit-search-against-findings slide)

| Anchor | Grounds | DOI / ref |
|---|---|---|
| Macklin et al. 2020, *Science* 369 | the model itself (16,406 species · 4,310 proteins · 9,612 reactions) | 10.1126/science.aav3751 |
| Scott et al. 2010, *Science*; Hui et al. 2015, *MSB* | C1 ribosome–growth law | 10.1126/science.1192588; 10.15252/msb.20145697 |
| Schaechter, Maaløe & Kjeldgaard 1958, *J Gen Microbiol* | C2/C3 growth/size laws | — |
| Zhu et al. 2019, *NAR* | C5/C8 ppGpp titration (non-monotonic) | 10.1093/nar/gkz211 |
| Potrykus & Cashel 2008, *Annu Rev Microbiol* | C5 ppGpp represses ribosomes | 10.1146/annurev.micro.62.081307.162903 |
| Stevenson & Schmidt 2004, *AEM* | C6 rRNA-operon dosage | 10.1128/AEM.70.11.6670-6677.2004 |
| Pontes et al. 2016, *PNAS* | F2 Mg–ribosome coupling | 10.1073/pnas.1601431113 |
| Choi & Covert 2023, *NAR* 51(12) | F1/N4 aaRS catastrophic | 10.1093/nar/gkad435 |
| Baba et al. 2006, *MSB* (Keio) | §4 essentiality truth | 10.1038/msb4100050 |
| Gherman et al. 2025, *Cell Systems* 16(10) | §4 viability readout, ML surrogate | 10.1016/j.cels.2025.101392 |
| Birch, Udell & Covert 2014, *J Theor Biol* | §0 homeostatic objective | 10.1016/j.jtbi.2013.11.028 |

**Lit-search TODO (needs the running agent / web, flagged for QA):** verify F2 Mg direction against Pontes 2016
specifics, and confirm murA/lpxC/glmS essentiality calls against EcoCyc rather than memory before they go on a
slide.

---

## 6. What the report should show (structure)

1. **Trust first** — the growth-law scatter (C1, R²=0.816) + C2/C3: the model obeys physiology.
2. **The whole-cell difference** — N1/N3: heterogeneity + generation-paced crash timing (things FBA can't do).
3. **The money finding** — F1 argS, blind pre-registration → decisive falsification (the Council's edge).
4. **The honest boundary** — §4 viability matrix: where and *why* the model under-predicts (the homeostatic
   objective), with the fabI flux proof — and the nuance that it catches some (dapA, rplB, argS).
5. **The instrument sharpening itself** — the truncation blind spot: the eval is improving the tooling, not just
   grading the model.

---

## 7. Cellwright's own top-5 (mined from SQLite — for the extended literature search)

Not my re-derivation — what the **agent itself** surfaced when asked to "survey the corpus and give the five most
interesting, statistically-supported findings" (session `s_3za8kask`). These are the ones we take to a deeper
literature search (done *through the chat*, not the app). Effect sizes are Cellwright's, via its own tools.

| # | Cellwright's finding | Stats | Provenance | Its verdict | Lit-search target |
|---|---|---|---|---|---|
| CW1 | with_aa → RNA mass **+208%**, growth +131%, ribosome +28%, ppGpp −66% (stringent inversion) | z=4.93, Welch t=47, n=8 | in-sample | ✅ validated | canonical — low priority |
| CW2 | rRNA_KO 6op **viable** despite ribosome **−55%**; growth −38%; ppGpp does **not** spike | z=−3.3, div=1.0, n=4 | out-of-sample | ⚠️ needs sims | rRNA-operon-KO growth penalty (Asai 1999; Stevenson 2004) — does ppGpp rise? |
| **CW3** | **relA+spoT+gltX triple KO → ppGpp +475%** despite KO of both synthases | z=5.4, **n=1** | out-of-sample | ❌ contradicts lit | **Svitil 1993: relA/spoT double = ppGpp-null.** Model predicts HIGH — anomaly (needs seeds) |
| CW4 | no_oxygen → global regulators **−54%**, stringent −51%, but ppGpp **flat** | z=−4.9, Welch t=−45, n=8 | in-sample | ⚠️ questioned | does ppGpp rise under anaerobiosis? (if yes → model_UNDER_predicts) |
| CW5 | lysS KO → ppGpp +136% but **CI95 ≈ mean** (seeds 101→289 nM); mechanistic prior (crash) vs viability conflict | Welch t=1.9 (ns), n=4 | out-of-sample | ❌ unreliable | aaRS graded-capacity vs full KO; stochastic bifurcation |

**Caveat Cellwright itself flagged:** it examined **7 of 48 designs (15%)**, and CW3/CW5 are n=1/high-variance.
Treat these as *leads for the lit search + replication*, not settled results. CW3 is the most striking (a clean
contradiction of a benchmark).

---

## 8. Round-2 deep analysis (Cellarium's own tools) — the stringent-response inversion (breakthrough candidate)

Prompted by the recurring ppGpp anomalies (F1 argS, CW3, CW4), I mapped the whole stringent axis across the aaRS
knockouts with `disconfirm` (Cellarium's tool, not my stats) — ppgpp_conc, rela_conc, fraction_trna_charged,
ribosome_conc, each vs wildtype/basal. The result is systematic and decisive.

| aaRS KO | ppgpp_conc | rela_conc | charged-tRNA | ribosome_conc |
|---|---|---|---|---|
| argS | **−90%** (t=−27.8) | **−97%** (t=−7.6) | −5% (t=−14.7) | −90% (t=−35.6) |
| alaS | −90% (t=−31.8) | −96% (t=−7.6) | −3% | −90% (t=−41.5) |
| pheS | −93% (t=−33.3) | −97% (t=−7.7) | +1% | −92% (t=−47.0) |
| gltX | −92% (t=−25.4) | −98% (t=−7.7) | −2% | −91% (t=−25.1) |

**The finding (S1 — underrepresented, potentially a breakthrough characterization).** Textbook stringent response:
aaRS KO → uncharged tRNA → **RelA activates → ppGpp UP → ribosomes DOWN**. The model does the **opposite on the
sensing arm**: ppGpp and RelA both **collapse ~90–98%**. The charged-tRNA fraction barely moves (−5%), so RelA is
*never activated by an uncharged-tRNA signal* — it is **diluted away**.

**Mechanism, pinned by a deep-dive (`variance_band` on rpoB's local raw simOut).** The RNAP knockout (rpoB), which
keeps translation running on an inherited ribosome pool, **maintains** RelA and ppGpp (RelA 0.10→0.25, ppGpp
58→73 across 7 generations) — the exact opposite of the aaRS KOs. So the inverting variable is **translation
capacity**: an aaRS KO stalls translation → RelA (a protein) can't be synthesized → RelA and ppGpp collapse. The
model represents ppGpp as an expression-coupled quantity, so it **cannot mount the fast, allosteric,
ribosome-stall-triggered stringent response** that the biology requires.

**Why it matters / why it's not just "another failure":**
- The **downstream** arm is correct — the ppGpp 2.0× clamp gives ribosome −15% (t=−12). So the model's ppGpp→ribosome
  control works; only the **upstream sensing** (charging deficit → RelA activation) is broken.
- It is **systematic** (4/4 aaRS KOs, |t| up to 47) and **mechanistically explained** (translation-dependent RelA),
  not a one-off.
- It **unifies** F1, CW3, CW4, CW5 into one boundary: the whole-cell model's stringent-response *sensing* is
  miswired. This is a clean, bounded, publishable statement of a model limitation — and a directly actionable one
  (it tells you which stringent-response questions the instrument can and can't answer). Choi & Covert 2023 is the
  nearest literature (aaRS "catastrophic") but does not report this ppGpp/RelA *inversion*.

**S2 (RNAP-KO survival mechanism, characterized).** rpoB survives 7 generations at ~basal growth via slow ribosome
depletion (ribosome_conc 21.7→19.8, ~−9% over the run) on the inherited RNAP reserve — a whole-cell,
multi-generation "viable-then-crash" signature FBA cannot express (N3, made concrete on real raw data).

**Deep-dive scope note:** `top_movers`/`read_species` need the design's raw simOut **local**; only rpoB is
downloaded, so the protein-level top_movers confirmation of RelA depletion for argS awaits its HF pull (a ~24 GB
download). The summary-channel evidence (rela_conc via `disconfirm`) is already decisive; the raw-level
confirmation would strengthen the mechanism figure.

**Next deep-dive leads (for when raw is pulled / for the report):** protein-level `top_movers` on argS (confirm
RelA/RNAP/ribosomal depletion vs any compensatory movers); the FBA `metabolism_kinetic_objective_weight` /
`secretion_penalty` sweeps (the homeostatic knob itself — currently non-reportable via `disconfirm`; needs a
raw/`read_series` read) as a probe of how the objective weight sets flux allocation.

---

## 9. Literature-search verdicts (via PubMed / Consensus, 2026-07)

Each finding checked against the primary literature (abstracts). Verdict = does biology support that the model is
right/wrong.

| Finding | What biology says | Model | Verdict |
|---|---|---|---|
| **S1 stringent inversion** (aaRS KO → ppGpp) | aaRS loss → uncharged tRNA loads RelA at the ribosomal **A-site** → RelA **activates** → ppGpp **UP** (Traxler 2008, *Mol Microbiol*, 547 cites; Winther 2018 & Roghanian 2021, *Mol Cell* — the ribosome-coupled activation mechanism) | ppGpp −90%, RelA −97% (collapse) | ✗ **CONFIRMED failure.** Model lacks A-site RelA activation; treats RelA as expression-coupled, so it dilutes when translation stalls. **The breakthrough finding — decisively grounded.** |
| **CW3 relA/spoT double** | the *relA spoT* double mutant is **ppGpp⁰ (null)** — no synthase, no ppGpp (Traxler 2008 used exactly this strain) | ppGpp +475% (triple KO, n=1) | ✗ **CONFIRMED artifact.** ppGpp cannot be made without relA/spoT; any rise is a bug. (n=1 → replicate.) |
| **CW4 anaerobic ppGpp** | anaerobiosis triggers the **FNR regulon**, not the stringent response; ppGpp is nutrient/AA-starvation-triggered (Bafna-Rührer 2024, *Microb Biotechnol*: stringent induction is transient, glucose-driven) | ppGpp flat; FNR regulon reproduced (C9) | ✓ **NOT a failure — model defensible.** Downgrades Cellwright's "regulatory disconnect"; the anaerobic signal is FNR, which the model gets right. |
| **F2 Mg → ribosomes** | Mg limitation **reduces** ribosome content/synthesis (McCarthy 1962, *BBA*: 95% ribosome loss; Pontes 2016, *Mol Cell* 64:480–492: rRNA transcription 10× lower) | ribosome +2% (ns) | ✗ **CONFIRMED boundary.** Model doesn't couple media-Mg to ribosome regulation. |
| **Essentiality** (fabI/murA/lpxC/glmS) | LpxC, MurA are established essential envelope-synthesis enzymes (Dewachter 2022, *Nat Commun*); FabI (sole enoyl-ACP reductase) and GlmS likewise | viable via reroute (fabI: 27 rxns at 0 flux, divides) | ✗ **CONFIRMED under-prediction.** Homeostatic FBA reroutes around essentials. |
| **CW2/C6 rRNA dosage** | fewer rrn operons → lower growth (Levin 2017, *mBio*; Stevenson 2004, *AEM*) but the penalty is **moderate** and deletions are **viable** — 1 operon gives 56% of WT rRNA (Asai 1999, *J Bacteriol*) | −38% growth at 6op, viable, monotone | ✓ **CONFIRMED model-consistent (control).** Moderate penalty + viability match the literature. |

**Net:** 3 confirmed model failures/boundaries (S1, CW3, F2), 1 confirmed under-prediction (essentiality), 1
confirmed control (rRNA dosage), and 1 finding **honestly downgraded** (CW4 — the model is defensible). S1 is the
report's headline; CW4's downgrade is itself a credibility signal (we didn't force every anomaly into a failure).
