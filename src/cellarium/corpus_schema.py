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

import json
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

# Columns the manifest does NOT carry and should, with what each would let us answer. Recorded here rather
# than in prose because the gap is only actionable if it is enumerated.
MISSING_COLUMNS = {
    "model_git_sha": "which simulator commit produced the row. `kb_sha256` pins the PARAMETERS; nothing pins "
                     "the CODE. Two rows can share a fit and still come from different model source, which is "
                     "exactly the confound the phnE1 investigation had to rule out by hand (bitwise "
                     "reproduction over 2,529 timesteps).",
    "image_digest": "the container digest actually executed. `WCECOLI_DOCKER` is a mutable tag, so "
                    "'wcecoli-sim:kinetic' today and last month need not be the same image.",
    "parca_ts": "when the knowledge base was built, and from which flat-file state. Lets a reader order the "
                "arms causally instead of inferring order from the first run that used them.",
    "reconstruction_sha": "a hash over reconstruction/ecoli/flat/. A KB rebuild is triggered by editing those "
                          "files, so this is the INPUT whose change explains why a new arm exists.",
    "runsim_argv": "the exact flags. The elongation model is recorded, but nothing else is, so a flag added "
                   "later would silently split an arm without being visible.",
}


def _rows(con=None):
    import duckdb
    from . import manifest
    con = con or duckdb.connect()
    cols = ", ".join(ARM_KEYS) + ", id, ts, reportable, generations, perturbation"
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
    for kb, op, el, rid, ts, rep, gens, pert in _rows():
        if not include_dropped and rid in dropped:
            continue
        key = (kb or "?", op or "?", el or "steady_state")
        a = out.setdefault(key, {"kb_sha256": key[0], "operons": key[1], "elongation_model": key[2],
                                 "rows": 0, "reportable": 0, "depths": Counter(),
                                 "perturbations": Counter(), "first_ts": ts, "last_ts": ts})
        a["rows"] += 1
        a["reportable"] += bool(rep)
        a["depths"][gens] += 1
        a["perturbations"][pert] += 1
        a["first_ts"] = min(a["first_ts"] or ts, ts or a["first_ts"])
        a["last_ts"] = max(a["last_ts"] or ts, ts or a["last_ts"])
    for a in out.values():
        a["depths"] = dict(sorted(a["depths"].items()))
        a["perturbations"] = dict(a["perturbations"].most_common())
    return sorted(out.values(), key=lambda a: -a["rows"])


def arm_of(row: dict) -> tuple:
    """The arm a row belongs to, as a hashable key. One definition, so no caller invents its own."""
    return tuple((row.get(k) or ("steady_state" if k == "elongation_model" else "?")) for k in ARM_KEYS)


def same_arm(row_a: dict, row_b: dict) -> bool:
    """The predicate a read boundary calls before averaging two rows."""
    norm = lambda r: tuple((r.get(k) or ("steady_state" if k == "elongation_model" else "?")) for k in ARM_KEYS)
    return norm(row_a) == norm(row_b)


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
    lines.append("| kb | operons | elongation | rows | reportable | depths | first run |")
    lines.append("|---|---|---|---|---|---|---|")
    for x in a:
        when = (datetime.datetime.fromtimestamp(x["first_ts"]).strftime("%Y-%m-%d") if x["first_ts"] else "?")
        depth = ", ".join("%sg:%d" % (k, v) for k, v in x["depths"].items())
        lines.append("| `%s` | %s | %s | %d | %d | %s | %s |"
                     % (x["kb_sha256"][:8], x["operons"], x["elongation_model"], x["rows"],
                        x["reportable"], depth, when))
    lines += ["", "%d arms, %d live rows." % (len(a), sum(x["rows"] for x in a)), "",
              "## Columns the manifest does not carry", ""]
    for k, why in MISSING_COLUMNS.items():
        lines.append("- **`%s`** — %s" % (k, why))
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
