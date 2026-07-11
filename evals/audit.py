"""Adversarial residual-defect audit of ablation hypotheses (paper C1, the sensitive mechanism metric).

The binary operationalization-quality rubric saturates (a single strong proposer already writes falsifiable,
discriminating hypotheses). The dialectic's value is subtler: it REMOVES residual methodological defects — a
falsifier that cannot actually fail, a rival whose 'distinguishing' experiment does not discriminate, an
internal contradiction, an instrument-exceeding/infeasible design, an unstated critical auxiliary. This audit
counts those defects with a fresh adversarial auditor that is BLIND to which config produced the hypothesis, so
we can test whether full-Council < proposer_only in residual-defect count.

Reads evals/results/ablation.json (the saved final hypotheses), grades each with a Claude auditor AND a
cross-family GPT auditor, writes evals/results/audited.json. Concurrent. Run: python evals/audit.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cases as cases_mod  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

DEFECT_TYPES = ["falsifier_cannot_fail", "rival_not_actually_discriminating", "internal_contradiction",
                "infeasible_or_instrument_exceeding_design", "unstated_critical_auxiliary",
                "vague_or_unmeasurable_construct", "answers_narrower_question_than_asked"]

_SYS = (
    "You are a rigorous, adversarial methods reviewer auditing a scientific hypothesis written for a whole-cell "
    "E. coli simulation. Find every SUBSTANTIVE methodological DEFECT that a careful reviewer would flag — only "
    "real, rubric-breaking flaws, not stylistic nits. Consider these defect types: "
    + "; ".join(DEFECT_TYPES) + ". For each genuine defect, give its type and a one-line issue. You do NOT know "
    "the biologically correct answer and must not penalise a well-formed hypothesis for being possibly wrong — "
    "audit the METHOD (falsifiability, discrimination, feasibility, consistency, scope), not the biology.")

_QUESTION_CTX = {c["id"]: c["question"] for c in cases_mod.CASES}


def _payload(rec) -> dict:
    return {"question": _QUESTION_CTX.get(rec["id"], ""), "hypothesis": rec.get("hypothesis", {})}


def audit_claude(rec, client, model="claude-opus-4-8") -> dict:
    tool = {"name": "audit", "description": "List substantive methodological defects.",
            "input_schema": {"type": "object", "properties": {
                "defects": {"type": "array", "items": {"type": "object", "properties": {
                    "type": {"type": "string", "enum": DEFECT_TYPES}, "issue": {"type": "string"}},
                    "required": ["type", "issue"]}}}, "required": ["defects"]}}
    r = client.messages.create(model=model, max_tokens=1024, system=_SYS, tools=[tool],
                               tool_choice={"type": "tool", "name": "audit"},
                               messages=[{"role": "user", "content": json.dumps(_payload(rec))}])
    for b in r.content:
        if getattr(b, "type", None) == "tool_use":
            return dict(b.input)
    return {"defects": []}


def audit_gpt(rec, oai, model="gpt-4o") -> dict:
    prompt = (_SYS + "\n\nReturn JSON: {\"defects\": [{\"type\": <one of " + str(DEFECT_TYPES)
              + ">, \"issue\": <string>}]}.\n\n" + json.dumps(_payload(rec)))
    r = oai.chat.completions.create(model=model, temperature=0, response_format={"type": "json_object"},
                                    messages=[{"role": "user", "content": prompt}])
    try:
        return json.loads(r.choices[0].message.content)
    except Exception:
        return {"defects": []}


def _one(rec, client, oai, gpt_model, claude_auditor):
    if "error" in rec or not rec.get("hypothesis"):
        return None
    out = {"id": rec["id"], "config": rec["config"], "rep": rec["rep"]}
    try:
        ca = audit_claude(rec, client, claude_auditor)
        out["claude_defects"] = len(ca.get("defects", []))
        out["claude_defect_list"] = ca.get("defects", [])
        if oai is not None:
            ga = audit_gpt(rec, oai, gpt_model)
            out["gpt_defects"] = len(ga.get("defects", []))
            out["gpt_defect_list"] = ga.get("defects", [])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default=str(Path(__file__).resolve().parent / "results" / "ablation.json"))
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "audited.json"))
    p.add_argument("--gpt-model", default="gpt-4o")
    p.add_argument("--claude-auditor", default="claude-opus-4-8")
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args()
    load_dotenv(str(Path(__file__).resolve().parents[1] / ".env"))
    import anthropic
    client = anthropic.Anthropic(max_retries=6)
    oai = None
    if os.environ.get("OPENAI_API_KEY"):
        import openai
        oai = openai.OpenAI(max_retries=6)

    recs = [r for r in json.loads(Path(a.src).read_text())["results"] if "error" not in r]
    audited, lock = [], threading.Lock()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(_one, r, client, oai, a.gpt_model, a.claude_auditor) for r in recs]
        for i, f in enumerate(as_completed(futs), 1):
            o = f.result()
            if o is None:
                continue
            with lock:
                audited.append(o)
                Path(a.out).write_text(json.dumps({"results": audited}, indent=2), encoding="utf-8")
            print(f"[{i}/{len(futs)}] {o['id']:4s} {o['config']:13s} rep{o['rep']}: "
                  f"claude_defects={o.get('claude_defects')} gpt_defects={o.get('gpt_defects')} "
                  f"{o.get('error','')}", flush=True)
    print(f"wrote {len(audited)} -> {a.out}")


if __name__ == "__main__":
    main()
