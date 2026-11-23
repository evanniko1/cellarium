"""An oracle for the gate's decision step: with a perfect parser, would the gate match every key? (ABC T.9)

The Agentic Benchmark Checklist (arXiv:2507.02825, T.9) asks for an automatic oracle that shows each task's
configuration is correct: that the intended answer is reachable at all. For the pre-dispatch gate the decision
step is deterministic, so a perfect PARSER is a constructible oracle: hand `decide()` the canonical requirement of
each cell's capability (the first `(observable, granularity)` row of `gate.REQUIRES` that maps to it), with no
dependency read in, and compare its verdict with the generated key.

MEASURED 2026-11-23 on the 27 cells of the stored 8-framing bank: 26 match. The one that cannot is
`nutrient_shift_timelines` x kinetic, keyed `propose`: kinetic runs exist and none carries a shift, and
`decide()` proposes only when the MODE has no runs (GATE-8b-D). So no parse can score those 8 items, the gate's
ceiling on this bank is 208/216 = 0.963, and of its 27 errors 8 are structural and 19 come from the parser
(the dependency reads of GATE-8b-C). The oracle is what separates the two; before it, both read as "the gate
was wrong".

When GATE-8b-D is fixed the mismatch disappears and the first test fails on purpose: the ceiling then changes,
and every number quoted from it has to be re-derived.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import capability as C  # noqa: E402
from cellarium import gate  # noqa: E402

RUN = REPO / "evals" / "results" / "gate_eval_8framings.json"


def _canonical(cap: str) -> tuple[str, str] | None:
    for (obs, gran), keys in gate.REQUIRES.items():
        if cap in keys:
            return obs, gran
    return None


def oracle(records: list[dict]) -> dict:
    """{(capability, mode): (key, oracle_verdict)} for every cell, with the corpus's own modes holding runs."""
    cells = {}
    for r in records:
        cells.setdefault((r["capability"], r["mode"]), r["required"])
    out = {}
    for (cap, mode), key in sorted(cells.items()):
        canon = _canonical(cap)
        if canon is None:
            out[(cap, mode)] = (key, None)
            continue
        d = gate.decide(gate.Requirement(observable=canon[0], granularity=canon[1], parser="manual"), mode=mode)
        out[(cap, mode)] = (key, d.verdict)
    return out


@pytest.fixture()
def corpus_modes(monkeypatch):
    # The stored run's corpus held steady_state and kinetic runs; pin that, so the oracle does not depend on
    # which corpus this checkout happens to carry.
    monkeypatch.setattr(gate, "modes_with_runs", lambda: tuple(C.MODES_IN_CORPUS))


@pytest.fixture(scope="module")
def recs() -> list[dict]:
    return json.loads(RUN.read_text(encoding="utf-8"))["records"]


def test_a_perfect_parser_matches_26_of_27_cells_and_the_27th_is_gate_8b_d(recs, corpus_modes):
    o = oracle(recs)
    assert len(o) == 27 and all(v[1] is not None for v in o.values())          # every cell has a canonical row
    wrong = {cell: v for cell, v in o.items() if v[0] != v[1]}
    assert wrong == {("nutrient_shift_timelines", "kinetic"): ("propose", "answer")}


def test_the_ceiling_and_the_split_of_the_27_errors(recs, corpus_modes):
    o = oracle(recs)
    per_cell = collections.Counter((r["capability"], r["mode"]) for r in recs)
    ceiling = sum(n for cell, n in per_cell.items() if o[cell][0] == o[cell][1])
    assert (ceiling, len(recs)) == (208, 216)                                   # 0.963
    wrong = [r for r in recs if r["got"] != r["required"]]
    structural = [r for r in wrong if o[(r["capability"], r["mode"])][0] != o[(r["capability"], r["mode"])][1]]
    assert (len(wrong), len(structural), len(wrong) - len(structural)) == (27, 8, 19)


def test_the_oracle_is_not_vacuous(recs, monkeypatch):
    """Forced failure: with the corpus holding no runs at all, every represented cell must flip to `propose`,
    so the oracle has to disagree with every `answer` key. An oracle that matched anyway would be reading the
    keys, not computing verdicts."""
    monkeypatch.setattr(gate, "modes_with_runs", lambda: ())
    o = oracle(recs)
    answer_cells = [cell for cell, (key, _) in o.items() if key == "answer"]
    assert answer_cells and all(o[cell][1] == "propose" for cell in answer_cells)
