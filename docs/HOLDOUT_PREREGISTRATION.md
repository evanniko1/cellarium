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
| `G2B_STRUCTURAL_COVERAGE` | Of the roles the *table* reading found, how many did the model reading also find? | `agent_covers_structural_roles` ≥ 0.5 | ADJ-W1 — **measured, met (0.869)** |
| `G3_QUOTES_VERBATIM` | Is every kept quote a verbatim span of its own document? | `quote_verbatim_rate` == 1.0 | ADJ-W9 |
| `G7_LEVELS_DERIVED` | Is every `factor:` level derived from the cited span rather than accepted? | `levels_derived_by_platform` is True | ADJ-W10 |
| `G4_PARTIALITY_TRAVELS` | Can a summary count over a partly-read document without saying so? | `summaries_carry_partial_flag` is True | ADJ-W8 (closed 2026-10-30) |
| `G8_SAMPLING_PINNED` | Was the extraction sampled at a pinned temperature? | `extraction_temperature_pinned` is True | ADJ-W7 |
| `G5_MAPPINGS_REVIEWED` | Has anyone but the author checked the value→member mappings? | `applied_mappings_signed_off_by` non-empty | ADJ-W5 |
| `G6_SCORING_IS_MECHANICAL` | Is every held-out number produced by committed, tested code? | `score_produced_by_committed_code` is True | — (mitigation, not a defect) — **met 2026-10-31** |

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
now three states — partial, complete, and *nobody said* — the summaries in
`adjudicate.COMPLETENESS_AWARE` all carry them, and a test enumerates that list rather than trusting a
reader to remember it. It was five; `extraction.mapping_review_sheet` made it six on 2026-10-31, and it
was added **by the test**, which failed until the new summary declared itself. A list nobody can join
quietly is the only kind worth keeping.

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
| `M4_LEVEL_REFUSAL_RATE` | What share of level-bearing records cite a span that states no derivable level? (0.521 then 0.510 over two development runs — **the 0.524 first reported for the second run used an undeclared denominator**) |
| `M5_MODEL_LEVEL_DISAGREEMENT_RATE` | Where a level *could* be derived, how often was the model's own value a different one? (26% on the development set) |
| `M2_UNRESOLVED_REQUIREMENT_RATE` | What share of extracted requirements cannot be costed at all? (**0.569** on the development set, table path; 0.888 on the model path — it was quoted as 79.8% from a stale literal, computed as 0.633, then 0.569 once `ADJ-W12` removed 47 misread demands) |
| `M3_SPAN_FAILURE_RATE` | What share of located sections could not be read at all? |

`M1` **changed meaning on 2026-10-30 and the old reading must not be carried over.** It used to count every
kept level whose value was absent from its own span, and it read 80% (249 of 312). Those records are now
rejected rather than kept — that is `M4` — and a derived level's spelling is a substring of its quote by
construction, so what is left in `M1` is the unverifiable tail: the `factor:` roles with no closed
vocabulary (a shift, a cistron retyping map), which are refused a price rather than costed.

`M4` is where the risk went instead, and it is deliberately not a gate: nobody knows how much of that half is
the model pointing at the wrong unit and how much is a document stating a level in a spelling the frozen
tables do not carry. Widening them to find out is precisely what the contract forbids, so the number is
reported and the vocabulary stays frozen. `M5` keeps the removed behaviour visible, the way `n_rewrote` keeps
the fabricated quote visible after it stopped being able to reach the output.

At readiness time these are supplied as the **development-set** value. The held-out value cannot exist before
the run, so what is being asked is whether the instrument that produces the number exists and produces one —
a result that omits a number because nothing could compute it is the same omission either way.

## G6: the score comes from committed code, and writing it corrected three numbers

`G6_SCORING_IS_MECHANICAL` is the mitigation for the single-annotator limitation rather than a defect found
in the code. One person built the locator, the vocabularies and the mappings and has read the development
set five times; that cannot be undone. What can be done is to keep his reading out of the score, so every
held-out number comes from code that existed **before** the seal was broken. The gate's own words are that
*a number computed by hand at the time of the run is the thing it exists to forbid.*

`src/cellarium/holdout_score.py` is that code and `scripts/score_heldout.py` is its entry point, committed
ahead of the run so the commit preceding the run is the version of the scorer that governed it — the same
rule `separate_commit` states for this registration. The coverage check **reads the gate table in
`holdout.py`** instead of carrying a copy, so a gate added later makes `G6` fail until somebody teaches the
scorer to compute its number.

**It did not pass on the first attempt, and the failures are the argument for the gate.** Three of the
eleven numbers already reported for the development set did not come from their own declared sources:

