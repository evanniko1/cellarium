"""A skip-guard must read the SAME object as the code it guards. This finds the ones that do not.

THE DEFECT THIS CATCHES, twice measured. `runner.py` and `reader.py` capture their environment at import:

    WCECOLI_DOCKER = os.environ.get("WCECOLI_DOCKER", "")     # runner.py:27

A test then guards on the environment instead:

    if not os.environ.get("WCECOLI_DOCKER"):
        pytest.skip("needs the model image")

Those agree only if the variable is already exported when `runner` is first imported. It is not: anything in
the suite that imports `apps/server.py` calls `load_dotenv()`, which fills the variable in AFTER the constant
has frozen an empty string. The guard then passes and the guarded call raises. Green alone, red in the full
suite, for a reason belonging to neither test — and INVISIBLE TO CI, which has no model image and therefore
skips every one of these guards on every run. This is exactly the class CI cannot see, which is why it needs
a static check rather than another job.

WHAT IT REPORTS, and the two grades:

  * **DIVERGENCE (an error).** A test reads `os.environ` for a variable that a `src/cellarium` module has
    frozen into a module-level constant, AND the same test file touches that module. Those two reads can
    disagree, and the test is the one that will lie about it.
  * **NOTE (not an error).** A test reads such a variable but never touches the module that froze it. The
    read is honest — there is no second object to disagree with — but it is listed so the pattern stays
    visible if that file later grows an import.

It deliberately does NOT flag `os.environ` reads inside `src/`: a module re-reading its own variable at call
time is the FIX for this defect, not an instance of it.

    python scripts/check_env_guards.py            # exit 1 on any divergence
    python scripts/check_env_guards.py --list     # print everything found, including notes
"""

from __future__ import annotations

import argparse
import ast
import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "cellarium"
TESTS = REPO / "tests"

# Guards that read the environment for a variable NO module freezes are fine, and so are these: they select
# behaviour rather than gating a call into a module that froze the same value.
EXEMPT_VARS = {
    "CELLARIUM_MODEL",           # which model to call; the caller passes it explicitly everywhere that matters
    "CELLARIUM_SUMMARY_MODEL",
}


