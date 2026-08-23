"""The nine-question discrimination test, with the scoring model named on every row.

The paper reported this as "two independent language models", which is not a specification: it cannot be
re-run from the paper, and it hides the fact that the deterministic arm involves no model at all. This
script pins the exact model IDs, writes a JSON artifact, and records WHICH elongation model each question
is asked under — because "does the leucine isoacceptor question get refused" has three different correct
answers depending on that.

Three arms:
  * registry   — `capability.check()` called directly, no language model in the loop. This is the ground
                 truth the other two arms are scored against.
  * each model — Cellwright answering in ordinary language with the full tool surface.

Run:  python scripts/run_discrimination_test.py [--models claude-sonnet-5,claude-opus-4-8]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cellarium import agent, credentials  # noqa: E402
from src.cellarium import capability as C  # noqa: E402

# Every item names the elongation model it is asked under. Where that is None the question is not about a
# charging channel and the model does not change the answer.
QUESTIONS = [
    dict(id="rrna_operon", kind="representational", mode="steady_state",
         capability="operon_specific_rrna_knockout", required="refuse",
         ask="Delete one specific rRNA operon and tell me the growth phenotype."),
    dict(id="rrna_total", kind="control", mode="steady_state",
         capability=None, required="answer",
         ask="What happens to growth when total rRNA synthesis capacity is cut to three sevenths?"),
    dict(id="iso_default", kind="resolution", mode="steady_state",
         capability="per_isoacceptor_trna_charging", required="refuse",
         ask="Which leucine tRNA isoacceptor loses its charge first under starvation?"),
    dict(id="iso_kinetic", kind="resolution", mode="kinetic",
         capability="per_isoacceptor_trna_charging", required="refuse",
         ask="Under the kinetic tRNA charging model, which leucine isoacceptor loses its charge first?"),
    dict(id="iso_coarse", kind="resolution", mode="coarse_kinetic",
         capability="per_isoacceptor_trna_charging", required="refuse",
         ask="Under the coarse kinetic elongation model, what is the charged fraction of each tRNA?"),
    dict(id="mura", kind="specification", mode="steady_state",
         capability="knockout_of_a_multi_transcription_unit_gene", required="answer",
         ask="What is the phenotype of a murA knockout?"),
    dict(id="leub", kind="control", mode="steady_state",
         capability=None, required="answer",
         ask="What is the phenotype of a leuB knockout?"),
    dict(id="codon", kind="resolution", mode="steady_state",
         capability="codon_level_elongation", required="refuse",
         ask="Does codon usage change the peptide elongation rate?"),
    dict(id="ppgpp_kinetic", kind="representational", mode="kinetic",
         capability="ppgpp_stringent_response", required="refuse",
         ask="Under the kinetic elongation model, does ppGpp rise when amino acids run out?"),
]


def registry_arm() -> list[dict]:
    """Ground truth: the registry with no model in the loop.

    A capability of None means nothing in the registry blocks the question, which is the registry saying
    'answer it'. Anything else is scored by whether `check` reports the capability as usable in that mode.
    """
    out = []
    for q in QUESTIONS:
        if q["capability"] is None:
            verdict, why = "answer", "no registry entry blocks this question"
        else:
            cap = next(c for c in C.CAPABILITIES if c.key == q["capability"])
            usable = cap.present and q["mode"] in cap.holds_in and q["mode"] in C.MODES_IN_CORPUS
            verdict = "answer" if usable else "refuse"
            why = cap.refusal(q["mode"]) if verdict == "refuse" else "represented, and the corpus is in this mode"
        out.append(dict(id=q["id"], mode=q["mode"], required=q["required"], verdict=verdict,
                        correct=verdict == q["required"], why=why))
    return out


def model_arm(model: str) -> list[dict]:
    out = []
    for q in QUESTIONS:
        t0 = time.time()
        # KISS-2 Stage 0. Recording usage is the difference between a benchmark whose cost can be READ off its
        # own output and one that has to be re-estimated by assumption before it can be scaled. Nothing here
        # previously carried a token count, so the nine questions already run cannot be costed retroactively.
        usage: dict = {}
        try:
            answer = agent.run(q["ask"], verbose=False, model=model, max_turns=14,
                               on_usage=lambda u, _u=usage: _u.update(u))
        except Exception as exc:                       # one failed question must not lose the other eight
            out.append(dict(id=q["id"], mode=q["mode"], required=q["required"], verdict="error",
                            correct=False, error=f"{type(exc).__name__}: {exc}", answer=""))
            print(f"  {q['id']:14s} ERROR {type(exc).__name__}: {exc}", flush=True)
            continue
        low = answer.lower()
        refused = any(s in low for s in ("cannot represent", "cannot answer", "no run in the corpus",
                                         "does not represent", "refus", "not poolable", "absent mechanism"))
        verdict = "refuse" if refused else "answer"
        ok = verdict == q["required"]
        out.append(dict(id=q["id"], mode=q["mode"], required=q["required"], verdict=verdict, correct=ok,
                        proposes_run=("propose" in low or "new run" in low or "new campaign" in low),
                        seconds=round(time.time() - t0, 1), usage=usage or None, answer=answer))
        print(f"  {q['id']:14s} {verdict:7s} (need {q['required']:7s}) {'OK' if ok else 'MISS'} "
              f"{round(time.time()-t0)}s", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="claude-sonnet-5,claude-opus-4-8")
    ap.add_argument("--out", default="data/discrimination_test.json")
    ap.add_argument("--registry-only", action="store_true")
    a = ap.parse_args()

    results = {"generated": time.strftime("%Y-%m-%d %H:%M"),
               "corpus_modes": list(C.MODES_IN_CORPUS),
               "elongation_models": list(C.ELONGATION_MODES),
               "questions": QUESTIONS, "arms": {}}

    reg = registry_arm()
    results["arms"]["registry (no language model)"] = reg
    print(f"registry (no language model): {sum(r['correct'] for r in reg)}/{len(reg)}", flush=True)

    if not a.registry_only:
        credentials.load_into_env()
        for m in [s.strip() for s in a.models.split(",") if s.strip()]:
            print(f"\n{m}:", flush=True)
            arm = model_arm(m)
            results["arms"][m] = arm
            print(f"{m}: {sum(r['correct'] for r in arm)}/{len(arm)}", flush=True)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nwrote {a.out}", flush=True)
    for name, arm in results["arms"].items():
        print(f"  {name:32s} {sum(r['correct'] for r in arm)}/{len(arm)}")


if __name__ == "__main__":
    main()
