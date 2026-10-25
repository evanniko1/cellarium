"""Probe the question parser's carbon_source_removal rule (AUDIT-KF-N1) with the live language model.

Each question carries the expected label: does its answer depend on the carbon source being removed? Every
question is parsed REPEATS times, because the call runs at the provider's default temperature, and the gate's
decision under steady_state is recorded with it. Writes evals/results/carbon_parse_probe.json.

    python scripts/probe_carbon_parse.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))
sys.path.insert(0, str(REPO / "src"))

from cellarium import credentials, gate  # noqa: E402

REPEATS = 3
# (question, depends_on_carbon_removal, note)
QUESTIONS = [
    ("What happens to the growth rate when glucose is removed from minimal medium 20 minutes into the simulation?", True, "removal mid-run"),
    ("In a medium with no carbon source at all, how fast does the cell grow?", True, "absent from the start"),
    ("How long after glucose runs out does the cell stop dividing?", True, "exhaustion"),
    ("Simulate carbon starvation: how does ribosome content change over the next generation?", True, "named starvation"),
    ("Does the cstA transcript rise when the cell is starved of carbon?", True, "starvation gene"),
    ("Does a ptsG knockout survive once glucose is withdrawn from the medium?", True, "knockout + removal"),
    ("After a downshift from glucose to a medium without any sugar, what happens to ppGpp?", True, "downshift to none"),
    ("How do protein synthesis rates respond to sudden glucose deprivation?", True, "deprivation"),
    ("How does the growth rate change when glucose is lowered from 20 mM to 2 mM?", False, "lowered, not removed"),
    ("Compare the growth rate in acetate minimal medium with glucose minimal medium.", False, "static alternative carbon"),
    ("What is the growth rate of the wild type in glucose minimal medium?", False, "plain glucose"),
    ("How does ppGpp respond when amino acids are removed from a rich medium?", False, "amino-acid removal"),
    ("Does growth slow when phosphate is removed from the medium?", False, "phosphate, not carbon"),
    ("Does an argS knockout grow in glucose minimal medium?", False, "knockout only"),
    ("What happens after a shift from glucose minimal medium to glucose plus amino acids?", False, "upshift"),
    ("How does the cell respond to the removal of oxygen?", False, "oxygen removal"),
    ("How does the cell respond to glucose limitation in a chemostat at a low dilution rate?", False, "limiting, non-zero"),
]


def main() -> int:
    credentials.load_into_env()     # the key lives in the OS keychain, not .env (docs/CREDENTIALS.md)
    rows = []
    for q, expected, note in QUESTIONS:
        reps = []
        for _ in range(REPEATS):
            req = gate.parse(q)
            dec = gate.decide(req, mode="steady_state")
            reps.append({"deps": list(req.regulatory_dependencies), "observable": req.observable,
                         "granularity": req.granularity, "parser": req.parser, "verdict": dec.verdict,
                         "blocking": list(dec.blocking)})
        flagged = [("carbon_source_removal" in r["deps"]) for r in reps]
        rows.append({"question": q, "expected": expected, "note": note, "flagged": flagged,
                     "all_correct": all(f == expected for f in flagged), "reps": reps})
        print(f"{'OK ' if rows[-1]['all_correct'] else 'BAD'} expected={expected!s:5} flagged={flagged} "
              f"verdicts={[r['verdict'] for r in reps]} :: {note}", flush=True)
    pos = [r for r in rows if r["expected"]]
    neg = [r for r in rows if not r["expected"]]
    calls = [f for r in rows for f in r["flagged"]]
    summary = {
        "model": rows[0]["reps"][0]["parser"], "repeats": REPEATS, "questions": len(rows), "calls": len(calls),
        "recall_calls": sum(f for r in pos for f in r["flagged"]) / (len(pos) * REPEATS),
        "false_positive_calls": sum(f for r in neg for f in r["flagged"]) / (len(neg) * REPEATS),
        "questions_stable_and_correct": sum(r["all_correct"] for r in rows),
        "verdicts_on_positives": dict(Counter(rep["verdict"] for r in pos for rep in r["reps"])),
        "parse_failures": sum("failed" in rep["parser"] for r in rows for rep in r["reps"]),
    }
    out = REPO / "evals" / "results" / "carbon_parse_probe.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
