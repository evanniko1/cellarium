"""evals/discovery_plan.py: an approved proposal becomes batch runs at the approved seeds, and its queue entry says so."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "src"))

import discovery_plan as P  # noqa: E402

from cellarium import launch  # noqa: E402


@pytest.fixture()
def queue(tmp_path, monkeypatch):
    q = tmp_path / "launch_queue.json"
    q.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(launch, "QUEUE", q)
    monkeypatch.setattr(P, "PLANS", tmp_path)
    return q


def test_an_approved_request_runs_at_three_seeds_and_is_marked(queue):
    r = launch.propose("graded_gene_knockout", "KO:argS", params={"level": 4, "ppgpp_clamp": "basal"}, seeds=6,
                       generations=4)
    assert r["status"] == "pending_approval", r
    out = P.build("S2", "kport5f19", [r["request_id"]])
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert [x["seed"] for x in plan["runs"]] == [0, 1, 2] and {x["generations"] for x in plan["runs"]} == {4}
    d = plan["runs"][0]["design"]
    assert d["condition"] == "KO:argS" and d["params"]["variant_index"] == 6444 and d["params"]["ppgpp_clamp"] == "basal"
    assert plan["approved_with"]["proposed_seeds"] == {r["request_id"]: 6} and plan["sim_path"] == "kport5f19"
    q = json.loads(queue.read_text(encoding="utf-8"))
    assert q[0]["status"] == "running" and q[0]["batch"] == "disc_s2" and q[0]["approved_seeds"] == [0, 1, 2]


def test_a_request_not_pending_is_refused(queue):
    r = launch.propose("wildtype", "basal")
    launch.reject(r["request_id"])
    with pytest.raises(SystemExit, match="not pending approval"):
        P.build("S1", "kport5f19", [r["request_id"]])
