"""Validation-layer item 8: mutation operators aimed at what the capability registry and the gate ENCODE.

WHY A SECOND HARNESS. `scripts/mutate_thresholds.py` mutates numeric literals: `<` for `<=`, 20 for 21. That is
first-order syntactic mutation, and published work on domain-semantic operators (arXiv:2605.17437) finds three of
the five fault classes a scientific registry is exposed to unreachable by it. Here the faults are the ones the
registry exists to prevent, written as concrete edits to the shipped records and to the gate's decision code:

  widen      a record claims a mode it does not hold in        (per-isoacceptor charging "in steady_state")
  aggregate  an all/and becomes any/or                          (a route that satisfies SOME requirements)
  threshold  a reporting floor moves                            (two seeds become one)
  provenance a record's evidence flips                          (present -> absent; its source markers dropped)
  branch     a structural shortcut appears in the gate          (answer every per-isoacceptor question)
  reproducibility  the four the spec names, where they apply    (seed and generation floors; a dependency pin)

PRE-REGISTERED. `data/mutation/registry_plan.json` lists every mutant, the exact edit, the operator class and a
PREDICTION (killed or survived) with its reason, and was committed before any mutant ran; the results are
compared against it, so a surprise is visible as a surprise. The workflow is fixed in the plan too: the FULL
suite, Docker off, in a clean worktree of the frozen revision, stopping at the first failure. The likely
killers are listed first on the command line only to save time: pytest de-duplicates, so the verdict is the
full suite's either way. A baseline run must be green, or no verdict is meaningful and the harness stops.

Edits are byte-exact both ways (read and written as bytes, the file's own line endings kept), because
`mutate_thresholds.py` was found on 2026-11-23 to leave restored files with changed line endings.

    python scripts/mutate_registry.py --check                 # every edit applies exactly once; nothing runs
    python scripts/mutate_registry.py --root C:/tmp/wt        # baseline + controls + mutants, in a worktree
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLAN = REPO / "data" / "mutation" / "registry_plan.json"
RESULTS = REPO / "data" / "mutation" / "registry_results.json"
NO_DOCKER = "npipe:////./pipe/cellarium_no_such_engine" if os.name == "nt" else "unix:///nonexistent.sock"


def apply_edit(path: Path, old: str, new: str) -> bytes:
    """Replace the ONE occurrence of `old` with `new`, keeping the file's own line endings. Returns the
    original bytes, which are what a restore writes back. Zero or several occurrences raise: an edit that
    did not land would hand the suite a clean tree and report the survivor of a mutation that never happened."""
    raw = path.read_bytes()
    nl = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8")
    o, n = old.replace("\n", nl), new.replace("\n", nl)
    count = text.count(o)
    if count != 1:
        raise ValueError(f"{path.name}: the edit's target occurs {count} times, not once: {old[:70]!r}")
    path.write_bytes(text.replace(o, n, 1).encode("utf-8"))
    return raw


def restore(path: Path, original: bytes) -> None:
    path.write_bytes(original)


def run_suite(root: Path, first: list[str], timeout_s: int) -> dict:
    cmd = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "--timeout=900",
           *[f for f in first if (root / f).exists()], "tests"]
    env = {**os.environ, "DOCKER_HOST": NO_DOCKER, "PYTHONDONTWRITEBYTECODE": "1"}
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout_s, env=env)
        code, out = p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        code, out = 124, str(e.stdout or "")
    failed = re.findall(r"^(?:FAILED|ERROR) (\S+)", out, flags=re.M)
    return {"exit": code, "secs": round(time.time() - t0, 1), "first_failure": failed[0] if failed else None,
            "summary": next((ln for ln in reversed(out.splitlines()) if " passed" in ln or " failed" in ln), "")}


def verdict(code: int) -> str:
    return {0: "survived", 1: "killed", 124: "timeout"}.get(code, f"error(exit {code})")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(REPO), help="the checkout to mutate (use a clean worktree)")
    ap.add_argument("--check", action="store_true", help="verify every edit applies exactly once; run nothing")
    ap.add_argument("--timeout", type=int, default=3600, help="seconds per full-suite run")
    ap.add_argument("--out", default=str(RESULTS))
    a = ap.parse_args(argv)
    root = Path(a.root)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    items = plan["controls"] + plan["mutants"]

    for m in items:                                    # the check runs in every mode, before anything else
        path = root / m["file"]
        orig = apply_edit(path, m["old"], m["new"])
        restore(path, orig)
        assert path.read_bytes() == orig, f"{m['id']}: restore was not byte-exact"
    print(f"all {len(items)} edits apply exactly once and restore byte-exactly in {root}")
    if a.check:
        return 0

    base = run_suite(root, [], a.timeout)
    print(f"baseline: exit {base['exit']} in {base['secs']} s  {base['summary']}")
    results = {"plan_frozen": plan["frozen"], "revision": plan.get("revision"), "root": str(root),
               "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "baseline": base, "rows": []}
    if base["exit"] != 0:
        results["aborted"] = "the unmutated suite is not green here, so no mutant verdict would mean anything"
        Path(a.out).write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
        print(results["aborted"])
        return 3
    for m in items:
        path = root / m["file"]
        orig = apply_edit(path, m["old"], m["new"])
        try:
            r = run_suite(root, m.get("likely_killers", []), a.timeout)
        finally:
            restore(path, orig)
        v = verdict(r["exit"])
        results["rows"].append({"id": m["id"], "class": m["class"], "file": m["file"], "prediction": m["prediction"],
                                "verdict": v, "as_predicted": v == m["prediction"], **r})
        print(f"  {m['id']:<6} {m['class']:<16} predicted {m['prediction']:<9} got {v:<9} "
              f"{r['secs']:>7} s  {r['first_failure'] or ''}")
        Path(a.out).write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")   # survive an interruption
    results["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    Path(a.out).write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
