"""EXT-PORT-13: the TrnaCharging listener must not need port-only sim_data on the steady-state path.

The defect these tests pin, measured 2026-08-03: `models/ecoli/listeners/trna_charging.py` is registered in
`_listenerClasses` UNCONDITIONALLY, and its `initialize()` read `sim_data.relation.codons` — an attribute
that exists only in a sim_data fitted by this tree's ParCa. A steady-state run writes NONE of the columns
those attributes size (the listener says so itself, in `unwritten_columns`), yet could not START against a
pre-port sim_data. Both fork-era `multi_gene_knockout` baselines died in 6 s with

    AttributeError: 'Relation' object has no attribute 'codons'

on kb_sha256 3b2f8ebd…, the knowledge base behind 279 of the corpus's 322 rows — and wcEcoli's FireWorks
wrapper still exited 0.

These tests run against the OVERLAY SOURCE, not a live simulation, so they need neither Docker nor a
wcEcoli checkout and hold on CI.
"""
import ast
import io
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LISTENER = ROOT / "model_overlay" / "files" / "models" / "ecoli" / "listeners" / "trna_charging.py"
SIMULATION = ROOT / "model_overlay" / "files" / "models" / "ecoli" / "sim" / "simulation.py"
MANIFEST = ROOT / "model_overlay" / "MANIFEST.json"
REL = "models/ecoli/listeners/trna_charging.py"


def _src():
    if not LISTENER.is_file():
        pytest.skip(f"{REL} is not shipped in this overlay")
    return io.open(LISTENER, encoding="utf-8").read()


def _initialize_body():
    tree = ast.parse(_src())
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "TrnaCharging")
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "initialize")


def test_the_listener_is_still_registered_unconditionally():
    """Non-vacuity. If the listener ever becomes conditional, the gate below stops being load-bearing and
    these tests should be re-read rather than silently kept passing."""
    if not SIMULATION.is_file():
        pytest.skip("models/ecoli/sim/simulation.py is not shipped in this overlay")
    src = io.open(SIMULATION, encoding="utf-8").read()
    assert "TrnaCharging," in src, "TrnaCharging is no longer in _listenerClasses — re-read this module"


def test_relation_codons_is_never_read_unguarded():
    """The actual defect: a bare `sim_data.relation.codons` / `.trna_codon_pairs` in initialize()."""
    body = _initialize_body()
    offenders = []
    for node in ast.walk(body):
        if not isinstance(node, ast.Attribute) or node.attr not in ("codons", "trna_codon_pairs"):
            continue
        v = node.value
        # `<anything>.relation.<attr>` or `relation.<attr>` — the unguarded direct read
        base = v.attr if isinstance(v, ast.Attribute) else (v.id if isinstance(v, ast.Name) else None)
        if base == "relation":
            offenders.append((node.lineno, node.attr))
    # A direct read is permitted ONLY inside the kinetic branch, where the attribute is required and an
    # AttributeError is the correct outcome. Locate that branch and allow its lines.
    allowed = set()
    for node in ast.walk(body):
        if isinstance(node, ast.If) and "_kinetic_path" in ast.dump(node.test):
            for sub in ast.walk(node.body[0] if node.body else node):
                allowed.add(getattr(sub, "lineno", None))
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    allowed.add(getattr(sub, "lineno", None))
    bad = [(ln, a) for ln, a in offenders if ln not in allowed]
    assert not bad, (
        f"unguarded relation.<attr> read(s) in TrnaCharging.initialize at lines {bad} — a steady-state run "
        f"cannot start against a pre-port sim_data")


def test_the_steady_state_branch_uses_a_default():
    """The steady-state branch must tolerate a Relation with no codons — that is the whole point."""
    src = _src()
    assert re.search(r"getattr\(\s*relation\s*,\s*['\"]codons['\"]\s*,", src), \
        "no defaulted read of relation.codons — the steady-state path will still raise"
    assert re.search(r"getattr\(\s*relation\s*,\s*['\"]trna_codon_pairs['\"]\s*,", src), \
        "no defaulted read of relation.trna_codon_pairs"


def test_the_kinetic_path_still_raises():
    """A missing attribute on the KINETIC path is a real misconfiguration and must not be defaulted away —
    silently logging zero-width columns for a run that is supposed to write them is the worse failure."""
    body = _initialize_body()
    kin = [n for n in ast.walk(body) if isinstance(n, ast.If) and "_kinetic_path" in ast.dump(n.test)]
    assert kin, "no branch on _kinetic_path in initialize()"
    stmts = [s for n in kin for s in n.body]

    # No 3-argument getattr() on `relation` inside the kinetic branch: a default there would silently turn a
    # misconfigured kinetic run into zero-width columns instead of an error.
    defaulted = [c for s in stmts for c in ast.walk(s)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "getattr"
                 and len(c.args) >= 3
                 and isinstance(c.args[0], ast.Name) and c.args[0].id == "relation"]
    assert not defaulted, "the kinetic branch defaults a relation attribute — it must raise instead"

    # And it must actually read them, so the AttributeError still fires where it should.
    read = {n.attr for s in stmts for n in ast.walk(s)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "relation"}
    assert {"codons", "trna_codon_pairs"} <= read, \
        f"the kinetic branch does not read relation.codons/.trna_codon_pairs directly, got {read}"


def test_the_manifest_records_the_patch_and_matches_the_file():
    """The overlay is harvested from a source checkout and `write_overlay` rmtree's it first, so a
    Cellarium-authored edit survives a rebuild only if it is declared. Assert it is declared AND that the
    declaration matches the bytes actually shipped."""
    import hashlib
    m = json.load(io.open(MANIFEST, encoding="utf-8"))
    rec = next((r for r in m["files"] if r["path"] == REL), None)
    assert rec is not None, f"{REL} is not in the overlay manifest"
    patch = rec.get("cellarium_patch")
    assert patch, "the listener is edited but carries no cellarium_patch block — a rebuild would revert it"
    for k in ("why", "harvested_sha256", "harvested_bytes"):
        assert patch.get(k), f"cellarium_patch is missing {k!r}"
    body = io.open(LISTENER, "rb").read().replace(b"\r\n", b"\n")
    assert hashlib.sha256(body).hexdigest() == rec["overlay_sha256"], \
        "the shipped listener does not match its manifest hash"
    assert rec["overlay_sha256"] != patch["harvested_sha256"], \
        "the patch hash equals the pre-patch hash — the edit is not actually present"


def test_the_builder_carries_declared_patches():
    """The guard itself: scripts/build_model_overlay.py must re-apply declared patches over a fresh
    harvest. Without this the next rebuild reverts the fix with a clean exit code and no output."""
    builder = ROOT / "scripts" / "build_model_overlay.py"
    src = io.open(builder, encoding="utf-8").read()
    assert "def carry_patches(" in src, "build_model_overlay.py has no carry_patches()"
    assert re.search(r"carry_patches\(records,\s*bodies\)", src), "carry_patches() is defined but never called"
    tree = ast.parse(src)
    main = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
    lines = [n.lineno for n in ast.walk(main)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in
             ("harvest", "carry_patches", "write_overlay")]
    order = [n.func.id for n in ast.walk(main)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in
             ("harvest", "carry_patches", "write_overlay")]
    seq = [o for _, o in sorted(zip(lines, order))]
    assert seq[:2] == ["harvest", "carry_patches"], \
        f"carry_patches must run immediately after harvest, got {seq}"
