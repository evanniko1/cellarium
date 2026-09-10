"""AG-2b — run the targeted tool probe and report SELECTION, separately from success.

    python evals/tool_probe.py                 # all cases
    python evals/tool_probe.py --ids P-B1 P-B2 # a subset
    python evals/tool_probe.py --dry-run       # print the plan and the cost shape, call nothing

WHAT IT MEASURES, and why it is not the A/B sweep. `evals/run_ab.py` grades ANSWER QUALITY across two arms
and costs ~$8 a pass; none of that is in question here. This asks one thing: given a question squarely in a
tool's domain, does the agent reach for that tool? So there is no Council arm, no grader, no rubric — just
the conversation and the record of what it called, with `max_turns` held low because a targeted question
that needs twenty turns has already answered the question being asked.

THE TWO OUTCOMES ARE NEVER MERGED. A tool that is SELECTED and then fails because the machine has no local
raw simOut has passed this probe -- the agent chose correctly and the data was absent, which is a corpus
fact, not a tool fact. AG-2 conflated these by counting errors instead of reading them, and concluded the
agent was mis-selecting when 26 of its 35 "selection errors" were `no local raw simOut`. Every row below
carries `selected`, `errored` and the error text, and the summary reports them apart.

WHAT COUNTS AS A HIT. `expect` hit means the aimed-at tool was called. `also_ok` hit means the agent chose a
defensible alternative reading of the same question -- reported as a near-miss, never silently scored as a
pass, because "the agent went somewhere reasonable instead" is exactly the evidence that two tools overlap
and one of them may be redundant.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tool_probe_cases as cases_mod  # noqa: E402

from cellarium import agent, observability, tools  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _ensure_key() -> None:
    """Resolve the provider key from every supported source, or abort saying so.

    MEASURED THE HARD WAY 2026-09-10: the first run of this probe reported "27 tools still never selected
    by either sweep" -- a dramatic-looking finding produced by 27 consecutive auth failures and $0.00 of
    spend. A sweep that cannot reach the model must say so, not publish a verdict. Same resolution order as
    run_ab.py: an explicit export or .env wins over the OS keychain.
    """
    from cellarium import credentials, llm

    var = credentials.env_var(llm.PROVIDER)
    if not os.environ.get(var):
        try:
            credentials.load_into_env()
        except Exception:
            pass
    if not os.environ.get(var):
        raise SystemExit(
            f"ERROR: no {var} for provider {llm.PROVIDER!r}. Set it in the app Settings tab (OS keychain), "
            f"in {ROOT / '.env'}, or as an exported shell variable. Aborting rather than reporting an "
            "empty sweep as a result.")

OUT = Path(__file__).resolve().parent / "results" / "ag2b_tool_probe.json"


def _log(msg: str) -> None:
    print(msg, flush=True)


HINT = ("  (Before answering from general knowledge, check what purpose-built tools are available for "
        "this and use one if it fits.)")


def run_case(case: dict, model: str, max_turns: int, hint: bool = False) -> dict:
    """One probe question. Records every tool call in order, with its turn index and whether it errored.

    `hint` appends a neutral nudge to LOOK for a tool, without naming one. It exists to split a single
    "not selected" into two very different diagnoses: a tool the agent could not FIND (discoverability, i.e.
    a description problem) versus one it did not think to REACH FOR (a judgement problem, and for something
    like a power analysis that is a correctness bug, not an inventory one). Naming the tool would collapse
    the distinction into a test of instruction-following, which is not in doubt.
    """
    events: list[dict] = []

    def on_tool(name, inp, out):
        errored = isinstance(out, dict) and "error" in out
        events.append({
            "order": len(events),
            "name": name,
            "errored": errored,
            # The error TEXT is what separates "wrong tool" from "right tool, absent data". Keep it.
            "error": (str(out.get("error"))[:220] if errored else None),
            "args": {k: str(v)[:60] for k, v in (inp or {}).items()},
        })

    t0 = time.time()
    with observability.meter() as m:
        try:
            q = case["question"] + (HINT if hint else "")
            answer = agent.converse([{"role": "user", "content": q}],
                                    model=model, max_turns=max_turns, on_tool=on_tool)
            crash = None
        except Exception as e:                                        # noqa: BLE001
            answer, crash = None, f"{type(e).__name__}: {str(e)[:200]}"

    called = [e["name"] for e in events]
    expect, also = case["expect"], case.get("also_ok", [])
    hit = expect in called
    near = (not hit) and any(a in called for a in also)
    # Selected-but-errored is a PASS for this probe. Recorded explicitly so the summary cannot blur it.
    expect_calls = [e for e in events if e["name"] == expect]
    return {
        "id": case["id"], "family": case["family"], "expect": expect, "hinted": hint,
        "question": case["question"],
        "selected": hit,
        "selected_but_errored": bool(expect_calls) and all(e["errored"] for e in expect_calls),
        "expect_error": (expect_calls[0]["error"] if expect_calls and expect_calls[0]["errored"] else None),
        "near_miss": near,
        "near_miss_tools": [a for a in also if a in called] if near else [],
        "n_tool_calls": len(events),
        "tools_called": called,
        "first_call_index": (called.index(expect) if hit else None),
        "events": events,
        "crash": crash,
        "answer_chars": len(answer or ""),
        "llm": m.summary(),
        "elapsed_s": round(time.time() - t0, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="AG-2b targeted tool-selection probe")
    ap.add_argument("--ids", nargs="*", default=None)
    # None => agent.MODEL, the same default run_ab.py uses; naming it here would pin a second place.
    ap.add_argument("--model", default=os.environ.get("CELLARIUM_MODEL") or agent.MODEL)
    ap.add_argument("--max-turns", type=int, default=8,
                    help="deliberately low: these are targeted questions, not open investigations")
    ap.add_argument("--hint", action="store_true",
                    help="append a neutral nudge to look for a tool (never names one) -- splits 'could not find it' from 'did not think to'")
    ap.add_argument("--out-suffix", default="", help="write results to ag2b_tool_probe<suffix>.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    selected = cases_mod.by_id(a.ids)
    if not a.dry_run:
        _ensure_key()
    registry = [t["name"] for t in tools.TOOLS]
    _log(f"AG-2b tool probe: {len(selected)} case(s), model={a.model}, max_turns={a.max_turns}")
    _log(f"registry: {len(registry)} tools; aimed at {len(cases_mod.expected_tools())} of them\n")
    if a.dry_run:
        for c in selected:
            _log(f"  {c['id']:6} {c['family']:9} -> {c['expect']:24} {c['question'][:70]}")
        missing = sorted(cases_mod.expected_tools() - set(registry))
        _log(f"\naimed-at tools NOT in the registry (would be un-hittable): {missing or 'none'}")
        return

    rows, t0 = [], time.time()
    for i, c in enumerate(selected, 1):
        _log(f"[{i}/{len(selected)}] {c['id']:6} -> {c['expect']}")
        r = run_case(c, a.model, a.max_turns, hint=a.hint)
        rows.append(r)
        mark = ("HIT " if r["selected"] else ("near" if r["near_miss"] else "MISS"))
        extra = ""
        if r["selected_but_errored"]:
            extra = f"  (selected, then errored: {str(r['expect_error'])[:70]})"
        elif r["near_miss"]:
            extra = f"  (chose {', '.join(r['near_miss_tools'])})"
        cost = (r["llm"] or {}).get("cost_usd")
        _log(f"    {mark}  calls={r['n_tool_calls']:2}  {r['elapsed_s']:5.1f}s  "
             f"${cost if cost is not None else '?'}{extra}")
        if r["crash"]:
            _log(f"    CRASH {r['crash']}")

    crashed = [r for r in rows if r["crash"]]
    if rows and len(crashed) == len(rows):
        _log(f"ABORTING THE SUMMARY: all {len(rows)} cases crashed before reaching a tool "
             f"({crashed[0]['crash']}). Nothing was measured, so no tool "
             "can be called unselected. Fix the cause and re-run; no result file is written.")
        raise SystemExit(2)

    # ---- summary ---------------------------------------------------------------------------------
    hits = [r for r in rows if r["selected"]]
    nears = [r for r in rows if r["near_miss"]]
    misses = [r for r in rows if not r["selected"] and not r["near_miss"]]
    sel_err = [r for r in rows if r["selected_but_errored"]]
    every_call: Counter = Counter()
    for r in rows:
        every_call.update(r["tools_called"])

    _log("\n" + "=" * 96)
    _log(f"SELECTED (the aimed-at tool was called): {len(hits)}/{len(rows)}")
    _log(f"  of which selected then errored on data/args: {len(sel_err)}  "
         f"<- these PASS: the agent chose right, the input was absent")
    _log(f"NEAR MISS (a defensible alternative instead):  {len(nears)}/{len(rows)}")
    _log(f"NOT SELECTED at all:                          {len(misses)}/{len(rows)}")
    for fam in ("reachable", "fba", "proposal"):
        f = [r for r in rows if r["family"] == fam]
        if f:
            _log(f"    {fam:9} {sum(1 for r in f if r['selected'])}/{len(f)} selected")
    if misses:
        _log("\nnot selected — the honest removal candidates, or a description problem:")
        for r in misses:
            _log(f"  {r['id']:6} {r['expect']:24} agent called: {r['tools_called'] or '(no tools at all)'}")
    if nears:
        _log("\nnear misses — evidence that two tools overlap:")
        for r in nears:
            _log(f"  {r['id']:6} {r['expect']:24} -> chose {', '.join(r['near_miss_tools'])}")

    newly = sorted(set(every_call) - set(json.loads(
        (OUT.parent / "ag2_tool_selection.json").read_text(encoding="utf-8"))["selected"]))
    _log(f"\ntools this probe reached that the first sweep never did: {len(newly)}")
    _log("  " + (", ".join(newly) if newly else "(none)"))
    still = sorted(set(t["name"] for t in tools.TOOLS) - set(every_call) - set(json.loads(
        (OUT.parent / "ag2_tool_selection.json").read_text(encoding="utf-8"))["selected"]))
    _log(f"\nSTILL never selected by either sweep: {len(still)}")
    _log("  " + (", ".join(still) if still else "(none)"))

    spend = sum((r["llm"] or {}).get("cost_usd") or 0 for r in rows)
    _log(f"\nspend (est., list price): ${spend:.4f}   elapsed {time.time() - t0:.0f}s")

    out = OUT.with_name(OUT.stem + a.out_suffix + OUT.suffix) if a.out_suffix else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "hinted": a.hint,
        "model": a.model, "max_turns": a.max_turns, "registry_size": len(registry),
        "n_cases": len(rows),
        "selected": len(hits), "selected_but_errored": len(sel_err),
        "near_miss": len(nears), "not_selected": len(misses),
        "not_selected_tools": [r["expect"] for r in misses],
        "near_miss_tools": {r["expect"]: r["near_miss_tools"] for r in nears},
        "tools_called_here": dict(every_call.most_common()),
        "newly_reached": newly, "still_never_selected": still,
        "spend_usd": round(spend, 4),
        "rows": rows,
    }, indent=1) + "\n", encoding="utf-8")
    _log(f"wrote {out}")


if __name__ == "__main__":
    main()
