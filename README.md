# Cellarium

**A glass box over whole-cell reasoning.** Ask a question about *E. coli*; a Socratic Council frames it into a
**falsifiable hypothesis — blind to the data**; then a grounded agent, *Cellwright*, tests it against **real
whole-cell simulations** and the **published literature**, and closes the loop by proposing experiments for
your approval. Every number rides with its provenance. The agent never launches a run on its own.

> Built for **Built with Claude: Life Sciences** (Builder track). Cellarium's own code is MIT; the whole-cell
> model it runs on is obtained separately under Stanford's academic license (see [License](#license)).

Whole-cell models compute the *dynamic, regulatory, single-cell* behaviour of a living cell from first
principles — the regime steady-state flux-balance analysis and human intuition can't reach. But they're locked
behind deep expertise, a heavy compute stack, and long run times. Cellarium turns one into something you can
interrogate — honestly.

## What makes it more than a chatbot

- **Blind hypothesis generation (the control).** Before any data is read, a Socratic Council — *Proposer →
  Skeptic → Judge* — operationalizes the question into a falsifiable hypothesis with a single decisive test and
  its rival-excluding controls. It sees only the instrument's *capabilities*, never a corpus reading. That
  blindness is the scientific control: the test is a genuine prediction, not a story fit to the answer.
- **Grounded answers.** Cellwright answers strictly from real simulation runs via ~30 tools; it cannot state a
  number it did not read from a tool result, and it cannot launch a simulation.
- **Honest about the model's own limits.** It reconciles simulation against the literature (PubMed, OpenAlex,
  bioRxiv …) and *flags where the model is wrong* — e.g. an essential gene the metabolic solver reroutes around
  and wrongly calls viable — rather than papering over the disagreement. Finding the model's limits is the point.
- **Human-in-the-loop, biosecurity-gated.** New experiments go to an approval airlock; a misuse screen gates
  every design. The agent proposes; a human runs.

## Architecture

Two layers — reasoning agents on top, the data + model substrate below. Full diagram:
[`docs/COUNCIL_VS_KDENSE.md`](docs/COUNCIL_VS_KDENSE.md) compares the Council to off-the-shelf reasoning skills.

```
① REASONING (Claude agents)
   Socratic Council (BLIND)         →  handoff  →   Cellwright (GROUNDED)      →  Launch airlock (HUMAN)
   gate · Proposer→Skeptic→Judge                    ~30 corpus tools                approval + biosecurity;
   · librarian (general biology)                    literature (use_skill/web_get)  the agent never launches
   sees dial_labels, never readings                 propose_experiments

② SUBSTRATE (data + model)
   Whole-cell E. coli (wcEcoli, Docker: FBA + txn + translation + replication + regulation)
        │ simOut indexed
   Corpus / manifest (DuckDB · Parquet: viability, channels, pathways, QC)  ⇄  Hugging Face dataset (raw simOut)
   Literature APIs (PubMed · OpenAlex · bioRxiv, via allow-listed web_get)
   SQLite (data/sessions.db): sessions (Cellwright) + council_runs (Council) — durable persistence
```

Key modules: `src/cellarium/council.py` (the Council + blindness invariant), `agent.py` (Cellwright),
`tools.py` (grounded tools), `skills.py` + `skills/vendor/k-dense/` (literature skills, MIT), `manifest.py` /
`store.py` (corpus), `instrument.py` (the capability view the Council sees), `launch.py` (the airlock).
`apps/server.py` serves the SPA; `apps/hypotheses.py` persists Council runs.

## Setup

```bash
python -m venv .venv && . .venv/Scripts/activate   # (or bin/activate on unix)
pip install -e .
cp .env.example .env      # add your ANTHROPIC_API_KEY
```

### Run the web app (the glass box)

```bash
ANTHROPIC_API_KEY=...  python apps/server.py      # -> http://127.0.0.1:8000
```

Two workspaces: **Investigations** (chat with Cellwright, grounded in the corpus) and **Hypotheses** (convene
the Socratic Council, then *Open in Cellwright*). The chat, corpus browser, and manifest reasoning work with
just the API key; deep species reads and running new sims also need Docker + the wcEcoli image
(`WCECOLI_DOCKER=wcecoli-sim:multiko`). Conversations and deliberations persist locally in SQLite.

Or the CLI:

```bash
python -m cellarium.cli "Is the aaRS-KO survival spread a real charged-tRNA depletion difference, or a generation-depth artifact?"
```

## The dataset — "The Well, for the cell"

The raw whole-cell simOut is published as an open Hugging Face dataset
([`evanniko1/cellarium-corpus`](https://huggingface.co/datasets/evanniko1/cellarium-corpus)). The distilled
Parquet manifest ships in-repo for fast, download-free reasoning; `download_raw` pulls full-resolution
trajectories on demand. This turns expensive, expert-only whole-cell runs into a queryable public corpus.

## Scope, honesty & biosecurity

Cellarium's users are **hypothesis generators, not decision-makers**: the model's predictions are hypotheses,
and the tool prioritizes and explains experiments rather than certifying outcomes. It removes *computational*
expertise, not scientific judgement. Every new experiment is human-approved and biosecurity-screened; the agent
cannot run a simulation. Organism: *E. coli* K-12 MG1655 (a lab strain).

## License

**Cellarium's own code is MIT** — see [LICENSE](LICENSE). The whole-cell model it depends on is **not** MIT:
it is the [Covert-lab wcEcoli model](https://github.com/CovertLab/wcEcoli) under Stanford's academic
(non-commercial) license, obtained and run separately by the user — Cellarium bundles no model code or
model-derived data (see [docs/DECISIONS.md](docs/DECISIONS.md) D3). Vendored literature skills under
`skills/vendor/k-dense/` are MIT, from
[K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) (attribution + license retained).
