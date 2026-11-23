"""Validation-layer item 9, step 1: a right number credited to the wrong run, against two kinds of check.

The synthetic transcripts are the decisive part: two runs with distinct readings, an answer that credits each
correctly, and the same answer with the runs swapped. A POOLED check (every number and label appears somewhere in
the tool output) passes both, by construction. A ROUTED check (the number sits in a record naming its run) catches
the swap when the runs come back in separate records, and cannot when one comparison record names both -- which
is what most of the 40 surviving real swaps look like. Artefact numbers are LITERALS from 2026-11-23.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))

import attribution_swap as S  # noqa: E402

WT, KO = "wildtype/basal", "gene_knockout/KO:argS"
SEPARATE = [json.dumps({"design": WT, "growth_rate": 0.01231}), json.dumps({"design": KO, "growth_rate": 0.00978})]
TOGETHER = [json.dumps({"reference": WT, "target": KO, "ref_mean": 0.01231, "target_mean": 0.00978})]
ANSWER = f"In {WT} growth was 0.0123 per minute, while {KO} reached 0.0098 per minute."


def test_rounding_follows_the_answers_own_precision():
    assert S.number_in("12.3", "x 12.2961 y") and S.number_in("12%", '{"f": 0.1204}')
    assert not S.number_in("12.4", "x 12.2961 y")


def test_each_number_is_credited_to_the_nearest_label_before_it():
    assert S.claims(ANSWER) == [(WT, "0.0123"), (KO, "0.0098")]
    assert S.claims(f"Three runs: {WT} had 4 seeds.") == []        # single digits are counts, not readings


def test_a_pooled_check_cannot_see_a_swap_and_a_routed_one_can_when_runs_come_back_separately():
    swapped = S.swap(ANSWER, WT, KO)
    assert S.claims(swapped) == [(KO, "0.0123"), (WT, "0.0098")]
    assert S.pooled_ok(ANSWER, SEPARATE) and S.pooled_ok(swapped, SEPARATE)          # blind by construction
    recs = S.records(SEPARATE)
    assert all(S.routed_ok(lab, n, recs) for lab, n in S.claims(ANSWER))
    assert not any(S.routed_ok(lab, n, recs) for lab, n in S.claims(swapped))         # both swaps caught
    r = S.measure([{"answer": ANSWER, "tool_texts": SEPARATE}])
    assert r["pooled_check_detected_swaps"] == 0 and r["routed"]["detected"] == 2


def test_a_record_level_routed_check_is_blind_when_one_record_names_both_runs():
    """The limitation, pinned: a comparison record carries both labels and both numbers, so routing by record
    cannot tell which number is whose. Routing has to reach the FIELD (`ref_mean` belongs to `reference`)."""
    r = S.measure([{"answer": ANSWER, "tool_texts": TOGETHER}])
    assert r["routed"]["detected"] == 0 and r["routed"]["supported_before_and_after"] == 2


@pytest.fixture(scope="module")
def stored() -> dict:
    return json.loads(S.OUT.read_text(encoding="utf-8"))


def test_the_stored_measurement_says_what_the_2026_11_23_run_found(stored):
    assert (stored["answers"], stored["claims"], stored["exposed_answers"]) == (60, 140, 11)
    assert stored["pooled_check_detected_swaps"] == 0
    assert stored["routed"] == {"original_supported": 100, "original_claims": 140, "swapped_claims": 62,
                                "detected": 10, "supported_before_and_after": 40}
    assert set(stored) <= {"answers", "claims", "exposed_answers", "pooled_check_detected_swaps", "routed",
                           "source", "computed_utc"}                                   # counts only, no text


@pytest.mark.skipif(not S.DB.is_file(), reason="data/sessions.db is the local app store; absent on this machine")
def test_the_measurement_is_what_the_store_gives_today(stored):
    now = S.measure(S.load_sessions())
    assert {k: now[k] for k in now} == {k: stored[k] for k in now}
