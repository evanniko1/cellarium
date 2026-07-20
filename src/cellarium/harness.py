"""The self-harness — a capability gate over Council falsifiers (audit M-1).

The blind Council names a statistical test in each falsifier's `decision_rule` ("dip test for bimodality",
"slope 95% CI excludes 0", "Welch t>=2"). Nothing used to check that a named test is EXECUTABLE by Cellwright's
toolkit, so when the Council named a test with no tool it failed silently (the agent narrated around it or
substituted the nearest wrong tool). This module closes that loop: on every finished Hypothesis it

  (a) DETECTS, deterministically, whether each named test maps to an executable tool (test_registry.py), and
  (b) for a genuine GAP, writes an idempotent, DEV-GATED record into BACKLOG.md (class X) so a developer picks it
      up and either implements the tool or tightens the Council so it stops naming it.

Design (SOTA brief wf_f7f85832): the detector is a deterministic structural match against a controlled vocabulary
(Gorilla — zero false positives; the LLM never grades itself, LLM-Modulo). The writer is dev-gated (gateswell /
DGM): it only ever CREATES `open` rows and increments how-often-seen; it never sets priority, never edits a
human-set State, and never reopens a row a human marked wontfix/resolved. No tool is ever synthesized
automatically — the record is an inspectable artifact, a human acts on it.

v1 scans the free-text decision_rule against the registry's curated aliases; it reliably catches a named test we
KNOW we lack (Hartigan's dip, Mann-Whitney, KS, ANOVA, mixture, rank-correlation) and confirms the ones we have.
Catching a genuinely NOVEL test the Council invents needs the structured `NamedTest` falsifier field with an
`"other"` escape hatch (brief step 2) — tracked as LLM-3 in BACKLOG.md.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import test_registry

BACKLOG = Path(__file__).resolve().parents[2] / "BACKLOG.md"

_SECTION = "## X · Capability gaps (auto-filed by the self-harness)"
_PREAMBLE = (
    "Written by `src/cellarium/harness.py` on every Council run: a falsifier that names a statistical test with "
    "no executable tool (see `test_registry.py`) is filed here for a developer to close. **The harness only "
    "creates `open` rows and bumps `Seen`; edit the `State` cell by hand — it is respected and never reopened.** "
    "Resolve a gap by either implementing the tool (add its `TestSpec`; the gap then stops recurring) or tightening "
    "the proposer so the Council stops naming it (set `State` to `wontfix`). Auto-filed at P3 until a dev triages; "
    "`Seen >= 3` earns a `⚑` ready-for-triage flag."
)
_BEGIN = "<!-- HARNESS-GAPS:BEGIN (managed by harness.py — edit only the State cell) -->"
_END = "<!-- HARNESS-GAPS:END -->"
_HEADER = ("| ID | State | Seen | Missing capability | Suggested resolution |\n"
           "|----|-------|------|--------------------|-----------------------|")

_TRIAGE_THRESHOLD = 3          # Seen >= this earns the ready-for-triage flag (gateswell ">=3 occurrences")
_MAX_NEW_PER_CALL = 3          # rate-limit: at most this many NEW gap rows per scan (flood guard)
_lock = threading.Lock()       # in-process guard for the read-modify-write of BACKLOG.md


# --- gap record ------------------------------------------------------------------------------------------

@dataclass
class GapRecord:
    test_id: str
    family: str
    matched: str                      # what the Council actually wrote (a matched alias, or an 'other' statistic)
    kind: str = "missing_test"        # "missing_test" (known-unsupported alias) | "unlisted_test" (structured 'other')
    question: str = ""
    hyp_id: str = ""
    rule: str = ""

    @property
    def gap_id(self) -> str:
        # keyed on the CAPABILITY (kind|family|test_id), normalized free of per-hypothesis thresholds/labels, so
        # the same missing test always hashes to the same id regardless of which hypothesis surfaced it.
        sig = f"{self.kind}|{self.family}|{self.test_id}"
        return "GAP-" + hashlib.sha1(sig.encode()).hexdigest()[:8]


# --- detection -------------------------------------------------------------------------------------------

def _falsifier_text(hyp) -> tuple[str, str]:
    """(decision_rule, refuting_result) from a Hypothesis object OR a stored hypothesis dict; ('','') if none."""
    f = getattr(hyp, "falsifier", None)
    if f is None and isinstance(hyp, dict):
        f = hyp.get("falsifier")
    if not f:
        return "", ""
    if isinstance(f, dict):
        return f.get("decision_rule", "") or "", f.get("refuting_result", "") or ""
    return getattr(f, "decision_rule", "") or "", getattr(f, "refuting_result", "") or ""


def _question(hyp) -> str:
    return (getattr(hyp, "question", None) or (hyp.get("question") if isinstance(hyp, dict) else "") or "")


def _named_test(hyp) -> tuple[str, str] | None:
    """(test_id, statistic) from the STRUCTURED falsifier.test field (M-1b), on an object or a stored dict; None
    if the run predates the field."""
    f = getattr(hyp, "falsifier", None)
    if f is None and isinstance(hyp, dict):
        f = hyp.get("falsifier")
    if not f:
        return None
    t = f.get("test") if isinstance(f, dict) else getattr(f, "test", None)
    if not t:
        return None
    if isinstance(t, dict):
        return (t.get("test_id") or ""), (t.get("statistic") or "")
    return (getattr(t, "test_id", "") or ""), (getattr(t, "statistic", "") or "")


def _slug(text: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "unspecified")[:40]


def scan_hypothesis(hyp, hyp_id: str = "") -> list[GapRecord]:
    """GapRecords for every test the falsifier names that the toolkit can't run. Two detectors:
      (1) FREE-TEXT (v1) — a distinctive alias of a known-UNSUPPORTED test in the decision_rule (Hartigan's dip,
          Mann-Whitney, ...). Reliable for the curated set; works on legacy runs with no structured field.
      (2) STRUCTURED (M-1b) — the falsifier's `test.test_id` is `"other"` (or not a supported id), i.e. the Council
          itself declared no listed test fits. This catches a NOVEL test deterministically, even one not in the
          curated list. Suppressed if (1) already filed a more-specific known gap for this falsifier.
    Empty list = the falsifier is fully executable (the common, healthy case)."""
    rule, refute = _falsifier_text(hyp)
    text = f"{rule}\n{refute}"
    gaps: dict[str, GapRecord] = {}
    for spec in test_registry.match(text):
        if spec.supported:
            continue
        alias = next((a for a in spec.aliases if test_registry._norm(a) in test_registry._norm(text)), spec.test_id)
        rec = GapRecord(test_id=spec.test_id, family=spec.family, matched=alias, kind="missing_test",
                        question=_question(hyp), hyp_id=hyp_id or "", rule=rule)
        gaps.setdefault(rec.gap_id, rec)   # one record per capability even if two aliases hit

    nt = _named_test(hyp)
    if nt and not gaps:                    # a free-text known gap is more specific -> don't also file 'unlisted'
        test_id, statistic = nt
        if test_id == "other" or (test_id and test_id not in test_registry.supported_ids()):
            label = statistic or rule or "unspecified"
            rec = GapRecord(test_id=_slug(label), family="unlisted", matched=label, kind="unlisted_test",
                            question=_question(hyp), hyp_id=hyp_id or "", rule=rule)
            gaps.setdefault(rec.gap_id, rec)
    return list(gaps.values())


# --- the BACKLOG block: parse / merge / render -----------------------------------------------------------

@dataclass
class _Row:
    gap_id: str
    state: str = "open"                       # HUMAN-editable; harness respects anything != "open"
    seen: list[str] = field(default_factory=list)   # distinct surfacing hyp_ids (dedup + count)
    first: str = ""
    question: str = ""
    test_id: str = ""
    family: str = ""


_ROW_RE = re.compile(r"^\|\s*`(GAP-[0-9a-f]{8})`\s*\|\s*([^|]*?)\s*\|", re.M)
_META_RE = re.compile(
    r"<!--gap (GAP-[0-9a-f]{8}) \| test=(\S+) family=(\S+) \| seen=([^|]*) \| first=([^|]*) \| q=(.*?) -->")


def _parse_block(text: str) -> dict[str, _Row]:
    """Rebuild the row state from the managed block: State from the visible table cell (human-owned), everything
    else from the machine comment (harness-owned)."""
    rows: dict[str, _Row] = {}
    for gid, test_id, family, seen, first, q in _META_RE.findall(text):
        rows[gid] = _Row(gap_id=gid, seen=[s for s in seen.split(",") if s],
                         first=first.strip(), question=q.strip(), test_id=test_id, family=family)
    for gid, state in _ROW_RE.findall(text):     # overlay the human-set State onto the machine state
        if gid in rows:
            rows[gid].state = (state or "open").strip() or "open"
    return rows


def _render(rows: dict[str, _Row]) -> str:
    lines = [_BEGIN, "", _HEADER]
    meta = []
    for gid, r in sorted(rows.items()):
        if r.family == "unlisted":         # a novel test the Council named via test_id="other" (M-1b)
            cap = f"**{r.test_id}** — a test named via `test_id=\"other\"`, not in the registry (novel/unlisted)."
            res = "implement it as a tool + add a `TestSpec`, OR tighten the proposer if it is spurious/redundant"
        else:
            spec = test_registry.by_id(r.test_id)
            cav = f" {spec.caveat}" if spec and spec.caveat else ""
            doc = f" ({spec.doc})" if spec and spec.doc else ""
            cap = f"**{r.test_id}** named, no executable tool.{cav}"
            res = f"implement the tool{doc} OR alias to a supported test + tighten the proposer"
        flag = " ⚑" if len(r.seen) >= _TRIAGE_THRESHOLD else ""
        lines.append(f"| `{gid}` | {r.state} | {len(r.seen)}×{flag} | {cap} | {res} |")
        q = (r.question or "").replace("\n", " ").replace("-->", "->")[:160]
        meta.append(f"<!--gap {gid} | test={r.test_id} family={r.family} | "
                    f"seen={','.join(r.seen)} | first={r.first} | q={q} -->")
    lines.append("")
    lines.extend(meta)
    lines.append(_END)
    return "\n".join(lines)


def _ensure_section(doc: str) -> str:
    """Guarantee the class-X section + an empty managed block exist; return the (possibly extended) document."""
    if _BEGIN in doc:
        return doc
    block = f"{_SECTION}\n\n{_PREAMBLE}\n\n{_render({})}\n"
    anchor = "## Coordinate with Filippo"
    if anchor in doc:
        return doc.replace(anchor, block + "\n" + anchor, 1)
    return doc.rstrip() + "\n\n" + block


def write_gaps(records: list[GapRecord], backlog_path: Path | str = BACKLOG,
               today: str | None = None) -> dict:
    """Idempotently merge gap records into BACKLOG.md class X. Respects human State edits, dedups by capability
    hash, dedups repeat sightings by hyp_id, rate-limits new rows, and writes only when the block actually changed
    (no churn / clean git diffs). Returns a summary {filed, updated, skipped, unchanged}."""
    path = Path(backlog_path)
    today = today or date.today().isoformat()
    with _lock:
        doc = path.read_text(encoding="utf-8") if path.exists() else ""
        doc = _ensure_section(doc)
        start = doc.index(_BEGIN)
        end = doc.index(_END) + len(_END)
        rows = _parse_block(doc[start:end])

        summary = {"filed": [], "updated": [], "skipped": [], "unchanged": True}
        new_count = 0
        for rec in records:
            gid = rec.gap_id
            row = rows.get(gid)
            if row is None:
                if new_count >= _MAX_NEW_PER_CALL:
                    summary["skipped"].append(gid + " (rate-limited)")
                    continue
                rows[gid] = _Row(gap_id=gid, state="open", seen=[rec.hyp_id] if rec.hyp_id else [],
                                 first=today, question=rec.question, test_id=rec.test_id, family=rec.family)
                new_count += 1
                summary["filed"].append(gid)
            elif row.state != "open":
                summary["skipped"].append(gid + f" (human State={row.state})")   # respect the dev's decision
            elif rec.hyp_id and rec.hyp_id not in row.seen:
                row.seen.append(rec.hyp_id)
                row.question = rec.question or row.question
                summary["updated"].append(gid)
            # else: same run re-scanned -> no change (idempotent)

        new_block = _render(rows)
        new_doc = doc[:start] + new_block + doc[end:]
        if new_doc != doc:
            path.write_text(new_doc, encoding="utf-8")
            summary["unchanged"] = False
        return summary


def scan_and_file(hyp, hyp_id: str = "", backlog_path: Path | str = BACKLOG, today: str | None = None) -> dict:
    """The listener: detect gaps in one finished Hypothesis and file them. Never raises out to the caller — a
    self-harness must never break a Council run (best-effort; returns an error dict instead)."""
    try:
        records = scan_hypothesis(hyp, hyp_id)
        if not records:
            return {"gaps": [], "unchanged": True}
        summary = write_gaps(records, backlog_path, today=today)
        summary["gaps"] = [r.test_id for r in records]
        return summary
    except Exception as exc:   # noqa: BLE001 — the harness is advisory; degrade quietly
        return {"error": f"{type(exc).__name__}: {exc}"}


def audit_store(store, backlog_path: Path | str = BACKLOG, today: str | None = None) -> dict:
    """Sweep mode: scan every persisted Council run and file gaps in one pass (a batch audit, no live run needed).
    `store` is an apps.hypotheses.HypothesisStore. Returns per-capability totals."""
    all_records: list[GapRecord] = []
    for row in store.list(limit=1000):
        run = store.get(row["id"])
        if run and run.get("hypothesis"):
            all_records.extend(scan_hypothesis(run["hypothesis"], run["id"]))
    summary = write_gaps(all_records, backlog_path, today=today) if all_records else {"unchanged": True}
    summary["scanned_records"] = len(all_records)
    return summary


if __name__ == "__main__":   # manual batch audit: `python -m cellarium.harness` sweeps stored runs -> BACKLOG
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps"))
    from hypotheses import HypothesisStore  # type: ignore

    print(audit_store(HypothesisStore()))
