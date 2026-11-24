"""What a paid evaluation costs: the meter for the calls `observability` cannot price (OpenAI), the spend cap that
stops a run before it passes the amount you approved, and the estimate quoted before a run.

THE CAP. `SpendCap(cap_usd, reserve_usd)` adds up the metered cost of every finished record and trips when the
total reaches `cap_usd - reserve_usd`. Like `outage.Breaker` it is consulted where a record STARTS, so nothing
starts after it trips; the reserve is held back for the records already in flight, so a run that trips finishes
inside the cap as long as no in-flight record costs more than reserve / workers. A call whose model has no price
trips it at once: a cap that cannot count a call cannot hold an approval. A capped run writes its partial and
exits `EXIT_SPEND_CAP` (4), distinct from an outage (3).

THE METER. Anthropic calls are priced by `observability.estimate_cost_usd` from each response's own usage. OpenAI
calls are priced here at the Standard-tier list price on OpenAI's pricing page, read 2026-11-24, with every input
token at the full rate (the page lists cached input at half), so the figure is a ceiling.

THE ESTIMATE. The `estimate_*` functions multiply measured sizes by one assumption:
  * the prompts the code sends, measured from the modules when called (system prompts and tool schemas);
  * reply sizes from the stored runs (hypotheses, grades, defect lists), with the two the stored runs do not
    keep (a skeptic's and a judge's reply) set as named constants;
  * rounds per Council run from the stored runs for the central case (the A/B's 25 Council runs for the full
    system, the ablation for the arms only it ran), the round cap for the high case;
  * the cost of a Cellwright arm as METERED in the stored A/B (`llm.cost_usd`), not estimated;
  * characters per token, MEASURED: 2.9 / 2.5 / 2.2 (low / central / high). The provider's token counter
    (free; it reproduced every billed call of M0, the first approved paid run, to a constant 124 tokens) puts
    these runs' prose system prompts at 2.67-2.89 characters per token and their JSON (tool schemas, hypotheses,
    defect lists, dial labels) at 1.99-2.78, mean 2.52, on claude-sonnet-5 and claude-opus-4-8 alike
    (2026-11-24). The bands used to assume 4.0 / 3.5 / 3.0, and M0 metered $2.67 against a "high" of $2.39. GPT
    calls get the same bands, which overstates them a little (its tokenizer packs more into a token);
  * a forced tool call's preamble, 124 input tokens on every Anthropic call (`TOOL_USE_TOKENS`), measured as the
    gap between the counter and M0's bills.
Caching follows `council._emit`: a role's system prompt and tool schema are cached after its first call and read
at 0.1x the input rate; a prefix under 1,024 tokens is not cacheable and is billed in full. Cache writes (1.25x,
once per role per five minutes) are left out. The HIGH case also drops every cache read, so it is a ceiling and
not merely a larger estimate (with the cache on, more tokens per character can push a prefix over the 1,024-token
threshold and make the "high" case cheaper). The estimate is for planning; the cap is what holds an approval.

    python evals/costs.py            # every prepared paid run: what it spends, low / central / high
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
REPO = HERE.parent

from cellarium import observability  # noqa: E402

EXIT_SPEND_CAP = 4

# USD per 1M tokens (input, output), Standard tier, developers.openai.com/api/docs/pricing, read 2026-11-24.
OPENAI_PRICES = {"gpt-4o": (2.50, 10.00)}

CHARS_PER_TOKEN = {"low": 2.9, "central": 2.5, "high": 2.2}          # measured 2026-11-24, see the docstring
BANDS = {"low": (2.9, True), "central": (2.5, True), "high": (2.2, False)}    # (characters per token, cache on)
TOOL_USE_TOKENS = 124   # input tokens a forced tool call adds to each Anthropic call (M0's bills minus the count)
CACHE_MIN_TOKENS = 1024
CACHE_READ = 0.1
ROUND_CAP = 4

# Reply sizes the stored runs do not keep, in characters. A skeptic's reply is a list of objections (the app store
# keeps a compact 730-character form per round; the emitted objects carry more fields); a judge's is six flags and
# a rationale.
SKEPTIC_REPLY = 1500
JUDGE_REPLY = 1000
DIGEST = 600            # the bounded "debate so far" every role sees after round 1
CRITERIA_REPLY = 1500   # a case-rubric judge's per-criterion verdicts (shared_metric, grade.llm_grade)


# --- prices, the meter, the cap ----------------------------------------------------------------------------

def _openai_key(model: str | None) -> str | None:
    """The OPENAI_PRICES row for a model id: an exact name or the name plus a date suffix. Not a bare prefix:
    gpt-4o-mini starts with gpt-4o and costs a fifteenth as much."""
    m = (model or "").lower()
    for k in OPENAI_PRICES:
        if m == k or re.fullmatch(re.escape(k) + r"-\d{4}-\d{2}-\d{2}", m):
            return k
    return None


def price(model: str | None):
    """(input, output) USD per 1M tokens, or None for a model in neither table."""
    if not model:
        return None
    p = observability._price(model)
    if p is not None:
        return p
    k = _openai_key(model)
    return OPENAI_PRICES[k] if k else None


def openai_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    k = _openai_key(model)
    if k is None:
        return None
    p_in, p_out = OPENAI_PRICES[k]
    return round((prompt_tokens * p_in + completion_tokens * p_out) / 1e6, 6)


def openai_record(role: str, model: str, resp, latency_ms: float) -> dict:
    """An observability-shaped record for one OpenAI chat completion, so the same meters count it."""
    usage = getattr(resp, "usage", None)
    pin = int(getattr(usage, "prompt_tokens", 0) or 0)
    pout = int(getattr(usage, "completion_tokens", 0) or 0)
    return {"role": role, "model": model, "request_id": getattr(resp, "id", None), "input_tokens": pin,
            "output_tokens": pout, "cache_read_tokens": 0, "cache_creation_tokens": 0,
            "latency_ms": int(latency_ms), "temperature": 0, "cost_usd": openai_cost(model, pin, pout)}


class SpendCap:
    """Trips when the metered spend reaches `cap_usd - reserve_usd`, or at the first record with an unpriced call.
    Thread-safe. `cap_usd=None` meters without ever tripping."""

    def __init__(self, cap_usd: float | None, reserve_usd: float = 0.0):
        if cap_usd is not None and cap_usd <= 0:
            raise ValueError(f"a spend cap must be positive, not {cap_usd}")
        if reserve_usd < 0 or (cap_usd is not None and reserve_usd >= cap_usd):
            raise ValueError(f"the reserve ({reserve_usd}) must be at least 0 and below the cap ({cap_usd})")
        self.cap_usd, self.reserve_usd = cap_usd, reserve_usd
        self.spent = 0.0
        self.n_records = 0
        self.unpriced = 0
        self.tripped_at: int | None = None
        self._lock = threading.Lock()

    def add(self, usd: float | None, partial: bool = False) -> bool:
        """Count one finished record's cost; `partial` = a call in it had no price. True on the call that trips."""
        with self._lock:
            self.n_records += 1
            if usd:
                self.spent += float(usd)
            if partial:
                self.unpriced += 1
            if self.cap_usd is None or self.tripped_at is not None:
                return False
            if self.unpriced or self.spent >= self.cap_usd - self.reserve_usd:
                self.tripped_at = self.n_records
                return True
            return False

    @property
    def tripped(self) -> bool:
        return self.tripped_at is not None

    def report(self, total: int) -> dict:
        why = ("a call had no price, so the cap could not count it" if self.unpriced else
               f"metered spend reached ${self.spent:.2f} of the ${self.cap_usd:.2f} cap "
               f"(${self.reserve_usd:.2f} held back for the records in flight)")
        return {"stopped_early": self.tripped, "reason": "spend cap", "after_records": self.tripped_at,
                "of": total, "cap_usd": self.cap_usd, "reserve_usd": round(self.reserve_usd, 4),
                "spent_usd": round(self.spent, 4), "unpriced_records": self.unpriced,
                "why": why if self.tripped else "the cap was not reached"}


