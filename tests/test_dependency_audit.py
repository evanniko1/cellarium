"""Ms-1: what each capability record depends on in the simulator, as references checked against the checkout.

Each reference is a file and a symbol (`path::symbol`), with no line numbers: one record cited `metabolism.py:171-176`,
right for the committed campaign branch and wrong for the audited checkout, whose uncommitted changes moved the block
to line 195. The audit resolves every reference twice: in the checkout Cellarium runs against, and at its committed
revision, so a dependency that exists only in uncommitted changes is named rather than assumed public.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))

import dependency_audit as D  # noqa: E402

from cellarium import capability as C  # noqa: E402


def test_every_record_declares_its_dependencies_or_says_why_it_has_none():
    assert set(C.DEPENDS_ON) == {c.key for c in C.CAPABILITIES}
    empty = {k for k, v in C.DEPENDS_ON.items() if not v}
    assert empty == {"per_gene_trna_abundance"}, empty
    assert C.NO_DEPENDENCY_REASON["per_gene_trna_abundance"]
    for refs in C.DEPENDS_ON.values():
        assert all(r.count("::") == 1 and ":" not in r.split("::")[0][2:] for r in refs), refs   # no line numbers


def test_a_symbol_is_found_as_a_whole_word_only():
    assert D.resolves("x = self.rela\n", "rela") and not D.resolves("relative = 1\n", "rela")
    assert D.resolves('"PHOSPHO-NARL"\t1\n', "PHOSPHO-NARL") and not D.resolves("", "rela")
    assert D.resolves(None, "rela") is None              # no file: unknown, not absent


def test_the_stored_audit_is_pinned():
    d = json.loads((REPO / "evals" / "results" / "dependency_audit.json").read_text(encoding="utf-8"))
    # 2026-11-25: five registry records (BV-G2, BV-AN, BV-OF, BV-EL, BV-CF) added two references each, five of them new
    # symbols, every one resolving at the commit; the stored audit had not been regenerated after the first two.
    # 2026-11-26 (BV-14): fold_changes_nca.tsv::narL and ::fnr, the table whose value the fit uses for a pair both list
    assert (d["n_references"], d["n_unique"]) == (41, 35)
    assert d["resolve_in_checkout"] == 35 and d["resolve_at_commit"] == 28
    assert sorted(d["only_in_uncommitted_changes"]) == sorted([
        "models/ecoli/processes/polypeptide_elongation.py::CoarseKineticTrnaChargingModel",
        "models/ecoli/processes/polypeptide_elongation.py::KineticTrnaChargingModel",
        "models/ecoli/processes/polypeptide_elongation.py::codons_kinetics_model",
        "models/ecoli/processes/polypeptide_elongation.py::codons_to_trnas",
        "models/ecoli/processes/polypeptide_elongation.py::trna_resolution_iso",
        "models/ecoli/processes/polypeptide_elongation.py::zero_charged_holder",
        "models/ecoli/sim/variants/graded_gene_knockout.py::graded_gene_knockout"])


def test_the_checkout_still_gives_the_stored_audit():
    if not (os.environ.get("WCECOLI_DIR") and os.path.isdir(os.environ["WCECOLI_DIR"])):
        pytest.skip("no model checkout: the references cannot be resolved here")
    stored = json.loads((REPO / "evals" / "results" / "dependency_audit.json").read_text(encoding="utf-8"))
    got = D.audit(Path(os.environ["WCECOLI_DIR"]))
    for key in ("n_references", "n_unique", "resolve_in_checkout", "resolve_at_commit", "only_in_uncommitted_changes",
                "missing"):
        assert got[key] == stored[key], key
