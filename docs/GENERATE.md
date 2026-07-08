# Generating the corpus (at scale, on a laptop)

Cellarium's *reasoning* is fresh code; the *simulation* is the public Covert model. Generation drives the
model's own scripts and records a manifest shard. Full `simOut` stays local; the manifest (provenance + QC +
summary channels) is the shareable, mergeable corpus.

## One-time setup
1. Get the **public** model: `git clone https://github.com/CovertLab/WholeCellEcoliRelease` (or use its Docker
   image — the model needs its Cython/aesara env; Docker is easiest on Windows/Mac).
2. Point Cellarium at it:
   ```bash
   export WCECOLI_DIR=/path/to/WholeCellEcoliRelease
   export WCECOLI_PY=python            # or the interpreter inside the model's Docker
   export CELLARIUM_OUT=runs
   ```
3. Build parameters once (cached by the model):
   ```bash
   python -m cellarium.runner  # or, inside the model env: python runscripts/manual/runParca.py cellarium
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
