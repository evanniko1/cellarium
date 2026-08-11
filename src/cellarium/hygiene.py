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


# ------------------------------------------------------------------------------------------------------------
# The read-site REGISTRY — intent, which no scanner can derive.
# ------------------------------------------------------------------------------------------------------------
# `read_sites()` answers WHERE the corpus is read. It cannot answer WHY, and the why is what decides whether a
# site should move onto this boundary. That judgement is declared here.
#
# WHY A REGISTRY IS NOT ENOUGH ON ITS OWN, stated because it is the objection this design has to answer. A
# registry is a DECLARATION, and this codebase's standing rule is that a declaration nobody verifies is a
# comment — `capability.probe()` greps the checkout, `INVARIANTS.json`'s probe codes are grepped out of
# `integrity_check`, `test_registry.unclassified_tools()` trips CI on a new tool. A registry of read sites
# fails the same way and worse: an unregistered new call site makes it UNDER-count, silently, while reading as
# complete. The text-search counter it replaces at least over-counted, which is loud.
#
# So the registry is paired with `registry_reconciliation()`, checked BOTH ways: every DETECTED site must be
# registered (catches new code), and every REGISTERED site must still exist (catches stale entries). The
# detector stays the authority on completeness; the registry is the authority on intent.
#
# WHAT THIS STILL CANNOT CATCH, so nobody reads it as more than it is:
#   * a MISCLASSIFIED site — registering a purpose-shaped read as a `lookup` silences the test and no
#     mechanical check can tell; only review can. There is a test that asserts this limit rather than hiding it.
#   * a call reached dynamically (`getattr(store, name)()`) — invisible to the syntax tree.
#   * a NEW read path that avoids these functions entirely, e.g. a fresh `read_parquet` in a new module. The
#     detector counts those; nothing yet FORBIDS one. Only a lint rule (banned call + allowlist) closes that,
#     which is a separate change with a CI dependency.
KINDS = ("lookup", "purpose_shaped", "primitive", "blocked", "migrated")

READ_SITE_REGISTRY: dict[str, dict] = {
    # --- LOOKUPS: "which row is this?", not "which rows may I use?". A purpose filter in front of a lookup
    # would HIDE the row being looked up — `data_availability` for a crashed run's id must still find it.
    "differential.py::_design_run_roots": {
        "kind": "lookup", "why": "resolves a design to its run directories; must see every row, crashed included"},
    "hf.py::_design_seeds": {
        "kind": "lookup", "why": "resolves a design label or a result_id to its rows"},
    "hf.py::data_availability": {
        "kind": "lookup", "why": "finds one row by id to report what is downloadable; filtering could hide it"},
    "raw.py::seed_runs": {
        "kind": "lookup", "why": "resolves a design to its seeds on disk"},
    "tools.py::_resolve_result": {
        "kind": "lookup", "why": "resolves a user-supplied id or label to a row"},
    "tools.py::_run_label": {
        "kind": "lookup", "why": ("resolves a run id to its label for display; a filtered set would render a "
                                  "real run as unknown rather than as filtered out")},
    "tools.py::run_experiment": {
        "kind": "lookup", "why": "checks whether a proposed design already has runs before launching"},
    "tools.py::segment_means": {
        "kind": "lookup", "why": "resolves a design_or_id argument; a shift run may legitimately be non-reportable"},
    "tools.py::read_series": {
        "kind": "lookup", "why": "label search for a user-supplied key"},

    # --- DECIDED, NOT MIGRATED.
    "segments.py::repair": {
        "kind": "lookup",
        "why": ("a maintenance WRITE path over live timeline rows. Its filter set matches `lethality` and "
                "`inventory`, but both contracts are wrong for it — `inventory` says the rows may not be read "
                "and repair reads them. A third contract over one filter set is the signal that filter and "
                "contract may want to be two dimensions; adding a sixth purpose for one internal function is "
                "how a boundary becomes a taxonomy nobody reads. Revisit if a second repair-like caller appears")},
}


