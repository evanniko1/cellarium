# Generating the corpus (at scale, on a laptop)

Cellarium's *reasoning* is fresh code; the *simulation* is the public Covert model. Generation drives the
model's own scripts and records a manifest shard. Full `simOut` stays local; the manifest (provenance + QC +
summary channels) is the shareable, mergeable corpus.

> **License note (docs/DECISIONS.md D3):** the model is under Stanford's **academic, non-commercial**
> license and is **not** open source. Obtain it yourself, accept that license, and run it locally. Cellarium
> bundles no model code; any Docker image below is built from *your* checkout and **never published**.

## One-time setup
1. Obtain the model (`git clone https://github.com/CovertLab/wcEcoli`) under its Stanford academic license.
   It needs a Cython/aesara env, so **Docker is easiest** — build a LOCAL image from the model's own
   `docker/local` Dockerfile (do not push it).
2. Point Cellarium at your checkout:
   ```bash
   export WCECOLI_DIR=/path/to/wcEcoli
   export WCECOLI_DOCKER=wcecoli-local   # optional: your locally-built model image (recommended)
   export WCECOLI_PY=python              # used only when WCECOLI_DOCKER is unset (native run)
   export CELLARIUM_OUT=runs
   ```
   With `WCECOLI_DOCKER` set, the runner bind-mounts your checkout into the image
   (`docker run -v $WCECOLI_DIR:/wcEcoli …`) — the model stays in your checkout, never inside a shipped image.
3. Build parameters once (cached by the model):
   ```bash
   python -m cellarium.runner   # runs ParCa via your native env or your local Docker image
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