| number | reported | from its declared source | what happened |
|---|---|---|---|
| `M2_UNRESOLVED_REQUIREMENT_RATE` | 0.798 | **0.633** | a literal typed into a scratchpad script, commented *"before normalisation"*, carried unchanged across every run after it — including the two that changed what normalises |
| `M4_LEVEL_REFUSAL_RATE` | 0.524 | **0.510** | divided by `rejected + derived + unverified`; the registration says `rejected + n_level_records`, and derived+unverified is a *subset* of them (1,305 of 1,378) |
| `G1_INDEPENDENT_CHECK` | `partial` | rule now written down | the gate states a *scalar* comparison over a `source` that is a *distribution* across reports; "18 of 21 eligible reports are partial" became the single value `partial` by a judgement at a console |

`M4`'s correction also means the reproducibility claim made on 2026-10-31 compared two *different formulas*.
Like for like the two runs read 0.521 and 0.510 — still about a point, so the conclusion survives the
correction and the comparison that produced it did not.

**`G1`'s aggregation rule is a choice, so both answers are reported.** `MEASURE_RULES` declares it as the
modal kind over the eligible reports, and declares that the rule was chosen with 18/21 already in view. The
strict alternative — *every* eligible report must be partial — reads `complementary`, because 3 of the 21
share no role at all between the two readings and on those three the agreement checks nothing. The scorer
returns both and flags that they disagree. The modal rule is defended on what the gate asks (whether the
*pipeline* has an internal check) rather than on which answer it gives; the strict rule would also fail a
twelve-document run on one thin table.

**Two defects in the scorer itself were found by running it, not by reading it.**

- Scoring the development dump turned a *missing* `levels_derived_by_platform` key into `False`, and the
  criterion reported `G7` as a **failed gate** — "I could not see it" rendered as "it is broken", this
  project's own recurring bug class aimed at its own completion criterion. Absent and no are now separate
  for every boolean and for the one categorical measurement.
- Running the paid half on one real report found that `extract_report` passed the agent path's *rejected*
  records on and **not its kept ones**. A caller reading `['agent']['kept']` got an empty list from a path
  that had kept sixty records. Nothing failed: role coverage came back 0.0, no report was eligible for the
  comparison, and **a held-out run would have reported the third path finding nothing** about documents it
  had read — on a one-shot set, with no second run to catch it.

What the scorer refuses to do is most of its value. It will not score a document whose bytes do not match
the seal or one the seal never named; it will not average over the reports that worked when one did not
read; it will not report a rate with an empty denominator as 0.0, which would clear two thresholds; and it
will not supply `G5`'s reviewer, which is a person.

## G5: the mapping review is now a page, not a corpus

`G5_MAPPINGS_REVIEWED` asks whether anybody **other than the author** has checked which declared member
each value maps to. No amount of code closes it. A machine checks *membership* — that the chosen value is
in the authority's own set — and does, on every call. Which member is **right** for what the author wrote
is a judgement, and a round-trip through the envelope validates the *design* rather than the mapping:
`Acetate minimal → minimal_acetate` is a correct mapping whose timeline the envelope rightly refuses as a
carbon switch, so a round-trip would report a correct mapping as broken.

So the gate stays unmet — nobody has signed — but the **cost of signing** has changed.
`extraction.mapping_review_sheet` lays out each of the **55** mappings that fired over the development set
with the members it was chosen over, which is the one thing a reviewer cannot judge without:

| role | the author wrote | mapped to | could have been | times |
|---|---|---|---|---|
| `factor:aa_supply` | Clamped Arg (150 uM) | `medium` | `enzymes` | 6 |
| `factor:aa_supply` | Endogenous ON | `enzymes` | `medium` | 65 |
| `factor:medium` | Glucose minimal | `minimal` | `minimal_acetate`, `minimal_succinate`, … | — |

That first row is the point: whether a single-amino-acid clamp is `medium` or `enzymes` is a call no
mechanical check makes, and it is now in front of a reviewer instead of inside a dictionary.

`scripts/mapping_review.py` writes the worksheet plus a sign-off file beside it, and **refuses to build
from the held-out partition** — the worksheet is made by reading the documents, which is the one thing the
seal exists to prevent.

**The sign-off is tied to what was actually seen.** A signature on a worksheet that has since changed means
nothing, so `holdout_score.read_signoff` takes no name from a file whose recorded mappings do not hash to
its recorded digest. The digest covers the `(role, value, member)` triples and *not* the occurrence counts,
so re-running on more documents keeps a signature valid while changing one mapping invalidates it. And it
reports a third category the gate's single string cannot: mappings firing **now** that the sign-off never
covered. That matters on this gate specifically — the held-out documents may use spellings the reviewer
could not have seen, because they were sealed, so a 56th mapping is a gap in the *review*, not grounds for
retroactively voiding it.

