"""Trivial answers to the Council's questions, scored by every instrument that scores a Council answer (Agentic
Benchmark Checklist R.13, trivial agents, and O.b.2, success by listing every possibility).

A reviewer asks two things of any graded system: would doing nothing score, and would hedging every possibility
score? Nothing had asked them of the Council. Three answers per case, built here without a model and without
reading the case beyond its question:

  restated   the question as a claim, every field the schema requires filled with boilerplate that measures
             nothing in particular ("the perturbation changes the observable"), and the one design any agent
             can write without understanding the question: wildtype, basal, eight seeds;
  hedge_all  every outcome predicted at once (an increase, a decrease or no change), every rival "may
             contribute", real channel names, the same generic design, and a falsifier no result can trigger;
  empty      the schema's fields present and empty.

FREE (no model; `--dry-run` prints it): the Council's own deterministic checks. `council._score` is the rule
best-of-N keeps a draft by; `grade.deterministic` is the A/B's minimum bar.

PAID: each answer is scored by the instruments that score a Council hypothesis: the six-criterion rubric (Claude
and GPT, evals/ablate.py), the residual-defect auditors (evals/audit.py) and the A/B's shared case-rubric judge
(evals/shared_metric.py). The stored real answers are the comparison. A trivial answer that scores near them says
that instrument measures form, not content.

    python evals/trivial_baselines.py --dry-run                 # the free checks and the estimate
    python evals/trivial_baselines.py --max-usd 5               # the paid scoring, 10 cases x 3 answers

The cases are the ten exploratory ones (evals/ablate.py EXPLORATORY_IDS). Progress goes to <out>.partial.json, the
artefact is written once, complete, and an outage (exit 3) or the spend cap (exit 4) stops the run.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ablate  # noqa: E402
import api_keys  # noqa: E402
import audit  # noqa: E402
import cases as cases_mod  # noqa: E402
import costs  # noqa: E402
import grade as grade_mod  # noqa: E402
import shared_metric  # noqa: E402

from cellarium import council, instrument, observability, outage, provenance  # noqa: E402

KINDS = ("restated", "hedge_all", "empty")
GENERIC_DESIGN = {"perturbation": "wildtype", "condition": "basal", "seeds": 8}
_RUBRIC = ("falsifiable", "specified", "operationalized", "discriminating")


def build(question: str, kind: str) -> dict:
    """One trivial answer, as the proposer's tool would emit it. Uses nothing about the case but its question."""
    if kind == "restated":
        return {
            "claim": f"The perturbation in question changes the outcome the question asks about. Question: {question}",
            "h1": "The observable differs between the perturbed design and the reference design.",
            "h0": "The observable does not differ between the perturbed design and the reference design.",
            "operational_defs": [{"construct": "the outcome", "observable": "the observable",
                                  "measure": "its value across seeds"}],
            "predicted_effect": "a change relative to the reference",
            "falsifier": {"target": "the perturbed design", "reference": "the reference design",
                          "channel": "the observable", "decision_rule": "reject H0 if the observable differs",
                          "refuting_result": "no difference between the designs"},
            "rivals": [{"claim": "chance", "distinguishing_result": "no consistent difference across seeds"},
                       {"claim": "another mechanism", "distinguishing_result": "a different pattern of change"}],
            "auxiliary_assumptions": ["the simulation represents the process"],
            "candidate_designs": [dict(GENERIC_DESIGN)],
        }
    if kind == "hedge_all":
        ch = list(instrument.channel_names())[:3]
        return {
            "claim": "The perturbation may increase, decrease or leave unchanged any observable, depending on "
                     "conditions, and any of these outcomes would be consistent with the mechanism.",
            "h1": "Each observable will rise, fall or stay the same relative to the reference.",
            "h0": "Each observable will stay the same relative to the reference.",
            "operational_defs": [{"construct": "any effect", "observable": c, "measure": "any change in any "
                                  "direction, at any time"} for c in ch],
            "predicted_effect": "an increase, a decrease, or no change; possibly transient, possibly sustained",
            "falsifier": {"target": "the perturbed design", "reference": "wildtype/basal", "channel": ch[0],
                          "decision_rule": "reject H0 if any change in any direction is seen",
                          "refuting_result": "none: every outcome matches one of the predicted possibilities"},
            "rivals": [{"claim": "the effect is direct", "distinguishing_result": "a change in either direction"},
                       {"claim": "the effect is indirect", "distinguishing_result": "a change in either direction"},
                       {"claim": "there is no effect", "distinguishing_result": "no change, or a small one"}],
            "auxiliary_assumptions": ["any outcome may occur"],
            "candidate_designs": [dict(GENERIC_DESIGN)],
        }
    if kind == "empty":
        return {"claim": "", "h1": "", "h0": "", "operational_defs": [], "predicted_effect": "",
                "falsifier": {"target": "", "reference": "", "channel": "", "decision_rule": "",
                              "refuting_result": ""},
                "rivals": [], "auxiliary_assumptions": [], "candidate_designs": []}
    raise ValueError(f"unknown kind {kind!r}; one of {KINDS}")


