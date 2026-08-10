"""PLAT-2 — truncation that names what it dropped, and refuses when trimming would destroy the claim.

Every tool result passes through one funnel on its way into the model's context (`agent._truncate_tool_result`),
and that funnel has to shrink oversized lists. The question is what it says about what it removed.

WHAT THE PLATFORM THIS CAME FROM DOES, and the one property worth keeping: it halves the largest oversized
list and stamps `"showing N of M"`, preserving the ORIGINAL M across repeated halvings so a second trim never
reports "N of the already-trimmed M". That property is kept here (`Omission.n_total` is captured once, before
any trimming) and there is a test for it.

THE THREE STEPS FURTHER, each of which is the difference between a footnote and a usable record:

  (1) NAME THE DROPPED DIMENSION. "31 of 37" tells a reader that something is missing and nothing about what.
      "seeds 4, 5, 6 dropped" tells them whether the answer is still about the thing they asked about. The
      identity comes from the tool's declared schema, not from guessing per call site.

  (2) IT IS A DECLARED CONTRACT, not a note a tool may forget. `RESULT_SCHEMA` says, per tool, which key holds
      the analysable rows and which field identifies one. A tool without a declaration still gets counts and a
      best-effort identity, but the declaration is what makes the omission mechanical and reviewable — and the
      omission rides into the EVIDENCE LEDGER next to the ids that were read, so a later reviewer sees the same
      hole the agent saw rather than a complete-looking list.

  (3) TRUNCATION IS REFUSABLE. If trimming drops the surviving set below `support.MIN_SEEDS` /
      `MIN_GENERATIONS`, the answer is no longer a measurement of what was asked, and a footnote saying so is
      not enough — the tool refuses AT THAT SCOPE and offers a narrower scope that would qualify. The platform
      has no floor at all: `keep = max(1, len(lst) // 2)` will reduce a set to one element and stamp
      "showing 1 of 34", which reads as an answer and is a case study.

WHY A REFUSAL RATHER THAN A LOUDER WARNING. `support.MIN_SEEDS` already governs whether a claim can be quoted
at all; a result that silently falls below it *because of context pressure* would be the same defect arriving
by a different road — and one with no trace in the payload, since the trimming happens after the tool has
returned. The floor belongs where the trimming happens.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# ------------------------------------------------------------------------------------------------------------
# The declared contract.
# ------------------------------------------------------------------------------------------------------------
# `rows` — the key holding the analysable list. `identity` — fields that name ONE item, in preference order.
# `stratum` — the dimension the evidential floor is counted over, when there is one; None means the list is not
# a set of replicates and no floor applies (a list of designs is not a list of seeds).
#
# Deliberately NOT exhaustive over all 72 tools, and that is a decision rather than an omission: a declaration
# is a promise about a payload's shape, and writing 72 of them from memory would produce promises that are
# wrong. The tools listed are the ones whose results are large enough to be trimmed in practice. Everything
# else falls back to `_INFERRED`, which names what it can and never claims a stratum it did not verify.
RESULT_SCHEMA: dict[str, dict] = {
    "list_results":       {"rows": "results", "identity": ("id", "label"), "stratum": "seed"},
    "survey_corpus":      {"rows": "notable", "identity": ("design", "label"), "stratum": None},
    "design_space":       {"rows": "designs", "identity": ("design", "label"), "stratum": None},
    "comparable_designs": {"rows": "designs", "identity": ("design", "label"), "stratum": None},
    "similar_designs":    {"rows": "designs", "identity": ("design", "label"), "stratum": None},
    "top_movers":         {"rows": "movers", "identity": ("species", "id"), "stratum": None},
    "read_series":        {"rows": "series", "identity": ("seed", "id"), "stratum": "seed"},
    "read_raw_series":    {"rows": "series", "identity": ("seed", "id"), "stratum": "seed"},
    "variance_band":      {"rows": "seeds", "identity": ("seed",), "stratum": "seed"},
    "trajectory":         {"rows": "points", "identity": ("generation", "seed"), "stratum": "generation"},
    "list_species":       {"rows": "species", "identity": ("id", "name"), "stratum": None},
    "lethality_landscape": {"rows": "designs", "identity": ("design", "label"), "stratum": None},
}

# Fields that identify one row when no schema is declared. Order matters: a run id is more useful to a reviewer
# than a seed number, because it joins to the manifest.
_INFERRED = ("id", "run_id", "design", "design_key", "label", "species", "name", "seed", "generation")


def schema_for(tool: str | None) -> dict:
    return RESULT_SCHEMA.get(tool or "", {})


def undeclared_list_tools(tool_names) -> list[str]:
    """Tools with no declared result schema. NOT a CI failure — see the note on RESULT_SCHEMA — but reported so
    the gap is visible and can be closed deliberately as payload shapes are confirmed."""
    return sorted(set(tool_names) - set(RESULT_SCHEMA))


# ------------------------------------------------------------------------------------------------------------
# What was dropped.
# ------------------------------------------------------------------------------------------------------------
@dataclass
class Omission:
    key: str                       # which list
    n_total: int                   # BEFORE any trimming — captured once, never recomputed from a trimmed list
    n_kept: int
    dropped: list = field(default_factory=list)     # named identities, when they can be named
    stratum: str | None = None     # the dimension a floor is counted over, if any
    kept_strata: list = field(default_factory=list)

    @property
    def n_dropped(self) -> int:
        return self.n_total - self.n_kept

    def as_dict(self) -> dict:
        d = {"key": self.key, "n_total": self.n_total, "n_kept": self.n_kept, "n_dropped": self.n_dropped}
        if self.dropped:
            d["dropped"] = self.dropped[:40]
            if len(self.dropped) > 40:
                d["dropped_truncated"] = f"{len(self.dropped) - 40} further identities not listed"
        if self.stratum:
            d["stratum"] = self.stratum
            d["kept_" + self.stratum + "s"] = self.kept_strata
        return d

    def marker(self) -> str:
        """The in-list marker the model reads. Names identities where it can, because a count tells a reader
        that something is missing and nothing about whether it mattered."""
        if self.dropped:
            shown = ", ".join(str(x) for x in self.dropped[:8])
            more = f" and {len(self.dropped) - 8} more" if len(self.dropped) > 8 else ""
            return (f"…[{self.n_dropped} of {self.n_total} '{self.key}' dropped to fit context: "
                    f"{shown}{more} — narrow the query to see them]")
        return (f"…[{self.n_dropped} of {self.n_total} '{self.key}' item(s) dropped to fit context — "
                f"narrow the query to see them]")


def _identity(item, fields) -> str | None:
    if not isinstance(item, dict):
        return None
    for f in fields:
        v = item.get(f)
        if v not in (None, ""):
            return str(v)
    return None


def _stratum_values(items, stratum: str | None) -> list:
    if not stratum:
        return []
    seen = []
    for it in items:
        if isinstance(it, dict) and it.get(stratum) not in (None, ""):
            v = it[stratum]
            if v not in seen:
                seen.append(v)
    return seen


# ------------------------------------------------------------------------------------------------------------
# The refusal floor.
# ------------------------------------------------------------------------------------------------------------
def floor_refusal(omissions: list[Omission], *, tool: str | None = None) -> dict | None:
    """Has trimming pushed a replicate set below the evidential floor? If so, this is not an answer.

    Returns a refusal naming the scope it refused AND a narrower scope that would qualify — a refusal with no
    route forward just moves the dead end. Returns None when every stratum still clears its floor, or when the
    list carries no stratum at all (a list of designs is not a list of replicates, and applying a seed floor to
    it would refuse ordinary questions).
    """
    from . import support
    for om in omissions:
        if not om.stratum or not om.n_dropped:
            continue
        floor = support.MIN_SEEDS if om.stratum == "seed" else (
            support.MIN_GENERATIONS if om.stratum == "generation" else None)
        if floor is None:
            continue
        kept = len(om.kept_strata) if om.kept_strata else om.n_kept
        if kept >= floor:
            continue
        return {
            "error": (f"refused at this scope: trimming to fit context left {kept} {om.stratum}(s), below the "
                      f"floor of {floor}"),
            "refused_scope": {"tool": tool, "key": om.key, "n_total": om.n_total, "n_kept": om.n_kept,
                              "stratum": om.stratum, "kept": om.kept_strata},
            "why": (f"`support.MIN_{om.stratum.upper()}S` = {floor} is the line between a measurement and a "
                    f"case study. A result that falls below it BECAUSE OF CONTEXT PRESSURE is the same defect "
                    f"arriving by a different road, and it would carry no trace — the trimming happens after "
                    f"the tool returned. A footnote on an under-powered answer is not enough here."),
            "narrower_scope_that_would_qualify": (
                f"ask for a single {om.stratum} at a time, or filter to one design, so the full set of "
                f"{om.stratum}s survives the context budget instead of being halved into a case study"),
            "not_a_measurement": "this scope was refused, not answered",
        }
    return None


# ------------------------------------------------------------------------------------------------------------
# The funnel.
# ------------------------------------------------------------------------------------------------------------
def _assemble(base: dict, lists: dict, keep: dict, ident_fields, stratum, declared_rows,
              detail_limit: int) -> tuple[dict, list]:
    """Build one candidate payload at the given per-list keep counts and omission-detail budget."""
    cand = dict(base)
    oms: list[Omission] = []
    for k, full in lists.items():
        n_total = len(full)                    # captured ONCE from the untrimmed input — a second trim can
        n_kept = keep[k]                       # never report "N of the already-trimmed M"
        cand[k] = list(full[:n_kept])
        if n_kept >= n_total:
            continue
        applies = declared_rows is None or k == declared_rows
        om = Omission(key=k, n_total=n_total, n_kept=n_kept,
                      dropped=[i for i in (_identity(x, ident_fields) for x in full[n_kept:]) if i],
                      stratum=stratum if applies else None,
                      kept_strata=_stratum_values(cand[k], stratum) if applies else [])
        oms.append(om)
        cand[k] = cand[k] + [om.marker()]
    if oms:
        block = []
        for o in oms:
            d = o.as_dict()
            if detail_limit <= 0:
                d.pop("dropped", None)
                d.pop("dropped_truncated", None)
            elif o.dropped and len(o.dropped) > detail_limit:
                d["dropped"] = o.dropped[:detail_limit]
                d["dropped_truncated"] = (f"{len(o.dropped) - detail_limit} further identities not listed "
                                          f"(the omission record itself was trimmed to fit)")
            block.append(d)
        cand["_omitted"] = block
    return cand, oms


def trim(out: dict, cap: int, *, tool: str | None = None) -> tuple[dict, list[Omission]]:
    """Shrink the biggest lists to fit `cap`, recording named omissions. Does not mutate `out`.

    Shrinks LISTS rather than slicing the JSON string, so the result stays valid and the scalar/provenance
    fields survive — a severed survey or top_movers payload is a provenance hole, which is what this project
    exists to prevent.

    FITTED BY MEASURING THE WHOLE CANDIDATE, not by reserving a guessed number of bytes for the note. The
    first version trimmed the lists against `cap - 220`, then appended the omission block, and at cap=900 the
    result came back OVER the cap and the caller's last-resort string slice cut it mid-string — the funnel
    emitting invalid JSON, which is the exact failure it exists to prevent. Found by running it at four caps.

    When it cannot all fit, the OMISSION DETAIL degrades before the DATA: the identities collapse to counts
    (and say so) before a single further row is dropped. A note about the data must not cost the data.
    """
    sch = schema_for(tool)
    ident_fields = tuple(sch.get("identity") or ()) or _INFERRED
    stratum, declared_rows = sch.get("stratum"), sch.get("rows")

    base = {k: v for k, v in out.items() if not (isinstance(v, list) and v)}
    lists = {k: list(v) for k, v in out.items() if isinstance(v, list) and v}
    if len(json.dumps(dict(out), default=str)) <= cap or not lists:
        return dict(out), []

    order = sorted(lists, key=lambda k: -len(json.dumps(lists[k], default=str)))
    keep = {k: len(v) for k, v in lists.items()}

    def size(detail):
        c, o = _assemble(base, lists, keep, ident_fields, stratum, declared_rows, detail)
        return len(json.dumps(c, default=str)), c, o

    # PHASE A — fit the DATA first, with the omission detail at its cheapest. A single monotone loop that
    # spent identities to save bytes and then trimmed rows anyway finished with room to spare and no names at
    # all: the note was sacrificed for nothing. Measured at cap=4000 on a 40-row payload.
    for _ in range(200):
        n, cand, oms = size(0)
        if n <= cap:
            break
        k = max(order, key=lambda k: keep[k])
        if keep[k] <= 0:
            break
        keep[k] = max(0, keep[k] - max(1, keep[k] // 4))

    # PHASE B — with the rows settled, spend whatever is left on naming what was dropped. Rows first because
    # the rows are the answer and the omission is the note about it; but the note gets every byte the answer
    # did not need.
    best = (cand, oms)
    for detail in (1, 2, 5, 10, 20, 40):
        n, c, o = size(detail)
        if n > cap:
            break
        best = (c, o)
    return best
