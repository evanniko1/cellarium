"""What the corpus is made of, as a generated artefact rather than an ad-hoc query.

The corpus is not one dataset. It is a set of ARMS, where an arm is the combination of things that must match
before two rows can be averaged: the fitted parameter set, the operon build mode, and the elongation model.
Rows from different arms describe different instruments -- a degradation rate that is 91.2 min under one fit
is 32.4 under another -- so a mean across arms describes nothing.

Nothing in this repository refused a cross-arm read until now. `survey.analysis_rows` filters QC and
tombstones inside the read so no caller can forget; `kb_sha256` had no equivalent, which is why a
cross-knowledge-base comparison was only caught by hand on 2026-08-07.

`arms()` is the generated table. `same_arm()` is the predicate a read boundary calls.
"""
from __future__ import annotations

from collections import Counter, defaultdict

# The columns that make two rows comparable. Adding one here tightens every consumer at once, which is the
# point of naming them in a single place rather than in each tool's WHERE clause.
ARM_KEYS = ("kb_sha256", "operons", "elongation_model")

# Recorded per row but NOT part of arm identity, with the reason. These are covariates a reader may want to
# stratify on; they do not by themselves make two rows incomparable.
NOT_ARM_KEYS = {
    "generations": "depth is handled by generation-depth matching, which compares within a stratum",
    "seed": "seeds are the replication unit; pooling them is the point",
    "condition": "the independent variable in most comparisons",
    "contributor": "who ran it does not change what it is, provided the arm matches",
}

# ARM-2 (shipped 2026-08-08). These are now WRITTEN on every new row, and they are deliberately NOT in
# ARM_KEYS. The reason is the same NULL hazard `survey._deduped_rows` already guards against: every one of the
# 366 existing rows predates the columns, `arm_of` coalesces None to '?', and a key that is '?' on both sides
# compares EQUAL — so promoting them today would not partition the corpus, it would manufacture one enormous
# "unknown" arm that silently claims agreement. That is the failure ARM-1 exists to prevent, arrived at from
# the other direction.
#
# What they CAN do immediately is the reverse: detect an arm the current keys MISS. Two rows that agree on
# kb_sha256 + operons + elongation_model but carry known and DIFFERENT model_sha256 are not comparable, and
# nothing else in the corpus would say so. `arm_conflicts()` is that check. Promote a column into ARM_KEYS
# once it is non-NULL across the rows being compared — the enforcement then tightens for free.
ARM2_COLUMNS = ("model_sha256", "image_digest", "reconstruction_sha", "parca_ts", "runsim_argv")

# What each column answers. Kept after shipping because the rationale is the part that rots.
MISSING_COLUMNS = {
    "model_sha256": "which simulator CODE produced the row. `kb_sha256` pins the PARAMETERS; nothing pinned "
                    "the code. Two rows can share a fit and still come from different model source, which is "
                    "exactly the confound the phnE1 investigation had to rule out by hand (bitwise "
                    "reproduction over 2,529 timesteps). Shipped as `<upstream_commit>+<overlay digest>` and "
                    "NOT as a bare git sha: this tree is public wcEcoli plus 44 overlay files, so a commit "
                    "alone would compare EQUAL across two different overlay states. Recorded in the backlog "
                    "under ARM-2's `model_git_sha`; renamed because a git-shaped name invites diffing commits "
                    "that would not explain the difference.",
    "image_digest": "the container digest actually executed. `WCECOLI_DOCKER` is a mutable tag, so "
                    "'wcecoli-sim:kinetic' today and last month need not be the same image.",
    "parca_ts": "when the knowledge base was built, and from which flat-file state. Lets a reader order the "
                "arms causally instead of inferring order from the first run that used them.",
    "reconstruction_sha": "a hash over reconstruction/ecoli/flat/. A KB rebuild is triggered by editing those "
                          "files, so this is the INPUT whose change explains why a new arm exists.",
    "runsim_argv": "the exact flags. The elongation model is recorded, but nothing else is, so a flag added "
                   "later would silently split an arm without being visible.",
}


