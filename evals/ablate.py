"""Role/gate ablation + baselines for the Socratic Council (paper Workstream C1/C2).

For each (case, config, replicate) we run council.deliberate with the config's knobs and grade the resulting
Hypothesis on a DE-CONFOUNDED operationalization-quality rubric — six criteria judgeable from the hypothesis
text ALONE (no literature answer key), so the metric measures *derivation quality*, not answer recall. Each
hypothesis is graded by an independent Claude judge AND a cross-family GPT judge (inter-rater robustness). The
rubric saturates (6 of 6 in every arm, checklist O.i.1), so `--no-rubric` skips it; the endpoint that varies is
the residual-defect count, scored afterwards by `evals/audit.py` over this artefact.

ARMS. Six run the Council with different parts switched off:
  full           proposer + skeptic + judge (the system)
  no_skeptic     proposer + judge. Also the judge's leave-one-IN arm: with the proposer always present, adding
                 one role to proposer_only is removing the other from full, so this is not run twice.
  skeptic_only   proposer + skeptic: the skeptic's leave-one-in arm
  proposer_only  one proposer call, no critique (the single-shot baseline)
  generic_judge  proposer + skeptic + a plain "is it good?" judge in place of the falsifiability rubric
  leaked         full, with the proposer handed the case's literature answer (the quarantine's positive control)
Two are DERIVED from the same sweep's `full` records, so they run after them (or from `--derive-from`):
  proposer_bestofN  single-shot drafts drawn until they have spent what `full` spent on that case (validation
                 item 3; tokens by default, `--budget-unit`), at most 12, then one kept by a rule that calls no
                 model: `score` (the spec's rule, `council._score` with the structural verdict) or `mbr` (among
                 the top-scoring drafts, the one sharing most words with the others). Both picks and the first
                 draft are stored, so the audit scores all three; `--select` names the one reported first,
                 `mbr` unless another is asked for (fixed 2026-11-24, before any best-of-N run). The
                 spec's rule scores 27 of the 30 stored single-shot drafts at its maximum, so alone it mostly
                 returns the first feasible draft.
  noise_skeptic  full, but no skeptic call: each round replays objections `full` raised against a DIFFERENT
                 case, in the shape `full` had on this one (count, severity, resolution round), matched on length
                 (validation item 5(d)'s irrelevant-objection control). A tie with `full` says the skeptic works
                 as a revision prompt with more context, not as a critic.
`--log-stop-rule` (item 5(d)): `full` records the round its early-stop rule would have fired, which branch (the
quota of doubt or two clean rounds), and what it would have returned, then runs to the round cap. The record's
`hypothesis` is what a normal run returns; the round-cap result is stored as `variants.all_rounds`, and
`llm_at_stop` is what a normal run spends.

WHAT IT SPENDS. Every record carries `llm` (the deliberation's calls, tokens and list-price cost, metered on
its own thread) and `grading_llm`. `--max-usd` stops the sweep before its metered spend passes the amount
(evals/costs.py: exit 4, a marked partial, the artefact untouched); five failed calls in a row stop it too (exit
3). A stopped sweep RESUMES: run the same command again and it keeps the partial's finished records, redoes the
ones that errored, and starts the cap from what they cost, so `--max-usd` is the budget for the whole sweep (a
partial from a different plan is refused, never mixed in). `--dry-run` prints the plan and its estimate and calls
nothing.

CASES. By default the ten exploratory cases the stored ablation ran on (`EXPLORATORY_IDS`); the other fifteen in
cases.py are held out for the confirmatory run, and naming one needs `--include-held-out`. Sampling temperature
is pinned (names the variance source). Output: evals/results/ablation.json (or --out).

Run: python evals/ablate.py --reps 3 --temperature 0.7
     python evals/ablate.py --configs full,proposer_only,proposer_bestofN --no-rubric --max-usd 20 --dry-run
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import api_keys  # noqa: E402
import cases as cases_mod  # noqa: E402
import costs  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from cellarium import council, instrument, observability, outage, provenance  # noqa: E402

CONFIGS = {
    "full":          dict(),                                        # proposer + skeptic + judge (the system)
    "no_skeptic":    dict(use_skeptic=False),                       # proposer + judge; the judge's leave-one-in
    "skeptic_only":  dict(use_judge=False),                         # proposer + skeptic; the skeptic's leave-one-in
    "proposer_only": dict(use_skeptic=False, use_judge=False),      # single-shot generation (the baseline)
    "generic_judge": dict(judge_mode="generic"),                   # proposer + skeptic + plain quality judge
    "leaked":        dict(),      # quarantine ABLATION: full system BUT the proposer is handed the answer key
}
DERIVED = ("proposer_bestofN", "noise_skeptic")   # built from the same sweep's `full` records; they run second
ARMS = tuple(CONFIGS) + DERIVED

# The ten cases the stored ablation (2026-07-11) ran on. The other fifteen in cases.py are held out for the
# confirmatory run (BACKLOG PUB-A3).
EXPLORATORY_IDS = ("1.1", "1.2", "2.1", "2.2", "3.1", "4.1", "4.2", "5.1", "6.1", "6.2")

BUDGET_UNITS = ("tokens", "usd", "output_tokens", "calls")
SELECTORS = ("score", "mbr")
N_MAX = 12                     # best-of-N never draws more drafts than this, whatever the budget
_RUBRIC = ("falsifiable", "specified", "operationalized", "discriminating")
_WORD = re.compile(r"[a-z0-9]+")

# Six operationalization-quality criteria — judgeable from the hypothesis text alone (NO answer key).
Q = {
    "q1_falsifiable": "Names a concrete result that would REFUTE H1 — a risky prohibition that could actually fail.",
    "q2_operationalized": "Every construct is bound to a named measurable observable, AND the falsifier names a "
                          "statistical test and a numeric threshold.",
    "q3_discriminating": "At least one rival hypothesis is named with a distinguishing experiment/design that "
                         "would separate it from H1.",
    "q4_quantitative": "predicted_effect states a DIRECTION and a NUMERIC magnitude (a CV, fold-change, slope, "
                       "or threshold).",
    "q5_specified": "Independent variable (perturbation), dependent variable (observable), and predicted "
                    "direction are all present.",
    "q6_consistent": "No internal contradiction between H1, the falsifier, and the rival predictions.",
}

_SYS = (
    "You are grading the METHODOLOGICAL QUALITY of a scientific hypothesis produced for a whole-cell E. coli "
    "simulation. Judge ONLY the form: is it falsifiable, operationalized, discriminating, quantitative, "
    "well-specified, and internally consistent? Do NOT use any outside knowledge of what the biologically "
    "correct answer is — a well-formed hypothesis that happens to be wrong should still score well on form. "
    "Return one boolean per criterion.")


def _feasible(h) -> bool:
    return any(instrument.check_design(d)["usable"] for d in h.candidate_designs)


def _payload(case, h) -> dict:
    return {"question": case["question"], "criteria": Q,
            "hypothesis": h.model_dump(by_alias=True, mode="json"), "brief": h.brief()}


def grade_claude(case, h, client, model="claude-opus-4-8") -> dict:
    tool = {"name": "grade", "description": "Grade each operationalization-quality criterion.",
            "input_schema": {"type": "object",
                             "properties": {**{k: {"type": "boolean"} for k in Q}, "rationale": {"type": "string"}},
                             "required": list(Q)}}
    # NB: claude-opus-4-8 (reasoning model) rejects an explicit temperature; omit it (grader defaults suffice).
    t0 = time.monotonic()
    resp = client.messages.create(model=model, max_tokens=1024, system=_SYS, tools=[tool],
                                  tool_choice={"type": "tool", "name": "grade"},
                                  messages=[{"role": "user", "content": json.dumps(_payload(case, h))}])
    observability.emit(observability.usage_record("grader", model, resp, (time.monotonic() - t0) * 1000))
    # An unreadable grade is an error, not a grade. This returned {} for a reply with no tool block until
    # 2026-11-24, which `_score` reads as 0 of 6, and read a missing criterion as False. The defect auditor had the
    # same hole the other way round (an empty list is its BEST score), and its stored Claude column shows it fired
    # there; here the stored scores are 5 or 6 throughout, so this is preventive.
    if getattr(resp, "stop_reason", None) == "max_tokens":
        raise ValueError("the Claude grade was cut off at max_tokens=1024")
    block = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        raise ValueError(f"no grade tool block in the Claude reply (stop_reason={getattr(resp, 'stop_reason', None)})")
    g = dict(block.input or {})
    missing = [k for k in Q if k not in g]
    if missing:
        raise ValueError(f"the Claude grade is missing criteria: {', '.join(missing)}")
    return g


def grade_gpt(case, h, oai, model="gpt-4o") -> dict:
    prompt = (_SYS + "\n\nReturn a JSON object with exactly these boolean keys: " + ", ".join(Q)
              + ", plus a 'rationale' string.\n\n" + json.dumps(_payload(case, h)))
    t0 = time.monotonic()
    r = oai.chat.completions.create(model=model, temperature=0, response_format={"type": "json_object"},
                                    messages=[{"role": "user", "content": prompt}])
    observability.emit(costs.openai_record("grader_gpt", model, r, (time.monotonic() - t0) * 1000))
    # An unreadable reply is an error, not a grade. This returned {} until 2026-11-23, which scores 0 of 6: a judge
    # that said nothing readable recorded as one that found nothing (none in the stored 120 records).
    try:
        return json.loads(r.choices[0].message.content)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"the GPT grader's reply is not JSON ({exc}): "
                         f"{str(r.choices[0].message.content)[:120]!r}") from exc


def _score(g: dict) -> int:
    return sum(1 for k in Q if bool(g.get(k)))


# --- best-of-N: drafts at the Council's budget, kept by a rule that calls no model ------------------------

def _as_dict(h) -> dict:
    return h if isinstance(h, dict) else h.model_dump(by_alias=True, mode="json")


def _spent(summary: dict, unit: str) -> float:
    """How much of a budget one meter summary used, in `unit` (tokens = input + output + cache reads + writes)."""
    if unit == "usd":
        return float(summary.get("cost_usd") or 0.0)
    if unit == "calls":
        return float(summary.get("n_calls") or 0)
    if unit == "output_tokens":
        return float(summary.get("output_tokens") or 0)
    if unit == "tokens":
        return float(sum(int(summary.get(k) or 0) for k in
                         ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")))
    raise ValueError(f"unknown budget unit {unit!r}; one of {BUDGET_UNITS}")


def draft_score(h) -> int:
    """The spec's selection rule (validation item 3): `council._score` without a judge, so the verdict is the
    Council's own structural one. Deterministic: complete 8, a usable design 4, the four structural flags 4."""
    c = _as_dict(h)
    ok = council._structural_ok(c)
    return council._score(c, council._feasible(c), dict.fromkeys(_RUBRIC, ok))