def record_cost(*summaries) -> tuple[float, bool]:
    """Sum the `cost_usd` of observability meter summaries; the flag says a call in them had no price."""
    total, partial = 0.0, False
    for s in summaries:
        if not s:
            continue
        total += float(s.get("cost_usd") or 0.0)
        partial = partial or bool(s.get("cost_partial"))
    return total, partial


# --- the estimate ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Call:
    """One model call's size in characters: the cacheable prefix (system prompt + tool schema), the per-call
    payload, and the reply."""
    model: str
    prefix: int | float
    payload: int | float
    reply: int | float

    def usd(self, cpt: float, cache: bool = True) -> float:
        p = price(self.model)
        if p is None:
            raise ValueError(f"no list price for {self.model!r}; add it before estimating a run that uses it")
        anthropic = observability._price(self.model) is not None
        pre, pay, rep = self.prefix / cpt, self.payload / cpt, self.reply / cpt
        if anthropic:
            pay += TOOL_USE_TOKENS
        cached = cache and anthropic and pre >= CACHE_MIN_TOKENS
        return ((pre * (CACHE_READ if cached else 1.0) + pay) * p[0] + rep * p[1]) / 1e6


def _stored(name: str):
    p = REPO / "evals" / "results" / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _mean(xs, default):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else default


