"""SCI-QC-2 — recompute the per-segment channel means that the media-label truncation corrupted.

SCI-QC-1 established that the amino-acid upshift DID execute, and that `FBAResults/media_id` failed to record
it: the column is fixed-width, sized from its first value (`minimal`, 7 chars), so the later
`minimal_plus_amino_acids` truncated to exactly `minimal`. That fixes the *label* question. It does not fix the
*numbers*, and the numbers are what a figure would be drawn from.

**What is actually broken.** `_reader_worker._media_segments` walks the recorded media labels and emits one
segment per contiguous run of the same label, with per-channel means inside it. When the labels collapse to a
single `minimal`, the walk emits ONE segment spanning the whole generation, and its "mean" averages pre-shift
and post-shift timesteps together. That is not a slightly-off number; it is a mean over a bimodal distribution,
reported as if it described a steady state. On upshift seed 1 the recorded `fba_objective` is ~7.9 for a
quantity that goes 0.81 before the shift and 14.1 after — a 17x step flattened into one number that describes
neither side.

**Two independent defects, both repaired here.**

1. *Wrong labels* (SCI-QC-2): use `Environment/media_id`, which is written at `<U25` in the same simOut and is
   not truncated. Verified across every shift seed on disk: it carries both media strings and switches at
   exactly the declared time.
2. *Wrong coverage* (SCI-QC-3): `mode_run` calls `_dynamics(gs[-1])`, so `media_segments` describes only the
   LAST generation. On upshift seed 0 that is 1686 of 8142 timesteps — 20.7% — and the retained window is a
   fully amino-acid-rich generation carrying the `minimal` label. That is worse than a truncated record,
   because it is internally self-consistent and cannot be spotted by inspection. `whole_lineage` here walks
   every generation on one continuous clock.

**This does not delete anything.** The manifest is append-only with `ORDER BY ts DESC` supersession, so a
repair writes a NEW shard carrying corrected `media_segments` and a newer timestamp; the corrupt row stays on
disk, superseded and auditable. `repair()` defaults to a dry run and reports the damage before it will write.
"""

from __future__ import annotations

import json
import os

from . import raw, store, support, survey

# the truncation-prone recorder, and the untruncated witness that replaces it
_RECORDED = ("FBAResults", "media_id")
_WITNESS = ("Environment", "media_id")


def _media_column(simout: str, table: str, column: str) -> list[str] | None:
    """One generation's media labels, whitespace-stripped (the witness column is space-padded to its width)."""
    import numpy as np
    path = os.path.join(simout, table, column)
    if not os.path.exists(path):
        return None
    try:
        return [str(x).rstrip() for x in np.asarray(raw.read_column(path)).ravel()]
    except Exception:
        return None


def _segments(t, media: list[str], cols: dict) -> list[dict]:
    """Contiguous media windows with per-channel means. Mirrors `_reader_worker._media_segments` exactly so the
    repaired value is comparable to the stored one — the ONLY difference is which media column feeds it."""
    import numpy as np
    out, start = [], 0
    n = len(media)
    for i in range(1, n + 1):
        if i == n or media[i] != media[start]:
            sl = slice(start, i)
            out.append({"media": media[start], "t0": round(float(t[start]), 1),
                        "t1": round(float(t[i - 1]), 1), "n": i - start,
                        "means": {k: (None if not np.isfinite(m) else round(float(m), 6))
                                  for k, m in ((k, np.nanmean(v[sl])) for k, v in cols.items())}})
            start = i
    return out


def _read_generation(simout: str) -> tuple:
    """(time, {channel: series}) for one generation, using the same channel set the reader records."""
    import numpy as np
    t = raw._col_1d(simout, "Main", "time")
    cols = {}
    for name, (table, column) in raw.CHANNELS.items():
        try:
            v = raw._col_1d(simout, table, column)
        except Exception:
            continue
        n = min(t.size, v.size)
        if n:
            cols[name] = np.asarray(v[:n], dtype=float)
    return t, cols


