"""Re-score the discrimination test from saved answers, with a rubric judge instead of a keyword list.

The first scorer matched a fixed phrase list ("cannot represent", "cannot answer", ...). It reported
claude-sonnet-5 at 6/9 and claude-opus-4-8 at 5/9, and every one of those misses that I read by hand was
a correct, substantive decline the list simply did not match: "I can't answer this from the corpus",
"I won't report a number here, because a number under this mode would be a fabrication", "I cannot read a
kinetic-mode result because none exists here", "reporting it ... would be fabricating a finding". A
keyword scorer measures its own vocabulary, not the system.

This re-scores the SAME stored answers, so it costs no simulation and no re-query of the agent. Two
independent judges, and where they disagree the item is reported as disputed rather than silently
resolved — a scorer that hides its own uncertainty is how 9/9 got claimed in the first place.

Run:  python scripts/rescore_discrimination.py [--in data/discrimination_test.json]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cellarium import agent, credentials      # noqa: E402

RUBRIC = """You are scoring whether an assistant DECLINED to answer a question, or ANSWERED it.

DECLINED means: it did not hand back the requested quantity/phenotype as a finding about the biology.
Saying why it cannot, naming another model that could, proposing a run, or redirecting to other data are
all still DECLINED - the decisive test is whether the reader is given the asked-for value as a result.

ANSWERED means: it gave the requested quantity or phenotype as a substantive finding, even if hedged,
caveated, or accompanied by a warning about interpretation.

A reply that answers a DIFFERENT but adjacent question (e.g. asked about one specific operon, it reports
the phenotype of deleting several) counts as ANSWERED, because the reader receives a finding.

Reply with exactly one JSON object and nothing else:
{"verdict": "declined" | "answered", "offered": "nothing" | "another_model" | "new_run" | "other_data",
 "quote": "<= 20 words quoted verbatim that decides it", "confidence": "high" | "low"}"""


def judge(model: str, question: str, answer: str) -> dict:
    prompt = (f"{RUBRIC}\n\nQUESTION ASKED:\n{question}\n\nASSISTANT REPLY:\n{answer[:6000]}\n\nJSON:")
    raw = agent.converse([{"role": "user", "content": prompt}], model=model, max_turns=1, verbose=False)
    m = re.search(r'\{.*\}', raw, re.S)
    if not m:
        return {"verdict": "unparsed", "offered": "", "quote": raw[:120], "confidence": "low"}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"verdict": "unparsed", "offered": "", "quote": m.group(0)[:120], "confidence": "low"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="data/discrimination_test.json")
    ap.add_argument("--out", default="data/discrimination_test_rescored.json")
    ap.add_argument("--judges", default="claude-opus-4-8,claude-sonnet-5")
    a = ap.parse_args()

    data = json.load(open(a.src, encoding="utf-8"))
    qtext = {q["id"]: q["ask"] for q in data["questions"]}
    judges = [s.strip() for s in a.judges.split(",") if s.strip()]
    credentials.load_into_env()

    out = {"source": a.src, "judges": judges, "rubric": RUBRIC, "arms": {}}
    for arm, rows in data["arms"].items():
        if "registry" in arm:                       # the deterministic arm has no prose to judge
            out["arms"][arm] = {"scored_by": "registry, deterministic",
                                "correct": sum(r["correct"] for r in rows), "n": len(rows), "items": rows}
            print(f"{arm}: {sum(r['correct'] for r in rows)}/{len(rows)} (deterministic, unchanged)")
            continue
        items, agree = [], 0
        for r in rows:
            verdicts = {}
            for j in judges:
                v = judge(j, qtext[r["id"]], r.get("answer", ""))
                verdicts[j] = v
            vs = {v["verdict"] for v in verdicts.values()}
            disputed = len(vs) > 1
            agree += not disputed
            final = "disputed" if disputed else vs.pop()
            correct = (None if disputed else
                       (final == "declined") == (r["required"] == "refuse"))
            items.append(dict(id=r["id"], required=r["required"], keyword_verdict=r["verdict"],
                              judge_verdict=final, correct=correct, disputed=disputed,
                              judges={k: v for k, v in verdicts.items()}))
            flag = "DISPUTED" if disputed else ("OK" if correct else "MISS")
            print(f"  {r['id']:14s} keyword={r['verdict']:7s} judged={final:9s} need={r['required']:7s} {flag}",
                  flush=True)
        n_ok = sum(1 for i in items if i["correct"] is True)
        out["arms"][arm] = {"scored_by": "rubric judges " + ", ".join(judges),
                            "correct": n_ok, "n": len(items),
                            "disputed": sum(1 for i in items if i["disputed"]),
                            "judge_agreement": f"{agree}/{len(items)}", "items": items}
        print(f"{arm}: {n_ok}/{len(items)} by rubric  (judges agreed {agree}/{len(items)})\n", flush=True)

    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=2)
    print(f"wrote {a.out}")
    for arm, v in out["arms"].items():
        print(f"  {arm:32s} {v['correct']}/{v['n']}"
              + (f"  disputed {v['disputed']}" if v.get("disputed") else ""))


if __name__ == "__main__":
    main()
