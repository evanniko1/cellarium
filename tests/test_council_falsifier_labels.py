"""D-1b: a falsifier's target and reference must name designs the hypothesis proposes, checked when proposed.

D-1 (2026-11-24) ranked the Council's stored hypotheses by how many rivals each run tests and found falsifiers naming
designs that do not exist: `gene_knockout/basal` (a knockout that names no gene) and
`timeline/glucose_to_acetate_shift` (prose where a design label belongs). Nothing checked the label against the
candidate designs, so such a hypothesis could converge with a falsifier no run can execute. The check uses only the
hypothesis's own candidate designs and the instrument's reference design: the Council stays blind to the corpus.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import council  # noqa: E402


def _cand(target, reference="wildtype/basal", designs=None):
    return {"falsifier": {"target": target, "reference": reference, "channel": "growth_rate"},
            "candidate_designs": designs if designs is not None else
            [{"perturbation": "gene_knockout", "condition": "KO:argS", "params": {"variant_index": 644}}]}


def test_a_label_that_names_a_candidate_design_passes():
    c = _cand("gene_knockout/KO:argS")
    assert council.falsifier_label_issues(c) == ([], [])


def test_a_knockout_proposed_with_its_genes_in_params_answers_to_its_ko_label():
    c = _cand("gene_knockout/KO:relA",
              designs=[{"perturbation": "gene_knockout", "condition": "basal", "params": {"target_genes": ["relA"]}}])
    assert council.falsifier_label_issues(c) == ([], [])


def test_the_reference_design_is_always_valid():
    c = _cand("gene_knockout/KO:argS", reference="wildtype/basal")
    assert council.falsifier_label_issues(c)[1] == []


def test_a_knockout_naming_no_gene_is_repaired_to_the_one_knockout_proposed():
    c = _cand("gene_knockout/basal")
    repairs, issues = council.falsifier_label_issues(c)
    assert issues == [] and c["falsifier"]["target"] == "gene_knockout/KO:argS"
    assert repairs and "gene_knockout/basal" in repairs[0]


def test_prose_with_no_matching_family_is_an_objection_not_a_guess():
    c = _cand("timeline/glucose_to_acetate_shift")
    repairs, issues = council.falsifier_label_issues(c)
    assert repairs == [] and len(issues) == 1 and "timeline/glucose_to_acetate_shift" in issues[0]
    assert c["falsifier"]["target"] == "timeline/glucose_to_acetate_shift"        # left as proposed


def test_a_family_match_that_changes_the_meaning_is_not_repaired():
    # measured on the recorded hypotheses: the family rule would have read rich amino acids as acetate
    c = _cand("condition/rich_amino_acids", designs=[{"perturbation": "condition", "condition": "acetate"}])
    repairs, issues = council.falsifier_label_issues(c)
    assert repairs == [] and len(issues) == 1 and c["falsifier"]["target"] == "condition/rich_amino_acids"


def test_prose_naming_a_gene_is_not_read_as_a_placeholder():
    # measured: `gene_knockout/relA_shift` names relA in prose; the code does not interpret prose
    repairs, issues = council.falsifier_label_issues(_cand("gene_knockout/relA_shift"))
    assert repairs == [] and len(issues) == 1


def test_a_knockout_candidate_naming_no_gene_is_not_a_design():
    c = _cand("gene_knockout/minimal", designs=[{"perturbation": "gene_knockout", "condition": "minimal"}])
    repairs, issues = council.falsifier_label_issues(c)
    assert repairs == [] and len(issues) == 1


def test_two_candidates_of_the_family_make_the_repair_ambiguous_so_it_objects():
    two = [{"perturbation": "gene_knockout", "condition": "KO:argS"},
           {"perturbation": "gene_knockout", "condition": "KO:alaS"}]
    repairs, issues = council.falsifier_label_issues(_cand("gene_knockout/basal", designs=two))
    assert repairs == [] and len(issues) == 1


def test_a_timeline_candidate_is_named_by_its_timeline():
    tl = [{"perturbation": "timeline", "timeline": "0 minimal, 1200 minimal_plus_amino_acids"}]
    c = _cand("timeline/0 minimal, 1200 minimal_plus_amino_acids", designs=tl)
    assert council.falsifier_label_issues(c) == ([], [])


def test_an_unrepaired_label_blocks_convergence_in_the_debate():
    sys.path.insert(0, os.path.dirname(__file__))
    from test_council import FakeClient, _candidate, _verdict
    bad = _candidate(falsifier={"target": "timeline/glucose_to_acetate_shift", "reference": "wildtype/basal",
                                "channel": "protein_mass", "decision_rule": "reject H0 if welch_t >= 2",
                                "refuting_result": "welch_t < 2"})
    good = _candidate()
    client = FakeClient({"propose_hypothesis": [bad, good],
                         "raise_objections": [{"objections": []}, {"objections": []}],
                         "rule": [_verdict(), _verdict()]})
    h = council.deliberate("q", client=client, max_rounds=2)
    assert h.converged and h.rounds_used == 2, "converged on a falsifier naming no design"
    led = [o for o in h.objection_ledger if o.get("deterministic")]
    assert led and led[0]["resolved_round"] == 2
