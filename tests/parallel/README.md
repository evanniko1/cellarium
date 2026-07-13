# Parallel-execution test — N whole-cell sims, one Docker container each

Cellarium runs an in-envelope `design × seed` matrix as a campaign; with `--parallel N` it dispatches N
simulations concurrently, **each in its own Docker container** (`manifest.campaign` →
`ThreadPoolExecutor(N)` → `runner.run_one` → `runner._exec` → `docker run --rm … runSim.py …`). This
directory verifies that behaviour.

**Report:** [`docs/parallel_test_report.html`](../../docs/parallel_test_report.html) — open in a browser.
It documents a run of **8 real wcEcoli simulations in parallel** (8/8 concurrent containers, 8/8 QC ok,
~8× speedup over sequential), including the second-by-second `docker ps` concurrency trace.

## Two ways to reproduce

### 1. Orchestration only — fast, no model needed (`test_parallel.py`)
Exercises the exact shipped dispatch path against a **stand-in image** that honours cellarium's identical
`docker run … python runscripts/manual/runSim.py …` contract but just sleeps + writes a `simOut`-shaped dir.
Proves concurrency, per-sim container isolation, distinct output dirs, and crash-isolation in ~40s. It's a
hermetic pytest test (sim output + the manifest shard go to a tmp dir — nothing touches `runs/` or
`data/manifest/`), opt-in so it stays out of the default unit suite:

```bash
docker build -t wcecoli-standin tests/parallel/standin
CELLARIUM_DOCKER_TESTS=1 pytest tests/parallel/test_parallel.py -v
```

### 2. The real thing — 8 actual whole-cell sims (`real_run.py`)
Needs the real, separately-licensed wcEcoli image and fitted `sim_data` (see
[`docs/GENERATE.md`](../../docs/GENERATE.md)). Each real generation is ~9–20 min.

```bash
# one-time: build the licensed image and fit parameters
docker build -t wcecoli-sim -f /path/to/wcEcoli/docker/local/Dockerfile /path/to/wcEcoli
export WCECOLI_DOCKER=wcecoli-sim CELLARIUM_OUT=$(pwd)/runs
python -m cellarium.runner --cpus 16       # ParCa once (cached sim_data)

python tests/parallel/real_run.py          # 8 sims, parallel=8, with a docker-ps concurrency watcher
```

Both scripts stub only the post-sim **reader** stage where noted (a separate container, not what's under
test); everything about how simulations are dispatched to containers is the real cellarium code.

## Caveats
- **RAM-bound, not core-bound.** Each sim loads ~1 GB of `sim_data`; size `--parallel` to host memory
  (start at 2–3 on a laptop; 8 needs ~8–16 GB headroom).
- **No doubling time at 1 generation** — the manifest surfaces instantaneous `growth_rate`; a full division
  interval needs `--generations 2+`.
- Test manifest shards and `runs/` output stay **local** (gitignored) — they are not committed.
