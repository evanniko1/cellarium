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
push a system into answering -- and (b) whether errors are symmetric. The two directions are not equally bad:
declining or deferring what the corpus can answer is a usability cost, while answering with nothing behind the
answer is the failure the whole architecture exists to prevent, so they are reported separately rather than
summed. With three honest responses a wrong verdict has SIX shapes (`ERROR_SHAPES`), each counted in exactly one
direction; until 2026-11-23 only three were counted, and a wrong verdict on a `propose`-keyed item fell in none.

    python scripts/run_gate_eval.py --framings 1            # one framing per capability-mode cell -- the pilot
    python scripts/run_gate_eval.py --framings 8            # the full paraphrase sweep
    python scripts/run_gate_eval.py --framings 2 --dry-run  # price it, call nothing
    python scripts/run_gate_eval.py --heldout               # the frozen held-out set (refuses if edited)
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

from cellarium import gate, observability, outage, provenance  # noqa: E402

OUT_DIR = REPO / "evals" / "results"
VERDICTS = ("answer", "propose", "refuse")

# A question has three honest responses, so a wrong verdict has SIX possible shapes. Each is named once, in one
# of two directions. TOO CAUTIOUS costs the user an answer the corpus could give. TOO PERMISSIVE is what the
# architecture exists to prevent: a claim with no run behind it, or a run the model cannot represent.
#
# Until 2026-11-23 the report had two columns, answer -> {refuse, propose} and refuse -> answer, so a wrong
# verdict on a `propose`-keyed item fell in NEITHER. On the stored 8-framing run that was 10 of 27 errors, and
# "under_refusals: 0" was true only because its two answers with no run behind them were not counted
# (VALIDATION_LAYER_SPEC item 1; tests/test_gate_error_accounting.py).
ERROR_SHAPES: dict[tuple[str, str], tuple[str, str]] = {
    ("answer", "refuse"): ("too_cautious", "refused a question the corpus can answer"),
    ("answer", "propose"): ("too_cautious", "proposed a new run where the corpus already holds the answer"),
    ("propose", "refuse"): ("too_cautious",
                            "refused a question the model represents, where it should have proposed a run"),
    ("propose", "answer"): ("too_permissive",
                            "answered with no run behind it: the model represents this, the corpus holds none"),
    ("refuse", "answer"): ("too_permissive", "answered a question the model cannot represent"),
    ("refuse", "propose"): ("too_permissive", "proposed a run the model cannot represent"),
}


def _errors(recs: list[dict], key: str = "required") -> dict:
    """Every wrong verdict against `key`, in exactly one named shape -- or an exception.

    A wrong verdict the table cannot place RAISES rather than being skipped: a counter whose definition
    silently leaves a case out is the defect this replaced. A parser that returned no verdict at all (`got` is
    "error") is `no_verdict`, in neither direction, because nothing was decided."""
    shapes = {f"{a}->{b}": {"n": 0, "direction": d, "meaning": m} for (a, b), (d, m) in ERROR_SHAPES.items()}
    ids: dict[str, list[str]] = {"too_cautious": [], "too_permissive": [], "no_verdict": []}
    for r in recs:
        want, got = r[key], r["got"]
        if got == want:
            continue
        if want not in VERDICTS:
            raise ValueError(f"{r['id']}: the key {want!r} is not one of {VERDICTS}")
        if got not in VERDICTS:
            ids["no_verdict"].append(r["id"])
            continue
        if (want, got) not in ERROR_SHAPES:
            raise ValueError(f"{r['id']}: the wrong verdict {want} -> {got} has no named shape")
        s = shapes[f"{want}->{got}"]
        s["n"] += 1
        ids[s["direction"]].append(r["id"])
    wrong = sum(1 for r in recs if r["got"] != r[key])
    placed = sum(len(v) for v in ids.values())
    if placed != wrong:                       # unreachable through the loop above; asserted so it cannot drift
        raise AssertionError(f"{wrong} wrong verdicts but {placed} placed")
    return {"wrong": wrong,
            "too_cautious": len(ids["too_cautious"]),
            "too_permissive": len(ids["too_permissive"]),
            "no_verdict": len(ids["no_verdict"]),
            "too_permissive_ids": sorted(ids["too_permissive"]),
            "no_verdict_ids": sorted(ids["no_verdict"]),
            "by_shape": shapes}


