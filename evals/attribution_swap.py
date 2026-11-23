"""Validation-layer item 9, step 1: would anything notice a right number credited to the wrong run?

Cellarium enforces grounding in the agent's prompt ("you cannot state a number you did not read from a tool") and
by construction of its tools; it has NO post-hoc check of the numbers in an answer. The campaign branch's
assistant has one (`check_faithfulness`), and it is POOLED: a number passes if it appears in SOME tool output.
When an answer compares two runs that both appear in the tool output -- wild type against a knockout, the case
where well4cell's rc1 twins showed identical numbers under two names -- crediting a number to the wrong run
passes a pooled check by construction. This measures how often that exposure exists in real answers, and
whether a ROUTED check (the number must sit in a tool-output record that names the run it is credited to) would
see the swap, before anyone builds the full verifier the spec describes.

    python evals/attribution_swap.py     # reads data/sessions.db read-only; writes aggregates only

Method, and what it cannot do. A run is named by its design label (`gene_knockout/KO:argS`,
`condition/minus_phosphate`, `KO:argS`, ...). A CLAIM is a number in the answer paired with the nearest label
before it in the same sentence. A record is any JSON object in a tool result that names a label. Numbers match
under the answer's own rounding (12.3 matches 12.2961; 12% matches 0.1204). The swap exchanges two labels that
both appear in the session's tool outputs, so the pooled check sees the same labels and the same numbers before
and after. LIMITS: the label pattern misses runs named in prose ("the argS knockout"), so exposure is a lower
bound; the nearest-label rule misattributes some claims, and a number the agent COMPUTED (a ratio of two read
values) is in no record, so the routed check's own false-alarm rate on unswapped answers is reported beside its
detection rate rather than hidden behind it.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "sessions.db"
OUT = REPO / "evals" / "results" / "attribution_swap.json"

LABEL = re.compile(r"\b(?:gene_knockout|condition|wildtype|ppgpp_conc|nutrient_shift)/[A-Za-z0-9_:\-.]*[A-Za-z0-9_]"
                   r"|\bKO:[A-Za-z0-9_]+")
NUM = re.compile(r"(?<![A-Za-z0-9_:/.])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z0-9_])")
SENTENCE = re.compile(r"(?<=[.!?;\n])\s+")


def _variants(tok: str) -> tuple[float, int, bool]:
    pct = tok.endswith("%")
    s = tok.rstrip("%").lstrip("+")
    dec = len(s.split(".")[1]) if "." in s else 0
    return float(s), dec, pct


def number_in(tok: str, text: str) -> bool:
    """Does `text` contain a number that rounds to `tok` at the answer's own precision (or its fraction, for %)?"""
    x, dec, pct = _variants(tok)
    for m in NUM.finditer(text):
        try:
            y = float(m.group(0).rstrip("%"))
        except ValueError:
            continue
        if round(y, dec) == x or (pct and round(y * 100, dec) == x):
            return True
    return False


def claims(answer: str) -> list[tuple[str, str]]:
    """(label, number) pairs: each number with the nearest label before it in the same sentence."""
    out = []
    for sent in SENTENCE.split(answer):
        last = None
        for m in re.finditer(f"{LABEL.pattern}|{NUM.pattern}", sent):
            tok = m.group(0)
            if LABEL.fullmatch(tok):
                last = tok
            elif last is not None and len(tok.rstrip("%").lstrip("+-").replace(".", "")) >= 2:
                out.append((last, tok))          # single digits are list markers and counts, not readings
    return out


def records(tool_texts: list[str]) -> list[str]:
    """Every JSON object in the tool results that names a design label, as its own text."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            s = json.dumps(x)
            if LABEL.search(s):
                out.append(s)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for t in tool_texts:
        try:
            walk(json.loads(t))
        except (ValueError, TypeError):
            if LABEL.search(t or ""):
                out.append(t)
    return out


def pooled_ok(answer: str, tool_texts: list[str]) -> bool:
    """The pooled rule: every label and every number in the answer appears SOMEWHERE in the tool outputs."""
    blob = " ".join(tool_texts)
    return (all(lab in blob for lab in LABEL.findall(answer))
            and all(number_in(n, blob) for _, n in claims(answer)))


def routed_ok(label: str, num: str, recs: list[str]) -> bool:
    """The routed rule: the number sits in a record that names the run it is credited to."""
    return any(label in r and number_in(num, r) for r in recs)


def swap(answer: str, a: str, b: str) -> str:
    return answer.replace(a, "\x00").replace(b, a).replace("\x00", b)


def measure(sessions: list[dict]) -> dict:
    """sessions: [{"answer": str, "tool_texts": [str]}]. Aggregates only."""
    exposed, pooled_detect, n_claims = 0, 0, 0
    routed = {"original_supported": 0, "original_claims": 0, "swapped_claims": 0,
              "detected": 0, "supported_before_and_after": 0}
    for s in sessions:
        blob = " ".join(s["tool_texts"])
        found = {lab for lab in LABEL.findall(s["answer"]) if lab in blob}
        # A label inside another ("KO:argS" in "gene_knockout/KO:argS") cannot be swapped on its own without
        # inventing a third label, which a pooled check would then flag for the wrong reason.
        labs = sorted(lab for lab in found if not any(lab != other and lab in other for other in found))
        cl = claims(s["answer"])
        n_claims += len(cl)
        recs = records(s["tool_texts"])
        routed["original_claims"] += len(cl)
        routed["original_supported"] += sum(routed_ok(lab, n, recs) for lab, n in cl)
        if len(labs) < 2 or not cl:
            continue
        exposed += 1
        a, b = labs[0], labs[1]
        swapped = swap(s["answer"], a, b)
        if pooled_ok(s["answer"], s["tool_texts"]) and not pooled_ok(swapped, s["tool_texts"]):
            pooled_detect += 1
        before = {(lab, n): routed_ok(lab, n, recs) for lab, n in cl if lab in (a, b)}
        for (lab, n), ok in before.items():
            moved = b if lab == a else a
            routed["swapped_claims"] += 1
            after = routed_ok(moved, n, recs)
            if ok and not after:
                routed["detected"] += 1
            elif ok and after:
                routed["supported_before_and_after"] += 1
    return {"answers": len(sessions), "claims": n_claims,
            "exposed_answers": exposed,
            "pooled_check_detected_swaps": pooled_detect,
            "routed": routed}


def load_sessions(db: Path = DB) -> list[dict]:
    """Final answer + every tool result per tool-using session, READ-ONLY. Nothing is written back."""
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
        if tools and texts:
            out.append({"sid": sid, "answer": texts[-1], "tool_texts": tools})
    return out


def main() -> int:
    if not DB.is_file():
        print(f"{DB.relative_to(REPO)} is not on this machine; nothing follows about answers stored elsewhere.",
              file=sys.stderr)
        return 2
    sessions = load_sessions()
    r = measure(sessions)
    # The session ids (opaque, no content) say WHICH answers this was computed from, so a later recomputation can
    # use exactly those and a different store is recognised as different rather than as a disagreement.
    r["session_ids"] = sorted(s["sid"] for s in sessions)
    r["source"] = "data/sessions.db sessions (final assistant answer + all tool results), read-only, this machine"
    r["computed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    OUT.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(r, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
