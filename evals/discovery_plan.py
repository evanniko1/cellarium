"""Turn the discovery campaign's approved proposals into batch plans (scripts/bv_batch.py), one plan per seed question.

The protocol (DISCOVERY_CAMPAIGN.md, local): Cellwright proposes runs through the launch queue and a person approves
each one. Approved by the user, 2026-11-27: "proceed with ... where those simulations run", then "3 seeds locally is
fine, keep going". So each approved request runs on this machine at 3 seeds (0, 1, 2), whatever seed count it proposed,
at its proposed generation depth, on the knowledge base its mode and its comparison need. The queue entry is marked
`running` with the batch's name and the approval, so the interface's lifecycle shows what happened to it.

    python evals/discovery_plan.py <seed id> <sim_path> <request id> [<request id> ...]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
PLANS = REPO / "evals" / "plans"
SEEDS = (0, 1, 2)
APPROVED_BY = ("the user, 2026-11-27: \"proceed with the paid discovery runs ... where those simulations run\", then "
               "\"3 seeds locally is fine, keep going\"")


def build(seed_id: str, sim_path: str, request_ids: list[str], *, mark: bool = True) -> Path:
    from cellarium import launch
    q = {r["id"]: r for r in launch._load()}
    missing = [rid for rid in request_ids if rid not in q]
    if missing:
        raise SystemExit(f"not in the launch queue: {missing}")
    bad = [rid for rid in request_ids if q[rid]["status"] != "pending_approval"]
    if bad:
        raise SystemExit(f"not pending approval: {[(rid, q[rid]['status']) for rid in bad]}")
    batch = f"disc_{seed_id.lower()}"
    runs = []
    for n, rid in enumerate(request_ids, 1):
        req = q[rid]
        d = dict(req["design"])
        d = {k: v for k, v in d.items() if v not in (None, "") or k == "perturbation"}
        for s in SEEDS:
            runs.append({"id": f"{seed_id}-{n}-{rid}-s{s}", "design": d, "seed": s,
                         "generations": int(req.get("generations") or 3), "group": f"{seed_id}_{rid}",
                         "role": "run", "stage": 1})
    plan = {"batch": batch, "sim_path": sim_path, "parallel": 6, "min_free_gb": 40, "priority": 0, "keep_raw": True,
            "gates": {}, "approved_requests": request_ids, "approved_by": APPROVED_BY,
            "approved_with": {"seeds": list(SEEDS),
                              "proposed_seeds": {rid: q[rid].get("seeds") for rid in request_ids}},
            "why": f"discovery seed {seed_id}: the runs Cellwright proposed to test the Council's hypothesis",
            "runs": runs}
    plan["design_sha256"] = hashlib.sha256(json.dumps(runs, sort_keys=True).encode()).hexdigest()
    out = PLANS / f"{batch}.json"
    out.write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    if mark:
        with launch._txn() as qq:
            for r in qq:
                if r["id"] in request_ids:
                    r["status"] = "running"
                    r["batch"] = batch
                    r["approved_by"] = APPROVED_BY
                    r["approved_seeds"] = list(SEEDS)
    shown = out.relative_to(REPO) if out.is_relative_to(REPO) else out
    print(f"{shown}: {len(runs)} runs from {len(request_ids)} requests, design_sha256 "
          f"{plan['design_sha256'][:12]}")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    build(sys.argv[1], sys.argv[2], sys.argv[3:])
