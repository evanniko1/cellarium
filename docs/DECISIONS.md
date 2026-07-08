# Deferred decisions

Design choices intentionally postponed. Revisit when noted.

## D1 — HuggingFace-mediated sharing of full `simOut` (deferred)
**Context.** The shared corpus manifest (Parquet shards + DuckDB) aggregates *summary + QC + a curated
species panel* across contributors (Evangelos, and possibly Filippo). But **full `simOut`** (all ~12,000
count series + ~9,600 fluxes per trajectory) lives on the machine that generated it — too large to sync
between laptops via git. So `read_species` gives full time-series depth only for **locally-available**
trajectories.

**Deferred decision.** How to mediate cross-contributor access to full `simOut` — most likely a
**HuggingFace dataset** (or object store) holding full tensors for a curated subset of trajectories, so
either contributor can deep-query the other's runs. Decide: which subset, tensor format, upload cadence.

**Why it matters beyond this hackathon.** This is exactly the sharding + full-tensor packaging problem
that **"The Well, for the Cell"** needs — so whatever we choose here should slot into that dataset work
(reproducible shards, checksummed manifests, leakage-free splits). Treat this as the seed of that pipeline.

## D3 — Model licensing & data distribution (constraint, not deferred)
The whole-cell *E. coli* model is under the **Stanford Academic Software License (Docket S18-475)** —
**not** open source: non-commercial academic use only; the Software and its derivatives may not be
redistributed without Stanford's written permission (§§5, 6, 8, 11). Consequences for Cellarium:
- **Do** use it for non-commercial academic research (running sims locally) and **do** publish results
  (papers/figures + the data behind them) *with acknowledgment* (§12 anticipates this) — low risk.
- **Do NOT** bundle/vendor/redistribute the model. Cellarium points at a user-obtained checkout; any Docker
  image is built locally from that checkout and **never published**.
- **Distributing a large standalone simulation dataset publicly** (e.g. "The Well, for the Cell") is the one
  action that **requires Stanford's written permission** — the license's own mechanism. This is a
  grant/dataset-level action, **not a hackathon blocker** (the hackathon submits code + a local demo; the
  corpus stays local). Track alongside D1. (Not legal advice.)

## D2 — Curated species panel for the manifest (deferred)
The manifest stores summary stats for a curated panel of high-interest species (TFs, key enzymes,
ribosomes, ppGpp, stress/AMR set). **Contents deferred until we have real simulation results** to see which
species carry signal. For now the manifest records the standard channels + provenance + QC only; the panel
is a config list, initially minimal.
