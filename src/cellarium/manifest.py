"""Build shardable Parquet manifest records from simOut, via the container reader + the QC guardrail.

Each contributor writes their own shard (data/manifest/<contributor>-<stamp>.parquet); the corpus is the
union of shards (concatenation), queried with DuckDB. Full simOut stays local; the manifest carries
provenance + QC + summary channels (+ a curated species panel, once decided — see docs/DECISIONS.md D2).
Reading of simOut happens inside the model image (see reader.py / _reader_worker.py).
"""

from __future__ import annotations

import getpass
import hashlib
import json
import socket
import time
import uuid
from pathlib import Path

from . import qc, reader, runner
from .model import Design, GenerationResult, SimResult


def _portable_runpath(run_root) -> str:
    """Repo-relative, forward-slash run path (e.g. 'runs/cellarium/<variant>/<seed>'). A stable dedup key that
    does NOT embed the machine's absolute directory — so the distilled/public manifest can't leak it. `store`
    resolves it back to an absolute path for local reads. Falls back to a slash-normalized path if no runs root
    is found."""
    parts = str(run_root).replace("\\", "/").split("/")
    for i, c in enumerate(parts):
        if c == "runs" or c.startswith("runs_"):
            return "/".join(parts[i:])
    return str(run_root).replace("\\", "/")


# The dedup key. It is the PAIR (id, normalised path), and it has to be, because **neither half is unique**:
#
#   * `simout_path` alone is not, even normalised. A run directory is named from variant-index + seed
#     (`runs/cellarium/rrna_operon_knockout_000004/000000`), which is not unique ACROSS CONTRIBUTORS — two
#     people running the same design produce the same relative path. Today the absolute prefix accidentally
#     disambiguates them; normalising the prefix away merges 17 genuinely different runs, including a gens=4
#     run of ours with a gens=1 run of Filippo's.
#   * `id` alone is not either. Crash rows written before `_crash_row` carried the design tag share ONE id
#     across genuinely different runs (8 ids covering 41 rows), so partitioning on `id` silently collapses
#     distinct failed runs and makes "how many runs failed" unanswerable.
#
# The pair separates all three cases. What it MERGES is the real duplicate: same `id`, same physical run,
# indexed twice under two path spellings — once absolute (`/Users/fmenol/Downloads/cellarium/runs/...`) and
# once repo-relative (`runs/...`), from an ingest predating `_portable_runpath`. Nine such rows inflated
# `wildtype/basal` — the reference for EVERY comparison — from 26 seeds to 34, and every interval on it.
#
# Normalising at READ time rather than rewriting the shards is deliberate: lossless, fixes historical rows
# nobody can re-index, and keeps working if an ingest path drifts again. The Python normaliser is
# `_portable_runpath`; the two MUST stay in agreement — pinned over every corpus path AND adversarial edge
# spellings in tests/test_corpus_integrity.py::test_the_sql_and_python_normalisers_agree.
#
# The `runs` segment is anchored to a path boundary `(^|/)` and only the exact `runs` / `runs_<x>` forms match,
# mirroring `_portable_runpath` (which splits on '/' and matches a whole component == 'runs' or startswith
# 'runs_'). The earlier `runs[^/]*/` matched `runs` as a SUBSTRING of a component, so `myruns/foo` wrongly
# normalised to `runs/foo` and `cellarium_runs/runs/...` to `runs/runs/...` — a future contributor whose
# run-root contains a `runs`-substring segment would silently wrong-split a duplicate. No live path hit it
# (all are clean `runs/...`); this is behaviour-identical on today's corpus and closes the latent gap.
_NORM_PATH = (r"COALESCE(NULLIF(regexp_extract(replace(simout_path, '\', '/'), "
              r"'(^|/)(runs(_[^/]*)?(/.*)?)$', 2), ''), simout_path)")
DEDUP_KEY = f"(COALESCE(id, '') || '@@' || COALESCE({_NORM_PATH}, ''))"
# `NULLS LAST` is explicit rather than load-bearing: DuckDB already orders NULLs last under `DESC`
# (verified directly — a NULL-ts row loses to a timestamped correction either way). Stated because an
# earlier version of this comment claimed the opposite and blamed NULL ordering for a supersession that
# had actually failed for a different reason: the correction had rewritten `simout_path`, which is HALF
# THE DEDUP KEY, so it minted a new row instead of superseding the old one. Appending a correction only
# works when the (id, normalised path) pair is preserved exactly.
DEDUP_QUALIFY = f"QUALIFY row_number() OVER (PARTITION BY {DEDUP_KEY} ORDER BY ts DESC NULLS LAST) = 1"

MANIFEST_DIR = Path("data/manifest")
DROPPED_PATH = MANIFEST_DIR / "dropped.json"
LEDGER_PATH = Path("docs/CORPUS_LEDGER.md")


def dedup_key_py(row: dict) -> str:
    """The DEDUP_KEY value for a row, computed in Python — mirrors the SQL `DEDUP_KEY`/`_NORM_PATH`, which are
    pinned equal in tests/test_corpus_integrity.py. Used to match a row against the tombstone set without a
    round-trip to SQL."""
    sp = row.get("simout_path")
    norm = _portable_runpath(sp) if sp else ""
    return f"{row.get('id') or ''}@@{norm}"


