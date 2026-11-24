"""D-1: rank the runs that could separate competing hypotheses, against the single run each hypothesis proposes today.

For one question, the Council's competing hypotheses each carry a falsifier naming a target run, a reference run and a
channel. Today each hypothesis proposes its own run. Ranked instead: every run any realisable falsifier names (F-1:
the falsifier can fire on it), scored by how many of the competing hypotheses it tests at once. A run in the corpus
already is marked: it is read, not run.

The score is a heuristic and the artefact says so: it counts hypotheses a run can test, which is not information gain
(that needs a predictive model of outcomes the platform does not have), and nothing validates it until the runs exist.
Measured on the 210 M1+M2 hypotheses (10 questions, 21 each).

    python evals/rank_proposals.py    # writes evals/results/proposal_ranking.json
"""
from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))

import falsifiers  # noqa: E402
from label_mechanism import CORPUS_DESIGNS_2026_11_24  # noqa: E402

OUT = REPO / "evals" / "results" / "proposal_ranking.json"
WHAT = ("the number of competing hypotheses whose realisable falsifier names the run as its target: how many one "
        "run tests at once; not information gain, and unvalidated until the runs exist")


def rank(hypotheses: list[dict]) -> dict:
    realisable = [h for h in hypotheses if falsifiers.realisability(h)["status"] == "realisable"]
    # Ranked over TARGET runs: nearly every falsifier compares against wildtype/basal, so counting references would put
    # the shared reference first for every question (it did, on the first run of this script) and say nothing.
    tests: dict[str, int] = collections.Counter(h["falsifier"].get("target") for h in realisable
                                                if h["falsifier"].get("target"))
    references = collections.Counter(h["falsifier"].get("reference") for h in realisable
                                     if h["falsifier"].get("reference"))
    corpus = set(CORPUS_DESIGNS_2026_11_24)
    ranked = [{"run": run, "hypotheses": n, "in_corpus": run in corpus}
              for run, n in sorted(tests.items(), key=lambda kv: (-kv[1], kv[0]))]
    targets = [h["falsifier"].get("target") for h in realisable]
    top_target = max((tests[t] for t in targets if t), default=0)
    own = [tests.get(t, 0) for t in targets]
    return {"n_hypotheses": len(hypotheses), "n_realisable": len(realisable), "ranked": ranked,
            "shared_references": dict(references),
            "own_run_scores": own, "own_run_is_top_target": sum(s == top_target for s in own)}


def main() -> int:
    from cellarium import provenance
    recs = json.loads((REPO / "evals" / "results" / "ablation_m1m2.json").read_text(encoding="utf-8"))["results"]
    by_q: dict[str, list[dict]] = collections.defaultdict(list)
    for r in recs:
        by_q[r["id"]].append(r.get("hypothesis") or {})
    per = {}
    for q, hs in sorted(by_q.items()):
        r = rank(hs)
        per[q] = {"n_hypotheses": r["n_hypotheses"], "n_realisable": r["n_realisable"],
                  "top_runs": r["ranked"][:3], "n_candidate_runs": len(r["ranked"]),
                  "shared_references": r["shared_references"],
                  "own_run_is_top_target": r["own_run_is_top_target"],
                  "mean_own_run_score": round(sum(r["own_run_scores"]) / len(r["own_run_scores"]), 2)
                  if r["own_run_scores"] else None}
    totals = {"n_realisable": sum(v["n_realisable"] for v in per.values()),
              "n_not_realisable": sum(v["n_hypotheses"] - v["n_realisable"] for v in per.values()),
              "own_run_is_top_target": sum(v["own_run_is_top_target"] for v in per.values())}
    out = {"spec": "D-1", "source": "evals/results/ablation_m1m2.json", "what_the_score_is": WHAT,
           "n_questions": len(per), "n_hypotheses": sum(v["n_hypotheses"] for v in per.values()),
           "totals": totals, "per_question": per,
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(totals), {q: v["top_runs"][0] if v["top_runs"] else None for q, v in per.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
