# Cellarium — project instructions

## Task tracking → BACKLOG.md
`BACKLOG.md` is the **single authoritative task list**. When any new task, finding, bug, or idea comes up, add it
there — do not create a separate audit/TODO/roadmap doc.

- Place it under the right **class**: A methodology & rigor · B data science · C LLM engineering · D agentic ·
  E design & UX · F infra & hygiene · G scientific capability · H publication.
- Give it an **ID** consistent with its class (audit findings use `M-`/`DS-`/`LLM-`/`AG-`/`D-`/`UX-`/`H-`/`SP-`;
  new items get a class-consistent id), a **priority** (`P1` before publication/open-source · `P2` soon · `P3`
  polish), a **source** tag, and a one-line description.
- **When an item ships, never delete it** — either strike it through in place (`~~**H-1**~~ ✅`) or move it to a
  **Completed** section at the bottom of `BACKLOG.md`, so the record of what's done stays visible.
- `docs/ROADMAP.md` and `docs/DECISIONS.md` are historical/design **reference only** — not task sources.
- Filippo's Council-defect ledger (D1–D6, branch `operationalization-debate`) is a **separate, Filippo-owned**
  workstream — cross-reference it in BACKLOG, never fold it in.

## Orientation
- Package: `src/cellarium/` — the blind Socratic Council (`council.py`), the grounded Cellwright agent
  (`agent.py`, `tools.py`), the guardrails (`provenance.py`, `biosecurity.py`, `envelope.py`, `rigor.py`).
- App: `apps/server.py` + `apps/web/` (the glass-box SPA). Benchmarks: `evals/`. Corpus docs: `docs/`.
- Git: commit and push directly to `main`.