def arm_conflicts(rows: list[dict], columns=ARM2_COLUMNS) -> list[dict]:
    """Rows that share an arm but disagree on a recorded covariate — an arm the current keys MISS.

    This is the useful direction for a column that is NULL across the existing corpus. It cannot partition
    (see ARM2_COLUMNS), but the moment two rows both carry a KNOWN value and those values differ, they are not
    comparable and nothing else in the repository would say so.

    Only KNOWN-vs-KNOWN counts. A NULL is unknown, never evidence of agreement OR of difference — treating a
    missing value as a mismatch would flag the whole pre-ARM-2 corpus against every new row, which is noise,
    and treating it as a match is the failure this exists to catch.
    """
    seen: dict[tuple, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in rows:
        for c in columns:
            v = r.get(c)
            if v is not None and v != "":
                seen[arm_of(r)][c].add(v)
    out = []
    for arm, cols in seen.items():
        for c, vals in cols.items():
            if len(vals) > 1:
                out.append({"arm": dict(zip(ARM_KEYS, arm)), "column": c, "n_distinct": len(vals),
                            "values": sorted(str(v)[:64] for v in vals)[:6],
                            "why": "these rows share an arm but ran under different %s, so the arm keys do not "
                                   "separate them. Either promote %s into ARM_KEYS or report them apart."
                                   % (c, c)})
    return sorted(out, key=lambda d: -d["n_distinct"])


def _rows(con=None):
    import duckdb

    from . import manifest
    con = con or duckdb.connect()
    cols = (", ".join(ARM_KEYS) + ", id, ts, reportable, generations, perturbation, "
            + manifest.optional_col_sql("parca_ts"))
    return con.execute(f"SELECT {cols} FROM read_parquet('{manifest.MANIFEST_DIR}/*.parquet', "
                       f"union_by_name=true)").fetchall()


def _dropped_ids():
    from . import manifest
    try:
        return {v.get("id") for v in manifest.dropped_keys().values()}
    except Exception:
        return set()


def arms(include_dropped: bool = False) -> list[dict]:
    """One row per arm: the comparability partition, its size, depth spread and date range.

    This is the table to publish beside the corpus. A reader who sees three arms knows, without asking, that
    three separate instruments produced these numbers.
    """
    dropped = _dropped_ids()
    out: dict[tuple, dict] = {}
    for kb, op, el, rid, ts, rep, gens, pert, parca in _rows():
        if not include_dropped and rid in dropped:
            continue
        key = (kb or "?", op or "?", el or "steady_state")
        a = out.setdefault(key, {"kb_sha256": key[0], "operons": key[1], "elongation_model": key[2],
                                 "rows": 0, "reportable": 0, "depths": Counter(),
                                 "perturbations": Counter(), "first_ts": ts, "last_ts": ts,
                                 "parca_ts": None})
        a["rows"] += 1
        a["reportable"] += bool(rep)
        a["depths"][gens] += 1
        a["perturbations"][pert] += 1
        a["first_ts"] = min(a["first_ts"] or ts, ts or a["first_ts"])
        a["last_ts"] = max(a["last_ts"] or ts, ts or a["last_ts"])
        # WHEN THE FIT WAS BUILT (ARM-2). This is the payoff of `parca_ts` and the reason it was worth
        # backfilling: `first_ts` is the earliest run that USED an arm, which is only a lower bound on when the
        # arm came into existence and is plainly wrong for a fit that sat unused. Every row of one arm shares a
        # kb, so any stamped row answers for the arm -- take the first non-NULL rather than an aggregate.
        if parca and not a["parca_ts"]:
            a["parca_ts"] = parca
    for a in out.values():
        a["depths"] = dict(sorted(a["depths"].items()))
        a["perturbations"] = dict(a["perturbations"].most_common())
    return sorted(out.values(), key=lambda a: -a["rows"])


def arm_of(row: dict) -> tuple:
    """The arm a row belongs to, as a hashable key. One definition, so no caller invents its own."""
    return tuple((row.get(k) or ("steady_state" if k == "elongation_model" else "?")) for k in ARM_KEYS)


def same_arm(row_a: dict, row_b: dict) -> bool:
    """The predicate a read boundary calls before averaging two rows."""
    return arm_of(row_a) == arm_of(row_b)


def arm_split(rows: list[dict]) -> dict | None:
    """None when every row shares an arm; otherwise a refusal naming the split.

    Returns a refusal rather than raising, so a caller can surface it to a reader instead of dying: the same
    contract `capability.check` uses.
    """
    seen = defaultdict(int)
    for r in rows:
        seen[tuple((r.get(k) or ("steady_state" if k == "elongation_model" else "?")) for k in ARM_KEYS)] += 1
    if len(seen) <= 1:
        return None
    return {
        "refused": "these rows span %d comparability arms and must not be pooled" % len(seen),
        "arms": [{"kb_sha256": k[0], "operons": k[1], "elongation_model": k[2], "rows": n}
                 for k, n in sorted(seen.items(), key=lambda kv: -kv[1])],
        "why": "a fitted parameter set, operon build mode and elongation model each change what a channel "
               "means; averaging across them describes no instrument.",
        "fix": "filter to one arm, or report per arm without pooling.",
    }


def report() -> str:
    """The human-readable artefact. Regenerate rather than hand-maintain."""
    import datetime
    lines = ["# Corpus arms", "",
             "Generated by `cellarium.corpus_schema.report()`. An ARM is %s." % " + ".join(ARM_KEYS),
             "Rows from different arms are not poolable.", ""]
    a = arms()
    # Two DIFFERENT dates, kept apart on purpose. `kb built` is when the fit was made (`parca_ts`); `first run`
    # is the earliest simulation that used it. They are not interchangeable — the second is only a lower bound
    # on the first, and ordering arms by it misreads any fit that sat unused before someone ran against it.
    def fmt(t):
        return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d") if t else "?"

    lines.append("| kb | operons | elongation | rows | reportable | depths | kb built | first run |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for x in sorted(a, key=lambda x: (x["parca_ts"] or x["first_ts"] or 0)):
        depth = ", ".join("%sg:%d" % (k, v) for k, v in x["depths"].items())
        lines.append("| `%s` | %s | %s | %d | %d | %s | %s | %s |"
                     % (x["kb_sha256"][:8], x["operons"], x["elongation_model"], x["rows"],
                        x["reportable"], depth, fmt(x["parca_ts"]), fmt(x["first_ts"])))
    lines += ["", "%d arms, %d live rows." % (len(a), sum(x["rows"] for x in a)), ""]

    # Coverage of the ARM-2 columns, measured rather than asserted. A column written only from now on is
    # useless on a corpus that predates it, and how useless is a number a reader should see rather than infer.
    try:
        from . import survey
        rows, _ = survey.analysis_rows(arm="all")
    except Exception:
        rows = []
    if rows:
        # The denominator here is the ANALYSIS set (reportable, not tombstoned), which is smaller than the
        # `rows` column above — that counts everything an arm holds. Both numbers are right and they are not
        # the same number, so the table says which one it is rather than leaving a reader to reconcile them.
        lines += ["## Provenance coverage (ARM-2)", "",
                  "Written on every new row; NULL on rows that predate the column. NULL means UNKNOWN and is "
                  "never read as agreement — see `arm_conflicts`.", "",
                  "| column | rows carrying it | of %d analysable rows |" % len(rows), "|---|---|---|"]
        for c in ARM2_COLUMNS:
            n = sum(1 for r in rows if r.get(c) is not None)
            lines.append("| `%s` | %d | %d%% |" % (c, n, round(100 * n / len(rows))))
        conflicts = arm_conflicts(rows)
        lines += ["", ("**%d conflict(s):** rows sharing an arm disagree on %s."
                       % (len(conflicts), ", ".join(sorted({c["column"] for c in conflicts})))
                       if conflicts else "No arm carries rows that disagree on a recorded covariate."), ""]

    lines += ["## What each provenance column answers", ""]
    for k, why in MISSING_COLUMNS.items():
        lines.append("- **`%s`** — %s" % (k, why))
    return "\n".join(lines)


REPORT_PATH = "docs/CORPUS_ARMS.md"


def write_report(path: str = REPORT_PATH) -> str:
    """Generate the arms table to disk. GENERATED, never hand-edited — that is the point of it existing.

    A table maintained by hand goes stale silently: it stays plausible while the corpus moves underneath it,
    and a reader has no way to tell. Regenerate with `python -m cellarium.corpus_schema`.
    """
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(report() + "\n", encoding="utf-8", newline="\n")
    return str(p)


if __name__ == "__main__":
    import sys
    if "--write" in sys.argv:
        print("wrote " + write_report())
    else:
        print(report())