def _items(framings: int) -> list[dict]:
    import gen_limits_questions as gen
    return gen.generate(framings)


HELDOUT = REPO / "evals" / "HELDOUT_GATE_QUESTIONS.json"
HELDOUT2 = REPO / "evals" / "HELDOUT_GATE_QUESTIONS_V2.json"


def _heldout_items() -> list[dict]:
    """The frozen held-out set, mapped to the record shape `_one` scores. Refuses to run if the items no longer
    match the hash committed when the set was frozen: a held-out set edited after a run is not held out."""
    import hashlib
    bank = json.loads(HELDOUT.read_text(encoding="utf-8"))
    lock = HELDOUT.with_suffix(".sha256").read_text(encoding="utf-8").split()[0]
    got = hashlib.sha256(json.dumps(bank["items"], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if got != lock:
        raise SystemExit("held-out items no longer match their lock; refusing to score an edited held-out set")
    return [{"id": i["id"], "capability": ",".join(i["required_capabilities"]) or None, "mode": i["mode"],
             "framing": i["category"], "kind": i["category"], "required": i["key"], "ask": i["question"],
             "required_judgement": i["key_judgement"], "registry_can_express": i["registry_can_express"]}
            for i in bank["items"]]


def _heldout2_items() -> list[dict]:
    """Held-out set v2, and it REFUSES while the set is unfrozen.

    GATE-8b-HO2. v2 exists because the four corrections (A-D) were designed with v1's results in view, so
    v1 can no longer measure them. The same logic condemns v2 the moment it is scored before it is frozen:
    a set whose keys could still be edited after a run is a development set with a hash on it. Freezing
    needs somebody other than the author to have reviewed the sample -- see
    `scripts/build_heldout_bank_v2.py --freeze --reviewer`.

    A missing bank is an environment fact and a missing LOCK is a process fact, so they are separate
    messages: one means this checkout does not have the file, the other means the file is not ready."""
    import hashlib
    if not HELDOUT2.exists():
        raise SystemExit(f"{HELDOUT2.name} is not in this checkout; nothing follows about whether v2 "
                         f"exists elsewhere. Build it with scripts/build_heldout_bank_v2.py.")
    bank = json.loads(HELDOUT2.read_text(encoding="utf-8"))
    lock_path = HELDOUT2.with_suffix(".sha256")
    if not lock_path.exists() or bank.get("status") != "frozen":
        raise SystemExit(
            "held-out set v2 is NOT FROZEN, so it cannot be scored. Scoring it now would spend the only "
            "documents that can measure GATE-8b A-D on a set whose keys are still editable. It is frozen "
            "by `scripts/build_heldout_bank_v2.py --freeze --reviewer \"Name, YYYY-MM-DD\"`, and the "
            "reviewer must be somebody other than the author of the requirements -- that is the whole "
            "reason the second set exists. The sample to review is evals/HELDOUT_V2_REVIEW_PACKET.md.")
    lock = lock_path.read_text(encoding="utf-8").split()[0]
    got = hashlib.sha256(
        json.dumps(bank["items"], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if got != lock:
        raise SystemExit("held-out v2 items no longer match their lock; refusing to score an edited set")
    return [{"id": i["id"], "capability": ",".join(i["required_capabilities"]) or None, "mode": i["mode"],
             "framing": i["category"], "kind": i["category"], "required": i["key"], "ask": i["question"],
             "required_judgement": i["key_judgement"], "registry_can_express": i["registry_can_express"]}
            for i in bank["items"]]


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
    return "propose" if C.represents(cap, item["mode"]) else "refuse"


def _guarded(it: dict, model: str, brk: outage.Breaker) -> dict | None:
    """One item, unless the run is stopping: then None, and the item never starts. The breaker is consulted
    here, where the call starts, so no call begins after it trips (checklist T.3)."""
    if brk.tripped:
        return None
    rec = _run_one(it, model)
    brk.observe(not rec["parser_failed"], rec["parser_error"] or "")
    return rec


def _run_one(it: dict, model: str) -> dict:
    """The record of one item: its result, or an error record when the harness itself raised."""
    try:
        return _one(it, model)
    except Exception as e:                                       # noqa: BLE001 - recorded below
        return {"id": it["id"], "capability": it["capability"], "mode": it["mode"],
                "framing": it["framing"], "kind": it["kind"], "required": it["required"],
                "got": "error", "correct": False, "observable": "", "granularity": "",
                "dependencies": [], "parser_failed": True, "parser_error": type(e).__name__,
                "required_capabilities": [], "blocking": [], "route": "", "seconds": 0, "ask": it["ask"],
                "error": f"{type(e).__name__}: {e}"}


def _one(item: dict, model: str) -> dict:
    t0 = time.time()
    # S2-5: what each question cost, beside whether it was right. Questions run in worker threads, so the meter
    # keeps only this thread's calls. None when no call was metered: unknown, never zero.
    with observability.meter(this_thread=True) as m:
        req = gate.parse(item["ask"], model=model)
    d = gate.decide(req, mode=item["mode"])
    spend = m.summary()
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
        # The failure's type, so a run of them can be told apart from a run of hard items (checklist T.3).
        "parser_error": (req.parser or "").split("failed: ", 1)[1].rstrip(")") if "failed:" in (req.parser or "")
        else None,
        "required_capabilities": list(d.required_capabilities),
        "blocking": list(d.blocking), "route": d.route,
        "seconds": round(time.time() - t0, 2),
        "usd": spend["cost_usd"] if spend["n_calls"] and not spend["cost_partial"] else None,
        "ask": item["ask"],
        **({"required_judgement": item["required_judgement"],
            "correct_judgement": d.verdict == item["required_judgement"],
            "registry_can_express": item["registry_can_express"]} if "required_judgement" in item else {}),
    }


def _cost(recs: list[dict]) -> dict:
    """S2-5: the accuracy's price. Records carry `usd` from 2026-11-24; a run from before says it was not
    metered, so a reader never takes a missing cost for a free one."""
    usd = [r["usd"] for r in recs if r.get("usd") is not None]
    if not usd:
        return {"metered": False, "usd_per_question": None,
                "note": "not metered: these records predate per-question metering or made no priced call"}
    out = {"metered": True, "n_metered": len(usd), "usd_per_question": round(sum(usd) / len(usd), 6),
           "usd_total": round(sum(usd), 6)}
    if len(usd) < len(recs):
        out["note"] = f"{len(recs) - len(usd)} of {len(recs)} records unmetered; the mean is over the metered ones"
    return out


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
    errors = _errors(recs)
    over = sum(1 for r in recs if r["required"] == "answer" and r["got"] in ("refuse", "propose"))
    under = sum(1 for r in recs if r["required"] == "refuse" and r["got"] == "answer")

    relabelled = [r for r in recs if r["required"] != r["required_principled"]]
    corr_p = sum(r["correct_principled"] for r in recs)
    return {
        "n": n,
        "accuracy": round(correct / n, 3) if n else None,
        "accuracy_principled_key": round(corr_p / n, 3) if n else None,
        "items_where_the_two_keys_differ": sorted({r["id"].rsplit("__", 1)[0] for r in relabelled}),
        "errors": errors,
        **({"errors_principled_key": _errors(recs, "required_principled")} if relabelled else {}),
        "superseded_two_column_count": {
            "over_refusals": over, "under_refusals": under,
            "wrong_verdicts_in_neither_column": errors["wrong"] - over - under,
            "why": "the report's only two error columns until 2026-11-23: answer -> {refuse, propose} and "
                   "refuse -> answer. A wrong verdict on a propose-keyed item fell in neither. Kept so an "
                   "earlier citation can be reconciled; never a headline."},
        "parser_failures": sum(r["parser_failed"] for r in recs),
        "cost": _cost(recs),
        "by_kind": {k: {"n": len(v), "accuracy": round(sum(x["correct"] for x in v) / len(v), 3)}
                    for k, v in sorted(by_kind.items())},
        "by_framing": {k: {"n": len(v), "accuracy": round(sum(x["correct"] for x in v) / len(v), 3)}
                       for k, v in sorted(by_framing.items())},
        "confusion": {f"{a}->{b}": c for (a, b), c in sorted(confusion.items())},
        "granularity_extracted": dict(collections.Counter(r["granularity"] for r in recs)),
        # the clustered interval is defined for the generated bank (framings nested in capability x mode cells);
        # held-out items are distinct questions with no such nesting, so they do not get one
        **({"reliability": _reliability(recs)}
           if all("capability" in r and "mode" in r for r in recs)
           and not any("required_judgement" in r for r in recs) else {}),
        **(_heldout_report(recs) if any("required_judgement" in r for r in recs) else {}),
    }


def _reliability(recs: list[dict]) -> dict:
    """What the headline accuracy is worth: against what a system with no knowledge would score, and with an
    interval that respects how the items were drawn.

    BACKLOG V-1, both halves measured on the stored 216 records before this existed.

    TRIVIAL BASELINES. The gold labels are not balanced -- refuse 120, answer 72, propose 24 -- so a system
    that refuses everything, with no registry, no source probing and no reasoning, scores 0.556. Quoting 0.875
    against nothing invites a reader to compare it to 0.333 (chance over three verdicts), which overstates the
    margin by a factor of two. The Agentic Benchmark Checklist (arXiv:2507.02825) has this as R.13, "compare
    against trivial baselines", and O.b.3, "prevent success by guessing".

    THE CLUSTERED INTERVAL. The 216 records are 8 framings nested in 27 capability-by-mode cells. Framings of
    one cell share its answer, so they are not 216 independent trials, and the naive binomial interval
    understates the uncertainty -- measured, by 2.7x. The cluster is the CELL, not the record id: `id` is
    unique per record here, so the case-clustered helper in evals/aggregate.py, which clusters on `id`, would
    have produced the naive interval while appearing to cluster. With 27 clusters a t critical value on 26
    degrees of freedom is used rather than 1.96, as the clustered-SE literature recommends for few clusters
    (arXiv:2411.00640).
    """
    import math
    import statistics

    n = len(recs)
    acc = sum(1 for r in recs if r["correct"]) / n
    gold = collections.Counter(r["required"] for r in recs)
    baselines = {f"always_{v}": round(gold.get(v, 0) / n, 4) for v in ("refuse", "answer", "propose")}

    cells: dict[tuple, list[float]] = collections.defaultdict(list)
    for r in recs:
        cells[(r["capability"], r["mode"])].append(1.0 if r["correct"] else 0.0)
    means = [statistics.fmean(v) for v in cells.values()]
    k = len(means)
    se_cluster = statistics.stdev(means) / math.sqrt(k) if k > 1 else float("nan")
    se_naive = math.sqrt(acc * (1 - acc) / n)
    try:
        from scipy.stats import t as _t
        crit, crit_name = float(_t.ppf(0.975, k - 1)), f"t({k - 1})"
    except Exception:                                             # noqa: BLE001 - scipy is optional
        crit, crit_name = 1.96, "z (scipy absent; t unavailable)"
    half = crit * se_cluster
    best_baseline = max(baselines, key=baselines.get)
    return {
        "trivial_baselines": baselines,
        "best_trivial_baseline": {"strategy": best_baseline, "accuracy": baselines[best_baseline]},
        "margin_over_best_trivial": round(acc - baselines[best_baseline], 4),
        "n_clusters": k,
        "cluster_unit": "capability x mode",
        "items_per_cluster": sorted(collections.Counter(len(v) for v in cells.values()).items()),
        "accuracy_ci95_clustered": [round(acc - half, 4), round(acc + half, 4)],
        "ci95_half_width_clustered": round(half, 4),
        "ci95_half_width_naive": round(1.96 * se_naive, 4),
        "naive_understates_se_by": round(se_cluster / se_naive, 2) if se_naive else None,
        "critical_value": crit_name,
        "note": "the naive interval treats the framings of one cell as independent trials; they are not",
    }


def _heldout_report(recs: list[dict]) -> dict:
    """Held-out only. Items whose registry key differs from the judgement key test the REGISTRY, not the parser,
    so they are scored separately and never folded into the headline."""
    expr = [r for r in recs if r.get("registry_can_express")]
    gap = [r for r in recs if not r.get("registry_can_express")]
    return {"headline_items": len(expr),
            "headline_accuracy": round(sum(r["correct"] for r in expr) / len(expr), 3) if expr else None,
            "headline_errors": _errors(expr) if expr else None,
            # the old headline counted refuse -> answer only; on the stored run it said 2 where the count is 4
            "headline_under_refusals_superseded": sum(1 for r in expr
                                                      if r["required"] == "refuse" and r["got"] == "answer"),
            "registry_gap_items": len(gap),
            "registry_gap_correct_against_judgement": sum(r["correct_judgement"] for r in gap)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--framings", type=int, default=1, help="paraphrases per capability x mode cell (1-8)")
    ap.add_argument("--model", default=os.environ.get("CELLARIUM_GATE_MODEL", "claude-opus-4-8"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=str(OUT_DIR / "gate_eval.json"))
    ap.add_argument("--dry-run", action="store_true", help="list the items and exit; no model calls")
    ap.add_argument("--heldout", action="store_true",
                    help="score the frozen held-out set (evals/HELDOUT_GATE_QUESTIONS.json) instead")
    ap.add_argument("--heldout2", action="store_true",
                    help="score held-out set v2; REFUSES until it is frozen by a reviewer (GATE-8b-HO2)")
    ap.add_argument("--rescore", nargs="+", metavar="RESULTS_JSON",
                    help="recompute the report of stored results from their own records; no model call")
    ap.add_argument("--stop-after-failures", type=int, default=outage.DEFAULT_LIMIT,
                    help="stop when this many model calls in a row fail (default %(default)s); the partial "
                         "records go to <out>.partial.json and the exit code is 3")
    a = ap.parse_args(argv)

    if a.rescore:
        # The records are the measurement; the report is arithmetic over them. Re-deriving it after a change
        # to the arithmetic keeps every stored artefact true to the current definitions without re-asking the
        # model anything, and the records are written back byte-for-byte unchanged.
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for p in a.rescore:
            path = Path(p)
            d = json.loads(path.read_text(encoding="utf-8"))
            rep = _report(d["records"])
            for k in ("model", "framings", "wall_seconds", "environment"):   # the run's, not the rescorer's
                if k in d["report"]:
                    rep[k] = d["report"][k]
            rep["report_recomputed"] = f"{stamp} from the stored records; no model call"
            path.write_text(json.dumps({"report": rep, "records": d["records"]}, indent=1), encoding="utf-8")
            e = rep["errors"]
            print(f"{path.name}: {e['wrong']} wrong = {e['too_cautious']} too cautious + "
                  f"{e['too_permissive']} too permissive + {e['no_verdict']} no verdict")
        return 0

    if a.heldout and a.heldout2:
        raise SystemExit("--heldout and --heldout2 are different sets; score one of them.")
    if a.heldout2:
        items = _heldout2_items()
        if a.out == str(OUT_DIR / "gate_eval.json"):
            a.out = str(OUT_DIR / "gate_eval_heldout_v2.json")
        print(f"{len(items)} held-out v2 items, parser model {a.model}")
    elif a.heldout:
        items = _heldout_items()
        if a.out == str(OUT_DIR / "gate_eval.json"):
            a.out = str(OUT_DIR / "gate_eval_heldout.json")
        print(f"{len(items)} held-out items, parser model {a.model}")
    else:
        items = _items(a.framings)
        print(f"{len(items)} items ({a.framings} framing(s) x capability-mode cells), parser model {a.model}")
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
    # An outage must stop the run, not be scored: gate.parse proceeds on a blank requirement when its call fails,
    # so every item after an outage began would be graded as the ignorance rule (checklist T.3).
    brk = outage.Breaker(a.stop_after_failures)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(_guarded, it, a.model, brk) for it in items]
        for k, f in enumerate(as_completed(futs), 1):
            rec = f.result()
            if rec is not None:                                  # None: never started, the run was stopping
                recs.append(rec)                                 # every call that was made is on record
            if not brk.tripped and (k % 10 == 0 or k == len(items)):
                print(f"  {k}/{len(items)}")
    if brk.tripped:
        part = Path(a.out).with_name(Path(a.out).stem + ".partial.json")
        part.parent.mkdir(parents=True, exist_ok=True)
        rep = {"model": a.model, "framings": a.framings, "n_items_planned": len(items), "n_records": len(recs),
               "parser_failures": sum(r["parser_failed"] for r in recs),
               "wall_seconds": round(time.time() - t0, 1), "stopped_early": brk.report(len(items)),
               "environment": provenance.code_environment()}
        part.write_text(json.dumps({"report": rep, "records": recs}, indent=1), encoding="utf-8")
        print(file=sys.stderr)
        print(brk.message(len(items)), file=sys.stderr)
        print(f"partial records (no score; not a result): {part}", file=sys.stderr)
        return brk.exit_code()

    rep = _report(recs)
    rep["model"] = a.model
    rep["framings"] = a.framings
    rep["wall_seconds"] = round(time.time() - t0, 1)
    rep["environment"] = provenance.code_environment()   # what ran this, not what the lock says should (T.1)

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
