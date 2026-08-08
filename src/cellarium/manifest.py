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
from .capability import DEFAULT_MODE, ELONGATION_MODES, mode_tag_suffix
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

# WHERE TOMBSTONED ROWS PHYSICALLY LIVE (TOMB-1). Every reader in this repository -- 17 sites across 8 modules
# -- globs `data/manifest/*.parquet`, and a glob does not descend into a subdirectory: neither Python's
# `glob.glob` nor DuckDB's `read_parquet` returns `data/manifest/dropped/x.parquet` for that pattern. Moving a
# tombstoned row here therefore makes it UNREACHABLE by construction rather than by discipline.
#
# The discipline version was tried first and did not hold. `_mark_dropped` stamps `_dropped` on rows that match
# the tombstone set, and every reader had to call it. MEASURED 2026-08-08: `store.list_results` and the two
# `survey` readers did; `audit.py`, `operons.py`, `evidence.py` and `corpus_schema._rows` contain no occurrence
# of the string "dropped" at all, and each returned all 52 tombstoned rows as live. The last of those is the
# module written THIS SESSION whose entire purpose is corpus hygiene -- which is the argument. A rule that four
# modules can forget is not a guarantee, and the failure it produces is a plausible number, not an exception.
#
# `dropped.json` stays: it is the record of WHY, and it is what `_mark_dropped` still keys on for anything that
# slips in. This directory is about reachability, not about the audit trail.
QUARANTINE_DIR = MANIFEST_DIR / "dropped"


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
        # Move it out of the glob NOW (TOMB-1). Without this the invariant would hold only for rows migrated
        # once, and the next tombstone would sit reachable in the shards again — which is how the previous
        # mechanism decayed. Rewriting the manifest is affordable here: a drop is a rare human decision.
        quarantine_tombstones(dry_run=False)
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


_COLUMNS_CACHE: tuple[tuple, set[str]] | None = None


def manifest_columns() -> set[str]:
    """The union of column names across every shard, or an empty set when the manifest is unreadable.

    Asked EXPLICITLY rather than discovered by catching a Binder Error, because catching is how the last
    column-drift incident hid: a `machine` column was added to `survey._deduped_rows`' tier-1 projection and
    never written to a single shard, so tier 1 raised on EVERY read and silently fell through to a tier that
    also lacked `contributor` — provenance was then guessed from the path and reported 18/16 against a truth
    of 10/24. A projection must know what exists before it asks for it.

    Cached on the shard set's (name, mtime, size) fingerprint rather than for the process lifetime: this sits
    on the read path (`survey._deduped_rows` consults it once per tier), but a run that appends a shard and
    then reads must see its own write — a stale schema would be the same class of bug this function prevents.
    """
    global _COLUMNS_CACHE
    import glob
    import os

    import duckdb
    files = sorted(glob.glob(str(MANIFEST_DIR / "*.parquet")))
    if not files:
        return set()
    try:
        fp = tuple((f, os.stat(f).st_mtime_ns, os.stat(f).st_size) for f in files)
    except OSError:
        fp = tuple(files)
    if _COLUMNS_CACHE is not None and _COLUMNS_CACHE[0] == fp:
        return _COLUMNS_CACHE[1]
    con = duckdb.connect()
    try:
        desc = con.execute(f"SELECT * FROM read_parquet('{MANIFEST_DIR}/*.parquet', union_by_name=true) "
                           f"LIMIT 0").description
        cols = {d[0] for d in (desc or [])}
    except Exception:
        return set()          # deliberately NOT cached: an unreadable manifest must be re-asked, not pinned
    finally:
        con.close()
    _COLUMNS_CACHE = (fp, cols)
    return cols


def elongation_sql(alias: str = "elongation_model") -> str:
    """A SELECT expression for a row's elongation model that is safe on a corpus written before the column.

    Two branches, and the NULL one is the point. Once any shard carries the column, `union_by_name` fills NULL
    for shards that do not — and NULL must read as "steady_state", never as absent. That is design decision 4
    and it is KNOWN, not assumed: no row in this corpus COULD have used another model, because the flag's host
    process was only just ported. Leaving it to each consumer to decide is exactly the shape of the
    `division_rate` bug (store.py:98-104), where `bool(None)` turned "we did not measure whether this divided"
    into "it did not divide" and produced three false IMPAIRED verdicts.

    When NO shard carries the column yet, the value is synthesised as the literal. Normalising at READ time
    rather than rewriting the shards is the same deliberate, lossless choice the dedup key already makes — and
    `capability.probe_corpus_modes()` reports the physical column as UNVERIFIED so this never reads as a
    confirmation. `backfill_elongation_model()` is what makes it physical."""
    if "elongation_model" in manifest_columns():
        return f"COALESCE(elongation_model, '{DEFAULT_MODE}') AS {alias}"
    return f"'{DEFAULT_MODE}' AS {alias}"


