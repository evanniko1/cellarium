"""G-1: an inducer's response through a fitted transcription factor is calibrated, not predicted, and arabinose
induction, which the knowledge base fits as a repression, is refused with that reason.

ParCa builds every condition in the knowledge base's condition table from its active factors' fitted fold changes
(`fold_changes.tsv`, with each factor's condition in `tf_condition.tsv`), so a factor's response in its own
condition reproduces an input. For NarL, BaeR and DcuR the fitted sign is the biology's (induction). For AraC it
is not: araA, araB and araD are fitted DOWN in minimal_plus_arabinose. So "does nitrate switch on narGHJI?" is
answered with the label, and "does arabinose switch on araBAD?" is refused naming the fitted repression.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import capability as C  # noqa: E402
from cellarium import gate  # noqa: E402

# The knowledge base's own rows, read from the campaign branch on 2026-11-24 (log2 fold change, mean).
FITTED = {("araC", "araA"): -0.70, ("araC", "araB"): -0.64, ("araC", "araD"): -0.35,
          ("narL", "narG"): 2.75, ("narL", "narH"): 2.80, ("narL", "narI"): 2.75, ("narL", "narJ"): 2.57,
          ("baeR", "mdtA"): 3.39, ("dcuR", "dcuB"): 2.55}
FITTING_CONDITION = {"araC": "minimal_plus_arabinose", "narL": "minimal_plus_nitrate",
                     "baeR": "minimal_plus_indole", "dcuR": "minimal_succinate"}


def _decide(deps, monkeypatch, observable="other", granularity="per_gene"):
    monkeypatch.setattr(gate, "modes_with_runs", lambda: tuple(C.MODES_IN_CORPUS))
    req = gate.Requirement(entity="x", observable=observable, granularity=granularity,
                           regulatory_dependencies=tuple(deps))
    return gate.decide(req, mode=C.DEFAULT_MODE)


def test_arabinose_induction_is_refused_with_the_fitted_repression_as_the_reason(monkeypatch):
    d = _decide(["arabinose_induction"], monkeypatch)
    assert d.verdict == "refuse" and "arabinose_induction_of_the_ara_operon" in d.blocking
    assert "AraC" in d.reason and "repress" in d.reason.lower()
    for gene in ("araA -0.70", "araB -0.64", "araD -0.35"):
        assert gene in d.reason, gene
    assert not d.route, "no elongation model represents it, so the refusal must not name one"


def test_an_induction_through_a_fitted_factor_is_answered_and_labelled_calibrated(monkeypatch):
    d = _decide(["inducer_response"], monkeypatch)
    assert d.verdict == "answer"
    notes = [n for n in d.notes if n.startswith("calibrated, not predicted")]
    assert len(notes) == 1, d.notes
    for s in ("NarL", "narG", "BaeR", "mdtA", "DcuR", "dcuB", "+2.57 to +2.80"):
        assert s in notes[0], s
    # the label names what the fit sets and what it does not
    assert "growth in the condition is simulated" in notes[0].lower()


def test_the_label_is_absent_from_a_question_that_rides_on_no_fitted_factor(monkeypatch):
    d = _decide([], monkeypatch, observable="ppgpp", granularity="aggregate")
    assert not any(n.startswith("calibrated") for n in d.notes)


def test_the_parser_is_told_when_each_new_token_applies():
    enum = gate._PARSE_TOOL["input_schema"]["properties"]["regulatory_dependencies"]["items"]["enum"]
    assert {"inducer_response", "arabinose_induction"} <= set(enum)
    for token in ("inducer_response", "arabinose_induction"):
        assert token in gate._PARSE_SYSTEM, token


def test_the_records_state_the_knowledge_bases_numbers():
    ara = " ".join(C._BY_KEY["arabinose_induction_of_the_ara_operon"].instead.values())
    calibrated = C._BY_KEY["induction_by_a_fitted_transcription_factor"].calibrated
    for (tf, target), fc in FITTED.items():
        text = ara if tf == "araC" else calibrated
        assert target in text, (tf, target)
    for tf, condition in FITTING_CONDITION.items():
        assert condition in (ara if tf == "araC" else calibrated), condition


def _kb_rows(name):
    path = Path(os.environ["WCECOLI_DIR"]) / "reconstruction" / "ecoli" / "flat" / name
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader([line for line in f if not line.startswith("#")], delimiter="\t"))


def test_the_knowledge_base_still_says_what_the_records_cite():
    if not (os.environ.get("WCECOLI_DIR") and os.path.isdir(os.environ["WCECOLI_DIR"])):
        pytest.skip("no model checkout: the records' numbers cannot be re-read from the knowledge base here")
    fc = {(r["TF"], r["Target"]): float(r["log2 FC mean"]) for r in _kb_rows("fold_changes.tsv")}
    for key, value in FITTED.items():
        assert fc.get(key) == value, (key, fc.get(key))
    active = {r["TF"]: r["active nutrients"] for r in _kb_rows("condition/tf_condition.tsv")}
    for tf, condition in FITTING_CONDITION.items():
        assert active.get(tf) == condition, (tf, active.get(tf))
