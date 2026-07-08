# Generating the corpus (at scale, on a laptop)

Cellarium's *reasoning* is fresh code; the *simulation* is the public Covert model. Generation drives the
model's own scripts and records a manifest shard. Full `simOut` stays local; the manifest (provenance + QC +
summary channels) is the shareable, mergeable corpus.

> **License note (docs/DECISIONS.md D3):** the model is under Stanford's **academic, non-commercial**
> license and is **not** open source. Obtain it yourself, accept that license, and run it locally. Cellarium
> bundles no model code; any Docker image below is built from *your* checkout and **never published**.

## One-time setup
1. Obtain the model (`git clone https://github.com/CovertLab/wcEcoli`) under its Stanford academic license,
   and build a **LOCAL** image from its own Dockerfile (model + compiled Cython baked in; **never push it**):
   ```bash
   cd /path/to/wcEcoli && docker build -t wcecoli-sim -f docker/local/Dockerfile .
   docker images | grep wcecoli-sim        # confirm the tag
   ```
2. Point Cellarium at the image + a host output dir:
   ```bash
   export WCECOLI_DOCKER=wcecoli-sim       # the local model image (recommended path)
   export CELLARIUM_OUT=$(pwd)/runs        # host dir where simOut + sim_data land
   # native fallback instead of Docker: unset WCECOLI_DOCKER and set WCECOLI_DIR + WCECOLI_PY
   ```
   The runner mounts **only the output** (`docker run -v $CELLARIUM_OUT:/wcEcoli/out -e PYTHONPATH=/wcEcoli
   -w /wcEcoli wcecoli-sim python …`). It does **not** mount the checkout over `/wcEcoli` — that would shadow
   the compiled model. The model stays inside your local image; nothing is redistributed.
3. Build parameters once (cached under `$CELLARIUM_OUT/cellarium/kb`):
   ```bash
   python -m cellarium.runner
   ```

## Run a campaign
```bash
python -m cellarium.generate --seeds 4 --generations 1                 # sequential
python -m cellarium.generate --seeds 4 --generations 1 --parallel 3    # 3 sims at once
```
Every design is envelope-checked before running; each generation is QC'd; degenerate runs are recorded as
non-`ok` and never turned into a doubling time. The batch is crash-isolated — a failed sim is logged and
skipped, and the shard is written for whatever completed. Run continuously (and on Filippo's machine too) to
build a few-thousand-trajectory corpus over the week.

## Performance
A single-generation sim is ~10–20 min wall-clock on a laptop. The reliable throughput lever is
**`--parallel N`**: sims are independent and each design now writes a distinct output dir, so N run
concurrently for a near-linear speedup — bounded by cores and RAM (each sim loads ~1 GB of `sim_data`; start
at `--parallel 2–3`).

On BLAS: the `numpy.distutils ... netlib Blas` and `aesara.tensor.blas` warnings are **not** numpy/scipy
running unoptimized — their PyPI wheels bundle OpenBLAS and the image sets `OPENBLAS_NUM_THREADS=1`. The
warnings are a cosmetic build-time probe plus **aesara** falling back to the numpy C-API because it can't find
a *system* BLAS to compile its ops against. Rebuilding the model image with `libopenblas-dev` + aesara
`blas__ldflags` set *may* speed aesara's ops, but the payoff is uncertain and it's a model-image change that
can affect determinism. Prefer `--parallel` first.

## Design space
The default campaign is a small in-envelope trio: minimal-glucose steady state (`wildtype`), rich minimal+AA
steady state (`condition` idx 4 = `with_aa`), and the AA-downshift transient (`timeline`). To go wider:

```bash
python -m cellarium.reader --variant-map          # derive gene-KO + condition indices from sim_data (once)
python -m cellarium.generate --knockout tRNA --seeds 2      # a gene-KO panel matching an rna_id query
```
`--variant-map` unpickles `sim_data` and caches `data/cache/variant_map.json` (local only, regenerable):
`conditions` (index -> media, e.g. `4: with_aa`, `5: acetate`) and `genes` (rna_id -> KO index). **Always take
indices from this map, not from a variant's docstring** — the orderings drift across model builds (the
`condition` docstring says +AA is index 1, but this build has it at 4). Lethal KOs are fine to run: the QC
guardrail records them non-`ok` (no division) instead of inventing a doubling time.

## Merge two contributors' shards
Both people commit their `data/manifest/*.parquet` shards (small). The corpus is their **union** — DuckDB
reads them as one table automatically. No database to host, no merge step.
`read_species` gives full time-series depth for **local** trajectories; cross-contributor deep dives wait on
the HF full-`simOut` decision (docs/DECISIONS.md D1).

## Verify a first run
After one campaign, check the manifest:
```bash
python -c "import duckdb; print(duckdb.sql(\"select perturbation,condition,seed,qc,growth_rate,ppgpp_conc from read_parquet('data/manifest/*.parquet')\").df())"
```
> First-run note: simOut is read **inside the model image** (`_reader_worker.py`, where `wholecell` lives);
> the host only consumes its JSON. After your first sim, dump the real listener schema with
> `python -m cellarium.reader` and confirm the table/column names in `_reader_worker.py`
> (`SUMMARY_CHANNELS`, `SPECIES_SOURCES`) — they are the public schema but can drift across model releases.
