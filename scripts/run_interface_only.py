"""PX-1: score an interface-level compatibility check against the representability gate, on both question banks.

No model call: the requirements were parsed when the gate was measured, and stored with each record, so only the
decision is replaced. Writes evals/results/interface_only_ablation.json.

    python scripts/run_interface_only.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))

import interface_only as I  # noqa: E402

from cellarium import provenance  # noqa: E402

BANKS = {"bank_216": "evals/results/gate_eval_8framings.json",
         "heldout_60": "evals/results/gate_eval_heldout.json"}
OUT = REPO / "evals" / "results" / "interface_only_ablation.json"


def _principled(recs: list[dict]) -> list[dict]:
    return [dict(r, required=r.get("required_principled", r["required"])) for r in recs]


def run() -> dict:
    banks: dict = {}
    for name, path in BANKS.items():
        recs = json.loads((REPO / path).read_text(encoding="utf-8"))["records"]
        banks[name] = {"against_key": I.score(recs), "against_principled_key": I.score(_principled(recs))}
        if name == "heldout_60":
            head = [r for r in recs if r.get("registry_can_express", True)]
            banks["heldout_headline_56"] = {"against_key": I.score(head),
                                            "against_principled_key": I.score(_principled(head))}
    return {
        "spec": "PX-1",
        "question": "What does the representability gate refuse that an interface-level compatibility check would "
                    "admit?",
        "definition": {
            "loose": "admit if the simulator accepts the intervention and writes an output for the observable",
            "strict": "loose, and the input can name and an output column carries the requested resolution",
            "gate": "admit only what the gate answered; refuse and propose run no tool",
            "risk": "share of what a check admits that the key says should have been refused",
        },
        "banks": banks,
        "interface_table": {f"{k} | {m}": {"loose": v.admits(strict=False), "strict": v.admits(strict=True),
                                           "evidence": v.evidence}
                            for (k, m), v in sorted(I.UNREPRESENTED.items())},
        "environment": provenance.code_environment(),
    }


def main() -> int:
    res = run()
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, b in res["banks"].items():
        s = b["against_key"]
        print(f"{name}: n={s['n']} keyed={s['keyed']}")
        for check in ("gate", "interface_strict", "interface_loose"):
            c = s[check]
            print(f"   {check:17s} admits {c['admitted']:3d}  of which keyed refuse {c['admitted_keyed_refuse']:3d}"
                  f"  risk {c['risk']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
