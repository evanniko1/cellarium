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
