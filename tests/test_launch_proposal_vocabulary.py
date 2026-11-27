"""What a human approves and what executes must not differ (launch.propose).

Found 2026-11-27 by the first live discovery run (S1): Cellwright proposed five designs and the queue accepted all five
"none blocked", although four could not run as proposed.
  - three `graded_gene_knockout` designs with condition "basal", no gene and a `knockdown_level` parameter that nothing
    reads: `_resolve_ko` resolves plain and multi-gene knockouts only, so a graded design went to the queue with no
    variant index, to fail at launch at best;
  - a `multi_gene_knockout` of relA carrying `co_knockdown: {leuS: 0.5}`, which nothing reads either: it would have run
    as a plain relA knockout while the queue, and the approval, showed a double perturbation.
A parameter is accepted only if Cellarium declares it (manifest.IDENTITY_AXES / NOT_IDENTITY_AXES), and a graded design
is resolved to its gene and level, so the index the model runs is the one the label names.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import launch  # noqa: E402


@pytest.fixture()
def queue(tmp_path, monkeypatch):
    q = tmp_path / "launch_queue.json"
    q.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(launch, "QUEUE", q)
    return q


def _queued(q):
    return json.loads(q.read_text(encoding="utf-8"))


def test_a_parameter_nothing_reads_is_refused_not_queued(queue):
    r = launch.propose("multi_gene_knockout", "basal", params={"target_genes": ["relA"], "co_knockdown": {"leuS": 0.5}})
    assert r["status"] == "unresolved" and "co_knockdown" in r["error"]
    assert "tf_occupancy_clamp" in r["error"]            # the refusal lists what IS accepted
    assert _queued(queue) == []


def test_a_graded_design_is_resolved_to_its_gene_and_level(queue):
    r = launch.propose("graded_gene_knockout", "KO:leuS", params={"level": 4}, elongation_model="kinetic")
    assert r["status"] == "pending_approval", r
    d = _queued(queue)[0]["design"]
    assert d["condition"] == "KO:leuS" and d["params"]["target_genes"] == ["leuS"]
    assert d["params"]["variant_index"] == 2554 and d["params"]["level"] == 4      # leuS ko_index 255, level 4


def test_a_graded_design_named_by_its_target_gene_gets_the_condition_the_runner_reads(queue):
    r = launch.propose("graded_gene_knockout", "basal", params={"target_genes": ["argS"], "level": 3})
    assert r["status"] == "pending_approval", r
    d = _queued(queue)[0]["design"]
    assert d["condition"] == "KO:argS" and d["params"]["variant_index"] == 6443       # the corpus's own argS index


def test_a_graded_design_without_a_gene_is_refused(queue):
    r = launch.propose("graded_gene_knockout", "basal", params={"level": 4})
    assert r["status"] == "unresolved" and "one gene" in r["error"]
    assert _queued(queue) == []


def test_a_graded_design_without_a_level_names_the_levels(queue):
    r = launch.propose("graded_gene_knockout", "KO:leuS", params={"knockdown_level": 0.25})
    assert r["status"] == "unresolved"
    assert "knockdown_level" in r["error"]
    r2 = launch.propose("graded_gene_knockout", "KO:leuS", params={})
    assert r2["status"] == "unresolved" and "4: 0.25" in r2["error"] and "expression" in r2["error"]
    assert _queued(queue) == []


def test_every_declared_parameter_passes_the_vocabulary_check(queue):
    r = launch.propose("wildtype", "acetate", timeline="0 minimal_acetate", params={"initial_condition": "acetate"})
    assert r["status"] in ("pending_approval", "blocked") and "error" not in r
