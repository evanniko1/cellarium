"""CRIT (2026-11-26): a shift may not move the replication threshold.

`chromosome_replication.py` re-reads the critical initiation mass from the CURRENT medium's doubling time at every
step, so a shift between media with different doubling times moves it at once while the cell is still the old
medium's: after a downshift it initiates and divides early (well4cell rc2), where the organism pauses. The envelope
refuses launching such a shift, the registry refuses reading one and the question gate refuses asking about one.

Every expectation below is a literal read from the model's tables or measured in the knowledge bases, never the
module's own constant compared with itself.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cellarium import capability, envelope, gate, mcp  # noqa: E402
from cellarium.model import Design  # noqa: E402

KEY = "replication_initiation_after_a_nutrient_shift"


def _check(timeline: str, **kw) -> envelope.EnvelopeVerdict:
    return envelope.check(Design(perturbation=kw.pop("perturbation", "timeline"), timeline=timeline, **kw))


# ---- what is refused ---------------------------------------------------------------------------------------------

def test_oxygen_removal_mid_run_is_refused_with_the_jump_it_causes():
    v = _check("0 minimal, 1200 minimal_minus_oxygen")
    assert not v.in_envelope
    assert "minimal_minus_oxygen (100 minutes)" in v.reason and "975 to 590 fg" in v.reason
    assert "at 1200 s" in v.reason and "drops" in v.reason and "2,238 s" in v.reason
    assert "condition='no_oxygen'" in v.suggestion and "initial_condition='no_oxygen'" in v.suggestion


def test_oxygen_removal_at_t0_from_a_glucose_fitted_cell_is_refused():
    v = _check("0 minimal_minus_oxygen", perturbation="wildtype")
    assert not v.in_envelope and "at t=0 from basal" in v.reason


def test_glucose_removal_is_refused():
    v = _check("0 minimal, 1200 minimal_no_glucose")
    assert not v.in_envelope and "975 to 590 fg" in v.reason and "condition='no_glucose'" in v.suggestion


def test_both_nitrate_shifts_under_anaerobiosis_are_refused():
    """The follow-ups BV-14 invites: oxygen off with nitrate present, and nitrate added to an anaerobic culture."""
    off = _check("0 minimal_plus_nitrate, 1200 minimal_minus_oxygen_plus_nitrate")
    assert not off.in_envelope and "975 to 734.6 fg" in off.reason and "drops" in off.reason
    added = _check("0 minimal_minus_oxygen, 1200 minimal_minus_oxygen_plus_nitrate",
                   params={"initial_condition": "no_oxygen"})
    assert not added.in_envelope and "590 to 734.6 fg" in added.reason and "rises" in added.reason
    assert "grow to the higher threshold" in added.reason


def test_an_upshift_out_of_a_fitted_slow_condition_is_refused():
    """The carbon rule admits it (the switch is INTO glucose); the threshold still jumps, the other way."""
    v = _check("0 minimal_acetate, 1200 minimal", params={"initial_condition": "acetate"})
    assert not v.in_envelope and "423.4 to 975 fg" in v.reason and "rises" in v.reason
    assert "condition='basal'" in v.suggestion


def test_a_tf_activity_variant_with_a_timeline_is_refused_and_without_one_is_not():
    v = envelope.check(Design(perturbation="tf_activity", params={"variant_index": 13}, timeline="0 minimal"))
    assert not v.in_envelope and "sorted TF list" in v.reason
    assert envelope.check(Design(perturbation="tf_activity", params={"variant_index": 13})).in_envelope


# ---- what passes -------------------------------------------------------------------------------------------------

def test_a_cell_started_fitted_to_its_medium_passes():
    """Both readings of the threshold then agree: BV-12's knockouts in fitted acetate, BV-14d's static runs."""
    assert _check("0 minimal_minus_oxygen", perturbation="gene_knockout", condition="KO:cyaA",
                  params={"initial_condition": "no_oxygen"}).in_envelope
    assert _check("0 minimal_minus_oxygen", perturbation="condition", condition="no_oxygen").in_envelope
    assert envelope.check(Design(perturbation="condition", condition="no_oxygen")).in_envelope
    assert envelope.check(Design(perturbation="condition", condition="no_oxygen_plus_nitrate")).in_envelope


def test_shifts_that_stay_on_the_cap_pass():
    """25 and 44 minutes both sit at the 975 fg cap, so the amino-acid shifts and dropouts the corpus ran pass."""
    for tl in ("0 minimal, 1200 minimal_plus_amino_acids",
               "0 minimal_plus_amino_acids, 1200 minimal_aa_minus_leu",
               "0 minimal_GLC_20mM, 1800 minimal_GLC_5mM, 3600 minimal_GLC_2mM",
               "0 minimal, 1200 minimal_plus_nitrate",
               "0 minimal, 1200 minimal_plus_arabinose"):
        assert _check(tl).in_envelope, tl


# ---- the arms do not all agree -----------------------------------------------------------------------------------

def test_phosphate_is_judged_in_every_arm_view():
    """The overlay and the BV-14 fit time phosphate starvation at 100 min; the three older fits at 44. A design must be
    threshold-neutral in both, and the refusal names the view in which it is not."""
    v = _check("0 minimal, 2400 minimal_minus_phosphate")
    assert not v.in_envelope and "975 to 590 fg" in v.reason and "as the fits" not in v.reason
    assert _check("0 minimal_minus_phosphate", params={"initial_condition": "minus_phosphate"}).in_envelope
    older = _check("0 minimal_minus_phosphate, 1200 minimal_no_glucose", params={"initial_condition": "minus_phosphate"})
    assert not older.in_envelope and "(cellarium, refit1, refit2)" in older.reason


def test_the_measured_thresholds_and_views_are_the_ones_read_from_the_knowledge_bases():
    """Measured 2026-11-26 in kb 3b2f8ebd, e491a580, 4965d619, 9055ee3b and 5f19d040 with get_dna_critical_mass."""
    assert envelope.CAP_DOUBLING_TIME_MIN == 44.0
    assert envelope.THRESHOLD_FG == {25.0: 975.0, 44.0: 975.0, 82.0: 734.6, 100.0: 590.0, 136.0: 423.4}
    assert list(envelope.DOUBLING_TIME_VIEWS.values()) == [{}, {"minus_phosphate": 44.0}]


def test_the_overlay_doubling_times_are_what_the_rule_was_written_against():
    """If the condition table changes, this fails, and the rule's measured basis has to be read again."""
    by_condition, by_medium = envelope._doubling_times({})
    assert {m: by_medium[m] for m in ("minimal", "minimal_plus_amino_acids", "minimal_acetate", "minimal_succinate",
                                      "minimal_minus_oxygen", "minimal_no_glucose", "minimal_minus_phosphate",
                                      "minimal_minus_oxygen_plus_nitrate", "minimal_aa_minus_leu")} == {
        "minimal": 44.0, "minimal_plus_amino_acids": 25.0, "minimal_acetate": 136.0, "minimal_succinate": 82.0,
        "minimal_minus_oxygen": 100.0, "minimal_no_glucose": 100.0, "minimal_minus_phosphate": 100.0,
        "minimal_minus_oxygen_plus_nitrate": 82.0, "minimal_aa_minus_leu": 25.0}
    assert by_condition["basal"] == 44.0 and by_condition["no_oxygen_plus_nitrate"] == 82.0


