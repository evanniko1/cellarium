"""S2-2: an integrity audit of a Cellwright answer, after the fact.

PLAT-1 (`reconcile.py`) asks whether an answer names runs the turn never read. This asks three more questions of
the same answer, each with a planted fault in `tests/test_answer_integrity.py` that it must catch:

  NUMBERS    Each number credited to a run should sit in a field of THAT run in the turn's tool output. The rule is
             I.8's field rule (moved here from `evals/attribution_swap.py`, which now imports it): it caught 29 of
             30 numbers swapped between two runs in 60 recorded answers, where a pooled check ("the number is
             somewhere in the output") caught none. Four outcomes per claim:
               own_run         in a field owned by the credited run
               shared          in a comparison's own statistic that includes the run (a swap cannot show there)
               other_run_only  in a field of another run only: the swap signature, and the only number finding
                               the note names
               unrouted        in no field: computed by the agent (a ratio of two read values), from prose, or
                               paired with the wrong label by the nearest-label rule. Counted, never named: in
                               the 60 recorded answers 65 of 140 claims are unrouted, so naming them would bury
                               the misattributions.
  VERDICT    A turn whose reply is the gate's rendered refusal or proposal ran no tool. `investigate` returns
             before dispatch, so this checks the record against the code's promise.
  CITATIONS  Every DOI and PMID the answer cites appears in what the turn read. Whether a paper SUPPORTS the
             sentence needs a model and is not checked; the audit says "not checked" rather than leaving it out.

Like PLAT-1 it annotates and never rewrites, and it fails closed: with no tool output to read, the verdict is
`could_not_verify` and the note says the check could not run.

LIMITS. The claim pattern pairs a number with the nearest run label before it in the same sentence, so a run named
in prose ("the argS knockout") is invisible and a number can be paired with the wrong label; numbers are matched
at the answer's own rounding, so a short number can match a field by coincidence.
"""
from __future__ import annotations

import json
import re

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


# --- S2-2: the audit ---------------------------------------------------------------------------------------------

def classify(label: str, num: str, leaves) -> tuple[str, list[str]]:
    """One claim's status, and the other runs whose fields hold the number when it is misattributed."""
    if field_routed_ok(label, num, leaves):
        return "own_run", []
    if shared_ok(label, num, leaves):
        return "shared", []
    others = sorted({next(iter(o)) for o, text in leaves
                     if len(o) == 1 and not _same_run(label, next(iter(o))) and number_in(num, text)})
    return ("other_run_only", others) if others else ("unrouted", [])


# A design written in a family the label pattern does not cover: `graded_gene_knockout/KO:argS#expr:0.1` reads as
# `KO:argS`, `ppgpp_conc/basal|ppGpp:0.6x` as `ppgpp_conc/basal`. Seven of the corpus's ten families are such.
_DESIGN = re.compile(r"\b(?:[a-z]+(?:_[a-z]+)+|timeline)/[^\s`'\"(),;*]+")


def _significant(tok: str) -> int:
    return len(tok.rstrip("%").lstrip("+-").replace(".", "").lstrip("0"))


def actionable_claims(answer: str) -> list[tuple[str, str]]:
    """The claims whose pairing with a run is unambiguous enough to name a misattribution: prose, not a table row;
    a sentence that names exactly one run, in a family the label pattern recognises; a number of three or more
    significant digits. On the 60 recorded answers I.8 used, every one of the 13 misattributions the plain rule
    found was the pairing's error, not the answer's (7 table columns, 3 sentences comparing two runs, 2 graded
    knockdowns read as full knockouts, 1 two-digit number matching another run by rounding); this rule finds none,
    and keeps 11 of the 140 claims. Precision bought with coverage: the rest need provenance written with the
    number, which no parser can recover afterwards."""
    prose = "\n".join(line for line in answer.splitlines() if not line.lstrip().startswith("|"))
    out = []
    for sent in SENTENCE.split(prose):
        runs: list[str] = []
        for lab in LABEL.findall(sent):
            if not any(_same_run(lab, r) for r in runs):
                runs.append(lab)
        if len(runs) != 1 or any(not LABEL.fullmatch(d.rstrip(".:")) for d in _DESIGN.findall(sent)):
            continue
        out += [(lab, n) for lab, n in claims(sent) if _significant(n) >= 3]
    return out