def _words(h) -> set:
    c = _as_dict(h)
    f = c.get("falsifier") or {}
    text = " ".join(str(x or "") for x in (c.get("claim"), c.get("h1"), c.get("predicted_effect"),
                                           f.get("refuting_result")))
    return set(_WORD.findall(text.lower()))


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 1.0


def select(drafts: list, rule: str = "score") -> int:
    """The index of the draft best-of-N keeps. Both rules consider only the drafts with the highest
    `draft_score`. `score` (the spec's rule) then takes the first of them. `mbr` takes the one whose claim, H1,
    predicted effect and refuting result share the most words with all the other drafts (minimum Bayes risk with
    a word-overlap utility: self-consistency for free text); a tie goes to the earlier draft. No model call."""
    if rule not in SELECTORS:
        raise ValueError(f"unknown selection rule {rule!r}; one of {SELECTORS}")
    scores = [draft_score(d) for d in drafts]
    top = [i for i, s in enumerate(scores) if s == max(scores)]
    if rule == "score" or len(top) == 1:
        return top[0]
    words = [_words(d) for d in drafts]

    def consensus(i):
        return sum(_jaccard(words[i], words[j]) for j in range(len(drafts)) if j != i) / max(1, len(drafts) - 1)
    return max(top, key=lambda i: (consensus(i), -i))


