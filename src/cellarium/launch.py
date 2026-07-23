"""Close-the-loop with a HUMAN APPROVAL GATE.

Cellwright PROPOSES experiments (the `propose_experiment` tool); each is vetted (safety is the only hard gate) and
queued as PENDING. Only a human approval — `approve_and_run`, which is NOT an agent tool; the hackathon interface
calls it — actually launches sims. After a run the data is indexed (record_existing) so Cellwright can reason over it.
Cellwright can never launch autonomously: the queue is the airlock.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

from .model import Design

# AG-1: root the queue at an ABSOLUTE, config-rooted path (env override, else the repo root derived from this file),
# not a CWD-relative 'data/...' — a job launched from a script run in a different directory used to write a stray
# queue the server never saw. src/cellarium/launch.py -> parents[2] is the repo root.
_ROOT = Path(__file__).resolve().parents[2]
QUEUE = Path(os.environ.get("CELLARIUM_QUEUE") or (_ROOT / "data" / "launch_queue.json"))

# AG-1: the queue was a LOCK-FREE read-modify-write — the server handles requests on threads (propose/revise/stamp/
# approve) and reconcile() runs at boot, so two concurrent load->mutate->save cycles could lose an update. A
# re-entrant lock serializes every mutation in-process (the only writer process); `_save` writes atomically
# (temp + os.replace), so even a crash mid-write, or a stray second process, can never leave a half-written queue
# (worst case is last-writer-wins, never corruption). Reads stay lock-free — os.replace means a reader always sees
# a complete file, old or new.
_LOCK = threading.RLock()


def _load() -> list[dict]:
    return json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else []


def _save(q: list[dict]) -> None:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(q, indent=2), encoding="utf-8")
    os.replace(tmp, QUEUE)   # atomic on POSIX + Windows — no half-written queue, ever


@contextlib.contextmanager
def _txn():
    """One atomic read-modify-write of the queue: hold the lock, load, hand the caller the list to mutate IN PLACE,
    then save. Serializes concurrent mutators so no update is lost. Use for single-step mutations; multi-step flows
    (revise, approve_and_run) hold `_LOCK` explicitly so they can release it around a long sim."""
    with _LOCK:
        q = _load()
        yield q
        _save(q)


def _resolve_ko(perturbation: str, params: dict | None, gene: str | None) -> tuple[dict, str | None]:
    """A gene KO runs on a variant INDEX, not a symbol: the runner reads params['variant_index'] / ['ko_indices']
    and IGNORES a symbolic 'target_genes'. Left unresolved, _variant_index falls back to a content HASH and the
    model silently knocks out the wrong gene. So resolve target gene(s) -> ko_index here (via scope), for BOTH
    interface- and agent-proposed designs. Returns (params_with_index, error_or_None); refuses if unresolvable."""
    params = dict(params or {})
    if perturbation not in ("gene_knockout", "multi_gene_knockout"):
        return params, None
    if "variant_index" in params or "ko_indices" in params:   # already correctly indexed — trust it
        return params, None
    genes = list(params.get("target_genes") or ([gene] if gene else []))
    if not genes:
        return params, f"{perturbation} needs a target gene (params.target_genes or gene=)."
    from . import scope
    idxs: list[int] = []
    for g in genes:
        ix = scope.classify_gene(g).get("ko_index")
        if ix is None:
            return params, f"could not resolve ko_index for gene '{g}' — check the symbol (design_space resolves it)."
        idxs.append(int(ix))
    params["target_genes"] = genes                            # keep the symbol for provenance
    if perturbation == "multi_gene_knockout":
        params["ko_indices"] = idxs
    else:
        params["variant_index"] = idxs[0]
    return params, None


def propose(perturbation: str = "wildtype", condition: str | None = None, timeline: str | None = None,
            params: dict | None = None, seeds: int = 4, generations: int = 4, gene: str | None = None) -> dict:
    """Vet + queue a proposed experiment. Never runs. A safety-flagged design is queued 'blocked'; otherwise
    'pending_approval'. A gene KO with no resolvable index is REFUSED (not queued) so we never run the wrong gene.
    Returns the request (with the full vet result)."""
    from . import tools
    params, err = _resolve_ko(perturbation, params, gene)
    if err:
        return {"status": "unresolved", "error": err,
                "note": "gene_knockout runs on a variant index; resolve the gene -> ko_index (design_space) first."}
    vet = tools.vet_hypothesis(perturbation, condition, timeline, params, gene)
    req = {"id": "req_" + uuid.uuid4().hex[:8],
           "status": "blocked" if not vet.get("runnable") else "pending_approval",
           "design": {"perturbation": perturbation, "condition": condition, "timeline": timeline, "params": params or {}},
           "seeds": seeds, "generations": generations, "vet": vet, "ts": time.time()}
    with _txn() as q:
        q.append(req)
    return {"request_id": req["id"], "status": req["status"], "runnable": vet.get("runnable"),
            "recommendation": vet.get("recommendation"), "vet": vet,
            "note": ("SAFETY-BLOCKED — will not run without human override." if req["status"] == "blocked"
                     else "Queued PENDING human approval — Cellwright cannot launch; a human approves via the interface.")}


def revise(request_id: str, *, perturbation: str | None = None, condition: str | None = None,
           timeline: str | None = None, params: dict | None = None, seeds: int | None = None,
           generations: int | None = None, gene: str | None = None, genes: list | None = None) -> dict:
    """REVISE a PENDING draft: mark the old one 'superseded' and queue a re-vetted new draft with the changed
    arg(s) merged over the old design. Keeps the human-approval airlock — only an UN-approved draft can be
    revised; a human still approves the result. Returns the new request (linked back via `revised_from`)."""
    with _LOCK:   # hold across the whole (fast, no-sim) revise so it can't interleave with another mutator
        q = _load()
        old = next((r for r in q if r["id"] == request_id), None)
        if not old:
            return {"error": f"no request '{request_id}'"}
        if old["status"] not in ("pending_approval", "blocked"):
            return {"error": f"request '{request_id}' is '{old['status']}' — only a pending draft can be revised."}
        d = old["design"]
        merged = dict(params) if params is not None else dict(d.get("params") or {})
        if genes:   # a gene-set change: drop stale indices so the new symbols are re-resolved
            merged["target_genes"] = list(genes)
            merged.pop("ko_indices", None); merged.pop("variant_index", None)
        old["status"] = "superseded"; _save(q)                       # withdraw the old draft (no duplicate left)
        res = propose(perturbation or d["perturbation"],             # re-acquires _LOCK (re-entrant); sees the save above
                      condition if condition is not None else d.get("condition"),
                      timeline if timeline is not None else d.get("timeline"),
                      merged,
                      seeds if seeds is not None else old["seeds"],
                      generations if generations is not None else old["generations"], gene)
        with _txn() as q:                                            # link old -> new for traceability
            for r in q:
                if r["id"] == request_id:
                    r["superseded_by"] = res.get("request_id")
    return {**res, "revised_from": request_id}


def list_requests(status: str | None = None) -> list[dict]:
    return [{"id": r["id"], "status": r["status"], "design": r["design"], "seeds": r["seeds"],
             "generations": r["generations"], "recommendation": r.get("vet", {}).get("recommendation"),
             "vet": r.get("vet"),   # the interface renders the approval gate (safety/feasibility/provenance) from this
             "session_id": r.get("session_id"), "hyp_id": r.get("hyp_id"),   # provenance: the chat OR the Hypothesis run that proposed it
             "from_question": r.get("from_question"),
             "ts": r.get("ts"), "shard": r.get("shard"), "error": r.get("error")}
            for r in _load() if status is None or r["status"] == status]


def stamp_provenance(request_id: str, session_id: str | None = None, question: str | None = None,
                     hyp_id: str | None = None) -> bool:
    """Record WHERE a queued job came from — an agent chat (session_id) or a Council/Hypothesis run (hyp_id) — plus
    the framing question. Powers the queue's click-to-jump-back-to-context (the agent stamps the sid; a Council
    falsifier queued from the surface stamps the hyp_id)."""
    with _txn() as q:
        for r in q:
            if r["id"] == request_id:
                if session_id:
                    r["session_id"] = session_id
                if hyp_id:
                    r["hyp_id"] = hyp_id
                if question:
                    r["from_question"] = question[:200]
                return True
    return False


# --- SP-1: per-design lifecycle — reflect the launch queue back onto a Hypothesis -------------------------
_LIFE_RANK = {"done": 6, "running": 5, "pending_approval": 4, "blocked": 3, "failed": 2, "superseded": 1,
              "rejected": 0, "unresolved": 0}


def _match_key(perturbation, condition, timeline, params) -> tuple:
    """A design's SEMANTIC identity for matching against queued/run jobs — perturbation/condition/timeline + the
    identifying params (gene set, ppGpp multiplier, operon count, TF targets). It deliberately EXCLUDES the resolved
    variant_index/ko_indices: a Council falsifier carries the gene SYMBOLS, and the queued job it spawns also carries
    the resolved index, so keying on the index would wrongly split them. Symbol-level identity matches both."""
    p = params or {}
    genes = tuple(sorted(str(g).lower() for g in (p.get("target_genes") or ([p["gene"]] if p.get("gene") else []))))
    ident = {k: p[k] for k in ("multiplier", "num_operons_to_delete", "direction", "target_tfs") if k in p}
    return (perturbation or "wildtype", condition or None, timeline or None, genes,
            json.dumps(ident, sort_keys=True, default=str))


def lifecycle_for_designs(designs: list[dict]) -> list[dict]:
    """For each rendered design (a dict with perturbation/condition/timeline/params), find any launch-queue job of the
    same semantic identity and return its lifecycle, PARALLEL to `designs`: {status, request_id, shard}. The
    most-advanced matching job wins (done > running > pending_approval > blocked > failed). status is 'proposed' when
    nothing matches. Matched by DESIGN, not hyp_id, so a run submitted from the Council surface OR proposed by
    Cellwright is reflected back onto the Hypothesis. Corpus 'in_corpus' membership is the caller's concern."""
    q = _load()
    by_key: dict[tuple, list] = {}
    for r in q:
        d = r.get("design") or {}
        by_key.setdefault(_match_key(d.get("perturbation"), d.get("condition"), d.get("timeline"), d.get("params")),
                          []).append(r)
    out = []
    for dv in designs:
        jobs = by_key.get(_match_key(dv.get("perturbation"), dv.get("condition"), dv.get("timeline"),
                                     dv.get("params")), [])
        job = max(jobs, key=lambda r: _LIFE_RANK.get(r.get("status"), -1), default=None)
        out.append({"status": (job["status"] if job else "proposed"),
                    "request_id": (job["id"] if job else None),
                    "shard": (job.get("shard") if job else None)})
    return out


