"""PARCA-6's free prerequisite — catch a stability claim that rests on a degradation rate which is NOT a fit.

THE GAP THIS CLOSES. `deg_rate_provenance` tells the AGENT, on request, whether a transcript's degradation
rate was inferred from data or is a constant wearing the same float type. But an agent has to think to ask,
and the failure mode is precisely that nobody thinks to ask: 854 of 3,133 mRNA units (27%), carrying 12.087%
of mRNA expression, are on a bound or imputed the population mean, and *"this transcript is unusually
stable"* is sayable about any of them with nothing to check it against.

WHY THIS IS THE THING TO DO BEFORE SPENDING AN ARM. PARCA-6 proposes carrying an `unknown` class INTO
`sim_data`, which costs a comparability arm: `transcription.py` becomes the 45th overlay file, `kb_sha256`
moves, and none of the 363 existing rows pool with the result. This check asks whether the arm is needed at
all — if a claim resting on a constant is caught at the point it is made, the flag inside `sim_data` may be
solving a problem that no longer bites. Answering that costs nothing; the arm costs comparator re-runs.

AND IT IS GENUINELY FREE, which is the load-bearing part. `data/parca/deg_rate_baseline.json` already carries
all 854 not-a-fit unit ids with their expression weights, frozen against a named `kb_sha256`. So this is a
dict lookup: no model image, no container, no ParCa, nothing to rebuild. If it needed a live
`deg_rate_provenance` call it would cost ~90 s per turn and would be switched off within a week.

THE CONJUNCTION IS THE WHOLE DESIGN. It fires only when a sentence BOTH names a not-a-fit unit AND makes a
degradation-flavoured claim. Naming `rpmJ` while discussing translation is not a half-life claim, and
flagging it would train the reader to skip the annotation — which is how a real one gets skipped too.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

BASELINE = Path(os.environ.get("CELLARIUM_DEG_BASELINE") or "data/parca/deg_rate_baseline.json")

# What the classes MEAN, in the same words the agent tool uses, so a reader meets one vocabulary not two.
_MEANS = {
    "floor": ("the rate FLOOR — the slowest single measured mRNA cistron in the organism, applied as a "
              "lower bound, not a fit for this unit"),
    "ceiling": ("the rate CEILING — the fastest single measured cistron, applied as an upper bound, not a "
                "fit for this unit"),
    "imputed": ("the MEAN of the reported half-lives — this unit's cistrons were never measured, so it "
                "carries a population default"),
}

# A sentence has to be ABOUT degradation for a not-a-fit unit in it to matter. Deliberately narrow: these are
# the words a half-life claim actually uses, not every word that co-occurs with one.
#
# A REGEX rather than a substring list, because the first version listed "half-life" and missed "half-lives" —
# the plural shares no stem with the singular ("half-lif" vs "half-liv"), so the single most common form of
# the key term was a false negative. Caught by probing the check with four sentences rather than one.
_DEG_RE = re.compile(
    r"half[- ]?li[fv]e|degrad|decay|turnover|stabilit|stable|unstable|long[- ]lived|short[- ]lived"
    r"|persist|lifetime", re.I)

_cache: dict | None = None


def _load(path: str | os.PathLike | None = None) -> dict:
    """The frozen baseline, or an explicit error. Never an empty dict — see `check`'s fail-closed branch."""
    global _cache
    if _cache is not None and path is None:
        return _cache
    p = Path(path or BASELINE)
    if not p.exists():
        return {"error": f"no frozen degradation baseline at {p}"}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"degradation baseline unreadable: {type(exc).__name__}: {exc}"}
    units = doc.get("units_not_a_fit") or {}
    index: dict[str, dict] = {}
    for cls in ("floor", "ceiling", "imputed"):
        for uid, pct in (units.get(cls) or {}).items():
            entry = {"unit": uid, "class": cls, "pct_of_mrna_expression": pct}
            index[uid.lower()] = entry
            # Prose says `rpmJ`, not `rpmJ[c]`; and `EG10149`, not `EG10149_RNA[c]`. Alias both, but ONLY
            # when the stripped form is distinctive enough to not collide with an ordinary word — a 2-letter
            # alias would match inside prose constantly.
            bare = re.sub(r"\[[a-z]\]$", "", uid)
            for alias in {bare, re.sub(r"_RNA$", "", bare)}:
                if len(alias) >= 4:
                    index.setdefault(alias.lower(), entry)
    out = {"kb_sha256": doc.get("kb_sha256"), "index": index,
           "n_not_a_fit": (doc.get("not_a_fit") or {}).get("n_units"),
           "pct_expression": (doc.get("not_a_fit") or {}).get("pct_expression")}
    if path is None:
        _cache = out
    return out


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def check(prose: str, *, path: str | os.PathLike | None = None) -> dict:
    """Does this answer make a degradation claim about a unit whose rate is not a fit?

    Verdicts: `could_not_verify` (no baseline — never a pass), `no_degradation_claims`, `clear`, or
    `claims_on_non_fits`.
    """
    base = _load(path)
    if base.get("error"):
        return {"verdict": "could_not_verify", "hits": [], "why": base["error"] + " — this check reports "
                "that it could not run, never that the answer passed"}
    index = base["index"]
    hits, seen = [], set()
    n_deg_sentences = 0
    for sent in _sentences(prose):
        if not _DEG_RE.search(sent):
            continue
        n_deg_sentences += 1
        for token in set(re.findall(r"[A-Za-z][A-Za-z0-9_.\[\]-]{3,}", sent)):
            entry = index.get(token.strip(".,;:)").lower())
            if entry and entry["unit"] not in seen:
                seen.add(entry["unit"])
                hits.append({**entry, "means": _MEANS[entry["class"]], "sentence": sent.strip()[:240]})
    common = {"kb_sha256": base["kb_sha256"], "n_degradation_sentences": n_deg_sentences,
              "corpus_not_a_fit": {"n_units": base["n_not_a_fit"], "pct_mrna_expression": base["pct_expression"]}}
    if not n_deg_sentences:
        return {**common, "verdict": "no_degradation_claims", "hits": []}
    if not hits:
        return {**common, "verdict": "clear", "hits": [],
                "why": "the answer makes degradation claims, and none of them names a unit that is not a fit"}
    return {**common, "verdict": "claims_on_non_fits", "hits": hits,
            "why": ("these transcripts' degradation rates are constants or bounds, not values inferred from "
                    "a measurement of them, so a claim about their stability rests on the estimator's "
                    "default rather than on data")}