def hypothesis(question: str, kind: str):
    """The answer as the Council would return it, so every instrument sees exactly what it sees for a real one."""
    return council._assemble(question, build(question, kind), residual=[], converged=True, rounds_used=1)


def free_checks(question: str, kind: str) -> dict:
    """What the Council's own deterministic checks make of a trivial answer. No model call."""
    cand = build(question, kind)
    ok = council._structural_ok(cand)
    det = grade_mod.deterministic(hypothesis(question, kind))
    return {"council_score": council._score(cand, council._feasible(cand), dict.fromkeys(_RUBRIC, ok)),
            "council_score_max": 16, "complete": council._complete(cand), "structural_ok": ok,
            "feasible": council._feasible(cand), "ab_minimum_bar": det.get("_floor_pass"),
            "ab_checks": {k: v for k, v in det.items() if not k.startswith("_")}}


def _score_one(case: dict, kind: str, client, oai, gpt_model: str, claude: str, judge: str) -> dict:
    rec = {"id": case["id"], "kind": kind, "free": free_checks(case["question"], kind)}
    h = hypothesis(case["question"], kind)
    payload = {"id": case["id"], "hypothesis": h.model_dump(by_alias=True, mode="json")}
    with observability.meter(this_thread=True) as m:
        try:
            gc = ablate.grade_claude(case, h, client, claude)
            rec["rubric_claude"] = ablate._score(gc)
            ca = audit.audit_claude(payload, client, claude)
            rec["defects_claude"] = len(ca["defects"])
            rec["defect_list_claude"] = ca["defects"]
            sm = shared_metric.grade(case, shared_metric.from_council(h), client, judge)
            rec["shared_quality"] = sm.get("quality_score")
            rec["shared_judged"] = sm.get("judged")
            rec["shared_min_bar"] = sm.get("min_bar_pass")
            if oai is not None:
                gg = ablate.grade_gpt(case, h, oai, gpt_model)
                rec["rubric_gpt"] = ablate._score(gg)
                ga = audit.audit_gpt(payload, oai, gpt_model)
                rec["defects_gpt"] = len(ga["defects"])
        except Exception as exc:                                      # noqa: BLE001 - recorded, never a score
            rec["error"] = f"{type(exc).__name__}: {exc}"
    rec["llm"] = m.summary()
    return rec


def reference_points(case_ids) -> dict:
    """The stored real answers to the same cases, each scored by the instrument it is compared with: the rubric
    (ablation.json), the GPT defect count (audited.json; the stored Claude column is not used, see evals/audit.py)
    and the shared judge's quality of the A/B's Cellwright answers (ab_ledger.json, arm A).

    The A/B's Council rows predate the shared judge: their criteria come from grade.llm_grade, a different grader
    that sees the structured hypothesis, so no stored Council answer has a shared-judge score. That reference is
    absent and says why; it is never filled in from the other grader."""
    ids = set(case_ids)
    out: dict = {}
    abl = (costs._stored("ablation.json") or {}).get("results") or []
    aud = (costs._stored("audited.json") or {}).get("results") or []
    for cfg in ("full", "proposer_only"):
        rs = [r for r in abl if r.get("config") == cfg and r.get("claude") and r.get("id") in ids]
        ds = [r["gpt_defects"] for r in aud if r.get("config") == cfg and "gpt_defects" in r and r.get("id") in ids]
        out[cfg] = {"rubric_claude": round(sum(r["claude"]["score"] for r in rs) / len(rs), 2) if rs else None,
                    "defects_gpt": round(sum(ds) / len(ds), 2) if ds else None}
    ab = costs._stored("ab_ledger.json") or {}
    q = [(s.get("a") or {}).get("quality_score") for k, s in ab.items() if s.get("_case", k) in ids]
    q = [x for x in q if x is not None]
    out["ab_cellwright_shared_quality"] = round(sum(q) / len(q), 4) if q else None
    out["ab_council_shared_quality_absent"] = ("the A/B's Council rows predate the shared judge (their criteria "
                                               "come from grade.llm_grade, which sees the structured hypothesis)")
    return out


