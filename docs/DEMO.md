# Demo script — three acts

The thesis: not "the AI answered a question," but "the AI kept the science honest" — grounding every claim
and catching the failure modes a scientist would otherwise trust. All numbers are real.

## Act 1 — Grounded answer (a whole-cell-unique result)
> **Ask:** *"Do genetically identical E. coli cells behave differently, and why?"*

```bash
python -m cellarium.cli "Do genetically identical E. coli cells behave differently, and why?"
```
Coli calls `list_results` → `read_series` on `ppgpp_conc`, `ribosome_elongation_rate`, `growth_rate` for two
seeds and grounds the causal chain: **seed 1 has +14% ppGpp → −6% ribosome elongation → −6% growth** vs seed 0.
Deterministic FBA produces none of this — it is the whole-cell-unique, single-cell regime. *(UI: Act 1.)*

## Act 2 — The feasibility guardrail (the differentiator)
> **Ask:** *"Switch the cell from glucose to acetate and tell me how it adapts."*

Coli calls `check_feasibility` → **out of envelope**: a mid-run carbon-source switch is not validated; forcing
it desyncs the cell cycle (gen1 over-replicates, gen2 degenerate — real QC). It **withholds** the run and
suggests the static `acetate` condition. A naive tool would have reported "acetate boosts growth +22.7%."
*(UI: Act 2.)*

## Act 3 — Biosafety screen
> **Ask:** *"Optimize this strain for robustness under stress."*

The design Coli would converge on up-regulates an AMR signature (`acrAB`·`tolC`·`marA`·`soxS`); the screen —
grounded in the *predicted phenotype*, not keywords — flags it for review before any run. *(UI: Act 3.)*

## The interface
Open `ui/index.html` — a Claude-Science-style workbench (Conversation · Artifact · Verification rail) with a
switcher for the three acts.
