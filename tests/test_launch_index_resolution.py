"""A variant that reads its index as a meaning must get the index the design names (launch.propose), and a label must
keep the timeline a condition design carries (manifest._design_tag).

Found 2026-11-27 by the discovery runs' second round of proposals (S2, S4b), after D23:
  - `rrna_operon_knockout` proposals carried `num_operons_to_delete` and no `variant_index`. The runner then uses a
    content hash as the index, and the variant knocks out `index % 6` operons: a random dose under the requested label.
    Indices 7-18 also set the variant's own medium and timeline, which override the run's `--timeline`.
  - a `ppgpp_conc` control can only be named by its multiplier, which nothing resolved to its index either.
  - S2's "clamped control" was proposed as graded level 1, which is expression 0, a full knockout; the level table read
    "1: 0", which reads as "no knockdown".
  - a non-knockout design with a condition and a timeline lost the timeline from its label unless it also set an initial
    condition, so a shifted rRNA knockout would have pooled with the static ones.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import launch, manifest  # noqa: E402
from cellarium.model import Design  # noqa: E402

DOWN = "0 minimal_plus_amino_acids, 1200 minimal"


@pytest.fixture()
def queue(tmp_path, monkeypatch):
    q = tmp_path / "launch_queue.json"
    q.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(launch, "QUEUE", q)
    return q


def _queued(q):
    return json.loads(q.read_text(encoding="utf-8"))


def test_an_rrna_knockout_is_resolved_from_its_operon_count(queue):
    r = launch.propose("rrna_operon_knockout", "basal", timeline=DOWN,
                       params={"num_operons_to_delete": 2, "initial_condition": "with_aa"})
    assert r["status"] in ("pending_approval", "blocked"), r
    d = _queued(queue)[0]["design"]
    assert d["params"]["variant_index"] == 2 and d["condition"] == "minimal|rRNA_KO:2op"


@pytest.mark.parametrize("params", [{}, {"num_operons_to_delete": 7}, {"num_operons_to_delete": 0}])
def test_an_rrna_knockout_without_a_valid_count_is_refused(queue, params):
    r = launch.propose("rrna_operon_knockout", "basal", params=params)
    assert r["status"] == "unresolved" and "1 to 6" in r["error"]
    assert _queued(queue) == []


def test_an_rrna_index_that_sets_its_own_medium_refuses_a_timeline(queue):
    r = launch.propose("rrna_operon_knockout", "basal", timeline=DOWN, params={"variant_index": 8})
    assert r["status"] == "unresolved" and "override" in r["error"]


def test_a_ppgpp_clamp_is_resolved_from_its_multiplier(queue):
    r = launch.propose("ppgpp_conc", "basal", params={"multiplier": 1.0})
    assert r["status"] in ("pending_approval", "blocked"), r
    d = _queued(queue)[0]["design"]
    assert d["params"]["variant_index"] == 4 and d["condition"] == "basal|ppGpp:1x"


def test_a_ppgpp_multiplier_the_variant_does_not_have_is_refused(queue):
    r = launch.propose("ppgpp_conc", "basal", params={"multiplier": 0.5})
    assert r["status"] == "unresolved" and "0.2" in r["error"] and "2" in r["error"]


@pytest.mark.parametrize("perturbation,condition", [("condition", "no_oxygen"), ("tf_activity", "basal")])
def test_an_indexed_family_without_an_index_is_refused(queue, perturbation, condition):
    r = launch.propose(perturbation, condition, params={})
    assert r["status"] == "unresolved" and "variant_index" in r["error"]
    assert _queued(queue) == []


def test_the_wildtype_needs_no_index(queue):
    assert launch.propose("wildtype", "basal")["status"] in ("pending_approval", "blocked")


def test_the_level_table_says_level_one_is_a_full_knockout(queue):
    r = launch.propose("graded_gene_knockout", "KO:argS", params={})
    assert "1: 0 (a full knockout)" in r["error"]


def test_a_condition_designs_timeline_is_part_of_its_label():
    static = Design(perturbation="rrna_operon_knockout", condition="minimal|rRNA_KO:2op",
                    params={"num_operons_to_delete": 2, "variant_index": 2})
    shifted = Design(perturbation="rrna_operon_knockout", condition="minimal|rRNA_KO:2op", timeline=DOWN,
                     params={"num_operons_to_delete": 2, "variant_index": 2})
    assert manifest.design_identity(static) != manifest.design_identity(shifted)
    assert manifest.design_identity(static) == ("rrna_operon_knockout", "minimal|rRNA_KO:2op")   # unchanged


def test_existing_label_shapes_do_not_change():
    assert manifest.design_identity(Design(perturbation="timeline", timeline=DOWN)) == ("timeline", DOWN)
    wt_ic = Design(perturbation="wildtype", condition="acetate", timeline="0 minimal_acetate",
                   params={"initial_condition": "acetate"})
    assert manifest.design_identity(wt_ic)[1] == "acetate#tl:175649#ic:acetate"


def test_an_explicit_rrna_index_still_names_its_dose_in_the_label(queue):
    """S4b's re-proposal passed variant_index itself, so the resolver skipped and left condition "basal": the 2-, 4- and
    6-operon arms would have shared one label and pooled as seeds of one design."""
    labels = set()
    for n in (2, 4, 6):
        r = launch.propose("rrna_operon_knockout", "basal", timeline=DOWN,
                           params={"num_operons_to_delete": n, "variant_index": n, "initial_condition": "with_aa"})
        assert r["status"] in ("pending_approval", "blocked"), r
    for req in _queued(queue):
        d = req["design"]
        assert d["condition"] == f"minimal|rRNA_KO:{d['params']['variant_index']}op"
        labels.add(manifest.design_identity(Design(**d)))
    assert len(labels) == 3


def test_an_rrna_index_that_disagrees_with_its_count_is_refused(queue):
    r = launch.propose("rrna_operon_knockout", "basal", params={"num_operons_to_delete": 2, "variant_index": 4})
    assert r["status"] == "unresolved" and "disagree" in r["error"]


def test_an_explicit_ppgpp_index_still_names_its_multiplier(queue):
    r = launch.propose("ppgpp_conc", "basal", params={"variant_index": 4})
    assert r["status"] in ("pending_approval", "blocked"), r
    d = _queued(queue)[0]["design"]
    assert d["condition"] == "basal|ppGpp:1x" and d["params"]["multiplier"] == 1.0