def sizes() -> dict:
    """Characters for every call an ablation, its audit and the A/B make, measured from the code and the stored
    runs (evals/results/ablation.json, audited.json, ab_ledger.json)."""
    import ablate
    import audit
    import cases as cases_mod
    import grade as grade_mod
    import shared_metric

    from cellarium import council, gate, instrument
    from cellarium.hypothesis import Hypothesis

    def J(x):
        return len(json.dumps(x))
    abl = (_stored("ablation.json") or {}).get("results") or []
    aud = (_stored("audited.json") or {}).get("results") or []
    ab = _stored("ab_ledger.json") or {}
    hyp = {cfg: _mean([J(r["hypothesis"]) for r in abl if r.get("config") == cfg and r.get("hypothesis")], 7000)
           for cfg in ("full", "proposer_only")}
    briefs = []
    for r in abl[:40]:
        try:
            briefs.append(len(Hypothesis.model_validate(r["hypothesis"]).brief()))
        except Exception:                                            # noqa: BLE001 - a size, not a check
            pass
    labels = instrument.dial_labels()
    rounds = {cfg: _mean([r.get("rounds_used") for r in abl if r.get("config") == cfg], None)
              for cfg in ("full", "no_skeptic", "proposer_only", "generic_judge")}
    ab_rounds = _mean([((s.get("b") or {}).get("hypothesis") or {}).get("rounds_used") for s in ab.values()], None)
    if ab_rounds:
        rounds["full"] = ab_rounds          # the A/B's 25 Council runs are newer than the 2026-07-11 ablation
    return {
        "question": _mean([len(c["question"]) for c in cases_mod.CASES], 300),
        "canonical": _mean([len(c.get("canonical", "")) for c in cases_mod.CASES], 400),
        "case_payload": _mean([J(shared_metric.payload(c, "")) for c in cases_mod.CASES], 1600),
        "hyp_full": hyp["full"], "hyp_single": hyp["proposer_only"], "brief": _mean(briefs, 0.7 * hyp["full"]),
        "labels": J(labels), "channels": J(instrument.channel_names()),
        "perturbations": J(sorted(labels.get("perturbations", {}))),
        "proposer_prefix": len(council._PROPOSER_SYS) + J(council._PROPOSE_TOOL),
        "skeptic_prefix": len(council._SKEPTIC_SYS) + J(council._SKEPTIC_TOOL),
        "judge_prefix": len(council._JUDGE_SYS) + J(council._JUDGE_TOOL),
        "generic_prefix": len(council._JUDGE_GENERIC_SYS) + J(council._JUDGE_GENERIC_TOOL),
        "grader_prefix": len(ablate._SYS) + 900, "criteria": J(ablate.Q),
        "grader_reply_claude": _mean([len(r["claude"].get("rationale", "")) for r in abl if r.get("claude")], 1400) + 200,
        "grader_reply_gpt": _mean([len(r["gpt"].get("rationale", "")) for r in abl if r.get("gpt")], 800) + 200,
        "auditor_prefix": len(audit._SYS) + 700,
        # The stored Claude lists that were readable average this; the ones cut off were longer, so the central
        # case adds a third.
        "auditor_reply_claude": 1.33 * _mean([J(r["claude_defect_list"]) for r in aud if r.get("claude_defects")], 2400),
        "auditor_reply_gpt": _mean([J(r["gpt_defect_list"]) for r in aud if "gpt_defect_list" in r], 900),
        "shared_prefix": len(shared_metric._JUDGE_SYS) + J(shared_metric._JUDGE_TOOL),
        "legacy_prefix": len(grade_mod._GRADER_SYS) + J(grade_mod._GRADE_TOOL),
        "agent_answer": _mean([(s.get("a") or {}).get("answer_chars") for s in ab.values()], 3200),
        "agent_usd": [((s.get("a") or {}).get("llm") or {}).get("cost_usd") for s in ab.values()
                      if ((s.get("a") or {}).get("llm") or {}).get("cost_usd") is not None],
        "gate_prefix": len(gate._PARSE_SYSTEM) + J(gate._PARSE_TOOL),
        "rounds": rounds,
    }


