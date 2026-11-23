"""The corpora Cellarium can read, and how it reaches each one.

WHY THIS MODULE EXISTS. Until now "the corpus" meant one thing — `data/manifest/*.parquet` — and that
assumption was hard-coded in five modules independently: `manifest.MANIFEST_DIR` (29 uses),
`store.MANIFEST_DIR`/`MANIFEST_GLOB`, `survey.MANIFEST_GLOB`, `audit.MANIFEST_GLOB`, and
`evidence.py:80`'s `CELLARIUM_MANIFEST` environment variable, which was the only one a user could point
somewhere else. Five definitions of one fact is the condition this project's conformance family 9 fails a
suite for. This module is the single declaration; the others should read from it rather than restate it.

WHAT A CORPUS IS HERE. A body of simulation output with (a) an index that makes it queryable without
reading the bulk, and (b) a declared statement of what one row of that index IS. (b) is not decoration.
The row unit differs per corpus and getting it wrong is the commonest cross-corpus error in this project's
own history: `mcp.describe_cellarium` told third-party agents that "one row is one generation of one seed of
one design" when 369 rows carry 825 generations, so a row cannot be a generation. Pooling rows across
corpora without reconciling the unit produces a number with no meaning, so every record names its unit and
`row_unit_differs` refuses a cross-corpus pool that has not declared a reconciliation.

THE THREE TIERS, AND WHY A CORPUS IS NOT DOWNLOADED TO BE USED. Both corpora registered here publish the
same shape: an index of a few megabytes, and bulk measured in terabytes. well4cell's index is 7.51 MB
against 1.4 TB of part files (measured 2026-11-14 via the HF paths-info API); Cellarium's is 7,847,841
bytes against a 270.0 GB deposit. So "plug in a corpus" means fetch the METADATA tier and register it —
after which the whole corpus is queryable — and pull bulk only for a named selection, behind the same
confirmation gate `hf.download_raw` already applies. A corpus is usable the moment its index is local.

WHAT THIS MODULE DOES NOT DO. It does not make two corpora comparable. Cellarium's rows come from a fitted
knowledge base crossed with an operon setting and an elongation model — the "arm" of section 03 — and
nothing here asserts that well4cell's physiology is the same arm. `answers` and `does_not_answer` record
what each corpus can be ASKED, which the capability gate consumes; they do not license a pooled statistic.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Where a plugged-in corpus is recorded. A file rather than an environment variable because a corpus the
# user added should survive a restart and be readable by the UI, and because `CELLARIUM_MANIFEST` already
# demonstrated the limit of the env-var approach: it can name one path and nothing else about it.
REGISTRY_FILE = Path(os.environ.get("CELLARIUM_CORPORA", "data/corpora/registered.json"))
# Where fetched metadata tiers land. One directory per corpus key, so a corpus can be removed by deleting
# one tree and the index of another is never ambiguous.
CACHE_ROOT = Path(os.environ.get("CELLARIUM_CORPUS_CACHE", "data/corpora"))

KINDS = ("local", "hf")
# BINARY, because `scripts/reconcile_corpus_counts.py:41` defines `GB = 1024 ** 3` and every published
# corpus size — the 270.0 GB deposit, the 212.2 GB working copy, the index — is stated in that convention.
# Reporting 7.85 here where the dataset card and the Platform Map say 7.5 would put a third number on one
# file, which is the decay this project files findings about. One convention, named where it is used.
MB = 1024 ** 2


@dataclass(frozen=True)
class Corpus:
    """One body of simulation output, and the terms on which it can be read.

    `row_unit` is required and has no default on purpose: a corpus registered without saying what one row
    is cannot be queried safely, and a default would let the omission pass.
    """

    key: str
    title: str
    kind: str
    locator: str                       # a directory for "local", a dataset repo id for "hf"
    row_unit: str
    index: str = ""                    # the queryable index, relative to `locator`
    metadata_files: tuple = ()         # the cheap tier: with these local, the corpus is queryable
    answers: tuple = ()
    does_not_answer: tuple = ()
    licence: str = ""
    citation: str = ""
    caveats: tuple = ()                # known defects, each naming where the finding is recorded
    declared_in: str = "code"          # "code" for the three below, "user" for a plugged-in one
    notes: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"{self.key}: kind must be one of {KINDS}, not {self.kind!r}")
        if not self.row_unit.strip():
            raise ValueError(f"{self.key}: row_unit is required — a corpus whose row unit is undeclared "
                             f"cannot be pooled or compared, and this project has already shipped one "
                             f"wrong statement of it (mcp.describe_cellarium: 'one row is one generation')")


# --- the corpora declared in code -----------------------------------------------------------------
# Three, and they are deliberately three records rather than two: the local working copy and the HF
# deposit are NEITHER a superset nor a subset of each other (designs uploaded there were pruned here to
# reclaim disk, while runs never uploaded exist only here), which section 04 of the Platform Map states
# and which a single "cellarium" record would erase.

CELLARIUM_LOCAL = Corpus(
    key="cellarium-local",
    title="Cellarium — local working copy",
    kind="local",
    locator="data/manifest",
    index="*.parquet",
    row_unit="one seed of one design, carrying however many generations that seed reached. NOT one cell, "
             "one lineage or one generation: 369 rows carry 333 distinct runs and 825 generations.",
    metadata_files=("*.parquet",),
    answers=("summary channels (growth_rate, ppgpp_conc, ribosome_conc, fraction_trna_charged, rela_conc, "
             "mass channels, fba_objective)", "the 199-species panel", "viability and QC verdicts",
             "per-generation trajectory for growth_rate and ppgpp_conc", "pathway rollups"),
    does_not_answer=("arbitrary non-panel species", "full-resolution trajectories",
                     "FBA reaction/exchange fluxes — these need the raw simOut"),
    licence="see repository",
    caveats=("Rows from different arms (fitted knowledge base x operon setting x elongation model) are not "
             "poolable; the corpus spans four arms.",),
    notes="The index the package ships with. Most questions need no download.",
)

CELLARIUM_HF = Corpus(
    key="cellarium-hf",
    title="Cellarium — published deposit",
    kind="hf",
    locator=os.environ.get("CELLARIUM_HF_REPO", "evanniko1/cellarium-corpus"),
    index="",
    row_unit="one run archive per seed of one design — the same unit as the local copy, compressed.",
    metadata_files=(),
    answers=("raw simOut for a named design, which unlocks arbitrary species, full-resolution "
             "trajectories and FBA fluxes",),
    does_not_answer=("anything about a design it does not hold — per-design presence is checked, not "
                     "assumed",),
    licence="see dataset card",
    caveats=("Neither a superset nor a subset of the local copy.",),
    notes="Reached through `hf.py`, which owns the per-design plan and the gated pull. This record exists "
          "so the deposit appears in the registry beside the others rather than being invisible to it.",
)

WELL4CELL = Corpus(
    key="well4cell",
    title="well4cell — The Well for The Cell",
    kind="hf",
    locator="cSynBioSys/well4cell",
    index="index.parquet",
    row_unit="one TRAJECTORY. MEASURED 2026-11-14 from the fetched index of release 1.0.0-rc2: 139,039 rows, "
             "90 columns, and "
             "`sample_id` is unique across every one of them. A row of a PART FILE is a different unit "
             "again — one timestep of one trajectory — so the index row and the data row never pool. The "
             "audited 1.0.0-rc1 had 117,174 rows x 67 columns, so the release grew by 21,865 trajectories "
             "and 23 columns.",
    metadata_files=("index.parquet", "manifest.json", "provenance/export_qc.parquet",
                    "provenance/failed_jobs.parquet", "provenance/scan_runs.parquet",
                    "provenance/reference/*.parquet", "stats/*.parquet", "README.md"),
    answers=("per-AMINO-ACID tRNA charged fraction, 21 channels (the 20 canonical plus "
             "L-SELENOCYSTEINE[c]) — measured from provenance/reference/charging_trna_charged_fraction — for "
             "21,865 of the 139,039 trajectories ONLY: the rc2 re-runs and wild-type controls, none in the "
             "`regulation` family. Filter on the index column `trna_channels`",
             "amino-acid pool sizes (21) and NTP pool sizes (4: ATP, CTP, GTP, UTP), for the same 21,865 "
             "trajectories",
             "per-trajectory summary: 139,039 rows, one per sample_id",
             "expression and metabolism matrices, at coarse and 1-second resolution",
             "five perturbation families: single_knockout 97,478 trajectories, dynamic_media 21,404, "
             "double_knockout 16,830, regulation 2,046, wildtype_media 1,281"),
    does_not_answer=(
        "PER-ISOACCEPTOR (per-tRNA-gene) charged fraction. This is the important one, and it is MEASURED "
        "rather than inferred: the release's own column map for the charging channel carries 21 rows "
        "indexed by amino acid, not 86 indexed by tRNA gene. A question about one isoacceptor against "
        "another must be refused here exactly as it is against Cellarium's steady_state mode.",
        "ANY charging, amino-acid-pool or NTP-pool question about the 117,174 trajectories carried over from "
        "1.0.0-rc1: they recorded none (`trna_channels` false; the card says the raw output was pruned), so "
        "audit finding F18 still describes them.",
        "anything requiring a re-run: the release carries no simulation inputs (audit finding F17)",),
    licence="CC BY 4.0",
    citation="see the dataset card; the audit records that the citation block had no author in 1.0.0-rc1",
    caveats=(
        "THE PROJECT'S AUDIT IS OF A DIFFERENT RELEASE. `kinetic_port/WELL4CELL_AUDIT.md` (445 lines) "
        "audited 1.0.0-rc1 (built 2026-10-21): 763 files, 1.399 TB, configs `core` plus four matrix "
        "configs. The live release is 1.0.0-rc2, built 2026-11-04 (Hub revision 4ab4aa37, re-confirmed "
        "live 2026-11-21): 978 files across seven configs. Every finding in that audit must be re-checked "
        "against rc2 before it is cited, and a citation of either must name the release.",
        "AUDIT FINDING F18 IS FALSE FOR 1.0.0-rc2 AS A WHOLE AND STILL TRUE FOR MOST OF ITS ROWS. F18 "
        "read 'no charging, pool or per-amino-acid channel exists' of rc1. rc2 carries a `charging` config "
        "of 62,396,417 rows across 10 part files, with the index locators `charging_file`, "
        "`charging_row_offset` and `charging_n_rows`, and three reference tables -- but MEASURED 2026-11-21 "
        "from the index and the manifest's `trna_channels` block, only 21,865 of the 139,039 trajectories "
        "recorded it, every one an rc2 re-run or wild-type control and none in the `regulation` family; the "
        "117,174 carried over from rc1 have none. MEASURED 2026-11-14: the charged-fraction column map holds "
        "21 ids -- the 20 canonical amino acids plus L-SELENOCYSTEINE[c] -- which the card defines as the "
        "fraction of each amino acid's tRNAs that is charged.",
        "WITHDRAWN 2026-11-21: an earlier version of this entry called that 21-column layout independent "
        "corroboration of the capability record Cellarium derives from source. It is neither. Not "
        "evidence: a per-amino-acid summary is what an exporter writes whether or not the simulator's 86 "
        "per-tRNA values are broadcasts of 21, so the layout cannot tell the two apart -- it is CONSISTENT "
        "with the record and no more. Not independent: the rc2 card is built on Cellarium's own definitions "
        "(`translation_collapse`, the qc vocabulary, the pathway panel) and is ordered as a response to the "
        "review of rc1.",
        "Audit finding F1 -- both declared train/test splits put bit-identical twin trajectories on "
        "opposite sides -- describes 1.0.0-rc1 and was FIXED in 1.0.0-rc2, not removed. An earlier version "
        "of this entry said the live index has no train/test column; that was wrong. The rc2 index carries "
        "`split_by_lineage` (train 111,233 / val 13,910 / test 13,896), now assigned per design and seed, "
        "and `split_by_tu` (train 107,228 / val 15,848 / test 15,963), which holds out whole transcription "
        "units -- the fix the audit proposed; `split_by_gene` is gone. MEASURED 2026-11-21 on the rc2 index: "
        "of 25,187 groups of rows sharing the release's `design_id`, seed and generation across more than "
        "one cell, 0 cross either split; grouping instead on every design-defining index column, 0 of "
        "13,099. Bit-identity itself needs the bulk data and was not re-checked; the card reports 447 "
        "pairs, 13,108 trajectories, compared byte for byte on rc1.",
        "Audit finding F4: the alternative carbon sources are t=0 switches out of glucose-fitted "
        "physiology — the same class of boundary Cellarium's own envelope refuses.",
    ),
    notes="Metadata tier MEASURED 2026-11-14: 24 files, 12.03 MB, of which index.parquet is 7.16 MB -- "
          "and that 12 MB makes all 978 files and ~1.4 TB queryable. Bulk is a different cost class: one "
          "charging part file is 1.65 GB, and the configs total 1,375,149,012 data rows "
          "(core 379,148,262; expression_1s 379,148,262; metabolism_1s 379,128,423; charging 62,396,417; "
          "expression 38,098,821; metabolism 38,096,827; summary 139,039). Public, not gated.",
    extra={"api": "https://huggingface.co/api/datasets/cSynBioSys/well4cell",
           "audit": "kinetic_port/WELL4CELL_AUDIT.md",
           "audit_release": "1.0.0-rc1",
           "release_measured": "1.0.0-rc2",
           "hub_revision_2026_11_21": "4ab4aa379afb51150b565e3afd05dddac7e27bd6",
           "files_measured_2026_11_14": 978,
           "configs_measured_2026_11_14": {"charging": 10, "core": 22, "expression": 64,
                                           "expression_1s": 246, "metabolism": 63,
                                           "metabolism_1s": 542, "summary": 5}},
)

DECLARED = (CELLARIUM_LOCAL, CELLARIUM_HF, WELL4CELL)


# --- the registry ---------------------------------------------------------------------------------

def _user_records() -> list[dict]:
    """Corpora the user plugged in. Returns [] when the file is absent, and says so rather than failing —
    but a file that exists and cannot be PARSED is an error, not an empty registry: the silent-absence
    class this project names is exactly 'could not read' reported as 'nothing there'."""
    if not REGISTRY_FILE.is_file():
        return []
    raw = REGISTRY_FILE.read_text(encoding="utf-8")
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{REGISTRY_FILE} exists but is not readable JSON ({exc}). Refusing to report an "
                         f"empty registry for a file that is present: fix or remove it.") from exc
    if not isinstance(rows, list):
        raise ValueError(f"{REGISTRY_FILE} should hold a JSON list of corpus records, not {type(rows).__name__}")
    return rows


def registered() -> list[Corpus]:
    """Every corpus Cellarium knows about: the three declared in code, then the user's, in that order.

    A user record may OVERRIDE a declared one by reusing its key — that is how someone points
    `cellarium-local` at a different directory without editing the package — and the override is reported
    by `declared_in` so the UI can show that a built-in has been redirected.
    """
    out = {c.key: c for c in DECLARED}
    for rec in _user_records():
        rec = dict(rec)
        rec.setdefault("declared_in", "user")
        rec["extra"] = dict(rec.get("extra") or {})
        for k in ("metadata_files", "answers", "does_not_answer", "caveats"):
            if k in rec and rec[k] is not None:
                rec[k] = tuple(rec[k])
        known = {f for f in Corpus.__dataclass_fields__}
        unknown = set(rec) - known
        if unknown:
            raise ValueError(f"corpus {rec.get('key')!r} declares unknown field(s) {sorted(unknown)}; "
                             f"known fields are {sorted(known)}")
        out[rec["key"]] = Corpus(**rec)
    return list(out.values())


def get(key: str) -> Corpus | None:
    return next((c for c in registered() if c.key == key), None)


def register(key: str, title: str, kind: str, locator: str, row_unit: str, **kw) -> dict:
    """Plug a corpus in. Writes the record and returns it plus its measured status.

    `row_unit` is required for the reason given on the dataclass. Everything else is optional, because a
    corpus whose channels are not yet known is still worth registering — `answers=()` reads as UNDECLARED
    in `status()`, which is honest, where an invented list would not be.

    A LOCAL corpus registered without an `index` gets `*.parquet`, because that is what every corpus in
    this project is indexed by and because the alternative is worse: the commonest plug-in case, a
    directory of parquet shards, would come back `undeclared_index` — "cannot be queried" — for a corpus
    that is perfectly queryable. A caught defect, not a convenience: the first test of `register` failed on
    exactly this. A REMOTE corpus gets no default, because the index's filename varies per release (
    well4cell publishes `index.parquet`) and guessing it would produce a confident 404 instead of a
    question.
    """
    if kind == "local":
        kw.setdefault("index", "*.parquet")
        kw.setdefault("metadata_files", ("*.parquet",))
    c = Corpus(key=key, title=title, kind=kind, locator=locator, row_unit=row_unit,
               declared_in="user", **kw)
    rows = [r for r in _user_records() if r.get("key") != key]
    rows.append({f: (list(v) if isinstance(v, tuple) else v)
                 for f, v in c.__dict__.items() if f != "declared_in"} | {"declared_in": "user"})
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    return {"registered": key, "file": str(REGISTRY_FILE), "status": status(key)}


def unregister(key: str) -> dict:
    """Remove a user record. A corpus declared in code cannot be removed this way — say so rather than
    silently doing nothing, which would read as success."""
    rows = _user_records()
    kept = [r for r in rows if r.get("key") != key]
    if len(kept) == len(rows):
        if any(c.key == key for c in DECLARED):
            return {"error": f"{key!r} is declared in code, not in {REGISTRY_FILE}. It cannot be "
                             f"unregistered; point it elsewhere by registering a record with the same key."}
        return {"error": f"no user-registered corpus with key {key!r}"}
    REGISTRY_FILE.write_text(json.dumps(kept, indent=1) + "\n", encoding="utf-8")
    return {"unregistered": key, "remaining": [r["key"] for r in kept]}


# --- availability, measured rather than assumed ----------------------------------------------------

def cache_dir(key: str) -> Path:
    return CACHE_ROOT / key


def _local_index_files(c: Corpus) -> list[Path]:
    import glob as _glob
    root = Path(c.locator)
    if not c.index:
        return []
    return [Path(p) for p in sorted(_glob.glob(str(root / c.index)))]


def _cached_files(c: Corpus) -> list[Path]:
    d = cache_dir(c.key)
    return [p for p in sorted(d.rglob("*")) if p.is_file()] if d.is_dir() else []


def status(key: str) -> dict:
    """Whether Cellarium can read this corpus right now, and on what evidence.

    `state` is one of:
      `ready`        — the index is local and queryable.
      `metadata_absent` — declared and reachable in principle, but nothing fetched yet. NOT an error.
      `locator_missing` — a local corpus whose directory is not there.
      `undeclared_index` — registered without an index, so it cannot be queried (the HF deposit record is
                           deliberately in this state: it is reached per design through `hf.py`, not by an
                           index of its own).
    No network call is made. A remote corpus's reachability is UNMEASURED here and is measured only by
    `metadata_plan`, so that `status()` stays usable offline and never reports "unreachable" for a laptop
    with the wifi off — the misattribution recorded in `hf._repo_sizes` and again in BACKLOG M-13.
    """
    c = get(key)
    if c is None:
        return {"error": f"no corpus registered under {key!r}; known: {[x.key for x in registered()]}"}
    cached = _cached_files(c)
    out = {"key": c.key, "title": c.title, "kind": c.kind, "locator": c.locator,
           "declared_in": c.declared_in, "row_unit": c.row_unit,
           "answers": list(c.answers) or ["UNDECLARED"],
           "does_not_answer": list(c.does_not_answer) or ["UNDECLARED"],
           "licence": c.licence, "caveats": list(c.caveats),
           "cache": str(cache_dir(c.key)), "n_cached_files": len(cached),
           "cached_mb": round(sum(p.stat().st_size for p in cached) / MB, 2) if cached else 0.0,
           "network_checked": False}
    if not c.index:
        out["state"] = "undeclared_index"
        out["why"] = ("registered without an index, so it cannot be queried as a corpus. "
                      + (c.notes or ""))
        return out
    if c.kind == "local":
        files = _local_index_files(c)
        if not Path(c.locator).is_dir():
            out |= {"state": "locator_missing", "why": f"{c.locator} is not a directory on this machine"}
        elif not files:
            out |= {"state": "metadata_absent",
                    "why": f"{c.locator} exists but holds no file matching {c.index!r}"}
        else:
            out |= {"state": "ready", "n_index_files": len(files),
                    "index_mb": round(sum(p.stat().st_size for p in files) / MB, 2)}
        return out
    local_index = cache_dir(c.key) / c.index
    if local_index.is_file():
        out |= {"state": "ready", "n_index_files": 1,
                "index_mb": round(local_index.stat().st_size / MB, 2),
                "index_path": str(local_index)}
    else:
        out |= {"state": "metadata_absent",
                "why": f"the metadata tier has not been fetched into {cache_dir(c.key)}; "
                       f"call metadata_plan({c.key!r}) to size it"}
    return out


def status_all() -> dict:
    """The whole registry, for the UI's corpora field. Ordered as `registered()` returns them."""
    rows = [status(c.key) for c in registered()]
    return {"n_corpora": len(rows),
            "n_ready": sum(1 for r in rows if r.get("state") == "ready"),
            "registry_file": str(REGISTRY_FILE),
            "cache_root": str(CACHE_ROOT),
            "corpora": rows}


