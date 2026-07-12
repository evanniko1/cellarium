# Operationalization debate — per-case breakdown vs the human pilot

Rows are the ten problems. **Your blind pref** is the human-pilot preference (Council = the `full` Council
hypothesis, agent = the single-shot `proposer_only` hypothesis, tie). **Council verdict** and **Agent verdict**
are each advocate's honest self-verdict from the debate (YIELD = conceded the other is stronger; MAINTAIN = held
its ground; TIE = equipotent or the question too under-specified to separate). **Notes** is a reading of where the
two advocates actually agree and where they part.

| P (case) | Your blind pref | Council verdict | Agent verdict | Notes — reading of the two positions |
|---|---|---|---|---|
| **P01** (1.1) | agent | **TIE** | **TIE** | Full mutual agreement. Both name the *identical* core (protein-level CV across isogenic seeds, gen 10) and the same rivals; they differ only on calibration — CV threshold 0.15 vs 0.2, and 20 named genes vs ≥10 flexible. Both independently frame the only open question the same way: does "same gene" mean *specific loci* or *genome-general*? Neither can break it, so the question — not the systems — is the bottleneck. |
| **P02** (1.2) | agent | **YIELD** | **TIE** | They agree on the observable (CV ∝ 1/√mean) but split on what "what makes noisier" *asks*. Council concedes outright that the agent's design is better because it **decomposes the mechanism** (burst parameters beyond the Poisson floor) rather than just showing the scaling law. The agent is more modest — calls it a semantic tie. So the agent wins on merit while under-claiming. |
| **P03** (2.1) | Council | **YIELD** | **YIELD** | Cross-concession: each praises a *different* virtue of the other and rates it the more important one. Council concedes the agent measures "**some** bacteria" directly (per-cell subpopulation classification); the agent concedes the Council's ppGpp dose-response clamp gives **causal** inference it can't. Complementary designs — one measures the fraction, the other proves causation. |
| **P04** (2.2) | Council | **YIELD** | **YIELD** | The healthiest mutual concession: each spotted a real hole *in its own* design that the other fills. Council concedes the agent's time-integrated fitness metric beats its single-timepoint snapshot; the agent concedes the Council actually **validates its control** (verifies the ppGpp-clamp truly homogenizes) where the agent just assumed it. Both right about themselves. |
| **P05** (3.1) | agent | **YIELD** | **TIE** | Same shape as P02. Same core (between-seed CV in growth_rate); Council fully concedes the agent's multi-channel + temporal-control design has more power against the technical-noise rival, while the agent retreats to "the question doesn't specify temporal-amplification vs steady-state dispersion." Agent prevails but again under-claims. |
| **P06** (4.1) | Council | **TIE** | **TIE** | Strong agreement. Both build the same chain (tRNA→ppGpp→ribosome→growth) and both use the relA/spoT knockout. The sole split is framed identically by each: does "how does a cell **decide**" demand *necessity* (mandatory knockout) or just the *input-output transfer function* (gradient/regression)? Equipotent — the human lean to Council was a finer judgment than either advocate would defend. |
| **P07** (4.2) | tie | **MAINTAIN** | **TIE** | The Council's one stand — and its best case. It maintains that its **60 s sampling over 300–600 s + relA-KO + ppGpp-clamp** captures causal *ordering* (tRNA→ppGpp→arrest) that the agent's single 10-min snapshot cannot. The agent concedes those points but ties on "'suddenly' has no specified timescale." The Council's surplus structure (dynamics + causal perturbation) actually *pays* here — a mechanism question, exactly where extra rigor earns its keep. Human called it a tie; the debate gives the Council its only edge. |
| **P08** (5.1) | agent | **YIELD** | **MAINTAIN** | The cleanest, least ambiguous case. Both sides agree the deciding feature is the **viability threshold**, and both agree the agent's is better: Council concedes its own 0.05/h absolute cutoff conflates biology (a 12×-slower strain counts as "nonessential"); the agent maintains on exactly that point, preferring 0.8×-wildtype (20% impairment) + a larger sample. Rare full agreement on *what decides it* and *who wins*. |
| **P09** (6.1) | **Council** | **YIELD** | **MAINTAIN** | **The one case the debate contradicts the human pilot.** The pilot preferred the Council; here its own counsel concedes. They target different axes: Council concedes the agent's **evidentiary breadth** (extracellular GLC[e]/AC[e] channels + CRP anchor + per-seed falsifier); the agent maintains by finding a concrete brittleness in the Council's design — `find_peaks(min_distance=2 generations)` misses short diauxic lags. The favored Council design had a specific fragile parameter both advocates flagged. |
| **P10** (6.2) | tie | **YIELD** | **YIELD** | Mutual concession on *falsifier design*. Council concedes the agent's single Hartigan dip test is more principled than its own redundant dip-**and**-CV (which risks false negatives); the agent concedes the Council's per-seed resumption-time CV measures "**at the same time**" better than a single-snapshot bimodality that could miss the transient window. Each fixed the other's weakness — effectively the human tie. |

## Cross-cutting patterns

1. **The Council is the concessive advocate; the agent is the cautious one.** Council YIELDs 7×, the agent only 3×
   — but the agent hides in TIE 5× (vs the Council's 2×). When the agent's design is actually stronger (P02, P05),
   it *still* only claims a tie while the Council openly concedes. The agent rarely presses an advantage; the
   Council rarely defends one. That asymmetry, not the operationalizations themselves, drives several outcomes.

2. **Two distinct "tie" mechanisms — and they mean opposite things.** A *symmetric TIE* (P01, P06) means both
   advocates converge on the same design and agree the **question** is underspecified — the systems are
   indistinguishable. A *mutual concession* (P03, P04, P10) means the designs are **complementary** — each caught
   a real gap in itself the other fills. The first says "you couldn't tell them apart because they're the same";
   the second says "you couldn't tell them apart because each is half of the right answer." The two pilot ties
   (P07, P10) actually sit in different buckets.

3. **The agent wins by finding one concrete defect; the Council wins by supplying dynamics.** Every agent MAINTAIN
   (P08, P09) hinges on a single, specific technical flaw in the Council's design — a conflated threshold, a
   brittle peak-finder parameter. The Council's only MAINTAIN (P07) is the opposite: it wins by *adding* temporal
   resolution and causal perturbation on a mechanism question. So the Council's elaboration is not uniformly
   wasted — it pays precisely on causal/dynamic questions (P07) and is dead weight on threshold/definition
   questions (P08). That is a sharper, more useful thesis than "the Council writes better hypotheses."
