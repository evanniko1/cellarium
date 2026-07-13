# Docker setup — running real whole‑cell simulations under Cellarium

Cellarium's **reasoning** (Council, Cellwright, corpus) is fresh code and runs with just Python + the committed
shards — **no Docker needed** to browse the corpus, chat, or convene the Council. Docker is required only to
**execute new simulations**: the launch airlock's approved experiments, ParCa (re‑calibration), and any
regenerate‑locally path. Those call the **public Covert‑lab wcEcoli model**, which Cellarium bundles no code
from — you obtain it yourself and build a **local** image from your own checkout.

> **License (docs/DECISIONS.md D3).** wcEcoli is under Stanford's **academic, non‑commercial** license and is
> **not** open source. Clone it yourself, accept that license, and run it locally. Any image you build below is
> built from *your* checkout and **must never be published**. Cellarium redistributes no model code or image.

---

## 0. Prerequisites

- **Docker** (Desktop on macOS/Windows, Engine on Linux) — `docker --version`.
- **~30 GB free disk** for the image + `sim_data` + a small run set (raw `simOut` is ~5 GB/seed).
- **8 GB+ RAM** available to Docker (a single sim fits comfortably; parallelism needs more — see Tuning).
- Cellarium checked out and its Python env ready (`.venv`), able to `import cellarium`.

## 1. Clone the model

```bash
git clone https://github.com/CovertLab/wcEcoli        # Stanford academic, non-commercial license
cd wcEcoli
```

The local Docker runtime lives in [`docker/local/`](https://github.com/CovertLab/wcEcoli) of that repo
(`Dockerfile`, `run.sh`, `entrypoint.sh`): a Python 3.10 image that installs the model's requirements, compiles
its Cython/Fortran, and bakes the model in at `/wcEcoli`. If your checkout lacks `docker/local/`, use the
`Dockerfile` the model ships with (the requirement is only that the image can run
`runscripts/manual/{runParca,runSim}.py`).

## 2. Build the local image

From the **wcEcoli** repo root (this compiles the model — first build is slow, ~15–30 min):

```bash
docker build -t wcecoli-sim -f docker/local/Dockerfile .
docker image inspect wcecoli-sim >/dev/null && echo "image OK"
```

> **Windows line endings.** The build strips CRLF from the entrypoint, but if a build step fails with
> `\r: command not found`, set `git config core.autocrlf input` in the wcEcoli checkout and re‑clone/reset so
> shell scripts land LF. (Cellarium's own scripts are unaffected — this is a model‑repo build concern.)

## 3. Point Cellarium at the image

Cellarium's `runner` mounts **only the output dir** into the image and calls the model's scripts. Set:

```bash
export WCECOLI_DOCKER=wcecoli-sim            # the local model image (recommended path)
export CELLARIUM_OUT="$(pwd)/runs"           # host dir where simOut + sim_data land (Cellarium's runs/)
# Native (no Docker) fallback instead: unset WCECOLI_DOCKER, set WCECOLI_DIR=/path/to/wcEcoli (+ WCECOLI_PY)
```

The runner never mounts your checkout over `/wcEcoli` (that would shadow the compiled model): it runs
`docker run --rm -v "$CELLARIUM_OUT:/wcEcoli/out" -e PYTHONPATH=/wcEcoli -w /wcEcoli wcecoli-sim python …`.

## 4. Calibrate once (ParCa)

`sim_data` (the fitted parameters, incl. the gene→variant‑index map) is built once and cached under
`$CELLARIUM_OUT/cellarium/kb`. This is also what `data/cache/gene_scope.json` is derived from.

```bash
python -m cellarium.runner            # ensure_parca — first run ~20–40 min; cached thereafter
```

## 5. Smoke‑test the loop

Confirm Docker → sim → output → read‑back works before committing to a campaign:

```bash
python scripts/docker_smoke.py --check     # fast: verifies docker, image, env, sim_data
python scripts/docker_smoke.py --sim       # runs ONE wildtype/basal seed × 1 generation and reads it back
```

A green `--sim` means the launch airlock and the regenerate path will work.

## 6. Use it

- **Run a campaign** (build corpus): see [`docs/GENERATE.md`](GENERATE.md) —
  `python -m cellarium.generate --seeds 4 --generations 1 --parallel 3`.
- **Run the app with launches enabled**: start the server with `WCECOLI_DOCKER` set, and the launch airlock's
  approved experiments will actually execute (without it, the airlock queues but can't run — the read‑only mode
  used for the hosted/demo build):
  ```bash
  WCECOLI_DOCKER=wcecoli-sim CELLARIUM_OUT="$(pwd)/runs" \
    .venv/Scripts/python.exe -m uvicorn apps.server:app --host 127.0.0.1 --port 8000
  ```

## Tuning & troubleshooting

| Symptom | Fix |
|---|---|
| ParCa is slow | It parallelizes: `cellarium.runner.ensure_parca(cpus=N)` (defaults to all host cores; the container clamps to what Docker gives it). |
| Parallel sims thrash | Raw `simOut` writes are I/O‑heavy — **~6 parallel sims** saturates a laptop SSD; above that you lose throughput to I/O, not CPU. Keep `--parallel ≤ 6`. |
| Multi‑gene KO overwrites | Run multi‑gene batches with `--parallel 1` (the index‑0 variant dir is shared before the runner moves it). |
| `Refusing out-of-envelope design` | The design failed the safety/feasibility envelope (e.g. a mid‑run carbon‑source switch, a biosecurity‑blocked gene). Expected — pick an in‑envelope design. |
| Out of disk | Each seed's raw `simOut` is ~5 GB. Keep the manifest shard (small, shareable) and delete raw `runs/` you don't need; re‑pull from HF on demand (see below). |

## You usually don't need to generate — pull raw from HF instead

Most questions are answered by the committed shards with no Docker at all. For full‑resolution/raw needs, an
already‑run design can be pulled from the HF dataset (`evanniko1/cellarium-corpus`) instead of regenerated —
Cellwright does this itself via `data_availability` → `download_raw` (gated on size). Docker/ParCa is only for
runs that are **not** already in the corpus or on HF.