def audit_numbers(answer: str, tool_texts: list[str]) -> dict:
    """Every claim with its status (counted), and the actionable ones found only in another run's field (named)."""
    leaves = field_leaves(tool_texts)
    out = []
    for label, num in claims(answer):
        status, found_in = classify(label, num, leaves)
        out.append({"label": label, "number": num, "status": status, **({"found_in": found_in} if found_in else {})})
    named = []
    for label, num in actionable_claims(answer):
        status, found_in = classify(label, num, leaves)
        if status == "other_run_only":
            named.append({"label": label, "number": num, "status": status, "found_in": found_in})
    return {"claims": out, "misattributed": named,
            "counts": {s: sum(c["status"] == s for c in out) for s in ("own_run", "shared", "other_run_only",
                                                                     "unrouted")}}


# The heads `gate.render` writes for the two verdicts that stop an investigation. A test renders both through the
# gate itself, so a change to the wording there fails here rather than silently disarming the check.
GATE_HEADS = ("This model cannot represent what the question asks.",
              "This model can represent what the question asks, but no run exists to read.")


def audit_verdict(reply: str, tool_calls: int | None) -> dict:
    gated = (reply or "").lstrip().startswith(GATE_HEADS)
    if not gated:
        return {"gated": False, "respected": None}
    return {"gated": True, "respected": None if tool_calls is None else tool_calls == 0}


DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+")
PMID = re.compile(r"\bPMID:?\s*(\d{5,9})\b", re.I)


_TRAIL = ".,;:'*_`"                         # sentence punctuation and the markdown an answer wraps a DOI in


def _doi(tok: str) -> str:
    tok = tok.rstrip(_TRAIL)
    while tok.endswith(("]", ")")) and tok.count(tok[-1]) > tok.count("[" if tok[-1] == "]" else "("):
        tok = tok[:-1].rstrip(_TRAIL)
    return tok


def audit_citations(answer: str, tool_texts: list[str]) -> dict:
    # A tool result is JSON, often stringified inside JSON, so a DOI's slash arrives as "\/" escaped once or more
    # (a recorded Crossref result holds "10.1126\\/science.1070919"); without this it reads as never returned.
    blob = re.sub(r"\\+/", "/", "\n".join(tool_texts))
    low = blob.lower()
    cited = [_doi(m.group(0)) for m in DOI.finditer(answer)] + [f"PMID:{m.group(1)}" for m in PMID.finditer(answer)]
    cited = list(dict.fromkeys(cited))

    def read(c: str) -> bool:
        if c.startswith("PMID:"):
            return re.search(rf"(?<!\d){c[5:]}(?!\d)", blob) is not None
        return c.lower() in low

    return {"cited": cited, "unread": [c for c in cited if not read(c)], "supporting": "not checked"}


def audit(answer: str, tool_texts: list[str] | None, *, tool_calls: int | None) -> dict:
    """All three checks on one answer. `tool_texts` None means the turn's output could not be read."""
    if tool_texts is None:
        return {"verdict": "could_not_verify",
                "why": "no tool output to read: this check reports that it could not run, never that the answer "
                       "passed"}
    nums, cites = audit_numbers(answer, tool_texts), audit_citations(answer, tool_texts)
    verdict = audit_verdict(answer, tool_calls)
    faults = bool(nums["misattributed"] or cites["unread"] or verdict["respected"] is False)
    return {"verdict": "faults" if faults else "clean", "numbers": nums, "citations": cites, "gate": verdict}


def annotation(result: dict) -> str:
    """The note to append, or "" when there is nothing precise to say. Silent on a clean answer, as PLAT-1 is."""
    if result.get("verdict") == "could_not_verify":
        return "\n\n---\n**Integrity check could not run**: " + result["why"] + ". Treat this as unverified."
    if result.get("verdict") != "faults":
        return ""
    lines = ["", "---", "**Integrity check: what the record does not support.** The answer above is left exactly as "
             "written; this note is the record, not a correction."]
    for c in result["numbers"]["misattributed"][:8]:
        lines.append(f"- {c['number']} is credited to `{c['label']}`, but the tool output holds it only in a field "
                     f"of {', '.join(f'`{x}`' for x in c['found_in'])}.")
    for c in result["citations"]["unread"][:8]:
        lines.append(f"- `{c}` is cited, but no tool call in this conversation returned it.")
    if result["gate"]["respected"] is False:
        lines.append("- The gate stopped this question, yet tools ran in the turn.")
    return "\n".join(lines)