def dropped_keys() -> dict:
    """The TOMBSTONE set (WELL-1y): `{dedup_key: {id, reason, ts, simout_path, design_key}}`. A dropped run is
    EXCLUDED from ranking and comparisons but KEPT in coverage — the DB never forgets it existed or why. Empty
    when nothing has been dropped. This is the dev/benchmark-corpus curation policy (D7): free disk by deleting
    the RAW simOut, but the manifest row and this record survive so a decision stays auditable."""
    try:
        data = json.loads(DROPPED_PATH.read_text(encoding="utf-8"))
        return {t["key"]: t for t in data if isinstance(t, dict) and t.get("key")}
    except Exception:
        return {}


def drop_run(run_id: str, reason: str, ts: float | None = None) -> dict:
    """TOMBSTONE a run: mark it dropped, NEVER delete its manifest row. Records the decision to
    `data/manifest/dropped.json` + `docs/CORPUS_LEDGER.md` and returns the raw simOut path + size for the user
    to delete — raw deletion is the user's irreversible step, never this tool's. Idempotent on `run_id`.

    Resolves `run_id` to its dedup key; refuses if the id is ambiguous (maps to more than one physical run)
    rather than tombstoning several runs behind one id — the exact data-loss shape the dedup key exists to
    prevent. `reason` is required: a drop with no recorded rationale is indistinguishable from silent loss."""
    if not (reason or "").strip():
        return {"error": "a drop needs a reason — an unrecorded drop is the silent-loss failure this prevents"}
    import time

    import duckdb
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT id, simout_path, perturbation, condition, timeline, label, generations, reportable "
            f"FROM read_parquet('{MANIFEST_DIR}/*.parquet', union_by_name=true) WHERE id = ?", [run_id]
        ).fetch_arrow_table().to_pylist()
    finally:
        con.close()
    if not rows:
        return {"error": f"no run with id '{run_id}' in the manifest"}
    keys = {dedup_key_py(r) for r in rows}
    if len(keys) > 1:
        return {"error": f"id '{run_id}' maps to {len(keys)} distinct runs {sorted(keys)} — refusing to "
                         f"tombstone several behind one id; drop each by its full identity"}
    r0 = rows[0]
    key = next(iter(keys))
    existing = dropped_keys()
    if key not in existing:
        rec = {"key": key, "id": run_id, "reason": reason, "ts": (ts if ts is not None else time.time()),
               "simout_path": r0.get("simout_path"),
               "design_key": f"{r0.get('perturbation')}/{_design_tag_from_row(r0)}"}
        DROPPED_PATH.parent.mkdir(parents=True, exist_ok=True)
        allrecs = list(existing.values()) + [rec]
        DROPPED_PATH.write_text(json.dumps(allrecs, indent=2, default=str), encoding="utf-8")
        _append_ledger(rec)
        existing[key] = rec
    from . import store
    raw = store._resolve_run(r0.get("simout_path"))
    gb = None
    if raw and Path(raw).exists():
        try:
            gb = round(sum(p.stat().st_size for p in Path(raw).rglob("*") if p.is_file()) / 1e9, 2)
        except Exception:
            gb = None
    return {"dropped": existing[key], "raw_path": r0.get("simout_path"), "raw_gb_to_reclaim": gb,
            "note": ("Tombstoned — the manifest row and this record SURVIVE (surveys exclude it from ranking, "
                     "keep it in coverage). To reclaim disk, delete the raw simOut at `raw_path` yourself; the "
                     "tombstone remains so the decision stays auditable.")}


def _design_tag_from_row(r: dict) -> str:
    """The design tag from a raw manifest row (for the ledger's design_key). Mirrors survey.design_tag's label
    parse but works on the columns present here."""
    import re
    lbl = str(r.get("label") or "")
    core = re.sub(r"(·s\d+|\s+seed\d+)$", "", lbl)
    if "·" in core:
        return core.split("·", 1)[1]
    if "/" in core:
        return core.split("/", 1)[1]
    return r.get("condition") or r.get("timeline") or "basal"


def _append_ledger(rec: dict) -> None:
    """Append a human-readable line to docs/CORPUS_LEDGER.md — the decision record a later repo/DB version reads
    to know what was dropped and why."""
    import datetime
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LEDGER_PATH.exists():
        LEDGER_PATH.write_text(
            "# Corpus ledger\n\nEvery dropped run, recorded so a decision stays auditable across DB versions "
            "(WELL-1y). Dropping tombstones the manifest row (never deletes it) and frees disk by removing the "
            "RAW simOut only. Newest last.\n\n"
            "| when (UTC) | design | id | reason |\n|---|---|---|---|\n", encoding="utf-8")
    when = datetime.datetime.utcfromtimestamp(rec["ts"]).strftime("%Y-%m-%d %H:%M") if rec.get("ts") else "?"
    line = f"| {when} | {rec.get('design_key')} | `{rec.get('id')}` | {rec.get('reason')} |\n"
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


def _design_tag(design: Design) -> str:
    """The label's middle segment. For a gene KO, the GENE is the identity — but the propose (agent/UI) path sets
    condition='basal' with the gene in params.target_genes, while generate.py sets condition='KO:<gene>'. Both must
    label as 'KO:<gene>' so a KO run is never mislabeled 'basal'. Appends a non-basal media as '@<cond>'."""
    genes = list((design.params or {}).get("target_genes") or [])
    if "gene_knockout" in design.perturbation and genes:
        tag = "KO:" + "+".join(genes)
        if design.condition and design.condition not in ("basal", "KO:" + "+".join(genes)):
            tag += "@" + design.condition
        return tag
    return design.condition or design.timeline or "basal"


