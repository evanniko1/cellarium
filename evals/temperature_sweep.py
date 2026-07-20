"""DD-MTH-3: Council temperature sweep — choose COUNCIL_TEMPERATURE empirically, not by assertion.

The Council pins a WARM temperature (council.COUNCIL_TEMPERATURE, default 1.0) because exploration across
operationalizations is its FUNCTION — asymmetric to Cellwright's faithful 0.0 by purpose (DD-MTH-2). That default
is a placeholder. This sweep runs the canonical questions across a TEMPERATURE GRID with REPLICATES per
(question, temperature), on a NON-REASONING model (the ONLY regime where temperature is a lever — opus / extended
thinking force temperature=1 and reject an explicit value), and reports, per temperature:
  * QUALITY — the ablation's 6-criterion operationalization rubric (Claude + optional cross-family GPT judge);
  * CONVERGENCE rate;
  * cross-replicate DIVERSITY — does warmer actually explore more DISTINCT operationalizations, or just add noise?
Pin COUNCIL_TEMPERATURE at the operating point where quality holds while diversity is still useful.

Reuses evals/ablate.py's per-cell grading (DRY). Output: evals/results/temperature_sweep.json.

Run: python evals/temperature_sweep.py --temps 0.0,0.3,0.7,1.0 --reps 4 --model claude-sonnet-5
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

# --- pure metric functions (no heavy deps at module top, so the metric is unit-testable in CI) ----------------


def _signature(h: dict) -> str:
    """A structural operationalization SIGNATURE for one hypothesis: falsifier channel + the sorted set of bound
    observables + the predicted-effect direction. Two hypotheses with the same signature operationalized the
    question the same way; the fraction of DISTINCT signatures across replicates is the exploration measure."""
    fal = h.get("falsifier") or {}
    obs = sorted({(d.get("observable") or "") for d in (h.get("operational_defs") or []) if isinstance(d, dict)})
    return json.dumps([fal.get("channel"), obs, (h.get("predicted_effect") or "")[:40]], sort_keys=True)


def diversity(hyps: list) -> dict:
    """Cross-replicate diversity for the hypotheses at one (case, temperature): the fraction of DISTINCT structural
    operationalizations, and the mean pairwise Jaccard distance of the claim tokens (a continuous companion)."""
    hyps = [h for h in hyps if isinstance(h, dict)]
    n = len(hyps)
    if n < 2:
        return {"n": n, "distinct_operationalizations": None, "claim_pairwise_distance": None}
    distinct = len({_signature(h) for h in hyps}) / n
    toks = [set(re.findall(r"[a-z0-9]+", (h.get("claim") or "").lower())) for h in hyps]
    dists = [1.0 - (len(a & b) / len(a | b) if (a | b) else 1.0)
             for i, a in enumerate(toks) for b in toks[i + 1:]]
    return {"n": n, "distinct_operationalizations": round(distinct, 3),
            "claim_pairwise_distance": (round(statistics.fmean(dists), 3) if dists else None)}


def summarize(results: list, temps: list) -> dict:
    """Per-temperature roll-up: mean operationalization quality, convergence rate, and cross-replicate diversity
    (distinct operationalizations + claim diversity), diversity computed per case then averaged. This is the curve
    that chooses the operating point — quality should hold while diversity stays useful."""
    out: dict = {}
    for temp in temps:
        recs = [r for r in results if r.get("temperature") == temp and not r.get("error")]
        if not recs:
            continue
        q = [r["claude"]["score"] for r in recs if r.get("claude")]
        per_case: dict = {}
        for r in recs:
            per_case.setdefault(r["id"], []).append(r.get("hypothesis") or {})
        divs = [diversity(hs) for hs in per_case.values()]
        distinct = [d["distinct_operationalizations"] for d in divs if d["distinct_operationalizations"] is not None]
        cdist = [d["claim_pairwise_distance"] for d in divs if d["claim_pairwise_distance"] is not None]
        out[str(temp)] = {
            "n_runs": len(recs),
            "mean_quality_6": round(statistics.fmean(q), 2) if q else None,
            "convergence_rate": round(sum(1 for r in recs if r.get("converged")) / len(recs), 2),
            "mean_distinct_operationalizations": round(statistics.fmean(distinct), 3) if distinct else None,
            "mean_claim_diversity": round(statistics.fmean(cdist), 3) if cdist else None,
        }
    return out


# --- live run (heavy deps imported lazily so the pure metric above stays importable without them) -------------


def _cell(case, rep, temp, model, client, oai, gpt_model, claude_grader) -> dict:
    """One (case, replicate, temperature) run at the FULL Council + both graders — reuses ablate.py's grading."""
    import ablate

    from cellarium import council
    rec = {"id": case["id"], "rep": rep, "temperature": temp, "model": model}
    try:
        models = {"proposer": model, "skeptic": model, "judge": model}
        h = council.deliberate(case["question"], temperature=temp, client=client, models=models, verbose=False)
        rec.update(converged=h.converged, rounds_used=h.rounds_used,
                   substantive_objections=h.substantive_objections, feasible=ablate._feasible(h))
        gc = ablate.grade_claude(case, h, client, claude_grader)
        rec["claude"] = {"score": ablate._score(gc), **gc}
        if oai is not None:
            gg = ablate.grade_gpt(case, h, oai, gpt_model)
            rec["gpt"] = {"score": ablate._score(gg), **gg}
        rec["hypothesis"] = h.model_dump(by_alias=True, mode="json")
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def run(case_ids, temps, reps, model, out_path, gpt_model, claude_grader, workers=6):
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import anthropic
    import cases as cases_mod
    from dotenv import load_dotenv
    load_dotenv(str(Path(__file__).resolve().parents[1] / ".env"))

    if "opus" in (model or "").lower():
        print("WARNING: a reasoning model (opus) FORCES temperature=1 and rejects an explicit value — the sweep is "
              "a no-op there. Use a non-reasoning model (e.g. claude-sonnet-5).", flush=True)

    client = anthropic.Anthropic(max_retries=6)
    oai = None
    if os.environ.get("OPENAI_API_KEY"):
        import openai
        oai = openai.OpenAI(max_retries=6)

    cases = cases_mod.by_id(case_ids)
    tasks = [(c, rep, temp) for temp in temps for c in cases for rep in range(reps)]
    results, lock = [], threading.Lock()
    meta = {"temps": temps, "reps": reps, "model": model, "claude_grader": claude_grader, "gpt_grader": gpt_model}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_cell, c, rep, temp, model, client, oai, gpt_model, claude_grader): (c, rep, temp)
                for (c, rep, temp) in tasks}
        done = 0
        for fut in as_completed(futs):
            rec = fut.result()
            with lock:
                results.append(rec)
                Path(out_path).write_text(
                    json.dumps({**meta, "results": results, "summary": summarize(results, temps)}, indent=2),
                    encoding="utf-8")
            done += 1
            cq = rec.get("claude", {}).get("score", "-")
            print(f"[{done}/{len(tasks)}] {rec['id']:5s} T={rec['temperature']:<4} rep{rec['rep']}: "
                  f"quality={cq}/6 conv={rec.get('converged')} {rec.get('error', '')}", flush=True)

    print("\n=== per-temperature summary (quality / convergence / diversity) ===", flush=True)
    for t, s in summarize(results, temps).items():
        print(f"  T={t:<4} quality={s['mean_quality_6']}/6  conv={s['convergence_rate']}  "
              f"distinct_ops={s['mean_distinct_operationalizations']}  claim_div={s['mean_claim_diversity']}",
              flush=True)
    print(f"\nwrote {len(results)} records -> {out_path}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ids", nargs="*")
    p.add_argument("--temps", default="0.0,0.3,0.7,1.0", help="comma-separated temperature grid")
    p.add_argument("--reps", type=int, default=4, help="replicates per (case, temperature) — need >1 for diversity")
    p.add_argument("--model", default="claude-sonnet-5", help="a NON-REASONING model (temperature is a no-op on opus)")
    p.add_argument("--gpt-model", default="gpt-4o")
    p.add_argument("--claude-grader", default="claude-opus-4-8")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "temperature_sweep.json"))
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    run(a.ids, [float(t) for t in a.temps.split(",")], a.reps, a.model, a.out, a.gpt_model, a.claude_grader, a.workers)


if __name__ == "__main__":
    main()
