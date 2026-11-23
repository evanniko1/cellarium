"""The registry-mutation harness's mechanics, and the shape of its pre-registered plan (validation item 8).

The verdicts themselves are not here: they come from one full-suite run per mutant in a clean worktree, recorded in
data/mutation/registry_results.json. What is pinned here is what must hold for those verdicts to mean anything:
an edit lands exactly once and comes back byte for byte, an edit that would not land refuses to run, and the plan
names a prediction and a reason for every mutant before any result exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import mutate_registry as R  # noqa: E402


@pytest.mark.parametrize("nl", [b"\n", b"\r\n"], ids=["LF", "CRLF"])
def test_a_multi_line_edit_lands_once_and_restores_byte_for_byte(tmp_path, nl):
    p = tmp_path / "m.py"
    src = b"a = 1" + nl + b"b = 2" + nl + b"c = 3" + nl
    p.write_bytes(src)
    orig = R.apply_edit(p, "a = 1\nb = 2", "a = 1\nb = 20")      # the plan writes "\n"; the file keeps its own
    assert p.read_bytes() == b"a = 1" + nl + b"b = 20" + nl + b"c = 3" + nl
    R.restore(p, orig)
    assert p.read_bytes() == src


@pytest.mark.parametrize("body", ["x = 1\n", "y = 2\ny = 2\n"], ids=["absent", "twice"])
def test_an_edit_that_would_not_land_exactly_once_refuses(tmp_path, body):
    p = tmp_path / "m.py"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="not once"):
        R.apply_edit(p, "y = 2", "y = 3")
    assert p.read_text(encoding="utf-8") == body                  # nothing was written


def test_the_plan_predicts_every_mutant_before_any_result_exists():
    plan = json.loads(R.PLAN.read_text(encoding="utf-8"))
    items = plan["controls"] + plan["mutants"]
    assert len({m["id"] for m in items}) == len(items)
    for m in items:
        assert m["prediction"] in ("killed", "survived"), m["id"]
        assert len(m["why"]) >= 40 and m["old"] != m["new"], m["id"]
    classes = {m["class"] for m in plan["mutants"]}
    assert {"widen", "aggregate", "threshold", "provenance", "branch", "reproducibility"} <= classes
    assert {c["prediction"] for c in plan["controls"]} == {"killed", "survived"}   # one control of each kind
    assert set(plan["reproducibility_operators_mapped"]) == {
        "seed count below MIN_SEEDS", "generation window below MIN_GENERATIONS", "dependency pin loosened",
        "split re-creating the twin leak"}
