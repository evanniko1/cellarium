"""H-17a — the corpus invariants, published machine-readably and checked against what actually verifies them.

WHY A FILE AND NOT A DOCSTRING. The rules that make a number from this corpus mean something live in
`support.py`, `capability.py` and tribal knowledge — three places a stranger never opens. A cloner reaches the
same Parquet by CLI, by the web app, by a future MCP surface, or by `duckdb` at a shell prompt, and **only the
Python route touches any of them**. `data/INVARIANTS.json` is the one artifact all four populations can read,
and it is loaded here, by the HF dataset card, and by the MCP surface, so there is one catalogue rather than
three copies drifting apart.

WHY EACH ENTRY CARRIES A PROBE. `capability.py` already established the pattern: it declares markers and
`probe()` greps the model checkout, so a stale declaration is caught rather than believed. Every invariant here
names the `manifest.integrity_check` code that VERIFIES it — or names null WITH the reason there is none. A
declared invariant nobody verifies is a comment, and this codebase has been burned by comments that were true
when written (the `media_id` truncation was documented correctly and silently stopped being true).

`coverage()` is the honest summary: 8 of 17 are probe-verified today, and the other 9 say why not. That ratio
is meant to be read, not hidden — it is the difference between "we have 17 invariants" and "we enforce 8".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PATH = Path(os.environ.get("CELLARIUM_INVARIANTS") or "data/INVARIANTS.json")

_cache: dict | None = None


def load(path: str | os.PathLike | None = None, refresh: bool = False) -> dict:
    """The catalogue. Returns `{"error": ...}` rather than raising — a missing catalogue must not take down a
    read path, and an empty one must never read as "no invariants apply"."""
    global _cache
    if _cache is not None and not refresh and path is None:
        return _cache
    p = Path(path or PATH)
    if not p.exists():
        return {"error": f"no invariant catalogue at {p}",
                "note": ("This is an ABSENCE, not a finding that the corpus has no invariants. Every rule in "
                         "BACKLOG.md § F-HYG still applies; nothing here can check them.")}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"invariant catalogue is unreadable: {type(exc).__name__}: {exc}"}
    if path is None:
        _cache = doc
    return doc


def by_id(inv_id: str) -> dict | None:
    doc = load()
    for i in doc.get("invariants") or ():
        if i.get("id") == inv_id:
            return i
    return None


def probed_by(code: str) -> list[dict]:
    """Which invariants a given `integrity_check` code verifies. The reverse lookup a violation needs: a D3
    hit should be reportable as "invariant INV-7", not as an opaque letter-number."""
    doc = load()
    return [i for i in (doc.get("invariants") or ()) if (i.get("probe") or {}).get("integrity_check") == code]


def coverage() -> dict:
    """How much of the catalogue is actually enforced, and by what.

    Reported as a ratio with both lists, deliberately. "17 invariants" and "8 enforced invariants" are very
    different claims about a corpus, and a catalogue that shows only the first is the kind of declaration this
    file exists to stop.
    """
    doc = load()
    if doc.get("error"):
        return {**doc, "verified": [], "unverified": []}
    inv = doc.get("invariants") or []
    ver = [i["id"] for i in inv if (i.get("probe") or {}).get("integrity_check")]
    unver = [{"id": i["id"], "why_no_probe": (i.get("probe") or {}).get("how")}
             for i in inv if not (i.get("probe") or {}).get("integrity_check")]
    return {
        "n_invariants": len(inv), "n_verified": len(ver), "n_unverified": len(unver),
        "verified": ver, "unverified": unver,
        "note": ("`verified` means a `manifest.integrity_check` code fails when the invariant is broken. "
                 "`unverified` entries are real rules with no mechanical check — each says why, and each is a "
                 "place a stranger can still get it wrong without anything going red."),
    }


def validate(doc: dict | None = None) -> list[str]:
    """Structural problems with the catalogue itself. Used by CI: a catalogue that has drifted from the codes
    it names is worse than none, because it reads as verification that is not happening."""
    doc = doc if doc is not None else load()
    problems: list[str] = []
    if doc.get("error"):
        return [doc["error"]]
    inv = doc.get("invariants") or []
    if not inv:
        problems.append("catalogue contains no invariants")
    seen: set = set()
    for i in inv:
        iid = i.get("id") or "<no id>"
        if iid in seen:
            problems.append(f"{iid}: duplicate id")
        seen.add(iid)
        for field in ("title", "statement", "failure_without_it", "evidence", "standing"):
            if not str(i.get(field) or "").strip():
                problems.append(f"{iid}: empty '{field}'")
        probe = i.get("probe") or {}
        if "integrity_check" not in probe or not str(probe.get("how") or "").strip():
            problems.append(f"{iid}: probe must name an integrity_check code OR say why there is none")
        if bool(i.get("verified")) != bool(probe.get("integrity_check")):
            problems.append(f"{iid}: `verified` disagrees with whether a probe code is named")
    return problems
