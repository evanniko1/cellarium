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
    python scripts/mutate_thresholds.py selfref [--static] [--limit N]

`baseline` runs between `map` and `run`: it supplies the per-mutant timeout its own covering set earns,
and it is the only thing that makes a `timeout` verdict mean anything. `map` overwrites it.

`selfref` is a SEPARATE sweep over the suite's own assertions rather than over the source, and it needs
neither the map nor `.coverage`. Tier 0 answers "does anything notice this number move"; `selfref`
answers "does this TEST notice", which is a different question with a different blind spot -- the join it
replaces (`_survivor_keys()` x `tests_naming`) resolved to 2 tests while 40 name a declared threshold,
and 7 of the 9 cases it had itself found were already outside it. See `_sweep_candidates` for the four
classes and `_discriminate` for why it runs ONE test id and not the covering set.
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
SELFREF = REPO / "data" / "mutation" / "selfref.json"

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


# ----------------------------------------------------------------------------------------------------
# The `selfref` sweep: which ASSERTIONS cannot see their own threshold move.
# ----------------------------------------------------------------------------------------------------
#
# WHY THIS IS NOT THE SHAPE THE BACKLOG ASKED FOR. The remedy filed for the nine self-referential cases
# was a sweep for `<expr involving CONST> == <expr involving the same CONST>`. That rule was implemented
# and MEASURED over all 136 test files: it matches ONE assertion in the suite (`tests/test_llm_seam.py:91`,
# on `TEMPERATURE`, which is a CORRECT assertion -- two modules must agree) and NONE of the nine it was
# generalised from. In all nine the constant appears on one side only and the other side holds a value the
# PRODUCTION code derived from that same constant: `_gb(8, 1) == round(8 * audit.GB_PER_GENERATION, 2)`,
# `max_tokens <= extraction.AGENT_MAX_TOKENS_CAP`, `len(seen) <= D._MAX_NODES`. That is data flow, not
# syntax, so the static half here classifies rather than matches, and the decision is made by MUTATION.
#
# The four classes and the per-class meaning:
#
#   * both_sides       -- the same constant on two sides of one comparison. The backlog's shape. Rarest.
#   * literal_pinned   -- the constant pinned BY LITERALS: an equality against a literal, or literals on
#                         both sides of a chain (`8000 <= CAP <= 16000`). The form this project's ledger
#                         exists to write; the expectation does not move with the mutant.
#   * one_sided_bound  -- an inequality whose other sides are not pure literals. `CAP <= 16000` is here
#                         and NOT in `literal_pinned`, deliberately: it catches raising the cap and not
#                         lowering it, which is precisely what the review of `test_extraction.py:1269`
#                         records about it. A one-sided literal bound is half a pin.
#   * computed_equality -- an equality against something a call produced. The `test_audit.py:7` shape.
_SELFREF_CLASSES = ("both_sides", "literal_pinned", "one_sided_bound", "computed_equality")

# The verdicts stage 2 may record. Five, and they MUST partition the candidate set -- the same assertion
# `run()` carries, for the same reason: the first Tier 0 run's summary line printed four of its five
# categories and left its 13 timeouts out of its own total, reporting a partition of a population it had
# silently shrunk. `unmeasured` is never a pass; neither is `error` or `timeout`.
_SELFREF_VERDICTS = ("detects_it", "cannot_see_it_move", "unmeasured", "error", "timeout")

# A pair's class, when its occurrences disagree. STRONGEST EVIDENCE FIRST: a pair that pins its constant
# against a literal anywhere in the test is detectable regardless of what else it does, so `literal_pinned`
# wins -- `tests/test_threshold_boundaries.py::test_the_agent_token_cap_has_a_FLOOR_and_not_only_a_ceiling`
# carries both a `== 12000` and an `8000 <= .. <= 16000` and is correctly a pin. Then the backlog's own
# shape, then the two data-flow shapes. Every class a pair carries is kept in `classes`, so the reduction
# hides nothing; the primary is what the tally partitions on.
_SELFREF_PRECEDENCE = ("literal_pinned", "both_sides", "computed_equality", "one_sided_bound")