def test_an_unreadable_condition_table_refuses_nothing(monkeypatch):
    """Not checkable is not a refusal: the gate stands in front of every launch."""
    monkeypatch.setattr(envelope, "condition_rows", lambda: None)
    assert envelope.threshold_step(Design(perturbation="timeline", timeline="0 minimal, 1200 minimal_minus_oxygen")) \
        is None


# ---- the runs in flight ------------------------------------------------------------------------------------------

def test_every_design_in_the_committed_plans_passes():
    """BV-12 and BV-14d were planned before the rule. Closing the gap must not refuse a run they hold, or a restart
    of the batch would silently drop part of a pre-registered experiment."""
    n = 0
    for name in ("bv12.json", "bv12_amend1.json", "bv14.json", "bv14d.json"):
        for r in json.loads((ROOT / "evals" / "plans" / name).read_text(encoding="utf-8"))["runs"]:
            v = envelope.check(Design(**r["design"]))
            assert v.in_envelope, f"{name} {r['id']}: {v.reason}"
            n += 1
    assert n >= 154      # 126 + 2 + 12 + 14 when the rule was written


# ---- reading and asking ------------------------------------------------------------------------------------------

def test_the_record_refuses_in_every_mode():
    c = capability.get(KEY)
    assert c is not None and c.holds_in == () and not c.present
    for mode in capability.ELONGATION_MODES:
        assert capability.check(KEY, mode)["can_answer"] is False, mode
    assert "re-reads it at every step" in c.instead_in(capability.DEFAULT_MODE)
    assert "2,251 s" in c.consequence_in(capability.DEFAULT_MODE)


def test_a_read_of_a_threshold_crossing_design_is_refused_and_a_neutral_one_is_not():
    refusal = mcp.capability_precheck("read_series", {"design": "timeline/0 minimal, 1200 minimal_minus_oxygen",
                                                      "channel": "growth_rate"})
    assert refusal is not None and KEY in refusal["capabilities"]
    for neutral in ("timeline/0 minimal, 1200 minimal_plus_amino_acids", "timeline/0 minimal_minus_oxygen#ic:no_oxygen"):
        r = mcp.capability_precheck("read_series", {"design": neutral, "channel": "growth_rate"})
        assert r is None or KEY not in r.get("capabilities", []), neutral


def test_a_knockout_tag_carries_a_hashed_timeline_that_cannot_be_read_back():
    """Documented limit of the read-side check: `#tl:` is a hash. The envelope still refuses LAUNCHING the design."""
    assert envelope.threshold_moves_in_tag("gene_knockout", "KO:cyaA#tl:77fb74") is False
    assert not _check("0 minimal_minus_oxygen", perturbation="gene_knockout", condition="KO:cyaA").in_envelope


def test_the_question_gate_maps_a_cell_cycle_question_after_a_shift_to_the_record():
    assert gate.DEPENDENCY_REQUIRES["cell_cycle_after_a_shift"] == (KEY,)
    enum = gate._PARSE_TOOL["input_schema"]["properties"]["regulatory_dependencies"]["items"]["enum"]
    assert "cell_cycle_after_a_shift" in enum
    assert "cell_cycle_after_a_shift" in gate._PARSE_SYSTEM and "stays constant does not" in gate._PARSE_SYSTEM
