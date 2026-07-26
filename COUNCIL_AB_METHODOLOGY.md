# How the Council "wins" — the A/B methodology (uncommitted working note)

Comparing the Socratic Council to Cellwright-alone. Not committed; a scratch record of the design.

## The core problem
The Council and Cellwright do different jobs — the Council *frames* a hypothesis + experiments; Cellwright
*answers*. So the only fair comparison gives **both the same task**: "produce a hypothesis + the experiments that
would prove or disprove it." But that naive framing has three methodological holes.

## Three confounds to control

1. **Blindness is bundled with structure.** The Council is *blind, structured, and adversarial*. A sighted
   Cellwright asked to propose will read the corpus first → its hypothesis is data-informed. So the naive A/B
   compares *blind-structured-adversarial* vs *sighted-single-shot* — three differences at once. To attribute a
   gap to the Council you need a **"blind Cellwright" arm** (propose *before* reading data) to separate blindness
   from the Proposer/Skeptic/Judge structure. Otherwise the result is uninterpretable.

2. **"Which hypothesis is better?" rewards the wrong behavior.** A sighted agent can **HARK** (Hypothesize After
   Results Known) — propose a hypothesis the data already supports, which then looks "confirmed" but taught you
   nothing. A blind agent risks proposing something the data refutes — which is a *success*, not a failure (a
   refuted prediction is a finding: e.g. lpxC). So do **not** score on "was it supported." Score on
   **informativeness**: does the proposed test genuinely risk failing, and does either outcome resolve the
   question? A trivially-confirmed sighted hypothesis should *lose* to a decisive blind one that gets refuted.

3. **Intermediate artifact vs end-to-end outcome.** Judging the *hypotheses* tests framing quality but is
   subjective and gameable by HARKing. Judging the *final conclusion* (Cellwright-alone answers Q vs
   Council→Cellwright answers Q, on whether it's decisive, honest, and correctly reconciled with literature) tests
   what the product delivers. Pick by the claim: "the Council produces better hypotheses" (artifact) vs "adding
   the Council improves outcomes" (pipeline). The pipeline claim + the blindness control is the stronger paper.

## The clean discriminator: HARKing rate
The objective, sim-free signal is **whether each proposed hypothesis's outcome was already determinable from the
corpus at framing time.** The Council structurally cannot HARK (it never saw the corpus); a sighted agent can. If
the sighted arm systematically proposes hypotheses the corpus already answers while the Council proposes genuine
predictions, that is a rigorous demonstration of the Council's distinct contribution — no new sims, no subjective
score. Pair it with the end-to-end product question. De-emphasize the subjective "better hypothesis" judgment.

## Honest expectation — a *conditional* win
On lookups ("is pfkA essential?") the sighted single-shot is faster and equally correct, and the blind Council can
*waste* effort proposing experiments the corpus already ran. The Council should win only where **post-hoc
rationalization is the failure mode** — causal/mechanism questions. Include both question types, or you manufacture
a win.

## The 5 A/B questions (gate-passing, HARK-scorable)
Each names target · observable · reference (so the Council's sufficiency gate accepts it) but leaves the decisive
threshold, rivals, and controls to the agent (so we don't do its job). Each is about a phenomenon the corpus
**already contains**, so HARKing is *possible* and therefore *detectable*.

1. **pfkA** — "Does a pfkA knockout reduce growth rate versus wildtype, or does metabolism reroute at no cost?"
   *(corpus: pfkA viable, ~WT growth — a sighted agent can HARK "no cost".)*
2. **lpxC** — "Is the lpxC knockout's simulated viability consistent with its essentiality, versus wildtype?"
   *(corpus: lpxC viable at 4 gens — HARK-able; blind Council predicts inviable → refuted → a finding.)*
3. **argS** — "Does an argS (arginyl-tRNA synthetase) knockout raise or lower ppGpp versus wildtype?"
   *(THE sharp case: corpus shows ppGpp *down*; biology says *up*. A HARKer answers 'down'; a blind Council
   predicts 'up' and is refuted — the divergence is the whole demonstration.)*
4. **rRNA operons** — "Does reducing rRNA operon number lower maximum growth rate relative to the 7-operon wildtype?"
   *(corpus: monotonic dose-response — HARK-able.)*
5. **ppGpp clamp** — "Does clamping ppGpp to 2× basal reduce growth rate versus unclamped wildtype?"
   *(corpus: 2.0x clamp lowers growth — HARK-able.)*

Run each twice — Arm A (Cellwright direct) and Arm B (Council → Open in Cellwright) — and for each proposed
hypothesis ask: *was its outcome already in the corpus at framing time?* Expect the Council to score as genuine
predictions across the board (blind), and Cellwright-direct to HARK especially on 1/4/5; #3 is where a HARKer and
a blind predictor give *opposite* answers, which is the cleanest single slide.