def build_record(run_root: Path, design: Design, seed: int) -> SimResult:
    data = reader.read_run(run_root)
    note = "" if "error" not in data else f"reader error: {data['error']}"
    gens = [GenerationResult(**g) for g in data.get("generations", [])]
    label = f"{design.perturbation}·{_design_tag(design)}·s{seed}"
    return SimResult(id=f"{design.perturbation}_{seed}_{uuid.uuid4().hex[:8]}", label=label,
                     design=design, channels=data.get("channels", {}), generations=gens, note=note,
                     channel_stats=data.get("channel_stats", {}), series=data.get("series", {}),
                     media_segments=data.get("media_segments", []), pathways=data.get("pathways", {}),
                     species_panel=data.get("species_panel", {}),
                     viability=data.get("viability", {}))


_KB_PROV_CACHE: dict | None = None


def _kb_prov(sim_path: str = "cellarium") -> dict:
    """kb hash + operon mode, cached PER sim_path (hashing a 69 MB pickle per row would be absurd).

    Keyed by sim_path, not a single global: different campaigns run against different knowledge bases and they
    are genuinely different — `runs/cellarium/kb` hashes to 3b2f8ebd… and `runs/aadrop/kb`, which adds the
    amino-acid dropout media, to 0d861f80…. A single cached value silently attributed every campaign to
    whichever kb was hashed first."""
    global _KB_PROV_CACHE
    if not isinstance(_KB_PROV_CACHE, dict) or "kb_sha256" in (_KB_PROV_CACHE or {}):
        _KB_PROV_CACHE = {}                      # migrate the old single-value cache shape
    if sim_path not in _KB_PROV_CACHE:
        try:
            from . import provenance
            _KB_PROV_CACHE[sim_path] = provenance.kb_provenance(sim_path)
        except Exception:
            _KB_PROV_CACHE[sim_path] = {}
    return _KB_PROV_CACHE[sim_path]


def _machine_of(run_root) -> str:
    """A stable id for the machine that produced a run, from the run path's home directory. Everything under
    this checkout is "local"; a contributed shard carries its own absolute path.

    NOT written to the manifest, and deliberately so. A `machine` column was added here to support a
    cross-machine variance correction that has since been WITHDRAWN — at a fixed generation index the machine
    effect is exactly zero (see BACKLOG WELL-6x). It never reached a single shard, so `survey` tier 1 asked for
    a column that did not exist, took a Binder Error on every read, and fell through to a tier that also lacked
    `contributor` — leaving provenance to be guessed from the path, wrongly (18 "local"/16 fmenol against a
    truth of 10 vmnik/24 fmenol). `contributor` is the real column; this stays only for path forensics."""
    p = str(run_root or "").replace("\\", "/")
    for prefix in ("/Users/", "/home/", "C:/Users/", "c:/users/"):
        if prefix.lower() in p.lower():
            i = p.lower().index(prefix.lower()) + len(prefix)
            return p[i:].split("/", 1)[0] or "local"
    return "local"


def _sim_path_of(run_root) -> str:
    """The campaign (`runs/<sim_path>/...`) a run belongs to, read off its own path.

    Derived rather than assumed: a row's knowledge base is a property of where it ran, and defaulting it to
    "cellarium" is how 21 dropout-campaign rows came to claim a kb that has never heard of their media."""
    parts = str(run_root).replace("\\", "/").split("/")
    for i, c in enumerate(parts):
        if (c == "runs" or c.startswith("runs_")) and i + 1 < len(parts):
            return parts[i + 1]
    return "cellarium"