def registry_reconciliation() -> dict:
    """Detected vs registered, BOTH ways. This is what makes the registry trustworthy rather than a comment."""
    sites = read_sites()["consumer_sites"]
    detected = {f"{s['file']}::{s['function']}" for s in sites}
    registered = set(READ_SITE_REGISTRY)
    unregistered = sorted(detected - registered)
    stale = sorted(registered - detected)
    bad_kind = sorted(k for k, v in READ_SITE_REGISTRY.items() if v.get("kind") not in KINDS)
    no_reason = sorted(k for k, v in READ_SITE_REGISTRY.items() if not str(v.get("why") or "").strip())
    return {
        "ok": not (unregistered or stale or bad_kind or no_reason),
        "n_detected": len(detected), "n_registered": len(registered),
        "unregistered": unregistered, "stale": stale,
        "invalid_kind": bad_kind, "missing_reason": no_reason,
        "by_kind": {k: sorted(n for n, v in READ_SITE_REGISTRY.items() if v.get("kind") == k) for k in KINDS},
        "cannot_catch": ("a MISCLASSIFIED site (registering a purpose-shaped read as a lookup silences this "
                         "check and only review can tell); a dynamically dispatched call; and a NEW read path "
                         "that avoids these functions entirely. Reconciliation proves the registry is "
                         "COMPLETE, not that it is RIGHT."),
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


def _docstring_nodes(tree):
    """The string constants that are DOCSTRINGS, so a counter can skip them."""
    import ast
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)                     and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def read_sites() -> dict:
    """The surface this boundary has to cover, counted from the SYNTAX TREE rather than by text search.

    The backlog names 7 modules issuing their own `read_parquet` and says out loud that "the true surface is
    larger than the 7 and was not enumerated". This enumerates it, so migration progress is measurable
    instead of asserted — the same discipline `invariants.coverage()` applies to the catalogue.

    WHY THIS IS NOT A REGEX ANY MORE. The first version searched the file TEXT for `list_results(` and
    counted three modules that consume nothing: the tool's name inside the agent's system prompt
    (`agent.py`), and the `def` lines of the two primitives themselves (`store.py`, `survey.py`). It reported
    15 consumer modules where there are 12. An instrument that over-counts reads as verification, which is
    the failure this whole file exists to end — so the instrument gets the same standard as the thing it
    measures.

    THE TWO THINGS COUNTED ARE DIFFERENT IN KIND, and that is why the implementation is hybrid rather than
    uniformly AST-based:

      * a CONSUMER is a Python function call — `store.list_results(...)` — so it is found as an `ast.Call`,
        which cannot be fooled by a comment, a docstring or prompt text, and yields the enclosing function
        name for free rather than by a second regex.
      * a DIRECT READ is not a Python call at all: `read_parquet('...')` is DuckDB SQL embedded in an
        f-string. No syntax tree will ever see it as a call, so it is found by inspecting string LITERALS —
        text search, but scoped to the nodes where SQL can actually live, with docstrings excluded.

    What this still cannot see: a dynamic call (`getattr(store, name)()`). There are none here, and saying so
    is part of the count.
    """
    import ast
    from pathlib import Path

    CONSUMER_FNS = {"list_results", "analysis_rows"}
    root = Path(__file__).resolve().parent
    direct, consumers, sites = {}, {}, []
    unparsed = []
    for p in sorted(root.glob("*.py")):
        if p.name == "hygiene.py":
            continue
        try:
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except Exception as exc:
            unparsed.append({"file": p.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        docstrings = _docstring_nodes(tree)

        # enclosing-function map, built once from the tree rather than by scanning backwards for `def`
        owner: dict = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(fn):
                    owner.setdefault(id(sub), fn.name)

        n_direct = n_cons = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str)                     and id(node) not in docstrings and "read_parquet(" in node.value:
                n_direct += 1
            elif isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
                if name in CONSUMER_FNS:
                    # `def list_results` in store.py calling itself is not a consumer; a call whose owner IS
                    # the function being called is the primitive, not a caller of it.
                    if owner.get(id(node)) == name:
                        continue
                    n_cons += 1
                    sites.append({"file": p.name, "function": owner.get(id(node), "<module>"),
                                  "calls": name, "line": node.lineno})
        if n_direct:
            direct[p.name] = n_direct
        if n_cons:
            consumers[p.name] = n_cons

    return {
        "direct_read_parquet": direct, "n_direct_modules": len(direct),
        "downstream_consumers": consumers, "n_consumer_modules": len(consumers),
        "consumer_sites": sites,
        "unparsed": unparsed,
        # The gap batch 2 recorded is CLOSED by the fifth purpose (`inventory`). Kept as an empty list rather
        # than deleted, because the next migration batch will find its own gaps and this is where they go.
        "unmigrated_needing_a_decision": [],
        "migrated": ["differential.matrix", "rigor.disconfirm", "launch.kb_dependents",
                     "reconcile.corpus_identifiers", "rigor.coverage", "trna.wildtype_null",
                     "resources._corpus_footprint", "manifest.integrity_check", "corpus_schema.fmt",
                     "manifest.reconcile_disk"],
        "counted_by": ("`ast.Call` for consumers; string literals for the SQL `read_parquet(`, which is not a "
                       "Python call and no syntax tree can see as one. Docstrings excluded; dynamic calls "
                       "(getattr) invisible, and there are none in this tree."),
        "note": ("A direct `read_parquet` bypasses every rule in `data/INVARIANTS.json`; a consumer of "
                 "`list_results`/`analysis_rows` gets the primitive's filters but chooses its own on top, "
                 "which is where the measured 5.5x `disconfirm` drift came from. Counted honestly the consumer "
                 "surface is the SMALLER one (7 modules against 8 that read the parquet directly) — the "
                 "opposite of what the text-search version reported. `migrated` lists the call "
                 "sites that now ask by PURPOSE; it is a small fraction of the surface above and is meant to "
                 "be read as such."),
    }
