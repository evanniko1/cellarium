"""NMI-1 — score the pre-dispatch gate against labels the registry generates, not labels a human wrote.

WHAT IS BEING MEASURED, and it is narrower than "is the system good". The gate has two halves with different
failure modes, and folding them together would hide which one is wrong:

  * the PARSER turns a question into a six-field requirement. It is a language model, it is stochastic, and
    it is the half that can be wrong in interesting ways -- most often by reading a question as finer- or
    coarser-grained than it is.
  * the DECISION is a table lookup over `capability.representable`. It is deterministic and is already pinned
    by `tests/test_gate.py`. If an item is scored wrong, the parser is why.

So this reports BOTH the end-to-end verdict accuracy and the extracted requirement for every item, because a
confusion matrix without the requirements tells you the gate was wrong and not what it misread.

THE LABELS ARE GENERATED, WHICH IS THE POINT. `gen_limits_questions.py` derives `required` from the registry:
a (capability, mode) pair determines whether the honest response is answer / refuse / propose, so no human
decided any answer key and the benchmark's real axis is PARAPHRASE -- how many ways one distinction can be
asked about. Eight framings exist, deliberately varied in register, because the failure being measured is a
system answering confidently when it should decline, and confidence is sensitive to how a question is posed.

WHAT A GOOD RESULT LOOKS LIKE, stated before the run so it cannot be chosen afterwards. The deterministic arm
scores 100% by construction and is not interesting. What is interesting is (a) whether the parser's
granularity extraction survives the adversarial framings -- `assumed` and `pressured` are the ones designed to
push a system into answering -- and (b) whether errors are symmetric. Over-refusal and under-refusal are not
equally bad here: refusing an answerable question is a usability cost, while admitting an unanswerable one is
the failure the whole architecture exists to prevent, so they are reported separately rather than summed.

    python scripts/run_gate_eval.py --framings 1            # 27 cells, one framing each -- the pilot
    python scripts/run_gate_eval.py --framings 8            # the full paraphrase sweep
    python scripts/run_gate_eval.py --framings 2 --dry-run  # price it, call nothing
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from cellarium import gate  # noqa: E402

OUT_DIR = REPO / "evals" / "results"


def _items(framings: int) -> list[dict]:
    import gen_limits_questions as gen
    return gen.generate(framings)


def principled_label(item: dict) -> str:
    """The generator's own stated principle, applied to the one stratum it does not apply it to.

    `gen_limits_questions` argues at length that "the model represents this, nobody has run it" must be
    `propose` and not `refuse`, because keying it `refuse` rewards stonewalling -- on an empty corpus every
    cell becomes that case and refusing everything scores perfectly. It then applies that rule to
    `no_corpus_data` (no run for this capability in a mode the corpus has) and NOT to `no_corpus_mode` (no
    run in this mode at all), where `usable` goes False for want of data and the key falls through to
    `refuse`.

    Two of the nine `coarse_kinetic` cells are represented in that mode -- nutrient shifts and multi-
    transcription-unit knockouts hold in all three -- so under the generator's own argument they are
    `propose`. The remaining seven are genuinely not represented there and stay `refuse`.

    THIS IS NOT APPLIED SILENTLY. Changing a benchmark's answer key in the direction that flatters a new
    component is exactly the move that deserves suspicion, so the eval reports accuracy against BOTH keys and
    names every item where they differ. The stored label stays the headline.
    """
    from cellarium import capability as C
    if item["kind"] != "no_corpus_mode":
        return item["required"]
    cap = C._BY_KEY.get(item["capability"])
    if cap is None:
        return item["required"]
    return "propose" if (cap.present and item["mode"] in cap.holds_in) else "refuse"


def _one(item: dict, model: str) -> dict:
    t0 = time.time()
    req = gate.parse(item["ask"], model=model)
    d = gate.decide(req, mode=item["mode"])
    return {
        "id": item["id"], "capability": item["capability"], "mode": item["mode"],
        "framing": item["framing"], "kind": item["kind"],
        "required": item["required"], "got": d.verdict,
        "correct": d.verdict == item["required"],
        "required_principled": principled_label(item),
        "correct_principled": d.verdict == principled_label(item),
        "observable": req.observable, "granularity": req.granularity,
        "dependencies": list(req.regulatory_dependencies),
        "parser_failed": "failed:" in (req.parser or ""),
        "required_capabilities": list(d.required_capabilities),
        "blocking": list(d.blocking), "route": d.route,
        "seconds": round(time.time() - t0, 2),
        "ask": item["ask"],
    }


def _report(recs: list[dict]) -> dict:
    n = len(recs)
    correct = sum(r["correct"] for r in recs)
    by_kind: dict[str, list[dict]] = collections.defaultdict(list)
    by_framing: dict[str, list[dict]] = collections.defaultdict(list)
    for r in recs:
        by_kind[r["kind"]].append(r)
        by_framing[r["framing"]].append(r)

    confusion = collections.Counter((r["required"], r["got"]) for r in recs)
    # the two error directions are not interchangeable and are never summed
    over = sum(1 for r in recs if r["required"] == "answer" and r["got"] in ("refuse", "propose"))
    under = sum(1 for r in recs if r["required"] == "refuse" and r["got"] == "answer")

    relabelled = [r for r in recs if r["required"] != r["required_principled"]]
    corr_p = sum(r["correct_principled"] for r in recs)
    return {
        "n": n,
        "accuracy": round(correct / n, 3) if n else None,
        "accuracy_principled_key": round(corr_p / n, 3) if n else None,
        "items_where_the_two_keys_differ": sorted({r["id"].rsplit("__", 1)[0] for r in relabelled}),
        "over_refusals": over,          # answerable, declined -- a usability cost
        "under_refusals": under,        # unanswerable, admitted -- the failure the architecture prevents
        "parser_failures": sum(r["parser_failed"] for r in recs),
        "by_kind": {k: {"n": len(v), "accuracy": round(sum(x["correct"] for x in v) / len(v), 3)}
                    for k, v in sorted(by_kind.items())},
        "by_framing": {k: {"n": len(v), "accuracy": round(sum(x["correct"] for x in v) / len(v), 3)}
                       for k, v in sorted(by_framing.items())},
        "confusion": {f"{a}->{b}": c for (a, b), c in sorted(confusion.items())},
        "granularity_extracted": dict(collections.Counter(r["granularity"] for r in recs)),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--framings", type=int, default=1, help="paraphrases per capability x mode cell (1-8)")
    ap.add_argument("--model", default=os.environ.get("CELLARIUM_GATE_MODEL", "claude-opus-4-8"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=str(OUT_DIR / "gate_eval.json"))
    ap.add_argument("--dry-run", action="store_true", help="list the items and exit; no model calls")
    a = ap.parse_args(argv)

    items = _items(a.framings)
    print(f"{len(items)} items ({a.framings} framing(s) x 27 capability-mode cells), parser model {a.model}")
    print("required:", dict(collections.Counter(i["required"] for i in items)))
    print("strata:  ", dict(collections.Counter(i["kind"] for i in items)))
    if a.dry_run:
        for i in items[:4]:
            print(f"\n  [{i['required']}] {i['ask'][:130]}")
        print("\n(dry run -- nothing called)")
        return 0

    # Same boot hook every other eval runner uses: an explicit export wins, the keychain is the fallback.
    try:
        from cellarium import credentials
        credentials.load_into_env()
    except Exception as e:                                       # noqa: BLE001
        print(f"could not load stored credentials ({type(e).__name__}); relying on the environment", file=sys.stderr)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set and no stored key was found; the parser needs one.", file=sys.stderr)
        return 2

    recs: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(_one, it, a.model): it for it in items}
        for k, f in enumerate(as_completed(futs), 1):
            try:
                recs.append(f.result())
            except Exception as e:                               # noqa: BLE001
                it = futs[f]
                recs.append({"id": it["id"], "capability": it["capability"], "mode": it["mode"],
                             "framing": it["framing"], "kind": it["kind"], "required": it["required"],
                             "got": "error", "correct": False, "observable": "", "granularity": "",
                             "dependencies": [], "parser_failed": True, "required_capabilities": [],
                             "blocking": [], "route": "", "seconds": 0, "ask": it["ask"],
                             "error": f"{type(e).__name__}: {e}"})
            if k % 10 == 0 or k == len(items):
                print(f"  {k}/{len(items)}")

    rep = _report(recs)
    rep["model"] = a.model
    rep["framings"] = a.framings
    rep["wall_seconds"] = round(time.time() - t0, 1)

    print("\n=== gate eval ===")
    print(json.dumps(rep, indent=1))

    wrong = [r for r in recs if not r["correct"]]
    if wrong:
        print(f"\n--- {len(wrong)} wrong, with what the parser read ---")
        for r in wrong[:25]:
            print(f"  [{r['required']} -> {r['got']}] {r['capability']}/{r['mode']}/{r['framing']}")
            print(f"      read as observable={r['observable']!r} granularity={r['granularity']!r} "
                  f"deps={r['dependencies']}")

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"report": rep, "records": recs}, indent=1), encoding="utf-8")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