def row_unit_differs(keys: list[str]) -> dict:
    """Whether these corpora can be pooled, and if not, why not.

    Returns `poolable: False` whenever the declared row units are not byte-identical. This is deliberately
    strict and deliberately dumb: it cannot tell a reconcilable difference from an irreconcilable one, so
    it refuses and names both units rather than guessing. A caller that has done the reconciliation says so
    explicitly in its own code; nothing here grants it.
    """
    cs = [get(k) for k in keys]
    missing = [k for k, c in zip(keys, cs) if c is None]
    if missing:
        return {"error": f"not registered: {missing}"}
    units = {c.key: c.row_unit for c in cs}
    distinct = set(units.values())
    return {"keys": keys, "poolable": len(distinct) == 1, "units": units,
            "why": ("one declared row unit across all of them" if len(distinct) == 1 else
                    "the row units differ, so a count or mean over the union is not a quantity. Reconcile "
                    "explicitly, per corpus, and say so where you do it.")}


# --- reaching a remote corpus ----------------------------------------------------------------------
# THE ERROR DISCIPLINE HERE IS NOT OPTIONAL, and it is inherited from two recorded failures.
# (1) `hf._repo_sizes` returns `{}` on any exception, and its own comment records what that cost: a stale
#     local OAuth token made the default client fail 401 on a PUBLIC repo while `HfApi(token=False)`
#     succeeded at the same moment, a bare `except` swallowed it, and BACKLOG WELL-6q recorded the wrong
#     diagnosis ("private, unpushed, or renamed") for a dataset any reader can open.
# (2) BACKLOG M-13: a Docker daemon that is down is reported as "reader worker produced no JSON", blaming
#     our own code for an absent engine.
# Both are one defect — an environment fault wearing the costume of a result — so every function below
# returns the ACTUAL exception text and never converts a failure into an empty answer.