def optional_col_sql(name: str) -> str:
    """A SELECT expression for a column that may not exist in any shard yet (ARM-2).

    Same contract as `elongation_sql` and for the same recorded reason: naming a bare column no shard carries
    raises a Binder Error, and the `machine` incident showed what that costs — tier 1 failed on EVERY read and
    fell through to a tier that also lacked `contributor`, so provenance was guessed from the path and reported
    18/16 against a truth of 10/24. Ask `manifest_columns()` what exists, then synthesise.

    UNLIKE `elongation_sql` there is NO default value here. The ARM-2 columns synthesise to NULL, because NULL
    is the honest answer for a row written before they existed — "which image ran this?" has no safe fallback,
    and `corpus_schema.arm_conflicts` is built to treat NULL as unknown rather than as agreement.
    """
    return f'"{name}"' if name in manifest_columns() else f"NULL AS {name}"


def corpus_elongation_modes() -> dict:
    """Which elongation models actually produced rows — probed, for `capability.probe_corpus_modes()`.

    Reports `verified: False` when the column is not physically present or the manifest cannot be read. It
    does NOT report the read-time default as if it were an observation: a "could not read" reported as a fact
    is the silent-absence bug this repo keeps re-encountering."""
    import glob

    import duckdb
    if not glob.glob(str(MANIFEST_DIR / "*.parquet")):
        return {"verified": False, "modes": [], "why": "no manifest shards to read"}
    if "elongation_model" not in manifest_columns():
        return {"verified": False, "modes": [],
                "why": ("no shard carries an `elongation_model` column yet — reads resolve it to "
                        f"'{DEFAULT_MODE}' via manifest.elongation_sql(), which is the documented value for "
                        "every pre-axis row but is NOT an observation. Run "
                        "manifest.backfill_elongation_model(dry_run=False) to make it physical.")}
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT DISTINCT COALESCE(elongation_model, '{DEFAULT_MODE}') AS m FROM "
            f"(SELECT * FROM read_parquet('{MANIFEST_DIR}/*.parquet', union_by_name=true) {DEDUP_QUALIFY})"
        ).fetch_arrow_table().to_pylist()
        return {"verified": True, "modes": sorted(r["m"] for r in rows if r.get("m"))}
    except Exception as exc:
        return {"verified": False, "modes": [], "why": f"manifest unreadable: {type(exc).__name__}: {exc}"}
    finally:
        con.close()


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


def _expr_suffix(design: Design) -> str:
    """The DOSE fragment for a graded knockout — '' for every other design, so no existing label changes.

    MEASURED 2026-08-08: without this, the depleting-allele campaign's four doses of argS (expression
    0.05/0.10/0.25/0.50, variant indices 6442-6445) all produced the label `graded_gene_knockout·KO:argS·sN`.
    Four rows therefore landed on the SAME (design_key, seed) cell with ppGpp spanning 675 down to 56 — a 12x
    range pooled as "four seeds of one design" by every design-keyed tool. It surfaced as `lethality()`
    reporting a different collapse generation between two calls in one session, because whichever dose won an
    unstable ordering decided the answer.

    The level is taken from `params['level']`, falling back to `variant_index % 10` — the variant index IS
    `gene_ko_index * 10 + level`, so the dose is recoverable even when only the index was passed.
    """
    from . import factors, runner
    if runner._variant_type(design) != "graded_gene_knockout":
        return ""
    p = design.params or {}
    level = p.get("level")
    if level is None and p.get("variant_index") is not None:
        try:
            level = int(p["variant_index"]) % 10
        except (TypeError, ValueError):
            level = None
    return factors.expr_tag_suffix(level)


