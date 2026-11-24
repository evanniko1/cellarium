"""PX-1: an interface-level compatibility check, scored on the gate's question banks against the same keys.

The point of the comparison is the closest concurrent work: PRAXIS-VirtualCell checks, before execution, whether a
request matches what each model DECLARES it accepts. These tests pin the interface table that stands in for such a
check over wcEcoli, and the scoring that compares it with the representability gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "evals"):
    sys.path.insert(0, str(REPO / p))

import interface_only as I  # noqa: E402
import pytest  # noqa: E402

from cellarium import capability as C  # noqa: E402


def test_every_capability_has_an_interface_entry_in_every_mode():
    for cap in C.CAPABILITIES:
        for mode in C.ELONGATION_MODES:
            assert isinstance(I.interface(cap.key, mode), I.Interface), (cap.key, mode)


def test_a_represented_cell_passes_the_interface_too():
    assert I.interface("per_isoacceptor_trna_charging", "kinetic").admits(strict=True)
    assert I.interface("nutrient_shift_timelines", "steady_state").admits(strict=True)


def test_every_unrepresented_cell_says_what_the_interface_sees():
    for cap in C.CAPABILITIES:
        for mode in C.ELONGATION_MODES:
            if mode not in cap.holds_in:
                assert len(I.interface(cap.key, mode).evidence) > 30, (cap.key, mode)


def test_the_steady_state_isoacceptor_question_passes_the_interface_and_not_the_registry():
    cell = I.interface("per_isoacceptor_trna_charging", "steady_state")
    assert cell.admits(strict=True) and cell.admits(strict=False)
    assert "steady_state" not in C.get("per_isoacceptor_trna_charging").holds_in


def test_the_strict_interface_refuses_what_no_column_or_input_can_express():
    assert not I.interface("codon_level_elongation", "steady_state").admits(strict=True)
    assert I.interface("codon_level_elongation", "steady_state").admits(strict=False)
    assert not I.interface("operon_specific_rrna_knockout", "kinetic").admits(strict=True)


def test_a_table_missing_a_cell_is_rejected():
    broken = dict(I.UNREPRESENTED)
    broken.pop(("growth_without_a_carbon_source", "kinetic"))
    with pytest.raises(AssertionError, match="growth_without_a_carbon_source"):
        I.validate(broken)


RECORDS = [
    # keyed refuse, the registry blocks it, the interface sees 86 columns and passes it
    {"id": "a", "mode": "steady_state", "required": "refuse", "got": "refuse",
     "required_capabilities": ["per_isoacceptor_trna_charging"]},
    # keyed answer, represented: both pass
    {"id": "b", "mode": "steady_state", "required": "answer", "got": "answer",
     "required_capabilities": ["per_amino_acid_trna_charging"]},
    # keyed refuse, and the strict interface refuses it too (no per-codon output)
    {"id": "c", "mode": "steady_state", "required": "refuse", "got": "refuse",
     "required_capabilities": ["codon_level_elongation"]},
    # keyed propose: the capability holds in another mode; the interface passes it (it would run)
    {"id": "d", "mode": "steady_state", "required": "propose", "got": "propose",
     "required_capabilities": []},
]


def test_scoring_counts_what_each_check_admits_against_the_key():
    s = I.score(RECORDS)
    assert s["n"] == 4 and s["keyed"] == {"answer": 1, "propose": 1, "refuse": 2}
    loose, strict, gate = s["interface_loose"], s["interface_strict"], s["gate"]
    assert loose["admitted"] == 4 and loose["admitted_keyed_refuse"] == 2 and loose["risk"] == 0.5
    assert strict["admitted"] == 3 and strict["admitted_keyed_refuse"] == 1 and strict["risk"] == round(1 / 3, 3)
    assert gate["admitted"] == 1 and gate["admitted_keyed_refuse"] == 0 and gate["risk"] == 0.0
    assert s["refused_by_gate_admitted_by_interface"]["loose"] == ["a", "c"]
    assert s["refused_by_gate_admitted_by_interface"]["strict"] == ["a"]
