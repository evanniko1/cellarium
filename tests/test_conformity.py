"""N-1: does the Council close objections without changing anything?

Unguided debate among homogeneous models fails by conformity (arXiv:2605.00914): agents adopt the modal answer and
the critic's objection is "resolved" by agreement. Appendix I.5 measured the Council's version on the app's stored
runs: an objection closed while the proposer's claim, H1 and H0 stayed word for word the same (2 of 43 substantive).
The M1+M2 ablation records keep only the final hypothesis, so the measure could not be repeated on them; the
ablation now records every round's proposer text and objections, and this module computes the measure from them.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "evals", "tests"):
    sys.path.insert(0, str(REPO / p))

import conformity  # noqa: E402
import test_council_independence as T  # noqa: E402

from cellarium import council  # noqa: E402


def test_the_recorder_keeps_every_rounds_proposer_text_and_objections():
    record, rounds = conformity.round_recorder()
    council.deliberate("does protein mass vary?", client=T._Client(T._scripts("t")), verbose=False,
                       temperature=0.0, on_round=record)
    assert [r["round"] for r in rounds] == list(range(1, len(rounds) + 1)) and len(rounds) >= 2
    assert rounds[0]["proposer"]["claim"] == "claim t0"
    assert rounds[0]["objections"][0]["severity"] == "substantive"


def _rec(cfg, rounds, ledger):
    return {"config": cfg, "rounds": rounds, "hypothesis": {"objection_ledger": ledger}}


def _rnd(i, claim):
    return {"round": i, "proposer": {"claim": claim, "h1": "h1", "h0": "h0"}, "objections": []}


def test_an_objection_closed_with_the_text_unchanged_is_counted():
    rec = _rec("full", [_rnd(1, "a"), _rnd(2, "a"), _rnd(3, "b")], [
        {"id": "r1.1", "round": 1, "severity": "substantive", "resolved_round": 2},   # closed, text unchanged
        {"id": "r1.2", "round": 1, "severity": "substantive", "resolved_round": 3},   # closed after a change
        {"id": "r2.1", "round": 2, "severity": "minor", "resolved_round": None},      # never closed
    ])
    out = conformity.conformity([rec])
    full = out["by_config"]["full"]
    assert full["substantive"] == {"raised": 2, "resolved": 2, "closed_unchanged": 1}
    assert full["minor"] == {"raised": 1, "resolved": 0, "closed_unchanged": 0}
    assert out["records_without_rounds"] == 0


def test_a_record_without_rounds_is_counted_not_guessed():
    out = conformity.conformity([{"config": "full", "hypothesis": {"objection_ledger": []}}])
    assert out["records_without_rounds"] == 1 and out["by_config"] == {}


def test_every_ablation_record_keeps_its_rounds_whatever_the_arm(monkeypatch):
    import ablate
    import test_ablation_arms as A

    def fake(question, **kw):
        for r in (1, 2):
            kw["on_round"]({"round": r, "proposer": {"claim": f"c{r}", "h1": "h1", "h0": "h0"},
                            "skeptic": [{"id": f"r{r}.1", "severity": "minor", "type": "t", "issue": "i"}]})
        return A._hyp()
    monkeypatch.setattr(council, "deliberate", fake)
    for cfg in ("no_skeptic", "full"):
        rec = ablate._one_cell({"id": "1.1", "question": "q"}, cfg, 0, 0.7, object(), None, "gpt-4o",
                               "claude-opus-4-8", rubric=False)
        assert [r["proposer"]["claim"] for r in rec["rounds"]] == ["c1", "c2"], cfg
        assert rec["rounds"][1]["objections"] == [{"id": "r2.1", "severity": "minor", "type": "t"}]