def _best_of_n(rec: dict, case: dict, temperature, client, derived: dict, primary: str):
    budget = (derived.get("budgets") or {}).get(case["id"])
    if not budget:
        raise ValueError(f"no budget for case {case['id']}: no `full` record for it finished")
    unit = derived["unit"]
    drafts, spent = [], dict.fromkeys(BUDGET_UNITS, 0.0)
    while len(drafts) < N_MAX and (not drafts or spent[unit] < budget):
        with observability.meter(this_thread=True) as m:
            drafts.append(council.deliberate(case["question"], temperature=temperature, client=client,
                                             verbose=False, use_skeptic=False, use_judge=False))
        s = m.summary()
        for u in BUDGET_UNITS:
            spent[u] += _spent(s, u)
    picks = {rule: select(drafts, rule) for rule in SELECTORS}
    dumps = [d.model_dump(by_alias=True, mode="json") for d in drafts]
    keep = picks[primary]
    rec["best_of_n"] = {"n_drafts": len(drafts), "n_max": N_MAX, "unit": unit, "budget": budget,
                        "spent": {u: round(v, 6) for u, v in spent.items()}, "budget_reached": spent[unit] >= budget,
                        "scores": [draft_score(d) for d in dumps], "selected": picks, "primary": primary}
    rec["drafts"] = dumps
    others = {f"select_{rule}": i for rule, i in picks.items() if rule != primary}
    others["first_draft"] = 0
    rec["variants"] = {name: dumps[i] for name, i in others.items() if i != keep}
    return drafts[keep]


