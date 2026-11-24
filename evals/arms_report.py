"""The report for a sweep with the new arms (validation items 3 and 5(d)): residual defects beside what each arm spent.

    python evals/arms_report.py evals/results/ablation_m1.json evals/results/audited_m1.json [--out report.json]

Per arm and per auditor, never pooled: the residual-defect count (case-clustered: each case's mean over its reps,
then the mean over cases), the paired difference to `full` with the minimum detectable effect
(aggregate.paired_mde), and beside it the mean metered cost and tokens of one record, because a quality number
without its budget is how an unmetered multi-agent win gets reported (validation item 3, step 4). Then the three
comparisons the new arms exist for, each paired inside a record or a case:

  best_of_n  the reported pick against the other rule's pick and against the first draft (does choosing help?);
  regret     the round-cap result against what the run returned, split by the branch that stopped it (the quota
             of doubt or two clean rounds), so each branch is credited separately (item 5(d));
  noise      `full` against `noise_skeptic`, paired by case: a tie says the skeptic is a revision prompt.

An audit that failed is left out of every mean and counted under `unreadable`, never scored as zero (the defect
that made the stored Claude column unusable, see evals/audit.py). A variant audited as identical to another
hypothesis takes that hypothesis's count (`same_as`).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ablate  # noqa: E402
import aggregate as agg  # noqa: E402

AUDITORS = ("claude", "gpt")


def _count(audit_rec: dict, auditor: str, variant: str | None = None):
    """Defects for the record's hypothesis or one of its variants, following `same_as`; None if unreadable."""
    if variant is None:
        return None if "error" in audit_rec else audit_rec.get(f"{auditor}_defects")
    v = (audit_rec.get("variants") or {}).get(variant)
    if v is None:
        return None
    if "same_as" in v:
        return _count(audit_rec, auditor, None if v["same_as"] == "hypothesis" else v["same_as"])
    return None if "error" in v else v.get(f"{auditor}_defects")


def _per_case(pairs: list) -> dict:
    by = defaultdict(list)
    for cid, x in pairs:
        if x is not None:
            by[cid].append(x)
    return {c: sum(v) / len(v) for c, v in by.items() if v}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def build(ablation: dict, audited: dict) -> dict:
    recs = {(r["id"], r["config"], r["rep"]): r for r in ablation["results"] if "error" not in r}
    auds = {(a["id"], a["config"], a["rep"]): a for a in audited["results"]}
    arms = [a for a in ablate.ARMS if any(k[1] == a for k in recs)]
    out: dict = {"arms": {}, "unreadable": {}, "n_records": len(recs), "n_audited": len(auds)}
    per_case: dict = {}
    for arm in arms:
        keys = [k for k in recs if k[1] == arm]
        entry: dict = {"n": len(keys)}
        for aud in AUDITORS:
            pc = _per_case([(k[0], _count(auds[k], aud)) for k in keys if k in auds])
            per_case[(arm, aud)] = pc
            entry[f"defects_{aud}"] = round(sum(pc.values()) / len(pc), 3) if pc else None
        entry["unreadable_audits"] = sum(1 for k in keys if k in auds and "error" in auds[k])
        entry["not_audited"] = sum(1 for k in keys if k not in auds)
        entry["usd_per_record"] = _mean([(recs[k].get("llm") or {}).get("cost_usd") for k in keys])
        entry["tokens_per_record"] = _mean([ablate._spent(recs[k]["llm"], "tokens") for k in keys
                                            if recs[k].get("llm")])
        entry["mean_rounds"] = _mean([recs[k].get("rounds_used") for k in keys])
        out["arms"][arm] = entry
    for arm in arms:
        if arm == "full":
            continue
        for aud in AUDITORS:
            a, b = per_case.get(("full", aud)) or {}, per_case.get((arm, aud)) or {}
            if a and b:
                out["arms"][arm][f"vs_full_{aud}"] = agg.paired_mde(a, b)

    # best-of-N: inside each record, the reported pick against the other pick and the first draft
    bon = [k for k in recs if k[1] == "proposer_bestofN" and k in auds]
    if bon:
        out["best_of_n"] = {"n_records": len(bon),
                            "mean_drafts": _mean([recs[k]["best_of_n"]["n_drafts"] for k in bon]),
                            "budget_reached": sum(bool(recs[k]["best_of_n"]["budget_reached"]) for k in bon),
                            "same_pick_both_rules": sum(len(set(recs[k]["best_of_n"]["selected"].values())) == 1
                                                        for k in bon)}
        for aud in AUDITORS:
            for name in ("first_draft", *(f"select_{r}" for r in ablate.SELECTORS)):
                d = [(_count(auds[k], aud), _count(auds[k], aud, name)) for k in bon
                     if name in (recs[k].get("variants") or {})]
                d = [(x, y) for x, y in d if x is not None and y is not None]
                if d:
                    out["best_of_n"][f"{aud}_reported_minus_{name}"] = round(sum(x - y for x, y in d) / len(d), 3)

    # regret: round-cap result against the returned one, per stopping branch
    logged = [k for k in recs if k[1] == "full" and recs[k].get("stop_log") and k in auds]
    if logged:
        reg: dict = {"n_records": len(logged), "never_fired": sum(recs[k]["stop_log"].get("round") is None
                                                                  for k in logged)}
        for aud in AUDITORS:
            for branch in ("quota", "stability", "both"):
                d = [(_count(auds[k], aud, "all_rounds"), _count(auds[k], aud)) for k in logged
                     if recs[k]["stop_log"].get("branch") == branch]
                d = [(x, y) for x, y in d if x is not None and y is not None]
                if d:
                    reg[f"{aud}_{branch}"] = {"n": len(d), "all_rounds_minus_returned":
                                              round(sum(x - y for x, y in d) / len(d), 3)}
        out["regret"] = reg

    # noise: full against noise_skeptic, by case
    if any(k[1] == "noise_skeptic" for k in recs):
        out["noise"] = {aud: agg.paired_mde(per_case.get(("full", aud)) or {},
                                            per_case.get(("noise_skeptic", aud)) or {}) for aud in AUDITORS}
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("ablation")
    p.add_argument("audited")
    p.add_argument("--out")
    a = p.parse_args()
    rep = build(json.loads(Path(a.ablation).read_text(encoding="utf-8")),
                json.loads(Path(a.audited).read_text(encoding="utf-8")))
    print(f"{'arm':17s} {'n':>3s} {'defects_claude':>15s} {'defects_gpt':>12s} {'$/record':>9s} "
          f"{'tokens/record':>14s} {'rounds':>7s} unreadable")
    for arm, e in rep["arms"].items():
        print(f"{arm:17s} {e['n']:3d} {str(e['defects_claude']):>15s} {str(e['defects_gpt']):>12s} "
              f"{str(e['usd_per_record']):>9s} {str(e['tokens_per_record']):>14s} {str(e['mean_rounds']):>7s} "
              f"{e['unreadable_audits']}")
    for part in ("best_of_n", "regret", "noise"):
        if part in rep:
            print(f"\n{part}: {json.dumps(rep[part], indent=1)}")
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
