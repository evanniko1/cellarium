"""The gate's held-out question set: frozen before any run, disjoint from the 216, keyed from its requirements.

Two changes to the gate and its benchmark were made after inspecting results on the 216 items, so no clean
figure exists for them. This set is what a clean figure will be computed on. The tests below pin the
properties that make it held out: it cannot change silently after a run, it shares no question with the 216,
and its keys follow from hand-labelled requirements through the registry's own predicates.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from cellarium import capability as C

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "evals" / "HELDOUT_GATE_QUESTIONS.json"
LOCK = ROOT / "evals" / "HELDOUT_GATE_QUESTIONS.sha256"


def _bank() -> dict:
    return json.loads(BANK.read_text(encoding="utf-8"))


def _hash(items) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def test_the_set_still_matches_the_hash_committed_when_it_was_frozen():
    assert _hash(_bank()["items"]) == LOCK.read_text(encoding="utf-8").split()[0], \
        "the held-out set was edited after freezing; create a new versioned set instead"


def test_ids_keys_and_categories_are_well_formed():
    items = _bank()["items"]
    assert len({i["id"] for i in items}) == len(items)
    assert {i["key"] for i in items} <= {"answer", "refuse", "propose"}
    assert {i["key_judgement"] for i in items} <= {"answer", "refuse", "propose"}
    for i in items:
        assert i["mode"] in C.ELONGATION_MODES, i["id"]
        assert all(k in C._BY_KEY for k in i["required_capabilities"]), i["id"]
        assert i["registry_can_express"] == (i["key"] == i["key_judgement"]), i["id"]


def test_keys_follow_from_the_labelled_requirement():
    """Corpus-independent half of the key rule: refuse exactly when some required capability is not represented
    in the item's mode. (Answer versus propose depends on corpus coverage, recorded at freeze time.)"""
    for i in _bank()["items"]:
        caps = [C._BY_KEY[k] for k in i["required_capabilities"]]
        blocked = any(not C.represents(c, i["mode"]) for c in caps)
        assert (i["key"] == "refuse") == blocked, i["id"]


def test_no_question_is_shared_with_the_216_or_with_the_registry_text():
    old = json.loads((ROOT / "evals" / "GATE_QUESTION_BANK.json").read_text(encoding="utf-8"))
    asked = [x["ask"].lower() for x in old["items"]]
    registry_q = [c.question.lower() for c in C.CAPABILITIES]
    for i in _bank()["items"]:
        q = i["question"].lower()
        assert not any(q in a or a in q for a in asked), i["id"]
        assert not any(r in q for r in registry_q), i["id"]


def test_the_set_is_representative_and_includes_the_hard_cases():
    items = _bank()["items"]
    keys = Counter(i["key"] for i in items)
    cats = Counter(i["category"] for i in items)
    assert keys["answer"] >= 20 and keys["refuse"] >= 20 and keys["propose"] >= 5
    for cat in ("supported", "resolution", "representational", "no_corpus_mode", "no_corpus_data",
                "near_neighbour", "compound", "dependency", "undeclared", "registry_gap", "false_premise",
                "pressure"):
        assert cats[cat] >= 2, cat
    assert {i["mode"] for i in items} == set(C.ELONGATION_MODES)
    nn = [i for i in items if i["category"] == "near_neighbour"]
    assert Counter(i["key"] for i in nn) == Counter({"answer": 3, "refuse": 3}), "pairs must flip the verdict"


def test_the_evaluator_refuses_an_edited_set(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import run_gate_eval as ev
    bank = _bank()
    bank["items"][0]["question"] += " (edited)"
    p = tmp_path / "HELDOUT_GATE_QUESTIONS.json"
    p.write_text(json.dumps(bank), encoding="utf-8")
    p.with_suffix(".sha256").write_text(LOCK.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(ev, "HELDOUT", p)
    with pytest.raises(SystemExit):
        ev._heldout_items()
    monkeypatch.setattr(ev, "HELDOUT", BANK)
    assert len(ev._heldout_items()) == len(_bank()["items"])
