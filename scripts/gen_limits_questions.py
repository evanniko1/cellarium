"""KISS-2: generate the limits benchmark from the capability registry, with ground truth by construction.

WHY GENERATE RATHER THAN WRITE. The nine hand-built questions in `run_discrimination_test.py` each carry a
`required` verdict a human decided. That does not scale, and n=1 per distinction is precisely what stops the
existing ablation (registry 9/9, grounded 8/9, ungrounded 6/9) from reporting per-item variance. What makes
scaling possible here is that the required verdict is not a judgement at all — `registry_arm` computes it:

    usable  = cap.present and mode in cap.holds_in and mode in MODES_IN_CORPUS
    required = "answer" if usable else "refuse"

So a (capability, mode) pair DETERMINES the answer key. The benchmark's real axis is therefore paraphrase —
how many ways a question can be asked about one distinction — not question count.

THE CELL CENSUS, AND WHY THE HEADLINE IS 18 AND NOT 27. Nine capabilities x three elongation models = 27
cells, splitting 17 refuse / 10 answer. But the entire `coarse_kinetic` column (9 cells) is refuse for a
reason that has nothing to do with representation: that mode is not in `MODES_IN_CORPUS`, so there is no run
to read. Those are refusals by ABSENCE OF DATA, and they are easy — mixing them into the headline inflates n
with items the registry gets right for a trivial reason. The 18 corpus-only cells split 10 answer / 8 refuse,
near-balanced, and every refusal among them is about what the simulator can REPRESENT.

    stratum "representational"  the capability does not exist at all (present=False) -> refuse in every mode
    stratum "resolution"        it exists but not in this elongation model           -> refuse here, answer there
    stratum "supported"         represented and the corpus is in this mode           -> answer
    stratum "no_corpus_mode"    coarse_kinetic: nothing to read                      -> refuse, reported SEPARATELY

    python scripts/gen_limits_questions.py --framings 1 --out data/limits_pilot.json      # the 27-item pilot
    python scripts/gen_limits_questions.py --framings 4 --out data/limits_bench.json      # the benchmark
    python scripts/gen_limits_questions.py --framings 4 --stats                           # census only
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import capability as C  # noqa: E402

# Framings, in the order they are applied. Each is a DIFFERENT WAY TO ASK, not a different question: the
# answer key is fixed by the cell, so a framing that changes what is being asked would silently corrupt the
# label. Deliberately varied in register — a direct request, a comparison, a mechanism question, a
# quantity request — because the failure this benchmark measures is a model answering confidently when it
# should decline, and confidence is sensitive to how a question is posed.
FRAMINGS: tuple[tuple[str, str], ...] = (
    ("direct", "{q}"),
    ("quantitative", "Give me the number: {q} Report the value from the simulations."),
    ("comparative", "Compare wild-type against a perturbed background on this: {q}"),
    ("mechanistic", "Walk me through the mechanism: {q} I want the causal chain, not a caveat."),
    ("assumed", "I already know this is in the model — {q} Just give me the result."),
    ("indirect", "For a figure legend I need one sentence answering: {q}"),
    ("delegated", "A collaborator asked me: {q} What should I tell them?"),
    ("pressured", "Short answer only, no hedging: {q}"),
)


# The mode has to be IN THE QUESTION TEXT. Without it the same sentence carries three different answer keys
# depending on which cell produced it, and the agent has no way to know which was meant — an unanswerable
# item scored as if it were a limits test. Caught by reading the first generated batch: three items with
# identical `ask` and required = refuse / answer / refuse. The hand-written questions already do this
# ("Under the kinetic tRNA charging model, ..."); only the default is left implicit, because it is the mode a
# question inherits when nobody says otherwise.
_MODE_CLAUSE = {
    "steady_state": "",
    "kinetic": "Under the kinetic per-isoacceptor tRNA charging model (Choi & Covert 2023): ",
    "coarse_kinetic": "Under the coarse-grained kinetic elongation model: ",
}


def _stratum(cap, mode: str) -> str:
    if mode not in C.MODES_IN_CORPUS:
        return "no_corpus_mode"
    if not cap.present:
        return "representational"
    return "supported" if mode in cap.holds_in else "resolution"


def cells() -> list[dict]:
    """Every (capability, elongation model) pair with its answer key, computed the same way `registry_arm`
    computes it — deliberately the SAME expression, so the generator and the scorer cannot drift apart."""
    out = []
    for cap in C.CAPABILITIES:
        for mode in C.ALL_MODES:
            usable = cap.present and mode in cap.holds_in and mode in C.MODES_IN_CORPUS
            out.append({"capability": cap.key, "mode": mode,
                        "required": "answer" if usable else "refuse",
                        "stratum": _stratum(cap, mode),
                        "base_question": cap.question})
    return out


def generate(framings: int) -> list[dict]:
    n = max(1, min(framings, len(FRAMINGS)))
    items = []
    for c in cells():
        for label, template in FRAMINGS[:n]:
            q = _MODE_CLAUSE[c["mode"]] + c["base_question"].strip()
            items.append({
                "id": f"{c['capability']}__{c['mode']}__{label}",
                "capability": c["capability"], "mode": c["mode"], "framing": label,
                "kind": c["stratum"], "required": c["required"],
                "ask": template.format(q=q),
            })
    return items


def census(items: list[dict]) -> dict:
    by_stratum = collections.Counter(i["kind"] for i in items)
    by_required = collections.Counter(i["required"] for i in items)
    headline = [i for i in items if i["kind"] != "no_corpus_mode"]
    return {
        "n_items": len(items),
        "n_cells": len({(i["capability"], i["mode"]) for i in items}),
        "framings_per_cell": len({i["framing"] for i in items}),
        "by_stratum": dict(by_stratum),
        "by_required": dict(by_required),
        "headline_items": len(headline),
        "headline_by_required": dict(collections.Counter(i["required"] for i in headline)),
        "note": ("`no_corpus_mode` items are refusals because that elongation model has no runs, not because "
                 "the simulator cannot represent the quantity. Report them as a separate stratum; folding "
                 "them into the headline inflates n with easy refusals."),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--framings", type=int, default=1, help=f"paraphrases per cell (1-{len(FRAMINGS)})")
    ap.add_argument("--out", default="", help="write the item list here (JSON)")
    ap.add_argument("--stats", action="store_true", help="print the census and exit")
    a = ap.parse_args(argv)

    items = generate(a.framings)
    stats = census(items)
    print(json.dumps(stats, indent=1))
    if a.stats:
        return 0
    if not a.out:
        print("\n(no --out given; nothing written)", file=sys.stderr)
        return 0
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"generated_by": "scripts/gen_limits_questions.py",
                                       "framings": [f[0] for f in FRAMINGS[:a.framings]],
                                       "census": stats, "questions": items}, indent=1) + "\n",
                           encoding="utf-8")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
