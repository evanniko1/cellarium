# Demo script — the clash that led somewhere

**Thesis.** A glass box over a whole-cell model does more than *answer* questions or *keep score* on the model — at
its best it turns the model's **disagreement with textbook theory** into a genuine research lead. This demo builds to
one such case: a grounded result clashes with a growth law, the clash frames a falsifiable hypothesis, and a
grounded literature search lands on a known experimental finding that has **never been shown computationally** —
opening a pharmacology angle. All numbers are real; every citation is verified against the primary source.

The full write-up — strengths, boundaries, the cumulative verdict ledger, and the References — is the interactive
report at [`docs/report/index.html`](report/index.html).

---

## Act 1 — The instrument (~20s)

Cellarium pairs a **blind Socratic Council** (Proposer → Skeptic → Judge; frames a falsifiable hypothesis *without
seeing the data*) with a **grounded Cellwright** agent (asserts nothing from memory — only through **38 tools** over
the corpus, the raw simulation traces, and the literature), under a **provenance guard** that separates what the
model was *fitted* to from what it genuinely *predicts*. Two ways in: a Council-framed hypothesis, or a direct data
question.

## Act 2 — A grounded, out-of-sample result (~40s)

> **Ask:** *"What happens as you delete ribosomal-RNA operons?"*

Cellwright runs the dose-response across the corpus (2 → 4 → 6 of the 7 operons removed): ribosome content and
growth fall together, the cell stays **viable** (divides for four generations), and — the mechanism — the
**remaining operons compensate**, per-operon rRNA output rising **1.6× → 3.3×** with **ppGpp flat** — exactly the
ppGpp-independent ribosome feedback Condon measured [Condon 1993]. A clean out-of-sample result the model gets
right. *(This is the numbers axis: a genetic cap on ribosome supply.)*

## Act 3 — The success story: the clash that led somewhere (~90s)

**The clash.** That result sits on the *wrong side* of Scott's second growth law. Scott: impair ribosome
**efficiency** (chloramphenicol) and the cell *over-builds* ribosomes to compensate — ribosome fraction rises as
growth falls. We cut the **numbers** (the genes), so the cell *cannot* over-build — ribosomes fall *with* growth.
Same endpoint, fewer functional ribosomes and slower growth, reached two ways — but the response is **opposite**,
because only the efficiency route leaves the cell free to compensate. Not a contradiction; a **different axis**
[Scott 2010].

**The hypothesis it generates.** Do both at once — cap the numbers *and* jam the efficiency. A number-capped cell
has no way to compensate → a synergistic, non-linear collapse. A clean wet-lab experiment writes itself: an
operon-deletion series crossed with a translation inhibitor.

**The grounded resolution.** Cellwright runs a targeted literature search — and the experiment already has a name:
the **Numbers Game**. Levin et al. built *E. coli* with 1–6 of the 7 rrn operons deleted and challenged them with
chloramphenicol, tetracycline, and azithromycin: operon-poor strains are killed far faster — but not by
ciprofloxacin, which does not target ribosomes. Experimentally confirmed [Levin 2017].

**The payoff.** The Numbers Game is established *experimentally* — but it has **never been shown computationally** in
a whole-cell model. Cellarium already reproduces the numbers half; the drug-synergy prediction is a clean,
falsifiable validation target, and its natural scale — a colony under a drug gradient — is exactly what **Vivarium**
runs (it already simulates wcEcoli colonies under tetracycline) [Agmon 2022; Skalnik 2023]. It opens a
**pharmacology angle**: predicting a ribosome-targeting antibiotic's potency from a cell's ribosome-allocation
state. The clash did not just recover forgotten biology — it pointed at a model test worth running.

## The close — why trust it (~20s)

The same discipline that found the lead keeps it honest. Provenance tags separate prediction from fit. When a
"Scott law, R²=0.99" headline did not survive a check against the primary source, it was **pulled** — the
numbers-vs-efficiency framing above is the corrected version. Every one of the eleven citations is verified against
the publication (report §09). The glass box earns trust not by never being wrong, but by catching itself.

---

## Alternate opener — the falsification (Council mode, ~30s)

If leading with a sharper hook: the Council pre-registers a falsifiable claim blind — *"an argS knockout raises
ppGpp 2–4×; refute if ppGpp falls below 0.8× wildtype."* Cellwright grounds it against the corpus: ppGpp =
**6.45 vs 64.70 µM — down 90%, t = −27.85**. The falsifier fires; the model is caught contradicting the textbook
stringent response, decisively [Winther, Roghanian & Gerdes 2018; Traxler 2008]. Use this to establish "the method
catches the model failing," then pivot to Act 3 for "the method produces a lead."

## In-app hands-free walkthrough (`?demo=1`)

`apps/web/app.js → runDemo()` plays a timed ~3-min auto-play for screen recording. It currently climaxes on the
argS falsification (recorded session `s_ah487iwa`). **To make the clash the success story**, re-point the climax to
the rRNA-operon investigation (`s_r5fasfpz`) followed by clash → Numbers-Game → Vivarium narrative slides. The
grounded rRNA session already exists in the seed DB; the clash and Numbers-Game beats are new narrative slides.