# Nodes whose value cannot be read off the source. A comparison side containing none of these is a pure
# literal expression (`300`, `8000`, `"x" * 3`, `(1, 2)`), and only then can it pin anything.
_OPAQUE = (ast.Name, ast.Attribute, ast.Call, ast.Subscript)
_BOUND_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _constant_inventory() -> dict[str, list[str]]:
    """Every module-level constant-shaped name in `src/cellarium`, and the module(s) declaring it.

    A DELIBERATE SUPERSET of `thresholds()`, which is why the rule is `name.lstrip('_').isupper()` and
    carries no type test at all. `runner.WALL_MIN_PER_GEN = float(os.environ.get(..., "180"))` is the
    proof it has to be: it is a threshold by every meaning of the word, `tests/test_failures.py:161` names
    it, and `thresholds()` cannot see it because the assigned value is not an `ast.Constant`. A threshold
    written as an expression was outside tier 0's universe by construction, and the join inherited that
    blindness. MEASURED 2026-11-14: 479 names here against 63 declared numeric thresholds. Both counts
    move with the tree, so `data/mutation/selfref.json` records the pair it was swept at rather than
    leaving this comment as the only statement of it.

    The value is a LIST because a name can be declared in several modules -- `TEMPERATURE` in `agent.py`
    and `llm.py`, `MANIFEST_GLOB` in three. Stage 2 resolves the mutation target through `thresholds()`
    instead, which currently declares no duplicated name, but the ambiguity is recorded per candidate
    rather than collapsed, because a test naming `TEMPERATURE` may mean either one.
    """
    inv: dict[str, set[str]] = {}
    for f in sorted(SRC.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign) else [])
            for t in targets:
                if isinstance(t, ast.Name) and t.id.lstrip("_").isupper():
                    inv.setdefault(t.id, set()).add(f.name)
    return {k: sorted(v) for k, v in inv.items()}


def _literal_only(node: ast.AST) -> bool:
    """True when nothing in this subtree hides a value the source does not state."""
    return not any(isinstance(n, _OPAQUE) for n in ast.walk(node))


def _root_name(node: ast.AST) -> str | None:
    """The leftmost bare name of an attribute/subscript chain: `extraction.citable_units` -> 'extraction'."""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _subject_call_lines(fn: ast.AST, modules: set[str]) -> list[int]:
    """Lines where this test CALLS one of the modules that declare the constant, assertions excluded.

    This is what separates a slack bound from a correct precondition, and the distinction is positional
    rather than syntactic. `tests/test_extraction.py:1528` asserts `len(row) > extraction.CITABLE_UNIT_MAX`
    one line BEFORE `extraction.citable_units(row)`: the inequality is keeping the fixture pathological if
    the cap ever moves, which is the right way to write it, and its slackness is correct. Two lines away in
    the same file, `max(len(u['text'])) <= extraction.CITABLE_UNIT_MAX` comes AFTER the call and asserts a
    property of the RESULT -- and that one holds at every cap. Same operator, opposite meaning.

    Calls inside the assertion itself are excluded, or the assertion would be its own subject. Known limit:
    a test that imports the function directly (`from cellarium.extraction import citable_units`) calls it
    by a bare name that is not the module's, so no subject call is found and the flag stays False. The flag
    is advisory -- it never changes a verdict, it tells a reviewer where to look first.
    """
    inside: set[int] = set()
    for a in [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]:
        inside.update(id(n) for n in ast.walk(a))
    return sorted({n.lineno for n in ast.walk(fn)
                   if isinstance(n, ast.Call) and id(n) not in inside
                   and _root_name(n.func) in modules})


def _classify_side(cmp_node: ast.Compare, idx: int, name: str) -> str:
    """The class of one (comparison side, constant) pair. The order of the tests IS the rule.

    `both_sides` first because it is unconditional. `literal_pinned` second, and it demands the constant
    actually be pinned -- an equality, or a position with literals on both sides of it -- because
    `CAP <= 16000` leaves the constant free to fall and calling that a pin is the error the review of
    `tests/test_extraction.py:1269` already recorded in prose. `one_sided_bound` third, so a chain of
    inequalities against anything opaque lands there. `computed_equality` is the remainder, which is why
    `in`/`not in` and `!=` against a call end up there rather than in a class of their own.
    """
    sides = [cmp_node.left, *cmp_node.comparators]
    for j, side in enumerate(sides):
        if j != idx and name in _referenced_names(side):
            return "both_sides"
    others = [s for j, s in enumerate(sides) if j != idx]
    if all(_literal_only(s) for s in others):
        equality = any(isinstance(op, (ast.Eq, ast.NotEq)) for op in cmp_node.ops)
        straddled = 0 < idx < len(sides) - 1          # a literal on each side of the constant
        if equality or straddled:
            return "literal_pinned"
    if all(isinstance(op, _BOUND_OPS) for op in cmp_node.ops):
        return "one_sided_bound"
    return "computed_equality"