def _design_tag(design: Design) -> str:
    """The label's middle segment. For a gene KO, the GENE is the identity — but the propose (agent/UI) path sets
    condition='basal' with the gene in params.target_genes, while generate.py sets condition='KO:<gene>'. Both must
    label as 'KO:<gene>' so a KO run is never mislabeled 'basal'. Appends a non-basal media as '@<cond>'.

    The ELONGATION MODEL is appended last (as `#elong:<mode>`, and only when it is not the default) because
    this one function is where design identity is actually decided. Its output flows into `label`, the stored
    `design_key`/`design_tag` columns, `count_runs`' prefix, the deterministic crash-row id, the ledger — and,
    via `survey.design_tag` re-parsing `label`, into EVERY analysis grouping in the repo. Without the mode
    here, `survey.analysis_rows` pools kinetic and steady-state seeds into one design cell and averages
    `fraction_trna_charged` across a measurement and an algebraic identity, silently, because both rows carry
    an 86-wide column of the same name. That pooling is the entire reason this axis exists."""
    genes = list((design.params or {}).get("target_genes") or [])
    if "gene_knockout" in design.perturbation and genes:
        tag = "KO:" + "+".join(genes)
        if design.condition and design.condition not in ("basal", "KO:" + "+".join(genes)):
            tag += "@" + design.condition
        return tag + _expr_suffix(design) + mode_tag_suffix(design.elongation_model)
    base = design.condition or design.timeline or "basal"
    return base + mode_tag_suffix(design.elongation_model)


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


_RUN_PROV_CACHE: dict = {}


_ABSENT_RUN_PROV = {"model_sha256": None, "model_upstream_commit": None,
                    "image_digest": None, "reconstruction_sha": None}


def _run_prov() -> dict:
    """`model_sha256` + `image_digest` + `reconstruction_sha` — but ONLY for a run this process actually executed.

    THE GUARD IS THE POINT, and it is the same one `backfill_parca_ts` needed. These three describe WHAT RAN A
    SIMULATION. `record_existing` builds rows for runs ALREADY ON DISK without re-simulating any of them, so
    stamping there would assert that a run from July used today's model source, today's image and today's flat
    files — a confident, plausible, false claim, and precisely the kind the arm keys are supposed to catch
    rather than manufacture.

    `runner.last_argv()` is the signal: it is non-None only on a thread that launched a run through `_exec`.
    A row therefore carries the whole "what executed this" set or none of it, never a mixture — a row half
    described by the current process would be worse than one that says nothing.

    Cached because `_flat_row` runs per row and `reconstruction_sha` spawns a container: a ~1 s spawn per row
    would tax every campaign, and all three describe the PROCESS, not the row.
    """
    if not _runsim_argv():
        return dict(_ABSENT_RUN_PROV)
    if not _RUN_PROV_CACHE:
        try:
            from . import provenance
            m = provenance.model_provenance()
            _RUN_PROV_CACHE.update({"model_sha256": m.get("model_sha256"),
                                    "model_upstream_commit": m.get("model_upstream_commit"),
                                    "image_digest": provenance.image_digest(),
                                    "reconstruction_sha": provenance.reconstruction_sha()})
        except Exception:
            _RUN_PROV_CACHE.update({"model_sha256": None, "model_upstream_commit": None,
                                    "image_digest": None, "reconstruction_sha": None})
    return dict(_RUN_PROV_CACHE)


def _runsim_argv() -> str | None:
    """The flags this row's run executed with, or None when the row was built without launching anything."""
    try:
        from . import runner
        return runner.last_argv()
    except Exception:
        return None


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
           # The FILE hash above is sound only as "same hash => same kb". MEASURED 2026-08-03: two ParCa runs
           # of identical code, inputs and cpu count produced different file hashes whose sim_data content was
           # identical and whose simulations matched bitwise over all 2530 timesteps — so a differing
           # `kb_sha256` is NOT evidence of a different experiment, and a comparability guard built on it would
           # refuse valid pooling and overcount baselines. `kb_content_sha256` hashes what a simulation reads
           # (provenance._cached_content_hash -> reader.kb_content_hash) and is the field
           # `provenance.same_kb()` prefers. NULL on rows written before this column existed, and on any host
           # without the model image — `same_kb` treats NULL as UNDECIDABLE, never as agreement.
           "kb_content_sha256": _kb.get("kb_content_sha256"),
           # ARM-2 — the five columns the manifest did not carry. `kb_sha256` pins the PARAMETERS; these pin
           # the CODE, the CONTAINER, the INPUTS the fit was built from, WHEN it was built, and the FLAGS.
           # Every one is NULL-when-unknown by design: a row from `record_existing` never launched anything, so
           # its argv is genuinely unknown and must read as unknown. Rationale per column is in
           # `corpus_schema.MISSING_COLUMNS`, and none of them joins ARM_KEYS yet — see `arm_conflicts()` for
           # why a column that is NULL on every existing row cannot partition anything but CAN detect a split.
           **_run_prov(),
           "parca_ts": _kb.get("parca_ts"),
           "runsim_argv": _runsim_argv(),
           # WHICH ELONGATION MODEL produced this row, stored beside kb_sha256/operons and for the same
           # reason the comment below argues for design_key: identity is STORED, not left to be re-derived.
           # A reader that had to recover it by parsing `label` would be keying on a string that already
           # tolerates two conventions in this corpus, and every drift incident recorded in this file came
           # from a reader keying on something it had to re-derive.
           "elongation_model": rec.design.elongation_model,
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


