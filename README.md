# Cellarium

**A Claude-backed copilot for reasoning over a whole-cell *E. coli* simulation — grounded, and honest about its own limits.**

Whole-cell models compute the *dynamic, regulatory, single-cell* behaviour of a living cell from first
principles — the regime that steady-state flux-balance analysis and human intuition can't reach. But they are
locked behind deep expertise, a heavy compute stack, and long run times. Cellarium is a small agentic
workbench that lets a scientist ask a question in plain English and get back a **grounded** answer — every
number tied to real simulation output, never fabricated — with two guardrails that make the answer
*trustworthy*:

- **Feasibility / validation-envelope check** — refuses experiments the model was never built or validated to
  simulate (e.g. a mid-run carbon-source switch), and says why.
- **Output QC** — inspects each simulated generation and withholds any degenerate / non-viable result instead
  of laundering it into a clean-looking number.

Built for *Built with Claude: Life Sciences* (Builder track). This is a fresh, from-scratch implementation.
It depends on the **public, open-source** [Covert-lab whole-cell *E. coli* model](https://github.com/CovertLab/WholeCellEcoliRelease)
as an external model backend — Cellarium is the new agent + guardrail + interface layer around it.

## Why it's interesting

The differentiator is not "the AI answers the question" — a naive tool can print a number. It is that the
agent **imposes the scientific rigor** (validated envelope, replication, grounding) that a mechanistic model
demands, and **catches the failure modes a scientist would otherwise trust.** That rigor layer is a
specialization of the reviewer-agent pattern, applied to systems-biology *modelling* — a domain a scientific
AI workbench does not yet cover.

## Architecture (minimal vertical slice)

```
src/cellarium/
  envelope.py   validated-perturbation envelope check   (feasibility guardrail)
  qc.py         per-generation output QC                 (integrity guardrail)
  model.py      thin backend adapter (cached + live hook to the public wcEcoli model)
  tools.py      grounded read tools exposed to the agent
  agent.py      Claude (Anthropic Messages API) tool-using loop
  cli.py        run a question end-to-end
ui/index.html   Claude-Science-style demo interface
data/cache/     cached demo simulation results (reproducible, fast)
docs/DEMO.md    the demo script
```

## Setup

```bash
python -m venv .venv && . .venv/Scripts/activate   # (or bin/activate on unix)
pip install -e .
cp .env.example .env      # add your ANTHROPIC_API_KEY
python -m cellarium.cli "Do genetically identical E. coli cells behave differently, and why?"
```

Open `ui/index.html` in a browser for the interface mockup.

## Scope & honesty

Cellarium's users are **hypothesis generators, not decision-makers**: the model's predictions are hypotheses,
and the tool prioritizes and explains experiments rather than certifying outcomes. It removes
*computational* expertise, not scientific judgement. Organism: *E. coli* K-12 MG1655 (a lab strain).

## License

MIT — see [LICENSE](LICENSE).