def _module_env_constants() -> dict[str, list[tuple[str, str]]]:
    """`{env var: [(module, CONSTANT), …]}` for MODULE-LEVEL captures only.

    Module level is the whole point: a capture inside a function re-reads on every call and cannot go stale.
    """
    frozen: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for p in sorted(SRC.glob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            var = _env_var_of(node.value)
            if var is None:
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    frozen[var].append((p.stem, tgt.id))
    return dict(frozen)


def _env_var_of(node) -> str | None:
    """The env var name read by `os.environ.get("X")`, `os.getenv("X")` or `os.environ["X"]`, else None."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
        base, fn = node.func.value, node.func.attr
        is_env_get = fn == "get" and isinstance(base, ast.Attribute) and base.attr == "environ"
        if (is_env_get or fn == "getenv") and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            return node.args[0].value
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
            and node.value.attr == "environ" and isinstance(node.slice, ast.Constant) \
            and isinstance(node.slice.value, str):
        return node.slice.value
    return None


def _modules_touched(tree: ast.AST) -> tuple[set[str], set[str]]:
    """`(directly imported, reachable transitively)` cellarium modules for this test file.

    THE SPLIT IS DELIBERATE AND IT COST A REWRITE. The first version expanded any import of `tools` into
    "reaches reader and runner", because `tools.dispatch` transitively does. That flagged
    `test_capability.py` and `test_operon_mode.py`, and BOTH were false: `capability.probe` reads
    `os.environ.get("WCECOLI_DIR")` at CALL time (`capability.py:729`), so the guard and the guarded code
    read the same live value and cannot disagree. A check whose first output contains two wrong answers is a
    check that gets switched off — the same argument `reconcile.NOT_A_MEASUREMENT` makes for being explicit
    rather than heuristic. So a DIRECT import is an error and transitive reach is only a note.
    """
    direct: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("cellarium"):
            direct |= {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            for a in node.names:
                if "cellarium" in a.name:
                    direct.add(a.name.rsplit(".", 1)[-1])
    transitive = set(direct)
    if direct & {"tools", "launch", "provenance", "generate", "manifest"}:
        transitive |= {"runner", "reader"}
    return direct, transitive


def scan() -> dict:
    frozen = _module_env_constants()
    divergences, notes = [], []
    seen: set[tuple] = set()          # one line reading the same var twice is ONE site, not two
    for p in sorted(TESTS.glob("*.py")):
        text = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        direct, transitive = _modules_touched(tree)
        for node in ast.walk(tree):
            var = _env_var_of(node)
            if var is None or var in EXEMPT_VARS or var not in frozen:
                continue
            holders = {m for m, _ in frozen[var]}
            line = getattr(node, "lineno", 0)
            if (p.name, line, var) in seen:
                continue
            seen.add((p.name, line, var))
            rec = {"file": f"tests/{p.name}", "line": line, "var": var,
                   "frozen_in": [f"{m}.{c}" for m, c in frozen[var]],
                   "reach": "direct" if holders & direct else
                            "transitive" if holders & transitive else "none"}
            (divergences if rec["reach"] == "direct" else notes).append(rec)
    return {"frozen_constants": {k: [f"{m}.{c}" for m, c in v] for k, v in sorted(frozen.items())},
            "divergences": divergences, "notes": notes, "gated_files": gated_files(frozen)}


def gated_files(frozen: dict[str, list[tuple[str, str]]] | None = None) -> list[str]:
    """Test files that gate themselves on the model environment BY ANY ROUTE.

    Separate from `divergences` on purpose, and the separation is the whole point of the census. Fixing a
    guard to read `runner.WCECOLI_DOCKER` removes a DIVERGENCE but changes nothing about what CI exercises —
    the test still skips there. A census built from divergences alone would have reported the blind spot
    SHRINKING at the exact moment the guards were made correct, which is backwards. So this counts both
    spellings: the environment read and the module constant.
    """
    frozen = frozen if frozen is not None else _module_env_constants()
    model_vars = {v for v in frozen if v.startswith("WCECOLI")}
    model_consts = {c for v in model_vars for _, c in frozen[v]}
    out: set[str] = set()
    for p in sorted(TESTS.glob("*.py")):
        if p.name == "conftest.py":
            continue                     # the loader, not a gated test
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if _env_var_of(node) in model_vars:
                out.add(f"tests/{p.name}")
                break
            if isinstance(node, ast.Attribute) and node.attr in model_consts \
                    and isinstance(node.value, ast.Name) and node.value.id in ("reader", "runner"):
                out.add(f"tests/{p.name}")
                break
    return sorted(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="print notes too, not only divergences")
    args = ap.parse_args(argv)

    res = scan()
    if args.list:
        print(f"{len(res['frozen_constants'])} module-level env constant(s) in src/cellarium:")
        for var, where in res["frozen_constants"].items():
            print(f"  {var:26} {', '.join(where)}")
        print()
        for n in res["notes"]:
            why = ("reaches it only through another module, which may read the environment live"
                   if n["reach"] == "transitive" else "does not import the module that froze it")
            print(f"note  {n['file']}:{n['line']}  reads os.environ[{n['var']}] "
                  f"(frozen in {', '.join(n['frozen_in'])}) — {why}")
        print()
    for d in res["divergences"]:
        print(f"DIVERGENCE  {d['file']}:{d['line']}  guards on os.environ[{d['var']}] while the code it "
              f"reaches uses {', '.join(d['frozen_in'])} — read the constant instead")
    if res["divergences"]:
        print(f"\n{len(res['divergences'])} guard(s) read a different object from the code they guard.")
        return 1
    print(f"env guards OK — {len(res['frozen_constants'])} frozen constant(s), 0 divergences, "
          f"{len(res['notes'])} note(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