def _clients() -> list:
    """The token-carrying client first (correct for a gated repo), then the anonymous one, which is what a
    reader actually experiences. Both, because either can be the one that works."""
    from huggingface_hub import HfApi
    out = [HfApi()]
    try:
        out.append(HfApi(token=False))
    except Exception:                                     # noqa: BLE001 - reported by the caller
        pass
    return out


def _repo_files(repo: str) -> tuple[dict, str | None]:
    """({path: size_bytes}, error). Exactly one of the two is populated, and the error is the real message."""
    try:
        from huggingface_hub import HfApi  # noqa: F401 - the ImportError is the thing we report
    except ImportError as exc:
        return {}, (f"huggingface_hub is not installed ({exc}). That is an environment gap, not a "
                    f"statement about {repo}: install it with `pip install huggingface_hub`.")
    errors = []
    for api in _clients():
        try:
            from . import egress
            egress.record("hf_list_repo_tree", f"https://huggingface.co/datasets/{repo}", purpose="corpus file listing")
            tree = api.list_repo_tree(repo, repo_type="dataset", recursive=True)
            return {getattr(f, "path", ""): int(getattr(f, "size", 0) or 0)
                    for f in tree if getattr(f, "size", None) is not None}, None
        except Exception as exc:                          # noqa: BLE001 - reported below
            errors.append(f"{type(exc).__name__}: {exc}")
    return {}, (f"every hub client failed for {repo}. This may be the network, a stale local token, or the "
                f"repo itself, and the messages distinguish them: " + " | ".join(errors))


