"""Numbers in prose need a driver — the convention, and the enumeration of where it is implemented.

WHY THIS FILE EXISTS. A quantity stated in a document drifts from the thing it describes, silently, and this
project has the receipts: `M2_UNRESOLVED_REQUIREMENT_RATE` was a literal typed into a scratchpad script and
carried unchanged across two runs that changed what it measured, ending **sixteen points** from its own
declared source. An audit of twelve freshly written benchmark cases found 53 of their 68 recorded values
recomputed by nothing — all 44 that could be re-derived agreed, which is the point: nothing would have
noticed when one stopped agreeing.

CLAUDE.md states the rule. This file does two things for it:

  1. **Drives the corpus counts**, which had no driver at all. `data/hf/CORPUS_COUNTS.json` is a committed
     artifact produced by `scripts/reconcile_corpus_counts.py`, and the Platform Map said of it that "a test
     fails when a document disagrees with it". MEASURED 2026-11-01: `CORPUS_COUNTS` appeared in exactly ONE
     file in the tree — the script that writes it. Nothing read it, no test compared anything against it,
     and the sentence claiming otherwise had been carried in the Map for several versions. It is the Map's
     documented hazard (prose ahead of code) landing on the mechanism that was supposed to prevent exactly
     this. Now the claim is true.

  2. **Enumerates the provenance surfaces**, so losing a completeness assertion is loud. The registries
     below are the implemented instances of the convention; a surface that drops its both-directions check
     stops being a driver and starts being a copy of the numbers it was supposed to guard.

WHAT THIS FILE DOES NOT CLAIM. It does not prove every number in every document has a driver — that would
need to know which numerals in prose are claims, and "369" appears in `README.md` as the volume number of a
*Science* citation. Document claims are therefore PHRASE-anchored and declared one at a time, which is the
same lesson a mutation sweep taught the gate tests on the same day: searching a whole document for a number
is not reading the sentence that claims it.
"""

from __future__ import annotations

