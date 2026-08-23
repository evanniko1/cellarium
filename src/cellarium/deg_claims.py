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

TWO SECTIONS, TWO PLACES A NUMBER CAN GO UNMARKED:

  (a) `check`/`annotation` — the PROSE check above. It reads the answer the model wrote.
  (b) `mark_payload` — PARCA-6 TIER 1. It reads the payload before the model writes anything.

WHY (b) EXISTS, AND WHY (a) WAS NOT ENOUGH. The incidental probe's one genuine failure was a protein copy
number — *"rpmJ protein sits at ~50 copies in the KO vs ~70 in wildtype"* — and (a) let it through, correctly
by its own contract: the sentence used no degradation vocabulary, so the conjunction never fired. The lesson
is not that the vocabulary list is too short. It is that a check keyed on PROSE is the wrong place to catch a
number that was already unmarked when it arrived. (b) marks the number at the read boundary instead, the way
`reconcile.mark_non_measurement` marks an iML1515 prediction — on the payload, in the same breath as the
value, rather than as an advisory the model reads after it has written the sentence.
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


# ------------------------------------------------------------------------------------------------------------
# (b) PARCA-6 TIER 1 — mark the NUMBER at the read boundary.
#
# The join that makes this possible is NOT free-by-inspection, and the Tier-1 design was wrong about that.
# The baseline names TRANSCRIPTION UNITS (`TU-8392[c]`); payloads name GENES (`rplE`, `EG10868-MONOMER`).
# Measured, a bare-symbol match against the baseline reaches 6 of 854 units and 1.708% of mRNA expression
# against 12.087% for the full set — so "a dict lookup over the ids we already have" would have shipped a
# check covering an eighth of what it claimed. `scripts/build_deg_alias_map.py` composes the four
# transcription-unit tables with `rnas.tsv` once, offline, and freezes the gene-space index; all 854 units
# resolve, giving 1,149 genes and 4,557 aliases. The RUNTIME is then genuinely the dict lookup that was
# promised — one JSON load, no model image.
# ------------------------------------------------------------------------------------------------------------

# EXPLICIT, not inferred, for the same reason `reconcile.NOT_A_MEASUREMENT` is: a heuristic that stamps the
# wrong payload is the false positive that gets the whole feature switched off. These are the tools whose
# results carry a per-gene or per-species QUANTITY — the numbers a reader quotes.
MARKED_TOOLS: frozenset[str] = frozenset({
    "mechanistic_scope",   # ko_footprint.measured — the probe's actual failure lives here
    "top_movers", "differential", "compare_at_generation",
    "read_species", "list_species", "regulon_response",
    "selective_charging", "trna_families",
})

_MARK_KEY = "parameter_provenance"

# Bounds on the payload walk. A tool result is a small dict; `read_raw_series`-shaped payloads are not in
# MARKED_TOOLS, but a bound is cheaper than trusting that to stay true.
_MAX_NODES = 4000
_MAX_DEPTH = 8
_ALIASES = Path(os.environ.get("CELLARIUM_DEG_ALIASES") or "data/parca/deg_rate_aliases.json")

_alias_cache: dict | None = None


def _load_aliases(path: str | os.PathLike | None = None) -> dict:
    """The frozen gene-space index, or an explicit error — never a silently empty map.

    An empty map would make every payload look clean, which is the silent-absence failure this whole module
    exists to prevent.
    """
    global _alias_cache
    if _alias_cache is not None and path is None:
        return _alias_cache
    p = Path(path or _ALIASES)
    if not p.exists():
        return {"error": f"no frozen degradation alias map at {p} "
                         f"(build it with scripts/build_deg_alias_map.py)"}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"degradation alias map unreadable: {type(exc).__name__}: {exc}"}
    out = {"alias": doc.get("alias") or {}, "genes": doc.get("genes") or {},
           "kb_sha256": doc.get("baseline_kb_sha256"), "n_genes": doc.get("n_genes")}
    if not out["alias"]:
        return {"error": f"degradation alias map at {p} carries no aliases"}
    if path is None:
        _alias_cache = out
    return out


def _looks_like_id(s: str) -> bool:
    """Identifier-shaped, so an English word in a free-text field cannot match a three-letter gene symbol.

    Payload keys and ids have no spaces; prose does. `mechanistic_scope`'s `note` is a paragraph and must
    never be scanned token-by-token — that is (a)'s job, under (a)'s much narrower conjunction.
    """
    return 3 <= len(s) <= 64 and " " not in s and "\n" not in s


def _walk(node, out: set, depth: int = 0, budget: list | None = None) -> None:
    """Collect identifier-shaped strings from a payload's keys and short string values, bounded."""
    budget = budget if budget is not None else [_MAX_NODES]
    if depth > _MAX_DEPTH or budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and _looks_like_id(k):
                out.add(k.lower())
            _walk(v, out, depth + 1, budget)
    elif isinstance(node, (list, tuple)):
        for v in node:
            if isinstance(v, (int, float)) or v is None:
                continue        # numeric arrays are the bulk of a payload and can hold no identifier
            _walk(v, out, depth + 1, budget)
    elif isinstance(node, str) and _looks_like_id(node):
        out.add(node.lower())


