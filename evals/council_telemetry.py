"""Validation-layer item 5 (the free part): what the Council's debate changed, read from runs already stored.

Three measures, no model call:

  (a) COLLAPSE. A run in which a substantive objection was raised and which still converged within two rounds.
      The worry: a dialectic that closes before the objection can have done any work.
  (b) RESOLVED WITHOUT A VISIBLE CHANGE. An objection the run records as resolved (`meta.resolutions`: objection
      id -> round) where the proposer's claim, H1 and H0 are IDENTICAL between the round the objection was
      raised and the round that resolved it. The Council's resolution tracking lets the critic close an
      objection whether or not the proposer changed anything, so this is the direct test of "the critique
      changes the hypothesis", from stored data. A near-identical change (text similarity >= 0.95) is reported
      beside it, because one edited word is a change in text and not necessarily in substance.
  (c) CONVERGED BELOW ITS OWN EARLIER BEST. A converged multi-round run whose final round the Council's OWN
      judge rated lower (rubric: falsifiable, specified, operationalized, discriminating) than an earlier round.
      An oracle gap measured with the Council's own instrument, not the blind auditor's.

THE DATA, AND WHY ITS LIMITS ARE WHAT THEY ARE. Only the hypothesis app's store (data/sessions.db, table
`council_runs`, local and gitignored) keeps each round's proposer text and objections; the stored ablation records
predate the ledger. So the sample is the runs a person actually made in the app: real questions, varied settings,
n small. The store keeps claim, H1 and H0 per round but NOT the falsifier, rivals or designs, so (b)'s count is
an UPPER bound on "resolved while nothing changed" (the answer may sit in a field not stored per round) and a
LOWER bound on "resolved without a substantive change" (a cosmetic edit counts as a change). (c) uses the
Council's own coarse four-item rubric, which saturates; it cannot see a regression the rubric does not score.

    python evals/council_telemetry.py            # reads data/sessions.db read-only, writes the aggregate artefact

The artefact (evals/results/council_telemetry.json) carries counts and per-run numbers keyed by run id only: no
question, claim or objection text leaves the local store.
"""

from __future__ import annotations

import difflib
import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "sessions.db"
OUT = REPO / "evals" / "results" / "council_telemetry.json"
RUBRIC = ("falsifiable", "specified", "operationalized", "discriminating")
TEXT_FIELDS = ("claim", "h1", "h0")
NEAR_IDENTICAL = 0.95


def _text(cand: dict) -> str:
    return "\n".join(str((cand or {}).get(k) or "") for k in TEXT_FIELDS)


def objections(run: dict) -> list[dict]:
    """Every objection the run raised: id, severity, the round it was raised in and the round that resolved it
    (None when it never was), and how much the proposer's claim/H1/H0 text moved between those two rounds."""
    by_round = {r["round"]: r for r in run["rounds"]}
    resolved = (run.get("meta") or {}).get("resolutions") or {}
    out = []
    for r in run["rounds"]:
        for o in r.get("skeptic") or []:
            raised, closed = r["round"], resolved.get(o.get("id"))
            row = {"id": o.get("id"), "severity": o.get("severity") or "unstated", "raised": raised,
                   "resolved": closed, "identical": None, "similarity": None}
            if closed is not None:
                a = _text(by_round.get(raised, {}).get("proposer"))
                b = _text(by_round.get(closed, {}).get("proposer"))
                row["identical"] = a == b
                row["similarity"] = round(difflib.SequenceMatcher(None, a, b).ratio(), 4)
            out.append(row)
    return out


def collapsed(run: dict, within: int = 2) -> bool:
    meta = run.get("meta") or {}
    raised = any(o["severity"] == "substantive" for o in objections(run))
    used = meta.get("rounds_used") or len(run["rounds"])
    return bool(raised and meta.get("converged") and used <= within)


def judge_scores(run: dict) -> list[int]:
    return [sum(bool((r.get("judge") or {}).get(k)) for k in RUBRIC) for r in run["rounds"]]


def converged_below_earlier_best(run: dict) -> bool | None:
    """None when the question does not apply: not converged, or a single round (nothing earlier to compare)."""
    if not (run.get("meta") or {}).get("converged") or len(run["rounds"]) < 2:
        return None
    s = judge_scores(run)
    return s[-1] < max(s[:-1])


