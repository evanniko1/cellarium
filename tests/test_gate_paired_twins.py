"""Paired act/abstain scoring on registry-deletion twins (validation-layer item 2).

WHY PAIRED. The gate eval's headline (0.875 on 216 records) is a SINGLE-SIDED accuracy, and V-1 measured what
that is worth: a system that refuses everything scores 0.556 on the same records. Paired scoring removes that
loophole by construction. Each item is a PAIR -- an answerable requirement, and its TWIN with exactly one
required capability deleted from the registry -- and credit is given only when the gate answers the first AND
refuses the second. Always-refuse fails every first member; always-answer fails every twin. Both score 0.

WHAT WAS ALREADY THERE, AND WHAT IS NEW. `evals/capbench_cases.py` holds hand-authored near-neighbour pairs
(C1 granularity, C2 intervention, ...), each differing in one field. They are the expensive half: every pair
is authored and adjudicated by a person, which is CAPBENCH-1's bottleneck. These twins are the cheap half. They
are generated MECHANICALLY by deleting a capability, so they cover every representable cell in the registry
rather than a sample, and they cost nothing to regenerate when the registry changes.

WHAT THIS DOES AND DOES NOT TEST. `gate.decide` consults no model -- the docstring says so and it is by design
-- so a twin built by deleting a capability tests the DECISION layer: does the verdict follow the registry.
It does not test the PARSER that turns a sentence into a requirement; that is what the 216-record eval
measures, at model cost. The two are complementary. A twin is deleted in EVERY mode, because deleting it in one
would let the gate legitimately route the question to another mode that still represents it, and that would be
a correct answer, not a failure.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import capability as C  # noqa: E402
from cellarium import gate  # noqa: E402


def _representable_cells():
    """Every (requirement, mode) the registry says the model can represent, with the keys it needs."""
    out = []
    for (obs, gran), keys in sorted(gate.REQUIRES.items()):
        if not keys:
            continue
        for mode in C.ELONGATION_MODES:
            if all(gate.representable(k, mode) for k in keys):
                out.append((obs, gran, mode, tuple(keys)))
    return out


def _paired(decide_fn, monkeypatch):
    """Score paired act/abstain over every cell. Returns (n_pairs, n_correct, failures)."""
    cells = _representable_cells()
    real = gate.representable
    failures = []
    correct = 0
    for obs, gran, mode, keys in cells:
        req = gate.Requirement(observable=obs, granularity=gran)
        original = decide_fn(req, mode).verdict
        gone = keys[0]
        monkeypatch.setattr(gate, "representable", lambda k, m, _g=gone: False if k == _g else real(k, m))
        twin = decide_fn(req, mode).verdict
        monkeypatch.setattr(gate, "representable", real)
        ok = original != "refuse" and twin == "refuse"
        correct += ok
        if not ok:
            failures.append((obs, gran, mode, gone, original, twin))
    return len(cells), correct, failures


def test_the_registry_has_representable_cells_to_pair():
    """Not vacuous: an empty cell list would make every assertion below hold trivially."""
    cells = _representable_cells()
    assert len(cells) == 16, f"{len(cells)} representable cells; the registry or REQUIRES moved"


def test_the_gate_answers_every_cell_and_refuses_every_deleted_twin(monkeypatch):
    """The real decision layer. Paired accuracy must be 1.0: every answerable cell is accepted, and deleting
    any one of its required capabilities -- in every mode -- turns it into a refusal."""
    n, correct, failures = _paired(gate.decide, monkeypatch)
    assert failures == [], (
        "pairs where the gate did not answer the cell AND refuse its twin "
        "(obs, gran, mode, deleted, original, twin): " + repr(failures))
    assert correct == n == 16


def test_a_gate_that_refuses_everything_scores_zero(monkeypatch):
    """The loophole single-sided accuracy leaves open, closed. On the 216 records always-refuse scores 0.556;
    on paired twins it scores 0, because it never answers a first member."""
    def always_refuse(req, mode):
        return gate.Decision(verdict="refuse", mode=mode, requirement=req)
    n, correct, _ = _paired(always_refuse, monkeypatch)
    assert n == 16 and correct == 0


def test_a_gate_that_answers_everything_scores_zero(monkeypatch):
    """The other degenerate strategy. It answers every first member and every twin, so it fails every pair."""
    def always_answer(req, mode):
        return gate.Decision(verdict="answer", mode=mode, requirement=req)
    n, correct, _ = _paired(always_answer, monkeypatch)
    assert n == 16 and correct == 0


def test_a_gate_that_ignored_the_registry_would_be_caught(monkeypatch):
    """The failure the gate exists to prevent: a decision that does not actually follow the registry. Patch
    `representable` to report everything as present -- deletion then changes nothing -- and the real `decide`
    must fail every pair, because no twin can refuse."""
    monkeypatch.setattr(gate, "representable", lambda k, m: True)

    def decide_blind(req, mode):
        return gate.decide(req, mode)

    cells = _representable_cells()
    blind_failures = 0
    for obs, gran, mode, keys in cells:
        req = gate.Requirement(observable=obs, granularity=gran)
        # with representable() pinned True, "deleting" a capability cannot take effect
        if decide_blind(req, mode).verdict != "refuse":
            blind_failures += 1
    assert blind_failures == len(cells), "a registry-blind gate should fail to refuse every twin"
