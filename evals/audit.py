"""Adversarial residual-defect audit of ablation hypotheses (paper C1, the sensitive mechanism metric).

The binary operationalization-quality rubric saturates (a single strong proposer already writes falsifiable,
discriminating hypotheses). The dialectic's value is subtler: it REMOVES residual methodological defects — a
falsifier that cannot actually fail, a rival whose 'distinguishing' experiment does not discriminate, an
internal contradiction, an instrument-exceeding/infeasible design, an unstated critical auxiliary. This audit
counts those defects with a fresh adversarial auditor that is BLIND to which config produced the hypothesis, so
we can test whether full-Council < proposer_only in residual-defect count.

Reads evals/results/ablation.json (the saved final hypotheses), grades each with a Claude auditor AND a
cross-family GPT auditor, writes evals/results/audited.json. Concurrent. Run: python evals/audit.py.

AN UNREADABLE REPLY IS AN ERROR, NEVER ZERO DEFECTS (fixed 2026-11-24). Zero is this endpoint's best score, and
both auditors used to return an empty list for a reply they could not read: no tool block, a missing `defects`
key, or (GPT) unparseable JSON. The stored Claude column has the shape that leaves: 58 of 120 audits are zero and
every other one is 7 to 10, never 1 to 6, while the GPT auditor never returned zero. The readable lists stop at
about 2,700 characters, near what the old 1,024-token reply limit holds, so the likeliest cause is a list cut off
at the limit. A reply cut off at its limit is now an error too, even when part of the list parsed, because a
partial list undercounts. `MAX_TOKENS` is 4096. To confirm the stored zeros, re-audit just those 58 records:

    python evals/audit.py --only-claude-zeros evals/results/audited.json --out evals/results/audited_zeros_reaudit.json

Progress goes to <out>.partial.json and the artefact is written once, complete; five failed calls in a row stop
the run with exit code 3 (checklist T.3). The artefact records the auditors, the reply limit, the source and the
software that produced it (checklist T.1).
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

from cellarium import outage, provenance  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# Room for a long list. The stored run used 1,024 tokens, and no readable Claude audit in it lists more than ten
# defects of about 270 characters each; a longer list was cut off.
MAX_TOKENS = 4096

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


class UnreadableAudit(ValueError):
    """An auditor's reply that cannot be counted. Raised, never mapped to zero defects, which is the best score."""


def _payload(rec) -> dict:
    return {"question": _QUESTION_CTX.get(rec["id"], ""), "hypothesis": rec.get("hypothesis", {})}


