"""Close-the-loop with a HUMAN APPROVAL GATE.

Coli PROPOSES experiments (the `propose_experiment` tool); each is vetted (safety is the only hard gate) and
queued as PENDING. Only a human approval — `approve_and_run`, which is NOT an agent tool; the hackathon interface
calls it — actually launches sims. After a run the data is indexed (record_existing) so Coli can reason over it.
Coli can never launch autonomously: the queue is the airlock.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .model import Design

QUEUE = Path("data/launch_queue.json")


def _load() -> list[dict]:
    return json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else []


def _save(q: list[dict]) -> None:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps(q, indent=2), encoding="utf-8")


def propose(perturbation: str = "wildtype", condition: str | None = None, timeline: str | None = None,
            params: dict | None = None, seeds: int = 4, generations: int = 4, gene: str | None = None) -> dict:
    """Vet + queue a proposed experiment. Never runs. A safety-flagged design is queued 'blocked'; otherwise
    'pending_approval'. Returns the request (with the full vet result)."""
    from . import tools
    vet = tools.vet_hypothesis(perturbation, condition, timeline, params, gene)
    req = {"id": "req_" + uuid.uuid4().hex[:8],
           "status": "blocked" if not vet.get("runnable") else "pending_approval",
           "design": {"perturbation": perturbation, "condition": condition, "timeline": timeline, "params": params or {}},
           "seeds": seeds, "generations": generations, "vet": vet, "ts": time.time()}
    q = _load(); q.append(req); _save(q)
    return {"request_id": req["id"], "status": req["status"], "runnable": vet.get("runnable"),
            "recommendation": vet.get("recommendation"), "vet": vet,
            "note": ("SAFETY-BLOCKED — will not run without human override." if req["status"] == "blocked"
                     else "Queued PENDING human approval — Coli cannot launch; a human approves via the interface.")}


def list_requests(status: str | None = None) -> list[dict]:
    return [{"id": r["id"], "status": r["status"], "design": r["design"], "seeds": r["seeds"],
             "generations": r["generations"], "recommendation": r.get("vet", {}).get("recommendation"),
             "vet": r.get("vet")}   # the interface renders the approval gate (safety/feasibility/provenance) from this
            for r in _load() if status is None or r["status"] == status]


def approve_and_run(request_id: str, parallel: int = 1, index: bool = True) -> dict:
    """HUMAN APPROVAL — launches the vetted design. NOT an agent tool (the interface / a human calls it). Refuses a
    safety-blocked request. Indexes the result so Coli can then reason over it."""
    from . import manifest
    q = _load()
    req = next((r for r in q if r["id"] == request_id), None)
    if not req:
        return {"error": f"no request '{request_id}'"}
    if req["status"] == "blocked":
        return {"error": "request is SAFETY-BLOCKED — refusing to run (override requires editing the queue by hand)."}
    if req["status"] != "pending_approval":
        return {"error": f"request is '{req['status']}', not pending_approval."}
    d = req["design"]
    design = Design(perturbation=d["perturbation"], condition=d["condition"], timeline=d["timeline"], params=d["params"])
    req["status"] = "running"; _save(q)
    try:
        shard = manifest.campaign([design], list(range(req["seeds"])), req["generations"], parallel)
        if index:
            manifest.record_existing()   # make the new data agent-visible
        req["status"], req["shard"] = "done", str(shard)
    except Exception as exc:
        req["status"], req["error"] = "failed", str(exc)[:200]
    _save(q)
    return {"request_id": request_id, "status": req["status"], "shard": req.get("shard"), "error": req.get("error")}


def reject(request_id: str) -> dict:
    q = _load()
    hit = False
    for r in q:
        if r["id"] == request_id and r["status"] in ("pending_approval", "blocked"):
            r["status"], hit = "rejected", True
    _save(q)
    return {"request_id": request_id, "status": "rejected" if hit else "not_found_or_not_pending"}