def _council_calls(s: dict, models: dict, *, leak: bool = False) -> dict:
    q = s["question"]
    first = q + s["labels"] + 350 + (s["canonical"] + 150 if leak else 0)
    later = first + s["hyp_full"] + SKEPTIC_REPLY + DIGEST
    review = q + s["hyp_full"] + SKEPTIC_REPLY + s["channels"] + DIGEST + 200
    return {
        "p1": Call(models["proposer"], s["proposer_prefix"], first, s["hyp_full"]),
        "p1_single": Call(models["proposer"], s["proposer_prefix"], first, s["hyp_single"]),
        "pn": Call(models["proposer"], s["proposer_prefix"], later, s["hyp_full"]),
        "skeptic": Call(models["skeptic"], s["skeptic_prefix"],
                        q + s["channels"] + s["perturbations"] + s["hyp_full"] + DIGEST + SKEPTIC_REPLY // 2 + 200,
                        SKEPTIC_REPLY),
        "judge": Call(models["judge"], s["judge_prefix"], review, JUDGE_REPLY),
        "generic": Call(models["judge"], s["generic_prefix"], review, 500),
    }


# The roles each arm calls every round besides the proposer, and whose stored round count stands in for it.
_ROLES = {"full": ("skeptic", "judge"), "leaked": ("skeptic", "judge"), "no_skeptic": ("judge",),
          "skeptic_only": ("skeptic",), "generic_judge": ("skeptic", "generic"), "noise_skeptic": ("judge",)}
_ROUNDS_FROM = {"full": "full", "leaked": "full", "no_skeptic": "no_skeptic", "skeptic_only": "full",
                "generic_judge": "generic_judge", "noise_skeptic": "full"}


def _rounds(arm: str, stored: dict, log_stop: bool, case: str, *, at_stop: bool = False) -> float:
    """Rounds one record of `arm` runs. In log mode `full` always runs to the cap, but what a normal run spends
    (best-of-N's budget) stops where the rule fires, which the stored mean estimates."""
    if arm == "full" and log_stop and not at_stop:
        return float(ROUND_CAP)
    if case == "high":
        return float(ROUND_CAP)
    return float(stored.get(_ROUNDS_FROM.get(arm, "full")) or stored.get("full") or 3.0)