def run(case_ids, out_path: str, *, client, oai, gpt_model="gpt-4o", claude="claude-opus-4-8",
        judge="claude-opus-4-8", workers=4, max_usd=None) -> int:
    cases = cases_mod.by_id(case_ids)
    tasks = [(c, k) for c in cases for k in KINDS]
    meta = {"kinds": list(KINDS), "case_ids": [c["id"] for c in cases], "claude": claude,
            "gpt": gpt_model if oai else None, "judge": judge,
            "reference": reference_points([c["id"] for c in cases]),
            "environment": provenance.code_environment()}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.stem + ".partial.json")
    brk = outage.Breaker()
    per = costs.estimate_trivial(1, 1, gpt=oai is not None)["per_record"]["high"]
    cap = costs.SpendCap(max_usd, reserve_usd=workers * per if max_usd else 0.0)
    results, lock = [], threading.Lock()

    def _guarded(t):
        if brk.tripped or cap.tripped:
            return None
        rec = _score_one(t[0], t[1], client, oai, gpt_model, claude, judge)
        brk.observe("error" not in rec, (rec.get("error") or "").split(":")[0])
        cap.add(*costs.record_cost(rec.get("llm")))
        return rec

    skipped = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(_guarded, t) for t in tasks]):
            rec = fut.result()
            if rec is None:
                skipped += 1
                continue
            with lock:
                results.append(rec)
                partial.write_text(json.dumps({**meta, "results": results}, indent=2), encoding="utf-8")
            print(f"{rec['id']:4s} {rec['kind']:9s} rubric={rec.get('rubric_claude')}/{rec.get('rubric_gpt')} "
                  f"defects={rec.get('defects_claude')}/{rec.get('defects_gpt')} shared={rec.get('shared_quality')} "
                  f"{rec.get('error', '')}", flush=True)
    stopper = brk if brk.tripped else cap if (cap.tripped and skipped) else None   # a stop is a record not run
    if stopper is not None:
        partial.write_text(json.dumps({**meta, "stopped_early": stopper.report(len(tasks)), "results": results},
                                      indent=2), encoding="utf-8")
        print(f"STOPPED; partial results, not a result: {partial}", flush=True)
        return brk.exit_code() if stopper is brk else costs.EXIT_SPEND_CAP
    out.write_text(json.dumps({**meta, "spent_usd": round(cap.spent, 4), "results": results}, indent=2),
                   encoding="utf-8")
    partial.unlink(missing_ok=True)
    print(f"wrote {len(results)} -> {out} (metered ${cap.spent:.2f})", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("ids", nargs="*", help="case ids; default: the ten exploratory cases")
    p.add_argument("--out", default=str(HERE / "results" / "trivial_baselines.json"))
    p.add_argument("--gpt-model", default="gpt-4o")
    p.add_argument("--claude", default="claude-opus-4-8", help="the rubric grader and the defect auditor")
    p.add_argument("--judge", default="claude-opus-4-8", help="the A/B's shared case-rubric judge")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-usd", type=float)
    p.add_argument("--dry-run", action="store_true", help="print the free checks and the estimate; call nothing")
    a = p.parse_args()
    ids = list(a.ids) or list(ablate.EXPLORATORY_IDS)
    if ablate.held_out(ids):
        p.error(f"{', '.join(ablate.held_out(ids))} are held out for the confirmatory run (BACKLOG PUB-A3)")
    q = cases_mod.by_id(ids[:1])[0]["question"]
    for kind in KINDS:
        f = free_checks(q, kind)
        print(f"{kind:9s} council._score {f['council_score']}/{f['council_score_max']}  complete={f['complete']} "
              f"structural={f['structural_ok']} feasible={f['feasible']}  A/B minimum bar={f['ab_minimum_bar']}")
    est = costs.estimate_trivial(len(ids), len(KINDS), gpt=True)     # every grader, GPT's included
    print(f"{len(ids)} cases x {len(KINDS)} answers: estimate USD low / central / high "
          f"{est['total_usd']['low']:.2f} / {est['total_usd']['central']:.2f} / {est['total_usd']['high']:.2f}")
    if a.dry_run:
        print("(dry run -- nothing called)")
        return 0
    api_keys.require(api_keys.ANTHROPIC, api_keys.OPENAI)
    import openai

    from cellarium import llm
    client = llm.client(max_retries=6)
    oai = openai.OpenAI(max_retries=6)
    return run(ids, a.out, client=client, oai=oai, gpt_model=a.gpt_model, claude=a.claude, judge=a.judge,
               workers=a.workers, max_usd=a.max_usd)


if __name__ == "__main__":
    raise SystemExit(main())
