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

**VERIFIED END-TO-END on a throwaway branch (`ci/verify-annotations`, deleted), not assumed.** A deliberately
failing test was pushed, CI went red, and the annotation was read back from
`/repos/<owner>/<repo>/check-runs/<id>/annotations` with NO token. Round 1 exposed two real defects that local
testing had missed, both fixed here:
  1. the pytest nodeid contains `::`, the workflow-command delimiter, so an unescaped `title=` truncated at the
     first `::` and spilled the rest into the message (see `_escape_prop`);
  2. `file`/`line` were absent because pytest's DEFAULT `junit_family=xunit2` drops them — CI now asks for
     `xunit1`, so the annotation anchors to the failing test instead of the workflow file.
Round 2 returned exactly what it should:
    path : tests/test_ci_annotation_probe.py | line 7
    title: pytest failure: tests/test_ci_annotation_probe.py::test_ci_annotation_probe_deliberate_failure
    msg  : AssertionError: … / assert 272 == 264
If either behaviour regresses, re-run that probe rather than trusting the local unit checks — both defects
passed locally and only surfaced against the real API.
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_ANNOTATIONS = 30       # GitHub renders ~50 per run; keep headroom and say when we truncate
MAX_MSG_LINES = 12         # the assertion + its immediate context, not the whole traceback


def _escape(text: str) -> str:
    """Escape the DATA half (after `::`) — a raw newline would silently truncate the annotation."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_prop(text: str) -> str:
    """Escape a PROPERTY VALUE (`title=…`), which needs MORE than the data half: `:` and `,` are the property
    delimiters, so an unescaped one silently truncates the command.

    This is not theoretical — it is the bug the end-to-end probe caught. A pytest nodeid contains `::`
    (`tests/test_x.py::test_name`), so `title=pytest failure: tests/test_x.py::test_name` made GitHub end the
    property section at that `::` and dump the rest of the nodeid into the message. The annotation still
    appeared, but with a truncated title and a mangled body — which is exactly the kind of half-broken
    diagnostic that is worse than none, because it looks like it worked."""
    return _escape(text).replace(":", "%3A").replace(",", "%2C")


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
            name = case.get("name") or "?"
            classname = case.get("classname", "")
            # `file`/`line` exist only under junit_family=xunit1 — the DEFAULT xunit2 schema drops them, which is
            # why the first probe run anchored its annotation to `.github` instead of the test file. CI requests
            # xunit1; this still derives a path from the dotted classname (tests.test_x -> tests/test_x.py) so a
            # config drift degrades to "right file, no line" instead of "wrong file entirely".
            file = (case.get("file") or "").replace("\\", "/")
            if not file and classname:
                file = classname.replace(".", "/") + ".py"
            nodeid = f"{file}::{name}" if file else f"{classname or '?'}::{name}"
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
        props.append("title=" + _escape_prop("pytest {}: {}".format(f["kind"], f["nodeid"])))
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