# --- the noise skeptic: objections raised against another question, replayed ------------------------------

def _seq(oid) -> tuple:
    """'r2.10' -> (2, 10), so objections replay in the order the Council numbered them."""
    m = re.fullmatch(r"r(\d+)\.(\d+)", str(oid or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (10 ** 6, 10 ** 6)


def noise_plans(full_recs: list, case_ids) -> dict:
    """For each `full` record: the debate's SHAPE (objections per round, their severity, the round that resolved
    each) with every objection's CONTENT (type and text) taken from the `full` runs of a different case.

    The donor is the next case in id order, wrapping round, so no case is its own donor; if that case's runs raised
    nothing, the next one that did. Within a severity each slot takes the unused donor objection whose text is
    closest in length (ties to the earlier one), so the replay carries about as many words as the original. The
    resolved ids are the original's, which the replay reproduces because the Council numbers a round's objections
    in order. Returns {(case_id, rep): {"donor", "rounds": {round: {"objections", "resolved"}}, "n"}}."""
    order = sorted(set(case_ids))
    if len(order) < 2:
        raise ValueError("the noise arm needs at least two cases: its objections come from a different question")
    pools: dict = {c: [] for c in order}
    for r in full_recs:
        if r.get("id") in pools:
            pools[r["id"]].extend(o for o in (r.get("hypothesis") or {}).get("objection_ledger") or []
                                  if isinstance(o, dict) and o.get("issue"))
    plans = {}
    for r in full_recs:
        cid = r.get("id")
        if cid not in pools:
            continue
        start = order.index(cid)
        donor = next((order[(start + k) % len(order)] for k in range(1, len(order))
                      if pools[order[(start + k) % len(order)]]), None)
        shape = sorted((r.get("hypothesis") or {}).get("objection_ledger") or [], key=lambda o: _seq(o.get("id")))
        if shape and donor is None:
            raise ValueError("no other case's `full` runs raised an objection, so there is nothing to replay")
        pool = pools.get(donor, [])
        used: set = set()
        rounds: dict = {}

        def slot(rnd, rounds=rounds):
            return rounds.setdefault(int(rnd), {"objections": [], "resolved": []})
        for o in shape:
            free = [i for i in range(len(pool)) if i not in used] or list(range(len(pool)))
            same = [i for i in free if pool[i].get("severity") == o.get("severity")] or free
            k = min(same, key=lambda i: (abs(len(pool[i]["issue"]) - len(str(o.get("issue") or ""))), i))
            used.add(k)
            slot(o.get("round") or _seq(o.get("id"))[0])["objections"].append(
                {"type": pool[k].get("type"), "severity": o.get("severity"), "issue": pool[k]["issue"]})
            if o.get("resolved_round"):
                slot(o["resolved_round"])["resolved"].append(o["id"])
        plans[(cid, r.get("rep"))] = {"donor": donor, "rounds": rounds, "n": len(shape)}
    return plans


def replay(plan: dict):
    """The `objection_source` that council.deliberate calls in place of the skeptic."""
    def source(rnd, cand, open_led):
        return copy.deepcopy(plan["rounds"].get(rnd, {"objections": [], "resolved": []}))
    return source


def derive(full_recs: list, case_ids, unit: str) -> dict:
    """What the derived arms need from finished `full` records: each case's budget (the mean over its reps of
    what a normal run spent, `llm_at_stop` when the stop rule was logged) and the noise plans."""
    if unit not in BUDGET_UNITS:
        raise ValueError(f"unknown budget unit {unit!r}; one of {BUDGET_UNITS}")
    by_case = defaultdict(list)
    for r in full_recs:
        s = r.get("llm_at_stop") or r.get("llm")
        if s:
            by_case[r["id"]].append(_spent(s, unit))
    budgets = {c: sum(v) / len(v) for c, v in by_case.items() if v}
    return {"unit": unit, "budgets": budgets, "noise": noise_plans(full_recs, case_ids),
            "n_full": len(full_recs)}


# --- one record --------------------------------------------------------------------------------------------

def _one_cell(case, cfg, rep, temperature, client, oai, gpt_model, claude_grader, *, rubric=True, log_stop=False,
              derived=None, select_primary="mbr"):
    rec = {"id": case["id"], "config": cfg, "rep": rep, "temperature": temperature}
    try:
        with observability.meter(this_thread=True) as gen:
            if cfg == "proposer_bestofN":
                h = _best_of_n(rec, case, temperature, client, derived or {}, select_primary)
            else:
                kw = dict(CONFIGS.get(cfg, CONFIGS["full"]))
                if cfg == "leaked":  # inject this case's canonical literature answer into the proposer (breaks quarantine)
                    kw["leak"] = case.get("canonical", "")
                if cfg == "noise_skeptic":
                    plan = ((derived or {}).get("noise") or {}).get((case["id"], rep))
                    if plan is None:
                        raise ValueError(f"no `full` record for case {case['id']} rep {rep} to take a shape from")
                    kw["objection_source"] = replay(plan)
                    rec["noise"] = {"donor": plan["donor"], "n_objections": plan["n"]}
                stop, snaps = None, []
                if log_stop and cfg == "full":
                    stop = {}
                    kw["log_stop"] = stop
                    kw["on_round"] = lambda _info, m=gen: snaps.append(m.summary())  # spend through each round
                h = council.deliberate(case["question"], temperature=temperature, client=client, verbose=False, **kw)
                if stop is not None:
                    rec["stop_log"] = {k: stop.get(k) for k in ("round", "branch", "quota_met", "stable", "rounds")}
                    rec["variants"] = {"all_rounds": h.model_dump(by_alias=True, mode="json")}
                    if stop.get("hypothesis") is not None:
                        h = stop["hypothesis"]                    # what a normal run returns
                        if len(snaps) >= stop["round"]:
                            rec["llm_at_stop"] = snaps[stop["round"] - 1]
        rec["llm"] = gen.summary()
        rec.update(converged=h.converged, rounds_used=h.rounds_used,
                   substantive_objections=h.substantive_objections, feasible=_feasible(h))
        if rubric:
            with observability.meter(this_thread=True) as gm:
                gc = grade_claude(case, h, client, claude_grader)
                rec["claude"] = {"score": _score(gc), **gc}
                if oai is not None:
                    gg = grade_gpt(case, h, oai, gpt_model)
                    rec["gpt"] = {"score": _score(gg), **gg}
            rec["grading_llm"] = gm.summary()
        rec["hypothesis"] = h.model_dump(by_alias=True, mode="json")
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


# --- the sweep ---------------------------------------------------------------------------------------------

def run(case_ids, configs, reps, temperature, out_path, gpt_model, claude_grader, workers=6, *, rubric=True,
        log_stop=False, select_primary="mbr", budget_unit="tokens", max_usd=None, derive_from=None):
    unknown = [c for c in configs if c not in ARMS]
    if unknown:
        raise ValueError(f"unknown arm(s) {unknown}; the arms are {list(ARMS)}")
    load_dotenv(str(Path(__file__).resolve().parents[1] / ".env"))
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from cellarium import llm
    client = llm.client(max_retries=6)  # ride out 429s under concurrency
    oai = None
    if os.environ.get("OPENAI_API_KEY"):
        import openai
        oai = openai.OpenAI(max_retries=6)

    cases = cases_mod.by_id(case_ids)
    base = [c for c in configs if c in CONFIGS]
    later = [c for c in configs if c in DERIVED]
    phase1 = [(c, cfg, rep) for c in cases for cfg in base for rep in range(reps)]
    phase2 = [(c, cfg, rep) for c in cases for cfg in later for rep in range(reps)]
    total = len(phase1) + len(phase2)
    results, lock = [], threading.Lock()
    meta = {"configs": configs, "reps": reps, "temperature": temperature, "claude_grader": claude_grader,
            "gpt_grader": gpt_model, "council_models": council._default_models(), "case_ids": [c["id"] for c in cases],
            "rubric": rubric, "log_stop_rule": log_stop, "select_primary": select_primary,
            "budget_unit": budget_unit, "max_usd": max_usd, "derived_from": derive_from or ("this sweep" if later else None),
            "environment": provenance.code_environment()}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # Progress goes to <out>.partial.json, and the artefact itself is written once, complete. Until 2026-11-23
    # every progress write went to `out_path`, so any interrupted re-run replaced the stored ablation with a
    # fragment of a new one. An outage now stops the run (checklist T.3) and leaves only the partial; so does
    # reaching the spend cap.
    brk = outage.Breaker()
    reserve = workers * costs.estimate_ablation(configs, 1, 1, log_stop=log_stop, rubric=rubric,
                                                gpt=oai is not None)["max_per_record_usd"] if max_usd else 0.0
    cap = costs.SpendCap(max_usd, reserve_usd=reserve)
    partial = Path(out_path).with_name(Path(out_path).stem + ".partial.json")
    done = 0

    # Resume: keep a stopped run's finished records, redo its errors, and count what it already spent.
    resumed: list = []
    if partial.exists():
        prev = json.loads(partial.read_text(encoding="utf-8"))
        differs = [k for k in _PLAN_KEYS if prev.get(k) != meta.get(k)]
        if differs:
            raise ValueError(f"{partial} is from a different plan ({', '.join(differs)} differ); move or delete it "
                             "to start over, or re-run with the plan that wrote it")
        resumed = [r for r in prev.get("results") or [] if "error" not in r]
    finished = {(r["id"], r["config"], r["rep"]) for r in resumed}
    for r in resumed:
        cap.add(*costs.record_cost(r.get("llm"), r.get("grading_llm")))
    results.extend(resumed)
    meta["resumed_records"] = len(resumed)
    done = len(resumed)
    phase1 = [t for t in phase1 if (t[0]["id"], t[1], t[2]) not in finished]
    phase2 = [t for t in phase2 if (t[0]["id"], t[1], t[2]) not in finished]
    if resumed:
        print(f"resuming: {len(resumed)} finished records kept from {partial} (${cap.spent:.2f} already spent)",
              flush=True)

    def _guarded(t, derived):
        if brk.tripped or cap.tripped:                    # checked where a call starts, so none starts after a trip
            return None
        rec = _one_cell(t[0], t[1], t[2], temperature, client, oai, gpt_model, claude_grader, rubric=rubric,
                        log_stop=log_stop, derived=derived, select_primary=select_primary)
        brk.observe("error" not in rec, (rec.get("error") or "").split(":")[0])
        cap.add(*costs.record_cost(rec.get("llm"), rec.get("grading_llm")))
        return rec

    def _pool(tasks, derived=None):
        nonlocal done
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_guarded, t, derived) for t in tasks]
            for fut in as_completed(futs):
                rec = fut.result()
                if rec is None:
                    continue
                with lock:
                    results.append(rec)
                    partial.write_text(json.dumps({**meta, "results": results}, indent=2), encoding="utf-8")
                done += 1
                cq = rec.get("claude", {}).get("score", "-")
                gq = rec.get("gpt", {}).get("score", "-")
                usd = (rec.get("llm") or {}).get("cost_usd")
                print(f"[{done}/{total}] {rec['id']:4s} {rec['config']:16s} rep{rec['rep']}: "
                      f"claude_q={cq}/6 gpt_q={gq}/6 conv={rec.get('converged')} rounds={rec.get('rounds_used')} "
                      f"${usd if usd is not None else '-'} spent=${cap.spent:.2f} {rec.get('error', '')}", flush=True)

    _pool(phase1)
    if phase2 and not (brk.tripped or cap.tripped):
        if derive_from:
            source = json.loads(Path(derive_from).read_text(encoding="utf-8"))["results"]
        else:
            source = results
        full = [r for r in source if r.get("config") == "full" and "error" not in r]
        if not full:
            raise ValueError("the derived arms need finished `full` records: add `full` to --configs or pass "
                             "--derive-from with an artefact that has them")
        _pool(phase2, derive(full, [c["id"] for c in cases], budget_unit))
    stopper = brk if brk.tripped else cap if cap.tripped else None
    if stopper is not None:
        partial.write_text(json.dumps({**meta, "stopped_early": stopper.report(total), "results": results},
                                      indent=2), encoding="utf-8")
        why = brk.message(total) if stopper is brk else stopper.report(total)["why"]
        print(f"\nSTOPPED: {why}\npartial results, not a result: {partial}", flush=True)
        return brk.exit_code() if stopper is brk else costs.EXIT_SPEND_CAP
    Path(out_path).write_text(json.dumps({**meta, "spent_usd": round(cap.spent, 4), "results": results}, indent=2),
                              encoding="utf-8")
    partial.unlink(missing_ok=True)
    print(f"\nwrote {len(results)} records -> {out_path} (metered ${cap.spent:.2f})", flush=True)
    return 0


