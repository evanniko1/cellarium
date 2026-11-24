"""S2-2 measured: the integrity audit (`cellarium.integrity`) on the recorded Cellwright answers, and on the same
answers with two runs' labels swapped.

The answers are the 60 tool-using sessions I.8 was computed from (`evals/results/attribution_swap.json` names them),
read from data/sessions.db read-only. The swap is I.8's: the first two run labels the answer and the tool output
share, exchanged in the answer, so the pooled check sees the same labels and numbers before and after.

    python evals/answer_integrity.py            # writes evals/results/answer_integrity.json (aggregates only)
    python evals/answer_integrity.py --show     # also prints every finding on a recorded answer, to read by hand

A finding on a recorded answer is not a misattribution until it has been read: a short number can match another
run's field by coincidence. `--show` prints each one with its sentence so it can be adjudicated; the artefact keeps
counts and the adjudication, never answer text.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))

from cellarium import integrity as I  # noqa: E402

DB = REPO / "data" / "sessions.db"
I8 = REPO / "evals" / "results" / "attribution_swap.json"
OUT = REPO / "evals" / "results" / "answer_integrity.json"


def load(db: Path = DB) -> list[dict]:
    """Final answer, every tool result and the number of tool calls per session. READ-ONLY."""
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT sid, messages FROM sessions").fetchall()
    finally:
        con.close()
    out = []
    for sid, msgs in rows:
        m = json.loads(msgs or "[]")
        blocks = [(x.get("role"), b) for x in m if isinstance(x.get("content"), list)
                  for b in x["content"] if isinstance(b, dict)]
        tools = [str(b.get("content")) for role, b in blocks if b.get("type") == "tool_result"]
        texts = [b.get("text", "") for role, b in blocks if role == "assistant" and b.get("type") == "text"]
        calls = sum(1 for role, b in blocks if role == "assistant" and b.get("type") == "tool_use")
        if texts:
            out.append({"sid": sid, "answer": texts[-1], "tool_texts": tools, "tool_calls": calls})
    return out


def _swap_pair(s: dict) -> tuple[str, str] | None:
    """I.8's choice of the two labels to exchange (evals/attribution_swap.py, `measure`)."""
    blob = " ".join(s["tool_texts"])
    found = {lab for lab in I.LABEL.findall(s["answer"]) if lab in blob}
    labs = sorted(lab for lab in found if not any(lab != other and lab in other for other in found))
    return (labs[0], labs[1]) if len(labs) >= 2 and I.claims(s["answer"]) else None


def _swap(answer: str, a: str, b: str) -> str:
    return answer.replace(a, "\x00").replace(b, a).replace("\x00", b)


# Every finding on the recorded answers, read one by one on 2026-11-24 (`--show` prints them). A test pins the counts
# these were read against, so a change to the rules that moves them fails until they are read again.
ADJUDICATED = {
    "date": "2026-11-24",
    "other_run_only_among_all_claims": {
        "n": 13, "the_answers_error": 0,
        "the_pairings_error": {"table_column": 7, "sentence_comparing_two_runs": 3,
                               "graded_knockdown_read_as_full_knockout": 2, "two_digit_number_matched_by_rounding": 1}},
    "unread_citations": {
        "n": 2, "real_paper_cited_without_being_read": 2, "not_a_real_paper": 0,
        "how": "both PMIDs looked up on PubMed: each is the paper the answer describes"},
    "parser_errors_fixed_before_counting": "3 DOIs read with a trailing ')**' and 1 DOI the tool returned with its "
                                           "slash JSON-escaped were reported unread; both parses are fixed and tested",
}


def _planted(planted: dict, before: str, after: str) -> None:
    if before != "own_run":
        return
    planted["own_run_before"] += 1
    planted[{"other_run_only": "found_in_the_other_run_after", "own_run": "still_own_run_after"}.get(
        after, "neither_after")] += 1


def measure(sessions: list[dict], show: bool = False) -> dict:
    status = {k: 0 for k in ("own_run", "shared", "other_run_only", "unrouted")}
    cites = {"answers_citing": 0, "cited": 0, "unread": 0}
    gated = {"gated_replies": 0, "gated_with_tool_calls": 0}
    named = {"actionable_claims": 0, "named_misattributions": 0}
    zero = {"swapped_claims": 0, "own_run_before": 0, "found_in_the_other_run_after": 0, "neither_after": 0,
            "still_own_run_after": 0}
    planted = {"exposed_answers": 0, "all_claims": dict(zero), "actionable_claims": dict(zero)}
    flagged = []
    for s in sessions:
        r = I.audit(s["answer"], s["tool_texts"], tool_calls=s["tool_calls"])
        for k, v in r["numbers"]["counts"].items():
            status[k] += v
        named["actionable_claims"] += len(I.actionable_claims(s["answer"]))
        named["named_misattributions"] += len(r["numbers"]["misattributed"])
        cites["answers_citing"] += bool(r["citations"]["cited"])
        cites["cited"] += len(r["citations"]["cited"])
        cites["unread"] += len(r["citations"]["unread"])
        gated["gated_replies"] += r["gate"]["gated"]
        gated["gated_with_tool_calls"] += r["gate"]["respected"] is False
        if r["verdict"] == "faults" or r["numbers"]["counts"]["other_run_only"]:
            flagged.append((s, r))
        pair = _swap_pair(s)
        if pair is None:
            continue
        planted["exposed_answers"] += 1
        a, b = pair
        leaves = I.field_leaves(s["tool_texts"])
        for key, cl in (("all_claims", I.claims(s["answer"])), ("actionable_claims", I.actionable_claims(s["answer"]))):
            for lab, n in cl:
                if lab not in (a, b):
                    continue
                planted[key]["swapped_claims"] += 1
                _planted(planted[key], I.classify(lab, n, leaves)[0], I.classify(b if lab == a else a, n, leaves)[0])
    if show:
        for s, r in flagged:
            print(f"\n=== {s['sid']}")
            for c in r["numbers"]["claims"]:
                if c["status"] == "other_run_only":
                    sent = next((x for x in I.SENTENCE.split(s["answer"]) if c["label"] in x and c["number"] in x),
                                "")
                    print(f"  NUMBER {c['number']} -> {c['label']} found only in {c['found_in']}"
                          f"{' [NAMED]' if c in r['numbers']['misattributed'] else ''}\n    {sent[:400]}")
            for c in r["citations"]["unread"]:
                print(f"  CITATION {c}")
            if r["gate"]["respected"] is False:
                print("  GATED REPLY WITH TOOL CALLS")
    return {"answers": len(sessions), "claim_status": status, "named": named, "citations": cites, "gate": gated,
            "planted_swap": planted, "adjudicated": ADJUDICATED}


def main() -> int:
    if not DB.is_file():
        print(f"{DB.relative_to(REPO)} is not on this machine; nothing follows about answers stored elsewhere.",
              file=sys.stderr)
        return 2
    want = set(json.loads(I8.read_text(encoding="utf-8"))["session_ids"])
    sessions = [s for s in load() if s["sid"] in want]
    if len(sessions) != len(want):
        print(f"this store holds {len(sessions)} of I.8's {len(want)} sessions; not measuring.", file=sys.stderr)
        return 2
    from cellarium import provenance
    r = measure(sessions, show="--show" in sys.argv[1:])
    r["source"] = "the 60 sessions of evals/results/attribution_swap.json, from data/sessions.db, read-only"
    r["computed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    r["environment"] = provenance.code_environment()
    if "--show" not in sys.argv[1:]:
        OUT.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in r.items() if k != "environment"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
