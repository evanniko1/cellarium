"""KISS-2: generate the limits benchmark from the capability registry, with ground truth by construction.

WHY GENERATE RATHER THAN WRITE. The nine hand-built questions in `run_discrimination_test.py` each carry a
`required` verdict a human decided. That does not scale, and n=1 per distinction is precisely what stops the
existing ablation (registry 9/9, grounded 8/9, ungrounded 6/9) from reporting per-item variance. What makes
scaling possible here is that the required verdict is not a judgement at all — `registry_arm` computes it:

    usable  = cap.present and mode in cap.holds_in and mode in MODES_IN_CORPUS
    required = "answer" if usable else "refuse"

So a (capability, mode) pair DETERMINES the answer key. The benchmark's real axis is therefore paraphrase —
how many ways a question can be asked about one distinction — not question count.

ONE PLACE THE KEY DELIBERATELY DIVERGES FROM `registry_arm`, and the divergence is itself a finding. The
registry answers "can the simulator REPRESENT this?". The benchmark asks "should the agent answer or
decline?". For a quantity that IS represented in a mode the corpus HAS, but for which no run carries the
needed perturbation, those give different answers — and the agent's is the right one. So `registry_arm` now
scores 26/27 rather than 27/27 on the generated set, and that missing point is not a bug: it is the registry
correctly reporting representational capability while the question also needed data coverage, which was never
its job. Report it, do not paper over it.

THE CELL CENSUS. Nine capabilities x three elongation models = 27 cells. Three strata are refusals about
DATA rather than representation and are reported APART from the headline, because folding them in measures
coverage while claiming to measure limits:

    stratum "representational"  the capability does not exist at all (present=False) -> refuse in every mode
    stratum "resolution"        it exists but not in this elongation model           -> refuse here, answer there
    stratum "supported"         represented, mode in corpus, AND a run exists        -> answer
    stratum "no_corpus_mode"    coarse_kinetic: that mode has no runs at all         -> refuse, reported apart
    stratum "no_corpus_data"    represented and in-corpus, but no run carries the
                                perturbation the question needs                      -> refuse, reported apart

Headline: **17 cells, 9 answer / 8 refuse** — near-balanced, and every refusal in it is about what the
simulator can represent. 9 fall in `no_corpus_mode` and 1 in `no_corpus_data`.

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


# WHAT ROWS EACH QUESTION ACTUALLY NEEDS, so the key stops conflating two different things.
#
# THE PILOT FOUND THIS, and it is worth being precise about what went wrong. The registry answers
# "can the simulator REPRESENT this?" — and the benchmark was scoring the agent as if it had answered
# "is there a RUN I can read?". On `nutrient_shift_timelines__kinetic` the agent declined because no run
# combines a timeline with the kinetic elongation model, and the key marked that a miss because the
# capability is present and kinetic is in the corpus. The agent was right.
#
# Measured across all 27 cells, exactly ONE is affected — the kinetic arm holds 8 rows (4 gene_knockout,
# 4 wildtype) and all 7 timeline rows are steady_state. So this is not a widespread defect, but the CAUSE is
# systemic: nothing checked coverage, and it would bite again the moment the corpus or the capability set
# moved. Explicit table rather than a heuristic, for the same reason `reconcile.NOT_A_MEASUREMENT` is
# explicit — and derived from what each QUESTION asks for, not from `markers`, which describe the CODE.
_NEEDS: dict[str, set[str] | None] = {
    "per_isoacceptor_trna_charging": None,             # charging channels ride on every run
    "codon_level_elongation": None,
    "operon_specific_rrna_knockout": {"rrna_operon_knockout"},
    "per_gene_trna_abundance": None,
    "knockout_of_a_multi_transcription_unit_gene": {"gene_knockout", "graded_gene_knockout"},
    "per_amino_acid_trna_charging": None,
    "ppgpp_stringent_response": {"ppgpp_conc", "condition", "gene_knockout"},
    "amino_acid_uptake_from_the_medium": {"condition", "timeline"},
    "nutrient_shift_timelines": {"timeline"},
}

_coverage_cache: dict[str, set[str]] | None = None


def corpus_coverage() -> dict[str, set[str]]:
    """`{elongation_model: {perturbations present}}`, read once from the manifest."""
    global _coverage_cache
    if _coverage_cache is None:
        from cellarium import corpus_schema as cs
        keys = list(cs.ARM_KEYS) + ["id", "ts", "reportable", "generations", "perturbation", "parca_ts"]
        i_el, i_p = keys.index("elongation_model"), keys.index("perturbation")
        cov: dict[str, set[str]] = {}
        for r in cs._rows():
            cov.setdefault(r[i_el], set()).add(r[i_p])
        _coverage_cache = cov
    return _coverage_cache


def has_data(cap_key: str, mode: str) -> bool:
    cov = corpus_coverage()
    if mode not in cov:
        return False
    need = _NEEDS.get(cap_key, None)
    return bool(cov[mode]) if need is None else bool(need & cov[mode])


def _stratum(cap, mode: str) -> str:
    if mode not in C.MODES_IN_CORPUS:
        return "no_corpus_mode"
    if not cap.present:
        return "representational"
    if mode not in cap.holds_in:
        return "resolution"
    # Represented AND in a mode the corpus has — but is there a run that could answer it?
    return "supported" if has_data(cap.key, mode) else "no_corpus_data"


def cells() -> list[dict]:
    """Every (capability, elongation model) pair with its answer key, computed the same way `registry_arm`
    computes it — deliberately the SAME expression, so the generator and the scorer cannot drift apart."""
    out = []
    for cap in C.CAPABILITIES:
        for mode in C.ALL_MODES:
            usable = cap.present and mode in cap.holds_in and mode in C.MODES_IN_CORPUS
            stratum = _stratum(cap, mode)
            # Represented but unrunnable is still a decline, and for a reason the agent can state. Keying it
            # `answer` scored the agent down for correctly saying "no run combines those conditions".
            required = "answer" if (usable and stratum != "no_corpus_data") else "refuse"
            out.append({"capability": cap.key, "mode": mode, "required": required,
                        "stratum": stratum, "base_question": cap.question})
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
    headline = [i for i in items if i["kind"] not in ("no_corpus_mode", "no_corpus_data")]
    return {
        "n_items": len(items),
        "n_cells": len({(i["capability"], i["mode"]) for i in items}),
        "framings_per_cell": len({i["framing"] for i in items}),
        "by_stratum": dict(by_stratum),
        "by_required": dict(by_required),
        "headline_items": len(headline),
        "headline_by_required": dict(collections.Counter(i["required"] for i in headline)),
        "note": ("Two strata are refusals about DATA, not about representation, and both are reported apart "
                 "from the headline. `no_corpus_mode`: that elongation model has no runs at all. "
                 "`no_corpus_data`: the simulator represents the quantity and the mode is in the corpus, but "
                 "no run carries the perturbation the question needs — the pilot found exactly one, "
                 "nutrient_shift_timelines under kinetic, where the agent declined correctly and the key "
                 "called it a miss. Folding either into the headline measures coverage, not limits."),
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
