# Held-out set: pre-registration

**Status: registered, seal CLOSED.** Frozen 2026-10-29; this registration written 2026-10-30, before any
held-out report was read.

The authority for every gate in this document is the table in
[`src/cellarium/holdout.py`](../src/cellarium/holdout.py), and `cellarium.holdout.readiness()` is how the
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

Four of the six are the open weakness items. That is deliberate: "finished" means the things already known
to be wrong are no longer wrong. A criterion invented from scratch would be a second chance to pick
thresholds that today's numbers happen to clear.

| gate | asks | threshold | closes |
|---|---|---|---|
| `G1_INDEPENDENT_CHECK` | Does anything in the pipeline check anything else? | `agent_vs_structural_comparison_kind` ∈ {redundant, partial} | ADJ-W1 |
| `G2_ROLE_OVERLAP` | Do the two compared paths cover the same roles? | `agent_vs_structural_role_overlap` ≥ 0.5 | ADJ-W1 |
| `G3_QUOTES_VERBATIM` | Is every kept quote a verbatim span of its own document? | `quote_verbatim_rate` == 1.0 | ADJ-W9 |
| `G4_PARTIALITY_TRAVELS` | Can a summary count over a partly-read document without saying so? | `summaries_carry_partial_flag` is True | ADJ-W8 |
| `G5_MAPPINGS_REVIEWED` | Has anyone but the author checked the value→member mappings? | `applied_mappings_signed_off_by` non-empty | ADJ-W5 |
| `G6_SCORING_IS_MECHANICAL` | Is every held-out number produced by committed, tested code? | `score_produced_by_committed_code` is True | — (mitigation, not a defect) |

Each gate in `holdout.py` also carries a `source` field naming the call that produces its number. A gate
whose measurement has no stated source is a gate somebody fills in by hand at the moment of the run, which is
what `G6_SCORING_IS_MECHANICAL` exists to forbid. Three of the six say plainly that the answer today is no.

`G1` and `G2` are the one that actually blocks today. The two mechanical paths turned out *complementary* —
role overlap about zero, Jaccard 0.004, 30 of 33 reports agreeing on nothing — so their agreement checked
nothing about either of them. Dual extraction's entire value is two independent readings of **one** quantity.
Until two paths read the same fields, every field in this pipeline has a provenance and no check.

`G3` reads 1.0 by construction now: quotes are cut by the platform from the units a record cites, not copied
by the model. The gate stays because a check on a construction is the only thing that can tell you the
construction broke.

### Measurements with no threshold

These have no defensible threshold yet. Not having a threshold is not the same as not having to report it,
and an unreported number is how a known weakness disappears from a result.

| must report | asks |
|---|---|
| `M1_VALUE_OUTSIDE_QUOTE_RATE` | How often is a real span cited for a record it does not support? |
| `M2_UNRESOLVED_REQUIREMENT_RATE` | What share of extracted requirements cannot be costed at all? (79.8% on the development set, before normalisation) |
| `M3_SPAN_FAILURE_RATE` | What share of located sections could not be read at all? |

`M1` is where the risk went when the quote stopped being forgeable: verbatim is not the same as relevant.

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
