"""Role/gate ablation + baselines for the Socratic Council (paper Workstream C1/C2).

For each (case, config, replicate) we run council.deliberate with the config's knobs and grade the resulting
Hypothesis on a DE-CONFOUNDED operationalization-quality rubric — six criteria judgeable from the hypothesis
text ALONE (no literature answer key), so the metric measures *derivation quality*, not answer recall. Each
hypothesis is graded by an independent Claude judge AND a cross-family GPT judge (inter-rater robustness).

Configs (the role/gate ablation): full = proposer+skeptic+judge; no_skeptic = proposer+judge; proposer_only =
single-shot; generic_judge = proposer+skeptic+plain-quality-judge (no falsifiability rubric). Sampling
temperature is pinned (names the variance source). Output: evals/results/ablation.json (or --out).

Run: python evals/ablate.py --reps 3 --temperature 0.7
     python evals/ablate.py 1.1 4.1 4.2 --configs full,no_skeptic,proposer_only --reps 5
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

CONFIGS = {
    "full":          dict(),                                        # proposer + skeptic + judge (the system)
    "no_skeptic":    dict(use_skeptic=False),                       # proposer + judge (no elenctic critic)
    "proposer_only": dict(use_skeptic=False, use_judge=False),      # single-shot generation (the baseline)
    "generic_judge": dict(judge_mode="generic"),                   # proposer + skeptic + plain quality judge
}

# Six operationalization-quality criteria — judgeable from the hypothesis text alone (NO answer key).
Q = {
    "q1_falsifiable": "Names a concrete result that would REFUTE H1 — a risky prohibition that could actually fail.",
    "q2_operationalized": "Every construct is bound to a named measurable observable, AND the falsifier names a "
                          "statistical test and a numeric threshold.",
    "q3_discriminating": "At least one rival hypothesis is named with a distinguishing experiment/design that "
                         "would separate it from H1.",
    "q4_quantitative": "predicted_effect states a DIRECTION and a NUMERIC magnitude (a CV, fold-change, slope, "
                       "or threshold).",
    "q5_specified": "Independent variable (perturbation), dependent variable (observable), and predicted "
                    "direction are all present.",
    "q6_consistent": "No internal contradiction between H1, the falsifier, and the rival predictions.",
}

_SYS = (
    "You are grading the METHODOLOGICAL QUALITY of a scientific hypothesis produced for a whole-cell E. coli "
    "simulation. Judge ONLY the form: is it falsifiable, operationalized, discriminating, quantitative, "
    "well-specified, and internally consistent? Do NOT use any outside knowledge of what the biologically "
    "correct answer is — a well-formed hypothesis that happens to be wrong should still score well on form. "
    "Return one boolean per criterion.")


def _feasible(h) -> bool:
    return any(instrument.check_design(d)["usable"] for d in h.candidate_designs)


def _payload(case, h) -> dict:
    return {"question": case["question"], "criteria": Q,
            "hypothesis": h.model_dump(by_alias=True, mode="json"), "brief": h.brief()}


def grade_claude(case, h, client, model="claude-opus-4-8") -> dict:
    tool = {"name": "grade", "description": "Grade each operationalization-quality criterion.",
            "input_schema": {"type": "object",
                             "properties": {**{k: {"type": "boolean"} for k in Q}, "rationale": {"type": "string"}},
                             "required": list(Q)}}
    resp = client.messages.create(model=model, max_tokens=1024, system=_SYS, tools=[tool],
                                  tool_choice={"type": "tool", "name": "grade"}, temperature=0,
                                  messages=[{"role": "user", "content": json.dumps(_payload(case, h))}])
    for b in resp.content:
        if getattr(b, "type", None) == "tool_use":
            return dict(b.input)
    return {}


def grade_gpt(case, h, oai, model="gpt-4o") -> dict:
    prompt = (_SYS + "\n\nReturn a JSON object with exactly these boolean keys: " + ", ".join(Q)
              + ", plus a 'rationale' string.\n\n" + json.dumps(_payload(case, h)))
    r = oai.chat.completions.create(model=model, temperature=0, response_format={"type": "json_object"},
                                    messages=[{"role": "user", "content": prompt}])
    try:
        return json.loads(r.choices[0].message.content)
    except Exception:
        return {}


def _score(g: dict) -> int:
    return sum(1 for k in Q if bool(g.get(k)))


def run(case_ids, configs, reps, temperature, out_path, gpt_model, claude_grader):
    load_dotenv(str(Path(__file__).resolve().parents[1] / ".env"))
    import anthropic
    client = anthropic.Anthropic()
    oai = None
    if os.environ.get("OPENAI_API_KEY"):
        import openai
        oai = openai.OpenAI()

    selected = cases_mod.by_id(case_ids)
    results = []
    for case in selected:
        for cfg in configs:
            for rep in range(reps):
                rec = {"id": case["id"], "config": cfg, "rep": rep, "temperature": temperature}
                try:
                    h = council.deliberate(case["question"], temperature=temperature, client=client,
                                           verbose=False, **CONFIGS[cfg])
                    rec.update(converged=h.converged, rounds_used=h.rounds_used,
                               substantive_objections=h.substantive_objections, feasible=_feasible(h))
                    gc = grade_claude(case, h, client, claude_grader)
                    rec["claude"] = {"score": _score(gc), **gc}
                    if oai is not None:
                        gg = grade_gpt(case, h, oai, gpt_model)
                        rec["gpt"] = {"score": _score(gg), **gg}
                    rec["hypothesis"] = h.model_dump(by_alias=True, mode="json")
                    print(f"  {case['id']:4s} {cfg:13s} rep{rep}: claude_q={rec['claude']['score']}/6"
                          f" gpt_q={rec.get('gpt',{}).get('score','-')}/6 conv={rec['converged']}"
                          f" rounds={rec['rounds_used']} feas={rec['feasible']}", flush=True)
                except Exception as exc:
                    rec["error"] = f"{type(exc).__name__}: {exc}"
                    print(f"  {case['id']} {cfg} rep{rep}: ERROR {rec['error']}", flush=True)
                results.append(rec)
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                Path(out_path).write_text(json.dumps({"configs": configs, "reps": reps,
                                                      "temperature": temperature, "claude_grader": claude_grader,
                                                      "gpt_grader": gpt_model, "results": results}, indent=2),
                                          encoding="utf-8")
    print(f"\nwrote {len(results)} records -> {out_path}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ids", nargs="*")
    p.add_argument("--configs", default="full,no_skeptic,proposer_only,generic_judge")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--gpt-model", default="gpt-4o")
    p.add_argument("--claude-grader", default="claude-opus-4-8")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "ablation.json"))
    a = p.parse_args()
    run(a.ids, a.configs.split(","), a.reps, a.temperature, a.out, a.gpt_model, a.claude_grader)


if __name__ == "__main__":
    main()
