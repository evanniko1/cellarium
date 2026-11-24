"""PX-2: the registry's evidence, graded in states rather than verified-or-declared.

PRAXIS-VirtualCell (arXiv:2609.29221) keeps four evidence states apart and never upgrades one from another. A
capability record makes a claim about the MODEL (what it computes, and what it does instead), so the fourth state is
adapted: a record can be confirmed by simulation (runs that show the model doing what the record says), but none is
scientifically validated in PRAXIS's sense, which would need the organism.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "evals"):
    sys.path.insert(0, str(REPO / p))

import evidence_states as E  # noqa: E402

from cellarium import capability as C  # noqa: E402


def test_every_record_has_all_four_states():
    states = E.states()
    assert set(states) == {c.key for c in C.CAPABILITIES}
    for key, s in states.items():
        assert set(s) == set(E.STATES), key


def test_the_two_benches_are_read_from_the_stored_records():
    s = E.states()
    assert s["per_isoacceptor_trna_charging"]["development"] is True
    assert s["per_isoacceptor_trna_charging"]["external_stress"] is True
    # the three newest records were never put through either bench (checklist R.4)
    for key in ("growth_under_phosphate_depletion", "growth_without_a_carbon_source",
                "response_to_the_glucose_concentration"):
        assert s[key]["development"] is False and s[key]["external_stress"] is False, key


def test_a_record_is_simulation_confirmed_only_with_a_cited_run():
    s = E.states()
    assert s["growth_under_phosphate_depletion"]["simulation_confirmed"].startswith("Appendix B")
    assert s["codon_level_elongation"]["simulation_confirmed"] is False
    for key, v in s.items():
        if v["simulation_confirmed"]:
            assert key in E.SIMULATION_CONFIRMED


def test_technical_follows_the_markers_and_no_state_implies_another():
    s = E.states()
    for c in C.CAPABILITIES:
        assert s[c.key]["technical"] == bool(c.markers), c.key
    # a record in neither bench can still be confirmed by simulation, and the reverse: the states are independent
    assert s["growth_under_phosphate_depletion"]["simulation_confirmed"] and not s[
        "growth_under_phosphate_depletion"]["development"]
    assert s["codon_level_elongation"]["development"] and not s["codon_level_elongation"]["simulation_confirmed"]
