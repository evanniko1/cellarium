"""Two controls for the Council that run inside `council.deliberate` (validation item 5(d) and its noise arm).

1. LOG, DON'T STOP (stopping-rule regret). The Council stops early once a clean draft has survived its quota of
   doubt or stayed clean for two rounds. Whether that stop costs anything is unmeasured: the early stop returns,
   so no one sees what rounds 3 and 4 would have produced. With `log_stop`, the rule is recorded instead of taken:
   the run goes to the round cap, and the dict receives the round where it would have stopped, which branch
   fired (the quota or the two-clean-rounds stability), and the hypothesis it would have returned. That
   hypothesis must be exactly what a normal run returns, or the comparison measures the instrument.

2. REPLAYED OBJECTIONS (the irrelevant-objection noise arm). `objection_source` stands in for the skeptic: no
   skeptic call is made, and its objections (with the ids it certifies as resolved) come from the callable. The
   eval harness feeds it objections raised against a DIFFERENT question, so a tie with the real skeptic would say
   the skeptic works as a revision prompt with more context rather than as a critic.

Every model call is scripted; nothing leaves the machine.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import council  # noqa: E402


class _Block:
    def __init__(self, data):
        self.type = "tool_use"
        self.input = data


class _Resp:
    def __init__(self, data):
        self.content = [_Block(data)]


class _Messages:
    def __init__(self, scripts):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls: list[str] = []

    def create(self, **kw):
        name = kw["tool_choice"]["name"]
        self.calls.append(name)
        queue = self.scripts.get(name)
        assert queue, f"no scripted response left for {name!r} (call #{len(self.calls)})"
        return _Resp(copy.deepcopy(queue.pop(0)))


class _Client:
    def __init__(self, scripts):
        self.messages = _Messages(scripts)


def _cand(tag: str) -> dict:
    return {
        "claim": f"claim {tag}", "h1": f"h1 {tag}", "h0": f"h0 {tag}",
        "operational_defs": [{"construct": "c", "observable": "protein_mass", "measure": "cv across seeds"}],
        "predicted_effect": "positive; CV above baseline",
        "falsifier": {"target": "wildtype/basal", "reference": "wildtype/basal", "channel": "protein_mass",
                      "decision_rule": "reject H0 if welch_t >= 2", "refuting_result": "welch_t < 2"},
        "rivals": [{"claim": "noise", "distinguishing_result": "cv == baseline"},
                   {"claim": "extrinsic", "distinguishing_result": "tracks mass"}],
        "auxiliary_assumptions": ["same medium"],
        "candidate_designs": [{"perturbation": "wildtype", "condition": "basal", "seeds": 8}],
    }


def _verdict(**over):
    v = {"falsifiable": True, "specified": True, "operationalized": True, "discriminating": True,
         "new_substantive_objection_this_round": False, "open_objections_resolved": True}
    v.update(over)
    return v


def _obj(t, sev="substantive"):
    return {"type": t, "issue": f"{t} concern", "severity": sev}


def _stable_scripts():
    """Round 1 raises one substantive objection; rounds 2 and 3 are clean, so the stability branch fires at 3."""
    return {
        "propose_hypothesis": [_cand("a"), _cand("b"), _cand("c"), _cand("d")],
        "raise_objections": [{"objections": [_obj("undefined_term")]},
                             {"objections": [], "resolved": ["r1.1"]},
                             {"objections": []}, {"objections": []}],
        "rule": [_verdict(new_substantive_objection_this_round=True, open_objections_resolved=False),
                 _verdict(), _verdict(), _verdict()],
    }


def _run(scripts, **kw):
    client = _Client(scripts)
    h = council.deliberate("does the enzyme vary?", client=client, verbose=False, temperature=0.0, **kw)
    return h, client


# --- log, don't stop -----------------------------------------------------------------------------------

def test_a_normal_run_stops_where_the_rule_fires():
    h, client = _run(_stable_scripts())
    assert h.rounds_used == 3 and h.claim == "claim c"
    assert client.messages.calls.count("propose_hypothesis") == 3


def test_log_mode_runs_every_round_and_records_where_it_would_have_stopped():
    log: dict = {}
    h, client = _run(_stable_scripts(), log_stop=log)
    assert client.messages.calls.count("propose_hypothesis") == 4       # the round cap, every time
    assert log["round"] == 3 and log["branch"] == "stability"
    assert (log["quota_met"], log["stable"]) == (False, True)
    assert h.rounds_used == 4                                           # the returned run is the full one


def test_the_logged_hypothesis_is_exactly_what_a_normal_run_returns():
    normal, _ = _run(_stable_scripts())
    log: dict = {}
    _run(_stable_scripts(), log_stop=log)
    assert log["hypothesis"].model_dump() == normal.model_dump()


def test_later_rounds_do_not_rewrite_the_logged_hypothesis():
    """`_finalize_ledger` writes into ledger entries. Round 2 raises a minor objection still open when the rule
    fires in round 3, so the snapshot credits it to round 3; the skeptic resolves it in round 4, and the round-cap
    result must say 4 while the snapshot still says 3. Without its own copy of the ledger the snapshot's write
    would reach the live debate and the round-cap result would say 3."""
    scripts = {
        "propose_hypothesis": [_cand("a"), _cand("b"), _cand("c"), _cand("d")],
        "raise_objections": [{"objections": [_obj("undefined_term")]},
                             {"objections": [_obj("style", sev="minor")], "resolved": ["r1.1"]},
                             {"objections": []},
                             {"objections": [], "resolved": ["r2.1"]}],
        "rule": [_verdict(new_substantive_objection_this_round=True, open_objections_resolved=False),
                 _verdict(), _verdict(), _verdict()],
    }
    log: dict = {}
    final, _ = _run(scripts, log_stop=log)
    assert log["round"] == 3
    assert [(o["id"], o["resolved_round"]) for o in log["hypothesis"].objection_ledger] == [("r1.1", 2), ("r2.1", 3)]
    assert [(o["id"], o["resolved_round"]) for o in final.objection_ledger] == [("r1.1", 2), ("r2.1", 4)]


def test_the_quota_branch_is_named_when_the_quota_fired():
    scripts = {
        "propose_hypothesis": [_cand("a"), _cand("b"), _cand("c"), _cand("d")],
        "raise_objections": [{"objections": [_obj("undefined_term"), _obj("hidden_auxiliary"),
                                             _obj("rival_not_excluded")]},
                             {"objections": [], "resolved": ["r1.1", "r1.2", "r1.3"]},
                             {"objections": []}, {"objections": []}],
        "rule": [_verdict(new_substantive_objection_this_round=True, open_objections_resolved=False),
                 _verdict(), _verdict(), _verdict()],
    }
    log: dict = {}
    _run(scripts, log_stop=log)
    assert log["round"] == 2 and log["branch"] == "quota"
    assert (log["quota_met"], log["stable"]) == (True, False)


def test_a_run_whose_rule_never_fires_logs_none():
    scripts = {
        "propose_hypothesis": [_cand(t) for t in "abcd"],
        "raise_objections": [{"objections": [_obj("undefined_term")]} for _ in range(4)],
        "rule": [_verdict(new_substantive_objection_this_round=True, open_objections_resolved=False)
                 for _ in range(4)],
    }
    log: dict = {}
    _run(scripts, log_stop=log)
    assert log["round"] is None and log["branch"] is None and log["hypothesis"] is None
    assert [r["clean"] for r in log["rounds"]] == [False, False, False, False]


# --- replayed objections -------------------------------------------------------------------------------

def test_an_objection_source_replaces_the_skeptic_call():
    scripts = _stable_scripts()
    scripts.pop("raise_objections")                                    # any skeptic call would now fail
    plan = {1: {"objections": [_obj("unfalsifiable")]}, 2: {"objections": [], "resolved": ["r1.1"]}}
    seen: list[int] = []

    def source(rnd, cand, open_led):
        seen.append(rnd)
        return copy.deepcopy(plan.get(rnd, {"objections": []}))
    h, client = _run(scripts, objection_source=source)
    assert "raise_objections" not in client.messages.calls
    assert seen == [1, 2, 3]
    assert [(o["id"], o["type"], o["resolved_round"]) for o in h.objection_ledger] == [("r1.1", "unfalsifiable", 2)]


def test_an_objection_source_is_ignored_when_the_skeptic_is_off():
    """`use_skeptic=False` means no objections at all, replayed or not."""
    def source(rnd, cand, open_led):
        raise AssertionError("called with the skeptic off")
    scripts = _stable_scripts()
    scripts.pop("raise_objections")
    h, _ = _run(scripts, use_skeptic=False, objection_source=source)
    assert h.objection_ledger == []


@pytest.mark.parametrize("bad", [None, "text", {"objections": "not a list"}])
def test_an_unreadable_replay_is_reported_like_an_unreadable_skeptic(bad):
    """The replay path gets the same guard the skeptic does: unreadable is never 'no objections'."""
    scripts = _stable_scripts()
    scripts.pop("raise_objections")
    h, _ = _run(scripts, objection_source=lambda rnd, cand, open_led: bad)
    assert not h.converged and any("skeptic_unreadable" in r for r in h.residual_ambiguities)