def recompute(result_id: str) -> dict:
    """Recompute one run's media segments from raw, using the untruncated witness column.

    Returns BOTH readings, because they answer different questions:
      `last_generation` — same scope as the stored value, so it is a like-for-like repair
      `whole_lineage`   — every generation on one clock, which is what the science actually needs
    """
    import numpy as np
    root = store.simout_path(result_id)
    if not root:
        return {"available": False, "why": "no local raw simOut for this run", "result_id": result_id}
    gens = raw.simout_dirs(root)
    if not gens:
        return {"available": False, "why": "no simOut generations under the run path", "result_id": result_id}

    per_gen, offset = [], 0.0
    all_t, all_media, all_cols = [], [], {}
    for gi, so in enumerate(gens):
        witness = _media_column(so, *_WITNESS)
        recorded = _media_column(so, *_RECORDED)
        t, cols = _read_generation(so)
        if witness is None:
            return {"available": False, "result_id": result_id,
                    "why": "this run predates the Environment/media_id listener — no untruncated witness"}
        n = min(len(witness), t.size, *(v.size for v in cols.values())) if cols else 0
        if not n:
            continue
        t, witness = t[:n], witness[:n]
        cols = {k: v[:n] for k, v in cols.items()}
        per_gen.append({"generation": gi, "n_timesteps": n,
                        "witness_media": sorted(set(witness)),
                        "recorded_media": sorted(set(recorded[:n])) if recorded else None,
                        "segments": _segments(t, witness, cols)})
        # continuous lineage clock, matching raw.seed_channel
        tt = t - t[0] + offset
        offset = tt[-1] + (tt[-1] - tt[-2] if tt.size > 1 else 1.0)
        all_t.append(tt); all_media.extend(witness)
        for k, v in cols.items():
            all_cols.setdefault(k, []).append(v)
    if not per_gen:
        return {"available": False, "why": "no readable generation", "result_id": result_id}

    t_all = np.concatenate(all_t)
    cols_all = {k: np.concatenate(v) for k, v in all_cols.items() if len(v) == len(all_t)}
    return {
        "available": True, "result_id": result_id, "n_generations": len(per_gen),
        "last_generation": per_gen[-1]["segments"],
        "whole_lineage": _segments(t_all, all_media, cols_all),
        "per_generation": per_gen,
        "source": "Environment/media_id (<U25, untruncated) + Main/time, read host-side from local raw",
    }


def full_row(result_id: str) -> dict | None:
    """The COMPLETE manifest row for a run — every column, not the 9 that `list_results` projects.

    A repair writes a superseding row, and the read layer resolves `union_by_name` + `ts DESC`. So a repaired
    row built from the projected view would supersede the real one and NULL every column it omitted — the
    channels, the series, the pathways, the species panel. Reading `SELECT *` is the difference between a
    repair and silent data loss, so it is a separate, named function rather than an inline query."""
    from . import manifest
    if not store.has_manifest():
        return None
    rows = store._duck(f"SELECT * FROM {store._FROM} WHERE id = ? {manifest.DEDUP_QUALIFY}", [result_id])
    return rows[0] if rows else None


def _mean_of(segs: list, channel: str) -> list:
    return [(s.get("media"), (s.get("means") or {}).get(channel)) for s in segs or []]


