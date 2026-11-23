"""A mutation run must leave every file exactly as it found it: byte for byte, line endings included.

FOUND 2026-11-23. Eighteen source files showed as modified with their text identical to the last commit: only
the line endings differed. `scripts/mutate_thresholds.py` read each file as text (which turns CRLF into LF) and
wrote it back as text (which, on Windows, turns every LF into CRLF), so a file came back from a mutation with
different bytes from the ones it went in with. One of the eighteen was last written during the 2026-11-02 tier-0
run. Harmless to the code, but a mutation tool that cannot put a file back exactly is the wrong base for the
registry operators built on it (scripts/mutate_registry.py), and it filled `git status` with changes nobody made.

Red before the fix on Windows, where text mode translates newlines; on Linux the old code happened to round-trip,
which is why CI never saw it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import mutate_thresholds as M  # noqa: E402


@pytest.mark.parametrize("nl", [b"\n", b"\r\n"], ids=["LF", "CRLF"])
def test_a_mutation_and_its_restore_are_byte_exact(tmp_path, nl):
    p = tmp_path / "module.py"
    src = b"X = 20" + nl + b"Y = 3" + nl
    p.write_bytes(src)
    orig = M._apply(p, 1, "20", "21")
    assert p.read_bytes() == b"X = 21" + nl + b"Y = 3" + nl        # mutated, the file's own line endings kept
    M._restore(p, orig)
    assert p.read_bytes() == src


def _text_restores(tree: ast.AST) -> list[int]:
    """`<path>.write_text(orig ...)` -- the pattern that changed the bytes. Restores go through `_restore`."""
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "write_text"
            and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id in ("orig", "original")]


def test_no_restore_writes_text():
    assert _text_restores(ast.parse("path.write_text(orig, encoding='utf-8')")) == [1]          # control
    assert _text_restores(ast.parse("M._restore(path, orig)")) == []
    src = (REPO / "scripts" / "mutate_thresholds.py").read_text(encoding="utf-8")
    assert _text_restores(ast.parse(src)) == []