def _flat_row(rec: SimResult, seed: int, run_root: Path,
              requested_generations: int | None = None, crashed: bool = False,
              sim_path: str | None = None) -> dict:
    overall, per = qc.check_result(rec)
    # Knockout semantics depend entirely on whether the kb was built operons-ON (see docs/KNOCKOUT_SEMANTICS.md),
    # and nothing recorded it — "operons on" was filesystem inference. Stamp the kb identity and the operon mode
    # on EVERY row so a published row is self-describing when someone slices the parquet away from this repo.
    # Resolve the kb of the CAMPAIGN this row belongs to. This called `_kb_prov()` with no argument, so every
    # row ever indexed was stamped with the DEFAULT sim_path's knowledge base regardless of which one produced
    # it. Measured before the fix: all 21 `runs/aadrop/` rows — the amino-acid dropout arm — carried the corpus
    # hash 3b2f8ebd..., which does not contain the dropout media those runs executed in. Self-contradictory
    # provenance on ~7% of the corpus, and precisely on the rows a tRNA question would read.
    #
    # `sim_path` is derived from the run path when not supplied, so callers that cannot pass it (historical
    # `record_existing`) still get the right answer rather than the default one.
    _kb = _kb_prov(sim_path or _sim_path_of(run_root))
    row = {"id": rec.id, "label": rec.label,
           "kb_sha256": _kb.get("kb_sha256"), "operons": _kb.get("operons"),
           # Identity is STORED, not left to be re-derived. Every drift incident in this corpus came from a
           # reader keying on a raw field: `condition` is NULL for timelines and 'basal' for propose-path KOs,
           # so two opposite nutrient shifts merged into one cell and a gltX knockout was filed as a control.
           # Deriving correctly is now optional for a reader; getting it wrong requires ignoring this column.
           "design_key": f"{rec.design.perturbation}/{_design_tag(rec.design)}",
           "design_tag": _design_tag(rec.design),
           "requested_generations": requested_generations,   # for the viability truncation signal (§M)
           "crashed": crashed,                                # the sim raised — inviable regardless of partial data
           "contributor": getpass.getuser(), "host": socket.gethostname(), "ts": time.time(),
           "perturbation": rec.design.perturbation, "condition": rec.design.condition,
           "timeline": rec.design.timeline, "seed": seed, "generations": len(rec.generations),
           "qc": overall.value, "generation_qc": json.dumps([s.value for s in per]),
           "reportable": qc.is_reportable(rec), "note": rec.note,
           "per_generation": json.dumps([{"i": g.index, "growth": g.growth_mean, "ppgpp": g.ppgpp_mean,
                                           "divided": g.divided} for g in rec.generations]),
           "pathways": json.dumps(rec.pathways),   # {pathway: proteome_fraction} — surveyed as channels
           "species_panel": json.dumps(rec.species_panel),  # {monomer_id: {mean,last,series}} — per-species depth (scope A)
           "simout_path": _portable_runpath(run_root),  # repo-RELATIVE, forward-slash: a stable dedup key that
           # does NOT leak the machine's absolute path into the distilled/public manifest (store resolves it back
           # to an absolute path for local reads).
           "channel_stats": json.dumps(rec.channel_stats),   # dynamics (JSON) — depth without a live read
           "series": json.dumps(rec.series),
           "media_segments": json.dumps(rec.media_segments)}
    # viability (§J) as first-class queryable columns: does this lineage divide? A metabolic KO reroutes (viable);
    # a machinery KO collapses. gens_reached < requested (a cross-seed GROUP BY) is the 'died early' signal.
    v = rec.viability or {}
    row.update({"division_rate": v.get("division_rate"), "gens_reached": v.get("gens_reached"),
                "terminal_divided": v.get("terminal_divided"), "n_fba_failures": v.get("n_fba_failures"),
                "median_division_time_sec": v.get("median_division_time_sec")})
    row.update(rec.channels)  # flatten summary channel means into columns for easy DuckDB SQL
    return row


def append_shard(rows: list[dict], name: str | None = None) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not rows:
        raise RuntimeError("nothing to write (no rows)")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{name}.parquet" if name else f"{getpass.getuser()}-{int(time.time())}-{uuid.uuid4().hex[:6]}.parquet"
    shard = MANIFEST_DIR / fname
    pq.write_table(pa.Table.from_pylist(rows), shard)
    return shard


def compact(dry_run: bool = False) -> dict:
    """Housekeeping guardrail: consolidate ALL manifest shards into ONE deduped shard, dropping superseded rows
    (older duplicates per run; latest ts wins, matching the read layer). Deterministic — NO judgment — so the
    shard files don't blow up as re-indexes accumulate. Not an agent/user decision; runs automatically after a
    re-index (see record_existing). Writes + verifies the new shard, THEN removes the olds; dry_run only reports."""
    import glob
    import os

    import duckdb

    glob_pat = "data/manifest/*.parquet"
    files = sorted(glob.glob(str(MANIFEST_DIR / "*.parquet")))
    if not files:
        return {"error": "no manifest shards to compact"}
    con = duckdb.connect()
    try:
        latest = con.execute(
            f"SELECT * FROM read_parquet('{glob_pat}', union_by_name=true) {DEDUP_QUALIFY}"
        ).fetch_arrow_table().to_pylist()
        total = con.execute(f"SELECT count(*) FROM read_parquet('{glob_pat}', union_by_name=true)").fetchone()[0]
    finally:
        con.close()
    res = {"files_before": len(files), "rows_before": total, "rows_after": len(latest),
           "superseded_dropped": total - len(latest), "dry_run": dry_run}
    if dry_run or not latest:
        return res
    new = append_shard(latest, name=f"{getpass.getuser()}-compact")  # write the consolidated shard FIRST
    for f in files:
        if Path(f).resolve() != Path(new).resolve():                 # ...then drop the olds
            os.remove(f)
    res.update({"files_after": 1, "shard": str(new)})
    return res


def prune(where_sql: str, dry_run: bool = True) -> dict:
    """Delete manifest rows matching a SQL predicate and rewrite ONE consolidated shard. DELIBERATE and auditable
    (dry_run returns exactly what WOULD be dropped) — unlike compact() this is NOT automatic, because it removes
    rows you name. Use ONLY for infrastructure-crash artifacts (e.g. a disk-crashed batch); NEVER for valid results.
    Keeps rows by id (NULL-safe); write-new-then-delete-old."""
    import glob
    import os

    import duckdb

    glob_pat = "data/manifest/*.parquet"
    files = sorted(glob.glob(str(MANIFEST_DIR / "*.parquet")))
    if not files:
        return {"error": "no manifest shards"}
    con = duckdb.connect()
    try:
        drop = con.execute(f"SELECT id, perturbation, condition, seed, generations, crashed, simout_path "
                           f"FROM read_parquet('{glob_pat}', union_by_name=true) WHERE {where_sql}"
                           ).fetch_arrow_table().to_pylist()
        allrows = con.execute(f"SELECT * FROM read_parquet('{glob_pat}', union_by_name=true)"
                              ).fetch_arrow_table().to_pylist()
    finally:
        con.close()
    drop_ids = {r["id"] for r in drop}
    keep = [r for r in allrows if r.get("id") not in drop_ids]
    res = {"where": where_sql, "n_dropped": len(drop_ids), "n_kept": len(keep), "dry_run": dry_run,
           "dropped_sample": [{k: r.get(k) for k in ("perturbation", "condition", "seed", "generations", "crashed")}
                              for r in drop[:15]]}
    if dry_run:
        return res
    new = append_shard(keep, name=f"{getpass.getuser()}-compact")
    for f in files:
        if Path(f).resolve() != Path(new).resolve():
            os.remove(f)
    res["shard"] = str(new)
    return res


