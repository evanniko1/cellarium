"""S2-2 (structured provenance): a number written with its source is checked against that source exactly.

Before: the integrity check could pair a number with a run only when a sentence named exactly one run, 11 of 140
claims in the recorded answers, so "In wildtype/basal growth was 0.0123, while KO:argS reached 0.0098" with the two
numbers swapped passed. After: Cellwright writes `0.0098 [gene_knockout/KO:argS · growth_rate · 4 seeds]`, and the
check resolves every cited number to a field of the cited run. Whether the model complies with the format is a paid
validation (S2-2b); this pins what the check does with an answer that uses it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import integrity as I  # noqa: E402

TOOL = [json.dumps({"target": "gene_knockout/KO:argS", "reference": "wildtype/basal", "channel": "growth_rate",
                    "target_mean": 0.0098, "reference_mean": 0.0123, "effect_pct": -20.33, "welch_t": -4.12,
                    "n_target": 4, "n_reference": 4})]


def test_a_correct_citation_matches():
    a = "Growth fell to 0.0098 [gene_knockout/KO:argS · growth_rate · 4 seeds]."
    r = I.audit_cited(a, TOOL)
    assert r["format_used"] and [c["status"] for c in r["cited"]] == ["matches"]


def test_a_swap_is_caught_whatever_the_sentence_says():
    # the sentence names both runs, so the prose rule could not pair them; the citations can
    a = ("In wildtype/basal growth was 0.0098 [wildtype/basal · growth_rate · 4 seeds], while KO:argS reached "
         "0.0123 [gene_knockout/KO:argS · growth_rate · 4 seeds].")
    r = I.audit_cited(a, TOOL)
    assert [c["status"] for c in r["cited"]] == ["mismatched", "mismatched"]
    assert r["cited"][0]["found_in"] == ["gene_knockout/KO:argS"]
    assert I.audit(a, TOOL, tool_calls=1)["verdict"] == "faults"


def test_a_comparison_statistic_cites_the_pair():
    a = "The knockout grew 20.33% slower [gene_knockout/KO:argS vs wildtype/basal · growth_rate · effect_pct]."
    assert [c["status"] for c in I.audit_cited(a, TOOL)["cited"]] == ["matches"]


def test_a_cited_run_absent_from_the_output_is_unresolved():
    a = "Ribosomes read 21.4 [gene_knockout/KO:alaS · ribosome_conc · 4 seeds]."
    assert [c["status"] for c in I.audit_cited(a, TOOL)["cited"]] == ["unresolved"]


def test_an_uncited_number_in_a_cited_answer_is_unsourced():
    a = "Growth fell to 0.0098 [gene_knockout/KO:argS · growth_rate · 4 seeds] and ppGpp rose to 81.27 uM."
    r = I.audit_cited(a, TOOL)
    assert r["unsourced"] == ["81.27"]
    assert I.audit(a, TOOL, tool_calls=1)["verdict"] == "faults"


def test_a_computed_number_cites_its_inputs_and_is_not_unsourced():
    a = ("Growth fell to 0.0098 [gene_knockout/KO:argS · growth_rate · 4 seeds], 0.797 of the wild type "
         "[computed: 0.0098 / 0.0123].")
    r = I.audit_cited(a, TOOL)
    assert r["unsourced"] == [] and [c["status"] for c in r["cited"]] == ["matches", "computed"]


def test_counts_seeds_and_small_numbers_are_not_flagged():
    a = "Across 4 seeds and 3 generations growth fell to 0.0098 [gene_knockout/KO:argS · growth_rate · 4 seeds]."
    assert I.audit_cited(a, TOOL)["unsourced"] == []


def test_an_answer_in_the_old_format_is_reported_as_such_not_flagged_number_by_number():
    a = "Growth fell to 0.0098 and ppGpp rose to 81.27 uM."
    r = I.audit_cited(a, TOOL)
    assert r["format_used"] is False and r["unsourced"] == []
    assert I.audit(a, TOOL, tool_calls=1)["verdict"] == "clean"


def test_the_pipe_separator_and_a_percent_unit_parse():
    a = "Effect -20.33% [gene_knockout/KO:argS vs wildtype/basal | growth_rate | effect_pct]."
    assert [c["status"] for c in I.audit_cited(a, TOOL)["cited"]] == ["matches"]


def test_the_annotation_names_a_mismatch_and_an_unsourced_number():
    a = ("In wildtype/basal growth was 0.0098 [wildtype/basal · growth_rate · 4 seeds]; ppGpp rose to 81.27 uM.")
    note = I.annotation(I.audit(a, TOOL, tool_calls=1))
    assert "0.0098" in note and "wildtype/basal" in note and "81.27" in note


def test_the_examples_in_cellwrights_instructions_parse_as_citations():
    # the instruction and the checker must not drift apart: every example the prompt teaches is one the check reads
    from cellarium import agent
    assert "CITE EVERY SIMULATED NUMBER" in agent.SYSTEM
    start = agent.SYSTEM.index("CITE EVERY SIMULATED NUMBER")
    rule = agent.SYSTEM[start:agent.SYSTEM.index("\n", start)]
    examples = [e.strip("`") for e in rule.split("`")[1::2] if "[" in e]
    assert len(examples) == 3
    kinds = []
    for e in examples:
        c = I.citations(e)
        assert len(c) == 1, e
        kinds.append("computed" if "computed" in c[0] else ("pair" if len(c[0]["designs"]) == 2 else "run"))
    assert kinds == ["run", "pair", "computed"]