def payload_hits(out, *, path: str | os.PathLike | None = None) -> dict:
    """Which not-a-fit transcription units this payload's genes belong to.

    GROUPED BY UNIT, not by gene, because the unit is what the estimator failed to fit — the genes are its
    members. Ungrouped, a single ribosomal operon printed ten identical entries with ten identical
    explanations, which is the shape of an annotation a reader learns to scroll past.

    Returns `{"verdict": ..., "units": [...]}`. Verdicts: `could_not_verify` (no map — never a pass),
    `clear`, `rests_on_non_fits`.
    """
    base = _load_aliases(path)
    if base.get("error"):
        return {"verdict": "could_not_verify", "units": [], "why": base["error"]}
    seen: set = set()
    _walk(out, seen)
    genes: dict[str, dict] = {}
    for token in seen:
        gid = base["alias"].get(token)
        if gid and gid not in genes:
            genes[gid] = base["genes"].get(gid) or {}
    if not genes:
        return {"verdict": "clear", "units": [], "kb_sha256": base["kb_sha256"]}
    by_unit: dict[str, dict] = {}
    for gid, rec in genes.items():
        for i, unit in enumerate(rec.get("units") or []):
            u = by_unit.setdefault(unit, {"unit": unit, "genes_in_payload": [],
                                          "rate_class": (rec.get("cls") or [None])[min(i, len(rec.get("cls") or [None]) - 1)],
                                          "pct_of_mrna_expression": None})
            u["genes_in_payload"].append(rec.get("sym") or gid)
    # The per-unit share is the baseline's own number for that unit, not a per-gene total: `genes[*].pct`
    # sums a gene's units, so reading it back per unit would over-state a gene that sits in two of them.
    weights = _load()
    for unit, u in by_unit.items():
        entry = (weights.get("index") or {}).get(unit.lower()) if not weights.get("error") else None
        u["pct_of_mrna_expression"] = entry["pct_of_mrna_expression"] if entry else None
        if entry:
            u["rate_class"] = entry["class"]
        u["genes_in_payload"] = sorted(set(u["genes_in_payload"]))
    ranked = sorted(by_unit.values(), key=lambda u: -(u["pct_of_mrna_expression"] or 0.0))
    return {"verdict": "rests_on_non_fits", "units": ranked, "kb_sha256": base["kb_sha256"],
            "n_units_matched": len(ranked), "n_genes_matched": len(genes),
            "max_pct_of_mrna_expression": ranked[0]["pct_of_mrna_expression"]}


def mark_payload(tool: str, out, *, path: str | os.PathLike | None = None):
    """Stamp a result whose numbers rest on a degradation rate that is not a fit.

    Silent on `clear` for the reason (a) is silent on a clean answer: a marker on every payload is a marker
    the model learns to skip. NOT silent on `could_not_verify` — an absent stamp reads as "this number is
    fine", so a check that could not run has to say so rather than look like a pass.
    """
    if tool not in MARKED_TOOLS or not isinstance(out, dict) or out.get("error"):
        return out
    res = payload_hits(out, path=path)
    if res["verdict"] == "clear":
        return out
    if res["verdict"] == "could_not_verify":
        out.setdefault(_MARK_KEY, {
            "verdict": "could_not_verify", "why": res.get("why"),
            "read_as": "unverified, not verified — the degradation-provenance index could not be read"})
        return out
    shown = res["units"][:6]
    classes = {u["rate_class"] for u in shown if u["rate_class"]}
    out.setdefault(_MARK_KEY, {
        "verdict": "rests_on_non_fits",
        "what_this_means": (
            "genes named in this result are transcribed from units whose degradation rate the ParCa "
            "estimator did not fit — it is a bound or the population mean. The numbers are left exactly as "
            "computed; this records what they rest on."),
        "units": shown,
        "rate_classes": {c: _MEANS[c] for c in sorted(classes) if c in _MEANS},
        "n_units_matched": res["n_units_matched"],
        "n_units_shown": len(shown),
        "n_genes_matched": res["n_genes_matched"],
        "max_pct_of_mrna_expression": res["max_pct_of_mrna_expression"],
        "pct_is_of_total_mrna_expression": ("each unit's share of TOTAL mRNA expression in the knowledge "
                                            "base — not a share of this result, and not additive with the "
                                            "corpus-wide 12.087% figure"),
        "measured_on_kb_sha256": res["kb_sha256"],
        "transfer_limit": ("the classification was measured on ONE knowledge base. A result from a different "
                           "arm may not carry the same classification — check `provenance` for this "
                           "result's arm."),
        "full_picture": "call `deg_rate_provenance` for any single unit",
    })
    return out
