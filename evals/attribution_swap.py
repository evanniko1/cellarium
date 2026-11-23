"""Validation-layer item 9, steps 1 and 2: would anything notice a right number credited to the wrong run?

Step 2 (2026-11-23) routes each number to the FIELD it came from, not the record: the record rule caught 10 of the
50 swapped claims it supported, because one comparison record names both runs; the field rule catches 29 of 30,
and supports fewer claims to begin with (64 of 140 against 100). See `field_leaves` for the rule.
`python evals/attribution_swap.py --same-sessions` re-measures exactly the recorded answers and refuses to write
if any figure it already reported would change.

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


# --- step 2: route each number to the FIELD it came from (2026-11-23) --------------------------------------
# The record-level rule above credits a number to every run its record names, so a comparison record that names
# both runs supports either attribution. On the 60 recorded answers two shapes carried most of that: role fields
# (`reference`, `target`) naming two runs, with the runs' values in fields named after the roles (`ref_mean`, or
# `reference`/`target` inside `ranked` items) beside numbers that belong to the pair (log2fc, welch_t, pct); and
# tool results cut off for the model's context, which parsed as nothing and so counted as one blob naming
# every run.

def repair_json(text):
    """Parse JSON, or JSON cut off part-way: keep every complete member up to the last comma before the cut and close
    whatever is still open. None when the text is not JSON at all."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    if not isinstance(text, str) or not text.lstrip().startswith(("{", "[")):
        return None
    stack, in_str, esc, cuts = [], False, False, []
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack:
                break
            stack.pop()
            if not stack:                # a complete top-level value; json.loads failed on what follows it
                return _loads_or_none(text[: i + 1])
        elif ch == ",":
            cuts.append((i, tuple(stack)))
    # The last cut that parses: a truncation marker can itself hold a comma or a bracket.
    for i, open_ in reversed(cuts[-200:]):
        got = _loads_or_none(text[:i] + "".join(reversed(open_)))
        if got is not None:
            return got
    return None


def _loads_or_none(s):
    try:
        return json.loads(s)
    except ValueError:
        return None


def _same_run(a: str, b: str) -> bool:
    """`KO:argS` and `gene_knockout/KO:argS` name one run; `KO:arg` and `KO:argS` do not."""
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def _role_owns(key: str, role: str) -> bool:
    """Does a number stored under `key` belong to the run named in field `role`? `reference` owns `reference`,
    `reference_mean` and `ref_mean`; `target` owns `target` and `target_mean`."""
    k, r = key.lower(), role.lower()
    head = k.split("_", 1)[0]
    return k == r or k.startswith(r + "_") or (len(head) >= 3 and r.startswith(head))


def field_leaves(tool_texts: list[str]) -> list[tuple[frozenset, str]]:
    """(owner, number text) for every number in the tool results. The owner is the run the number belongs to: the
    run its key names; else the run whose role field its key is named after; else every run the nearest naming
    object names -- one run for a single-run object, the pair for a comparison's own statistics."""
    out: list[tuple[frozenset, str]] = []

    def owner(key, roles: dict) -> frozenset:
        if key:
            named = set(LABEL.findall(str(key)))
            if len(named) == 1:
                return frozenset(named)
            hit = {lab for role, lab in roles.items() if _role_owns(str(key), role)}
            if len(hit) == 1:
                return frozenset(hit)
        return frozenset(roles.values())

    def walk(x, roles: dict, key=None):
        if isinstance(x, dict):
            own = {k: v.strip() for k, v in x.items() if isinstance(v, str) and LABEL.fullmatch(v.strip())}
            scope = own or roles                  # the nearest object that names runs owns what is inside it
            for k, v in x.items():
                if k in own:
                    continue
                named = set(LABEL.findall(str(k)))
                walk(v, {k: next(iter(named))} if len(named) == 1 else scope, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, roles, key)
        elif isinstance(x, bool) or x is None:
            return
        elif isinstance(x, (int, float)):
            out.append((owner(key, roles), repr(x)))
        elif isinstance(x, str) and NUM.search(x):
            named = set(LABEL.findall(x))
            out.append((frozenset(named) if len(named) == 1 else owner(key, roles), x))

    for t in tool_texts:
        obj = repair_json(t)
        if obj is not None:
            walk(obj, {})
        else:
            out += [(frozenset(LABEL.findall(line)), line) for line in (t or "").splitlines() if NUM.search(line)]
    return out


def field_routed_ok(label: str, num: str, leaves) -> bool:
    """The field rule: the number sits in a field that belongs to the run it is credited to, and to no other."""
    return any(len(o) == 1 and _same_run(label, next(iter(o))) and number_in(num, text) for o, text in leaves)


def shared_ok(label: str, num: str, leaves) -> bool:
    """The number belongs to a comparison that includes the run: a swap of the pair cannot be seen in it."""
    return any(len(o) > 1 and any(_same_run(label, x) for x in o) and number_in(num, text) for o, text in leaves)


def swap(answer: str, a: str, b: str) -> str:
    return answer.replace(a, "\x00").replace(b, a).replace("\x00", b)


def measure(sessions: list[dict]) -> dict:
    """sessions: [{"answer": str, "tool_texts": [str]}]. Aggregates only."""
    exposed, pooled_detect, n_claims = 0, 0, 0
    routed = {"original_supported": 0, "original_claims": 0, "swapped_claims": 0,
              "detected": 0, "supported_before_and_after": 0}
    # Step 2, the same claims and swaps routed to the FIELD. `shared_before`: the number belongs to the pair's own
    # comparison, so no attribution check can see a swap of the pair in it.
    field = {"original_supported": 0, "original_shared_only": 0, "swapped_claims": 0,
             "detected": 0, "supported_before_and_after": 0, "shared_before": 0}
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
        leaves = field_leaves(s["tool_texts"])
        field["original_supported"] += sum(field_routed_ok(lab, n, leaves) for lab, n in cl)
        field["original_shared_only"] += sum(not field_routed_ok(lab, n, leaves) and shared_ok(lab, n, leaves)
                                             for lab, n in cl)
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
            field["swapped_claims"] += 1
            f_ok, f_after = field_routed_ok(lab, n, leaves), field_routed_ok(moved, n, leaves)
            if f_ok and not f_after:
                field["detected"] += 1
            elif f_ok and f_after:
                field["supported_before_and_after"] += 1
            elif shared_ok(lab, n, leaves):
                field["shared_before"] += 1
    return {"answers": len(sessions), "claims": n_claims,
            "exposed_answers": exposed,
            "pooled_check_detected_swaps": pooled_detect,
            "routed": routed, "field_routed": field}


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
    if "--same-sessions" in sys.argv[1:]:
        # Re-measure EXACTLY the answers the stored artefact was computed from, and refuse if what it already
        # reported would change: a new measurement added beside an old one must not quietly move the old one.
        old = json.loads(OUT.read_text(encoding="utf-8"))
        want = set(old["session_ids"])
        sessions = [s for s in sessions if s["sid"] in want]
        if len(sessions) != len(want):
            print(f"this store holds {len(sessions)} of the artefact's {len(want)} sessions; not re-measuring.",
                  file=sys.stderr)
            return 2
        moved = {k: (old[k], v) for k, v in measure(sessions).items() if k in old and old[k] != v}
        if moved:
            print(f"refusing: the stored figures would change: {moved}", file=sys.stderr)
            return 3
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