def has_run(design: Design) -> bool:
    """Is at least one indexed run for this design in the manifest? The `label` column encodes the design identity
    ('{perturbation}·{tag}·s{seed}'), so match on that prefix — robust to WHERE the raw output landed on disk
    (out/ vs runs/) and to variant-index recomputation, both of which make a run-dir probe unreliable. Used by
    launch.reconcile to decide whether an orphaned 'running' job actually produced agent-visible data."""
    return count_runs(design) > 0


def count_runs(design: Design) -> int:
    """How many DISTINCT indexed runs (seed-labels) exist for this design. `has_run` (>=1) can't tell a COMPLETE
    campaign (all requested seeds landed) from a PARTIAL one (a crash left only some) — `launch.reconcile` uses this
    count vs the requested seed count for that distinction. NB: labels are seed-scoped but NOT campaign-scoped, so a
    design re-run across campaigns pools their seeds (an over-count that can still mask a partial RE-run) — a residual
    manifest limitation, not fixed here."""
    import glob

    import duckdb

    if not glob.glob(str(MANIFEST_DIR / "*.parquet")):
        return 0
    prefix = f"{design.perturbation}·{_design_tag(design)}·"
    con = duckdb.connect()
    try:
        n = con.execute(
            "SELECT count(DISTINCT label) FROM read_parquet('data/manifest/*.parquet', union_by_name=true) "
            "WHERE starts_with(label, ?)", [prefix]).fetchone()[0]
    finally:
        con.close()
    return int(n)


def _label(design: Design, seed: int) -> str:
    return f"{design.perturbation}/{design.condition or design.timeline or 'basal'} seed{seed}"


def _run_job(design: Design, seed: int, generations: int, sim_path: str = "cellarium") -> dict:
    run_root = runner.run_one(design, seed, generations, sim_path=sim_path)
    return _flat_row(build_record(run_root, design, seed), seed, run_root,
                     requested_generations=generations, sim_path=sim_path)


def _classify_crash(exc: Exception) -> str:
    """infrastructure (disk / I/O / host) vs model (FBA / biology) crash. A lethal KO and an infra-crash otherwise
    look identical in the row (generations=0, crashed=True), so tagging the CAUSE at write time is the only way to
    tell a valid inviable datapoint from a disk-crash artifact without batch archaeology."""
    s = f"{type(exc).__name__}: {exc}".lower()
    if any(k in s for k in ("oserror", "ioerror", "errno 5", "winerror", "no space", "input/output", "disk full")):
        return "infrastructure"
    if "returned non-zero" in s or "docker" in s:      # container failure — ambiguous (could be either)
        return "container"
    return "model"


def _crash_row(design: Design, seed: int, generations: int, exc: Exception,
               sim_path: str = "cellarium") -> dict:
    """A row for a sim that CRASHED (run_one raised) — captures the partial on-disk lineage so the crash is a
    first-class INVIABLE point (§M), not a silently-dropped job. crashed=True overrides any 'looks viable' partial.
    crash_type distinguishes a real lethal KO (model) from a disk/host failure (infrastructure).

    `sim_path` was hard-coded to "cellarium" here, so a crash in ANY other campaign recorded a run path that
    does not exist and names the wrong knowledge base. Measured: the SCI-TRNA-4 leu arm ran under `aadrop` and
    its 7 crash rows claimed `runs/cellarium/gene_knockout_001818/...`. That is not cosmetic — the kb
    provenance backfill infers a row's knowledge base from its campaign, so those rows would have been
    attributed to the corpus KB they never ran against."""
    run_root = runner._run_subpath(design, seed, sim_path)
    ctype = _classify_crash(exc)
    try:
        rec = build_record(run_root, design, seed) if run_root.exists() else None
    except Exception:
        rec = None
    if rec is not None:
        row = _flat_row(rec, seed, run_root, requested_generations=generations, crashed=True,
                        sim_path=sim_path)
        row["qc"], row["reportable"], row["note"] = "crashed", False, f"sim crashed: {str(exc)[:150]}"
        row["crash_type"] = ctype
        return row
    # The id MUST carry the design tag. Without it, `<perturbation>_<seed>_crash` collides across every variant
    # of a family: 8 such ids currently cover 41 genuinely different failed runs (all 10 `kin_w` doses at seed 1
    # share `metabolism_kinetic_objective_weight_1_crash`). They survive today only because the dedup key is the
    # (id, path) PAIR — keyed on id alone they would collapse to 8 rows and "how many runs failed" would be
    # unanswerable. Matches the shape of a successful row's id: <perturbation>_<seed>_<hash8>.
    tag = hashlib.sha256(f"{design.perturbation}|{_design_tag(design)}|{seed}".encode()).hexdigest()[:8]
    return {"id": f"{design.perturbation}_{seed}_{tag}_crash", "label": _label(design, seed),
            "perturbation": design.perturbation, "condition": design.condition, "timeline": design.timeline,
            "seed": seed, "generations": 0, "requested_generations": generations, "crashed": True,
            "qc": "crashed", "reportable": False, "gens_reached": 0, "division_rate": 0.0, "crash_type": ctype,
            "terminal_divided": False, "n_fba_failures": 0, "note": f"sim crashed (no data): {str(exc)[:150]}",
            "simout_path": _portable_runpath(run_root)}


