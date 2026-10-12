"""Work-plan items 2 and 4e — one predicate per question, and no record counted as verified when nothing ran.

ITEM 2. `capability.answerable_in` folded "a run exists in this mode" into "the model computes this". The gate,
the benchmark generator and the generator's test each needed the two apart and each re-derived the first half
by hand. `represents` (the simulator) and `has_runs_in` (the corpus) are now the two predicates, and
`answerable_in` is derived from them. A hand-written conjunction anywhere else is the drift this replaces.

ITEM 4e. The two declaration-only records carry no marker symbols, so a checkout cannot confirm them — yet the
probe left their `verified` at True and the audit counted them as checked against source.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from cellarium import capability as C
from cellarium import gate

ROOT = Path(__file__).resolve().parents[1]


def test_the_composite_is_exactly_the_two_predicates():
    for c in C.CAPABILITIES:
        for m in C.ELONGATION_MODES:
            assert C.answerable_in(c, m) == (C.represents(c, m) and C.has_runs_in(m)), (c.key, m)
            assert c.default_on == C.answerable_in(c, C.DEFAULT_MODE)


def test_representability_does_not_depend_on_the_corpus(monkeypatch):
    before = {(c.key, m): C.represents(c, m) for c in C.CAPABILITIES for m in C.ELONGATION_MODES}
    monkeypatch.setattr(C, "MODES_IN_CORPUS", ())
    after = {(c.key, m): C.represents(c, m) for c in C.CAPABILITIES for m in C.ELONGATION_MODES}
    assert before == after
    assert not any(C.answerable_in(c, m) for c in C.CAPABILITIES for m in C.ELONGATION_MODES)
    assert gate.modes_with_runs() == ()


def test_the_gate_delegates_rather_than_restating():
    for c in C.CAPABILITIES:
        for m in C.ELONGATION_MODES:
            assert gate.representable(c.key, m) == C.represents(c, m)
    assert gate.representable("not_a_capability", "steady_state") is None
    assert gate.representable(C.CAPABILITIES[0].key, "no_such_mode") is None


def _hand_written_conjunctions(path: Path) -> list[str]:
    """`and` expressions that combine a capability's `holds_in` with `present` or with MODES_IN_CORPUS."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            src = ast.unparse(node)
            if "holds_in" in src and ("MODES_IN_CORPUS" in src or ".present" in src):
                hits.append(f"{path.relative_to(ROOT)}:{node.lineno}: {src}")
    return hits


def test_no_module_outside_the_registry_rederives_a_predicate():
    files = [p for d in ("src", "scripts", "apps") for p in (ROOT / d).rglob("*.py")]
    hits = [h for p in files if p.name != "capability.py" for h in _hand_written_conjunctions(p)]
    assert not hits, "use capability.represents / has_runs_in / answerable_in instead:\n" + "\n".join(hits)


# ------------------------------------------------------------------------------------------- item 4e

def _fake_checkout(tmp_path: Path) -> Path:
    """A checkout that contains every declared marker symbol, so every probeable record agrees."""
    markers = sorted({m for c in C.CAPABILITIES for m in c.markers})
    d = tmp_path / "wc" / "models"
    d.mkdir(parents=True)
    (d / "symbols.py").write_text("\n".join(f"{m} = None" for m in markers), encoding="utf-8")
    return tmp_path / "wc"


def test_declaration_only_records_are_never_counted_as_verified(tmp_path, monkeypatch):
    root = _fake_checkout(tmp_path)
    monkeypatch.setattr(C, "probe_launch_surface", lambda w=None: {"ok": True, "verified": False})
    monkeypatch.setattr(C, "probe_corpus_modes", lambda: {"ok": True, "verified": False})
    res = {r.key: r for r in C.probe(str(root))}
    empty = {c.key for c in C.CAPABILITIES if not c.markers}
    assert empty, "the registry has declaration-only records; this test must exercise them"
    for k in empty:
        assert res[k].verified is False and res[k].basis == "declaration_only", k
    for k in set(res) - empty:
        assert res[k].verified is True and res[k].basis == "markers", k

    a = C.audit(str(root))
    assert set(a["declaration_only"]) == empty
    assert a["n_verified"] == a["n_probeable"] == len(C.CAPABILITIES) - len(empty)
    assert a["verdict"] == "verified_consistent" and a["verified"] is True
    assert a["n_unverified"] == len(empty), "the two are reported as unverified, not hidden"


def test_no_checkout_is_labelled_as_such(monkeypatch):
    monkeypatch.delenv("WCECOLI_DIR", raising=False)
    assert {r.basis for r in C.probe(None)} == {"no_checkout"}
    assert C.audit(None)["verdict"] == "unverified"


@pytest.mark.parametrize("key", [c.key for c in C.CAPABILITIES if not c.markers])
def test_declaration_only_note_says_nothing_was_compared(tmp_path, key):
    r = next(r for r in C.probe(str(_fake_checkout(tmp_path))) if r.key == key)
    assert "nothing was compared" in r.note
