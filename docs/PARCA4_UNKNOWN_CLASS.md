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

## 4. Recommendation: label the values, do not change them

**Do not re-fit.** Three reasons, in order of force:

1. **A new value mints a new arm.** Changing any fitted parameter changes `kb_sha256`, and the existing
   369-row corpus stops being comparable to anything produced afterwards. That is REPRO-1's entire problem;
   paying it again to relabel a number would be a poor trade.
2. **There is no better number on offer.** Four candidate estimators, both hyper-parameters tuned by nested
   cross-validation, all scored on held-out measurements under a rule fixed in advance: **none beat the
   shipped estimator.** Ridge — the design's own preferred remedy — failed most informatively.
3. **The harm was never the number.** A floor value is a legitimate statement (*"at least this slow"*). The
   harm is that it is **indistinguishable from a measurement** when read out of `sim_data`. That is fixed by
   labelling, at zero simulation cost.

**So the concrete change is to promote the existing four-way classification from a tool into a stored field** —
`deg_rate_class` ∈ {`fit`, `floor`, `ceiling`, `imputed`} on `rna_data`, beside `deg_rate_is_measured` — so it
travels with the data into the HF dataset and into every downstream reader, instead of being recoverable only
by calling a tool that a non-Cellarium user does not have.

Detection needs no new fitting: `floor` is `deg_rate == min_deg_rate` bit-exactly (equivalently, NNLS offset
== 0), `ceiling` likewise against the clip, and `imputed` is already known at assignment time.

**Cost note, and the reason this is still not free:** adding a field to `rna_data` changes the pickle, hence
`kb_sha256`, hence the arm — even though every *value* is unchanged. So it should ride along with the next
rebuild that happens for another reason, not trigger one. PARCA-4's existing "if it ships, it ships with
company" note already says exactly this about the declined coverage filter and the `deg_rate_is_bound`
provenance field: **one arm, everything at once.**

## 5. What stays open

- Whether `deg_rate_class` belongs on `rna_data` (per transcription unit) or `cistron_data` too.
- Whether the HF dataset card should carry the 27% / 12.087% figures prominently — a user computing mRNA
  stability statistics from the corpus would otherwise average bounds together with fits.
- The imputation's own measured error, which is what an `unknown` label should quantify: **median 1.41x, and
  23.4% of values beyond 2-fold.**
