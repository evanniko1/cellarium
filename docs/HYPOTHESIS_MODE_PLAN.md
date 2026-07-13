# Hypothesis-Generation Mode — plan (Socratic Council → dedicated surface)

**Status:** in progress. **Owners:** Evangelos + Claude (we build all of it — not split to Filippo).
**Decision (Evangelos + Filippo, 2026-07-12):** Option 1 — separate the Socratic Council from the main chat.

## The decision

Cellwright stays the **main grounded chat** (no Council toggle in the composer — already defaulted OFF).
The Council becomes a **dedicated, persistent Hypothesis-Generation surface**: you pose a research question, the
Council deliberates **async**, the full debate is **persisted and cleanly readable**, and a **"Open in Cellwright"**
handover seeds a grounded investigation from the operationalized hypothesis.

## Why (grounded, not vibes)

- **Resource footgun.** The Council is up to 4 rounds × 3 route-bumped model calls; it was default-ON per chat, so
  every investigation paid for a deliberation whether or not it needed one.
- **Conditional value.** Filippo's `operationalization-debate` eval: the blinded human pilot preferred the Council
  on only **4/10** questions (4 Council / 4 single-shot agent / 2 tie). The sharp thesis: *the agent wins by finding
  one concrete defect; the Council wins by supplying dynamics* — it **pays on mechanism/causal questions** (P07) and
  is **dead weight on threshold/definition questions** (P08). A dedicated surface makes the Council **opt-in for
  exactly the deep questions where it wins**, and showcases it instead of hiding it (which routing would do).
- **The output is a lab-notebook artifact that we currently throw away.** The aaRS-KO debate produced an
  operationalized hypothesis (claim/H1/H0/falsifier/rivals/operational-defs/assumptions) + **13 queue-ready
  falsifier designs** — and it lives only in the browser front-end. SQLite persists `{messages, used_council,
  title}`, **not the deliberation**. Persistence is the concrete gap.

## Invariants (non-negotiable — protect the crown jewel)

Blindness = the Council frames **blind to the corpus RESULTS** (the paper's quarantine/recitation control). Both
enhancements below are contamination vectors; guard them:

1. **Web / lit-review = literature-informed, corpus-blind.** The Council may read *general biology* (web,
   K-dense/ResearchStudio) — that is not seeing the *simulation answer*. It must NEVER see corpus results.
   **Cellwright stays corpus-only** (its whole rigor). Clean split of the two agents.
2. **Challenge = scope, never the answer.** A "sensible challenge" (Filippo) beats Co-Scientist's gap (which "runs
   away making assumptions"). But asking *"what do you mean by X?"* (scope) is blindness-safe; hinting at expected
   outcomes is not. The Council asks for **specification only, only when it would genuinely fail otherwise** — never
   reflexively (or we become planning-mode Claude/ChatGPT). Gate behind a cheap "is this operationalizable as-is?"
   classifier; it should fire rarely (the aaRS question needed **zero** challenge).
3. **Any change to the Council (web, challenge) must re-pass the blindness/quarantine control before it ships**, and
   the paper's blindness claim is scoped to whatever artifact the eval actually covered.

## Phases

### Phase 1 — Persistence + backend (the gap) — START HERE
- `HypothesisStore` (SQLite, new `council_runs` table in `data/sessions.db`), mirroring `SessionStore`:
  `id, question, status, created, model, rounds(json), hypothesis(json), designs(json), meta(json)`.
- `run_hypothesis(question, ...)`: run `council.deliberate`, capture rounds via `on_round`, persist the full run
  (rounds + `ui.hypothesis_view` + `ui.design_view`s + convergence meta).
- Endpoints: `POST /api/hypothesis` (run async, persist, stream rounds), `GET /api/hypotheses` (list),
  `GET /api/hypothesis/{id}` (full run).
- Tests: store round-trip; a run persists rounds + hypothesis + designs.

### Phase 2 — The surface (front-end)
- A **Hypothesis-Generation workspace** (overlay, sibling of the Corpus browser): pose a question → async run with a
  live/streamed debate → **clean debate view** (rounds; the operationalized brief as readable sections; the
  falsifier designs) → a **persistent, browsable list** of past runs.
- **"Open in Cellwright"** per run: create a Cellwright investigation seeded with the operationalized brief (reuse
  `agent.first_user_content`); secondary "copy spec" (markdown).
- Retire the composer Council toggle (it now lives in the surface).

### Phase 3 — Blindness invariants + enhancements
- Automated **blindness-invariant test** (the quarantine control as a test), bolted on before web-access lands.
- **Web / lit-review** skill for the Council (corpus-blind): web + K-dense / Microsoft ResearchStudio.
- **Sufficiency gate** ("sensible challenge"): scope-only, classifier-gated, rare.
- Re-run the human-eval / quarantine control on the enhanced Council; scope the paper claims accordingly.

## Handover contract
`Open in Cellwright` → a new investigation whose first user turn is the operationalized brief + "test this against
the corpus" (exactly `agent.first_user_content(question, hypothesis)`). Cellwright then grounds and runs the
falsifiers through the approval airlock. The Council frames (blind); Cellwright tests (grounded). That boundary is
the product.