def _generation_usd(arm: str, calls: dict, rounds: float, cpt: float, cache: bool = True) -> float:
    if arm == "proposer_only":
        return calls["p1_single"].usd(cpt, cache)
    return (calls["p1"].usd(cpt, cache) + max(rounds - 1, 0) * calls["pn"].usd(cpt, cache)
            + rounds * sum(calls[r].usd(cpt, cache) for r in _ROLES[arm]))


def _band(fn) -> dict:
    """{low, central, high} of fn(case, characters_per_token, cache_on)."""
    return {case: fn(case, cpt, cache) for case, (cpt, cache) in BANDS.items()}


def estimate_ablation(arms, n_cases: int, reps: int, *, log_stop: bool = False, rubric: bool = True,
                      gpt: bool = True, models: dict | None = None, claude_grader: str = "claude-opus-4-8",
                      claude_auditor: str = "claude-opus-4-8", gpt_model: str = "gpt-4o") -> dict:
    """USD for an ablation sweep: what ablate.py spends (generation and, unless `rubric=False`, the rubric
    graders) and what audit.py then spends on the same records, per arm, at low / central / high."""
    from cellarium import council
    s = sizes()
    models = models or council._default_models()
    q = s["question"]
    grade = q + s["criteria"] + s["hyp_full"] + s["brief"] + 100
    rubric_calls = [Call(claude_grader, s["grader_prefix"], grade, s["grader_reply_claude"])]
    audit_calls = [Call(claude_auditor, s["auditor_prefix"], q + s["hyp_full"] + 50, s["auditor_reply_claude"])]
    if gpt:
        rubric_calls.append(Call(gpt_model, 0, s["grader_prefix"] + grade + 300, s["grader_reply_gpt"]))
        audit_calls.append(Call(gpt_model, 0, s["auditor_prefix"] + 300 + q + s["hyp_full"], s["auditor_reply_gpt"]))
    calls = {arm: _council_calls(s, models, leak=(arm == "leaked")) for arm in arms}

    def per_record(arm, case, cpt, cache):
        spend = "high" if case == "high" else "central"
        if arm == "proposer_bestofN":       # matched to what full spends, overshooting by at most one draft
            gen = (_generation_usd("full", calls[arm], _rounds("full", s["rounds"], log_stop, spend, at_stop=True),
                                   cpt, cache) + calls[arm]["p1_single"].usd(cpt, cache))
        else:
            gen = _generation_usd(arm, calls[arm], _rounds(arm, s["rounds"], log_stop, spend), cpt, cache)
        graded = sum(c.usd(cpt, cache) for c in rubric_calls) if rubric else 0.0
        n_audits = 1 + (1 if (log_stop and arm == "full") else 0) + (2 if arm == "proposer_bestofN" else 0)
        return gen + graded, n_audits * sum(c.usd(cpt, cache) for c in audit_calls)

    n = n_cases * reps
    out: dict = {"arms": {}}
    for arm in arms:
        band = _band(lambda case, cpt, cache, arm=arm: per_record(arm, case, cpt, cache))
        out["arms"][arm] = {"records": n, "per_record": {k: round(sum(v), 4) for k, v in band.items()},
                            "ablate_usd": {k: round(n * v[0], 2) for k, v in band.items()},
                            "audit_usd": {k: round(n * v[1], 2) for k, v in band.items()}}
    for part in ("ablate_usd", "audit_usd"):
        out[part] = {k: round(sum(a[part][k] for a in out["arms"].values()), 2) for k in CHARS_PER_TOKEN}
    out["total_usd"] = {k: round(out["ablate_usd"][k] + out["audit_usd"][k], 2) for k in CHARS_PER_TOKEN}
    out["max_per_record_usd"] = max((a["per_record"]["high"] for a in out["arms"].values()), default=0.0)
    out["assumptions"] = {"council_models": models, "rubric": rubric, "gpt_judges": gpt, "log_stop": log_stop,
                          "rounds_central": {a: round(_rounds(a, s["rounds"], log_stop, "central"), 2)
                                             for a in arms if a in _ROUNDS_FROM},
                          "rounds_high": ROUND_CAP, "chars_per_token": CHARS_PER_TOKEN}
    return out


