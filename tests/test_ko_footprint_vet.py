"""D33: a knockout's footprint reaches the proposer and the person approving it.

S4b's relA arm was proposed, queued, approved and read back as a relA knockout. It was not one: `gene_knockout`
zeroes ONE transcription unit (ko 1345, relA-mazEF), and relA is also transcribed from its own unit, so RelA stayed
at wildtype level and kept making ppGpp. `scope.ko_footprint('relA')` already predicted it (target_n_tu 2,
target_silenced False), but `vet_hypothesis` attached only the gene's role and benchmark, `propose_experiments`
dropped the vet from its per-design results, and the approval summary never showed it. Advisory only: a footprint
never blocks a run.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import launch, tools, ui  # noqa: E402


def test_a_multi_unit_knockout_names_its_footprint_in_the_vet():
    v = tools.vet_hypothesis("gene_knockout", "basal", params={"variant_index": 1345, "target_genes": ["relA"]},
                             gene="relA")
    fp = v["ko_footprint"]["relA"]
    assert fp["zeroes"] == "relA-mazEF (TU0-14269)"
    assert fp["target_n_tu"] == 2 and fp["target_silenced"] is False
    assert fp["co_members"] == ["mazE", "mazF"]
    # actionable: the variant that covers every unit of the gene's own cistron, and the check to run
    assert "graded_gene_knockout at level 1" in fp["advisory"]
    assert "stay expressed" in fp["advisory"]
    assert v["runnable"] is True, "a footprint is advisory; it must never gate a run"


def test_the_targets_are_read_from_params_when_no_gene_is_named():
    v = tools.vet_hypothesis("gene_knockout", "basal", params={"variant_index": 1345, "target_genes": ["relA"]})
    assert v["ko_footprint"]["relA"]["target_n_tu"] == 2


def test_a_clean_knockout_carries_no_footprint():
    v = tools.vet_hypothesis("gene_knockout", "basal", params={"variant_index": 2042}, gene="argG")
    assert "ko_footprint" not in v


def test_a_non_knockout_design_carries_no_footprint_even_with_target_genes():
    v = tools.vet_hypothesis("wildtype", "basal", params={"target_genes": ["relA"]})
    assert "ko_footprint" not in v


def test_a_single_unit_target_is_silenced_but_its_unit_partners_are_at_risk():
    v = tools.vet_hypothesis("gene_knockout", "basal", gene="spoT")
    fp = v["ko_footprint"]["spoT"]
    assert fp["target_silenced"] is True and fp["target_n_tu"] == 1
    assert "at risk" in fp["advisory"] and "graded_gene_knockout" not in fp["advisory"]
    assert set(fp["co_members"]) == {"recG", "rpoZ", "trmH"}


def test_a_graded_knockdown_covers_the_gene_and_names_only_its_unit_partners():
    v = tools.vet_hypothesis("graded_gene_knockout", "KO:leuS",
                             params={"level": 4, "variant_index": 2554, "target_genes": ["leuS"]}, gene="leuS")
    fp = v["ko_footprint"]["leuS"]
    assert set(fp["co_members"]) == {"cobC", "holA", "lptE", "nadD"}
    assert "every transcription unit of leuS" in fp["advisory"]
    assert "stay expressed" not in fp["advisory"]


def test_propose_experiments_returns_the_footprint_and_the_queue_keeps_it(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    res = tools.propose_experiments(designs=[
        {"perturbation": "gene_knockout", "condition": "basal", "gene": "relA", "seeds": 1, "generations": 1},
        {"perturbation": "gene_knockout", "condition": "basal", "gene": "argG", "seeds": 1, "generations": 1},
    ])
    assert res["queued"] == 2
    by_gene = {r["design"]["gene"]: r for r in res["requests"]}
    assert by_gene["relA"]["ko_footprint"]["relA"]["target_silenced"] is False
    assert "ko_footprint" not in by_gene["argG"]
    q = json.loads((tmp_path / "q.json").read_text())
    rel = next(r for r in q if r["design"]["params"].get("target_genes") == ["relA"])
    assert rel["vet"]["ko_footprint"]["relA"]["target_n_tu"] == 2


def test_the_approval_summary_shows_the_footprint_to_the_person_approving():
    v = tools.vet_hypothesis("gene_knockout", "basal", gene="relA")
    s = ui.vet_summary(v)
    assert "relA" in s["knockout"] and "stay expressed" in s["knockout"]
    clean = ui.vet_summary(tools.vet_hypothesis("gene_knockout", "basal", gene="argG"))
    assert "knockout" not in clean
