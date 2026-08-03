# The investigation loop — build spec

**Status:** DESIGNED 2026-08-03, **not built.** · **Decision + rationale:** [`DECISIONS.md` **D10**](DECISIONS.md)
(which supersedes **D6a**'s blindness stamp) · **Backlog thread:** `SP-3` → `SP-3a…SP-3e`.

This file is the *build* spec: schema, migration, API, UI, acceptance tests, sequencing. It deliberately does
**not** re-argue the decision — that is D10, and the withdrawn position it replaces is kept visible in D6a.

---

## 1. What this is, for a reader who was not in the conversation

Cellarium has two surfaces. The **Socratic Council** (`src/cellarium/council.py`) deliberates on a scientific
question **blind to the corpus** and emits a falsifiable hypothesis. **Cellwright** (`src/cellarium/agent.py`,
`tools.py`) is a grounded agent that answers from a corpus of whole-cell *E. coli* simulations.

A researcher's real workflow is a **loop**: broad hypotheses → check them against simulation results → re-convene
with a sharper, targeted question → check again. The second and later Council rounds are **informed**. That is
not contamination — it is the method. An earlier assessment (D6a) treated it as a leak to be detected and
stamped `unblinded`; that framing is withdrawn (D10).

The problem the loop feature solves is therefore **not** "how do we detect informed rounds". It is: **an
autoresearch loop whose chain cannot be recovered is a black box that emits confident conclusions.** The
deliverable is auditability — *this* round was informed by *that* investigation, which read *those* runs, which
came from *this* prior round.

**Anti-requirement, carried from precedent: the loop NEVER blocks.** Nothing here refuses a round. A blocking
Council sufficiency gate once parked ~23 of 25 canonical questions and was made advisory
(`apps/hypotheses.py:138-143`, M-7). Lineage is **displayed, never enforced**.

## 2. The four edges — what exists today

The chain is *prior Council → investigation → runs → next Council*. **MEASURED by reading the writers**
(2026-08-03; every line below opened and re-verified):

| Edge | Stored? | Where |
|---|---|---|
| Council run → queued falsifier run | **Yes** | `launch.stamp_provenance(request_id, session_id, question, hyp_id)` (`src/cellarium/launch.py:163-178`); the SPA supplies `state._hypSource = {hyp_id, question}` (`apps/web/app.js:1154`); `apps/server.py:304-328` reflects the lifecycle back onto the hypothesis |
| Investigation → runs it read | **Yes**, opt-in | `src/cellarium/evidence.py` — append-only JSONL, one line per tool call, **ids not values**, fields mapped to W3C PROV `activity`/`entity`/`wasGeneratedBy` (`:20-22`); off unless `CELLARIUM_EVIDENCE=1` (`:25-26`) |
| **Council run → investigation** | **No** | `openInCellwright(run)` holds `run.id` (`apps/web/app.js:1173`) but `send()` posts only `{session_id, question, use_council, model, reasoning}` (`:320`), and `sessions` has columns `sid, model, used_council, title, messages, updated` (`apps/sessions.py:35-37`) — **there is nowhere to put it** |
| **Council run → prior Council run** | **No, and destructive** | see §3 |

The launch airlock is the precedent this design generalizes: lineage as a **stored edge** already exists in one
place in this codebase, and it works.

**The Council→investigation edge survives only as English.** `app.js:1180` prefixes the handoff message with
*"The Socratic Council framed this falsifiable hypothesis blind to the data…"*, and `scripts/ab_score.py:42,73`
then **substring-matches that sentence** to exclude Arm A. The project already depends on this edge and already
reconstructs it by string search — the same fragility as `M-10`, in a second place.

## 3. The destructive write — fix this first

`run_council(..., reuse_id=X)` sets `run_id = reuse_id` (`apps/hypotheses.py:163`) and calls `store.create`,
which is an `INSERT OR REPLACE` resetting `rounds="[]"`, `hypothesis="{}"`, `designs="[]"`, `meta="{}"`
(`apps/hypotheses.py:69-74`). **A re-convene overwrites the deliberation it was refining.** M-7's progressive
narrowing (`tests/test_narrowing.py:73-78`) therefore leaves no record of what it narrowed *from*.

This is the first casualty of the missing loop feature and a **standalone win**: fixing it is strictly better
than today even if nothing else in this spec is built (`SP-3a`).

## 4. The representation: Thread · Round · typed `informed_by`

Additive columns on the two existing SQLite tables. No new store, no new object graph. The
`ALTER TABLE … ADD COLUMN` migration idiom is already in place at `apps/hypotheses.py:40-43` (wrapped in
`try/except`, for pre-existing DBs).

```sql
-- council_runs (apps/hypotheses.py:37-39)
ALTER TABLE council_runs ADD COLUMN thread_id   TEXT;     -- the investigation thread
ALTER TABLE council_runs ADD COLUMN round_index INTEGER;  -- 0, 1, 2 … within the thread
ALTER TABLE council_runs ADD COLUMN informed_by TEXT;     -- JSON, TYPED (see below)

-- sessions (apps/sessions.py:35-37) — closes the Council→investigation edge
ALTER TABLE sessions ADD COLUMN thread_id   TEXT;
ALTER TABLE sessions ADD COLUMN from_hyp_id TEXT;
```

`informed_by` is a **typed list**, not a boolean:

```json
[{"kind": "investigation", "id": "s_…"},
 {"kind": "council_run",   "id": "h_…"},
 {"kind": "literature",    "source": "…"}]
```

**Why typed and not `blind: bool`.** Blindness in this project is already scoped *by input class* —
**literature-informed, corpus-blind** (`docs/HYPOTHESIS_MODE_PLAN.md:32-34`), and `tests/test_blindness.py:19-24`
admits `library_brief` into `_ALLOWED_KEYS` at `:23` for exactly that reason. A boolean would be a **lossier
record than the tests already encode**.

**Lineage is derived, never stored twice.** The chain walks the edges —
`council_run → informed_by → session → evidence.jsonl lines for that sid → run ids → manifest rows`. No node
caches its ancestors' contents; **ids only**, which is `evidence.py`'s own stated rule (`:14-16`).

**A re-convene becomes** `round_index + 1` in the same thread with
`informed_by=[{"kind":"council_run","id":<prior>}]`, and **the prior row is preserved**.

**Blindness becomes a query, not a stamp.** `blindness_of(run_id)` returns the transitive **set of input
classes** — `{"literature"}` for a corpus-blind round, `{"literature","corpus"}` for an informed one. Because it
is computed at query time from the chain, a later reader can ask a question we did not think to stamp, e.g.
*"was this round informed by an investigation that only ever read designs below `MIN_SEEDS`/`MIN_GENERATIONS`
(`src/cellarium/support.py:32-33`)?"*

## 5. API + UI surface

| Surface | Change | Anchor |
|---|---|---|
| `GET /api/thread?id=` | **New route** — the ordered chain for a thread: rounds, their `informed_by`, and the sessions/runs each edge reaches | beside the existing routes at `apps/server.py:605-617` |
| `GET /api/hypothesis_get` | carries `thread_id`, `round_index`, `informed_by` | `apps/server.py:301`; the detail pane already renders per-design lifecycle at `:304-328`, so the review pane has a home |
| `POST /api/investigate` | body gains `from_hyp_id` / `thread_id` | `apps/web/app.js:320` → handler `apps/server.py:169-256` → INSERT `apps/sessions.py:72-78` |
| Run list | groups by thread — *round 2 of 3* | `HypothesisStore.list`, `apps/hypotheses.py:111-117` |
| **The button** | **"Re-convene the Council with what Cellwright found"**, on an investigation. Mints round N+1 with `informed_by` pre-filled | new, beside `openInCellwright` (`apps/web/app.js:1173`) |

**The button is the feature.** Today the return leg of the loop is reachable **only by copy-paste** — and
copy-paste is precisely the route that leaves no lineage.

## 6. How the A/B evidence base stays measurable alongside it

The powered Council-vs-Cellwright A/B claim is **already insulated**: the cohort is designated at creation
(`evals/run_ab.py:167-168`, `:208`, `:323` → `evals/results/ab_ledger.json`) and the aggregate reads that
ledger, not `council_runs` (`evals/aggregate_ab.py:24-36`). Informed rounds accumulating in the table cannot
touch it. Two changes make that robust rather than lucky:

1. **`scripts/ab_score.py` selects by the ledger's `run_id` set** instead of substring-matching the question
   text and asserting blindness from `status == "done"` (`:67`, `:74`, `:86`) — filed as **`M-10`**, P1.
2. **`run_ab.py` writes `thread_id` + `round_index=0` + `informed_by=[]` at creation** — a *record* of the
   designation, not a *recovery* of it. Round-0 rows then remain a **superset** of the A/B cohort and can serve
   as an observational replication, while the claim itself continues to rest on the designated set.

## 7. What a user can then ask that they cannot ask today

1. **"Show me the chain behind this claim."** Breaks today at the Council→investigation edge
   (`apps/sessions.py:35-37`).
2. **"Which hypotheses were refined *after* seeing data, and what did they see?"** Unanswerable: `reuse_id`
   deleted the predecessor (`apps/hypotheses.py:163` + `:69-74`).
3. **"Did this conclusion ever leave the runs it started from?"** — was round 3 informed by an investigation
   that only read below the evidential floor (`support.py:32-33`)? A graph query here; a manual transcript read
   today.
4. **"Round 0 vs round 3, side by side."** The honest exhibit for what the loop bought. Today round 0 is gone.
5. **"Which threads converged and which oscillated?"** Rounds-to-convergence *across a thread*, distinct from
   `meta.converged` (`apps/hypotheses.py:185`), which is convergence of **one** debate.

(1)–(4) follow directly from the two missing edges and the destructive write — **CODE-READ**. (5) is
**ARGUED**: a thread-level convergence metric is proposed here, not measured, and cannot be measured until
re-convenes stop being destructive.

## 8. Acceptance tests

- **Non-destructive re-convene** — re-convene an existing run; assert the predecessor row still has its
  `rounds`/`hypothesis`/`designs`, and that the new row has `round_index = prior + 1` and the same `thread_id`.
  (Extend `tests/test_narrowing.py`, which already exercises `reuse_id` twice at `:73-78`.)
- **Edge is stored, not parsed** — open an investigation from a hypothesis; assert `sessions.from_hyp_id` equals
  the hypothesis id **without** reading the transcript text.
- **Typed, not boolean** — a round with a `library_brief` and no corpus input has
  `blindness_of(run) == {"literature"}`, not `unblinded`.
- **Never blocks** — a round with a non-empty `informed_by` completes normally and is returned by the run list.
- **Chain walk** — `GET /api/thread` on a 3-round thread returns the rounds in order with each edge resolved,
  and reaches run ids only through `evidence.py` lines (no cached values).
- **A/B insulation** — with informed rounds present in `council_runs`, `evals/aggregate_ab.py` output is
  byte-identical to the run without them.

## 9. Sequencing

`SP-3a` non-destructive re-convene (standalone win) → `SP-3b` the columns + migration → `SP-3c` the
Council→investigation edge (which also unblocks `SP-1b`, whose own text says it "needs a session↔hypothesis
link") → `SP-3d` `/api/thread` + thread grouping + the re-convene button → `SP-3e` `run_ab.py` writes the
round-0 designation.

## 10. Open — not settled by this spec

- **The out-of-app path.** The button covers the in-app return leg. A user who copies a Cellwright finding into
  a **fresh** Hypotheses question still produces an unlinked round. This spec does **not** close that — by
  design: it stamps nothing and blocks nothing. Whether that residual gap is acceptable is an owner decision.
- **Migration of existing rows.** New columns default to `NULL`, so historical `council_runs` rows are
  indistinguishable between *"no lineage recorded"* and *"lineage was empty"*. Whether to backfill
  `round_index = 0` for all pre-D10 rows is **NOT ESTABLISHED** — the committed `data/sessions.seed.db` snapshot
  was not opened to count how many rows are affected, and some of them may already be informed re-convenes whose
  predecessor `reuse_id` destroyed.
- **`SP-1b` (explicit Cellwright write-back)** — `SP-3c` supplies the session↔hypothesis link `SP-1b` says it
  needs, but whether `SP-1b`'s agent-side write belongs in the same change was not assessed.
