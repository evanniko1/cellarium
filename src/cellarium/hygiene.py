"""H-17b — ONE read boundary. `rows(purpose) -> (rows, ctx)`, where the purpose decides the filters.

THE DRIFT THIS ENDS HAS ALREADY HAPPENED, MEASURED. Three readers grew their own filtering: `survey_corpus`
filtered on `reportable`, `differential` did not, and `rigor.disconfirm` neither filtered nor used
`design_key` — it keyed on `perturbation/condition`, which is NULL for timelines and 'basal' for propose-path
knockouts. Consequence: **`disconfirm`, the tool whose job is to CHALLENGE a claim, reported an interval 5.5x
NARROWER than `survey_corpus` for the same cell**, over crashed runs, under a key that can collide. A
disconfirmation tool more confident than the thing it checks is worse than no tool. `survey.analysis_rows`
fixed that for the comparison tools; this fixes the shape of the problem, which is that there is no one place
to ask for rows.

**PURPOSE IS MANDATORY AND IT IS NOT COSMETIC.** The four purposes return genuinely DIFFERENT row sets, and
using the wrong one silently answers a different question:

  * `analysis`  — deduped, reportable, live, narrowed to one comparability arm. The set you may quote a mean
                  from. It EXCLUDES crashed runs, so counting lethality here reports zero deaths.
  * `coverage`  — everything that exists, tombstones included. Counts what is there; never compares.
  * `audit`     — UN-deduped, because supersession needs the duplicate rows visible. Deduping here hides the
                  correction history the audit exists to read.
  * `lethality` — non-reportable INCLUDED, because collapse IS the phenotype. `WHERE reportable` deletes the
                  thing being measured.
  * `inventory` — the DENOMINATOR: every live design, regardless of whether a mean could be quoted from it.
                  What "have I covered the corpus?" is measured against.

A PURPOSE IS A CONTRACT, NOT ONLY A FILTER — and `inventory` is the case that forces the distinction.
It returns the SAME ROWS as `lethality`: deduped, live, reportability-agnostic. Two purposes over one row set
looks like the decoration this module exists to avoid, so the reason it is not: what differs is what the set
LICENSES. `lethality` may be asked whether a design collapses and may not be asked for a channel mean;
`inventory` may be COUNTED and may not be read at all — its rows exist to size a denominator. A caller that
takes `inventory` and starts reading channels has made a category error the row set cannot detect, and the
only place that can say so is the contract. `test_no_two_purposes_share_a_filter_set_AND_a_contract` pins
that they never collapse into genuine duplicates.

`ctx` names every filter applied, every count it changed, the invariants it enforces (`data/INVARIANTS.json`),
and — the field that matters most — **what this row set must NOT be used for**. A caller who reaches for the
wrong purpose gets an answer that looks right, which is why the boundary says so rather than assuming.

BUILT ON THE EXISTING PRIMITIVES, DELIBERATELY. Each purpose composes the function that already implements it
(`survey.analysis_rows`, `store.list_results`, `audit._rows`, `survey.lethality`'s row source) rather than
re-querying the parquet. A rewrite would make this a FIFTH read path with its own subtly different filters —
which is the defect, not the fix. The drift came from callers applying their own rules, not from the
primitives, so the boundary's job is to be the one place that chooses.
"""

from __future__ import annotations

PURPOSES: dict[str, dict] = {
    "analysis": {
        "summary": "deduped, reportable, live, one comparability arm — the set a mean may be quoted from",
        "filters": ("dedup", "reportable", "tombstones", "arm"),
        "invariants": ("INV-3", "INV-2", "INV-11"),
        "not_for": ("counting lethality or collapse — crashed runs are removed, so deaths read as zero; "
                    "auditing corrections — supersession is invisible once deduped"),
    },
    "coverage": {
        "summary": "everything indexed, tombstones included — counts what exists, never compares",
        "filters": ("dedup",),
        "invariants": ("INV-3", "INV-12"),
        "not_for": ("quoting a mean or running a test — this set mixes arms, crashed runs and tombstoned "
                    "runs, so any statistic over it describes no instrument"),
    },
    "audit": {
        "summary": "UN-deduped — supersession needs the duplicate rows visible",
        "filters": (),
        "invariants": ("INV-11",),
        "not_for": ("any count of runs or seeds — duplicates are present BY DESIGN here, and counting them "
                    "is how `wildtype/basal` was once reported at 34 seeds instead of 26"),
    },
    "lethality": {
        "summary": "non-reportable INCLUDED — collapse is the phenotype, not a data defect",
        "filters": ("dedup", "tombstones"),
        "invariants": ("INV-3",),
        "not_for": ("quoting a channel mean — a collapsed run's channels are garbage; this set is for asking "
                    "WHETHER a design collapses, not what its numbers were"),
    },
    "inventory": {
        "summary": ("every live design, reportability-agnostic — the DENOMINATOR of 'what fraction of the "
                    "corpus have I examined?'"),
        "filters": ("dedup", "tombstones"),
        "invariants": ("INV-12", "INV-6"),
        "not_for": ("reading ANY value off these rows. They are here to be COUNTED. The set deliberately "
                    "mixes arms, crashed runs and depths, because a denominator must include the designs you "
                    "did not examine — which is exactly what makes every number in it uninterpretable"),
    },
}


class UnknownPurpose(ValueError):
    """Raised rather than defaulted. A default purpose is how every caller ends up on `analysis` and lethality
    silently reads zero — the failure this boundary exists to prevent."""


