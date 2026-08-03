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

## Reporting rules (each one caught a real error here)

These are not style preferences. Each is written against a specific failure this project actually produced.

- **Report per-family, never aggregate-plus-one-example** — whenever per-item spread is comparable to or larger
  than the effect you are claiming. Show every family (or every seed, gene, condition) or say plainly which you
  are omitting and why; one illustrative example next to a mean is a *selected* example, and the reader cannot
  tell how it was selected. *Evidence:* re-auditing 18 claims with all 20 amino-acid families displayed
  **weakened or failed 14 of them**, and a headline "fix" turned out to be carried **109% by four families**
  while **9 of 20 moved the other way** — the aggregate was positive only because a few families dominated it.

- **Label evidential standing on every claim** — one of **SIMULATED** (came out of a run in the corpus) ·
  **ALGEBRAIC** (derived from run outputs by arithmetic we did) · **CODE-READ** (read off model source) ·
  **LITERATURE** (external source, cited) · **ARGUED** (reasoning, no direct evidence). The label is part of the
  claim, not a footnote; an unlabelled claim reads as SIMULATED to anyone downstream. *Evidence:* a 150-claim
  audit found failures **clustered in the ARGUED ones**, including a flagship result that had to be **withdrawn**.
  The point of the label is to make that cluster visible *before* it ships, not after.

- **A string search is not a dependency proof.** `grep`/absence-of-token establishes only that a name does not
  appear *as text in the files searched*. It does not establish that a quantity has no causal path into a
  computation — dependencies travel through call arguments, intermediate variables, closures, config, and
  precomputed inputs. To claim independence, trace the data flow (or perturb the input and show the output does
  not move); to claim a dependency exists, a hit is suggestive, not sufficient. *Evidence:* "ppGpp appears
  nowhere in `dcdt_jit`, verified by grep, zero hits" was **true as text and false as a dependency claim** —
  ppGpp enters via `max_elong_rate`. The same text-for-dependency conflation broke **two separate conclusions**.
  The text really is absent, and the dependency really is there, three hops up
  (`model_overlay/files/models/ecoli/processes/polypeptide_elongation.py`): `dcdt_jit` takes `max_elong_rate` as
  a parameter (`:1698`) and uses it for `v_rib` (`:1709`); it is assigned from `self.elongation_rate()` (`:1091`);
  and `SteadyStateElongationModel.elongation_rate` derives that rate from `ppgpp_conc` via `elong_rate_by_ppgpp`
  whenever `ppgpp_regulation` is on (`:1028-1034`). Related, and the same error class: never report a failed read
  or an empty grep as an established fact.

## Orientation
- Package: `src/cellarium/` — the blind Socratic Council (`council.py`), the grounded Cellwright agent
  (`agent.py`, `tools.py`), the guardrails (`provenance.py`, `biosecurity.py`, `envelope.py`, `rigor.py`).
- App: `apps/server.py` + `apps/web/` (the glass-box SPA). Benchmarks: `evals/`. Corpus docs: `docs/`.
- Git: commit and push directly to `main`.