def estimate_audit(n_records: int, *, gpt: bool = True, claude_auditor: str = "claude-opus-4-8",
                   gpt_model: str = "gpt-4o") -> dict:
    """USD for auditing `n_records` hypotheses (audit.py), e.g. the 58 zeroed records with `gpt=False`."""
    s = sizes()
    q = s["question"]
    calls = [Call(claude_auditor, s["auditor_prefix"], q + s["hyp_full"] + 50, s["auditor_reply_claude"])]
    if gpt:
        calls.append(Call(gpt_model, 0, s["auditor_prefix"] + 300 + q + s["hyp_full"], s["auditor_reply_gpt"]))
    per = _band(lambda case, cpt, cache: sum(c.usd(cpt, cache) for c in calls))
    return {"records": n_records, "per_record": {k: round(v, 4) for k, v in per.items()},
            "total_usd": {k: round(n_records * v, 2) for k, v in per.items()}}


def estimate_trivial(n_cases: int, n_kinds: int = 3, *, gpt: bool = True, claude: str = "claude-opus-4-8",
                     gpt_model: str = "gpt-4o", judge: str = "claude-opus-4-8") -> dict:
    """USD for the trivial-answer probe: each constructed hypothesis graded by the rubric graders, both auditors
    and the A/B's shared judge."""
    s = sizes()
    q, hyp = s["question"], 2500                      # a constructed answer is short; 2,500 characters is generous
    grade = q + s["criteria"] + hyp + hyp + 100
    calls = [Call(claude, s["grader_prefix"], grade, s["grader_reply_claude"]),
             Call(claude, s["auditor_prefix"], q + hyp + 50, s["auditor_reply_claude"]),
             Call(judge, s["shared_prefix"], s["case_payload"] + hyp, CRITERIA_REPLY)]
    if gpt:
        calls += [Call(gpt_model, 0, s["grader_prefix"] + grade + 300, s["grader_reply_gpt"]),
                  Call(gpt_model, 0, s["auditor_prefix"] + 300 + q + hyp, s["auditor_reply_gpt"])]
    per = _band(lambda case, cpt, cache: sum(c.usd(cpt, cache) for c in calls))
    n = n_cases * n_kinds
    return {"records": n, "per_record": {k: round(v, 4) for k, v in per.items()},
            "total_usd": {k: round(n * v, 2) for k, v in per.items()}}


def estimate_ab(n_cases: int, reps: int, *, framings: int = 2, judge: str = "claude-opus-4-8",
                models: dict | None = None) -> dict:
    """USD for the A/B replication (PUB-A1): Cellwright (arm A) once per framing, the Council (arm B) once, each
    graded by the shared judge, and arm B also by its legacy case-rubric grader. Arm A's cost is the METERED mean
    of the stored A/B's 25 arm-A runs, scaled by 0.9 / 1.0 / 1.5 for low / central / high, because its cost
    varies by case (the stored maximum is about three times the mean)."""
    from cellarium import council
    s = sizes()
    models = models or council._default_models()
    calls = _council_calls(s, models)
    agent = statistics.fmean(s["agent_usd"]) if s["agent_usd"] else 0.35
    scale = {"low": 0.9, "central": 1.0, "high": 1.5}
    shared_b = Call(judge, s["shared_prefix"], s["case_payload"] + s["brief"], CRITERIA_REPLY)
    shared_a = Call(judge, s["shared_prefix"], s["case_payload"] + s["agent_answer"], CRITERIA_REPLY)
    legacy = Call(judge, s["legacy_prefix"], s["case_payload"] + s["hyp_full"] + s["brief"], CRITERIA_REPLY)

    def per_case(case, cpt, cache):
        b = (_generation_usd("full", calls, _rounds("full", s["rounds"], False, case), cpt, cache)
             + shared_b.usd(cpt, cache) + legacy.usd(cpt, cache))
        a = framings * (agent * scale[case] + shared_a.usd(cpt, cache))
        return a, b
    band = _band(per_case)
    n = n_cases * reps
    return {"cases": n_cases, "reps": reps, "framings": framings,
            "arm_a_usd": {k: round(n * v[0], 2) for k, v in band.items()},
            "arm_b_usd": {k: round(n * v[1], 2) for k, v in band.items()},
            "total_usd": {k: round(n * (v[0] + v[1]), 2) for k, v in band.items()},
            "arm_a_metered_mean_usd": round(agent, 4), "n_metered": len(s["agent_usd"])}


