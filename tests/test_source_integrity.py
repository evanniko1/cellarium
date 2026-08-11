"""No source file carries a FLATTENED line-continuation — the damage class programmatic patching leaves behind.

WHY THIS EXISTS. Several modules in this tree were edited by scripts doing `source.replace(old, new)`. That is
a silent tool in two ways, and both happened:

  * `str.replace` with a non-matching anchor **does nothing and raises nothing**, so an edit can report success
    while changing not one byte;
  * a replacement written in an escaped string can lose a `\\` line-continuation, joining two physical lines
    into one with the indentation preserved as a run of spaces mid-statement.

The second leaves valid, importable, ruff-clean Python — `E501` is deliberately OFF here because the codebase
uses long single-line tool-description strings (the longest real line is ~1,960 characters), so line length
cannot be the guard. The file parses, the tests pass, and the only trace is a 20-space gap inside an `if`.

TWO were introduced. The first was found by accident when a later patch anchor failed to match it. The second
— in `hygiene._docstring_nodes` — was found only when this check was written, having survived a full-repo
sweep for the same class that used a cruder pattern. That is the argument for a test rather than a habit.

HOW IT DISTINGUISHES DAMAGE FROM STYLE. Detection is over TOKENS, not text, so strings and comments are
excluded by construction — an aligned trailing comment is not a hit. Genuine alignment inside code (a dict
literal lining its values up, a ternary) uses gaps of ~8-13 spaces; a flattened continuation leaves the whole
original indent, which here was 21. The threshold sits above the alignment band and is asserted with its
reasoning rather than tuned until green.
"""
import io
import tokenize
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Above the alignment band (dict/ternary alignment runs to ~13 here), below any plausible flattened indent.
_GAP = 16

_SKIP = {tokenize.STRING, tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
         tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}


def _suspicious_gaps(path: Path) -> list[str]:
    with io.open(path, "rb") as fh:
        toks = list(tokenize.tokenize(fh.readline))
    out, prev = [], None
    for t in toks:
        if t.type in _SKIP:
            prev = t
            continue
        if prev is not None and prev.end[0] == t.start[0] and prev.type not in _SKIP:
            gap = t.start[1] - prev.end[1]
            if gap >= _GAP:
                out.append(f"{path.name}:{t.start[0]} — {prev.string!r} <{gap} spaces> {t.string!r}")
        prev = t
    return out


def _sources() -> list[Path]:
    dirs = [REPO / "src" / "cellarium", REPO / "apps", REPO / "scripts", REPO / "evals", REPO / "tests"]
    return sorted(p for d in dirs if d.is_dir() for p in d.rglob("*.py"))


def test_no_source_file_carries_a_flattened_line_continuation():
    """The whole point: this damage is invisible to the interpreter, to ruff, and to the test suite."""
    hits = [h for p in _sources() for h in _suspicious_gaps(p)]
    assert not hits, (
        "a line-continuation looks flattened (a run of spaces mid-statement, outside strings and comments) — "
        "this is what `source.replace()` patching leaves behind:\n  " + "\n  ".join(hits))


def test_every_source_file_still_parses():
    """The other half of the same hazard: a bad replacement can produce a file that does not compile, and if
    nothing imports it, nothing notices."""
    import ast
    broken = []
    for p in _sources():
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            broken.append(f"{p.name}:{exc.lineno}: {exc.msg}")
    assert not broken, broken


def test_the_detector_would_actually_catch_one(tmp_path):
    """Injection, in-line: the guard is worthless if the threshold drifted above the damage it looks for."""
    good = tmp_path / "good.py"
    good.write_text("x = (1 and\n     2)\n", encoding="utf-8")
    assert not _suspicious_gaps(good)

    flat = tmp_path / "flat.py"
    flat.write_text("x = (1" + " " * 21 + "and 2)\n", encoding="utf-8")
    assert _suspicious_gaps(flat), f"a {_GAP}+ space mid-statement gap was not flagged"


def test_alignment_is_not_reported_as_damage():
    """The false positive that would get this switched off. Dict-literal and ternary alignment in this tree
    runs to about 13 spaces; the threshold has to sit above that band, not at it."""
    from src.cellarium import instrument  # noqa: F401  — a module that aligns dict values deliberately
    assert not _suspicious_gaps(REPO / "src" / "cellarium" / "instrument.py")


@pytest.mark.parametrize("name", ["hygiene.py", "manifest.py", "trna.py", "rigor.py", "reconcile.py"])
def test_the_modules_edited_programmatically_are_clean(name):
    """Named explicitly. These are the files this session patched with string replacement, and two of them
    carried this exact damage."""
    p = REPO / "src" / "cellarium" / name
    if not p.exists():
        pytest.skip(f"{name} not present")
    assert not _suspicious_gaps(p)
