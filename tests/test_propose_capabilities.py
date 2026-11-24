"""K-1: candidate capability records proposed from the simulator's source, scored against the hand-built registry.

The scan reads the elongation models' source and proposes, as a candidate, every attribute that some elongation models
assign and others do not: a mechanism present in some modes only. Nothing is admitted to the registry; a candidate is a
line for a human to read. Scored against the hand-built records that also hold in some modes only, by exact marker:
recall is how many of those records the scan rediscovers, precision how many candidates are some record's marker.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))

import propose_capabilities as K  # noqa: E402

SOURCE = '''
class Base(object):
    def __init__(self, process):
        self.process = process
        self.shared = 1

class Steady(Base):
    def __init__(self, process):
        super().__init__(process)
        self.ppgpp = 0
        self.process.aa_exchange_rates = 0

class Kinetic(Base):
    def __init__(self, process):
        super().__init__(process)
        self.codons_to_trnas = {}

class Coarse(Base):
    pass
'''
MODES = {"steady_state": "Steady", "kinetic": "Kinetic", "coarse_kinetic": "Coarse"}


def test_an_attribute_some_models_assign_and_others_do_not_is_a_candidate():
    cands = K.candidates(SOURCE, MODES)
    assert cands == {"ppgpp": ("steady_state",), "aa_exchange_rates": ("steady_state",),
                     "codons_to_trnas": ("kinetic",)}


def test_an_inherited_attribute_is_shared_and_not_a_candidate():
    assert "shared" not in K.candidates(SOURCE, MODES) and "process" not in K.candidates(SOURCE, MODES)


def test_a_record_is_rediscovered_only_by_an_exact_marker_in_its_own_modes():
    records = [("uptake", ("steady_state",), ("aa_exchange_rates",)),
               ("iso", ("kinetic",), ("codons_to_trnas", "Kinetic")),
               ("stringent", ("steady_state",), ("ppgpp_conc",)),           # near miss: not exact, not found
               ("wrong_modes", ("kinetic",), ("ppgpp",))]                     # exact name, wrong modes
    s = K.score(K.candidates(SOURCE, MODES), records)
    assert s["rediscovered"] == ["iso", "uptake"]
    assert s["missed"] == ["stringent", "wrong_modes"]
    assert (s["n_candidates"], s["candidates_that_are_markers"]) == (3, 2)


def test_the_stored_scan_is_pinned():
    d = json.loads((REPO / "evals" / "results" / "capability_candidates.json").read_text(encoding="utf-8"))
    assert d["admitted"] == 0
    assert (d["score"]["n_reference"], len(d["score"]["rediscovered"])) == (5, d["score"]["n_rediscovered"])


def test_the_checkout_still_gives_the_stored_scan():
    if not (os.environ.get("WCECOLI_DIR") and os.path.isdir(os.environ["WCECOLI_DIR"])):
        pytest.skip("no model checkout: the elongation source cannot be re-read here")
    stored = json.loads((REPO / "evals" / "results" / "capability_candidates.json").read_text(encoding="utf-8"))
    got = K.scan(Path(os.environ["WCECOLI_DIR"]))
    assert got["score"] == stored["score"] and got["by_modes"] == stored["by_modes"]
