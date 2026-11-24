"""Q-1: item-level retention for section 18's grounded-against-ungrounded comparison, from the stored replies.

No model call. Reads the grounded arms' judged items (data/discrimination_test_rescored.json), the ungrounded arms'
judged items (data/ablation_rescored.json) and the ungrounded replies themselves (data/ablation_ungrounded.json),
and writes evals/results/item_retention_n9.json.

    python scripts/item_retention.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))

import retention  # noqa: E402

from cellarium import provenance  # noqa: E402

OUT = REPO / "evals" / "results" / "item_retention_n9.json"


def _load(rel: str) -> dict:
    return json.loads((REPO / rel).read_text(encoding="utf-8"))


def run() -> dict:
    grounded = _load("data/discrimination_test_rescored.json")["arms"]
    ungrounded = _load("data/ablation_rescored.json")["arms"]
    replies = _load("data/ablation_ungrounded.json")["arms"]
    models = {}
    for m in ungrounded:
        g = {i["id"]: i["correct"] for i in grounded[m]["items"]}
        u = {i["id"]: i["correct"] for i in ungrounded[m]["items"]}
        answers = {r["id"]: r.get("answer", "") for r in replies[m]}
        models[m] = retention.retention(g, u, answers)
    return {
        "spec": "Q-1",
        "finding": ("The ungrounded arm has almost no answers to compare: it ran through the agent loop, so it saw "
                    "Cellwright's system prompt and tools, and its single turn cut most replies off. The comparison "
                    "is withdrawn; a valid one needs the fixed runner and judge (spec K-2)."),
        "models": models,
        "environment": provenance.code_environment(),
    }


def main() -> int:
    res = run()
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for m, r in res["models"].items():
        print(f"{m}: {r['n']} items, ungrounded no-answer {len(r['ungrounded_no_answer'])}, comparable "
              f"{r['comparable']}, lost {r['lost_by_grounding']}, gained {r['gained_by_grounding']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