def _match(patterns, paths: list[str]) -> list[str]:
    from fnmatch import fnmatch
    return sorted({p for p in paths for pat in patterns if fnmatch(p, pat)})


def metadata_plan(key: str) -> dict:
    """What fetching this corpus's metadata tier would pull, and how big it is. Downloads NOTHING.

    This is the gate. The whole point of the tier split is that a corpus becomes queryable for megabytes
    while its bulk stays in terabytes, so the figure this returns is what the user approves.
    """
    c = get(key)
    if c is None:
        return {"error": f"no corpus registered under {key!r}"}
    if c.kind == "local":
        st = status(key)
        return {"key": key, "kind": "local", "nothing_to_fetch": True,
                "why": f"a local corpus is read in place from {c.locator}; its state is {st['state']}",
                "state": st["state"]}
    if not c.metadata_files:
        return {"key": key, "kind": c.kind, "nothing_to_fetch": True,
                "why": "this corpus declares no metadata tier. " + (c.notes or "")}
    files, err = _repo_files(c.locator)
    if err:
        return {"key": key, "error": err, "network_checked": True}
    want = _match(c.metadata_files, list(files))
    missing = [pat for pat in c.metadata_files if not _match((pat,), list(files))]
    cached = _cached_files(c)
    have = {p.relative_to(cache_dir(key)).as_posix() for p in cached} if cached else set()
    to_pull = [p for p in want if p not in have]
    return {"key": key, "repo": c.locator, "n_repo_files": len(files),
            "n_matched": len(want), "n_already_local": len(want) - len(to_pull),
            "n_to_pull": len(to_pull),
            "est_mb": round(sum(files[p] for p in to_pull) / MB, 2),
            "total_tier_mb": round(sum(files[p] for p in want) / MB, 2),
            "patterns_matching_nothing": missing,
            "files": [{"path": p, "mb": round(files[p] / MB, 2)} for p in to_pull],
            "cache": str(cache_dir(key)), "network_checked": True}


