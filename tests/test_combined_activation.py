"""COMB-REG (2026-11-27, D18): several activators at one promoter combine additively in the simulation.

`transcript_initiation.py` computes a promoter's synthesis probability as basal(ppGpp) x (1 + sum of effect x bound),
while the fit built each combined condition's expression target by MULTIPLYING the active factors' fold changes
(`fit_sim_data_1.py::buildCombinedConditionCellSpecifications`, under upstream's own TODO that multiplying "might not
be appropriate"). So at a promoter where two activators are bound at once, each one's effect is diluted by the
other's term. BV-14d measured it with occupancies clamped: NarL's nitrate effect at narGHJI is +0.563 log2 with FNR
bound at the fit and +1.439 with FNR held off, against +0.549 and +1.454 from that algebra.

The record HOLDS (the model computes the combination in every elongation mode) and carries a caveat; it never
refuses. Every expectation below is a literal from evals/results/bv14d_clamp.json or the D18 text, never the module's
own constant compared with itself.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cellarium import capability, gate, mcp  # noqa: E402

KEY = "combined_activation_at_a_promoter"
NITRATE_ANAEROBIC = "condition/no_oxygen_plus_nitrate"


def test_the_record_holds_in_every_mode_and_says_how_the_reading_errs():
    c = capability.get(KEY)
    assert c is not None and c.present and c.holds_in == capability.ELONGATION_MODES
    assert capability.check(KEY, "steady_state")["can_answer"] is True
    # the rule and the fit's contrary rule, both named
    assert "1 + sum of effect x bound" in c.caveat and "multiplying" in c.caveat
    # the measured dilution, from the stored BV-14d result, and the algebra's prediction beside it
    assert "+0.56" in c.caveat and "+1.44" in c.caveat and "+0.55" in c.caveat and "+1.45" in c.caveat
    # which way the organism differs (D18's post hoc literature), and what a reader must do
    assert "AND gate" in c.caveat and "Stewart" in c.caveat
    assert "name the co-activators" in c.caveat


def test_the_caveat_quotes_the_stored_result_not_a_retyped_number():
    r = json.loads((ROOT / "evals" / "results" / "bv14d_clamp.json").read_text(encoding="utf-8"))["contrasts"]["narGHJI"]
    c = capability.get(KEY)
    assert f"+{r['NarL_effect_FNR_at_fit']['log2_ratio']:.2f}" in c.caveat
    assert f"+{r['NarL_effect_FNR_off']['log2_ratio']:.2f}" in c.caveat


def test_the_record_cites_the_combination_rule_and_the_fit():
    refs = capability.DEPENDS_ON[KEY]
    assert "models/ecoli/processes/transcript_initiation.py::promoter_init_probs" in refs
    assert "reconstruction/ecoli/dataclasses/process/transcription_regulation.py::get_delta_prob_matrix" in refs
    assert "reconstruction/ecoli/fit_sim_data_1.py::buildCombinedConditionCellSpecifications" in refs


def test_the_gate_answers_a_combined_activation_question_with_the_caveat():
    req = gate.Requirement(entity="narGHJI", intervention="nitrate without oxygen", observable="other",
                           granularity="per_gene", regulatory_dependencies=("combined_activation",))
    d = gate.decide(req, "steady_state")
    assert d.verdict == "answer" and KEY in d.required_capabilities
    caveats = [n for n in d.notes if n.startswith(f"answered with a caveat ({KEY})")]
    assert len(caveats) == 1 and "+1.44" in caveats[0]


def test_the_gate_does_not_attach_the_caveat_to_an_unrelated_question():
    d = gate.decide(gate.Requirement(entity="cell", observable="ppgpp", granularity="aggregate"), "steady_state")
    assert not any(KEY in n for n in d.notes)


def test_the_parser_is_told_about_combined_activation():
    assert gate.DEPENDENCY_REQUIRES["combined_activation"] == (KEY,)
    enum = gate._PARSE_TOOL["input_schema"]["properties"]["regulatory_dependencies"]["items"]["enum"]
    assert "combined_activation" in enum
    desc = gate._PARSE_TOOL["input_schema"]["properties"]["regulatory_dependencies"]["description"]
    assert "combined_activation" in desc
    assert "two or more activators" in gate._PARSE_SYSTEM and "combined_activation" in gate._PARSE_SYSTEM


def test_a_read_of_an_anaerobic_nitrate_design_carries_the_caveat_and_is_never_refused():
    args = {"design": NITRATE_ANAEROBIC, "channel": "growth_rate"}
    pre = mcp.capability_precheck("read_series", args)
    assert pre is None or KEY not in pre.get("capabilities", [])
    note = mcp.capability_note("read_series", args)
    assert note is not None and any("+1.44" in s for s in note["caveats"])
    assert "does_not_hold" not in note          # a caveat is not a failure


def test_a_clamped_design_carries_the_caveat_too():
    clamped = NITRATE_ANAEROBIC + "#occ:FNR-4FE-4S-CPLX=0+PHOSPHO-NARL=fit"
    note = mcp.capability_note("read_series", {"design": clamped, "channel": "growth_rate"})
    assert note is not None and any(KEY in s or "+1.44" in s for s in note["caveats"])


def test_a_read_with_one_activator_condition_carries_no_combination_caveat():
    for design in ("condition/no_oxygen", "condition/plus_nitrate", "wildtype/basal"):
        note = mcp.capability_note("read_series", {"design": design, "channel": "growth_rate"})
        assert note is None or not any("+1.44" in s for s in note.get("caveats", [])), design
