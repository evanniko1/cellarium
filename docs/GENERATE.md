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
python -m cellarium.generate --seeds 4 --generations 1      # writes data/manifest/<user>-<stamp>.parquet
```
Every design is envelope-checked before running; each generation is QC'd; degenerate runs are recorded as
non-`ok` and never turned into a doubling time. Run continuously (and on Filippo's machine too) to build a
few-thousand-trajectory corpus over the week.

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
> First-run note: confirm the listener table/column names in `simout.py` (`SUMMARY_CHANNELS`,
> `SPECIES_SOURCES`) against your model version's `columnNames()` — they are the public schema but can drift
> across model releases.