def annotation(result: dict) -> str:
    """The note to append, or "" when there is nothing to say.

    Silent on `clear` and `no_degradation_claims` for the same reason the provenance check is: a banner on
    every answer saying "checked, fine" is a banner readers learn to skip.
    """
    v = result.get("verdict")
    if v == "claims_on_non_fits":
        lines = ["", "---",
                 "**Degradation-rate check — this answer rests on values that are not fits.** The claims are "
                 "left exactly as written; this is the record, not a correction."]
        for h in result["hits"][:6]:
            lines.append(f"- `{h['unit']}` — its rate is {h['means']} "
                         f"({h['pct_of_mrna_expression']}% of mRNA expression). In: “{h['sentence']}”")
        extra = len(result["hits"]) - 6
        if extra > 0:
            lines.append(f"- …and {extra} more.")
        c = result.get("corpus_not_a_fit") or {}
        lines.append(f"\nAcross this knowledge base, {c.get('n_units')} of 3,133 mRNA units carry a value that "
                     f"is not a fit, holding {c.get('pct_mrna_expression')}% of mRNA expression "
                     f"(kb `{str(result.get('kb_sha256'))[:8]}`). `deg_rate_provenance` reports the full "
                     f"picture for any unit.")
        return "\n".join(lines)
    if v == "could_not_verify":
        return ("\n\n---\n**Degradation-rate check could not run** — " + str(result.get("why", "")) +
                ". Treat this as unverified, not as verified.")
    return ""