def dropped_rows() -> list[dict]:
    """The quarantined rows themselves — the ON REQUEST path (TOMB-1).

    Quarantine is not deletion. A tombstoned run is still a run that happened, and a question like "what did the
    20 mislabelled knockouts actually report?" has to stay answerable. Nothing globs this by accident, which is
    the point; a caller that wants them has to name them.
    """
    import glob as _glob

    import duckdb
    if not _glob.glob(str(QUARANTINE_DIR / "*.parquet")):
        return []
    con = duckdb.connect()
    try:
        return con.execute(f"SELECT * FROM read_parquet('{QUARANTINE_DIR.as_posix()}/*.parquet', "
                           f"union_by_name=true)").fetch_arrow_table().to_pylist()
    finally:
        con.close()


def quarantine_tombstones(dry_run: bool = True) -> dict:
    """Move every tombstoned row out of the shards readers glob and into `data/manifest/dropped/` (TOMB-1).

    Write-new-then-rewrite-old, and VERIFY between the two: the migration refuses to touch a live shard until it
    has confirmed the quarantine file holds exactly the rows it is about to remove. The failure this guards
    against is not a crash but a partial move -- rows gone from one place and absent from the other -- which on
    this corpus would be indistinguishable from the silent loss the tombstone mechanism exists to prevent.

    Idempotent: running it again finds nothing to move. `dry_run` reports without writing.
    """
    import glob as _glob
    import os

    import duckdb

    tomb = dropped_keys()
    files = sorted(_glob.glob(str(MANIFEST_DIR / "*.parquet")))
    res: dict = {"tombstones": len(tomb), "shards": len(files), "dry_run": dry_run,
                 "quarantine_dir": str(QUARANTINE_DIR)}
    if not tomb or not files:
        return {**res, "moved": 0, "note": "nothing to quarantine"}

    con = duckdb.connect()
    try:
        rows = con.execute(f"SELECT * FROM read_parquet('{MANIFEST_DIR.as_posix()}/*.parquet', "
                           f"union_by_name=true)").fetch_arrow_table().to_pylist()
    finally:
        con.close()
    move = [r for r in rows if dedup_key_py(r) in tomb]
    keep = [r for r in rows if dedup_key_py(r) not in tomb]
    res.update({"rows_before": len(rows), "moved": len(move), "rows_after": len(keep),
                "already_quarantined": len(dropped_rows())})
    if dry_run or not move:
        return res
    if not keep:
        return {**res, "error": "refusing to quarantine EVERY row — that is not a tombstone set, it is a bug"}

    import pyarrow as pa
    import pyarrow.parquet as pq
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    target = QUARANTINE_DIR / f"{getpass.getuser()}-{int(time.time())}-{uuid.uuid4().hex[:6]}.parquet"
    pq.write_table(pa.Table.from_pylist(move), target)

    # VERIFY BEFORE REWRITING. Re-read from disk rather than trusting the in-memory list: the check has to be
    # that the file on disk holds them, which is the thing the next step is about to rely on.
    landed = {dedup_key_py(r) for r in dropped_rows()}
    missing = [dedup_key_py(r) for r in move if dedup_key_py(r) not in landed]
    if missing:
        os.remove(target)
        return {**res, "error": "quarantine file did not land %d rows; nothing removed from the shards"
                                % len(missing), "missing": missing[:5]}

    consolidated = append_shard(keep, name=f"{getpass.getuser()}-compact")
    for f in files:
        if Path(f).resolve() != Path(consolidated).resolve():
            os.remove(f)
    res.update({"quarantine_file": str(target), "shard": str(consolidated), "files_after": 1})
    return res


