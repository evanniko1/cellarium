"""M-8: analyst robustness pass — a GATED, heterogeneous adversarial check on a high-stakes grounded conclusion.

The Cellwright analyst can reach a conclusion that is an artifact of (a) which order it happened to read the evidence
in, or (b) a single reasoning pass that no one challenged. This pass hardens a conclusion the user will ACT on:

  * heterogeneous jurors — an analyst (weighs it), a verifier (re-derives the statistics), and a skeptic (tries to
    refute) — so agreement means the claim survived DIFFERENT failure modes, not three copies of one bias;
  * order-randomization — each juror sees the per-seed evidence in a different (deterministic) order, so a verdict
    that flips under reordering is flagged as order-sensitive rather than trusted;
  * a pure aggregation layer (`aggregate`) that turns the votes into one robustness verdict — unit-testable with no
    model in the loop.

It is TOKEN-COSTLY (a juror panel, each run over several orders) and so is meant to be GATED to high-stakes
conclusions — an essentiality/viability verdict, or a claim that will drive a wet-lab decision — not called on every
intermediate read. The evidence bundle is the SAME grounded numbers the analyst already read (via rigor.disconfirm);
the panel re-examines the INFERENCE, it never runs new sims.
"""

from __future__ import annotations

import json
import os
from collections import Counter

_VERDICTS = ("supported", "refuted", "underpowered")

# One shared structured-output tool for every juror — same shape so aggregate() can treat the votes uniformly.
_VERDICT_TOOL = {
    "name": "verdict",
    "input_schema": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": list(_VERDICTS),
                    "description": "supported = evidence backs the claim; refuted = it does not or is contradicted; "
                                   "underpowered = too few seeds / effect within noise to decide"},
        "rationale": {"type": "string"},
        "key_check": {"type": "string", "description": "the single decisive number or comparison you used"}},
        "required": ["verdict"]},
}

_ANALYST_SYS = (
    "You are the ANALYST on a robustness panel. You are GROUNDED — you see real grounded evidence (per-seed values, "
    "means, a Welch t, CIs, a corpus z). Weigh it FAIRLY and decide whether the stated CLAIM holds. Judge the "
    "evidence as given; the order the values are listed in is irrelevant and must not affect your verdict. Emit the "
    "verdict tool.")
_VERIFIER_SYS = (
    "You are the VERIFIER on a robustness panel. Do NOT take the summary statistics on trust — re-derive them from "
    "the raw per-seed values: is the effect actually larger than the replicate spread, do the CIs overlap, is n>=2 "
    "on both sides? If the numbers do not support the claim as stated (effect within noise, arithmetic off, n too "
    "small), say so. The listing order of the values is irrelevant. Emit the verdict tool.")
_SKEPTIC_SYS = (
    "You are the SKEPTIC on a robustness panel. Your job is to REFUTE the CLAIM: name the confound, the alternative "
    "explanation, the way the sample is too thin to conclude. If the evidence is genuinely decisive you must concede "
    "'supported' — but default to 'refuted' or 'underpowered' when the case is thin. The listing order of the values "
    "is irrelevant. Emit the verdict tool.")

_JURORS = (("analyst", _ANALYST_SYS), ("verifier", _VERIFIER_SYS), ("skeptic", _SKEPTIC_SYS))


def _rotate(seq: list, k: int) -> list:
    """Deterministic reordering by offset k (no RNG — reproducible, and Math.random is unavailable in workflows).
    A rotation preserves the exact multiset of values while changing their presentation order, which is precisely
    what an order-robust conclusion must be invariant to."""
    if not seq:
        return list(seq)
    k %= len(seq)
    return list(seq[k:]) + list(seq[:k])


def _order_variants(bundle: dict, n_orders: int) -> list[dict]:
    """`n_orders` copies of the evidence bundle with the per-seed value lists rotated by a different offset each —
    identical evidence, different order. A juror whose verdict changes across these is order-sensitive."""
    tv = list((bundle.get("target") or {}).get("values") or [])
    rv = list((bundle.get("reference") or {}).get("values") or [])
    out = []
    for k in range(max(1, n_orders)):
        b = json.loads(json.dumps(bundle))   # deep copy; bundle is plain JSON from rigor.disconfirm
        if "target" in b:
            b["target"]["values"] = _rotate(tv, k)
        if "reference" in b:
            b["reference"]["values"] = _rotate(rv, k)
        b["_order"] = k
        out.append(b)
    return out