def fetch_metadata(key: str, confirm: bool = False, on_progress=None) -> dict:
    """Fetch the metadata tier into the local cache, after which the corpus is queryable.

    GATED exactly as `hf.download_raw` is: with `confirm=False` (the default) it returns the plan and
    downloads nothing. The gate stays even though this tier is megabytes, because "Cellarium reached out to
    the network" is a thing the user should have agreed to.
    """
    plan = metadata_plan(key)
    if plan.get("error") or plan.get("nothing_to_fetch"):
        return plan
    if not confirm:
        return plan | {"confirm_required": True,
                       "message": f"fetching {plan['n_to_pull']} file(s), {plan['est_mb']} MB, from "
                                  f"{plan['repo']} into {plan['cache']}. Call again with confirm=True."}
    from huggingface_hub import hf_hub_download
    c = get(key)
    dest = cache_dir(key)
    dest.mkdir(parents=True, exist_ok=True)
    got, failed = [], []
    for i, f in enumerate(plan["files"], 1):
        last = "no attempt was made"
        for api_kw in ({}, {"token": False}):
            try:
                from . import egress
                egress.record("hf_hub_download", f"https://huggingface.co/datasets/{c.locator}/blob/main/{f['path']}",
                              purpose="corpus metadata fetch", corpus=key)
                hf_hub_download(c.locator, f["path"], repo_type="dataset",
                                local_dir=str(dest), **api_kw)
                got.append(f["path"])
                break
            except Exception as exc:                      # noqa: BLE001 - reported below
                last = f"{type(exc).__name__}: {exc}"
        else:
            failed.append({"path": f["path"], "error": last})
        if on_progress:
            on_progress({"i": i, "n": len(plan["files"]), "path": f["path"]})
    return {"key": key, "fetched": len(got), "failed": failed, "cache": str(dest),
            "state_now": status(key)["state"],
            "note": ("the corpus is queryable" if not failed else
                     f"{len(failed)} file(s) did not arrive, so the corpus is NOT fully fetched; the "
                     f"errors are reported rather than reduced to 'unavailable'")}


def bulk_plan(key: str, patterns=("data/**",)) -> dict:
    """Size a bulk selection without fetching it.

    Bulk is a different cost class from metadata — one well4cell charging part file measured 1.65 GB on
    2026-11-14 — so this exists to be shown to a user BEFORE anything is pulled, which is the discipline
    `hf.download_plan` already applies per design.
    """
    c = get(key)
    if c is None:
        return {"error": f"no corpus registered under {key!r}"}
    if c.kind == "local":
        return {"key": key, "nothing_to_fetch": True, "why": "a local corpus has no bulk to fetch"}
    files, err = _repo_files(c.locator)
    if err:
        return {"key": key, "error": err, "network_checked": True}
    want = _match(tuple(patterns), list(files))
    total = sum(files[p] for p in want)
    return {"key": key, "repo": c.locator, "patterns": list(patterns),
            "n_files": len(want), "est_gb": round(total / 1024 ** 3, 2),
            "largest": [{"path": p, "gb": round(files[p] / 1024 ** 3, 2)}
                        for p in sorted(want, key=lambda x: -files[x])[:5]],
            "network_checked": True,
            "note": "nothing was downloaded. Pass a narrower pattern to size one config or split."}
