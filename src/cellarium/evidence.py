"""The evidence ledger — a durable, append-only record of which runs each claim actually rests on.

The gap this closes. `rigor.coverage()` answers "which designs did the agent deep-read?", but it is **in-memory
and cleared by `reset()`**, so the moment a session ends the link between a sentence in the manuscript and the
run ids behind it is gone. Every other provenance surface in the project is per-*answer* (the trust strip) or
per-*run* (`provenance.run_environment`); nothing survives the session at the granularity a reviewer asks about,
which is: *"Figure 3 says the argS knockout lowers ppGpp — show me the runs."*

Design, and why it is shaped this way:

  * **One funnel.** Every tool call already passes through `tools.dispatch`, so recording there means no tool has
    to remember to participate, and a tool added later is covered for free.
  * **Append-only JSONL**, never rewritten. A ledger you can edit is not evidence. One line per tool call.
  * **Ids, not values.** The line stores the run ids and design keys a call touched, not the numbers — so it stays
    small, and the numbers are always re-derived from the manifest rather than cached into a second source of
    truth that can drift from it.
  * **Environment captured once per process** (git commit, model, temperature, manifest shards), not per line.
    Sandve et al., *Ten Simple Rules for Reproducible Computational Research* (PLOS CB 9(10):e1003285), Rule 1:
    "whenever a result may be of potential interest, keep track of how it was produced."
  * **Field names map to W3C PROV** — `activity` (the tool call), `entity` (the runs it read), `wasGeneratedBy`.
    We do not emit PROV-JSON, but naming the mapping means a reviewer asking for standard provenance gets a
    mechanical translation rather than an argument. (BACKLOG DATA-PROV.)

Off by default: writing is enabled by `CELLARIUM_EVIDENCE=1` or by calling `enable()`, so tests, evals and the
read-only tier do not accumulate a file nobody asked for.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

LEDGER = Path(os.environ.get("CELLARIUM_EVIDENCE_PATH") or "data/evidence.jsonl")
_lock = threading.Lock()
_enabled: bool | None = None
_env_cache: dict | None = None

# Keys a tool result uses for a run id / design identity. Kept explicit rather than guessed, so a rename shows up
# as "the ledger stopped recording ids" in the test rather than as silent under-recording.
_ID_KEYS = ("id", "result_id", "run_id")
_LABEL_KEYS = ("label", "design", "design_key")


def enabled() -> bool:
    global _enabled
    if _enabled is None:
        _enabled = os.environ.get("CELLARIUM_EVIDENCE", "").strip().lower() in ("1", "true", "yes")
    return _enabled


def enable(path: str | os.PathLike | None = None) -> None:
    """Turn recording on for this process (and optionally point it at a different ledger)."""
    global _enabled, LEDGER
    _enabled = True
    if path is not None:
        LEDGER = Path(path)


def disable() -> None:
    global _enabled
    _enabled = False


def _env() -> dict:
    """Run context, resolved once. Reuses provenance.run_environment so the ledger and the Council's recorded
    environment cannot disagree about what produced a result."""
    global _env_cache
    if _env_cache is None:
        env: dict = {}
        try:
            from . import provenance
            env = dict(provenance.run_environment() or {})
        except Exception:
            env = {}
        env.setdefault("model", os.environ.get("CELLARIUM_MODEL"))
        env.setdefault("temperature", os.environ.get("CELLARIUM_TEMPERATURE"))
        env["manifest"] = os.environ.get("CELLARIUM_MANIFEST") or "data/manifest/*.parquet"
        _env_cache = env
    return _env_cache


def _harvest(obj, ids: set, labels: set, depth: int = 0) -> None:
    """Walk a tool result and collect run ids + design keys. Bounded: a tool result is already capped upstream."""
    if depth > 8:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v:
                if k in _ID_KEYS:
                    ids.add(v)
                elif k in _LABEL_KEYS and ("/" in v or "·" in v):   # a design key, not a free-text label
                    labels.add(v)
            else:
                _harvest(v, ids, labels, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj[:400]:                       # a long rows list is homogeneous; the tail adds no new designs
            _harvest(v, ids, labels, depth + 1)


def _compact_args(args: dict) -> dict:
    """Arguments, trimmed. Long strings are the agent's prose, not evidence — the ids are what matter."""
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, str):
            out[k] = v if len(v) <= 120 else v[:117] + "..."
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = [str(x)[:60] for x in v[:12]]
        else:
            out[k] = f"<{type(v).__name__}>"
    return out


