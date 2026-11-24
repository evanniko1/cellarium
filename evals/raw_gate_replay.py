"""P-2 measured: every tool call Cellwright made in the recorded sessions, replayed through the raw-tool gate as it
was before P-2 (commit ed7d036) and as it is now. What the change costs (calls newly refused: utility lost, in
PACE's terms) and what it buys (calls newly refused that read a quantity the model does not represent; calls no
longer refused that read nothing simulated; notes that now travel with a number).

    python evals/raw_gate_replay.py           # writes evals/results/raw_gate_replay.json (counts only)
    python evals/raw_gate_replay.py --show    # also prints each call whose decision changed, to read by hand

Read-only on data/sessions.db. The "before" gate is loaded from git at that commit, so this needs the repository's
history; without it the script says so and measures nothing.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import mcp  # noqa: E402

DB = REPO / "data" / "sessions.db"
OUT = REPO / "evals" / "results" / "raw_gate_replay.json"
BEFORE_COMMIT = "ed7d036"

# Every changed decision, read one by one on 2026-11-24 (`--show`). A test pins the counts these were read against.
ADJUDICATED = {
    "date": "2026-11-24",
    "newly_refused": {
        "n": 10,
        "rrna_operon_count_design_read_for_growth_ribosomes_or_ppgpp": {
            "n": 8, "verdict": "false refusal by the registry's own evidence",
            "why": "the record is about WHICH operon was deleted (the variant reassigns every rRNA row to the mean over "
                   "all seven, erasing identity but keeping the total), so a count-level reading is represented; "
                   "A-1's positive control reproduces it. The rule that refuses it maps the whole design family to "
                   "the operon-specific record and already refused the same reads through `design` and `target`; "
                   "P-2 made it consistent. Narrowing it is decision Y11."},
        "growth_law_fit_including_condition_no_glucose": {
            "n": 2, "verdict": "correct refusal, too coarse before this change",
            "why": "the no-carbon record: growth continues with no carbon uptake, so the point means nothing; the "
                   "refusal now names the design so the fit can run without it"}},
    "no_longer_refused": {"n": 1, "comparable_designs": "lists designs; reads no simulated quantity"},
}


def _before_gate():
    """The gate at BEFORE_COMMIT, imported as a sibling module of the package so its relative imports resolve."""
    src = subprocess.run(["git", "-C", str(REPO), "show", f"{BEFORE_COMMIT}:src/cellarium/mcp.py"],
                         capture_output=True, text=True, encoding="utf-8")
    if src.returncode != 0:
        return None
    tmp = Path(tempfile.mkdtemp()) / "_mcp_before.py"
    tmp.write_text(src.stdout, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("cellarium._mcp_before", tmp)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "cellarium"
    spec.loader.exec_module(mod)
    return mod


def calls(db: Path = DB, sessions: set | None = None) -> tuple[list[tuple[str, dict]], list[str]]:
    """Every tool call in the recorded sessions, as (name, arguments), and the sessions they came from. READ-ONLY.
    `sessions` restricts to a stored set: the store is live, and a new session would move every count."""
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT sid, messages FROM sessions").fetchall()
    finally:
        con.close()
    out, used = [], []
    for sid, msgs in rows:
        if sessions is not None and sid not in sessions:
            continue
        found = []
        for m in json.loads(msgs or "[]"):
            if m.get("role") == "assistant" and isinstance(m.get("content"), list):
                found += [(b.get("name"), dict(b.get("input") or {})) for b in m["content"]
                          if isinstance(b, dict) and b.get("type") == "tool_use"]
        if found:
            out += found
            used.append(sid)
    return out, sorted(used)


def measure(recorded: list[tuple[str, dict]], before, show: bool = False) -> dict:
    tally = collections.Counter()
    changed = []
    for name, args in recorded:
        b_ref = before.capability_precheck(name, args) is not None
        a_ref = mcp.capability_precheck(name, args) is not None
        b_note = not b_ref and before.capability_note(name, args) is not None
        a_note = not a_ref and mcp.capability_note(name, args) is not None
        tally["calls"] += 1
        tally["refused_before"] += b_ref
        tally["refused_after"] += a_ref
        tally["noted_before"] += b_note
        tally["noted_after"] += a_note
        if (b_ref, b_note) != (a_ref, a_note):
            kind = ("newly_refused" if a_ref and not b_ref else "no_longer_refused" if b_ref and not a_ref
                    else "newly_noted" if a_note and not b_note else "no_longer_noted")
            tally[kind] += 1
            changed.append((kind, name, args))
    reads = sum(1 for n, _ in recorded if n in mcp.READS_SIMULATED_QUANTITIES)
    by_capability = collections.Counter(
        k for n, a in recorded if (r := mcp.capability_precheck(n, a)) for k in r["capabilities"])
    if show:
        for kind, name, args in changed:
            print(f"{kind:18s} {name:24s} {json.dumps(args)[:200]}")
    return {"calls": tally["calls"], "calls_to_tools_that_read": reads,
            "refused": {"before": tally["refused_before"], "after": tally["refused_after"]},
            "noted": {"before": tally["noted_before"], "after": tally["noted_after"]},
            "changed": {k: tally[k] for k in ("newly_refused", "no_longer_refused", "newly_noted",
                                              "no_longer_noted")},
            "changed_by_tool": dict(collections.Counter(f"{k}:{n}" for k, n, _ in changed)),
            "refused_after_by_capability": dict(by_capability)}


def main() -> int:
    if not DB.is_file():
        print(f"{DB.relative_to(REPO)} is not on this machine; nothing follows about calls recorded elsewhere.",
              file=sys.stderr)
        return 2
    before = _before_gate()
    if before is None:
        print(f"commit {BEFORE_COMMIT} is not in this repository's history; the before-gate cannot be loaded.",
              file=sys.stderr)
        return 2
    from cellarium import provenance
    recorded, used = calls()
    r = measure(recorded, before, show="--show" in sys.argv[1:])
    r.update({"adjudicated": ADJUDICATED, "session_ids": used, "before_commit": BEFORE_COMMIT,
              "source": "every tool_use block in data/sessions.db, read-only. These are Cellwright's own calls, "
                        "made after the question-level gate admitted each question; they never passed the raw-tool "
                        "gate, and are replayed here as a direct client's calls would be",
              "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "environment": provenance.code_environment()})
    if "--show" not in sys.argv[1:]:
        OUT.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in r.items() if k != "environment"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