def summarize(runs: list[dict]) -> dict:
    per_run, objs = [], []
    for run in runs:
        o = objections(run)
        objs += [{**x, "where": f"{run['id']}:{x['id']}"} for x in o]   # objection ids repeat across runs
        per_run.append({"id": run["id"], "rounds": len(run["rounds"]),
                        "converged": bool((run.get("meta") or {}).get("converged")),
                        "substantive": sum(x["severity"] == "substantive" for x in o),
                        "minor": sum(x["severity"] == "minor" for x in o),
                        "resolved_identical": sum(bool(x["identical"]) for x in o),
                        "collapsed": collapsed(run), "judge_scores": judge_scores(run),
                        "converged_below_earlier_best": converged_below_earlier_best(run)})

    def by_sev(sev: str) -> dict:
        xs = [x for x in objs if x["severity"] == sev]
        res = [x for x in xs if x["resolved"] is not None]
        return {"raised": len(xs), "resolved": len(res), "unresolved": len(xs) - len(res),
                "resolved_in_the_round_raised": sum(x["resolved"] == x["raised"] for x in res),
                "resolved_with_identical_claim_h1_h0": sum(bool(x["identical"]) for x in res),
                f"resolved_with_text_similarity_ge_{NEAR_IDENTICAL}": sum((x["similarity"] or 0) >= NEAR_IDENTICAL
                                                                         for x in res),
                "identical_at": sorted(x["where"] for x in res if x["identical"])}

    applicable = [r for r in per_run if r["converged_below_earlier_best"] is not None]
    with_sub = [r for r in per_run if r["substantive"]]
    return {
        "runs": len(runs), "rounds": sum(r["rounds"] for r in per_run),
        "objections": len(objs),
        "substantive": by_sev("substantive"), "minor": by_sev("minor"),
        "unstated_severity": sum(x["severity"] == "unstated" for x in objs),
        "collapse": {"runs_with_a_substantive_objection": len(with_sub),
                     "converged_within_2_rounds_anyway": sum(r["collapsed"] for r in with_sub),
                     "ids": sorted(r["id"] for r in with_sub if r["collapsed"])},
        "converged_below_its_own_earlier_best": {"applicable_runs": len(applicable),
                                                 "count": sum(bool(r["converged_below_earlier_best"])
                                                              for r in applicable)},
        "per_run": per_run,
    }


def load_app_runs(db: Path = DB) -> list[dict]:
    """Finished runs from the app store, READ-ONLY, with no question text: id, rounds, meta."""
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, rounds, meta FROM council_runs WHERE status='done' ORDER BY created").fetchall()
    finally:
        con.close()
    return [{"id": i, "rounds": json.loads(r or "[]"), "meta": json.loads(m or "{}")} for i, r, m in rows]


def main() -> int:
    if not DB.is_file():
        print(f"{DB.relative_to(REPO)} is not on this machine; the stored Council runs live only in the app store "
              "where they were made. Nothing follows about whether such runs exist elsewhere.", file=sys.stderr)
        return 2
    s = summarize(load_app_runs())
    s["source"] = ("data/sessions.db council_runs (status 'done'), read-only; the app store of the machine that "
                   "made the runs, so this artefact is re-derivable only there")
    s["computed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    s["limits"] = ("claim/H1/H0 are the only proposer fields stored per round: 'identical' is an upper bound on "
                   "'nothing changed' and a lower bound on 'no substantive change'; the judge-rubric measure uses "
                   "the Council's own four-item rubric, not the blind auditor")
    OUT.write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")
    sub = s["substantive"]
    print(f"{s['runs']} runs, {s['objections']} objections; substantive resolved {sub['resolved']}/{sub['raised']}, "
          f"of which identical claim/H1/H0: {sub['resolved_with_identical_claim_h1_h0']}; collapse "
          f"{s['collapse']['converged_within_2_rounds_anyway']}/{s['collapse']['runs_with_a_substantive_objection']}; "
          f"converged below own earlier best {s['converged_below_its_own_earlier_best']['count']}/"
          f"{s['converged_below_its_own_earlier_best']['applicable_runs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
