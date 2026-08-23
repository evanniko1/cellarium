---
pretty_name: "Cellarium Corpus — a whole-cell E. coli simulation dataset"
license: other
license_name: stanford-academic-s18-475-derived
tags:
  - biology
  - systems-biology
  - whole-cell-model
  - escherichia-coli
  - simulation
  - synthetic-data
size_categories:
  - 100K<n<1M
configs:
  - config_name: manifest
    data_files: "data/manifest/*.parquet"
---

# Cellarium Corpus

A distilled, queryable corpus of **whole-cell *Escherichia coli* simulations** produced with the [Covert Lab wcEcoli model](https://github.com/CovertLab/wcEcoli), plus (optionally) the full raw trajectories. It is the data layer behind **Cellarium** — a grounded agent + Socratic-council that answers whole-cell questions strictly from these results.

## Two tiers

| Tier | What | Where | Size |
|---|---|---|---|
| **Manifest** (always here) | Per-(design, seed) **distilled summaries**: QC verdict, viability, summary-channel means + downsampled trajectories, per-media-segment means, pathway proteome fractions, and a **199-species panel** (terminal count + coarse trajectory) | `data/manifest/*.parquet` | ~MB |
| **Raw** (optional) | Full `simOut` trajectories per run, one `.tar.gz` per lineage | `runs/cellarium/<variant>/<seed>.tar.gz` | ~GBs each |

The manifest answers most questions (panel species, summary channels, viability) with **no download**. Reach for a raw archive only when you need an arbitrary (non-panel) species, full timestep resolution, or FBA fluxes.

## Load the manifest

```python
from datasets import load_dataset
ds = load_dataset("evanniko1/cellarium-corpus", "manifest")   # the distilled corpus
# or directly with DuckDB / pandas over data/manifest/*.parquet
```

Key columns: `perturbation`, `condition`, `timeline`, `seed`, `elongation_model`, `qc`, `reportable`, `generations`, `crashed`, `crash_type`, `division_rate`, `gens_reached`, `channels` (means), `channel_stats`, `series` (downsampled), `pathways`, `species_panel` (per-monomer `{mean, last, series}`), `simout_path`.

### `elongation_model` — filter on this before pooling anything tRNA-related

The model tree carries three translation-elongation models, and **the same column name means a different quantity under each**. `elongation_model` records which one produced a row; a row without it (written before the column existed) is `steady_state`, which is known rather than assumed — no earlier run could select another model.

| value | what it does | `fraction_trna_charged` (86 wide in all three) |
|---|---|---|
| `steady_state` | charging solved as a 20-state ODE indexed by **amino acid**, then broadcast across the family | 21 distinct values in 86 columns; **within-family spread is 0.00 by construction**, not a measurement |
| `kinetic` | per-isoacceptor charging with explicit codon reading (Choi & Covert 2023) | 86 genuinely independent values |
| `coarse_kinetic` | coarse-grained elongation that **does not solve charging at all** | 86 **exact zeros** — the absence of a model, not total de-acylation |

So: never average `fraction_trna_charged` across `elongation_model` values, and never read a within-family spread from `steady_state` rows as evidence about isoacceptors. Two runs of one design under different elongation models are separate experiments — they carry different design tags, different run paths and different dedup keys, and are not replicates of each other. `ppgpp_conc` needs the same care: only `steady_state` runs synthesise or degrade ppGpp, so a flat ppGpp trace under a kinetic model is a missing mechanism rather than a failed stringent response.

## Degradation rates: 854 of 3,133 mRNA units carry a value that is not a fit

Every run in this corpus shares ONE fitted parameter set, produced by the model's parameter calculator
(ParCa). For mRNA degradation, that calculator solves a non-negative least squares over the cistron x
transcription-unit matrix under a lower bound on the rate — and for a large minority of units it does not
return a fitted value at all. Measured on the knowledge base behind most of this corpus
(`kb_sha256 = 3b2f8ebd…`):

| class | units | what the number actually is |
|---|---|---|
| **floor** | 245 | the rate FLOOR — the slowest single measured mRNA cistron in the organism, applied as a lower bound. The solution hit the wall and stopped there |
| **ceiling** | 7 | the rate CEILING — the fastest single measured cistron, applied as an upper bound |
| **imputed** | 602 | the MEAN of the reported half-lives. These units' cistrons were never measured, so they carry a population default |
| *(determined)* | 2,279 | genuinely inferred from data |

**854 units, 27.3% of mRNA units, carrying 12.087% of mRNA expression** in the basal condition (11.165%–15.491%
across 67 conditions). On disk all four classes are the same float in the same array — nothing in `sim_data`
distinguishes a fitted rate from a bound or a default.

**Why this reaches you even if you never ask about half-lives.** A transcript's degradation rate sets its
steady-state level, which sets translation, which sets protein copy number. The two most-expressed not-a-fit
units are RIBOSOMAL PROTEIN operons — `rpmJ` (1.584% of mRNA expression) and
`rplNXE-rpsNH-rplFR-rpsE-rpmD-rplO` (1.582%), both on the floor. Any statement about ribosomal protein
abundance in this corpus rests on a parameter that was bounded rather than measured.

### The index ships with the corpus

`parca/deg_rate_baseline.json` — the 854 unit ids with per-unit expression weights, frozen against the
`kb_sha256` above.
`parca/deg_rate_aliases.json` — the same set joined into GENE space (1,149 genes, 4,557 aliases: symbols,
b-numbers/EcoCyc ids, cistron ids, monomer ids), so you can check a gene without resolving transcription units
yourself.

```python
import json
alias = json.load(open("parca/deg_rate_aliases.json"))
g = alias["alias"].get("rple")                      # any symbol, cistron id or monomer id, lowercased
print(alias["genes"][g])
# {'sym': 'rplE', 'cls': ['floor'], 'pct': 1.581586,
#  'units': ['rplNXE-rpsNH-rplFR-rpsE-rpmD-rplO[c]']}
```

`pct` is the share of TOTAL mRNA expression held by the not-a-fit units that gene belongs to. **These weights
do not sum**: operon co-members each carry the operon's full share, so adding them across genes double-counts.
The corpus figure is 12.087%.

**Scope.** The classification was measured on one knowledge base. It covers 279 of the 363 manifest rows; the
other two arms were fitted separately and the same unit may fall in a different class there. Check
`kb_sha256` on the row before applying it.

## Get a run's full trajectory

```bash
hf download evanniko1/cellarium-corpus --repo-type dataset \
  --include 'runs/cellarium/gene_knockout_001594/000000.tar.gz' --local-dir .
tar xzf runs/cellarium/gene_knockout_001594/000000.tar.gz
```

## Provenance, license & citation

The **software** that produced this data is the Covert Lab wcEcoli whole-cell model, licensed under the **Stanford Academic Software License Agreement (Docket S18-475)** — non-commercial academic use. This dataset contains **derived simulation output**, shared for **non-commercial academic research** with attribution; it is not the wcEcoli software and confers no rights to it. Users of the underlying model must obtain and accept its license separately. If you are the rights holder and have concerns, please open a discussion.

Please cite the wcEcoli model (Macklin et al., *Science* 2020) and this dataset. QC-flagged rows (`qc != "ok"`, including `crashed` lethal KOs and `empty` reads) are **kept on purpose** as first-class negative results — do not treat them as noise.

*Generated with the Cellarium platform.*