def campaign(designs: list[Design], seeds: list[int], generations: int = 1, parallel: int = 1,
             sim_path: str = "cellarium") -> Path:
    """Run an in-envelope design x seed matrix on the public model and append a manifest shard.

    Crash-isolated: a failed sim is logged and skipped (never kills the batch), and the shard is written for
    whatever completed — so a long unattended run always leaves a usable corpus. `parallel>1` runs that many
    sims concurrently (each writes a distinct dir since Fix #1, and loads ~1GB sim_data — size to host RAM).

    `sim_path` selects WHICH FITTED KB the campaign runs against. It was hard-coded to "cellarium" here even
    though `runner.run_one` already accepted it, so any campaign needing a different KB — the SCI-TRNA-4
    auxotroph arms need the rebuilt one that knows the dropout media — would have silently run against the
    corpus KB: either dying on an unknown medium, or producing rows whose `kb_sha256` does not match the
    experiment they claim to be. Threaded through to every job, serial and parallel.
    """
    jobs = [(d, s) for d in designs for s in seeds]
    n = len(jobs)
    rows: list[dict] = []

    if parallel <= 1:
        for i, (d, s) in enumerate(jobs, 1):
            print(f"[{i}/{n}] {_label(d, s)} ...", flush=True)
            try:
                rows.append(_run_job(d, s, generations, sim_path))
                print(f"[{i}/{n}] {_label(d, s)} -> qc={rows[-1]['qc']}", flush=True)
            except Exception as exc:  # one bad sim must not lose the whole batch — but record it as a crash (§M)
                print(f"[{i}/{n}] {_label(d, s)} FAILED: {exc}", flush=True)
                try:
                    rows.append(_crash_row(d, s, generations, exc, sim_path))
                except Exception:
                    pass
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print(f"Running {n} sims, {parallel} at a time (each loads ~1GB sim_data — mind host RAM).", flush=True)
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            fut = {ex.submit(_run_job, d, s, generations, sim_path): (d, s) for d, s in jobs}
            for k, f in enumerate(as_completed(fut), 1):
                d, s = fut[f]
                try:
                    rows.append(f.result())
                    print(f"[{k}/{n}] {_label(d, s)} -> qc={rows[-1]['qc']}", flush=True)
                except Exception as exc:
                    print(f"[{k}/{n}] {_label(d, s)} FAILED: {exc}", flush=True)
                    try:
                        rows.append(_crash_row(d, s, generations, exc, sim_path))
                    except Exception:
                        pass

    if not rows:
        raise RuntimeError("campaign produced no completed runs")
    return append_shard(rows)


def _discover_runs(sim_path: str = "cellarium") -> list[Path]:
    """Existing <variant>/<seed> run roots already on disk (a run root is a simOut's 3rd parent)."""
    base = runner._out_root(sim_path)
    return sorted({so.parents[2] for so in base.glob("**/simOut")}) if base.exists() else []


def _design_from_dir(run_root: Path) -> tuple[Design, int]:
    seed = int(run_root.name)
    prov = run_root / "design.json"
    if prov.exists():  # true design written at run time (survives the opaque variant-dir naming)
        return Design.model_validate_json(prov.read_text(encoding="utf-8")), seed
    perturbation, _, idx = run_root.parent.name.rpartition("_")  # fallback for pre-provenance runs
    return Design(perturbation=perturbation, params={"variant_index": int(idx)}), seed