def record(tool: str, args: dict, out, *, session: str | None = None) -> None:
    """Append one activity line. NEVER raises — an evidence sink must not be able to break a live tool call, the
    same rule observability.emit follows."""
    if not enabled():
        return
    try:
        ids: set = set()
        labels: set = set()
        _harvest(out, ids, labels)
        if not ids and not labels:
            return                                # a call that touched no run is not evidence; keep the ledger dense
        line = {
            "ts": round(time.time(), 3),
            "session": session or os.environ.get("CELLARIUM_SESSION") or None,
            "activity": tool,                     # PROV: Activity
            "args": _compact_args(args),
            "entity_ids": sorted(ids)[:200],      # PROV: Entity — the runs this claim rests on
            "entity_designs": sorted(labels)[:200],
            "env": _env(),                        # PROV: wasAssociatedWith (agent + software environment)
        }
        with _lock:
            LEDGER.parent.mkdir(parents=True, exist_ok=True)
            with LEDGER.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, default=str) + "\n")
    except Exception:
        pass


def note_omission(tool: str | None, omissions, *, session: str | None = None) -> None:
    """PLAT-2: record what a context trim removed, as its own ledger line beside the activity that produced it.

    Written separately rather than folded into `record` because the trim happens AFTER the tool returned, at
    the agent boundary, and a non-agent caller (the CLI, the UI) gets the untrimmed result — so the omission
    is a property of one delivery of a result, not of the call. Without this the ledger shows a complete-looking
    list of ids and a reviewer has no way to learn that the agent was shown a shorter one.
    """
    if not enabled() or not omissions:
        return
    try:
        line = {"ts": round(time.time(), 3),
                "session": session or os.environ.get("CELLARIUM_SESSION") or None,
                "activity": f"{tool or 'tool'}#omitted",
                "omitted": [o.as_dict() if hasattr(o, "as_dict") else o for o in omissions],
                "env": _env()}
        with _lock:
            LEDGER.parent.mkdir(parents=True, exist_ok=True)
            with LEDGER.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, default=str) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- reading it back
def read(path: str | os.PathLike | None = None) -> list[dict]:
    p = Path(path or LEDGER)
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except Exception:
                continue                          # a torn final line must not make the whole ledger unreadable
    return out


def trace(query: str, path: str | os.PathLike | None = None) -> dict:
    """Everything the ledger knows about a run id, a design key, or a tool name — the reviewer's question
    ("show me the runs behind this") answered mechanically."""
    q = (query or "").strip()
    rows = read(path)

    def _hit(r: dict) -> bool:
        # SUBSTRING, not equality: a reviewer asks "argS", and the evidence is spread across run ids
        # (`ko_argS_s0`), design keys (`gene_knockout/KO:argS`) and the call's own arguments. Matching only whole
        # ids would answer "no evidence" for a claim that is in fact fully grounded — the worst possible failure
        # for this tool, because it reads as an absence rather than a miss.
        if q in (r.get("activity") or ""):
            return True
        if any(q in x for x in (*r.get("entity_ids", []), *r.get("entity_designs", []))):
            return True
        return any(q in str(v) for v in (r.get("args") or {}).values())

    hits = [r for r in rows if _hit(r)]
    ids, designs, tools = set(), set(), set()
    for r in hits:
        ids |= set(r.get("entity_ids") or [])
        designs |= set(r.get("entity_designs") or [])
        tools.add(r.get("activity"))
    return {"query": q, "n_activities": len(hits), "tools": sorted(t for t in tools if t),
            "run_ids": sorted(ids), "designs": sorted(designs),
            "first_ts": min((r["ts"] for r in hits), default=None),
            "last_ts": max((r["ts"] for r in hits), default=None),
            "env": (hits[-1].get("env") if hits else None),
            "note": ("Append-only evidence ledger. `run_ids` join to the manifest `id` column, `designs` to "
                     "survey.design_key(). Empty means the claim was never grounded in a recorded tool call.")}