def audit_claude(rec, client, model="claude-opus-4-8") -> dict:
    tool = {"name": "audit", "description": "List substantive methodological defects.",
            "input_schema": {"type": "object", "properties": {
                "defects": {"type": "array", "items": {"type": "object", "properties": {
                    "type": {"type": "string", "enum": DEFECT_TYPES}, "issue": {"type": "string"}},
                    "required": ["type", "issue"]}}}, "required": ["defects"]}}
    r = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=_SYS, tools=[tool],
                               tool_choice={"type": "tool", "name": "audit"},
                               messages=[{"role": "user", "content": json.dumps(_payload(rec))}])
    stop = getattr(r, "stop_reason", None)
    if stop == "max_tokens":
        raise UnreadableAudit(f"the Claude audit was cut off at max_tokens={MAX_TOKENS}; a partial list undercounts")
    block = next((b for b in r.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        raise UnreadableAudit(f"no audit tool block in the Claude reply (stop_reason={stop})")
    data = dict(block.input or {})
    if not isinstance(data.get("defects"), list):
        raise UnreadableAudit(f"the Claude reply has no 'defects' list (keys: {sorted(data)})")
    usage = getattr(r, "usage", None)
    return {"defects": data["defects"], "stop_reason": stop,
            "output_tokens": getattr(usage, "output_tokens", None)}


def audit_gpt(rec, oai, model="gpt-4o") -> dict:
    prompt = (_SYS + "\n\nReturn JSON: {\"defects\": [{\"type\": <one of " + str(DEFECT_TYPES)
              + ">, \"issue\": <string>}]}.\n\n" + json.dumps(_payload(rec)))
    r = oai.chat.completions.create(model=model, temperature=0, response_format={"type": "json_object"},
                                    messages=[{"role": "user", "content": prompt}])
    choice = r.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise UnreadableAudit("the GPT audit was cut off at its length limit; a partial list undercounts")
    try:
        data = json.loads(choice.message.content)
    except (TypeError, ValueError) as exc:
        raise UnreadableAudit(f"the GPT auditor's reply is not JSON ({exc}): "
                              f"{str(choice.message.content)[:120]!r}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("defects"), list):
        raise UnreadableAudit("the GPT reply has no 'defects' list")
    return data


def _one(rec, client, oai, gpt_model, claude_auditor):
    if "error" in rec or not rec.get("hypothesis"):
        return None
    out = {"id": rec["id"], "config": rec["config"], "rep": rec["rep"]}
    try:
        ca = audit_claude(rec, client, claude_auditor)
        out["claude_defects"] = len(ca["defects"])
        out["claude_defect_list"] = ca["defects"]
        out["claude_stop_reason"] = ca.get("stop_reason")
        out["claude_output_tokens"] = ca.get("output_tokens")
        if oai is not None:
            ga = audit_gpt(rec, oai, gpt_model)
            out["gpt_defects"] = len(ga["defects"])
            out["gpt_defect_list"] = ga["defects"]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def select(recs: list, *, only_claude_zeros: list | None = None) -> list:
    """The ablation records to audit: every graded record with a hypothesis, or with `only_claude_zeros` (a stored
    audit's results) only those that audit counted as zero Claude defects, so a confirmation re-audits nothing else."""
    keep = [r for r in recs if "error" not in r and r.get("hypothesis")]
    if only_claude_zeros is None:
        return keep
    zeroed = {(a["id"], a["config"], a["rep"]) for a in only_claude_zeros if a.get("claude_defects") == 0}
    return [r for r in keep if (r["id"], r["config"], r["rep"]) in zeroed]


def _shown(path) -> str:
    """A path as an artefact may record it: relative to the repo, never a local absolute path."""
    p = Path(path).resolve()
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError:
        return p.name


def run(recs: list, out_path: str, *, client, oai, gpt_model: str, claude_auditor: str, workers: int = 6,
        source: str = "", stop_after: int = outage.DEFAULT_LIMIT) -> int:
    """Audit `recs` and write the artefact once, complete. Returns the exit code: 0, or 3 if an outage stopped it."""
    meta = {"source": source, "claude_auditor": claude_auditor, "gpt_auditor": gpt_model if oai else None,
            "max_tokens": MAX_TOKENS, "environment": provenance.code_environment()}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.stem + ".partial.json")
    brk = outage.Breaker(stop_after)
    audited, lock = [], threading.Lock()

    def _guarded(rec):
        if brk.tripped:                                   # checked where a call starts, so none starts after a trip
            return None
        o = _one(rec, client, oai, gpt_model, claude_auditor)
        if o is not None:
            brk.observe("error" not in o, (o.get("error") or "").split(":")[0])
        return o

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_guarded, r) for r in recs]
        for i, f in enumerate(as_completed(futs), 1):
            o = f.result()
            if o is None:
                continue
            with lock:
                audited.append(o)
                partial.write_text(json.dumps({**meta, "results": audited}, indent=2), encoding="utf-8")
            print(f"[{i}/{len(futs)}] {o['id']:4s} {o['config']:13s} rep{o['rep']}: "
                  f"claude_defects={o.get('claude_defects')} gpt_defects={o.get('gpt_defects')} "
                  f"{o.get('error', '')}", flush=True)
    if brk.tripped:
        partial.write_text(json.dumps({**meta, "stopped_early": brk.report(len(recs)), "results": audited},
                                      indent=2), encoding="utf-8")
        print(f"\n{brk.message(len(recs))}\npartial results, not a result: {partial}", flush=True)
        return brk.exit_code()
    out.write_text(json.dumps({**meta, "results": audited}, indent=2), encoding="utf-8")
    partial.unlink(missing_ok=True)
    n_err = sum(1 for o in audited if "error" in o)
    print(f"wrote {len(audited)} -> {out} ({n_err} unreadable or failed, none counted as zero)", flush=True)
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default=str(Path(__file__).resolve().parent / "results" / "ablation.json"))
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "audited.json"))
    p.add_argument("--gpt-model", default="gpt-4o")
    p.add_argument("--claude-auditor", default="claude-opus-4-8")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--only-claude-zeros", metavar="AUDITED_JSON",
                   help="re-audit only the records this stored audit counted as zero Claude defects")
    p.add_argument("--stop-after-failures", type=int, default=outage.DEFAULT_LIMIT)
    a = p.parse_args()
    load_dotenv(str(REPO / ".env"))
    from cellarium import llm
    client = llm.client(max_retries=6)
    oai = None
    if os.environ.get("OPENAI_API_KEY"):
        import openai
        oai = openai.OpenAI(max_retries=6)
    zeros = (json.loads(Path(a.only_claude_zeros).read_text(encoding="utf-8"))["results"]
             if a.only_claude_zeros else None)
    recs = select(json.loads(Path(a.src).read_text(encoding="utf-8"))["results"], only_claude_zeros=zeros)
    return run(recs, a.out, client=client, oai=oai, gpt_model=a.gpt_model, claude_auditor=a.claude_auditor,
               workers=a.workers, source=_shown(a.src), stop_after=a.stop_after_failures)


if __name__ == "__main__":
    raise SystemExit(main())