import ast
import collections
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/*.parquet")

import pytest  # noqa: E402

ARTIFACT = REPO / "data" / "hf" / "CORPUS_COUNTS.json"


# ------------------------------------------------------------------------------------------------------------
# 1 · The corpus counts, recomputed from the shipped manifest.
# ------------------------------------------------------------------------------------------------------------

def _artifact() -> dict:
    if not ARTIFACT.is_file():
        pytest.skip(f"{ARTIFACT.relative_to(REPO).as_posix()} is not in this tree — the counts it carries "
                    "are uncheckable here, which is not the same as their being wrong")
    doc = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert doc.get("index"), "the artifact parsed but carries no `index` block to check"
    return doc


def _manifest_groups() -> dict:
    """The artifact's `index` block, recomputed from the corpus the package ships."""
    from cellarium import store
    if not store.has_manifest():
        pytest.skip("no local manifest (data/manifest/*.parquet) — the corpus counts have nothing to be "
                    "recomputed against here")
    import duckdb

    from cellarium import manifest
    src = f"read_parquet('{manifest.MANIFEST_DIR.as_posix()}/*.parquet', union_by_name=true)"
    con = duckdb.connect()
    try:
        rows = con.execute(f"SELECT id, qc, perturbation, elongation_model, generations FROM "
                           f"(SELECT * FROM {src} {manifest.DEDUP_QUALIFY})").fetchall()
    finally:
        con.close()
    assert rows, "the manifest is present but empty — a count over zero rows would agree with nothing"
    ids = {r[0] for r in rows}
    return {
        "manifest_rows": len(rows),
        "distinct_run_ids": len(ids),
        "duplicate_rows": len(rows) - len(ids),
        "rows_that_produced_a_generation": sum(1 for r in rows if (r[4] or 0) > 0),
        "total_generations": sum(r[4] or 0 for r in rows),
        "perturbation_families": len({r[2] for r in rows}),
        "qc_verdicts": dict(collections.Counter(r[1] for r in rows)),
        "rows_per_family": dict(collections.Counter(r[2] for r in rows)),
        "rows_per_elongation_model": dict(collections.Counter(r[3] for r in rows)),
    }


def test_the_corpus_counts_artifact_still_matches_the_shipped_manifest():
    """Twenty-five numbers, re-derived from the parquet rather than read back from the file that states them.

    These are the project's most-quoted figures -- 369 rows, 333 runs, 825 generations, the QC spread, the
    per-family and per-mode splits -- and until now the only thing standing behind them was the day the
    script last ran.

    The deposit and local-working-copy halves of the artifact are deliberately NOT checked here: one needs
    the network and an anonymous Hugging Face listing, the other a 212 GB directory this machine may not
    have. A scheduled job re-measures the deposit. Pretending to check them from a tree that cannot see
    them is the shape this whole file exists to remove."""
    art = _artifact()["index"]
    got = _manifest_groups()
    bad = []
    for key, value in got.items():
        recorded = art.get(key, "<<absent>>")
        if isinstance(value, dict):
            same = isinstance(recorded, dict) and dict(sorted(recorded.items())) == dict(sorted(value.items()))
        else:
            same = recorded == value
        if not same:
            bad.append(f"index.{key}: artifact {recorded!r}, recomputed {value!r}")
    assert not bad, (
        "data/hf/CORPUS_COUNTS.json disagrees with the corpus it describes:\n  " + "\n  ".join(bad)
        + "\nRe-run scripts/reconcile_corpus_counts.py, and check every document that quotes the old value.")


# ------------------------------------------------------------------------------------------------------------
# 2 · The documents that quote those counts.
# ------------------------------------------------------------------------------------------------------------

# (document, the exact phrase that makes the claim, path into the artifact, the value the phrase states).
# PHRASE-ANCHORED on purpose. A bare numeral is not a claim: "369" is also the volume of the Science paper
# this repository cites, and a test that searched README.md for "369" would pass on that and call it
# provenance. Each entry is one sentence somebody wrote, checked against one number somebody measured.
DOCUMENT_CLAIMS = [
    ("README.md", "270.0 GB across 131 run", ("published_deposit", "total_gb"), 270.0),
    ("README.md", "270.0 GB across 131 run", ("published_deposit", "n_runs"), 131),
    ("docs/DATASHEET.md", "369 indexed rows", ("index", "manifest_rows"), 369),
]


def test_the_documents_that_quote_the_corpus_counts_agree_with_the_artifact():
    """Each declared sentence must still be in its document, and must still state the measured number.

    Both halves matter. A phrase that has gone means the claim was reworded and this entry now guards
    nothing; a phrase that is present while the artifact moved means a document is quoting a stale
    measurement, which is the failure this file is named for."""
    art = _artifact()
    missing_doc, missing_phrase, disagree = [], [], []
    for doc, phrase, path, stated in DOCUMENT_CLAIMS:
        f = REPO / doc
        if not f.is_file():
            missing_doc.append(doc)
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if phrase not in text:
            missing_phrase.append(f"{doc}: {phrase!r}")
            continue
        value = art
        for k in path:
            value = (value or {}).get(k)
        if value != stated:
            disagree.append(f"{doc} says {phrase!r} (i.e. {stated!r}); the artifact's "
                            f"{'.'.join(path)} is {value!r}")
    assert not missing_doc, f"declared document(s) absent from the tree: {missing_doc}"
    assert not missing_phrase, (
        "a declared claim's phrasing has changed, so the entry guards nothing:\n  "
        + "\n  ".join(missing_phrase) + "\nRe-anchor it on the new wording or drop it.")
    assert not disagree, "a document quotes a number the artifact no longer carries:\n  " + "\n  ".join(disagree)


# ------------------------------------------------------------------------------------------------------------
# 3 · The provenance surfaces, enumerated.
# ------------------------------------------------------------------------------------------------------------

# Where the convention is implemented. `registries` are the classification tables; `completeness` names the
# test asserting every entry is classified, in BOTH directions -- which is the assertion that makes the rest
# worth having, because checking only today's values is what left 53 of 68 undriven while every one of them
# was correct.
PROVENANCE_SURFACES = {
    "capbench case evidence": {
        "module": "tests/test_capbench_cases.py",
        "registries": ["DRIVEN_ELSEWHERE", "HISTORY", "SECOND_PASS", "FIRST_PASS_MEASURED_KEYS"],
        "completeness": ["test_no_measured_value_of_the_second_pass_is_left_unclassified"],
        "recompute": ["test_every_measured_value_of_the_second_pass_is_recomputed_from_its_source"],
    },
    "held-out gate verdicts": {
        "module": "tests/test_holdout.py",
        "registries": ["VERDICT_CLAIMS", "EXPECTED_VERDICT_KIND"],
        "completeness": ["test_the_gates_that_make_CHECKABLE_claims_are_the_ones_covered",
                         "test_every_gate_RECORDS_ITS_VERDICT_and_an_absent_record_cannot_be_silent"],
        "recompute": ["test_every_claim_a_gate_VERDICT_makes_about_this_tree_still_holds",
                      "test_the_prose_COUNTS_are_recomputed_from_the_gates_rather_than_typed"],
    },
    "mcp capability-gate coverage": {
        "module": "tests/test_mcp_capability_gate.py",
        "registries": ["GATED_TOOLS", "TOTAL_TOOLS"],
        "completeness": ["test_how_much_of_the_tool_surface_the_capability_table_covers_is_recorded"],
        "recompute": ["test_how_much_of_the_tool_surface_the_capability_table_covers_is_recorded"],
    },
    "conftest path reliance": {
        "module": "tests/test_env_guards.py",
        "registries": [],
        "completeness": ["test_the_count_of_modules_relying_on_conftest_is_recorded_not_discovered"],
        "recompute": ["test_every_test_module_imports_WITHOUT_another_module_having_moved_sys_path"],
    },
    "corpus counts": {
        "module": "tests/test_number_provenance.py",
        "registries": ["DOCUMENT_CLAIMS"],
        "completeness": ["test_the_documents_that_quote_the_corpus_counts_agree_with_the_artifact"],
        "recompute": ["test_the_corpus_counts_artifact_still_matches_the_shipped_manifest"],
    },
}


def _functions(path: Path) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _module_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            out |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
        elif isinstance(node, ast.FunctionDef):
            out.add(node.name)
    return out


def test_every_provenance_surface_still_has_its_completeness_assertion():
    """The enumeration CLAUDE.md points at, driven.

    For each surface: the module is there, every named registry is a module-level name in it, every named
    test is defined in it, and each completeness test carries AT LEAST TWO assertions -- because a
    both-directions check needs two, and a surface whose check collapsed to one direction has stopped
    noticing half of what it was written for. That is a floor, not a proof of correctness; the surfaces'
    own mutation probes are what establish they fire, and this is the ledger that says they still exist.

    Parsed with `ast` rather than searched as text, so a registry named inside a docstring or a comment does
    not count as present -- the mistake the gate tests made twice on the day they were written."""
    for name, spec in PROVENANCE_SURFACES.items():
        path = REPO / spec["module"]
        assert path.is_file(), f"{name}: {spec['module']} is gone, and with it the driver for those numbers"
        names, funcs = _module_level_names(path), _functions(path)
        for reg in spec["registries"]:
            assert reg in names, (
                f"{name}: {spec['module']} no longer defines `{reg}` at module level. Either the "
                "classification table was renamed -- update this entry -- or it was deleted, in which case "
                "those numbers have no driver.")
        for kind in ("completeness", "recompute"):
            for test in spec[kind]:
                assert test in funcs, (
                    f"{name}: {spec['module']} no longer defines {test}(), which this ledger records as its "
                    f"{kind} check")
        for test in spec["completeness"]:
            n_asserts = sum(1 for n in ast.walk(funcs[test]) if isinstance(n, ast.Assert))
            assert n_asserts >= 2, (
                f"{name}: {test}() carries {n_asserts} assertion(s). A completeness check runs in both "
                "directions -- an entry that is classified but absent, and one present but unclassified -- "
                "so one assertion means half of it is gone.")


def test_the_number_of_provenance_surfaces_is_recorded():
    """A count, so that losing a whole surface is a visible change rather than a quiet one. It may grow --
    that is the intent -- and growing it means editing one number here and saying what joined."""
    assert len(PROVENANCE_SURFACES) == 5, (
        f"{len(PROVENANCE_SURFACES)} provenance surfaces are enumerated, not 5. If one was added, say which; "
        "if one was removed, the numbers it drove are now undriven.")
    assert "corpus counts" in PROVENANCE_SURFACES, (
        "the corpus counts are the instance this file was written for -- they had no driver at all while a "
        "document claimed they did")
