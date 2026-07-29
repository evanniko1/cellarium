"""Resource constants that LEARN from what actually happened, instead of staying a guess forever.

`resources.estimate_sim_resources` sized a sweep from three hard-coded numbers. One of them was measurably
wrong: `_PER_SIM_RAM_GB = 2.0` against **0.55 GB** actually observed for six concurrent wcEcoli sims — a 3.6x
overestimate, which made the estimator warn (`12.0 GB needed` vs `11.4 GB free`) on a workload really needing
3.3 GB, and recommend `parallel=4` on a host comfortably running 6. A conservative constant is not free: it
silently wastes the machine, and nobody notices because the estimator is never wrong out loud.

The fix is not a better constant — it is to stop guessing. Everything here is measured from this host's own
history and re-measured as more runs land:

  * **disk per GENERATION**, stratified by whether the lineage ARRESTED. Measured 1.58 GB/gen for an arrested
    KO (KO:dapA, 25.32 GB / 16 generations) versus ~0.65 for a dividing one — an arrested cell runs its full
    time budget and writes 2-4x the timesteps. `resources._corpus_footprint` averages GB per *run* across
    both, so it under-estimates a knockout campaign by ~2.4x and over-estimates a wild-type one. Averaging
    across strata that differ by 2.4x is the same error the generation-depth work already cost us once.
  * **RAM per concurrent sim**, sampled from `docker stats` while a campaign is actually running.
  * **wall minutes per generation**, timed by `runner.run_one` and appended as each run finishes.

**Every learned value carries its `n` and its basis, and below `MIN_OBSERVATIONS` it returns None so the caller
falls back to the constant AND SAYS SO.** A calibration that silently swaps in a value derived from two runs
would be a worse failure than the stale constant, because it would look authoritative. Same rule as
`support.py`: the number travels with the evidence behind it.

Observations are keyed by host, because a per-sim RAM figure from a different machine is not evidence about
this one.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import time
from pathlib import Path

from . import redact

# Its OWN directory, not data/cache/: something in the stack parses every JSON under data/cache as a
# SimResult, and dropping an observations file there raised a pydantic validation error on an unrelated
# consumer. A calibration store that breaks the corpus reader is worse than no calibration store.
OBSERVATIONS_PATH = Path("data/calibration/resource_observations.json")

# Below this, a learned value is a rumour. Deliberately small — the point is to beat a constant that was 3.6x
# wrong, not to wait for statistical elegance — but never 1, because a single run is a case study.
MIN_OBSERVATIONS = 3
MAX_RECORDS = 2000                 # keep the file bounded; oldest are dropped first
_STALE_DAYS = 180.0                # older than this is history, not calibration (hardware and images change)


def _host_key() -> str:
    """Observations are per-machine. A per-sim RAM figure from another host is not evidence about this one."""
    return f"{platform.node()}|{platform.system()}"


def _load() -> list[dict]:
    try:
        data = json.loads(OBSERVATIONS_PATH.read_text(encoding="utf-8"))
        return [r for r in data if isinstance(r, dict)]
    except Exception:
        return []


def record(kind: str, value: float, **meta) -> dict:
    """Append one observation. Append-only and idempotent-safe: this never rewrites or reinterprets history."""
    if value is None or not (value == value) or value <= 0:      # NaN-safe
        return {"recorded": False, "why": f"refusing to record a non-positive/NaN {kind}: {value!r}"}
    rec = {"kind": kind, "value": float(value), "ts": time.time(), "host": _host_key(), **meta}
    recs = _load()
    recs.append(rec)
    if len(recs) > MAX_RECORDS:
        recs = recs[-MAX_RECORDS:]
    OBSERVATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OBSERVATIONS_PATH.write_text(json.dumps(recs, indent=1), encoding="utf-8")
    return {"recorded": True, "kind": kind, "value": rec["value"], "n_total": len(recs)}


def _values(kind: str, **match) -> list[float]:
    """Recent, this-host observations of `kind`, optionally filtered on metadata."""
    cutoff = time.time() - _STALE_DAYS * 86400
    host = _host_key()
    out = []
    for r in _load():
        if r.get("kind") != kind or r.get("host") != host or (r.get("ts") or 0) < cutoff:
            continue
        if any(r.get(k) != v for k, v in match.items()):
            continue
        out.append(float(r["value"]))
    return out


def _summary(kind: str, fallback: float, unit: str, **match) -> dict:
    """A learned value with its evidence, or the constant with an explicit reason for falling back.

    The median, not the mean: one pathological run (a sim that swapped, a disk that filled) should not move the
    estimate that decides whether the NEXT sweep fits."""
    vals = _values(kind, **match)
    n = len(vals)
    if n < MIN_OBSERVATIONS:
        return {"value": fallback, "n": n, "basis": "constant", "unit": unit,
                "why": f"only {n} observation(s) on this host; need {MIN_OBSERVATIONS} before trusting measurement"}
    med = statistics.median(vals)
    return {"value": round(med, 3), "n": n, "basis": "measured", "unit": unit,
            "spread": [round(min(vals), 3), round(max(vals), 3)],
            "constant_was": fallback,
            "ratio_vs_constant": round(med / fallback, 2) if fallback else None}


# ---------------- live measurement ----------------
def observe_docker(image: str = "wcecoli-sim", record_it: bool = True) -> dict:
    """Sample `docker stats` for running sim containers -> per-container RAM GB. Call it DURING a campaign.

    This is the measurement the estimator most needed and never had: RAM was the only parameter with no
    empirical path at all, so its constant could drift arbitrarily far from reality without any signal."""
    # `docker stats` has NO `.Image` field — templating on it exits 1 with a template-parsing error. The first
    # version did exactly that and reported "no running containers", i.e. it turned a broken command into an
    # apparent measurement of zero. Resolve IDs with `docker ps --filter ancestor` first, then stat those IDs,
    # and surface a non-zero exit instead of reading it as absence.
    try:
        # Match the image by SUBSTRING over `docker ps`, not with `--filter ancestor`: that filter wants the
        # exact tag, so `ancestor=wcecoli-sim` returned 0 containers while `wcecoli-sim:multiko` returned 6.
        # A filter that silently matches nothing is indistinguishable from an idle host.
        ps = subprocess.run(["docker", "ps", "--format", "{{.ID}}	{{.Image}}"],
                            capture_output=True, text=True, timeout=60, env=redact.child_env())
        if ps.returncode != 0:
            return {"ok": False, "why": f"docker ps failed (rc={ps.returncode}): {(ps.stderr or '').strip()[:200]}"}
        ids = [ln.split("	")[0] for ln in (ps.stdout or "").splitlines()
               if "	" in ln and image in ln.split("	")[1]]
        if not ids:
            return {"ok": False, "why": f"no running containers from image {image!r} — run this while a "
                                        f"campaign is live (this is an ABSENCE of containers, not a measurement)"}
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", *ids],
                             capture_output=True, text=True, timeout=90, env=redact.child_env())
        if out.returncode != 0:
            return {"ok": False, "why": f"docker stats failed (rc={out.returncode}): "
                                        f"{(out.stderr or '').strip()[:200]}"}
    except Exception as e:
        return {"ok": False, "why": f"docker stats failed: {type(e).__name__}: {e}"}
    gbs = []
    for line in (out.stdout or "").splitlines():
        used = line.split("/")[0].strip()
        if not used:
            continue
        try:
            num = float("".join(c for c in used if c.isdigit() or c == "."))
        except ValueError:
            continue
        u = used.upper()
        gb = num / 1024.0 if "MIB" in u or "MB" in u else (num if "GIB" in u or "GB" in u else None)
        if gb:
            gbs.append(gb)
    if not gbs:
        return {"ok": False, "why": f"no running containers matching {image!r} — run this while a campaign is live"}
    per = round(statistics.median(gbs), 3)
    res = {"ok": True, "n_containers": len(gbs), "per_sim_ram_gb": per,
           "spread_gb": [round(min(gbs), 3), round(max(gbs), 3)]}
    if record_it:
        res["record"] = record("per_sim_ram_gb", per, n_containers=len(gbs))
    return res


def observe_run(run_root: str, generations: int, elapsed_sec: float, arrested: bool | None = None) -> dict:
    """Record what ONE finished run actually cost: minutes per generation, and GB per generation.

    `arrested` stratifies the disk figure. An arrested lineage runs its full time budget and writes 2-4x the
    timesteps of a dividing one, so pooling them produces a number that describes neither."""
    gens = max(1, int(generations or 1))
    out = {}
    if elapsed_sec and elapsed_sec > 0:
        out["wall"] = record("min_per_generation", (elapsed_sec / 60.0) / gens, arrested=bool(arrested))
    try:
        total = sum(p.stat().st_size for p in Path(run_root).rglob("*") if p.is_file())
        if total:
            out["disk"] = record("gb_per_generation", (total / 1e9) / gens, arrested=bool(arrested))
    except Exception as e:
        out["disk"] = {"recorded": False, "why": f"{type(e).__name__}: {e}"}
    return out


# ---------------- mining what is already on disk ----------------
def from_corpus_disk(limit: int = 60) -> dict:
    """Learn GB-per-GENERATION from run directories already on disk.

    Retro-mining rather than waiting for new runs: the corpus already holds the answer, and an estimator that
    only learns from future campaigns is useless on the very next one.

    **Most historical rows cannot be classified as arrested or dividing** — `requested_generations` is NULL on
    the majority of them, so there is nothing to compare the reached depth against. The first version quietly
    fell back to `generations`, which made `want == reached` for every run and classified 100% as dividing,
    folding genuine arrested runs (up to 1.96 GB/gen) into the dividing median. Rather than invent a label,
    this reports the DISTRIBUTION and stratifies only the runs that carry the evidence, saying how many it
    could not classify.

    Budgeting uses **p90, not the median**: an estimate that decides whether a sweep fits should be wrong on
    the safe side, and the spread here is 4x from end to end."""
    from . import raw, store, survey
    per = {"arrested": [], "dividing": [], "unclassified": []}
    seen = 0
    for row in survey._deduped_rows(["simout_path", "generations", "gens_reached", "qc",
                                     "requested_generations"]):
        if seen >= limit:
            break
        p = store._resolve_run(row.get("simout_path"))
        if not p or not os.path.isdir(p):
            continue
        gens = raw.simout_dirs(p)
        if not gens:
            continue
        seen += 1
        try:
            total = sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file())
        except Exception:
            continue
        gb_per_gen = (total / 1e9) / len(gens)
        want = row.get("requested_generations")
        if want:
            # arrested = the lineage did not reach the depth it was ASKED for. That is what drives footprint:
            # a non-dividing cell keeps simulating, and keeps writing, for its whole time budget.
            key = "arrested" if len(gens) < int(want) else "dividing"
        else:
            key = "unclassified"
        per[key].append(gb_per_gen)

    def stats(vals):
        if not vals:
            return {"n": 0, "gb_per_generation": None}
        srt = sorted(vals)
        p90 = srt[min(len(srt) - 1, int(round(0.9 * (len(srt) - 1))))]
        return {"n": len(vals), "median": round(statistics.median(srt), 3), "p90": round(p90, 3),
                "spread": [round(srt[0], 3), round(srt[-1], 3)],
                "gb_per_generation": round(p90, 3)}

    out = {k: stats(v) for k, v in per.items()}
    out["all"] = stats([v for vals in per.values() for v in vals])
    out["note"] = ("GB per GENERATION measured from run dirs on disk. `gb_per_generation` is the p90, not the "
                   "median: an estimate that decides whether a sweep fits should err on the safe side. "
                   "Stratified by whether the lineage reached its REQUESTED depth, which is what drives "
                   "footprint (an arrested cell keeps simulating and writing); runs whose manifest row has no "
                   "`requested_generations` are reported as `unclassified` rather than assumed to be either.")
    return out


def backfill_from_corpus(limit: int = 60) -> dict:
    """Turn the on-disk mining into recorded observations so `calibrated()` can use it immediately.

    Records the `unclassified` bucket too, under `arrested=None`, because it is the bulk of the corpus and
    discarding it would leave the estimator with almost no evidence. It is kept in its own stratum rather than
    merged into either label."""
    mined = from_corpus_disk(limit=limit)
    n = 0
    for key, arrested in (("dividing", False), ("arrested", True), ("unclassified", None)):
        d = mined.get(key) or {}
        v = d.get("gb_per_generation")
        if v and d.get("n", 0) >= MIN_OBSERVATIONS:
            for _ in range(d["n"]):
                record("gb_per_generation", v, arrested=arrested, source="corpus_backfill")
                n += 1
    return {"recorded": n, "mined": mined}


# ---------------- what the estimator consumes ----------------
def calibrated() -> dict:
    """The learned parameters, each with its evidence. Values fall back to the constant below MIN_OBSERVATIONS
    and say so — a calibration derived from two runs would be more dangerous than a stale constant, because it
    would look authoritative."""
    from . import resources
    return {
        "per_sim_ram_gb": _summary("per_sim_ram_gb", resources._PER_SIM_RAM_GB, "GB"),
        "min_per_generation": _summary("min_per_generation", resources._PER_RUN_MIN_PER_GEN, "minutes"),
        "gb_per_generation_dividing": _summary("gb_per_generation", 0.65, "GB", arrested=False),
        "gb_per_generation_arrested": _summary("gb_per_generation", 1.58, "GB", arrested=True),
        "host": _host_key(),
        "min_observations": MIN_OBSERVATIONS,
        "note": ("Learned from this host's own runs. `basis` is 'measured' or 'constant'; a measured value "
                 "carries n and spread. Values are medians — one pathological run must not move the estimate "
                 "that decides whether the next sweep fits."),
    }


def watch(interval_sec: float = 180.0, max_samples: int = 40, image: str = "wcecoli-sim") -> dict:
    """Sample per-sim RAM every `interval_sec` for as long as a campaign is running, then stop.

    Spaced samples, not a burst: three readings a second apart are one observation wearing three hats, and
    `MIN_OBSERVATIONS` exists precisely to stop thin evidence being treated as thick. Spacing them across a
    campaign captures the variation that matters — sim_data load, steady state, and the tail — and stopping
    when the containers go away means this never has to be cleaned up by hand."""
    samples, misses = [], 0
    for _ in range(max(1, int(max_samples))):
        r = observe_docker(image=image, record_it=True)
        if r.get("ok"):
            samples.append(r["per_sim_ram_gb"])
            misses = 0
        else:
            misses += 1
            if misses >= 2:          # two consecutive empties = the campaign is over
                break
        time.sleep(max(5.0, float(interval_sec)))
    return {"n_samples": len(samples), "samples": samples,
            "median_gb": round(statistics.median(samples), 3) if samples else None,
            "stopped_because": "no containers for two consecutive checks" if misses >= 2 else "max_samples"}