def diff(result_id: str, channels: tuple = ("ppgpp_conc", "fba_objective", "growth_rate")) -> dict:
    """Stored vs recomputed for ONE run — how much the truncation actually distorted the numbers.

    The headline is `worst_fold_error`: for each channel, how many times larger the true post-shift value is
    than the true pre-shift value inside a segment the recorder collapsed into one. A large fold means the
    stored "mean" is averaging across a step and describes neither side of it."""
    rec = recompute(result_id)
    if not rec.get("available"):
        return rec
    row = full_row(result_id)
    stored = []
    if row is not None:
        raw_segs = row.get("media_segments")
        try:
            stored = json.loads(raw_segs) if isinstance(raw_segs, str) else (raw_segs or [])
        except Exception:
            stored = []
    fixed = rec["last_generation"]
    corrupted = len(stored) != len(fixed) or [s.get("media") for s in stored] != [s.get("media") for s in fixed]
    out = {"available": True, "result_id": result_id, "corrupted": bool(corrupted),
           "stored_segments": [s.get("media") for s in stored],
           "recomputed_segments": [s.get("media") for s in fixed],
           "n_generations": rec["n_generations"], "channels": {}}
    for ch in channels:
        s_vals = _mean_of(stored, ch)
        f_vals = _mean_of(fixed, ch)
        entry = {"stored": s_vals, "recomputed_last_generation": f_vals,
                 "recomputed_whole_lineage": _mean_of(rec["whole_lineage"], ch)}
        vals = [v for _m, v in entry["recomputed_whole_lineage"] if v is not None]
        if len(vals) >= 2 and min(abs(v) for v in vals) > 0:
            entry["fold_across_segments"] = round(max(vals) / min(v for v in vals if v != 0), 2)
        out["channels"][ch] = entry
    support.attach(out, result_id)
    folds = [c.get("fold_across_segments") for c in out["channels"].values() if c.get("fold_across_segments")]
    out["worst_fold_error"] = max(folds) if folds else None
    out["note"] = (
        "`stored` is what the manifest carries; where it shows ONE segment for a design that declares a shift, "
        "its means average pre- and post-shift timesteps together. `fold_across_segments` is how large the step "
        "being averaged over actually is — a fold of 17 means the stored single number describes neither side.")
    return out


def repair(write: bool = False, designs: tuple = ()) -> dict:
    """Corpus-wide: find every run whose stored segments disagree with the untruncated witness, and optionally
    write the corrected rows.

    DRY RUN BY DEFAULT. `write=True` appends a NEW manifest shard carrying the corrected `media_segments` with
    a fresh `ts`; the read layer's `ORDER BY ts DESC` supersession then serves the repaired row. Nothing is
    deleted or overwritten — the corrupt row remains on disk and remains auditable, which is the point."""
    import time

    from . import manifest
    rows = [r for r in store.list_results()
            if (not designs or survey.design_key(r) in designs)
            and (r.get("timeline") or "")]
    findings, repaired_rows = [], []
    for r in rows:
        d = diff(r["id"])
        if not d.get("available") or not d.get("corrupted"):
            continue
        rec = recompute(r["id"])
        findings.append({"result_id": r["id"], "design": survey.design_key(r), "seed": r.get("seed"),
                         "stored": d["stored_segments"], "recomputed": d["recomputed_segments"],
                         "worst_fold_error": d["worst_fold_error"],
                         "n_generations": d["n_generations"],
                         "channels": d["channels"]})
        base = full_row(r["id"])
        if base is None:
            findings[-1]["skipped"] = "could not read the full manifest row; refusing to write a partial one"
            continue
        new = dict(base)
        new.pop("_dropped", None)
        new["media_segments"] = json.dumps(rec["last_generation"])
        new["media_segments_whole_lineage"] = json.dumps(rec["whole_lineage"])
        new["segments_repaired_from"] = rec["source"]
        new["ts"] = time.time()
        repaired_rows.append(new)
    out = {"n_runs_examined": len(rows), "n_corrupted": len(findings), "findings": findings,
           "dry_run": not write,
           "note": ("Runs whose stored `media_segments` disagree with the untruncated `Environment/media_id`. "
                    "The repaired row carries BOTH the like-for-like `media_segments` (last generation, correct "
                    "labels) and `media_segments_whole_lineage` (every generation — the coverage hole of "
                    "SCI-QC-3). Append-only: the corrupt row is superseded by timestamp, never deleted.")}
    if write and repaired_rows:
        shard = manifest.append_shard(repaired_rows, name=f"segments-repair-{int(time.time())}")
        out["shard_written"] = str(shard)
        out["n_rows_written"] = len(repaired_rows)
    elif write:
        out["shard_written"] = None
    return out
