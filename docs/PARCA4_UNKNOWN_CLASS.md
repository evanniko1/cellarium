# PARCA-4 — what value does an "unknown" degradation rate get?

**Answering a direct question, 2026-09-10:** the open move on PARCA-4 is an explicit `unknown` class. What
value would those cases then carry? This file answers that, and narrows the item — because a large part of it
turns out to be **already built**.

## 1. The mechanism, read from the code rather than described

`reconstruction/ecoli/dataclasses/process/transcription.py:715-736`. Every transcription unit whose rate was
never measured is parameterised as **floor + a non-negative offset**:

```python
min_deg_rates[is_mRNA] = mRNA_cistron_deg_rates.min()          # the floor: 1.266716e-04 /s = 91.2 min
...
rna_deg_rates_estimated_minus_min, _ = fast_nnls(A, b - Am_measured - Am_min)
rna_deg_rates[~measured] = rna_deg_rates_estimated_minus_min + min_deg_rates
```

`fast_nnls` is **non-negative** least squares, so the offset can be zero but never negative. This matters for
how the defect should be described:

> The estimator does not "fail and fall back to the floor". The floor is a **hard lower bound baked into the
> parameterisation**, and 244 units come out with an offset of *exactly* zero.

There is a symmetric clip above at the fastest measured cistron (`:735-737`), and units whose cistrons were
never measured at all get the **mean** of the reported half-lives. So there are four populations, not two.

## 2. The four populations, and what each value actually means

| class | value it receives | what the number means |
|---|---|---|
| **fit** | NNLS offset > 0 | data constrained it |
| **floor** | 1.266716e-04 /s (t½ **91.2 min**) | *"at least this slow"* — a **bound**, carrying no unit-specific information |
| **ceiling** | 2.888113e-02 /s (t½ **24 s**) | *"at most this fast"* — the symmetric clip |
| **imputed** | mean of the reported half-lives | this unit's cistrons were **never measured**; a population default |

**Measured on the corpus fit** (recorded in `tools.deg_rate_provenance`): **854 of 3,133 mRNA units — 27% —
carry a value that is not a fit**, holding **12.087%** of mRNA expression in basal (11.165–15.491% across the
67 conditions). Of those, 244–245 sit bit-exactly on the floor.

## 3. Most of the "explicit unknown class" already exists

`tools.deg_rate_provenance` **already** classifies four-way and already refuses to merge "I could not find it"
into "it is fine". `agent.SYSTEM` already instructs the agent to call it before reasoning about any half-life.
So at the **reporting layer this is solved.**

**The gap is narrower than the backlog entry implies:** the classification is computed *on demand by a tool*.
It is **not a field in the knowledge base**. `rna_data` carries `deg_rate`, `deg_rate_is_measured` (binary) and
`Km_endoRNase` — so anything reading `sim_data` directly (a simulation, an analysis script, a user of the
HuggingFace dataset) still sees an undifferentiated float, and the binary flag cannot distinguish *estimated
with information* from *pinned at the bound*.

## 4. CORRECTED 2026-09-10 — nothing needs building; it already ships

**An earlier draft of this file recommended adding a stored `deg_rate_class` field to `rna_data`. That
recommendation was wrong and is withdrawn.** It rested on one concrete claim — that a HuggingFace user
reading `sim_data` sees an undifferentiated float — and that claim is false. Checked directly against the
published dataset: **136 files, and not one `simData` or `.cPickle` among them.** The Stanford licence
forbids redistributing the fitted knowledge base (`KB_DIVERGENCE.md:171-172`), so the reader that
justification was written for does not exist.

Removing that limb, nothing was left standing:

| supposed reader | reality |
|---|---|
| a HuggingFace user | never receives the knowledge base at all — `runs/` tarballs only |
| a simulation | needs the number, not its provenance; the class would change no behaviour |
| an analysis script in this repo | calls `deg_rate_provenance`, which already answers |
| someone with their own ParCa build | needs the CODE change, not a field in someone else's pickle |

**And the classification already travels to HuggingFace by another route.** `parca/deg_rate_baseline.json`
is published beside the run archives and carries exactly what the proposed field would have:
`on_floor`, `on_ceiling`, `imputed_average` (602 units, 19.21% of units, **7.482%** of mRNA expression),
`not_a_fit`, `not_a_fit_across_conditions`, `imputation_constant_min` (5.190693 min), and a ranked
`most_expressed_not_a_fit` list naming where it actually bites (`rpmJ[c]` at 1.5845% of mRNA expression,
`rplNXE-rpsNH-rplFR-rpsE-rpmD-rplO[c]` at 1.5816%) — all pinned to the `kb_sha256` it describes.

So the "explicit unknown class" exists in four places already: detected in `_reader_worker.py` (the on-bound
branch at `:922`), exposed as `tools.deg_rate_provenance`, required by `agent.SYSTEM` before any half-life
claim, and shipped to HuggingFace as a standalone artefact that needs no licence-encumbered pickle.

**Adding a field would have cost a new arm** (any change to `rna_data` changes `kb_sha256`, and the 369-row
corpus stops being comparable) **to duplicate something already published.** That is a bad trade, and the
right answer to "what value would the unknown cases receive?" is: **the value they already have, correctly
labelled — which they already are, everywhere a reader can actually reach them.**

## 5. What is genuinely left

Not code. Two documentation items, both cheap:

- **The paper and the HF dataset card should carry the headline figure** — 27% of mRNA units are not fits,
  holding 12.087% of basal mRNA expression — so nobody computes an average half-life over the corpus and
  silently averages bounds together with measurements. The number exists; the warning is not yet where a
  reader will meet it.
- **PARCA-4's own backlog framing is stale.** It calls the explicit `unknown` class "the open move". It is
  not open. What remains open is narrower and worth stating in its place: **the imputation's measured error
  — median 1.41x, 23.4% of values beyond 2-fold** — which is what any `unknown` label should quantify, and
  which is a claim about accuracy rather than a missing feature.