def _assert_shapes(text: str, rel: str, inventory: dict[str, list[str]]) -> list[dict]:
    """Every (test, constant) candidate in one test file's source, reduced from its occurrences.

    `inventory` is a parameter rather than a call so the classifier can be driven on PLANTED source with a
    planted inventory -- `tests/test_selfreferential_assertions.py` does exactly that, one plant per class
    plus the two legitimate false positives (a constant named only in a docstring, and the singular of a
    plural in use). A classifier that has only ever been run on the real tree has never been shown to
    refuse anything.

    `_referenced_names` is reused unchanged, so "names the constant" has ONE definition across the harness:
    attribute names, bare names and identifier tokens from non-docstring strings, exact identifiers never
    substrings. It is applied here to a comparison SIDE rather than to a whole test body, which is a change
    of domain and not of rule -- and the plants re-prove it in the new domain rather than assuming it.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    rows: dict[str, dict] = {}
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]:
        subject_by_name: dict[str, list[int]] = {}
        for a in [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]:
            for cmp_node in [n for n in ast.walk(a.test) if isinstance(n, ast.Compare)]:
                sides = [cmp_node.left, *cmp_node.comparators]
                for i, side in enumerate(sides):
                    for nm in sorted(_referenced_names(side) & inventory.keys()):
                        if nm not in subject_by_name:
                            stems = {m[:-3] for m in inventory[nm]}
                            subject_by_name[nm] = _subject_call_lines(fn, stems)
                        subject = subject_by_name[nm]
                        row = rows.setdefault(f"{fn.name}::{nm}", {
                            "key": f"{rel}::{fn.name}::{nm}", "test": f"{rel}::{fn.name}",
                            "constant": nm, "declared_in": inventory[nm], "occurrences": []})
                        row["occurrences"].append({
                            "line": a.lineno, "class": _classify_side(cmp_node, i, nm),
                            "equality": any(isinstance(op, (ast.Eq, ast.NotEq)) for op in cmp_node.ops),
                            # A precondition by position: the assertion runs before the module under test
                            # is called at all, so it is validating the fixture rather than the result.
                            "fixture_precondition": bool(subject) and a.lineno < min(subject)})
    out = []
    for row in rows.values():
        classes = {c: sum(1 for o in row["occurrences"] if o["class"] == c) for c in _SELFREF_CLASSES}
        row["classes"] = {c: n for c, n in classes.items() if n}
        row["class"] = next(c for c in _SELFREF_PRECEDENCE if classes[c])
        # The pair is a precondition only if EVERY occurrence is one. A single assertion made after the
        # call is an assertion about the result, and that is the one worth measuring.
        row["fixture_precondition"] = all(o["fixture_precondition"] for o in row["occurrences"])
        out.append(row)
    return sorted(out, key=lambda r: r["key"])


def _sweep_candidates(inventory: dict[str, list[str]] | None = None,
                      files: list[Path] | None = None) -> dict[str, dict]:
    """Stage 1 over the whole suite: `tests/file.py::test_name::CONST` -> the candidate row."""
    inv = inventory if inventory is not None else _constant_inventory()
    out = {}
    for f in files if files is not None else sorted((REPO / "tests").glob("test_*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        for row in _assert_shapes(text, f"tests/{f.name}", inv):
            out[row["key"]] = row
    return out


def _run_one(test_id: str, cwd: Path, timeout: int) -> tuple[int, str, float]:
    """One pytest invocation on one node id, with the project's own `addopts` turned OFF.

    `-o addopts=` is not tidiness. `pyproject.toml` sets `addopts = "-q"`, and a second `-q` on the command
    line suppresses the summary line entirely -- which is how a run with zero collected tests becomes
    indistinguishable from a green one by eye. The verdict here reads the EXIT CODE, but the tail is what a
    reviewer sees, and a tail with no summary line is the same silent absence in a smaller place.
    """
    cmd = [sys.executable, "-m", "pytest", test_id, "-o", "addopts=", "-q", "--no-header",
           "--tb=no", "-p", "no:cacheprovider"]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd), timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)[-400:], round(time.time() - t0, 1)
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT", round(time.time() - t0, 1)


def _discriminate(target: Path, line: int, literal: str, value, test_id: str, *,
                  cwd: Path = REPO, timeout: int = 300) -> dict:
    """Stage 2: perturb the literal both ways and run `test_id` ALONE. Never the covering set.

    THE COVERING SET IS THE MASK, and this is the single change that makes the finding stay closed. A
    self-referential assertion lives in a file beside tests that DO pin the constant; run them together and
    the suite goes red, the mutant is recorded `killed`, and the assertion that cannot see its own threshold
    move is reported as one that can. That is not an argument -- it is forced on planted source in
    `tests/test_selfreferential_assertions.py`, where two tests over one constant give `detects_it` for the
    file and `cannot_see_it_move` for the self-referential test id.

    WHICH VERDICT WINS WHEN THE TWO MUTANTS DISAGREE. A failure under either direction is positive evidence
    that the test notices, so `detects_it` is checked first. Everything after it is an absence of evidence
    and is reported as one: a stalled run is `timeout`, a skip or an empty collection is `unmeasured`, a
    broken interpreter or collection error is `error`. Only two completed, green, genuinely mutated runs
    yield `cannot_see_it_move` -- and even that is a measurement handed to a human, not a conviction: a
    fixture, a monkeypatch or a module-level cache holding the pre-mutation value produces the same signal.

    `target` is restored in a `finally` for every mutant, and the caller is handed the reason when the
    substitution refuses: `literal` is the source segment as WRITTEN, so `12_000` against a `repr`-derived
    `'12000'` must come back `unmeasured` rather than as a clean run on an unmutated tree. Eight mutants of
    the first Tier 0 pass died that way, and they were visible only because the substitution refused to
    pretend it had found its target.
    """
    muts = mutants_for(value)
    if not muts:
        return {"verdict": "unmeasured", "runs": [],
                "reason": f"no mutation operator for {value!r}; `mutants_for` produces none"}
    runs: list[dict] = []
    for label, newval in muts:
        try:
            orig = _apply(target, line, literal, repr(newval))
        except (ValueError, IndexError) as exc:
            return {"verdict": "unmeasured", "runs": runs,
                    "reason": f"the literal {literal!r} could not be substituted at {target.name}:{line} "
                              f"({exc}); the tree was NOT mutated, so nothing was measured"}
        try:
            code, tail, secs = _run_one(test_id, cwd, timeout)
        finally:
            target.write_text(orig, encoding="utf-8")
        runs.append({"mutant": label, "new_value": newval, "code": code, "secs": secs,
                     # pytest exits 0 for a skipped test, so the exit code alone cannot tell a test that
                     # passed under the mutant from one that never ran. A skip is UNMEASURED.
                     "skipped": bool(re.search(r"\b\d+ skipped\b", tail) and " passed" not in tail),
                     "tail": tail[-200:]})
    if any(r["code"] == 1 for r in runs):
        return {"verdict": "detects_it", "runs": runs,
                "reason": "the test failed under at least one mutant, so it can see the value move"}
    if any(r["code"] == 124 for r in runs):
        return {"verdict": "timeout", "runs": runs,
                "reason": f"a mutant run did not finish inside {timeout}s; nothing is decided"}
    if any(r["skipped"] or r["code"] == 5 for r in runs):
        return {"verdict": "unmeasured", "runs": runs,
                "reason": "the test skipped or collected nothing under a mutant, so it was never asked"}
    if any(r["code"] not in (0, 1, 5, 124) for r in runs):
        return {"verdict": "error", "runs": runs,
                "reason": f"pytest exited {[r['code'] for r in runs]}; the run broke rather than deciding"}
    return {"verdict": "cannot_see_it_move", "runs": runs,
            "reason": "the test passed under BOTH mutants: the assertion holds whatever the constant is"}


def selfref(limit: int | None = None, static: bool = False) -> int:
    """The three stages, into `data/mutation/selfref.json`.

    Stage 3 is the artefact and the two tallies, and both are ASSERTED to partition the candidate set
    rather than printed. A summary whose categories do not add up to its own denominator is how the first
    Tier 0 run reported 115 of 128 mutants as a complete classification.
    """
    t0 = time.time()
    inv = _constant_inventory()
    cands = _sweep_candidates(inv)
    declared = {t["name"]: t for t in thresholds(names_only=True)}
    files = sorted((REPO / "tests").glob("test_*.py"))
    mutatable = sorted(k for k, v in cands.items() if v["constant"] in declared)
    print(f"{len(files)} test files -> {len(cands)} (test, constant) candidates across "
          f"{len({v['test'] for v in cands.values()})} tests")
    print(f"  inventory {len(inv)} constants; {len(declared)} are declared numeric thresholds")
    print(f"  {len(mutatable)} candidates have a mutation operator; "
          f"{len(cands) - len(mutatable)} are STATIC ONLY and reported UNMEASURED\n")
    measured = 0
    for key in sorted(cands):
        row = cands[key]
        t = declared.get(row["constant"])
        row["threshold"] = f"{t['module']}::{row['constant']}" if t else None
        if not t:
            row["verdict"], row["runs"] = "unmeasured", []
            row["reason"] = ("not a declared numeric threshold, so there is no mutation operator for it; "
                             "this candidate carries a STATIC classification and no measurement")
            continue
        if static or (limit is not None and measured >= limit):
            row["verdict"], row["runs"] = "unmeasured", []
            row["reason"] = ("stage 2 was not run for this candidate (--static or --limit), so whether "
                             "the test can see the value move is UNMEASURED here")
            continue
        d = _discriminate(SRC / t["module"], t["assign_line"], t["literal"], t["value"], row["test"])
        row["verdict"], row["reason"], row["runs"] = d["verdict"], d["reason"], d["runs"]
        measured += 1
        print(f"  {key:<104} {row['class']:<17} {row['verdict']}")
    by_class = {c: sum(1 for v in cands.values() if v["class"] == c) for c in _SELFREF_CLASSES}
    by_verdict = {v: sum(1 for r in cands.values() if r["verdict"] == v) for v in _SELFREF_VERDICTS}
    if sum(by_class.values()) != len(cands):
        raise AssertionError(f"classes {by_class} sum to {sum(by_class.values())}, not {len(cands)}")
    if sum(by_verdict.values()) != len(cands):
        raise AssertionError(f"verdicts {by_verdict} sum to {sum(by_verdict.values())}, not {len(cands)}")
    # The backlog's own detector, run over the same candidate set so the artefact carries the comparison
    # rather than a claim about it.
    backlog_shape = sorted(k for k, v in cands.items()
                           if any(o["class"] == "both_sides" and o["equality"] for o in v["occurrences"]))
    SELFREF.parent.mkdir(parents=True, exist_ok=True)
    SELFREF.write_text(json.dumps({
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "`unmeasured` is UNMEASURED, never a pass -- a candidate whose constant has no mutation "
                "operator was asked nothing. `cannot_see_it_move` is a measurement handed to a reviewer, "
                "not a conviction: a fixture or a module-level cache holding the pre-mutation value gives "
                "the same signal. See tests/test_selfreferential_assertions.py for the ledger.",
        "n_test_files": len(files), "n_candidates": len(cands),
        "n_tests": len({v["test"] for v in cands.values()}),
        "n_inventory_constants": len(inv), "n_declared_numeric_thresholds": len(declared),
        "n_with_mutation_operator": len(mutatable), "n_measured": measured,
        "by_class": by_class, "by_verdict": by_verdict,
        "backlog_both_sides_equality_shape": backlog_shape,
        "elapsed_s": round(time.time() - t0, 1),
        "candidates": {k: cands[k] for k in sorted(cands)}}, indent=1) + "\n", encoding="utf-8")
    print(f"\n{len(cands)} candidates in {time.time() - t0:.0f}s -> {SELFREF.relative_to(REPO).as_posix()}")
    print("  class:   " + " | ".join(f"{k} {v}" for k, v in by_class.items())
          + f"  = {sum(by_class.values())} of {len(cands)}")
    print("  verdict: " + " | ".join(f"{k} {v}" for k, v in by_verdict.items())
          + f"  = {sum(by_verdict.values())} of {len(cands)}")
    print(f"  M-11's `CONST == CONST` shape matches {len(backlog_shape)} of {len(cands)}: {backlog_shape}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("map", "baseline", "controls", "run", "selfref"))
    ap.add_argument("--only", default=None, help="restrict to one source module, e.g. qc.py")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true",
                    help="baseline: re-time sets that already carry a baseline for their current tests")
    ap.add_argument("--static", action="store_true",
                    help="selfref: classify only, run no mutants (every verdict is then UNMEASURED)")
    a = ap.parse_args(argv)
    if a.cmd == "map":
        build_map()
        return 0
    # Neither the covering-set map nor `.coverage` is an input to `selfref`: it reads the TEST sources and
    # mutates through `thresholds()`, so it must not be gated on an artefact it does not consume.
    if a.cmd == "selfref":
        return selfref(a.limit, a.static)
    if not MAP.is_file():
        sys.exit(f"{MAP} is absent; run `map` first")
    rows = json.loads(MAP.read_text(encoding="utf-8"))
    if a.cmd == "baseline":
        return baseline(rows, a.only, a.force)
    return controls(rows) if a.cmd == "controls" else run(rows, a.only, a.limit)


if __name__ == "__main__":
    os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/*.parquet")
    raise SystemExit(main())