def append_shard(rows: list[dict], name: str | None = None, directory: Path | None = None) -> Path:
    """Write rows to a parquet shard, keeping EVERY column any row carries.

    `pa.Table.from_pylist` infers its schema from the FIRST ROW ONLY: a key that appears on later rows is
    silently dropped, no error, no warning. MEASURED 2026-08-08 — `from_pylist([{'a':1},{'a':2,'b':99}])`
    returns columns `['a']`. That is a data-loss bug with the worst possible signature, because the write
    reports success and the column simply is not there afterwards.

    Existing callers survived it by accident rather than by design: rows read through
    `read_parquet(..., union_by_name=true)` all come back with the same key set (DuckDB fills NULL), so the
    first row's schema was already complete. The accident ends the moment Python adds a key to SOME rows —
    which is what `backfill_parca_ts` does, since it stamps only rows whose kb is provably their own. Its first
    write dropped `parca_ts` entirely and still reported 279 rows backfilled.

    So the schema is the union over all rows, and the write asserts the column set survived.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not rows:
        raise RuntimeError("nothing to write (no rows)")
    target_dir = directory or MANIFEST_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{name}.parquet" if name else f"{getpass.getuser()}-{int(time.time())}-{uuid.uuid4().hex[:6]}.parquet"
    shard = target_dir / fname
    keys: list[str] = []
    seen: set[str] = set()
    for r in rows:                       # first-seen order, so an existing shard's column order is preserved
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    table = pa.Table.from_pylist([{k: r.get(k) for k in keys} for r in rows])
    missing = seen - set(table.column_names)
    if missing:
        raise RuntimeError(f"refusing to write a shard missing {sorted(missing)} — pyarrow dropped columns "
                           f"present on the input rows")
    pq.write_table(table, shard)
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
    """The `perturbation/tag seed{n}` label form — used for console progress and for the CRASH row.

    The elongation suffix is appended here too, and it has to be: `survey.design_tag` recognises this
    slash-and-space convention as well as the interpunct one, so a crash row labelled without the mode would
    group a kinetic failure into the steady-state design cell — the exact pooling the axis prevents, on the
    rows least able to defend themselves. Byte-identical for the default model."""
    tag = design.condition or design.timeline or "basal"
    return f"{design.perturbation}/{tag}{mode_tag_suffix(design.elongation_model)} seed{seed}"


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


def _exc_text(exc: BaseException, limit: int = 400) -> str:
    """A failure message that can never be empty.

    `print(f"FAILED: {exc}")` renders as "FAILED: " whenever str(exc) is empty, which several exceptions are:
    a bare `raise SomeError()`, a CalledProcessError whose child wrote only to a captured stream, anything
    constructed with no args. MEASURED 2026-08-06: sixteen graded-knockout jobs reported "FAILED:" with
    nothing after the colon; the real cause (a run root with no fitted simData.cPickle) only surfaced when the
    design was re-run outside the campaign. A crash report that says nothing is the silent-absence bug wearing
    an error's clothes, so this always yields at least the exception's type, and appends the deepest traceback
    frame so the reader gets a file and a line even when the message is blank.
    """
    import traceback
    msg = (str(exc) or "").strip()
    out = f"{type(exc).__name__}: {msg}" if msg else f"{type(exc).__name__} (no message)"
    tb = getattr(exc, "__traceback__", None)
    if tb is not None:
        frames = traceback.extract_tb(tb)
        if frames:
            f = frames[-1]
            out += f"  [at {f.filename.split(chr(92))[-1]}:{f.lineno} in {f.name}]"
    for attr in ("stderr", "output"):                       # subprocess errors carry the child's real message
        extra = getattr(exc, attr, None)
        if extra:
            if isinstance(extra, bytes):
                extra = extra.decode("utf-8", "replace")
            tail = " ".join(str(extra).split())[-240:]
            if tail:
                out += f"  <{attr}: ...{tail}>"
            break
    return out[:limit]


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
        row["qc"], row["reportable"], row["note"] = "crashed", False, f"sim crashed: {_exc_text(exc, 200)}"
        row["crash_type"] = ctype
        return row
    # The id MUST carry the design tag. Without it, `<perturbation>_<seed>_crash` collides across every variant
    # of a family: 8 such ids currently cover 41 genuinely different failed runs (all 10 `kin_w` doses at seed 1
    # share `metabolism_kinetic_objective_weight_1_crash`). They survive today only because the dedup key is the
    # (id, path) PAIR — keyed on id alone they would collapse to 8 rows and "how many runs failed" would be
    # unanswerable. Matches the shape of a successful row's id: <perturbation>_<seed>_<hash8>.
    tag = hashlib.sha256(f"{design.perturbation}|{_design_tag(design)}|{seed}".encode()).hexdigest()[:8]
    # This branch hand-writes its column dict instead of going through `_flat_row`, so a column added there
    # does NOT appear here — and these are the rows that MOST need to say which model was attempted. Left off,
    # a kinetic failure lands NULL and is then permanently recorded as a steady-state failure by the backfill.
    # The id and the path above already separate the two arms (both derive from `_design_tag` /
    # `_run_subpath`, which now carry the mode); this column is what makes the row say so out loud.
    return {"id": f"{design.perturbation}_{seed}_{tag}_crash", "label": _label(design, seed),
            "elongation_model": design.elongation_model,
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
                print(f"[{i}/{n}] {_label(d, s)} FAILED: {_exc_text(exc)}", flush=True)
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
                    print(f"[{k}/{n}] {_label(d, s)} FAILED: {_exc_text(exc)}", flush=True)
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
    # Fallback for pre-provenance runs. `_run_subpath` appends discriminator suffixes to the variant dir
    # (`__tl<hash>` for a timeline, `__el<mode>` for a non-default elongation model), so they have to come
    # off before the trailing index is parsed — `gene_knockout_000644__elkinetic`.rpartition('_') yields
    # 'elkinetic', and int() on that raises, which would take down record_existing for the whole campaign.
    # The elongation model is RECOVERED rather than defaulted: this is the one place a kinetic run with no
    # design.json could be silently indexed as steady_state, and the directory name knows the answer.
    name = run_root.parent.name
    elongation = DEFAULT_MODE
    for mode in ELONGATION_MODES:
        if name.endswith(f"__el{mode}"):
            name, elongation = name[: -len(f"__el{mode}")], mode
            break
    name = name.split("__tl")[0]
    perturbation, _, idx = name.rpartition("_")
    return Design(perturbation=perturbation, params={"variant_index": int(idx)},
                  elongation_model=elongation), seed


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


def backfill_elongation_model(dry_run: bool = True) -> dict:
    """Stamp `elongation_model = "steady_state"` onto rows indexed before that column existed.

    STRONGER evidence than the kb backfill above, and deliberately carries no `kb_verified`-style qualifier
    to say so. kb membership is INFERRED from a campaign path; this is not inferred at all — no row in the
    corpus COULD have used another elongation model, because Cellarium had no way to express the choice and
    the flags' host process was only ported afterwards. "steady_state" is KNOWN, not unknown, which is why
    this writes the value rather than an "unknown" category, and why it never writes NULL.

    MUST run before the first non-steady-state row is appended. After that, NULL stops being safely inferable:
    a NULL could then mean either "written before the column" or "written by something that dropped it", and
    nothing in the row distinguishes them.

    Reads are already correct without this — `elongation_sql()` resolves a missing column to the documented
    value — so the thing this buys is a SELF-DESCRIBING parquet row: the corpus is published to HuggingFace
    and sliced away from this repo, where no read-time helper travels with it. Compacts to one shard the way
    `backfill_kb_provenance` does; `dry_run` (the default) reports without writing.
    """
    import glob
    import os

    import duckdb

    files = sorted(glob.glob(str(MANIFEST_DIR / "*.parquet")))
    if not files:
        return {"error": "no manifest shards to backfill"}
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT * FROM read_parquet('{MANIFEST_DIR}/*.parquet', union_by_name=true) {DEDUP_QUALIFY}"
        ).fetch_arrow_table().to_pylist()
    finally:
        con.close()
    n_before = sum(1 for r in rows if r.get("elongation_model"))
    for r in rows:
        if not r.get("elongation_model"):
            r["elongation_model"] = DEFAULT_MODE
    res = {"rows": len(rows), "already_stamped": n_before, "backfilled": len(rows) - n_before,
           "elongation_model": DEFAULT_MODE, "dry_run": dry_run,
           "note": ("Every pre-axis row was produced by the steady-state elongation model — that is known, "
                    "not assumed. Reads already resolve it; this makes the parquet row self-describing.")}
    if dry_run:
        return res
    new = append_shard(rows, name=f"{getpass.getuser()}-compact")
    for f in files:
        if Path(f).resolve() != Path(new).resolve():
            os.remove(f)
    res["shard"] = str(new)
    return res


def backfill_parca_ts(dry_run: bool = True) -> dict:
    """Stamp `parca_ts` onto existing rows — but ONLY where the kb on disk is provably the row's own (ARM-2).

    Of the five ARM-2 columns this is the one that is backfillable at all, and it is the one most worth having:
    it orders the arms CAUSALLY, so a reader can see which fit came first instead of inferring it from the
    earliest run that happens to use each one.

    THE GATE IS THE WHOLE POINT. `parca_ts` is the mtime of `runs/<sim_path>/kb/simData.cPickle`, and the
    obvious backfill — stamp every row from the kb sitting at its campaign path — is WRONG here, measurably.
    A campaign path is reused across rebuilds: `runs/cellarium/kb` currently hashes to `3b2f8ebd…`, but 18
    corpus rows produced under that same path carry `5f19d040…`, a fit that has since been replaced. Stamping
    those with today's mtime would assert a build time for a knowledge base that is no longer there, and the
    row would then carry a `kb_sha256` and a `parca_ts` describing two different fits.

    So a row is stamped only when the kb currently on disk HASHES EQUAL to the row's recorded `kb_sha256`.
    MEASURED 2026-08-08 over 239 analysable rows: 188 match and are stamped; 18 are skipped because the kb at
    their path moved; 33 because `runs/aadrop/kb` no longer exists. Those 51 stay NULL, which is the correct
    answer — unknown, not guessed. `dry_run` (the default) reports without writing.
    """
    import glob
    import os

    import duckdb

    files = sorted(glob.glob(str(MANIFEST_DIR / "*.parquet")))
    if not files:
        return {"error": "no manifest shards to backfill"}
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT * FROM read_parquet('{MANIFEST_DIR.as_posix()}/*.parquet', union_by_name=true)"
        ).fetch_arrow_table().to_pylist()
    finally:
        con.close()

    cache: dict = {}
    stamped = skipped_moved = skipped_missing = already = 0
    for r in rows:
        if r.get("parca_ts"):
            already += 1
            continue
        sp = _sim_path_of(r.get("simout_path"))
        if sp not in cache:
            cache[sp] = _kb_prov(sp) if sp else {}
        disk, row_kb = cache[sp].get("kb_sha256"), r.get("kb_sha256")
        if not disk or not row_kb:
            skipped_missing += 1
        elif disk != row_kb:
            skipped_moved += 1                 # the campaign path was rebuilt; this row's kb is gone
        else:
            # Count the VALUE, not the assignment. The first version incremented here unconditionally and
            # reported "279 backfilled" for a write that stored nothing — an absence counted as a success,
            # which is the same silent-absence shape this repository keeps re-encountering.
            ts = cache[sp].get("parca_ts")
            if ts is None:
                skipped_missing += 1
            else:
                r["parca_ts"] = ts
                stamped += 1
    res = {"rows": len(rows), "already_stamped": already, "backfilled": stamped,
           "skipped_kb_replaced": skipped_moved, "skipped_kb_absent": skipped_missing, "dry_run": dry_run,
           "note": ("Stamped only where the kb on disk hashes equal to the row's own kb_sha256. A row whose "
                    "campaign path was rebuilt keeps parca_ts NULL: unknown, not guessed.")}
    if dry_run or not stamped:
        return res
    new = append_shard(rows, name=f"{getpass.getuser()}-compact")
    for f in files:
        if Path(f).resolve() != Path(new).resolve():
            os.remove(f)
    res["shard"] = str(new)
    return res


def backfill_graded_dose(dry_run: bool = True) -> dict:
    """Put the DOSE back into the identity of graded-knockout rows written before `_expr_suffix` existed.

    Recoverable without re-simulating anything, which is the only reason this is a backfill rather than a
    re-run: the model writes each variant to `graded_gene_knockout_<index>/`, the index is
    `gene_ko_index * 10 + level`, and the level maps to the expression factor. So the dose is on disk in the
    path of every affected row.

    Rewrites `label` and the stored `design_tag`/`design_key`, which are the three places identity is
    persisted — `survey.design_tag` re-derives from `label`, so leaving the stored columns stale would make
    the derived and stored keys disagree, which is invariant D2 and is itself checked elsewhere.
    """
    import glob
    import os
    import re

    import duckdb

    from . import factors

    files = sorted(glob.glob(str(MANIFEST_DIR / "*.parquet")))
    if not files:
        return {"error": "no manifest shards to backfill"}
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT * FROM read_parquet('{MANIFEST_DIR.as_posix()}/*.parquet', union_by_name=true)"
        ).fetch_arrow_table().to_pylist()
    finally:
        con.close()

    changed, skipped, already = [], [], 0
    for r in rows:
        if r.get("perturbation") != "graded_gene_knockout":
            continue
        lab = str(r.get("label") or "")
        if factors.EXPR_TAG_PREFIX in lab:
            already += 1
            continue
        m = re.search(r"graded_gene_knockout_(\d+)", str(r.get("simout_path") or "").replace("\\", "/"))
        suffix = factors.expr_tag_suffix(int(m.group(1)) % 10) if m else ""
        if not suffix:
            # No index in the path means the dose is genuinely unrecoverable. Leave the row alone and SAY so:
            # a guessed dose on a row that spans a 12x ppGpp range is worse than an unlabelled one.
            skipped.append(r.get("id"))
            continue
        new_lab = re.sub(r"(·s\d+|\s+seed\d+)$", lambda mm: suffix + mm.group(0), lab) if re.search(
            r"(·s\d+|\s+seed\d+)$", lab) else lab + suffix
        changed.append({"id": r.get("id"), "from": lab, "to": new_lab})
        r["label"] = new_lab
        if r.get("design_tag"):
            r["design_tag"] = str(r["design_tag"]) + suffix
        if r.get("design_key"):
            r["design_key"] = str(r["design_key"]) + suffix

    res = {"graded_rows": sum(1 for r in rows if r.get("perturbation") == "graded_gene_knockout"),
           "relabelled": len(changed), "already_tagged": already, "unrecoverable": skipped,
           "dry_run": dry_run, "sample": changed[:6],
           "note": ("The dose is part of a design's identity: without it four expression levels of one gene "
                    "share a (design_key, seed) cell and every design-keyed tool averages across them.")}
    if dry_run or not changed:
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
      D8  no row carries a NULL elongation model once that column exists (backfill, never leave NULL)
      D9  a row whose label tag names an elongation model carries the MATCHING column (write/read drift)

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
        # DEDUP FIRST, then filter. SQL applies WHERE before QUALIFY, so `WHERE kb_sha256 IS NULL ... QUALIFY`
        # selects the NULL rows and then dedups AMONG THEMSELVES — it reports a stale row even when a
        # superseding row carries the provenance. That made the invariant unsatisfiable by correction: 7 crash
        # rows were correctly re-stamped by an appended shard and D6 kept flagging the superseded originals.
        # Same shape as rewriting `simout_path` to "fix" a row: the repair is real, the check cannot see it.
        no_prov = [r["id"] for r in con.execute(
            f"SELECT id FROM (SELECT * FROM read_parquet('{MANIFEST_DIR}/*.parquet', union_by_name=true) "
            f"{DEDUP_QUALIFY}) WHERE kb_sha256 IS NULL"
        ).fetch_arrow_table().to_pylist()]
        con.close()
    except Exception:
        no_prov = []
    if no_prov:
        add("D6", "row carries no kb provenance, so its operon mode is unknowable", no_prov,
            "run manifest.backfill_kb_provenance(dry_run=False)")

    # D8/D9 — the elongation axis. Same query shape as D6 (DEDUP FIRST in a subquery, then filter), because
    # SQL applies WHERE before QUALIFY and filtering first would dedup among the offending rows alone,
    # reporting a stale row even after a superseding row fixed it — an invariant unsatisfiable by correction.
    if "elongation_model" in manifest_columns():
        try:
            import duckdb
            con = duckdb.connect()
            null_elong = [r["id"] for r in con.execute(
                f"SELECT id FROM (SELECT * FROM read_parquet('{MANIFEST_DIR}/*.parquet', union_by_name=true) "
                f"{DEDUP_QUALIFY}) WHERE elongation_model IS NULL").fetch_arrow_table().to_pylist()]
            con.close()
        except Exception:
            null_elong = []
        if null_elong:
            add("D8", "row carries a NULL elongation model, so the meaning of its 86-wide charging columns is "
                      "unknowable — and NULL is not 'unknown' here, it is un-backfilled", null_elong,
                "run manifest.backfill_elongation_model(dry_run=False)")
    # D9 catches the write/read drift D2 catches for design_key: the label says one model, the column says
    # another. Either the tag was written by an older _design_tag or the column by an older _flat_row, and a
    # reader that trusts the wrong one pools a measurement with an identity.
    from .capability import mode_from_tag
    drift_elong = [r["id"] for r in rows
                   if r.get("elongation_model")
                   and mode_from_tag(survey.design_tag(r))[1] != r["elongation_model"]]
    if drift_elong:
        add("D9", "the label's elongation tag disagrees with the stored elongation_model column", drift_elong,
            "re-index the affected runs: manifest._design_tag and manifest._flat_row must agree")

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
