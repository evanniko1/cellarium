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
partial list undercounts. `MAX_TOKENS` is 4096. CONFIRMED 2026-11-24 by re-auditing just those 58 records:

    python evals/audit.py --only-claude-zeros evals/results/audited.json --auditors claude         --out evals/results/audited_zeros_reaudit.json

All 58 replies were readable, each listing 8 to 12 defects, none zero. 43 of them ran longer than the old
1,024-token limit (851 to 1,430 output tokens), which fits the cut-off explanation; the old auditor kept no stop
reason, so for any one record it is inferred, not observed.

VARIANTS. A record may carry other hypotheses to score beside the one it returned: `variants.all_rounds` (the
Council's round-cap result when its early stop was logged, validation item 5(d)) or the drafts best-of-N did not
report first. Each distinct one is audited too, under `variants.<name>`; one identical to the returned hypothesis
or to another variant is not audited twice, and says which it equals (`same_as`).

Progress goes to <out>.partial.json and the artefact is written once, complete; five failed calls in a row stop
the run with exit code 3 (checklist T.3), and `--max-usd` stops it before the metered spend passes the amount
(exit 4, evals/costs.py). `--auditors claude` leaves out the GPT auditor (the confirmation above needs only
Claude's). `--dry-run` prints what the selected records would cost and calls nothing. The artefact records the
auditors, the reply limit, the source and the software that produced it (checklist T.1).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import api_keys  # noqa: E402
import cases as cases_mod  # noqa: E402
import costs  # noqa: E402

from cellarium import observability, outage, provenance  # noqa: E402

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


def _payload(rec, hypothesis=None) -> dict:
    return {"question": _QUESTION_CTX.get(rec["id"], ""),
            "hypothesis": rec.get("hypothesis", {}) if hypothesis is None else hypothesis}


def audit_claude(rec, client, model="claude-opus-4-8", hypothesis=None) -> dict:
    tool = {"name": "audit", "description": "List substantive methodological defects.",
            "input_schema": {"type": "object", "properties": {
                "defects": {"type": "array", "items": {"type": "object", "properties": {
                    "type": {"type": "string", "enum": DEFECT_TYPES}, "issue": {"type": "string"}},
                    "required": ["type", "issue"]}}}, "required": ["defects"]}}
    t0 = time.monotonic()
    r = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=_SYS, tools=[tool],
                               tool_choice={"type": "tool", "name": "audit"},
                               messages=[{"role": "user", "content": json.dumps(_payload(rec, hypothesis))}])
    observability.emit(observability.usage_record("auditor", model, r, (time.monotonic() - t0) * 1000))
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


def audit_gpt(rec, oai, model="gpt-4o", hypothesis=None) -> dict:
    prompt = (_SYS + "\n\nReturn JSON: {\"defects\": [{\"type\": <one of " + str(DEFECT_TYPES)
              + ">, \"issue\": <string>}]}.\n\n" + json.dumps(_payload(rec, hypothesis)))
    t0 = time.monotonic()
    r = oai.chat.completions.create(model=model, temperature=0, response_format={"type": "json_object"},
                                    messages=[{"role": "user", "content": prompt}])
    observability.emit(costs.openai_record("auditor_gpt", model, r, (time.monotonic() - t0) * 1000))
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


def _scores(rec, hypothesis, client, oai, gpt_model, claude_auditor) -> dict:
    """Both auditors' counts for one hypothesis; an exception becomes `error`, never a count."""
    out: dict = {}
    try:
        ca = audit_claude(rec, client, claude_auditor, hypothesis)
        out["claude_defects"] = len(ca["defects"])
        out["claude_defect_list"] = ca["defects"]
        out["claude_stop_reason"] = ca.get("stop_reason")
        out["claude_output_tokens"] = ca.get("output_tokens")
        if oai is not None:
            ga = audit_gpt(rec, oai, gpt_model, hypothesis)
            out["gpt_defects"] = len(ga["defects"])
            out["gpt_defect_list"] = ga["defects"]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _key(h) -> str:
    return json.dumps(h, sort_keys=True)


def _one(rec, client, oai, gpt_model, claude_auditor):
    if "error" in rec or not rec.get("hypothesis"):
        return None
    out = {"id": rec["id"], "config": rec["config"], "rep": rec["rep"]}
    with observability.meter(this_thread=True) as m:
        out.update(_scores(rec, None, client, oai, gpt_model, claude_auditor))
        seen = {_key(rec["hypothesis"]): "hypothesis"}
        for name, h in (rec.get("variants") or {}).items():
            if not h:
                continue
            if _key(h) in seen:
                out.setdefault("variants", {})[name] = {"same_as": seen[_key(h)]}
                continue
            seen[_key(h)] = name
            out.setdefault("variants", {})[name] = _scores(rec, h, client, oai, gpt_model, claude_auditor)
    out["llm"] = m.summary()
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


def n_audits(recs: list) -> int:
    """How many hypotheses auditing `recs` scores: each record's own plus its distinct variants."""
    n = 0
    for r in recs:
        seen = {_key(r["hypothesis"])}
        n += 1
        for h in (r.get("variants") or {}).values():
            if h and _key(h) not in seen:
                seen.add(_key(h))
                n += 1
    return n


def run(recs: list, out_path: str, *, client, oai, gpt_model: str, claude_auditor: str, workers: int = 6,
        source: str = "", stop_after: int = outage.DEFAULT_LIMIT, max_usd: float | None = None) -> int:
    """Audit `recs` and write the artefact once, complete. Returns the exit code: 0, 3 if an outage stopped it,
    4 if the spend cap did."""
    meta = {"source": source, "claude_auditor": claude_auditor, "gpt_auditor": gpt_model if oai else None,
            "max_tokens": MAX_TOKENS, "max_usd": max_usd, "environment": provenance.code_environment()}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.stem + ".partial.json")
    brk = outage.Breaker(stop_after)
    per_record = costs.estimate_audit(1, gpt=oai is not None)["per_record"]["high"]
    widest = max((1 + len(r.get("variants") or {}) for r in recs), default=1)
    cap = costs.SpendCap(max_usd, reserve_usd=workers * widest * per_record if max_usd else 0.0)
    audited, lock = [], threading.Lock()

    def _guarded(rec):
        if brk.tripped or cap.tripped:                    # checked where a call starts, so none starts after a trip
            return None
        o = _one(rec, client, oai, gpt_model, claude_auditor)
        if o is not None:
            brk.observe("error" not in o, (o.get("error") or "").split(":")[0])
            cap.add(*costs.record_cost(o.get("llm")))
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
    stopper = brk if brk.tripped else cap if cap.tripped else None
    if stopper is not None:
        partial.write_text(json.dumps({**meta, "stopped_early": stopper.report(len(recs)), "results": audited},
                                      indent=2), encoding="utf-8")
        why = brk.message(len(recs)) if stopper is brk else stopper.report(len(recs))["why"]
        print(f"\nSTOPPED: {why}\npartial results, not a result: {partial}", flush=True)
        return brk.exit_code() if stopper is brk else costs.EXIT_SPEND_CAP
    out.write_text(json.dumps({**meta, "spent_usd": round(cap.spent, 4), "results": audited}, indent=2),
                   encoding="utf-8")
    partial.unlink(missing_ok=True)
    n_err = sum(1 for o in audited if "error" in o)
    print(f"wrote {len(audited)} -> {out} ({n_err} unreadable or failed, none counted as zero; "
          f"metered ${cap.spent:.2f})", flush=True)
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
    p.add_argument("--auditors", choices=("both", "claude"), default="both",
                   help="'claude' leaves out the GPT auditor")
    p.add_argument("--max-usd", type=float, help="stop before the metered spend passes this (exit 4)")
    p.add_argument("--dry-run", action="store_true", help="print what the selected records cost; call nothing")
    a = p.parse_args()
    zeros = (json.loads(Path(a.only_claude_zeros).read_text(encoding="utf-8"))["results"]
             if a.only_claude_zeros else None)
    recs = select(json.loads(Path(a.src).read_text(encoding="utf-8"))["results"], only_claude_zeros=zeros)
    gpt = a.auditors == "both"          # the plan asked for, never the keys that happen to be present
    est = costs.estimate_audit(n_audits(recs), gpt=gpt, claude_auditor=a.claude_auditor, gpt_model=a.gpt_model)
    print(f"{len(recs)} records, {est['records']} hypotheses to audit "
          f"({'Claude and GPT' if gpt else 'Claude only'}): estimate USD low / central / high "
          f"{est['total_usd']['low']:.2f} / {est['total_usd']['central']:.2f} / {est['total_usd']['high']:.2f}")
    if a.dry_run:
        print("(dry run -- nothing called)")
        return 0
    api_keys.require(api_keys.ANTHROPIC, *([api_keys.OPENAI] if gpt else []),
                     hint="To audit with Claude alone, pass --auditors claude.")
    from cellarium import llm
    client = llm.client(max_retries=6)
    oai = None
    if gpt:
        import openai
        oai = openai.OpenAI(max_retries=6)
    return run(recs, a.out, client=client, oai=oai, gpt_model=a.gpt_model, claude_auditor=a.claude_auditor,
               workers=a.workers, source=_shown(a.src), stop_after=a.stop_after_failures, max_usd=a.max_usd)


if __name__ == "__main__":
    raise SystemExit(main())
