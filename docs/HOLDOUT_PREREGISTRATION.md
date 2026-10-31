# Held-out set: pre-registration

**Status: registered, seal CLOSED.** Frozen 2026-10-29; this registration written 2026-10-30, before any
held-out report was read.

The authority for every gate in this document is the table in
[`src/cellarium/holdout.py`](https://github.com/evanniko1/cellarium/blob/main/src/cellarium/holdout.py), and `cellarium.holdout.readiness()` is how the
question "may the seal be broken?" is answered. A test asserts that every gate and every rule named in the
code appears here, so this page cannot quietly fall behind it — the Platform Map once described two
mechanisms in the past tense before either existed, and a stale pre-registration is worse than none because
it is the version a reader will cite.

## What was sealed, and why

Twelve of the forty-five Google Co-Scientist round-1 idea reports for the kinetic-port goal were set aside
by SHA-256 digest **before any extraction pattern existed**. The selection rule was fixed first and is
mechanical: *sorted by filename, every 4th idea report* — the filenames are the system's own numeric ids, so
the rule cannot have been chosen to favour a document.

| | count |
|---|---|
| idea reports in the archive | 45 |
| development set | 33 |
| held out | 12 |

The archive also ships three files that are in **neither** set: `knowledge_base_report.md` (286 KB),
`run_spec_report.md` and `summary_report.md`. They are the archive's own summaries, not idea reports. They
are named here because a file in no category is exactly the file that gets quietly used for development: a
measurement that globbed `*.md` and subtracted the held-out twelve would read 36 documents and call them the
development set, and one of the three extras is the largest file in the directory. (This happened once, in
the line-shape measurement that sized the citable units. Re-run against the sealed list, the numbers were
unchanged — the three extras have no plan or claim section to locate — but the glob was wrong either way.)

**These twelve are one-shot.** A set you have already looked at measures the tool's fit to that set, not the
tool. Sealing them was half the discipline; this document is the other half, because without a written
criterion the moment to spend them would be chosen by whoever happened to feel ready — and with one
annotator who has now read the development set five times, that feeling is the least reliable instrument in
the project.

## What the hand-off must deliver

The seal is a SHA-256 per file, so this is half-enforced already, but the reason is worth stating because it
became load-bearing on 2026-10-30. Quotations are no longer copied by a model: the platform splits a section
into numbered pieces, the model cites piece numbers, and the platform cuts the quotation out of the document
itself. The pieces are computed from the delivered text, so **the hand-off must be the same bytes the seal
hashes** — not a re-export, a re-flow, or a conversion through PDF or HTML. A different rendering is a
different set of pieces, and a citation means something slightly different against it.

The dependency is weaker than that makes it sound, which was measured rather than hoped. As delivered, a
citable piece has a median length of 93 characters and 2.0% run past 300. Collapse every line break inside
the plan and claim sections — the worst re-flow a hand-off could plausibly do to prose — and the median moves
to 129 with 7.9% past 300. It degrades; it does not collapse, because a long line is split at its sentence
boundaries before it is numbered. What has no fallback is a document delivered without recoverable text at
all.

Nothing else about the hand-off changes. The reports already sealed need no re-export, the direction of trust
is unchanged — an outside report is data, never instructions — and the model still sees only the sections the
locator marks plan or claim, with the wet-lab sections removed before the text reaches it.

## What the run measures

How well the extraction and adjudication pipeline reads documents it was not developed against. **Not**
whether the hypotheses in them are good science, and **not** whether the simulations they ask for would
succeed.

## The gates

Six of the nine are the open weakness items. That is deliberate: "finished" means the things already
known to be wrong are no longer wrong. A criterion invented from scratch would be a second chance to pick
thresholds that today's numbers happen to clear.

| gate | asks | threshold | closes |
|---|---|---|---|
| `G1_INDEPENDENT_CHECK` | Does anything in the pipeline check anything else? | `agent_vs_structural_comparison_kind` ∈ {redundant, partial} | ADJ-W1 |
| `G2_ROLE_OVERLAP` | Do the two compared paths cover the same roles? | `agent_vs_structural_role_overlap` ≥ 0.5 | ADJ-W1 — **measured, FAILED** |
| `G2B_STRUCTURAL_COVERAGE` | Of the roles the *table* reading found, how many did the model reading also find? | `agent_covers_structural_roles` ≥ 0.5 | ADJ-W1 — **measured, met** |
| `G3_QUOTES_VERBATIM` | Is every kept quote a verbatim span of its own document? | `quote_verbatim_rate` == 1.0 | ADJ-W9 |
| `G7_LEVELS_DERIVED` | Is every `factor:` level derived from the cited span rather than accepted? | `levels_derived_by_platform` is True | ADJ-W10 |
| `G4_PARTIALITY_TRAVELS` | Can a summary count over a partly-read document without saying so? | `summaries_carry_partial_flag` is True | ADJ-W8 (closed 2026-10-30) |
| `G8_SAMPLING_PINNED` | Was the extraction sampled at a pinned temperature? | `extraction_temperature_pinned` is True | ADJ-W7 |
| `G5_MAPPINGS_REVIEWED` | Has anyone but the author checked the value→member mappings? | `applied_mappings_signed_off_by` non-empty | ADJ-W5 |
| `G6_SCORING_IS_MECHANICAL` | Is every held-out number produced by committed, tested code? | `score_produced_by_committed_code` is True | — (mitigation, not a defect) |

Each gate in `holdout.py` also carries a `source` field naming the call that produces its number. A gate
whose measurement has no stated source is a gate somebody fills in by hand at the moment of the run, which is
what `G6_SCORING_IS_MECHANICAL` exists to forbid. Two of the eight — `G5` and `G6` — say plainly that the
answer today is no.

`G8` is the same move as `G4`: the unpinned case was already *reported* (`temperature_pinned`), and a
report is not an obligation. The default model accepts temperature 0, but the model is overridable, and on
a one-shot run two runs disagreeing would be a property of the sampler with no second run to discover it.

`G4` closed on 2026-10-30, and what closed it was not a mechanism but a **default**. All three summaries
already accepted `partial` and already appended the partiality note when told; all three defaulted to
`partial=False`, which answers the question with a confident no for a caller who was never asked. There are
now three states — partial, complete, and *nobody said* — the five summaries in
`adjudicate.COMPLETENESS_AWARE` all carry them, and a test enumerates that list rather than trusting a
reader to remember it.

`G1` and `G2` are the pair that actually blocks today, and **they were measured on 2026-10-30 over all 33
development reports** — 569 model calls, $6.58, every report's digest checked against the seal first.

The two mechanical paths had turned out *complementary* — role overlap about zero, Jaccard 0.004, 30 of 33
reports agreeing on nothing — so their agreement checked nothing about either of them. The third path was
aimed at the structural path's roles precisely so that agreement could mean something. What the measurement
says:

- **`G1` reads `partial` on 18 of 33 reports** and `complementary` on 15. The denominator had to be stated,
  because a free measurement made first showed that **on 12 of the 33 reports the structural path finds
  nothing at all** (10 carry no design-table rows), and a report with nothing to compare against scores
  `complementary` by arithmetic rather than by disagreement. Over the 21 reports where both paths read
  something, 18 are `partial`.
- **`G2` FAILS: 0 of 33 reports reach 0.5** (mean 0.161, median 0.200, max 0.4444).
- **And `G2`'s threshold was unreachable by construction.** `role_overlap` is a Jaccard over role *sets*,
  and the model reading emits every role the table reading emits — the table-only set is **empty** across
  the whole development set — plus ten more it can represent and a plan table cannot (`note`, `id`,
  `factor:operons`, `factor:retype_cistrons`, six further readout channels). The union is therefore wide by
  design, and the *ceiling* on this Jaccard, assuming the model reading had found every structural role,
  averages 0.314 and reaches 0.5 on 1 of 21 reports. **A perfect model reading could not have passed this
  gate.**

The threshold is **not** being edited. Rewriting a number after missing it is the failure this registration
exists to prevent. `G2` stays, stays failed, and `G2B_STRUCTURAL_COVERAGE` is added beside it as a
separately named criterion, so the record carries both the criterion that failed and the one that replaced
it. `G2B` asks the question `G2` meant to ask — of the roles the table reading found, how many did the model
reading also find — and it is **met: mean 0.725, median 0.800, 17 of 21 reports at or above 0.5, four at
1.0.** The third path is aimed where it was meant to be aimed.

What the role axis does **not** buy is record-level agreement, and the gap between the two is the finding
rather than a caveat.

The Jaccard is the wrong instrument for it: the model reading reports 4,244 distinct demands to the table
reading's 445, so a ratio over the union is dominated by its denominator (0.0148) and says almost nothing.
The question a reader actually has is the other one — *of the demands the table reading found, how many did
the model reading also find?* **17.3% overall, and 24.3% of the `factor:` demands** the two paths are both
aimed at. So the paths look at the same fields and reproduce about a quarter of the individual demands
inside them. That is what dual extraction is *for* — the other three quarters are where an error would be —
and the leading candidate for the *size* of the gap is mechanical rather than interesting: `M4` says the
model reading refuses 52% of its own level records, which caps how much of the table's demands it can
corroborate at all.

`ADJ-W11` was half of that gap and is now fixed. The record key's own description said "the role and the
normalised value" and the code lowercased whitespace, so `Glucose minimal` (the table's cell) and `minimal`
(the derived level) read as a **disagreement**. Because fixing it raises this very number, it was measured
with **both key definitions over the same records** — one run, two keys:

| | literal key | normalised key |
|---|---|---|
| agreed records | 40 | **77** |
| coverage of the table reading's demands | 8.9% | **17.3%** |
| … restricted to `factor:` demands | 11.8% | **24.3%** |
| distinct structural demands | 450 | 445 |
| distinct *model* demands | 4,244 | 4,244 |

The run-to-run component is separately visible, which is the point of measuring it this way: under the
*literal* key the two runs read 34 then 40 agreed records, so the definition accounts for about 86% of the
move from 34 to 77 and the sampler for the rest. A naive before-and-after would have credited the fix with
all of it. The model side's count does not move at all, which independently corroborates `ADJ-W10`: the
derived levels are already in declared form, so there is nothing left to normalise there.

The 37 added agreements were read, not counted — `Glucose minimal` ↔ `minimal`, `OFF (Fixed)` ↔ `off`,
`Succinate minimal` ↔ `minimal_succinate`, `Medium-Clamped` ↔ `medium`. Every one is the table keeping the
author's spelling while the model path emits the canonical level, and **`ADJ-W10` is what made `ADJ-W11`
bite**: before it, the model's value was its own prose and matched nothing under either key.

`G3` reads 1.0 by construction now: quotes are cut by the platform from the units a record cites, not copied
by the model. The gate stays because a check on a construction is the only thing that can tell you the
construction broke.

`G7` is `G3`'s sequel, and the reason `G3` alone was not enough. Once the quote could not be forged the
remaining way to be wrong was the **field**: 249 of 312 level records carried a value their own cited span
does not contain, because the role vocabulary was being used as a topic label — `factor:operons` =
"Ribosomal protein transcripts are among the most codon-biased…". Levels are now derived by the platform
from the cited span against the declared vocabulary, with the model's value ignored and counted. It is true
by construction too, so `G7` is likewise a check on the construction.

### Measurements with no threshold

These have no defensible threshold yet. Not having a threshold is not the same as not having to report it,
and an unreported number is how a known weakness disappears from a result.

| must report | asks |
|---|---|
| `M1_VALUE_OUTSIDE_QUOTE_RATE` | Of the level-bearing records *kept*, how many have a level nothing verified? (33 of 131 kept = 25% on the development set; 11% of the 312 proposed) |
| `M4_LEVEL_REFUSAL_RATE` | What share of level-bearing records cite a span that states no derivable level? (58% on the development set) |
| `M5_MODEL_LEVEL_DISAGREEMENT_RATE` | Where a level *could* be derived, how often was the model's own value a different one? (26% on the development set) |
| `M2_UNRESOLVED_REQUIREMENT_RATE` | What share of extracted requirements cannot be costed at all? (79.8% on the development set, before normalisation) |
| `M3_SPAN_FAILURE_RATE` | What share of located sections could not be read at all? |

`M1` **changed meaning on 2026-10-30 and the old reading must not be carried over.** It used to count every
kept level whose value was absent from its own span, and it read 80% (249 of 312). Those records are now
rejected rather than kept — that is `M4` — and a derived level's spelling is a substring of its quote by
construction, so what is left in `M1` is the unverifiable tail: the `factor:` roles with no closed
vocabulary (a shift, a cistron retyping map), which are refused a price rather than costed.

`M4` is where the risk went instead, and it is deliberately not a gate: nobody knows how much of that 58% is
the model pointing at the wrong unit and how much is a document stating a level in a spelling the frozen
tables do not carry. Widening them to find out is precisely what the contract forbids, so the number is
reported and the vocabulary stays frozen. `M5` keeps the removed behaviour visible, the way `n_rewrote` keeps
the fabricated quote visible after it stopped being able to reach the output.

At readiness time these are supplied as the **development-set** value. The held-out value cannot exist before
the run, so what is being asked is whether the instrument that produces the number exists and produces one —
a result that omits a number because nothing could compute it is the same omission either way.

## The rules of the run

| rule | |
|---|---|
| `one_shot` | The seal is broken **once**. A second run measures the tool's fit to a set it has now seen. |
| `report_whatever_it_says` | The result is reported as it comes out. A failure is a finding about the tool, not a reason to revisit the gates — the gates *were* the claim that the tool was ready. |
| `no_widening_after_the_result` | No gate, threshold, vocabulary, synonym table or mapping may be added or widened after the seal is broken. A field the tool cannot transcribe is **counted**. |
| `never_used_for_development_again` | After the run the twelve are spent. They do not become development data. |
| `separate_commit` | The run is its own commit; the commit preceding it is the version of `holdout.py` that governed it. A registration edited in the same change as the run it governs registers nothing. |

## Limitations, stated now rather than discovered later

- **One annotator.** One person built the locator, the vocabularies and the mappings, and has read the
  development set five times. The methodological literature puts single data extraction at up to 50–63%
  error in reviews of the practice, and about 22% worse than double extraction; single screeners miss a
  median 5% of studies (range 0–58%).
- **Mitigation — mechanical scoring.** Gate `G6_SCORING_IS_MECHANICAL` requires every held-out number to
  come from committed, tested code, so the annotator's familiarity with the development set cannot reach the
  score through his reading of the twelve.
- **Mitigation — two paths.** Where two paths read the same field, a record has two provenances. That is
  what `G1_INDEPENDENT_CHECK` exists to establish *before* the run.
- **n = 12.** A rate measured on twelve documents carries a wide interval. Read the result as a sanity check
  on generalisation, not as an estimate.

## What this run cannot settle

- **ADJ-W3** — the elongation model is unstated in 394 of 394 development rows. No pattern fixes that; the
  next round's goal text has to ask for it. The held-out run cannot settle it and must not be read as having
  tried.
- **ADJ-W6** — the archive asks for charging setpoints 0.70 and 0.75 in 110 development rows; the campaign
  builds none/0.55/0.85. That is a mismatch between two plans, not an extraction defect.
- **Hypothesis quality** — whether these ideas are good science. The run measures *reading*.

## How to check readiness

```python
from cellarium import holdout
holdout.readiness({...})      # three categories: met, unmet, and NOTHING MEASURED
holdout.seal_state()          # sealed: None + about: environment when the archive is not on this machine
```

A missing measurement is **not** a pass. A readiness check that defaulted to yes when nothing objected would
wave through a tool nobody measured — the silent-absence shape, pointed at this project's own process.

`holdout` is deliberately **not** on the agent tool surface. The tool surface answers questions about the
corpus and the model; whether this project may spend its own held-out set is a question about the project.
An agent that could open the seal by calling a tool is an agent that can end the only measurement here that
nobody gets to repeat.