def backfill_kb_provenance(sim_path: str = "cellarium", dry_run: bool = True) -> dict:
    """Stamp kb identity + operon mode onto rows indexed before those columns existed.

    Why this is defensible rather than an overclaim: every row in a `sim_path` campaign was produced against the
    ONE kb in `runs/<sim_path>/kb`, so campaign membership is real evidence about the operon mode. But it is
    weaker evidence than reading the run directory, and the difference matters — so the backfilled rows carry
    `kb_verified = False`, and the rows whose directory was actually read at index time carry True. A reviewer
    can then filter on the strength of the provenance instead of trusting a flat assertion.

    Leaving them NULL was the alternative and it is worse: 119 of 273 rows with no operon annotation invites
    exactly the question ("are those results valid?") whose answer is yes-and-here-is-why.
    """
    import glob
    import os

    import duckdb

    kb = _kb_prov(sim_path)
    if not kb.get("kb_sha256"):
        return {"error": f"no kb found under runs/{sim_path}/kb — cannot backfill"}
    files = sorted(glob.glob(str(MANIFEST_DIR / "*.parquet")))
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT * FROM read_parquet('{MANIFEST_DIR}/*.parquet', union_by_name=true) {DEDUP_QUALIFY}"
        ).fetch_arrow_table().to_pylist()
    finally:
        con.close()
    # Stamp only rows from THIS campaign. `sim_path` was accepted and documented but never used: the kb was
    # always the default one and every unstamped row in the whole manifest was stamped with it, regardless of
    # which campaign produced it. That is the precise inverse of this function's own justification, and it
    # would have attributed the 7 `aadrop` crash rows to the corpus kb they never ran against.
    def _belongs(row) -> bool:
        p = str(row.get("simout_path") or "").replace("\\", "/")
        return f"runs/{sim_path}/" in p
    rows = [r for r in rows if _belongs(r)]
    n_before = sum(1 for r in rows if r.get("kb_sha256"))
    for r in rows:
        if r.get("kb_sha256"):
            r.setdefault("kb_verified", True)
            if r.get("kb_verified") is None:
                r["kb_verified"] = True
        else:
            r["kb_sha256"], r["operons"], r["kb_verified"] = kb["kb_sha256"], kb["operons"], False
    res = {"rows": len(rows), "already_stamped": n_before, "backfilled": len(rows) - n_before,
           "kb_sha256": kb["kb_sha256"], "operons": kb["operons"], "dry_run": dry_run}
    if dry_run:
        return res
    new = append_shard(rows, name=f"{getpass.getuser()}-compact")
    for f in files:
        if Path(f).resolve() != Path(new).resolve():
            os.remove(f)
    res["shard"] = str(new)
    return res


def integrity_check(sim_path: str = "cellarium", check_disk: bool = True) -> dict:
    """Standing guard against IDENTITY DRIFT — the failure mode that made this corpus's analyses untrustworthy.

    Every integrity bug found in this corpus was one thing wearing different clothes: **a design's recorded
    identity drifting from what it actually is.** An upshift and a downshift merged because both had
    `condition = NULL`; a gltX knockout was filed as a `basal` control because its provenance file was missing at
    index time; a whole `valS` design sat on disk unindexed and therefore invisible; 1,554 gene names turned out
    to be aliases of a design named after someone else. None of these announce themselves — they produce a
    plausible number computed over the wrong set, which is the worst failure a corpus can have.

    So this is a set of invariants a growing corpus must keep, meant to run in CI, not a one-off cleanup:

      D1  every label parses as `perturbation·tag·s{seed}` — the form identity is derived from
      D2  the STORED `design_key` agrees with the derived one (write/read drift)
      D3  no design key contains `/None` — the nullable-field bug that merged the two nutrient shifts
      D4  no two distinct design keys share a canonical experiment id (an alias counted as a replicate)
      D5  a `gene_knockout` whose tag is `basal` is definitionally suspicious — a gene KO must name a gene
      D6  every row carries kb provenance, so the operon mode behind it is checkable
      D7  no orphan runs on disk (readable but unindexed, hence invisible)

    Returns `{"ok": bool, "violations": [...]}`; each violation names the invariant, the rows, and the fix.
    """
    from . import factors, store, survey

    violations: list[dict] = []
    rows = store.list_results()

    def add(code, msg, examples, fix):
        violations.append({"invariant": code, "message": msg, "n": len(examples),
                           "examples": sorted(examples)[:8], "fix": fix})

    # The invariant is that identity is RECOVERABLE from the label, not that one format is used. Two conventions
    # exist in this corpus ("…·tag·s0" and "…/tag seed0"); both are recognised by survey.design_tag. What must
    # never happen is a label that carries no tag, because then identity silently falls back to the `condition`
    # column — the fall-through that filed a gltX knockout as a `basal` control.
    bad_label = [r["id"] for r in rows
                 if not str(r.get("label") or "") or survey.design_tag(r) in (None, "", "None")]
    if bad_label:
        add("D1", "label carries no recoverable tag, so identity falls back to the `condition` column",
            bad_label, "re-index the affected runs; identity must come from the label, not a nullable field")

    drift = [r["id"] for r in rows
             if r.get("design_key") and r["design_key"] != survey.design_key(r)]
    if drift:
        add("D2", "stored design_key disagrees with the derived one", drift,
            "re-index: the row was written by an older _flat_row")

    nulls = sorted({survey.design_key(r) for r in rows if survey.design_key(r).endswith("/None")})
    if nulls:
        add("D3", "design key contains /None — a nullable field is being used as identity", nulls,
            "the label must carry the tag; check manifest._design_tag for this perturbation")

    keys = sorted({survey.design_key(r) for r in rows})
    dupes = factors.dedupe(keys).get("duplicates") or {}
    if dupes:
        add("D4", "distinct designs resolve to ONE experiment (aliases counted as replicates)",
            [f"{c}: {'+'.join(v)}" for c, v in dupes.items()],
            "these are the same run under different gene names — merge them, do not treat as replicates")

    suspicious = sorted({survey.design_key(r) for r in rows
                         if "knockout" in str(r.get("perturbation") or "") and survey.design_tag(r) == "basal"})
    if suspicious:
        add("D5", "a knockout design is tagged 'basal' — it names no gene, so its identity is unresolved",
            suspicious, "the run needs a design.json; without it _design_from_dir falls back and mislabels")

    # query the manifest directly: store.list_results() projects a fixed column set that omits provenance,
    # so checking it through that view would report every row as unprovenanced (it did, on the first run).
    try:
        import duckdb
        con = duckdb.connect()
        no_prov = [r["id"] for r in con.execute(
            f"SELECT id FROM read_parquet('{MANIFEST_DIR}/*.parquet', union_by_name=true) "
            f"WHERE kb_sha256 IS NULL {DEDUP_QUALIFY}"
        ).fetch_arrow_table().to_pylist()]
        con.close()
    except Exception:
        no_prov = []
    if no_prov:
        add("D6", "row carries no kb provenance, so its operon mode is unknowable", no_prov,
            "run manifest.backfill_kb_provenance(dry_run=False)")

    if check_disk:
        try:
            rec = reconcile_disk(sim_path)
            if rec.get("orphan_designs") or rec.get("orphan_seeds"):
                add("D7", "runs readable on disk but NOT indexed — invisible to every query",
                    list(rec.get("orphan_designs") or []) + list(rec.get("orphan_seeds") or {}),
                    "manifest.record_existing() to index them")
        except Exception as exc:
            violations.append({"invariant": "D7", "message": f"disk check failed: {type(exc).__name__}", "n": 0,
                               "examples": [], "fix": "set CELLARIUM_OUT to the run root"})

    return {"ok": not violations, "n_rows": len(rows), "n_designs": len(keys),
            "violations": violations,
            "note": ("Identity drift produces a plausible number computed over the wrong set. These invariants "
                     "are meant to run in CI as the corpus grows, not once.")}


