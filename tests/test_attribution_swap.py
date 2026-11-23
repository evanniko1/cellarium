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
                           "field_routed", "session_ids", "source", "computed_utc"}    # counts and ids, no text
    assert len(stored["session_ids"]) == 60 and all(len(s) <= 40 for s in stored["session_ids"])


@pytest.mark.skipif(not S.DB.is_file(), reason="data/sessions.db is the local app store; absent on this machine")
def test_the_measurement_is_what_the_store_gives_today(stored):
    """Recomputed over EXACTLY the sessions the artefact names. Any other store -- a seeded demo database in a
    fresh clone, or this machine's store after new sessions -- skips with the reason. (Found 2026-11-23: comparing
    against whatever store existed killed every mutant of the registry-mutation run, including its control.)"""
    want = set(stored["session_ids"])
    sessions = [s for s in S.load_sessions() if s["sid"] in want]
    if len(sessions) != len(want):
        pytest.skip(f"this machine's app store holds {len(sessions)} of the artefact's {len(want)} sessions, so it "
                    "is not the store the artefact was computed from")
    now = S.measure(sessions)
    assert {k: now[k] for k in now} == {k: stored[k] for k in now}


# --- item 9, step 2: route each number to the FIELD it came from -----------------------------------------
# What the real store showed (2026-11-23, the 60 recorded answers, keys only): 19 objects name two runs in role
# fields (`reference`, `target`), and inside their `ranked` items `reference` and `target` are NUMBERS, the two
# runs' values, beside numbers that belong to the pair (log2fc, welch_t, pct); and 66 tool results that read as
# plain text are JSON cut off for the model's context, so they parsed as nothing and counted as one blob that names
# every run.

def test_routing_to_the_field_catches_29_of_the_30_swaps_it_can_check(stored):
    """Step 2 on the same 60 answers (re-measured with --same-sessions, which refuses if any step-1 figure would
    move). The record rule caught 10 of the 50 swapped claims it supported beforehand; the field rule catches 29
    of 30. Its price is coverage: it supports 64 of the 140 unswapped claims where the record rule supported 100,
    and 11 more rest only on numbers that belong to a pair, where no attribution check can see a swap."""
    assert stored["field_routed"] == {"original_supported": 64, "original_shared_only": 11, "swapped_claims": 62,
                                      "detected": 29, "supported_before_and_after": 1, "shared_before": 10}


def test_a_flat_comparison_routes_each_number_through_its_role_field():
    leaves = S.field_leaves(TOGETHER)
    assert S.field_routed_ok(WT, "0.0123", leaves) and S.field_routed_ok(KO, "0.0098", leaves)
    assert not S.field_routed_ok(KO, "0.0123", leaves) and not S.field_routed_ok(WT, "0.0098", leaves)
    r = S.measure([{"answer": ANSWER, "tool_texts": TOGETHER}])
    assert (r["field_routed"]["detected"], r["field_routed"]["supported_before_and_after"]) == (2, 0)


def test_a_ranking_item_routes_its_reference_and_target_values_to_the_runs_its_parent_names():
    tool = [json.dumps({"reference": WT, "target": KO, "ranked": [
        {"quantity": "ppgpp_conc", "reference": 61.37, "target": 88.02, "log2fc": 0.52, "welch_t": 7.31}]})]
    leaves = S.field_leaves(tool)
    assert S.field_routed_ok(WT, "61.4", leaves) and S.field_routed_ok(KO, "88.0", leaves)
    assert not S.field_routed_ok(KO, "61.4", leaves)


def test_a_number_that_belongs_to_the_pair_is_shared_not_evidence_for_either_run():
    tool = [json.dumps({"reference": WT, "target": KO, "effect_pct": 43.4, "welch_t": 7.31})]
    leaves = S.field_leaves(tool)
    assert not S.field_routed_ok(KO, "43.4", leaves) and not S.field_routed_ok(WT, "43.4", leaves)
    assert S.shared_ok(KO, "43.4", leaves) and S.shared_ok(WT, "43.4", leaves)


def test_a_mapping_keyed_by_run_routes_each_value_to_its_key():
    leaves = S.field_leaves([json.dumps({"growth_rate": {"KO:argS": 0.0123, "KO:pfkA": 0.0456}})])
    assert S.field_routed_ok("KO:argS", "0.0123", leaves) and not S.field_routed_ok("KO:pfkA", "0.0123", leaves)


def test_the_nearest_object_that_names_a_run_owns_its_numbers():
    leaves = S.field_leaves([json.dumps({"reference": WT, "target": KO,
                                         "designs": [{"condition": KO, "min_division_rate": 0.0211}]})])
    assert S.field_routed_ok(KO, "0.0211", leaves) and not S.shared_ok(WT, "0.0211", leaves)


def test_a_short_label_matches_its_long_form():
    leaves = S.field_leaves([json.dumps({"design": "gene_knockout/KO:argS", "growth_rate": 0.0123})])
    assert S.field_routed_ok("KO:argS", "0.0123", leaves)
    assert not S.field_routed_ok("KO:arg", "0.0123", leaves)


def test_json_cut_off_for_the_context_is_read_up_to_the_cut():
    full = json.dumps({"reference": WT, "target": KO, "ranked": [
        {"quantity": "growth_rate", "reference": 0.01231, "target": 0.00978},
        {"quantity": "ppgpp_conc", "reference": 61.37, "target": 88.02}]})
    cut = full[: full.index("88.02") + 2] + "... [truncated]"
    assert S.repair_json(cut) == {"reference": WT, "target": KO, "ranked": [
        {"quantity": "growth_rate", "reference": 0.01231, "target": 0.00978},
        {"quantity": "ppgpp_conc", "reference": 61.37}]}
    assert S.repair_json("not json at all") is None
    assert S.field_routed_ok(KO, "0.0098", S.field_leaves([cut]))


def test_without_role_routing_the_flat_comparison_is_blind_again(monkeypatch):
    """Forced: the role rule is what does the work. Switched off, the comparison's two values belong to the pair,
    and the swap the field check caught above goes unseen."""
    monkeypatch.setattr(S, "_role_owns", lambda key, role: False)
    r = S.measure([{"answer": ANSWER, "tool_texts": TOGETHER}])
    assert (r["field_routed"]["detected"], r["field_routed"]["shared_before"]) == (0, 2)
