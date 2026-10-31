"""Held-out set v2 — authored, keyed by the registry, and NOT frozen. Gate `GATE-8b-HO2`.

WHY A SECOND SET EXISTS AT ALL. The four corrections the first held-out set exposed (GATE-8b A-D) were
every one of them designed with that set's results in view, so v1 can no longer measure them: a fix tailored
to the only documents that could test it is a fix with no evidence. The registered order is to write and
freeze a second set first, with somebody other than the author reviewing a sample of the requirements.

WHAT THIS SUITE IS FOR, and it is not "the keys are right" — a test cannot establish that, which is exactly
why a human reviews a sample. It pins the things that CAN be checked mechanically:

  * the author did not choose the answers: every key is recomputed here from the hand-labelled requirement
    by the registry's predicates, and must match the committed one;
  * each correction is probed in BOTH directions, because a set that only contains cases the fix should
    refuse cannot tell a fix from a blanket refusal;
  * the same question in two or three modes carries keys that move with the MODE and not the wording;
  * and the set cannot be scored until it is frozen, and cannot be frozen without a named reviewer.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

BANK = REPO / "evals" / "HELDOUT_GATE_QUESTIONS_V2.json"
LOCK = REPO / "evals" / "HELDOUT_GATE_QUESTIONS_V2.sha256"
PACKET = REPO / "evals" / "HELDOUT_V2_REVIEW_PACKET.md"


def _builder():
    spec = importlib.util.spec_from_file_location("hb2", REPO / "scripts" / "build_heldout_bank_v2.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hb2"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bank() -> dict:
    return json.loads(BANK.read_text(encoding="utf-8"))


# --- the author did not choose the answers ------------------------------------------------------------

def test_every_KEY_is_RECOMPUTED_from_its_requirement_and_matches(bank):
    """The hand work is the question and WHICH capabilities it needs; the key follows from the registry's
    predicates. If a key in the committed bank disagreed with the recomputation, somebody had typed an
    answer in — which is the one thing the design forbids."""
    b = _builder()
    for item in bank["items"]:
        want = b._key(item["required_capabilities"], item["mode"])
        assert item["key"] == want, f"{item['id']}: committed {item['key']}, registry says {want}"


def test_the_key_rule_is_the_SAME_FUNCTION_v1_used(bank):
    """v1 and v2 have to be keyed by one rule or the comparison between them measures the rule change
    rather than the corrections. Asserted by behaviour over every (capability, mode) pair rather than by
    reading the two files."""
    from cellarium import capability as C
    v1 = importlib.util.spec_from_file_location("hb1", REPO / "scripts" / "build_heldout_bank.py")
    m1 = importlib.util.module_from_spec(v1)
    sys.modules["hb1"] = m1
    v1.loader.exec_module(m1)
    b2 = _builder()
    for cap in C.CAPABILITIES:
        for mode in C.ELONGATION_MODES:
            assert m1._key([cap.key], mode) == b2._key([cap.key], mode), (cap.key, mode)
    assert m1._key([], "steady_state") == b2._key([], "steady_state")


def test_every_requirement_names_a_REAL_capability(bank):
    from cellarium import capability as C
    for item in bank["items"]:
        for key in item["required_capabilities"]:
            assert key in C._BY_KEY, f"{item['id']}: {key}"


# --- both directions, or the set cannot tell a fix from a blanket refusal -----------------------------

@pytest.mark.parametrize("group", ["A", "B", "C", "D"])
def test_each_correction_is_probed_in_BOTH_directions(bank, group):
    """The registered spec asks for this explicitly. A set of cases the fix should refuse would be passed
    by a gate that refused everything -- which is the failure mode of the `per_operon` mapping that fix B
    exists to undo."""
    keys = {i["key"] for i in bank["items"] if i["probes"] == group}
    assert "answer" in keys, f"group {group} has no case the fix must still ANSWER"
    assert keys & {"refuse", "propose"}, f"group {group} has no case the fix must withhold"


def test_the_SAME_QUESTION_in_several_modes_is_keyed_by_the_MODE(bank):
    """Three items carry one sentence verbatim across three modes. If the keys did not differ, the set
    would be testing the wording; if the text differed, the comparison would not be clean."""
    by_q: dict[str, list[dict]] = {}
    for i in bank["items"]:
        by_q.setdefault(i["question"], []).append(i)
    repeated = [v for v in by_q.values() if len(v) > 1]
    assert len(repeated) >= 3, "the set needs several one-sentence, several-mode contrasts"
    for group in repeated:
        assert len({i["mode"] for i in group}) == len(group), "the repeats must be in different modes"
        assert len({i["key"] for i in group}) > 1, (
            f"{[i['id'] for i in group]} is the same sentence in different modes with the same key, so it "
            f"tests nothing about the mode")


def test_the_B_group_puts_the_FOUR_OPERON_CASES_side_by_side(bank):
    """One granularity was covering a named rRNA operon, a multi-transcription-unit gene, a named
    non-rRNA operon and an aggregate rRNA dose. Only the first should be refused, and the set has to show
    all four in one mode or the contrast is not visible."""
    ss = {i["id"]: i for i in bank["items"] if i["probes"] == "B" and i["mode"] == "steady_state"}
    assert ss["V13"]["key"] == "refuse"                       # the named rRNA operon
    assert ss["V14"]["key"] == "answer"                       # a multi-unit gene
    assert ss["V22"]["key"] == "answer"                       # a named operon that is not rRNA
    assert ss["V15"]["key"] == "answer"                       # a count of operons: an aggregate
    assert ss["V15"]["required_capabilities"] == []


def test_the_C_group_carries_the_NEITHER_case(bank):
    """Steady growth in a defined medium implies neither starvation nor supply. Without an item for it the
    set could be passed by a rule that attaches starvation to every minimal-medium question — and minimal
    media are exactly where starvation happens."""
    from cellarium import gate
    assert gate.IMPLIED_DEPENDENCIES["steady_growth_in_a_defined_medium"] == ()
    neither = [i for i in bank["items"]
               if i["probes"] == "C" and i["key"] == "answer" and len(i["required_capabilities"]) == 1]
    assert neither, "no single-requirement steady-growth item in group C"
    assert any("steady growth" in i["question"].lower() or "unperturbed" in i["question"].lower()
               for i in neither)


def test_the_bank_records_the_IMPLIED_DEPENDENCY_RULE_its_keys_were_written_against(bank):
    from cellarium import gate
    assert bank["implied_dependency_rule"] == {k: list(v) for k, v in gate.IMPLIED_DEPENDENCIES.items()}


# --- not frozen, and not scorable until it is --------------------------------------------------------

def test_the_set_is_NOT_FROZEN_and_says_so(bank):
    """Freezing is the human step. While it is unfrozen the bank says `awaiting_review` and carries no
    hash, so nothing can quietly treat it as held out."""
    assert bank["status"] == "awaiting_review"
    assert bank["frozen"] is None
    assert bank["reviewer"] == ""
    assert not LOCK.exists(), "a lock exists: if v2 was frozen, this test and the bank must say so"


def test_the_RUNNER_REFUSES_an_unfrozen_set():
    """THE REFUSAL IS THE POINT. Scoring v2 before it is frozen spends the only documents that can measure
    GATE-8b A-D on a set whose keys are still editable -- the same defect as v1, one level up."""
    import subprocess
    r = subprocess.run([sys.executable, "-I", str(REPO / "scripts" / "run_gate_eval.py"),
                        "--heldout2", "--dry-run"], capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode != 0
    assert "NOT FROZEN" in (r.stdout + r.stderr)


def test_FREEZING_without_a_REVIEWER_is_refused():
    import subprocess
    r = subprocess.run([sys.executable, "-I", str(REPO / "scripts" / "build_heldout_bank_v2.py"),
                        "--freeze"], capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode != 0
    assert "--reviewer" in (r.stdout + r.stderr)


def test_a_FROZEN_set_round_trips_and_an_EDIT_breaks_the_lock(tmp_path):
    """The freeze path exercised for real on a copy, because a mechanism that has never been run is a
    mechanism that will be run for the first time on the day it matters. An edited item must break the
    lock: that is what makes the hash mean anything."""
    b = _builder()
    bank = json.loads(BANK.read_text(encoding="utf-8"))
    lock = b._items_hash(bank)
    assert len(lock) == 64
    bank["items"][0]["question"] += " (edited)"
    assert b._items_hash(bank) != lock
    # And the hash covers the items only, so re-authoring the prose around them keeps a signature valid.
    bank["items"][0]["question"] = bank["items"][0]["question"].replace(" (edited)", "")
    bank["rule"] = "reworded"
    assert b._items_hash(bank) == lock


def test_the_REVIEW_PACKET_asks_about_the_REQUIREMENTS_and_not_the_answers(bank):
    """What a reviewer can check is the hand-labelled requirement; the key follows from it mechanically.
    A packet that asked "is this answer right?" would be asking them to re-derive the registry."""
    text = PACKET.read_text(encoding="utf-8")
    assert "hand-labelled requirement" in text.lower() or "hand-labelled requirement" in text
    assert "which capabilities each question needs" in text
    for hid in bank["review_sample"]:
        assert f"| {hid} |" in text, hid
    assert len(bank["review_sample"]) >= 15, "the registered spec asks for a sample of 15-20"
    assert len(bank["review_sample"]) <= 20


def test_the_review_sample_covers_EVERY_group_and_both_directions(bank):
    """A random 18 of 64 could miss a whole correction, so the sample is chosen rather than drawn."""
    chosen = [i for i in bank["items"] if i["id"] in set(bank["review_sample"])]
    for group in ("A", "B", "C", "D"):
        keys = {i["key"] for i in chosen if i["probes"] == group}
        assert "answer" in keys, f"the sample shows group {group} only in one direction"
        assert keys & {"refuse", "propose"}, f"the sample shows group {group} only in one direction"


# --- the corrections must NOT be implemented yet ------------------------------------------------------

def test_GATE_8b_A_to_D_are_STILL_UNIMPLEMENTED_while_v2_is_unfrozen(bank):
    """THE ORDERING IS THE CLAIM. If a correction lands before v2 is frozen, v2 is no longer able to
    measure it, and this test is what stops that happening quietly. It fails in the useful direction: the
    message says to freeze the set, not to revert the code."""
    from cellarium import gate
    assert bank["status"] == "awaiting_review"
    assert gate.IMPLIED_DEPENDENCIES_STATUS["wired"] is False, (
        "GATE-8b-C is wired while v2 is unfrozen. Freeze v2 first (it is what measures the fix), then "
        "wire it.")
    # B adds a `per_transcription_unit` granularity and an `entity_class`; A adds resolution-implied
    # requirements. Their absence is what "unimplemented" means here, read off the code.
    assert "per_transcription_unit" not in str(gate.REQUIRES), "GATE-8b-B appears implemented"
    assert not hasattr(gate.Requirement(), "entity_class"), "GATE-8b-B appears implemented"


def test_the_v1_set_is_UNTOUCHED(bank):
    """v1 stands as run. v2 does not supersede it, and editing v1 now would rewrite a reported result."""
    import subprocess
    r = subprocess.run([sys.executable, "-I", str(REPO / "scripts" / "build_heldout_bank.py"), "--check"],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "matches its lock" in r.stdout
    assert "supersedes_nothing" in bank


def test_the_markdown_and_the_json_agree_on_the_keys(bank):
    """The document a reader will cite is generated from the bank, so it cannot drift -- but a generated
    file can still be committed stale, which is what this catches."""
    md = (REPO / "evals" / "HELDOUT_GATE_QUESTIONS_V2.md").read_text(encoding="utf-8")
    assert f"{len(bank['items'])} questions" in md
    assert "awaiting_review" in md
    for item in bank["items"]:
        assert f"| {item['id']} |" in md, item["id"]
    assert os.path.getsize(REPO / "evals" / "HELDOUT_GATE_QUESTIONS_V2.md") > 4000