def reconcile() -> dict:
    """Heal jobs orphaned at 'running' by a server restart/crash. approve_and_run runs the sim in an in-process
    thread, so if the server dies between the sim finishing and the status write, the job is stuck at 'running'
    forever even though its data landed. On startup, for each 'running' job: if the manifest already has a run for
    its design -> 'done' (the data is indexed and agent-visible); otherwise it produced nothing -> 'failed'. We ask
    the manifest, not a recomputed run dir, because the raw output's location (out/ vs runs/) and the variant-index
    hash are both unreliable to reproduce. Idempotent; run once at boot."""
    from . import manifest
    from .model import Design

    healed = 0
    with _txn() as q:
        for r in q:
            if r.get("status") != "running":
                continue
            d = r.get("design") or {}
            landed = 0
            try:
                design = Design(perturbation=d["perturbation"], condition=d.get("condition"),
                                timeline=d.get("timeline"), params=d.get("params") or {})
                landed = manifest.count_runs(design)   # DISTINCT seeds indexed — not just ">=1" (the false-'done' bug)
            except Exception:
                landed = 0
            requested = int(r.get("seeds") or 0)
            # a multi-seed campaign that crashed after seed 0 must NOT report 'done' — that hid an incomplete run and
            # a null shard behind a green status. 'done' only when every requested seed landed; 'partial' otherwise.
            if landed <= 0:
                r["status"] = "failed"
                r["error"] = "orphaned at 'running' (server restart/crash mid-run); no indexed run found"
            elif requested and landed < requested:
                r["status"] = "partial"
                r["error"] = f"orphaned mid-campaign: only {landed}/{requested} seeds indexed (crash before completion)"
            else:
                r["status"] = "done"
            healed += 1
    return {"reconciled": healed}


