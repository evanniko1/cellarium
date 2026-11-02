"""Tier 0 of the mutation job: perturb every declared numeric threshold and see whether anything notices.

WHY THESE AND NOT A RANDOM MUTANT POPULATION. This project's worst defect class is thresholds. One was
UNREACHABLE BY CONSTRUCTION (`G2_ROLE_OVERLAP`'s 0.5, which no development report could reach). One was a
STALE LITERAL sixteen points from its own declared source (`M2_UNRESOLVED_REQUIREMENT_RATE`, 0.798 against a
computed 0.633). `viability_rules.VIABLE_MIN_RATE = 0.9` and `INVIABLE_MAX_RATE = 0.6` are known to have
been set on n=1 machinery and are open as `M-9`. A surviving threshold mutant means a number the paper leans
on that no test pins -- which is the cheapest possible high-yield slice of a mutation run, 64 constants
against 12,414 mutable sites.

HOW A MUTANT IS TARGETED, and why the honest answer needed `coverage`. A threshold's ASSIGNMENT line runs at
import, so covering the assignment tells you nothing. What matters is the lines that USE the constant, and
which tests execute those. So: find the reference lines by AST, then ask the coverage database which test
contexts touched them. Name-matching modules to `tests/test_<module>.py` was considered and rejected on
measurement -- `qc.py` and `viability_rules.py` have NO name-matched test module at all, so that convention
would have run the wrong tests and called the mutants survivors.

WHAT A RESULT MEANS, fixed before the run (docs/MUTATION_SCORE_PLAN.md sec.7):

  * killed              -- a covering test failed. The threshold is pinned.
  * SURVIVED            -- every covering test passed with the value changed. Triage required.
  * no_covering_tests   -- the constant's uses are not executed by any test. Reported as UNMEASURED, never
                           as a pass: three answers, not two, the same rule `readiness()` applies.
  * timeout             -- the covering set did not finish inside a budget scaled to its OWN measured
                           clean wall time (`_budget`). Not a survivor and not a pass.
  * error               -- the mutant could not be applied or the run broke. Not a survivor.

The five partition the population and the run asserts that they sum to it, because the first Tier 0 run's
summary line printed four of them and left its 13 timeouts out of its own total.

There is NO mutation-score target and no pass mark. A percentage with a pass mark is a threshold chosen
after seeing the number, which is the thing this project forbids. The deliverable is the survivor list.

    python scripts/mutate_thresholds.py map        # build constant -> covering tests, from .coverage
    python scripts/mutate_thresholds.py baseline   # time every covering set UNMUTATED, into the map
    python scripts/mutate_thresholds.py controls   # the positive and negative control; run before any tier
    python scripts/mutate_thresholds.py run [--only MODULE] [--limit N]

`baseline` runs between `map` and `run`: it supplies the per-mutant timeout its own covering set earns,
and it is the only thing that makes a `timeout` verdict mean anything. `map` overwrites it.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "cellarium"
COVDB = REPO / ".coverage"
MAP = REPO / "data" / "mutation" / "threshold_test_map.json"
OUT = REPO / "data" / "mutation" / "tier0_results.json"

# A mutant per threshold, in both directions. Two is the minimum that distinguishes "pinned" from "pinned
# only on one side" -- a test asserting `x > T` is killed by lowering T and not by raising it.
def mutants_for(value):
    """Two mutants per threshold, BOTH chosen to be capable of changing behaviour.

    The operator is magnitude-scaled on purpose. A first version used +-1 for every integer, and on a
    6,000-character cap (`agent._TOOL_CAP`) or a 50,000-draw null (`similarity._NULL_CAP`) that is an
    equivalent mutant by construction: no test can distinguish 6000 from 6001, and ~60 such mutants would
    have come back `SURVIVED` and swamped the list with noise nobody should act on -- the same reason
    docs/MUTATION_SCORE_PLAN.md s.5 excludes string literals.

    So: +-1 only where one unit is a real step (small counts and bounds -- MIN_SEEDS=2, MAX_CITED_UNITS=12,
    N_RRN_OPERONS=7, DEGENERATE_MAX_STEPS=10), and halve/double everywhere else, which crosses any
    plausible decision boundary.
    """
    if isinstance(value, bool):
        return []
    if isinstance(value, int) and abs(value) <= 20:
        return [("+1", value + 1), ("-1", value - 1)] if value else [("+1", 1), ("-1", -1)]
    if not value:
        return [("set_1", 1), ("set_-1", -1)]
    half = value // 2 if isinstance(value, int) else value * 0.5
    dbl = value * 2
    return [("half", half), ("double", dbl)]


def _cross_module_refs(name: str, defining: str) -> dict[str, list[int]]:
    """Lines in OTHER source modules that reference this constant.

    Needed because a threshold is routinely read from elsewhere -- `holdout.py` names
    `extraction.MAX_CITED_UNITS` in the verdict it records -- and a test exercising THAT module is as
    relevant as one exercising the definition's own file.
    """
    out = {}
    for f in sorted(SRC.glob("*.py")):
        if f.name == defining:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        lines = sorted({n.lineno for n in ast.walk(tree)
                        if (isinstance(n, ast.Name) and n.id == name)
                        or (isinstance(n, ast.Attribute) and n.attr == name)})
        if lines:
            out[f.name] = lines
    return out


def _tests_naming(name: str) -> list[str]:
    """Test ids whose own source names the constant.

    THE POSITIVE CONTROL CAUGHT THE NEED FOR THIS. Targeting by coverage alone missed the one test that
    pins `MAX_CITED_UNITS` to 12 -- `tests/test_holdout.py` reads the attribute directly, so it covers no
    line inside `extraction.py` and never appeared in the covering set. The mutant survived a run of 49
    genuinely covering tests, none of which cares whether the bound is 12 or 13. A test that asserts a
    constant's VALUE is exactly the test a threshold mutant should be measured against, and coverage
    cannot see it. This is not a proxy for coverage; it is a second, independent source of candidates,
    and the union of the two is strictly better than either.

    NAMES IN CODE, NOT NAMES IN PROSE. The first version matched the constant anywhere in the test's
    source segment, docstrings and comments included, and that is not a weaker rule -- it is a wrong one.
    A boundary case written on 2026-11-02 recorded in its OWN docstring that
    `audit.GB_PER_GENERATION_ARRESTED` is referenced nowhere in the tree, and the join promoted that dead
    constant from `no_covering_tests` to a threshold with a covering test -- which would have put it in
    the `SURVIVED` column of the next run, reading as measured-and-fine, when the column it belongs in is
    the one this tier insists is never a pass. Prose about a threshold asserts nothing about its value.
    `_referenced_names` therefore reads identifiers out of the AST: attribute names, bare names, and
    string literals other than a docstring, because `monkeypatch.setattr(mod, "THRESHOLD", ...)` and
    `getattr(mod, "THRESHOLD")` name one as a string and those ARE references.

    AND MODULE-LEVEL CODE COUNTS, which is how the rule's own founding case actually works. Tightening to
    prose-free identifiers dropped `test_holdout.py` -- the test the positive control was built around --
    because its reference to `MAX_CITED_UNITS` lives in the module-level `VERDICT_CLAIMS` ledger of
    lambdas that one test drives, and the only mention inside the function was in its docstring. The old
    substring rule had been catching that test for the WRONG reason and would have lost it the day the
    docstring was reworded. So each test is credited with the names in its own body and with the names in
    the file's module-level code and helpers -- everything except the other test functions' bodies.
    """
    out = []
    for f in sorted((REPO / "tests").glob("test_*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if name not in text:              # cheap prefilter only; the AST below is the rule
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        rel = f"tests/{f.name}"
        tests = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name.startswith("test_")]
        shared = _referenced_names(ast.Module(
            body=[s for s in tree.body if s not in tests], type_ignores=[]), strings=False)
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                   and n.name.startswith("test_")]:
            if name in shared or name in _referenced_names(fn):
                out.append(f"{rel}::{fn.name}")
    return out


def _referenced_names(node, strings: bool = True) -> set[str]:
    """Identifiers CODE in this subtree mentions, with every docstring inside it excluded.

    A string literal is split into identifier-shaped tokens rather than matched whole, because the
    reference is often dotted: `assert "support.MIN_GENERATIONS" in inspect.getsource(f)` is how
    `test_truncation.py` checks that the floor is the project's own constant and not a second private
    one, and whole-string equality lost it. Exact identifiers, never substrings -- substring matching is
    what credited `_TOOL_CAPS` usage to the unrelated `_TOOL_CAP`.

    `strings=False` IS THE MODULE-LEVEL RULE, and it is a distinction, not a hedge. At module level the
    thing worth catching is executable: `VERDICT_CLAIMS`' lambdas READ `_ex().MAX_CITED_UNITS`, so they
    are a reference a test drives. A module-level STRING naming a threshold is a label in a data
    structure -- a ledger key, a parametrize id, a message -- and a label asserts nothing about a value.
    Counting them credited all 26 tests of `tests/test_threshold_boundaries.py` to all 46 thresholds,
    because that module's own `SURVIVORS` ledger is keyed by `module::NAME`: 50 name-sourced tests became
    1,159, and the catalogue of the finding would have become every threshold's covering set.
    """
    docs = {d for n in ast.walk(node)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            for d in [ast.get_docstring(n, clean=False)] if d is not None}
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute):
            names.add(n.attr)
        elif isinstance(n, ast.Name):
            names.add(n.id)
        elif strings and isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in docs:
            names.update(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", n.value))
    return names


def thresholds(names_only: bool = False) -> list[dict]:
    """Module-level ALL-CAPS numeric assignments, with the lines that REFERENCE each one.

    `names_only` skips the cross-module and test-source scans, which cost ~8,300 file parses (64
    thresholds x every test file) and are not needed by a caller that only wants to know WHICH thresholds
    the tree declares. `tests/test_threshold_boundaries.py` is such a caller, and it imports this function
    rather than re-implementing the rule: one definition of "a declared threshold", two costs.
    """
    out = []
    for f in sorted(SRC.glob("*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
        for node in tree.body:
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign) else [])
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            v = getattr(node, "value", None)
            if not (names and isinstance(v, ast.Constant)):
                continue
            if isinstance(v.value, bool) or not isinstance(v.value, (int, float)):
                continue
            if not names[0].isupper():
                continue
            name = names[0]
            refs = sorted({n.lineno for n in ast.walk(tree)
                           if isinstance(n, ast.Name) and n.id == name and n.lineno != node.lineno})
            # THE LITERAL AS WRITTEN, not as `repr` renders it. The first Tier 0 run lost 4 of 64
            # thresholds to this: `repr(20000)` is `'20000'` and the source says `20_000`;
            # `repr(1e-06)` is `'1e-06'` and the source says `1e-6`. Eight mutants came back `error`
            # rather than `SURVIVED`, which is the only reason it was visible at all -- the text
            # substitution refused to pretend it had found its target.
            literal = ast.get_source_segment(text, v) or repr(v.value)
            row = {"module": f.name, "name": name, "value": v.value, "literal": literal,
                   "assign_line": node.lineno, "ref_lines": refs}
            if not names_only:
                row["cross_refs"] = _cross_module_refs(name, f.name)
                row["tests_naming"] = _tests_naming(name)
            out.append(row)
    return out


def _contexts_for(con, filename_like: str, lines: set[int]) -> set[str]:
    """Test contexts that executed any of `lines` in the file matching `filename_like`."""
    fid = None
    for (i, path) in con.execute("select id, path from file").fetchall():
        if path.replace("\\", "/").endswith(filename_like):
            fid = i
            break
    if fid is None:
        return set()
    ctx = {i: name for i, name in con.execute("select id, context from context").fetchall()}
    got = set()
    for cid, numbits in con.execute(
            "select context_id, numbits from line_bits where file_id = ?", (fid,)).fetchall():
        hit = {b * 8 + k for b, byte in enumerate(numbits) for k in range(8) if byte & (1 << k)}
        if hit & lines:
            name = ctx.get(cid, "")
            if name:
                got.add(name)
    return got


def build_map() -> dict:
    """Rebuild the covering-set map, CARRYING OVER a baseline whose covering set has not changed.

    A rebuild used to overwrite the map wholesale, which silently dropped the `baseline_s` that
    `baseline` had written into it -- and `_budget(None)` is the flat 180 s cap, the very thing that made
    13 mutants look like hangs when they were survivors. A rebuild therefore DEGRADED the measurement
    while reporting nothing, so `run` now refuses to start without the baselines rather than falling
    back. Carried over only when the test LIST is byte-identical: a baseline measured on 9 tests is not
    a budget for the 23 that set now holds, and a stale number is worse than a missing one.
    """
    if not COVDB.is_file():
        sys.exit(f"{COVDB} is absent. Run the suite once with:\n"
                 "  python -m pytest tests -q --cov=src/cellarium --cov-context=test --cov-report=")
    prior = json.loads(MAP.read_text(encoding="utf-8")) if MAP.is_file() else {}
    con = sqlite3.connect(str(COVDB))
    try:
        rows = {}
        for t in thresholds():
            key = f"{t['module']}::{t['name']}"
            # THREE sources, unioned. (a) tests covering the constant's reference lines in its own module;
            # (b) tests covering lines in other modules that reference it; (c) tests whose source names it.
            # (c) exists because the positive control failed without it -- see `_tests_naming`.
            ctxs = _contexts_for(con, f"cellarium/{t['module']}", set(t["ref_lines"]))
            for mod, lines in t["cross_refs"].items():
                ctxs |= _contexts_for(con, f"cellarium/{mod}", set(lines))
            tests = {c.split("|")[0] for c in ctxs if c.split("|")[0]}
            by_cov = len(tests)
            tests |= set(t["tests_naming"])
            rows[key] = {**t, "n_tests": len(tests), "n_by_coverage": by_cov,
                         "n_added_by_name": len(tests) - by_cov, "tests": sorted(tests)}
            was = prior.get(key) or {}
            if was.get("baseline_s") and was.get("tests") == rows[key]["tests"]:
                rows[key]["baseline_s"] = was["baseline_s"]
                rows[key]["baseline_code"] = was.get("baseline_code")
    finally:
        con.close()
    MAP.parent.mkdir(parents=True, exist_ok=True)
    MAP.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    covered = sum(1 for v in rows.values() if v["n_tests"])
    kept = sum(1 for v in rows.values() if v.get("baseline_s"))
    need = sorted(k for k, v in rows.items() if v["n_tests"] and not v.get("baseline_s"))
    print(f"{len(rows)} thresholds; {covered} have covering tests, {len(rows) - covered} have none")
    print(f"baselines: {kept} carried over unchanged, {len(need)} need re-timing (`baseline`)")
    if need:
        print("  " + ", ".join(need[:6]) + (f", +{len(need) - 6} more" if len(need) > 6 else ""))
    print(f"wrote {MAP.relative_to(REPO).as_posix()}")
    return rows


def _apply(path: Path, line: int, old_literal: str, new_repr: str) -> str:
    """Replace the literal on one line, byte-wise, and return the original text for restoration.

    `old_literal` is the source segment as WRITTEN (`20_000`, `1e-6`), not `repr` of the parsed value.
    The write is asserted rather than assumed: a substitution that left the line unchanged would hand
    every downstream verdict a clean tree to run against and report the survivors of a mutation that
    never happened.
    """
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    i = line - 1
    if old_literal not in lines[i]:
        raise ValueError(f"{path.name}:{line} does not contain {old_literal!r}: {lines[i]!r}")
    mutated = lines[i].replace(old_literal, new_repr, 1)
    if mutated == lines[i]:
        raise ValueError(f"{path.name}:{line} unchanged by {old_literal!r} -> {new_repr!r}")
    lines[i] = mutated
    path.write_text("".join(lines), encoding="utf-8")
    return original


def _run(tests: list[str], timeout: int = 180) -> tuple[int, str, float]:
    cmd = [sys.executable, "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider", *tests]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO), timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)[-400:], round(time.time() - t0, 1)
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT", round(time.time() - t0, 1)


def _machine_load() -> dict:
    """What else was running, recorded WITH the run because every timing here is a cost figure.

    Tier 0's whole cost model (35 s/mutant, 4,471 s) was measured while an unrelated job held roughly 4.5
    of 16 cores from before the run began, which makes those numbers an upper bound rather than a
    measurement -- and nothing in the output said so. `psutil` is optional and not a declared dependency,
    so its absence is recorded as UNMEASURED rather than as a quiet machine.

    A snapshot is LIFETIME cpu per process, which is a proxy for "busy now" and a bad one: the first
    version of this ranked `vmmemWSL` at 371,701 s above the job actually competing for the run, because
    an old long-lived process beats a hot young one on a lifetime total. What competes with a run is the
    DELTA across it, so `_load_delta` differences two snapshots; `cpu_percent_1s` is the one figure a
    single snapshot can report honestly.
    """
    try:
        import psutil
    except ImportError:
        return {"measured": False, "why": "psutil is not installed; concurrent load is UNMEASURED"}
    me, parent = os.getpid(), os.getppid()
    try:                                    # our own pytest children are not "other load"
        mine = {c.pid for c in psutil.Process(me).children(recursive=True)}
    except psutil.Error:
        mine = set()
    by_pid = {}
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.pid in (me, parent, 0) or p.pid in mine:
                continue
            cpu = p.cpu_times()
            cmd = " ".join(p.info["cmdline"] or [p.info["name"] or "?"])
            by_pid[str(p.pid)] = [round(cpu.user + cpu.system, 1), cmd[-110:]]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {"measured": True, "logical_cores": psutil.cpu_count(),
            "cpu_percent_1s": psutil.cpu_percent(interval=1.0), "cpu_by_pid": by_pid}


def _load_delta(before: dict, after: dict, elapsed_s: float) -> dict:
    """CPU seconds other processes burned DURING the run, and what that is as a share of the machine."""
    if not (before.get("measured") and after.get("measured")):
        return {"measured": False, "why": before.get("why") or after.get("why") or "no snapshot"}
    b, a = before["cpu_by_pid"], after["cpu_by_pid"]
    # A RELATIVE floor: 5% of one core over the window. An absolute "30 CPU-seconds" was tried first and
    # reported a BUSY machine as quiet -- 30 s is unreachable for most processes in a short window, so the
    # floor silenced the answer rather than filtering it. Forced on a 9 s window against a job measured at
    # 2.4 cores, the probe returned `other_cpu_s=0, quiet=True`, which is the dead-instrument shape.
    rows = []
    floor = 0.05 * max(elapsed_s, 1.0)
    for pid, (secs, cmd) in a.items():
        used = secs - (b.get(pid, [0.0])[0] if pid in b else 0.0)
        if used >= floor:
            rows.append({"pid": int(pid), "cpu_s_during_run": round(used, 1), "cmd": cmd})
    rows.sort(key=lambda r: -r["cpu_s_during_run"])
    total = sum(r["cpu_s_during_run"] for r in rows)
    cores = before.get("logical_cores") or 1
    return {"measured": True, "other_cpu_s_during_run": round(total),
            "cores_equivalent": round(total / max(elapsed_s, 1.0), 2), "of_logical_cores": cores,
            "quiet": total / max(elapsed_s, 1.0) < 0.5, "busiest": rows[:6]}


def _budget(baseline_s: float | None) -> int:
    """The per-mutant timeout, derived from the covering set's own measured clean wall time.

    WHY NOT A FLAT 180 s, which the first Tier 0 run used. `pytest -x` stops at the first failure, so a
    KILLED mutant exits early and a SURVIVING one must run every covering test to the end. A flat budget
    therefore expires preferentially on survivors, and 13 of 128 mutants came back `timeout` -- a verdict
    that reads like a hang and can equally be a slow test set that nothing failed in. Scaling the budget
    to the set's own baseline makes `timeout` mean what it says: this mutant made the set far slower, or
    hung it. Floor of 180 s so a fast set still tolerates ordinary variance.

    MEASURED, and it settled the question. All 13 timeouts of the first run came from 9 thresholds whose
    CLEAN wall time is between 313 s and 956 s -- every one above the flat cap, so not one could have
    finished without failing early. They were budget artefacts, not hangs, and the `half`/`double`
    asymmetry was the tell: the killed arm exits at the first failure in seconds while the surviving arm
    pays the whole set.

    The multiplier is 2.5x and not more, because the budget's only job is to catch a hang: a surviving
    mutant finishes at about the baseline. It is not smaller than 2x because for a count-like constant
    (`NULL_PERMUTATIONS`, `_SEARCH_BUDGET`) the `double` mutant legitimately doubles the work, and a
    budget that called that a hang would be measuring the operator rather than the code.
    """
    if not baseline_s:
        return 180
    return max(180, int(2.5 * baseline_s) + 60)


def baseline(rows: dict, only: str | None, force: bool = False) -> int:
    """Time every covering set on an UNMUTATED tree, and record it in the map.

    This is the denominator the timeout verdict needs, and it doubles as the cost model: the plan's
    estimate of ~10 s per mutant was taken from the wall time of a single test id, which ignores that a
    threshold's covering set runs 1-56 tests.

    Sets that already carry a baseline for their CURRENT test list are skipped, so a map rebuild costs
    only the sets whose membership actually moved. `--force` re-times everything.
    """
    pool = [v for k, v in sorted(rows.items()) if (not only or v["module"] == only) and v["tests"]]
    items = pool if force else [t for t in pool if not t.get("baseline_s")]
    skipped = len(pool) - len(items)
    print(f"{len(items)} covering sets to time, unmutated"
          f"{f' ({skipped} already timed for their current test list)' if skipped else ''}\n")
    if not items:
        print("nothing to time; pass --force to re-measure")
        return 0
    for t in items:
        code, tail, secs = _run(t["tests"][:60], timeout=1800)
        t["baseline_s"] = secs
        t["baseline_code"] = code
        flag = "" if code in (0, 5) else f"  <-- clean run is NOT green (exit {code}): {tail[-120:]}"
        print(f"  {t['module']}::{t['name']:<28} {len(t['tests'][:60]):>3} tests  {secs:7.1f}s{flag}")
    MAP.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    timed = [t["baseline_s"] for t in items]
    bad = [t for t in items if t["baseline_code"] not in (0, 5)]
    print(f"\nmin {min(timed):.1f}s  median {sorted(timed)[len(timed) // 2]:.1f}s  "
          f"mean {sum(timed) / len(timed):.1f}s  max {max(timed):.1f}s")
    print(f"{len(bad)} covering sets are not green on a clean tree"
          f"{'' if not bad else ': ' + ', '.join(t['name'] for t in bad)}")
    print(f"wrote baselines into {MAP.relative_to(REPO).as_posix()}")
    return 0 if not bad else 1


def controls(rows: dict) -> int:
    """The instrument's positive and negative control, before any real mutant.

    POSITIVE: a threshold known to be pinned must come back `killed`. NEGATIVE: a mutation that cannot
    change behaviour must come back `survived`. A harness that has never reported each of those, on demand,
    is not measuring anything -- CLAUDE.md's rule, applied to this script.
    """
    ok = True
    pos = rows.get("extraction.py::MAX_CITED_UNITS")
    if not pos or not pos["tests"]:
        print("  POSITIVE CONTROL: unavailable (MAX_CITED_UNITS has no covering tests in the map)")
        ok = False
    else:
        path = SRC / pos["module"]
        orig = _apply(path, pos["assign_line"], pos["literal"], repr(pos["value"] + 1))
        try:
            # ALL of them, not a slice. The first version ran `tests[:40]`; the map is sorted, the 49
            # `test_extraction.py` ids sort before `test_holdout.py`, and the one test that pins the value
            # to 12 was cut off -- so the control reported SURVIVED because of its own truncated domain.
            # A control that measures a subset of its own evidence is the class-B failure, in the
            # instrument built to catch it.
            code, tail, _secs = _run(pos["tests"], timeout=_budget(pos.get("baseline_s")))
        finally:
            path.write_text(orig, encoding="utf-8")
        print(f"  POSITIVE CONTROL  MAX_CITED_UNITS 12 -> 13 : "
              f"{'killed  OK' if code not in (0, 5) else 'SURVIVED  <-- the harness is not detecting'}")
        ok = ok and code not in (0, 5)
    # NEGATIVE: add a module-level constant nothing reads, then mutate it. No test can notice.
    probe = SRC / "_mutation_control_probe.py"
    probe.write_text("MUTATION_CONTROL_PROBE = 1\n", encoding="utf-8")
    try:
        orig = _apply(probe, 1, "1", "2")
        code, _tail, _secs = _run(["tests/test_number_provenance.py"])
        probe.write_text(orig, encoding="utf-8")
        print(f"  NEGATIVE CONTROL  a constant nothing reads   : "
              f"{'survived  OK' if code == 0 else 'killed  <-- the harness reports kills it cannot have'}")
        ok = ok and code == 0
    finally:
        probe.unlink(missing_ok=True)
    print("  -> controls PASS" if ok else "  -> controls FAIL: do not trust a tier run")
    return 0 if ok else 1


def run(rows: dict, only: str | None, limit: int | None) -> int:
    results, t0 = [], time.time()
    load_before = _machine_load()
    pct = load_before.get("cpu_percent_1s")
    if pct is not None and pct >= 15:
        print(f"  NOTE: the machine is not quiet -- {pct}% of {load_before['logical_cores']} logical cores "
              "busy before the first mutant.")
        print("  Every timing below is an UPPER BOUND on the per-mutant cost; the delta is in the artefact.\n")
    items = [v for k, v in sorted(rows.items()) if not only or v["module"] == only]
    if limit:
        items = items[:limit]
    # REFUSE rather than fall back. `_budget(None)` is the flat 180 s cap, and that cap is what turned 13
    # survivors into `timeout` in the first pass; a map rebuild silently drops the baselines, so running
    # on an unmeasured budget is a degradation nobody would see in the output.
    unmeasured = [f"{v['module']}::{v['name']}" for v in items if v["tests"] and not v.get("baseline_s")]
    if unmeasured:
        sys.exit(f"{len(unmeasured)} covering set(s) have no measured baseline, so their budget would be "
                 f"the flat cap that made survivors look like hangs. Run `baseline` first.\n  "
                 + ", ".join(unmeasured[:8]) + (f", +{len(unmeasured) - 8} more" if len(unmeasured) > 8 else ""))
    planned = sum(len(mutants_for(v["value"])) for v in items)
    print(f"{len(items)} thresholds -> {planned} mutants\n")
    for t in items:
        key = f"{t['module']}::{t['name']}"
        if not t["tests"]:
            for label, _nv in mutants_for(t["value"]):
                results.append({**{k: t[k] for k in ("module", "name", "value")}, "mutant": label,
                                "verdict": "no_covering_tests", "n_tests": 0})
            print(f"  {key:<52} UNMEASURED (no covering tests)")
            continue
        tests = t["tests"][:60]
        for label, newval in mutants_for(t["value"]):
            path = SRC / t["module"]
            try:
                orig = _apply(path, t["assign_line"], t["literal"], repr(newval))
            except ValueError as exc:
                results.append({**{k: t[k] for k in ("module", "name", "value")}, "mutant": label,
                                "verdict": "error", "detail": str(exc)[:200]})
                print(f"  {key:<52} ERROR applying {label}")
                continue
            budget, first = _budget(t.get("baseline_s")), None
            try:
                code, tail, secs = _run(tests, timeout=budget)
                # A timeout is RE-RUN ONCE, at a far larger budget, before it is recorded as one. One
                # attempt cannot separate a hung mutant from a stalled machine, and the difference is the
                # whole content of the verdict. MEASURED: pass 3's single timeout (`_PER_SIM_RAM_GB`
                # doubled) burned all 303 s of a budget derived from a 97 s baseline, while its `half`
                # sibling finished the same 12 tests in 85 s -- and the same mutant then finished in 84 s
                # on a re-run with nothing changed but the hour. A real-time virus scanner, not a hang.
                # This matters beyond one row: `timeout` is an UNRESOLVED verdict, and an unresolved
                # verdict is how a threshold with no disposition slips past the ledger's completeness
                # check, which reads the survivor column. Resolving it here keeps the partition honest.
                if code == 124:
                    retry = max(1800, 12 * budget)
                    print(f"  {key:<52} {label:>7} -> {newval!r:<12} timeout at {budget}s"
                          f"  <-- re-running once at {retry}s")
                    first = secs
                    code, tail, secs = _run(tests, timeout=retry)
                    budget = retry
            finally:
                path.write_text(orig, encoding="utf-8")
            verdict = ("killed" if code not in (0, 5, 124)
                       else "timeout" if code == 124 else "SURVIVED")
            results.append({**{k: t[k] for k in ("module", "name", "value")}, "mutant": label,
                            "new_value": newval, "verdict": verdict, "n_tests": len(tests),
                            "secs": secs, "baseline_s": t.get("baseline_s"), "budget_s": budget,
                            **({"first_timeout_s": first, "resolved_from": "timeout"} if first else {}),
                            "tail": tail if verdict != "killed" else ""})
            print(f"  {key:<52} {label:>7} -> {newval!r:<12} {verdict}  "
                  f"({len(tests)} tests, {secs:.0f}s/{budget}s)")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # EVERY category, and they must sum to the denominator. The first run's summary line printed
    # killed/SURVIVED/UNMEASURED/errors -- 115 of 128 -- and left the 13 timeouts out of its own total,
    # so the run reported a partition of a population it had silently shrunk. Asserted, not printed.
    tally = {v: sum(1 for r in results if r["verdict"] == v)
             for v in ("killed", "SURVIVED", "no_covering_tests", "error", "timeout")}
    if sum(tally.values()) != len(results):
        raise AssertionError(f"verdicts {tally} sum to {sum(tally.values())}, not {len(results)} mutants")
    OUT.write_text(json.dumps({
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "No mutation-score target and no pass mark by design; see docs/MUTATION_SCORE_PLAN.md s.7. "
                "`no_covering_tests` is UNMEASURED, never a pass.",
        "n_thresholds": len(items), "n_mutants": len(results),
        "killed": tally["killed"], "survived": tally["SURVIVED"],
        "unmeasured": tally["no_covering_tests"],
        "errors": tally["error"], "timeouts": tally["timeout"],
        "elapsed_s": round(time.time() - t0, 1),
        "concurrent_load": _load_delta(load_before, _machine_load(), time.time() - t0),
        "results": results}, indent=1) + "\n", encoding="utf-8")
    print(f"\n{len(results)} mutants in {time.time() - t0:.0f}s -> {OUT.relative_to(REPO).as_posix()}")
    print("  " + " | ".join(f"{k} {v}" for k, v in tally.items())
          + f"  = {sum(tally.values())} of {len(results)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("map", "baseline", "controls", "run"))
    ap.add_argument("--only", default=None, help="restrict to one source module, e.g. qc.py")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true",
                    help="baseline: re-time sets that already carry a baseline for their current tests")
    a = ap.parse_args(argv)
    if a.cmd == "map":
        build_map()
        return 0
    if not MAP.is_file():
        sys.exit(f"{MAP} is absent; run `map` first")
    rows = json.loads(MAP.read_text(encoding="utf-8"))
    if a.cmd == "baseline":
        return baseline(rows, a.only, a.force)
    return controls(rows) if a.cmd == "controls" else run(rows, a.only, a.limit)


if __name__ == "__main__":
    os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/*.parquet")
    raise SystemExit(main())
