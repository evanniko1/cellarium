# Docker setup — running real whole‑cell simulations under Cellarium

Cellarium's **reasoning** (Council, Cellwright, corpus) is fresh code and runs with just Python + the committed
shards — **no Docker needed** to browse the corpus, chat, or convene the Council. Docker is required only to
**execute new simulations**: the launch airlock's approved experiments, ParCa (re‑calibration), and any
regenerate‑locally path. Those call the **public Covert‑lab wcEcoli model** — you obtain it yourself and build a
**local** image from your own checkout.

> **License (docs/DECISIONS.md D3).** wcEcoli is under Stanford's **academic, non‑commercial** license and is
> **not** open source. Clone it yourself, accept that license, and run it locally. Any image you build below is
> built from *your* checkout and **must never be published**. Cellarium redistributes **no image**.
>
> It does redistribute a small set of **model source files** — [`model_overlay/`](../model_overlay/), 45 files —
> without which Cellarium's designs cannot run. Most of it derives from CovertLab/WholeCellEcoliRelease **v3.0.1**
> (Choi & Covert 2023, *NAR* 51(12):5911) and is redistributed **with Prof. Covert's permission**, under the same
> non‑commercial terms. It is model source, not a model, and not model‑derived *data*.

---

## 0. Prerequisites

- **Docker** (Desktop on macOS/Windows, Engine on Linux) — `docker --version`.
- **~30 GB free disk** for the image + `sim_data` + a small run set (raw `simOut` is ~5 GB/seed).
- **8 GB+ RAM** available to Docker (a single sim fits comfortably; parallelism needs more — see Tuning).
- Cellarium checked out and its Python env ready (`.venv`), able to `import cellarium`.

## 1. Clone the model, at the pinned commit

```bash
git clone https://github.com/CovertLab/wcEcoli        # Stanford academic, non-commercial license
cd wcEcoli
git checkout -b cellarium-pin a4497e17                 # a BRANCH at the pinned commit -- see the note below
```

`a4497e17` is the commit every SHA256 in `model_overlay/MANIFEST.json` is taken against. A different commit is
not fatal — step 2 will tell you exactly which files moved — but it is the state this path is verified on.

> **Use `-b`, not a bare `git checkout a4497e17`.** A detached HEAD makes step 3 fail: wcEcoli's own
> `cloud/locally-build-wcm.sh` runs `GIT_BRANCH=$(git symbolic-ref --short HEAD)` under `set -eu`, and that exits
> 128 on a detached HEAD, aborting the build before Docker is invoked. Measured on a fresh clone.

## 2. Apply the Cellarium overlay

**Stock wcEcoli cannot run Cellarium's designs.** It has no kinetic tRNA-charging model, and its condition table
has 5 rows where Cellarium's hardcoded indices expect 21. The finished files live in Cellarium's
[`model_overlay/`](../model_overlay/); they are copied over the checkout, not patched into it.

From the **Cellarium** repo root:

```bash
python scripts/apply_model_overlay.py --wcecoli /path/to/wcEcoli --check   # verify, writes nothing
python scripts/apply_model_overlay.py --wcecoli /path/to/wcEcoli
```

`--check` hashes every target file first. If upstream has changed a file the overlay ships, our copy is stale and
may be hiding a real upstream fix, so the tool **stops and names the file** instead of overwriting it. `--force`
proceeds anyway and prints each file it overwrote.

Expected on a clean `a4497e17`: `45 shipped, 0 blocked`, then `31 to replace, 14 to create, 0 problems`.
Re-running is idempotent. Earlier versions of this guide warned that the overlay would exit non-zero and name
files it was withholding; **nothing is withheld now** — see [docs/OVERLAY.md §5](OVERLAY.md) for what was cleared
and what remains open. There is still **no** `docker/local/` in upstream wcEcoli; step 3 is the supported route.

## 3. Build the local image

wcEcoli ships its own two-stage local build (`cloud/docker/runtime/Dockerfile` for the Python environment,
`cloud/docker/wholecell/Dockerfile` for the model on top of it). From the **wcEcoli** repo root — this compiles
the model, so the first build is slow, ~15–30 min:

```bash
export USER=${USER:-$USERNAME}             # Git Bash on Windows leaves $USER EMPTY -- see below
cloud/build-containers-locally.sh          # builds ${USER}-wcm-runtime, then ${USER}-wcm-code
docker image inspect "${USER}-wcm-code" >/dev/null && echo "image OK"
# DO NOT re-tag as a stable alias. `docker tag` is a SNAPSHOT POINTER — rebuilding ${USER}-wcm-code
# does NOT move an alias you made earlier. On this machine `wcecoli-sim:latest` was tagged 2026-05-10
# and never re-pointed; by 2026-08-24 it matched the overlay on 3 of 45 files while the real build
# matched 43, and it lacked two Cellarium variants that 24 corpus rows use. Name the BUILD:
echo "WCECOLI_DOCKER=${USER}-wcm-code:latest" >> .env   # the image the rest of this guide uses
```

> **Why `export USER`.** Both build scripts tag their images `${USER}-wcm-runtime` / `${USER}-wcm-code`. In Git
> Bash on Windows `$USER` is unset (`$USERNAME` holds the login name), so the tag degenerates to `-wcm-runtime`
> and `docker build -t` reads the leading dash as a flag.
>
> **Two upstream pins have bit-rotted, and the overlay fixes both.** On a clean `a4497e17` this build fails
> twice: `Equation==1.2.1` downloads a setuptools from a dead `pypi.python.org` path (`zipfile.BadZipFile`), and
> `stochastic-arrow==1.0.0` imports numpy at build time with no build-requires (`ModuleNotFoundError: No module
> named 'numpy'`). The overlay ships `cloud/docker/runtime/Dockerfile` with four added `pip` lines and no other
> change — which is another reason step 2 must come first.

Apply the overlay **before** building: the image bakes the model in at `/wcEcoli`, and the Cython extension
`_trna_charging.pyx` the overlay installs is compiled during the build by the `setup.py` the overlay also
installs. Overlaying after the build leaves you with an image running stock code.

Any image works as long as it can run `runscripts/manual/{runParca,runSim}.py`. The rest of this guide names it
`${USER}-wcm-code:latest`, which is exactly what `build-containers-locally.sh` produces — no alias, nothing to
re-point.

> **Windows line endings.** If a build step fails with `\r: command not found`, set
> `git config core.autocrlf input` in the wcEcoli checkout and re-clone/reset so shell scripts land LF. The
> overlay itself is unaffected — it writes LF and hashes CRLF-normalised, so it behaves identically on either.

## 4. Point Cellarium at the image

Cellarium's `runner` mounts **only the output dir** into the image and calls the model's scripts. Set:

```bash
export WCECOLI_DOCKER=${USER}-wcm-code:latest   # the image you just built (name the BUILD, not an alias)
export CELLARIUM_OUT="$(pwd)/runs"           # host dir where simOut + sim_data land (Cellarium's runs/)
# Native (no Docker) fallback instead: unset WCECOLI_DOCKER, set WCECOLI_DIR=/path/to/wcEcoli (+ WCECOLI_PY)
```

The runner never mounts your checkout over `/wcEcoli` (that would shadow the compiled model): it runs
`docker run --rm -v "$CELLARIUM_OUT:/wcEcoli/out" -e PYTHONPATH=/wcEcoli -w /wcEcoli ${USER}-wcm-code:latest python …`.

## 5. Calibrate once (ParCa)

`sim_data` (the fitted parameters, incl. the gene→variant‑index map) is built once and cached under
`$CELLARIUM_OUT/cellarium/kb`. This is also what `data/cache/gene_scope.json` is derived from.

```bash
python -m cellarium.runner            # ensure_parca — first run ~20–40 min; cached thereafter
```

## 6. Smoke‑test the loop

Confirm Docker → sim → output → read‑back works before committing to a campaign:

