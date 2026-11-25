"""D-1b re-evaluated: the falsifier-label check applied to the 210 recorded Council hypotheses (M1+M2, 10 questions).

`council.falsifier_label_issues` now runs inside every debate round. Here it is applied after the fact to the
hypotheses D-1 ranked, which were produced before the check existed, to count how many falsifier labels name a
proposed design, how many the check would have repaired, and how many it would have sent back to the proposer as an
objection. The Council is not re-run (that would be a paid run); this measures what the deterministic check does to
the recorded emits.

    python evals/d1b_falsifier_labels.py      # writes evals/results/d1b_falsifier_labels.json
"""
from __future__ import annotations

import collections
import copy
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "evals" / "results" / "d1b_falsifier_labels.json"


def main() -> int:
    from cellarium import council, provenance
    recs = json.loads((REPO / "evals" / "results" / "ablation_m1m2.json").read_text(encoding="utf-8"))["results"]
    tally = collections.Counter()
    examples = {"repaired": [], "objection": []}
    for r in recs:
        h = copy.deepcopy(r.get("hypothesis") or {})
        f = h.get("falsifier")
        if not isinstance(f, dict) or not (f.get("target") or f.get("reference")):
            tally["no_falsifier"] += 1
            continue
        tally["hypotheses_with_a_falsifier"] += 1
        repairs, issues = council.falsifier_label_issues(h)
        tally["labels_repaired"] += len(repairs)
        tally["labels_objected"] += len(issues)
        tally["clean" if not repairs and not issues else "repaired_only" if not issues else "would_be_sent_back"] += 1
        for k, items in (("repaired", repairs), ("objection", issues)):
            for it in items[:1]:
                if len(examples[k]) < 6:
                    examples[k].append({"question": r.get("id"), "detail": it[:240]})
    out = {"spec": "D-1b", "source": "evals/results/ablation_m1m2.json (the hypotheses D-1 ranked)",
           "tally": dict(tally), "examples": examples,
           "note": "recorded emits, checked after the fact; in a live debate an objection goes back to the proposer "
                   "and the round cannot converge until the label names a proposed design",
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["tally"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