def estimate_gate(n_items: int, model: str = "claude-opus-4-8") -> dict:
    """USD for the gate eval: one parse call per item (scripts/run_gate_eval.py)."""
    s = sizes()
    call = Call(model, s["gate_prefix"], 300, 700)
    per = _band(lambda case, cpt, cache: call.usd(cpt, cache))
    return {"items": n_items, "per_item": {k: round(v, 5) for k, v in per.items()},
            "total_usd": {k: round(n_items * v, 2) for k, v in per.items()}}


def render(est: dict, title: str = "") -> str:
    """A plain table of an ablation estimate."""
    def usd(d):
        return f"${d['low']:.2f} / ${d['central']:.2f} / ${d['high']:.2f}"
    cpt = " / ".join(f"{v}" for v in CHARS_PER_TOKEN.values())
    lines = [f"{title} -- estimate, USD low / central / high ({cpt} characters per token, measured; "
             f"high also assumes no cache reads and the round cap)"]
    for arm, a in est["arms"].items():
        lines.append(f"  {arm:17s} {a['records']:4d} records  ablate {usd(a['ablate_usd'])}  audit {usd(a['audit_usd'])}")
    lines.append(f"  {'ablate.py':17s} {usd(est['ablate_usd'])}")
    lines.append(f"  {'audit.py':17s} {usd(est['audit_usd'])}")
    lines.append(f"  {'total':17s} {usd(est['total_usd'])}")
    lines.append(f"  Council models {est['assumptions']['council_models']}; rounds (central) "
                 f"{est['assumptions']['rounds_central']}, high {est['assumptions']['rounds_high']}")
    return "\n".join(lines)


PLANS = {
    # The prepared paid runs, so their figures are re-derivable: python evals/costs.py
    "M1 budget-matched arm (+ leave-one-in, leaked; re-runs full and proposer_only)": lambda: estimate_ablation(
        ["full", "no_skeptic", "skeptic_only", "proposer_only", "leaked", "proposer_bestofN"], 10, 3, rubric=False),
    "M2 stopping-rule regret + noise arm": lambda: estimate_ablation(["full", "noise_skeptic"], 10, 3, rubric=False,
                                                                       log_stop=True),
    "M1 + M2 in one sweep": lambda: estimate_ablation(
        ["full", "no_skeptic", "skeptic_only", "proposer_only", "leaked", "proposer_bestofN", "noise_skeptic"],
        10, 3, rubric=False, log_stop=True),
}


def main() -> int:
    for name, fn in PLANS.items():
        print(render(fn(), title=name), end="\n\n")
    print("re-audit of the 58 zeroed Claude audits (Claude only):", estimate_audit(58, gpt=False)["total_usd"])
    print("M3 gate eval, 288 items:", estimate_gate(288)["total_usd"])
    print("M4 trivial answers, 10 cases x 3 kinds:", estimate_trivial(10)["total_usd"])
    for n_cases in (10, 25):
        e = estimate_ab(n_cases, 5)
        print(f"M5 A/B replication, {n_cases} cases x 5 reps x 2 framings:", e["total_usd"],
              f"(arm A metered mean ${e['arm_a_metered_mean_usd']} over {e['n_metered']} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