```bash
python scripts/docker_smoke.py --check     # fast: verifies docker, image, env, sim_data
python scripts/docker_smoke.py --sim       # runs ONE wildtype/basal seed × 1 generation and reads it back
```

A green `--sim` means the launch airlock and the regenerate path will work.

## 7. Use it

- **Run a campaign** (build corpus): see [`docs/GENERATE.md`](GENERATE.md) —
  `python -m cellarium.generate --seeds 4 --generations 1 --parallel 3`.
- **Run the app with launches enabled**: start the server with `WCECOLI_DOCKER` set, and the launch airlock's
  approved experiments will actually execute (without it, the airlock queues but can't run — the read‑only mode
  used for the hosted/demo build):
  ```bash
  WCECOLI_DOCKER=${USER}-wcm-code:latest CELLARIUM_OUT="$(pwd)/runs" \
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

---

## Deep dives on existing raw — the *reader* path (no new sims)

This is the workflow for gene‑level questions on a design that already exists: **`top_movers`**,
**`regulon_response`**, **`exchange_flux`**, **`read_species`**, **`read_raw_series`**, **`differential`**. These
read per‑cell listener tables (`MonomerCounts`, `BulkMolecules`, `FBAResults`, …) that the distilled shard does
not carry, so they need two things — the **raw on disk** and the **model's TableReader** to parse it. Running new
simulations is *not* required.

**Three tiers of question** (only the third needs this setup):

| Tier | Tools | Needs |
|---|---|---|
| Shard | `list_results`, `disconfirm`, `differential` (pathway sectors), `viability`, `fit_relation` | committed Parquet only — **no download, no Docker** |
| Panel raw | `read_series`, `read_species` on panel species | shard trajectory (often no Docker) |
| **Full raw** | `top_movers`, `regulon_response`, `exchange_flux`, per‑protein `differential` | **raw simOut local + a reader backend** |

**Step 1 — get the raw local.** For a design that's on HF, pull it (gated on size; ~5 GB/seed):

```bash
# from Cellwright, or directly:
python - <<'PY'
from cellarium import hf
print(hf.download_plan("condition/plus_nitrate"))          # shows n_to_pull + est_gb, downloads nothing
print(hf.download_raw("condition/plus_nitrate", confirm=True))  # pulls + extracts into runs/
PY
```

> **Only part of the corpus is on HF.** A curated subset of run archives is uploaded (the rest live only as the
> shard). `download_plan` tells you honestly: `n_to_pull>0` and `not_on_hf=[]` means it's pullable; a non‑empty
> `not_on_hf` means that design was never uploaded — regenerate it (§1–5) or pick another. **Locality is judged
> by actual simOut presence** (`hf._full_simout_local` checks `…/simOut/MonomerCounts`), so a half‑extracted or
> remnant run dir correctly reports as *not* local and is re‑pulled, rather than silently blocking the reader.

**Step 2 — point Cellarium at the reader image.** The listener tables are read *inside* the model image (the
`wholecell` TableReader lives there, not in Cellarium's venv). Set the same image you'd use for sims:

```bash
export WCECOLI_DOCKER=${USER}-wcm-code:latest   # carries the TableReader; multi-KO is a variant, not an image
export CELLARIUM_OUT="$(pwd)/runs"       # where the raw was extracted
```

Without this, the reader tools fail with `reader worker produced no JSON` /
`ModuleNotFoundError: No module named 'wholecell'` — that's the missing backend, **not** missing data. (Native
fallback: unset `WCECOLI_DOCKER`, set `WCECOLI_DIR=/path/to/wcEcoli` with `wholecell` importable.)

**Worked example — a regulon prediction on an out‑of‑sample stimulus:**

```bash
export WCECOLI_DOCKER=${USER}-wcm-code:latest
python - <<'PY'
from cellarium import tools
# does nitrate drive the nar regulon? control against the anaerobic (no_oxygen) reference
print(tools.regulon_response("nar_nitrate", "condition/plus_nitrate", "condition/no_oxygen"))
PY
```

This is exactly how the report's nitrate and arabinose findings were produced: raw already local, read through
the model image, no new simulation.