## ADJ-W12: a table's title read as its only column header

Found while closing `G6`, by reading what the table path *produced* rather than by reading the parser.
Four of the 33 development reports lay out their design matrix as an ASCII box table:

```
|                     WCECOLI SIMULATION MODULE MATRIX                     |
+---------------+---------------+--------------------+---------------------+
| Configuration | ppGpp Module  | Endogenous Amino   | Extracellular ...   |
| Designation   | State         | Acid Biosynthesis  | Regime / Carbon     |
+---------------+---------------+--------------------+---------------------+
| Config 1      | ON (Dynamic   | Active             | Shift at t=0:       |
| (Wild-Type)   | RelA / SpoT)  |                    | 0.4 mM AA -> 0 uM   |
```

The reader took the first table **line** as the header row. So the one-cell **title** became the header,
a role was matched against the title's own words, and every later line's first cell became a **value** for
that role: 52 records whose values are `Configuration`, `Designation`, `Config 1`, `(Wild-Type)` — row
labels and header fragments, costed and counted as demands on the model, and every one of them
`unresolved`. That is **47 of the 190 unresolved demands** on the whole development set. The two
table-*title* spellings in `COLUMN_ROLES["factor:elongation_model"]` had been added to make that match
work, which cemented it.

Two rules fix it, and **neither is a vocabulary change**: a leading row with fewer cells than the table's
modal row is a title, not a header; and how many lines make one row is set by the **header block's own
line count**, not by adjacency. Adjacency was the first attempt and it is wrong — one layout in the corpus
rules every logical row off (two lines per row) and the other rules only its header (four one-line rows in
a single block), and joining by adjacency read that second table's four simulations as one row whose first
cell was `Config 1 Config 2 Config 3 Config 4`.

**What moved, over the 33 development reports, with the model reading held fixed** (it reads prose spans
and never touches a table, so only one side of the comparison could move):

| | before | after |
|---|---|---|
| structural records | 2,018 | 1,974 |
| design rows asked for | 401 | 375 |
| distinct structural demands | 300 | 255 |
| unmapped column headers counted | 7 | **29** |
| `M2` unresolved rate | 0.633 | **0.569** |
| `G2B` role coverage | 0.745 | **0.869** |
| `G1` under the *strict* rule | `complementary` | **`partial`** |
| `G2` role overlap | 0.165 | 0.165 — *unchanged, still failed* |

**Three of those are gate inputs and all three moved in the favourable direction, which is stated rather
than buried.** The defence is the content of the records, not the direction of the numbers: a cell reading
`Designation` is not an elongation model, and keeping a known-wrong record in order not to improve a gate
would be the worse choice. `G2` not moving is the control.

The most useful consequence was not planned. `G1`'s aggregation ambiguity — documented one section above,
where the strict reading said `complementary` — **dissolved**: all three reports that shared no role with
the model reading had exactly one structural role, `factor:elongation_model`, and it was the misread. With
it gone those three have no table reading at all, so they leave the eligible set and all 18 remaining
eligible reports are `partial`. Both rules now agree. `factor:elongation_model` also vanishes from the
development set's structural roles entirely, which **confirms `ADJ-W3`** rather than contradicting it: the
elongation model really is unstated in every development row, and the four reports that appeared to state
it were an artefact of the reader.

**The dialect is not closed, and the remainder is counted rather than accommodated.** A box-drawn row whose
cells span two lines has no verbatim span to cite, so no quote can be cut from it and the row is **refused
and counted** in `extract_report(...)['structural']['refused_rows']` — 6 rows across 3 reports on the
development set, with their 6 real column headers now in `unmapped_columns`. Reading them needs a quote
model for multi-line cells and six header spellings this vocabulary does not carry. The held-out run will
report those rows as untranscribable, which is what the contract asks for and must not be read as those
documents asking for less.

One note on process, recorded because it happened rather than because it helped: a regex counting `+---+`
lines was run across **both** partitions before the defect was characterised, and it reported that half the
held-out reports contain such lines. That count turned out to be mostly ASCII *diagrams* in prose and
played no part in the fix, which is justified entirely by the four development reports. No held-out
document was read and no pattern derives from one, so the seal's own rule — *no pattern, heading spelling
or alias is added after reading a held-out report* — holds. It is written down here anyway.

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
