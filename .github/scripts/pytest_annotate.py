"""Turn a pytest JUnit-XML report into GitHub ANNOTATIONS, so a CI failure is diagnosable without the raw log.

Why this exists: a CI run failed on `7b5220d` and the only thing recoverable through the unauthenticated GitHub
API was `Process completed with exit code 1` — the job log needs a token to download, so the failing test was a
black box (it turned out to be a flake, but that took an identical-tree re-run to establish rather than a glance).

**Annotations are the one CI output the API exposes without auth** (`/check-runs/<id>/annotations`), so this
emits one `::error file=...,line=...::` per failing test. That makes "which test failed, and why" readable from
the API, the PR diff view, and the run summary — no token, no log download, no guessing.

Stdlib only (no new CI dependency). Exits 0 by design: the pytest step already failed the job, and a second
non-zero here would just add noise. If the report is missing entirely — pytest crashed before writing it, e.g. a
collection or import error — that is itself reported as the finding rather than passing silently.
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_ANNOTATIONS = 30       # GitHub renders ~50 per run; keep headroom and say when we truncate
MAX_MSG_LINES = 12         # the assertion + its immediate context, not the whole traceback


def _escape(text: str) -> str:
    """GitHub workflow-command escaping — a raw newline would silently truncate the annotation."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _tail(text: str, n: int = MAX_MSG_LINES) -> str:
    """The LAST n non-empty lines: pytest puts the assertion and the exception at the end of a traceback, so the
    tail is the diagnostic part and the head is usually setup noise."""
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def _failures(report: Path) -> list[dict]:
    out: list[dict] = []
    root = ET.parse(report).getroot()
    for case in root.iter("testcase"):
        for kind in ("failure", "error"):
            node = case.find(kind)
            if node is None:
                continue
            file = case.get("file") or ""
            name = case.get("name") or "?"
            nodeid = f"{file}::{name}" if file else f"{case.get('classname', '?')}::{name}"
            body = _tail(f"{node.get('message', '')}\n{node.text or ''}")
            out.append({"kind": kind, "nodeid": nodeid, "file": file,
                        "line": case.get("line") or "0", "message": body})
    return out


def main() -> int:
    report = Path(sys.argv[1] if len(sys.argv) > 1 else "pytest-report.xml")
    if not report.exists():
        print(f"::error::pytest wrote no JUnit report at '{report}'. It almost certainly crashed BEFORE running "
              "tests — a collection error, an import error, or a conftest failure. The raw job log has the "
              "traceback; this is the one case annotations cannot recover.")
        return 0

    try:
        failures = _failures(report)
    except ET.ParseError as exc:
        print(f"::error::pytest's JUnit report at '{report}' is not parseable ({exc}) — the run was likely "
              "killed mid-write (OOM or timeout).")
        return 0

    if not failures:
        # pytest can exit non-zero with no failed testcase: usage error, no tests collected, or -W error.
        print("::warning::The pytest step failed but the JUnit report lists no failing test. Likely a usage "
              "error, an empty collection, or a non-test failure (e.g. a warning promoted to an error). "
              "Check the raw log.")
        return 0

    shown = failures[:MAX_ANNOTATIONS]
    for f in shown:
        # Properties are comma-joined and must not carry an empty slot — `::error ,title=…` is malformed and
        # GitHub drops the annotation, which would defeat the whole point. `file` is absent when a test runs
        # from outside rootdir, so build the list conditionally rather than interpolating a maybe-empty string.
        props = [f"file={f['file']}", f"line={f['line']}"] if f["file"] else []
        title = _escape("pytest {}: {}".format(f["kind"], f["nodeid"]))
        props.append(f"title={title}")
        print(f"::error {','.join(props)}::{_escape(f['message'])}")
    if len(failures) > len(shown):
        print(f"::error::…and {len(failures) - len(shown)} more failing test(s) — see the uploaded "
              "`pytest-report` artifact for the full list.")

    # Also write a job summary: rendered in the run's UI, so a human sees the list without opening the log.
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### ❌ {len(failures)} failing test(s)\n\n")
            for f in failures:
                fh.write(f"- **`{f['nodeid']}`** ({f['kind']})\n")
            fh.write("\n<details><summary>First failure detail</summary>\n\n```\n"
                     f"{failures[0]['message']}\n```\n</details>\n")

    print(f"Surfaced {len(shown)} of {len(failures)} failing test(s) as annotations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
