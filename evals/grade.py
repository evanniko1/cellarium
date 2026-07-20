"""Eval runner: deliberate on each case, grade the Hypothesis against the literature rubric.

Grading is two-layer:
  1. Deterministic structural checks (evals/cases.py minimum-bar shape) — no LLM, cannot be gamed.
  2. An independent LLM judge (a different, strong model that SEES the answer key) scoring every minimum and
     stringent criterion pass/fail with a rationale. The Council never sees any of this.

A case passes the MINIMUM bar iff the deterministic floor holds AND the judge passes every minimum criterion;
it passes the STRINGENT bar iff it passes the minimum bar AND every stringent criterion. "Refine until the most
stringent evals pass" = drive the stringent column to green.

Run from the repo root:
    python evals/grade.py                 # all cases
    python evals/grade.py 1.1 3.1 4.2     # a subset
    python evals/grade.py --rounds 4 --quota 3 --council-model claude-sonnet-5 --grader-model claude-opus-4-8
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cases as cases_mod  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from cellarium import council, instrument  # noqa: E402

_DIRECTION = ("increase", "decrease", "higher", "lower", "greater", "less", "rise", "rises", "fall", "falls",
              "up", "down", "positive", "negative", "bimodal", "more", "fewer", ">", "<", "exceed", "above",
              "below", "linear", "proportional")


def deterministic(h) -> dict:
    """Structural minimum-bar checks that need no LLM."""
    channels = set(instrument.channel_names())
    obs = [od.observable for od in h.operational_defs if od.observable]
    fals = h.falsifier
    on_dial = any(o in channels for o in obs) or (fals and fals.channel in channels)
    designs_ok = any(instrument.check_design(d)["usable"] for d in h.candidate_designs)
    eff = (h.predicted_effect or "").lower()
    checks = {
        "M1_named_observable": bool(obs),
        "M1_observable_on_dial_label": bool(on_dial),
        "M2_direction_stated": any(k in eff for k in _DIRECTION),
        "M2_baseline_named": bool(fals and fals.reference),
        "M3_falsifier": bool(fals and fals.refuting_result),
        "M4_valid_design": designs_ok,
        "has_two_rivals": len(h.rivals) >= 2,
        "converged": bool(h.converged),
    }
    # the minimum-bar floor is about the ARTIFACT (M1-M4 + a real falsifier); convergence is reported but
    # graded separately — a clean converged result is required only for the stringent bar.
    checks["_floor_pass"] = all(v for k, v in checks.items()
                                if k not in ("has_two_rivals", "converged"))
    return checks


_GRADE_TOOL = {
    "name": "grade",
    "description": "Grade the hypothesis against each rubric criterion.",
    "input_schema": {"type": "object", "properties": {
        "min_criteria": {"type": "array", "items": {"type": "object", "properties": {
            "criterion": {"type": "string"}, "passed": {"type": "boolean"}, "rationale": {"type": "string"}},
            "required": ["criterion", "passed", "rationale"]}},
        "stringent_criteria": {"type": "array", "items": {"type": "object", "properties": {
            "criterion": {"type": "string"}, "passed": {"type": "boolean"}, "rationale": {"type": "string"}},
            "required": ["criterion", "passed", "rationale"]}},
        "comment": {"type": "string"},
    }, "required": ["min_criteria", "stringent_criteria"]},
}

_GRADER_SYS = (
    "You are a rigorous peer reviewer grading whether an auto-generated hypothesis meets a rubric derived from "
    "the seminal literature. You SEE the canonical answer and the expected observables/rivals; the generator did "
    "NOT. Grade each listed criterion strictly true/false with a one-line rationale. A criterion passes only if "
    "the hypothesis genuinely satisfies it — do not give credit for vague gestures. Reward operationalization "
    "onto the whole-cell E. coli simulation's real observables; a readout the base model cannot execute (flagged "
    "in scope_note) is acceptable only if the hypothesis maps the construct to an in-model proxy. Emit via the "
    "grade tool, echoing each criterion string verbatim."
)


def llm_grade(case: dict, h, client, grader_model: str) -> dict:
    payload = {
        "question": case["question"], "canonical_answer": case["canonical"],
        "expected_observables": case["expected_observables"], "expected_rivals": case["expected_rivals"],
        "scope_note": case.get("scope_note", ""),
        "minimum_criteria": case["min_criteria"], "stringent_criteria": case["stringent_criteria"],
        "generated_hypothesis": h.model_dump(by_alias=True, mode="json"),
        "generated_brief": h.brief(),
    }
    resp = client.messages.create(
        model=grader_model, max_tokens=2048, system=_GRADER_SYS, tools=[_GRADE_TOOL],
        tool_choice={"type": "tool", "name": "grade"},
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    return {"min_criteria": [], "stringent_criteria": []}


_ASK_POLICY = ("Operationalize onto the single most directly measurable in-model observable; if forced to choose "
               "an axis, prefer the named molecular quantity, else growth_rate. Keep the other readings as rival "
               "hypotheses.")


def run(case_ids, rounds, quota, council_model, grader_model, out_path):
    load_dotenv(str(Path(__file__).resolve().parents[1] / ".env"))
    import anthropic
    client = anthropic.Anthropic()
    models = {"proposer": council_model, "skeptic": council_model, "judge": council_model}

    selected = cases_mod.by_id(case_ids)
    results = []
    for case in selected:
        print(f"\n=== {case['id']}  {case['question']}")
        try:
            h = council.deliberate(case["question"], max_rounds=rounds, quota=quota,
                                   ask_user=lambda q: _ASK_POLICY, client=client, models=models, verbose=True)
        except Exception as exc:  # a live failure shouldn't abort the whole sweep
            print(f"  !! deliberate failed: {type(exc).__name__}: {exc}")
            results.append({"id": case["id"], "error": f"{type(exc).__name__}: {exc}"})
            continue

        det = deterministic(h)
        g = llm_grade(case, h, client, grader_model)
        min_c = g.get("min_criteria", [])
        str_c = g.get("stringent_criteria", [])
        min_judge = bool(min_c) and all(x.get("passed") for x in min_c)
        str_judge = bool(str_c) and all(x.get("passed") for x in str_c)
        min_bar = det["_floor_pass"] and min_judge
        # the stringent bar additionally requires the Council to have CLEANLY converged (no residual ambiguities)
        stringent_bar = min_bar and str_judge and bool(h.converged)

        results.append({
            "id": case["id"], "question": case["question"], "converged": h.converged,
            "deterministic": det, "min_bar_pass": min_bar, "stringent_bar_pass": stringent_bar,
            "min_criteria": min_c, "stringent_criteria": str_c, "comment": g.get("comment", ""),
            "hypothesis": h.model_dump(by_alias=True, mode="json"),
        })
        floor = "ok" if det["_floor_pass"] else "FAIL"
        print(f"  floor={floor}  min_bar={'PASS' if min_bar else 'fail'}  "
              f"stringent={'PASS' if stringent_bar else 'fail'}")
        for x in str_c:
            if not x.get("passed"):
                print(f"    stringent miss: {x.get('criterion','')[:70]} — {x.get('rationale','')[:90]}")

    ok = [r for r in results if "error" not in r]
    n_min = sum(r["min_bar_pass"] for r in ok)
    n_str = sum(r["stringent_bar_pass"] for r in ok)
    summary = {"n_cases": len(results), "n_min_bar": n_min, "n_stringent_bar": n_str,
               "council_model": council_model, "grader_model": grader_model,
               "rounds": rounds, "quota": quota, "results": results}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n===== SUMMARY  min-bar {n_min}/{len(ok)}   stringent-bar {n_str}/{len(ok)}   -> {out_path}")
    for r in ok:
        print(f"  {r['id']}: min={'Y' if r['min_bar_pass'] else 'n'} "
              f"stringent={'Y' if r['stringent_bar_pass'] else 'n'}  {r['question'][:54]}")
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ids", nargs="*", help="case ids to run (default all)")
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--quota", type=int, default=3)
    p.add_argument("--council-model", default=os.environ.get("CELLARIUM_MODEL") or "claude-sonnet-5")
    p.add_argument("--grader-model", default="claude-opus-4-8")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "last_run.json"))
    a = p.parse_args()
    run(a.ids, a.rounds, a.quota, a.council_model, a.grader_model, a.out)


if __name__ == "__main__":
    main()
