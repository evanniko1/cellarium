# Context truncation — the funnel, and two defects it taught us

**Methods record for PLAT-2.** Every tool result passes through one funnel on its way into the model's
context (`agent._truncate_tool_result` → `truncation.trim`). This documents what the funnel guarantees, and
the two defects found while building it — both introduced by the fix for the previous problem, both found by
running the code at several context budgets rather than by reading it.

Written up because the failures are general. Neither is specific to this corpus: any system that trims a
payload and then annotates the trim can hit both.

---

## What the funnel guarantees

| Guarantee | Why it is not optional |
|---|---|
| The output is **valid JSON** | A mid-string cut severs the payload, and the tail of a survey or a `top_movers` list disappears with no marker. The model reads a fragment and cannot tell it is one. |
| Lists shrink; **strings are never sliced** | The scalar and provenance fields are the part a claim rests on. Slicing takes them off the end at random. |
| The omission is **named**, not just counted | "31 of 37" says something is missing and nothing about whether it mattered. `seeds 4, 5, 6 dropped` says whether the answer is still about the question asked. |
| `n_total` is the **original** count | A second trim must never report "N of the already-trimmed M", or each pass makes the loss look smaller than it is. |
| Trimming below the evidential floor **refuses** | `support.MIN_SEEDS = 2` is the line between a measurement and a case study. A result that falls below it *because of context pressure* is that defect arriving by a road with no trace in the payload. |
| A refusal is **never sliced** | A truncated refusal reads like a result. Refusals are returned whole even when they overflow a tight budget. |

---

## Defect 1 — the funnel emitted invalid JSON, which is the one thing it exists to prevent

**What it did.** Trim the rows until the payload fit `cap - 220`, reserving 220 bytes for the note about
what had been removed. Then append the note.

**Why it broke.** The note lists *identities*, and identities are long. When it exceeded the reserved 220
bytes the finished payload was over budget, and the caller's last resort — a hard string slice at `cap` — cut
the JSON mid-string.

> Packing a box, leaving a fixed gap for the packing slip, finding the slip is longer than the gap, and
> shearing the lid off to make it close.

**How it was found.** Probing four context budgets (4000 / 1500 / 900 / 500) and parsing each result.
`cap=900` failed. Reading the code would not have surfaced it: the arithmetic is only wrong when the note
happens to be long, which depends on how many identities were dropped.

**The fix — stop estimating, start measuring.** `truncation.trim` assembles the *complete* candidate payload
(rows + markers + omission block), measures it, and shrinks again if it is over. There is no reserved-byte
constant anywhere in the final code, because a reserved-byte constant is a guess about a quantity that can be
computed exactly.

**Pinned by** `test_truncation.py::test_the_funnel_always_emits_valid_json`, parametrized over eight budgets —
the probe that found it, promoted to a test.

---

## Defect 2 — it spent the identities to save bytes, then removed the rows anyway

**What it did.** The fix for Defect 1 shrank in one monotone direction: over budget → first reduce the
omission detail, then (still over) drop rows. Once the detail reached zero it never came back.

**Why it broke.** After dropping rows there was room again, and nothing put the identities back. Measured at
`cap=4000` on a 40-row payload: **10 rows dropped, every identity discarded, and the result came in at 3,728
bytes — 272 under budget.** The two-phase version returns the same 30 rows *with all 10 identities* at 3,841
bytes. The names cost 113 bytes and were thrown away for nothing.

> Over the airline weight limit, so you bin the packing list, then remove three shirts — and land under the
> limit with room for the list you already threw out.

**The fix — two phases, in the order that matches what the data is for.**

1. **Phase A** settles the *rows* with the omission detail at its cheapest. The rows are the answer.
2. **Phase B** holds the rows fixed and grows the detail back — 1, 2, 5, 10, 20, 40 identities — while it
   still fits. The note gets every byte the answer did not need.

A note about the data must not cost the data; but it must also not be sacrificed for space the data then
gives back.

**Pinned by** `test_the_dropped_items_are_named_not_just_counted` and
`test_the_marker_the_model_reads_names_them_too`.

---

## Behaviour after both fixes

40 rows, five representative context budgets:

| cap | valid JSON | identities in `_omitted` | named in the in-list marker | refusal |
|---|---|---|---|---|
| 6000 | ✓ | — (nothing trimmed) | — | no |
| 4000 | ✓ | **10** | ✓ | no |
| 2000 | ✓ | 0 | ✓ | no |
| 900 | ✓ | 0 | ✓ | no |
| 500 | ✓ | — | — | **yes** |

Two things worth reading off this table:

* **The marker keeps naming after the structured block runs out of room.** `_omitted` is the machine-readable
  record; the marker (`…[10 of 40 'results' dropped: run_30, run_31 … — narrow the query to see them]`) is
  what the model reads mid-payload. At tight budgets the structured block degrades to counts while the marker
  still names up to eight, so the identities reach the model either way. That is designed degradation, not a
  residual defect.
* **The refusal at `cap=500` is the floor doing its job.** Trimming that far would leave fewer than
  `MIN_SEEDS` seeds, so the funnel returns a refusal naming the scope it refused and a narrower scope that
  would qualify, rather than an under-powered answer with a footnote.

---

## The general lesson

Both defects were introduced by the fix for the previous problem, and both were invisible to inspection:

1. **A reserved-byte constant is a guess about a computable quantity.** Assemble and measure.
2. **A monotone shrink strategy strands resources.** If two things compete for a budget, decide the priority
   order explicitly and then *re-check* whether the lower-priority one fits after the higher-priority one has
   settled.
3. **Probe the parameter, don't reason about it.** Both were found by running the same payload at several
   context budgets. The bug in each case was conditional on a size relationship that no single test budget
   would have exposed — which is why the budgets are now a `parametrize` list rather than one number.