def clear_finished() -> dict:
    """The queue's 'Clear': drop FINISHED/dismissed requests (done, failed, rejected, superseded) from the airlock,
    keeping live work (pending_approval, running, blocked). Called after the user has seen the results."""
    with _LOCK:
        q = _load()
        keep = [r for r in q if r["status"] in ("pending_approval", "running", "blocked")]
        n = len(q) - len(keep)
        _save(keep)
    return {"cleared": n, "remaining": len(keep)}


def clear_all() -> dict:
    """The queue's 'Clear ALL': drop every request EXCEPT one that is actively running (never orphan a live sim).
    For wiping a pile of accumulated pending drafts in one go."""
    with _LOCK:
        q = _load()
        keep = [r for r in q if r["status"] == "running"]
        n = len(q) - len(keep)
        _save(keep)
    return {"cleared": n, "remaining": len(keep)}


def approve_and_run(request_id: str, parallel: int = 1, index: bool = True) -> dict:
    """HUMAN APPROVAL — launches the vetted design. NOT an agent tool (the interface / a human calls it). Refuses a
    safety-blocked request. Indexes the result so Cellwright can then reason over it."""
    from . import manifest
    with _LOCK:   # claim the job (validate + flip to 'running') atomically, then RELEASE before the long sim
        q = _load()
        req = next((r for r in q if r["id"] == request_id), None)
        if not req:
            return {"error": f"no request '{request_id}'"}
        if req["status"] == "blocked":
            return {"error": "request is SAFETY-BLOCKED — refusing to run (override requires editing the queue by hand)."}
        if req["status"] != "pending_approval":
            return {"error": f"request is '{req['status']}', not pending_approval."}
        d = req["design"]
        seeds, generations = req["seeds"], req["generations"]
        req["status"] = "running"; _save(q)
    design = Design(perturbation=d["perturbation"], condition=d["condition"], timeline=d["timeline"], params=d["params"])
    shard: str | None = None
    error: str | None = None
    try:
        # campaign runs the sim AND indexes the new run into its own shard (one reader container per run) — that
        # alone makes it agent-visible. Then compact() consolidates shards WITHOUT re-reading every run on disk
        # (record_existing did, which spun a container per corpus run — the "blinking + seems-stuck" churn, and it
        # deleted the shard we then referenced). compact leaves ONE surviving shard, so point `shard` at it. Run OUTSIDE
        # the lock — a sim takes minutes and must not block propose/list/stamp on other threads.
        s = manifest.campaign([design], list(range(seeds)), generations, parallel)
        if index:
            res = manifest.compact()
            s = res.get("shard") or s
        shard, status = str(s), "done"
    except Exception as exc:
        status, error = "failed", str(exc)[:200]
    with _LOCK:   # re-acquire to write the terminal status (re-find the job — the queue may have changed under us)
        q = _load()
        req = next((r for r in q if r["id"] == request_id), None)
        if req is not None:
            req["status"] = status
            if error is None:
                req["shard"] = shard
            else:
                req["error"] = error
        _save(q)
    return {"request_id": request_id, "status": status, "shard": shard, "error": error}


def reject(request_id: str) -> dict:
    hit = False
    with _txn() as q:
        for r in q:
            if r["id"] == request_id and r["status"] in ("pending_approval", "blocked"):
                r["status"], hit = "rejected", True
    return {"request_id": request_id, "status": "rejected" if hit else "not_found_or_not_pending"}
