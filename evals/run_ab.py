"""Unattended A/B batch runner — Council-vs-Cellwright at scale, backfilling the running app.

For each eval case (evals/cases.py) it runs BOTH arms and PERSISTS them into the app's data/sessions.db, then
grades + aggregates into evals/results/:

  * Arm B  (Socratic Council): council.deliberate() runs BLIND — zero corpus reads, the paper's quarantine control
    (docs/SOCRATIC_COUNCIL.md). The run is written to the council_runs table, so it shows up in the app's
    Hypotheses surface, and the resulting Hypothesis is graded against the literature rubric (evals/grade.py:
    a deterministic floor + an independent Opus judge that DOES see the answer key; the Council never does).
  * Arm A  (Cellwright direct): agent.converse() answers the SAME question directly. It reads the corpus BEFORE
    committing, so its hypothesis is data-informed (HARKing-prone). Written to the sessions table; its corpus-read
    count is the HARKing proxy (a blind Arm B has zero by construction).

Design goals (so you can literally leave it running):
  - UNATTENDED: never prompts; the Council's D3 ask_user is answered by a fixed scope policy.
  - CRASH-ISOLATED: a per-case/per-arm failure is recorded and the sweep continues.
  - RESUMABLE: a completed arm is skipped on re-launch (ledger at evals/results/ab_ledger.json). If it dies at
    case 17, re-launch and it picks up at 17.

Needs ANTHROPIC_API_KEY (read from .env at the repo ROOT). Long + billable: ~25 cases x 2 arms x many model calls.

    python evals/run_ab.py                         # all cases, both arms
    python evals/run_ab.py 4.2 5.2 8.1 --arm b     # a subset, Council only
    python evals/run_ab.py --arm a                 # Cellwright arm only
    # leave it running (POSIX):   nohup python evals/run_ab.py > evals/results/ab_console.log 2>&1 &
    # leave it running (Windows): Start-Process -NoNewWindow python 'evals/run_ab.py'  (or just run in a spare shell)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))     # cellarium package
sys.path.insert(0, str(ROOT / "apps"))    # SessionStore / HypothesisStore (the app's persistence)
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling `cases`, `grade`

import cases as cases_mod  # noqa: E402
import grade as grade_mod  # noqa: E402  (reuse the deterministic floor + the independent LLM judge)
from dotenv import load_dotenv  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
LEDGER = RESULTS / "ab_ledger.json"

# corpus-read tools: a hypothesis stated AFTER any of these is data-informed (the HARKing proxy). Mirrors
# scripts/ab_score.py so the two agree.
READ_TOOLS = {"survey_corpus", "viability", "list_results", "read_series", "differential", "top_movers",
              "disconfirm", "read_raw_series", "variance_band", "mechanistic_scope"}


# --- ledger (resume) ---------------------------------------------------------------------------------------

def _load_ledger() -> dict:
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_ledger(led: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(led, indent=2, default=str), encoding="utf-8")
    tmp.replace(LEDGER)   # atomic-ish: a crash mid-write leaves the prior ledger intact


def _log(msg: str) -> None:
    print(msg, flush=True)   # flush so `tail -f` shows progress live in an unattended run


# --- Arm B: the blind Socratic Council, persisted + graded --------------------------------------------------

def run_arm_b(case: dict, client, council_models: dict, rounds: int, quota: int, grader_model: str) -> dict:
    """Deliberate blind, persist to council_runs (app-visible), grade against the rubric. Returns a result row."""
    from cellarium import council, ui
    from hypotheses import HypothesisStore

    hstore = HypothesisStore()
    run_id = hstore.new_id()
    hstore.create(run_id, case["question"], council_models.get("proposer"))

    # The eval deliberates DIRECTLY — it does NOT run the app's sufficiency gate. The eval cases are the
    # deliberately-vague literature SEED questions the Council exists to midwife (e.g. "What does a cell do when it
    # runs out of amino acids?" -> the stringent response). Gating them parks ~23/25 and would measure the gate, not
    # the Council. Mirrors evals/grade.py, which never gated. We still record the gate's deterministic pre-pass
    # verdict as a DIAGNOSTIC — how often the APP gate would fire on a canonical scientific question — but we always
    # deliberate. (This is the empirical case that the app gate conflicts with the Council's core competency.)
    gate_prepass_specific = council.looks_specific(case["question"])

    def _round(payload):
        hstore.append_round(run_id, payload)

    h = council.deliberate(case["question"], max_rounds=rounds, quota=quota,
                           ask_user=lambda q: grade_mod._ASK_POLICY, client=client,
                           models=council_models, on_round=_round, verbose=False)

    # persist the finished run exactly like apps/hypotheses.run_council, so the Hypotheses surface renders it
    hview = ui.hypothesis_view(h)
    designs = [ui.design_view(d) for d in (getattr(h, "candidate_designs", None) or [])]
    ledger = getattr(h, "objection_ledger", None) or []
    meta = {"converged": getattr(h, "converged", None), "rounds_used": getattr(h, "rounds_used", None),
            "substantive_objections": getattr(h, "substantive_objections", None),
            "resolutions": {o["id"]: o.get("resolved_round") for o in ledger if o.get("id")}}
    hstore.complete(run_id, hview, designs, meta)
    hstore.rename(run_id, f"[eval {case['id']}] {case['theme']}")   # label it in the run list

    # grade the artifact (deterministic floor + independent judge that sees the answer key)
    det = grade_mod.deterministic(h)
    g = grade_mod.llm_grade(case, h, client, grader_model)
    min_c, str_c = g.get("min_criteria", []), g.get("stringent_criteria", [])
    min_judge = bool(min_c) and all(x.get("passed") for x in min_c)
    str_judge = bool(str_c) and all(x.get("passed") for x in str_c)
    min_bar = det["_floor_pass"] and min_judge
    stringent_bar = min_bar and str_judge and bool(h.converged)
    return {"id": case["id"], "run_id": run_id, "status": "done", "converged": bool(h.converged),
            "gate_prepass_specific": gate_prepass_specific,   # diagnostic: would the APP gate have let this through?
            "deterministic_floor": det["_floor_pass"], "min_bar_pass": min_bar,
            "stringent_bar_pass": stringent_bar, "min_criteria": min_c, "stringent_criteria": str_c,
            "comment": g.get("comment", ""), "hypothesis": hview}


# --- Arm A: Cellwright answers directly, persisted (sighted) ------------------------------------------------

def run_arm_a(case: dict, agent_model: str | None) -> dict:
    """Answer the question directly with the grounded agent; persist to the sessions table; count corpus reads."""
    from cellarium import agent
    from sessions import SessionStore

    messages = [{"role": "user", "content": case["question"]}]
    final = agent.converse(messages, model=agent_model, max_turns=12)   # mutates messages in place
    reads = sum(1 for m in messages if isinstance(m.get("content"), list)
                for b in m["content"] if isinstance(b, dict)
                and b.get("type") == "tool_use" and b.get("name") in READ_TOOLS)
    sid = "s_eval_" + case["id"].replace(".", "_")
    SessionStore().put(sid, {"model": agent_model, "used_council": False,
                             "title": f"[eval {case['id']}] {case['question'][:48]}", "messages": messages})
    return {"id": case["id"], "sid": sid, "corpus_reads": reads,
            "data_informed": reads > 0, "answer_chars": len(final or "")}


# --- sweep -------------------------------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Unattended Council-vs-Cellwright A/B sweep with app backfill.")
    p.add_argument("ids", nargs="*", help="case ids (default: all in evals/cases.py)")
    p.add_argument("--arm", choices=["both", "a", "b"], default="both")
    p.add_argument("--council-model", default=os.environ.get("CELLARIUM_MODEL") or "claude-sonnet-5")
    p.add_argument("--grader-model", default="claude-opus-4-8")
    p.add_argument("--agent-model", default=os.environ.get("CELLARIUM_MODEL"))  # None => agent.MODEL default
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--quota", type=int, default=3)
    p.add_argument("--force", action="store_true", help="re-run arms already in the ledger")
    a = p.parse_args()

    load_dotenv(str(ROOT / ".env"))
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _log("ERROR: ANTHROPIC_API_KEY not set. Put it in a .env at the repo root:\n"
             f"    {ROOT / '.env'}\n    ANTHROPIC_API_KEY=sk-ant-...\nAborting (no model access).")
        sys.exit(2)
    import anthropic
    client = anthropic.Anthropic(max_retries=4)
    council_models = {"proposer": a.council_model, "skeptic": a.council_model, "judge": a.council_model}

    selected = cases_mod.by_id(a.ids or None)
    led = _load_ledger()
    RESULTS.mkdir(parents=True, exist_ok=True)
    _log(f"A/B sweep: {len(selected)} case(s), arm={a.arm}, council={a.council_model}, "
         f"grader={a.grader_model}, agent={a.agent_model or 'default'}\n")

    t0 = time.time()
    for i, case in enumerate(selected, 1):
        cid = case["id"]
        slot = led.setdefault(cid, {})
        _log(f"[{i}/{len(selected)}] {cid}  {case['question'][:66]}")

        if a.arm in ("b", "both") and (a.force or "b" not in slot):
            try:
                slot["b"] = run_arm_b(case, client, council_models, a.rounds, a.quota, a.grader_model)
                r = slot["b"]
                _log(f"    Arm B  Council [{r.get('run_id')}]  status={r['status']}  "
                     f"converged={r.get('converged')}  min={'Y' if r.get('min_bar_pass') else 'n'} "
                     f"stringent={'Y' if r.get('stringent_bar_pass') else 'n'}")
            except Exception as exc:
                slot["b"] = {"id": cid, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
                _log(f"    Arm B  !! {type(exc).__name__}: {exc}")
                traceback.print_exc()
            _save_ledger(led)

        if a.arm in ("a", "both") and (a.force or "a" not in slot):
            try:
                slot["a"] = run_arm_a(case, a.agent_model)
                r = slot["a"]
                _log(f"    Arm A  Cellwright [{r.get('sid')}]  corpus-reads={r.get('corpus_reads')}  "
                     f"-> {'data-informed' if r.get('data_informed') else 'no corpus read'}")
            except Exception as exc:
                slot["a"] = {"id": cid, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
                _log(f"    Arm A  !! {type(exc).__name__}: {exc}")
                traceback.print_exc()
            _save_ledger(led)

    _aggregate(led, selected, a, time.time() - t0)


def _aggregate(led: dict, selected: list, args, elapsed: float) -> None:
    """Roll the ledger up into a scorecard: Council min/stringent-bar pass rates + the HARKing contrast."""
    ok_b = [led[c["id"]]["b"] for c in selected if led.get(c["id"], {}).get("b", {}).get("status") == "done"]
    err_b = [c["id"] for c in selected if led.get(c["id"], {}).get("b", {}).get("status") == "error"]
    n_min = sum(bool(r.get("min_bar_pass")) for r in ok_b)
    n_str = sum(bool(r.get("stringent_bar_pass")) for r in ok_b)
    # gate diagnostic: of the canonical questions the Council deliberated, how many would the APP's gate pre-pass
    # have let through? (Low = the gate over-fires on exactly the questions the Council is built to answer.)
    gate_pass = [r["id"] for r in ok_b if r.get("gate_prepass_specific")]
    a_rows = [led[c["id"]]["a"] for c in selected if "corpus_reads" in led.get(c["id"], {}).get("a", {})]
    a_informed = sum(bool(r.get("data_informed")) for r in a_rows)

    summary = {
        "n_cases": len(selected), "arm": args.arm, "elapsed_sec": round(elapsed, 1),
        "council_model": args.council_model, "grader_model": args.grader_model,
        "arm_b_council": {
            "n_deliberated": len(ok_b), "n_error": len(err_b), "error_ids": err_b,
            "n_min_bar": n_min, "n_stringent_bar": n_str,
            "gate_diagnostic": {"n_gate_prepass_pass": len(gate_pass),
                                "note": "the eval deliberates all cases directly; this counts how many the APP "
                                        "sufficiency-gate pre-pass would have let through unblocked."}},
        "arm_a_cellwright": {
            "n_answered": len(a_rows), "n_data_informed": a_informed,
            "note": "Arm A reads the corpus before committing (HARKing-prone); Arm B is blind by construction."},
        "ledger": led,
    }
    (RESULTS / "ab_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    _log("\n" + "=" * 72)
    _log(f"Arm B (Council):  deliberated {len(ok_b)}   min-bar {n_min}/{len(ok_b)}   "
         f"stringent-bar {n_str}/{len(ok_b)}   errored {len(err_b)}")
    _log(f"  gate diagnostic: only {len(gate_pass)}/{len(ok_b)} of these canonical questions would clear the "
         f"app gate pre-pass — the gate over-fires on the Council's own competency")
    _log(f"Arm A (Cellwright): answered {len(a_rows)}   data-informed {a_informed}/{len(a_rows)} "
         f"(blind Arm B = 0/{len(ok_b)} by construction)")
    _log(f"\n-> evals/results/ab_summary.json   ·   app backfill: Council runs in the Hypotheses surface; "
         f"Arm A in the sessions table")
    _log("   score the HARKing contrast per-case with:  python scripts/ab_score.py")


if __name__ == "__main__":
    main()