def reconcile_disk(sim_path: str = "cellarium") -> dict:
    """Two-way diff between the manifest and what is actually on disk. READ-ONLY — it reports, never mutates.

    Both directions are real and they mean different things, which is why one function reports both:

      * **PHANTOM rows** — indexed, but the run directory is gone. These are NOT invalid: the row still carries
        real channels, QC and provenance, and only the full-resolution `simOut` is missing. `raw_available` /
        `data_availability` already model this correctly, so a phantom must be FLAGGED, never deleted — deleting
        would discard measured summary data to fix a storage fact.
      * **ORPHAN runs** — readable on disk, absent from the manifest, therefore invisible to every tool, since
        `_design_run_roots` resolves through the manifest. This is the dangerous direction: `KO:gltX` counted as
        "no local raw" for the whole audit while its seed-0 output sat there, and the six knockouts re-run on
        2026-07-26 are orphans by the same mechanism.

    Returns counts plus the design keys on each side, so a caller can decide whether to re-index.
    """
    from . import store, survey

    on_disk: dict = {}
    for run_root in _discover_runs(sim_path):
        try:
            design, seed = _design_from_dir(run_root)
        except Exception:
            continue
        key = f"{design.perturbation}/{_design_tag(design)}"
        on_disk.setdefault(key, []).append((seed, str(run_root)))

    indexed: dict = {}
    for r in store.list_results():
        key = survey.design_key(r)
        path = store.simout_path(r["id"])
        indexed.setdefault(key, []).append({"seed": r.get("seed"), "path": path,
                                            "exists": bool(path) and Path(path).exists()})

    phantom = {k: [v for v in vs if not v["exists"]] for k, vs in indexed.items()}
    phantom = {k: v for k, v in phantom.items() if v}
    orphan_designs = sorted(set(on_disk) - set(indexed))
    # a design can be indexed AND have unindexed seeds on disk (gltX: rows for seeds 1-3, disk holds seed 0)
    orphan_seeds = {}
    for k, seeds in on_disk.items():
        known = {v["seed"] for v in indexed.get(k, [])}
        extra = [s for s, _ in seeds if s not in known]
        if extra:
            orphan_seeds[k] = sorted(extra)

    return {
        "n_indexed_rows": sum(len(v) for v in indexed.values()),
        "n_designs_indexed": len(indexed), "n_designs_on_disk": len(on_disk),
        "phantom_rows": sum(len(v) for v in phantom.values()),
        "phantom_designs": sorted(phantom),
        "orphan_designs": orphan_designs,
        "orphan_seeds": orphan_seeds,
        "note": ("Phantom = indexed but no simOut on disk: FLAG, do not delete (the summary data is real; only "
                 "raw is gone). Orphan = readable on disk but not indexed, so invisible to every tool that "
                 "resolves through the manifest — re-index with record_existing() to make it queryable."),
    }


def record_existing(sim_path: str = "cellarium") -> Path:
    """Index runs ALREADY on disk into a manifest shard — no re-simulation (one container read each).

    Idempotent: writes to a fixed per-contributor shard (overwritten each call), so repeated re-indexing
    doesn't pile up files; read-time dedup handles any remaining overlap with campaign shards.
    """
    rows: list[dict] = []
    for run_root in _discover_runs(sim_path):
        design, seed = _design_from_dir(run_root)
        rows.append(_flat_row(build_record(run_root, design, seed), seed, run_root))
    if not rows:
        raise RuntimeError(f"no existing runs found under {runner._out_root(sim_path)}")
    append_shard(rows, name=f"{getpass.getuser()}-index")
    res = compact()   # guardrail: auto-consolidate so re-indexes don't pile up superseded shards
    return Path(res["shard"]) if "shard" in res else MANIFEST_DIR


if __name__ == "__main__":  # `python -m cellarium.manifest` -> index existing runs without re-simulating
    shard = record_existing()
    print(f"Indexed existing runs -> {shard}")
