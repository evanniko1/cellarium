"""A/B scoring — does the Socratic Council add value over Cellwright-alone, measured by HARKing?

Workflow: run each of the 5 A/B questions in the UI TWICE — Arm A (ask Cellwright directly in Investigations) and
Arm B (convene the Council in Hypotheses, then "Open in Cellwright") — so all ten transcripts persist to
data/sessions.db. Then run this script.

It computes the OBJECTIVE signals it reliably can, and leaves the one subjective judgment as a clearly-marked
manual field:
  - Did each arm READ corpus data for the target before committing to a hypothesis? Arm A (sighted) does; the
    Council in Arm B is blind by construction (zero corpus reads) -> pre-registered. This is the HARKing proxy:
    a data-informed hypothesis can be fit to the answer; a blind one cannot.
  - Does the corpus already contain the target's runs at framing time? (HARKing is only *possible* if it does.)
  - MANUAL: the predicted direction each arm committed to, and whether it matches the corpus. The value is where
    Arm B's blind prediction DIVERGES from the corpus (a model surprise Arm A, having read the data, would never surface).

Run:  python scripts/ab_score.py            (or: python scripts/ab_score.py path/to/sessions.db)
"""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cellarium import tools  # noqa: E402

DB = sys.argv[1] if len(sys.argv) > 1 else "data/sessions.db"

# (keyword to match the question, observable) — the 5 A/B questions
QUESTIONS = [
    ("pfkA", "growth rate — reroute or cost?"),
    ("lpxC", "viability vs essentiality"),
    ("argS", "ppGpp up or down?"),
    ("rRNA", "operon dosage vs max growth"),
    ("ppGpp", "clamp 2x vs growth"),
]

# corpus-read tools: a hypothesis stated after these is data-informed (HARKing-prone)
READ_TOOLS = {"survey_corpus", "viability", "list_results", "read_series", "differential",
              "top_movers", "disconfirm", "read_raw_series", "variance_band", "mechanistic_scope"}
HANDOFF = "socratic council framed"


def _first_user(msgs):
    for m in msgs:
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else " ".join(b.get("text", "") for b in c if isinstance(b, dict))
    return ""


def _read_tool_calls(msgs):
    n = 0
    for m in msgs:
        c = m.get("content")
        if isinstance(c, list):
            n += sum(1 for b in c if b.get("type") == "tool_use" and b.get("name") in READ_TOOLS)
    return n


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sess = [{**dict(r), "msgs": json.loads(r["messages"] or "[]")} for r in
            con.execute("SELECT sid, title, messages FROM sessions")]
    runs = [dict(r) for r in con.execute("SELECT id, question, status FROM council_runs")]
    for s in sess:
        s["fu"] = _first_user(s["msgs"]).lower()

    print(f"A/B HARKing scorecard  ·  {DB}\n")
    for key, obs in QUESTIONS:
        k = key.lower()
        arm_a = [s for s in sess if k in s["fu"] and HANDOFF not in s["fu"]]
        arm_b_council = [r for r in runs if k in (r["question"] or "").lower()]
        arm_b_test = [s for s in sess if HANDOFF in s["fu"] and k in s["fu"]]
        corpus_has = tools.list_results(gene=key).get("n", 0)

        print("=" * 74)
        print(f"Q[{key}] — {obs}")
        print(f"  corpus already has {corpus_has} {key} run(s) at framing time  ->  HARKing {'POSSIBLE' if corpus_has else 'not possible'}")
        if arm_a:
            print(f"  Arm A  Cellwright-direct  [{arm_a[-1]['sid']}]  corpus-reads={_read_tool_calls(arm_a[-1]['msgs'])}  ->  data-informed (HARKing-prone)")
        else:
            print("  Arm A  — NOT FOUND (ask it in Investigations)")
        if arm_b_council:
            print(f"  Arm B  Council  [{arm_b_council[-1]['id']}]  blind by construction (0 corpus reads)  ->  PRE-REGISTERED"
                  + (f"  +test [{arm_b_test[-1]['sid']}]" if arm_b_test else "  (no handoff session yet)"))
        else:
            print("  Arm B  — NOT FOUND (convene it in Hypotheses)")
        print(f"  MANUAL:  predicted direction  ArmA=____  ArmB=____  |  corpus shows=____  |  ArmB diverges from corpus? ____")

    print("\n" + "-" * 74)
    print("Read: Arm A hypotheses are data-informed (it read the corpus first); Arm B's are blind/pre-registered.")
    print("The Council's value shows where Arm B's blind prediction DIVERGES from the corpus (e.g. argS: predicts")
    print("ppGpp UP per biology, corpus shows DOWN) — a model surprise Arm A, having read the data, would rationalize away.")


if __name__ == "__main__":
    main()