def aggregate(votes: list[dict]) -> dict:
    """PURE decision layer (no model): fold the juror votes into one robustness verdict.

    votes: [{role, verdict, order, rationale?}, ...]. Returns the headline `verdict`:
      robust     — every juror 'supported' on every order, and no juror flipped across orders;
      refuted    — the skeptic (or a majority) says the claim does not hold;
      order_sensitive — a juror's verdict changed with the presentation order (the conclusion is fragile);
      underpowered — the modal verdict is 'underpowered' (decide nothing; get more seeds);
      contested  — jurors disagree without a clean majority.
    Plus the agreement fraction, the per-role verdicts, and any dissent, so the caller can show WHY."""
    votes = [v for v in votes if v and v.get("verdict") in _VERDICTS]
    if not votes:
        return {"verdict": "no_votes", "stable": False, "agreement": 0.0, "n_votes": 0,
                "by_role": {}, "note": "no juror returned a usable verdict."}

    # per-role: did this role flip across the orders it saw?  -> order sensitivity
    by_role: dict[str, list[str]] = {}
    for v in votes:
        by_role.setdefault(v["role"], []).append(v["verdict"])
    order_sensitive = sorted(r for r, vs in by_role.items() if len(set(vs)) > 1)

    tally = Counter(v["verdict"] for v in votes)
    top, top_n = tally.most_common(1)[0]
    agreement = round(top_n / len(votes), 3)
    unanimous_supported = set(tally) == {"supported"}
    skeptic_verdicts = by_role.get("skeptic", [])
    skeptic_refutes = "refuted" in skeptic_verdicts

    if order_sensitive:
        verdict = "order_sensitive"
    elif unanimous_supported:
        verdict = "robust"
    elif skeptic_refutes or top == "refuted":
        verdict = "refuted"
    elif top == "underpowered":
        verdict = "underpowered"
    else:
        verdict = "contested"

    return {
        "verdict": verdict,
        "stable": verdict == "robust",
        "agreement": agreement,
        "n_votes": len(votes),
        "n_orders": len({v.get("order") for v in votes}),
        "tally": dict(tally),
        "by_role": {r: (vs[0] if len(set(vs)) == 1 else sorted(set(vs))) for r, vs in by_role.items()},
        "order_sensitive_roles": order_sensitive,
        "skeptic_refutes": skeptic_refutes,
        "dissent": [v for v in votes if v["verdict"] != "supported"],
        "note": {
            "robust": "Unanimous support, invariant to evidence order — the conclusion held under adversarial re-exam.",
            "order_sensitive": "A juror's verdict changed with the order the evidence was presented in — the "
                               "conclusion is fragile; do NOT rely on it without stronger data.",
            "refuted": "The skeptic (or a majority) does not accept the claim on this evidence.",
            "underpowered": "The panel judges the evidence too thin to decide — get more seeds before concluding.",
            "contested": "The jurors disagree without a clean majority — treat the conclusion as unsettled.",
        }.get(verdict, ""),
    }


def consistency_panel(claim: str, bundle: dict, *, client=None, models: dict | None = None,
                      n_orders: int = 2) -> dict:
    """Run the heterogeneous juror panel over a grounded evidence `bundle`, each juror across `n_orders` orderings.
    Returns {claim, verdict-aggregate, votes, evidence}. Every model call is metered (LLM-2, via council._emit).
    Deterministic evidence, so the ONLY variance is the model's reasoning — which is exactly what we're stress-testing.
    `n_orders` is capped (a juror panel is already token-costly); tests inject a FakeClient."""
    from . import council  # reuse the metered, cache-aware, retrying forced-tool call

    n_orders = max(1, min(int(n_orders), 3))
    if client is None:
        import anthropic
        client = anthropic.Anthropic(max_retries=4)
    model = (models or {}).get("judge") or os.environ.get("CELLARIUM_ROBUSTNESS_MODEL") or "claude-sonnet-5"
    variants = _order_variants(bundle, n_orders)

    votes: list[dict] = []
    for role, system in _JURORS:
        for var in variants:
            payload = {"claim": claim, "evidence": var,
                       "instruction": "Decide whether the CLAIM holds given the evidence. The value-listing order "
                                      "carries no information. Emit the verdict tool."}
            out = council._emit(client, model, system, _VERDICT_TOOL, payload,
                                max_tokens=1024, temperature=0.0, role=f"robustness:{role}")
            v = out.get("verdict")
            if v in _VERDICTS:
                votes.append({"role": role, "verdict": v, "order": var.get("_order", 0),
                              "rationale": out.get("rationale", ""), "key_check": out.get("key_check", "")})
    agg = aggregate(votes)
    return {"claim": claim, **agg, "votes": votes,
            "evidence": {"channel": bundle.get("channel"),
                         "target": (bundle.get("target") or {}).get("design"),
                         "reference": (bundle.get("reference") or {}).get("design"),
                         "welch_t": bundle.get("welch_t"), "significant": bundle.get("significant"),
                         "effect_pct": bundle.get("effect_pct")},
            "cost_note": f"{len(_JURORS)} jurors x {n_orders} order(s) = {len(_JURORS) * n_orders} model calls."}


def robustness_check(target: str, reference: str, channel: str, claim: str | None = None, *,
                     client=None, models: dict | None = None, n_orders: int = 2) -> dict:
    """Agent-facing entry: build the grounded evidence bundle for a `target`-vs-`reference` effect on `channel`
    (the SAME numbers rigor.disconfirm reads — no new sims), then run the adversarial, order-randomized juror panel
    on the CLAIM. GATED: call this only on a HIGH-STAKES conclusion (an essentiality/viability verdict, a claim that
    will drive a decision) — it spawns a juror panel and is token-costly. Returns the robustness verdict + votes."""
    from . import rigor

    bundle = rigor.disconfirm(target, reference, channel)
    if bundle.get("error"):
        return {"error": bundle["error"], "note": "no grounded evidence for this contrast — cannot run the panel."}
    claim = claim or (f"{target} differs from {reference} on {channel} "
                      f"(effect {bundle.get('effect_pct')}%, Welch t={bundle.get('welch_t')}).")
    return consistency_panel(claim, bundle, client=client, models=models, n_orders=n_orders)
