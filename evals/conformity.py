"""N-1: objections the Council closed while the hypothesis stayed the same, per arm.

The measure is Appendix I.5's: an objection marked resolved at round k, raised against the candidate of round j,
counts as closed unchanged when the proposer's claim, H1 and H0 are word for word the same at j and at k. Only those
three fields are compared, so "unchanged" can overstate (a falsifier or design may have moved) and one edited word
counts as a change. A record that did not store its rounds is counted, never guessed at.
"""
from __future__ import annotations

from collections import defaultdict


def round_recorder():
    """An `on_round` callback for council.deliberate, and the list it fills: each round's proposer claim, H1 and H0,
    and the objections raised in it (id, severity, type)."""
    rounds: list[dict] = []

    def record(info: dict) -> None:
        rounds.append({"round": info.get("round"),
                       "proposer": dict(info.get("proposer") or {}),
                       "objections": [{k: o.get(k) for k in ("id", "severity", "type")}
                                      for o in info.get("skeptic") or []]})
    return record, rounds


def _text(rounds: list[dict], n: int):
    r = next((x for x in rounds if x.get("round") == n), None)
    p = (r or {}).get("proposer") or {}
    return None if r is None else (p.get("claim"), p.get("h1"), p.get("h0"))


def conformity(records: list[dict]) -> dict:
    by_cfg: dict = defaultdict(lambda: {"substantive": {"raised": 0, "resolved": 0, "closed_unchanged": 0},
                                        "minor": {"raised": 0, "resolved": 0, "closed_unchanged": 0}})
    without = 0
    for rec in records:
        rounds = rec.get("rounds")
        if not rounds:
            without += 1
            continue
        tally = by_cfg[rec.get("config", "?")]
        for o in (rec.get("hypothesis") or {}).get("objection_ledger") or []:
            sev = "substantive" if o.get("severity") == "substantive" else "minor"
            tally[sev]["raised"] += 1
            k = o.get("resolved_round")
            if k is None:
                continue
            tally[sev]["resolved"] += 1
            before, after = _text(rounds, o.get("round")), _text(rounds, k)
            if before is not None and before == after:
                tally[sev]["closed_unchanged"] += 1
    return {"by_config": {k: v for k, v in sorted(by_cfg.items())}, "records_without_rounds": without}
