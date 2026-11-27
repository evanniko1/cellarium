"""The discovery campaign's paid steps (DISCOVERY_CAMPAIGN.md, local): for each seed question, a blind Council
deliberation, the question gate, then Cellwright testing the Council's hypothesis against the corpus.

It drives the SAME functions the interface does, so every step leaves a trace the interface can open:
  - the Council through `hypotheses.run_council` (persisted in the app's store: the Hypothesis surface's run list);
  - the gate through `orchestrate.gate_question`, before any tool is dispatched;
  - Cellwright through `agent.converse` on the Council's brief (`agent.first_user_content`), inside the gate's
    admission, persisted as an app session.
Models are the interface's own on Auto: the Council's default, and Opus for a Council-framed investigation.

Spend: every model call is metered (observability). Before each stage the run stops if the metered spend plus that
stage's high estimate would pass `--max-usd` (exit 4, the finished stages kept). Stage highs are measured, not
assumed: the Council at $0.78 (the most a full Council question metered in M1+M2, 30 records), Cellwright at $1.85
(39,394 input tokens for its first call by the free token counter, 2026-11-27, 12 turns, Opus prices).

    PYTHONPATH=src .venv/Scripts/python.exe scripts/run_discovery.py --dry-run
    PYTHONPATH=src .venv/Scripts/python.exe scripts/run_discovery.py --seeds S1,S3,S4 --max-usd 40
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "apps"))
sys.path.insert(0, str(REPO / "evals"))

OUT = REPO / "audit" / "discovery" / "discovery_runs.json"      # local: the campaign is unpublished until adjudicated
CELLWRIGHT_MODEL = "claude-opus-4-8"                           # the interface's Auto choice for a Council-framed turn
STAGE_HIGH_USD = {"council": 0.78, "gate": 0.05, "cellwright": 1.85}

# The campaign's seed questions (DISCOVERY_CAMPAIGN.md), each followed by the mode and perturbation the registry says
# represent it, as scripts/run_council_kinetic.py does. Blind: no sentence states a simulated result.
SEEDS = {
    "S1": ("When the enzyme that charges one amino acid's tRNAs is partly depleted, which of that amino acid's "
           "isoacceptors lose charging first? Ask it of the kinetic elongation model, where each isoacceptor is "
           "charged separately, and of synthetase limitation by graded knockdown, not amino-acid starvation."),
    "S2": ("Does the stringent response soften the growth cost of making too little of a tRNA synthetase in E. coli? "
           "Ask it of the steady-state model, where ppGpp is dynamic, by graded knockdown of a synthetase with ppGpp "
           "free against ppGpp held at its basal level."),
    "S3": ("When one isoacceptor's charging falls, which codons slow translation: only those it reads, or also those "
           "it shares by wobble with a still-charged isoacceptor? Ask it of the kinetic elongation model, under "
           "synthetase limitation by graded knockdown."),
    "S4": ("After amino acids are removed from a rich medium, does a cell with fewer rRNA operons slow down more or "
           "less than one with the full set, and how does its ppGpp respond? Ask it of the steady-state model, with "
           "the timeline 0 minimal_plus_amino_acids, 1200 minimal, reading growth rate and ppGpp rather than "
           "division timing."),
}


# The mode each seed is asked in. The gate decides representability IN a mode, and its default is the steady-state
# corpus mode, where per-isoacceptor charging and codon-level elongation are not represented: asked there, S1 and S3
# would be refused with a route to "kinetic", and Cellwright would never run.
MODES = {"S1": "kinetic", "S2": "steady_state", "S3": "kinetic", "S4": "steady_state"}


def _load() -> dict:
    if OUT.is_file():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"campaign": "DISCOVERY_CAMPAIGN.md seeds", "records": {}, "spent_usd": 0.0}


def _save(state: dict) -> None:
    """Atomic write; in-memory keys (a leading underscore, such as the Council's hypothesis object) are not saved."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    clean = {**state, "records": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                                  for k, v in state["records"].items()}}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=1, default=str) + "\n", encoding="utf-8")
    tmp.replace(OUT)


def _fits(state: dict, stage: str, cap: float) -> bool:
    return state["spent_usd"] + STAGE_HIGH_USD[stage] <= cap


def run_seed(sid: str, state: dict, cap: float) -> str:
    """One seed's three stages; each stage's result is saved as it finishes. Returns 'done', 'gated' or 'capped'."""
    import hypotheses
    from sessions import SessionStore

    from cellarium import agent, effect, observability, orchestrate

    rec = state["records"].setdefault(sid, {"question": SEEDS[sid], "elongation_model": MODES[sid]})
    question = rec["question"]

    # 1. the Council, blind, persisted in the app's store
    if "council" not in rec:
        if not _fits(state, "council", cap):
            return "capped"
        got: dict = {}
        run = hypotheses.run_council(hypotheses.HypothesisStore(), question,
                                     on_hypothesis=lambda rid, hyp: got.update(hyp=hyp))
        cost = float((run.get("meta") or {}).get("llm", {}).get("cost_usd") or 0.0)
        state["spent_usd"] += cost
        hyp = got.get("hyp")
        rec["council"] = {"run_id": run["id"], "status": run.get("status"), "cost_usd": round(cost, 4),
                          "hypothesis": run.get("hypothesis"), "designs": run.get("designs"),
                          "meta": {k: (run.get("meta") or {}).get(k) for k in
                                   ("converged", "rounds_used", "substantive_objections", "model", "temperature")},
                          "brief": hyp.brief() if hyp is not None and hasattr(hyp, "brief") else None}
        rec["_hyp"] = hyp                                    # in memory only, for this process's Cellwright step
        _save(state)

    # 2. the gate, then 3. Cellwright on the Council's brief
    if "cellwright" not in rec:
        if rec.get("gate", {}).get("verdict") not in (None, "answer"):
            return "gated"
        if not (_fits(state, "gate", cap) and _fits(state, "cellwright", cap - STAGE_HIGH_USD["gate"])):
            return "capped"
        hyp = rec.pop("_hyp", None)
        if hyp is None:
            raise SystemExit(f"{sid}: the Council ran in an earlier process; its hypothesis object is not held. "
                             "Re-run the Council for this seed (delete its 'council' record) rather than hand "
                             "Cellwright a reconstructed brief.")
        with observability.meter() as gm:
            decision = orchestrate.gate_question(question, elongation_model=MODES[sid])
        gcost = float(gm.summary().get("cost_usd") or 0.0)
        state["spent_usd"] += gcost
        rec["gate"] = {"verdict": decision.verdict, "required_capabilities": list(decision.required_capabilities),
                       "blocking": list(decision.blocking), "route": decision.route, "notes": list(decision.notes),
                       "reason": decision.reason, "cost_usd": round(gcost, 4)}
        if decision.verdict != "answer":
            _save(state)
            return "gated"
        trace: list = []
        usage: dict = {}
        sess_id = f"s_disc_{sid}_{uuid.uuid4().hex[:6]}"
        messages = [{"role": "user", "content": agent.first_user_content(question, hyp)}]
        t0 = time.time()
        with effect.admitted(decision):
            answer = agent.converse(messages, model=CELLWRIGHT_MODEL, verbose=False,
                                    on_tool=lambda n, i, o: trace.append({"tool": n, "input": i}),
                                    on_usage=lambda s: usage.update(s))
        ccost = float(usage.get("cost_usd") or 0.0)
        state["spent_usd"] += ccost
        SessionStore().put(sess_id, {"messages": messages, "model": CELLWRIGHT_MODEL, "used_council": True,
                                     "title": f"Discovery {sid}: {question[:60]}",
                                     "temperature": agent.temperature_for(CELLWRIGHT_MODEL)})
        rec["cellwright"] = {"session_id": sess_id, "model": CELLWRIGHT_MODEL, "answer": answer,
                             "tools": trace, "usage": usage, "cost_usd": round(ccost, 4),
                             "wall_s": round(time.time() - t0, 1)}
        _save(state)
    return "done"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", default="S1,S2,S3,S4")
    p.add_argument("--max-usd", type=float, default=40.0)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    seeds = [s.strip() for s in a.seeds.split(",") if s.strip()]
    unknown = [s for s in seeds if s not in SEEDS]
    if unknown:
        raise SystemExit(f"unknown seeds {unknown}; known: {sorted(SEEDS)}")
    per_seed = sum(STAGE_HIGH_USD.values())
    plan = {"seeds": seeds, "cap_usd": a.max_usd, "high_per_seed_usd": round(per_seed, 2),
            "high_total_usd": round(per_seed * len(seeds), 2), "cellwright_model": CELLWRIGHT_MODEL, "out": str(OUT)}
    if a.dry_run:
        print(json.dumps(plan, indent=1))
        return 0
    import api_keys
    api_keys.require("anthropic")
    state = _load()
    print(json.dumps(plan))
    for sid in seeds:
        status = run_seed(sid, state, a.max_usd)
        print(f"{sid}: {status}; spent so far ${state['spent_usd']:.2f}", flush=True)
        if status == "capped":
            _save(state)
            print(f"stopped: the next stage's high estimate would pass the ${a.max_usd:.2f} cap", file=sys.stderr)
            return 4
    _save(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
