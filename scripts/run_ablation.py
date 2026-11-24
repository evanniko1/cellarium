"""The ungrounded baseline: the same nine questions with the harness removed.

The paper claims the harness is what makes the answers trustworthy, and until now the evidence for that was
that the grounded system scores well. That is not a comparison. A blind reviewer asked for exactly this
control -- "put the same questions to the same two models with no corpus, no registry, no quality control and
no depth matching, and report the difference" -- and the closest prior system in another domain (KISS,
arXiv:2605.17856) reports precisely this shape: agents with the scaffold succeed in up to 84% of trials,
agents without it plateau below 40%.

The ablated arm calls the same models with the same question text and no tools at all: no corpus, no raw
traces, no capability registry, no literature. It is `agent.converse` with a plain user turn, so the model
answers from its weights. Everything else -- the questions, the required responses, the rubric, the judges --
is held fixed, and the ablated replies are scored by the SAME rubric judges that scored the grounded arm, so
the comparison is of the harness and not of two scoring procedures.

What we expect, stated before running: an ungrounded model has no way to know that this particular simulator
copies one charging value across an isoacceptor family, or that a knockout silences a transcription unit
rather than a gene. It should therefore answer confidently where the grounded system declines. If instead it
declines at a similar rate, the harness is not doing the work we claim, and that is the finding.

Run:  python scripts/run_ablation.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cellarium import credentials, llm, observability  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_discrimination_test import QUESTIONS  # noqa: E402

MODELS = ("claude-sonnet-5", "claude-opus-4-8")
MAX_TOKENS = 2048
OUT = "data/ablation_ungrounded.json"

PREAMBLE = (
    "You are helping a biologist interpret results from a whole-cell computational model of Escherichia coli "
    "(the Covert lab model). Answer the question as directly and usefully as you can."
)


def _text(resp) -> str:
    return "".join(getattr(b, "text", "") for b in (getattr(resp, "content", None) or [])
                   if getattr(b, "type", "") == "text").strip()


def ungrounded_arm(model: str) -> list[dict]:
    """The same question, the same model, NO harness: one plain call with no system prompt and no tools, so the
    answer comes from the weights alone.

    Until 2026-11-24 this went through `agent.converse(..., max_turns=1)`, which always sends Cellwright's system
    prompt and its tools. The arm therefore saw the platform's instructions and ran at least one tool, and its one
    turn cut most replies off before any answer ("stopped: reached max turns without a synthesis" on 7 of 9 for
    claude-sonnet-5). tests/test_ungrounded_baseline.py pins this call's shape."""
    client = llm.client(max_retries=4)
    out = []
    for q in QUESTIONS:
        t0 = time.time()
        try:
            # metered like every other call site (observability.usage_record), so the record keeps the same
            # summary the agent loop's on_usage gave: tokens, cache reads and writes, estimated USD
            with observability.meter(this_thread=True) as m:
                resp = client.messages.create(model=model, max_tokens=MAX_TOKENS,
                                              messages=[{"role": "user", "content": PREAMBLE + "\n\n" + q["ask"]}])
                observability.emit(observability.usage_record("ungrounded", model, resp,
                                                              (time.time() - t0) * 1000))
            answer = _text(resp)
        except Exception as exc:
            out.append(dict(id=q["id"], mode=q["mode"], required=q["required"], verdict="error",
                            correct=False, error=f"{type(exc).__name__}: {exc}", answer=""))
            print(f"  {q['id']:14s} ERROR {type(exc).__name__}: {exc}", flush=True)
            continue
        out.append(dict(id=q["id"], mode=q["mode"], required=q["required"], verdict="unscored",
                        seconds=round(time.time() - t0, 1), usage=m.summary(), answer=answer))
        print(f"  {q['id']:14s} answered in {round(time.time() - t0)}s, {len(answer.split())} words",
              flush=True)
    return out


def main():
    credentials.load_into_env()
    data = {"note": "ungrounded ablation: same questions, same models; one plain call, no system prompt, no tools",
            "preamble": PREAMBLE, "questions": QUESTIONS, "arms": {}}
    for m in MODELS:
        print(f"\n{m} (ungrounded):", flush=True)
        data["arms"][m] = ungrounded_arm(m)
    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=2)
    print(f"\nwrote {OUT}")
    print("Now score it with the SAME rubric judges used for the grounded arm:")
    print(f"  python scripts/rescore_discrimination.py --in {OUT} --out data/ablation_rescored.json")


if __name__ == "__main__":
    main()