def _ctx(purpose: str, counts: dict, refusals: list, extra: dict | None = None) -> dict:
    spec = PURPOSES[purpose]
    return {
        "purpose": purpose,
        "means": spec["summary"],
        "filters_applied": list(spec["filters"]),
        "counts": counts,
        "refusals": refusals,
        "invariants_enforced": list(spec["invariants"]),
        "NOT_for": spec["not_for"],
        "note": ("Every filter this row set carries is named above. If your question is not the one this "
                 "purpose answers, ask for a different purpose — the sets are genuinely different and the "
                 "wrong one returns a plausible number for a question you did not ask."),
        **(extra or {}),
    }


def rows(purpose: str, *, arm=None) -> tuple[list[dict], dict]:
    """Rows for ONE stated purpose, with the context describing exactly what was applied.

    `purpose` has no default on purpose. Raises `UnknownPurpose` for anything not in `PURPOSES`, listing
    them — a boundary that guesses what a caller meant is a boundary that reintroduces the drift.
    """
    if purpose not in PURPOSES:
        raise UnknownPurpose(
            f"unknown purpose {purpose!r}; the corpus is read for one of {sorted(PURPOSES)} and each returns a "
            f"different row set. There is no default: 'give me the rows' is not a question this corpus can "
            f"answer without knowing what they are for.")

    if purpose == "analysis":
        from . import survey
        out, channels = survey.analysis_rows(arm=arm)
        note = survey.last_arm_note() or {}
        refusals = []
        if note.get("arm"):
            refusals.append({"refusal": "would not pool across comparability arms",
                             "kept": note.get("rows_kept"), "excluded": note.get("rows_excluded"),
                             "why": note.get("why")})
        if note.get("arm_incomplete"):
            refusals.append({"refusal": "the chosen arm is not homogeneous",
                             "detail": note["arm_incomplete"]})
        return out, _ctx(purpose, {"returned": len(out)}, refusals,
                         {"channels": channels, "arm": note.get("arm")})

    if purpose == "coverage":
        from . import store
        out = store.list_results(include_dropped=True)
        n_drop = sum(1 for r in out if r.get("dropped"))
        return out, _ctx(purpose, {"returned": len(out), "tombstoned_included": n_drop}, [],
                         {"tombstones": ("tombstoned rows are PRESENT and flagged `dropped`. They are a third "
                                         "population — excluded from ranking, kept in coverage — so a count "
                                         "here must say which of the three it counted.")})

    if purpose == "audit":
        from . import audit
        out = audit._rows()
        ids = {r.get("id") for r in out}
        return out, _ctx(purpose, {"returned": len(out), "distinct_ids": len(ids),
                                   "duplicate_rows": len(out) - len(ids)}, [],
                         {"why_un_deduped": ("`duplicate_rows` above is not a defect: an append-only corpus "
                                             "records a correction as a NEW row superseding an old one, and "
                                             "deduping here would hide exactly what an audit reads.")})

    from . import store, survey
    out = [r for r in store.list_results() if not r.get("dropped")]

    if purpose == "inventory":
        designs = {survey.design_key(r) for r in out}
        return out, _ctx(purpose, {"returned": len(out), "distinct_designs": len(designs)}, [],
                         {"denominator": sorted(designs),
                          "why_same_rows_as_lethality": (
                              "identical row SET, different CONTRACT. `lethality` may be asked whether a "
                              "design collapses; `inventory` may only be counted. Sharing a filter set is not "
                              "duplication when what the set licenses differs — and the licence is the part a "
                              "caller gets wrong.")})

    n_unreportable = sum(1 for r in out if not r.get("reportable"))
    return out, _ctx("lethality", {"returned": len(out), "non_reportable_kept": n_unreportable}, [],
                     {"why_non_reportable_kept": ("`WHERE reportable` deletes the lethality phenotype. A "
                                                  "design that divides and then collapses is exactly the "
                                                  "signal, and QC marks it unreportable.")})


def read_sites() -> dict:
    """The surface this boundary has to cover, counted rather than assumed.

    The backlog names 7 modules issuing their own `read_parquet` and says out loud that "the true surface is
    larger than the 7 and was not enumerated". This enumerates it, so migration progress is measurable instead
    of asserted — the same discipline `invariants.coverage()` applies to the catalogue.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent
    direct, consumers = {}, {}
    for p in sorted(root.glob("*.py")):
        if p.name in ("hygiene.py",):
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        n_direct = len(re.findall(r"read_parquet\(", src))
        if n_direct:
            direct[p.name] = n_direct
        n_cons = len(re.findall(r"list_results\(|analysis_rows\(", src))
        if n_cons:
            consumers[p.name] = n_cons
    return {
        "direct_read_parquet": direct, "n_direct_modules": len(direct),
        # The gap this list recorded is CLOSED: `rigor.coverage` needed "deduped, live, reportability-
        # agnostic" and the honest answer was a fifth purpose (`inventory`) rather than borrowing
        # `lethality`'s name. Kept as an empty list rather than deleted, because the next migration batch will
        # find its own gaps and this is where they go.
        "unmigrated_needing_a_decision": [],
        "downstream_consumers": consumers, "n_consumer_modules": len(consumers),
        "migrated": ["differential.matrix", "rigor.disconfirm", "launch.kb_dependents",
                     "reconcile.corpus_identifiers", "rigor.coverage"],
        "note": ("A direct `read_parquet` bypasses every rule in `data/INVARIANTS.json`; a consumer of "
                 "`list_results`/`analysis_rows` gets the primitive's filters but chooses its own on top, "
                 "which is where the measured 5.5x `disconfirm` drift came from. Both counts have to fall "
                 "for this boundary to have done its job. `migrated` lists the call sites that now ask by "
                 "PURPOSE; it is a small fraction of the surface above and is meant to be read as such."),
    }