# What must match for a partial to be resumed: anything that changes which records exist or how they were made.
_PLAN_KEYS = ("configs", "reps", "temperature", "case_ids", "rubric", "log_stop_rule", "select_primary",
              "budget_unit")


def held_out(ids) -> list:
    """The named case ids that are not exploratory."""
    return [i for i in ids if i not in EXPLORATORY_IDS]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ids", nargs="*", help="case ids; default: the ten exploratory cases (EXPLORATORY_IDS)")
    p.add_argument("--include-held-out", action="store_true",
                   help="allow case ids from the fifteen held out for the confirmatory run")
    p.add_argument("--configs", default="full,no_skeptic,proposer_only,generic_judge",
                   help=f"comma-separated arms from {', '.join(ARMS)}")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--gpt-model", default="gpt-4o")
    p.add_argument("--claude-grader", default="claude-opus-4-8")
    p.add_argument("--no-rubric", action="store_true", help="skip the six-criterion rubric (saturated, O.i.1)")
    p.add_argument("--log-stop-rule", action="store_true",
                   help="validation item 5(d): `full` logs its early stop and runs to the round cap")
    p.add_argument("--select", choices=SELECTORS, default="mbr",
                   help="the best-of-N rule reported first (both are computed and stored)")
    p.add_argument("--budget-unit", choices=BUDGET_UNITS, default="tokens")
    p.add_argument("--derive-from", help="a finished ablation artefact whose `full` records set the derived arms")
    p.add_argument("--max-usd", type=float, help="stop before the metered spend passes this (exit 4)")
    p.add_argument("--dry-run", action="store_true", help="print the plan and its estimate; call nothing")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "ablation.json"))
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args()
    ids = list(a.ids) or list(EXPLORATORY_IDS)
    if held_out(ids) and not a.include_held_out:
        p.error(f"{', '.join(held_out(ids))} are held out for the confirmatory run (BACKLOG PUB-A3); "
                "pass --include-held-out to use them")
    configs = a.configs.split(",")
    unknown = [c for c in configs if c not in ARMS]
    if unknown:
        p.error(f"unknown arm(s) {unknown}; the arms are {list(ARMS)}")
    est = costs.estimate_ablation(configs, len(ids), a.reps, log_stop=a.log_stop_rule, rubric=not a.no_rubric,
                                  gpt=True)        # the plan asked for, never the keys that happen to be present
    print(costs.render(est, title=f"ablation: {len(ids)} cases x {a.reps} reps"))
    if a.dry_run:
        print("\n(dry run -- nothing called)")
        return 0
    if a.max_usd is not None and a.max_usd <= a.workers * est["max_per_record_usd"]:
        p.error(f"--max-usd {a.max_usd} is below what {a.workers} records in flight could cost "
                f"(~${a.workers * est['max_per_record_usd']:.2f}); raise it or lower --workers")
    api_keys.require(api_keys.ANTHROPIC, *([] if a.no_rubric else [api_keys.OPENAI]),
                     hint="The six-criterion rubric grades with GPT as well; to run without it, pass --no-rubric.")
    return run(ids, configs, a.reps, a.temperature, a.out, a.gpt_model, a.claude_grader, a.workers,
               rubric=not a.no_rubric, log_stop=a.log_stop_rule, select_primary=a.select,
               budget_unit=a.budget_unit, max_usd=a.max_usd, derive_from=a.derive_from)


if __name__ == "__main__":
    raise SystemExit(main())
