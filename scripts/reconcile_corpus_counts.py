"""NMI-4b — ONE place that states how big the corpus is, in every sense of "big", with each sense defined.

WHY THE FIRST FIX WAS NOT ENOUGH. `verify_dataset_size.py` settled one number: what the PUBLISHED dataset
contains. That left three other quantities in circulation, all called "the corpus", none reconciled, and the
documents mixing them freely:

  * what the public deposit holds   -- compressed archives on Hugging Face
  * what is on this machine         -- uncompressed run directories, a SUPERSET of some designs and a
                                       SUBSET of others, because designs uploaded to the deposit were then
                                       pruned locally to reclaim disk
  * what the index holds            -- manifest rows, which is what every tool actually queries and is the
                                       only one of the three a user of the package interacts with

These are not addable. The deposit is compressed and the working copy is not, so their gigabytes are in
different units; and they overlap partially rather than wholly, so neither is a subset of the other. A
sentence like "the corpus is 361 GB" is therefore not wrong so much as unanswerable until it says which.

WHAT THIS FOUND, which is why it exists. The committed documents claimed a local corpus of 361 GB across
138,983 files. Measured: 212.2 GB across 84,684 files. The 361 figure predates a pruning pass that deleted
seed directories after they were uploaded -- it was true when written and nothing re-measured it. The index
was described as "369 runs"; it holds 369 ROWS of which 333 are distinct run ids, the 36 duplicates being
crashed attempts that share an id. And two tools in this package disagree about how many designs exist (68
from the audit, 77 from the survey), which is a definition difference nobody had written down.

    python scripts/reconcile_corpus_counts.py            # measure everything, write the artifact
    python scripts/reconcile_corpus_counts.py --no-hub    # skip the network half
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "data" / "hf" / "CORPUS_COUNTS.json"
GB = 1024 ** 3


def index_counts() -> dict:
    """What the committed manifest holds -- the only one of the three a package user queries."""
    import duckdb

    f = str(REPO / "data" / "manifest" / "corpus-compact.parquet").replace("\\", "/")
    con = duckdb.connect()

    def one(sql: str):
        return con.execute(sql.replace("{F}", f"read_parquet('{f}')")).fetchone()[0]

    qc = dict(con.execute(
        f"SELECT qc, count(*) FROM read_parquet('{f}') GROUP BY qc ORDER BY 2 DESC").fetchall())
    fam = dict(con.execute(
        f"SELECT perturbation, count(*) FROM read_parquet('{f}') "
        "GROUP BY perturbation ORDER BY 2 DESC").fetchall())
    modes = dict(con.execute(
        f"SELECT elongation_model, count(*) FROM read_parquet('{f}') GROUP BY elongation_model").fetchall())

    return {
        "manifest_rows": one("SELECT count(*) FROM {F}"),
        "distinct_run_ids": one("SELECT count(DISTINCT id) FROM {F}"),
        "duplicate_rows": one("SELECT count(*) - count(DISTINCT id) FROM {F}"),
        "rows_that_produced_a_generation": one("SELECT count(*) FROM {F} WHERE generations > 0"),
        "total_generations": one("SELECT sum(generations) FROM {F}"),
        "qc_verdicts": qc,
        "perturbation_families": len(fam),
        "rows_per_family": fam,
        "rows_per_elongation_model": modes,
        "note": ("one row is one SEED of one design, carrying however many generations it reached. The "
                 "duplicates are crashed attempts that share a run id; every row with generations > 0 is "
                 "distinct."),
    }


def design_counts() -> dict:
    """The two definitions this package uses, both reported, because they disagree and the difference is
    not an error -- it is two questions."""
    from cellarium import tools

    audit = tools.corpus_audit()
    cov = audit["coverage"]["designs"]
    survey_cov = tools.survey_corpus().get("coverage", {})
    return {
        "audit_n_designs": audit["summary"]["n_designs"],
        "audit_designs_with_a_passing_run": sum(1 for v in cov.values() if v.get("qc", {}).get("ok", 0) > 0),
        "survey_n_designs_in_corpus": survey_cov.get("n_designs_in_corpus"),
        "survey_n_designs_ranked": survey_cov.get("n_designs_ranked"),
        "survey_n_designs_excluded": survey_cov.get("n_designs_excluded"),
        "note": ("`corpus_audit` and `survey_corpus` count designs differently and both are in use. Until "
                 "one definition is adopted, a document must say WHICH it quotes; the survey number is the "
                 "one a user sees first, because the survey is the mandatory first call."),
    }


def local_counts() -> dict:
    """The working copy on this machine: uncompressed, and partially pruned after upload."""
    from cellarium.runner import OUT_ROOT

    root = Path(str(OUT_ROOT))
    if not root.is_dir():
        return {"present": False, "note": f"{root} is not a directory on this machine"}
    total = files = 0
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(dirpath, n))
                files += 1
            except OSError:
                pass
    return {
        "present": True, "path": str(root), "files": files,
        "bytes": total, "gb": round(total / GB, 1),
        "note": ("UNCOMPRESSED, and neither a superset nor a subset of the deposit: designs uploaded to "
                 "Hugging Face were pruned here to reclaim disk, while runs never uploaded exist only here. "
                 "Not addable to the deposit's gigabytes, which are compressed."),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-hub", action="store_true", help="skip the network measurement of the deposit")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)

    out: dict = {"measured_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    out["index"] = index_counts()
    out["designs"] = design_counts()
    out["local_working_copy"] = local_counts()

    if a.no_hub:
        out["published_deposit"] = {"skipped": True}
    else:
        try:
            import verify_dataset_size as v  # noqa: PLC0415 -- same directory, imported on demand
        except ImportError:
            sys.path.insert(0, str(REPO / "scripts"))
            import verify_dataset_size as v
        try:
            out["published_deposit"] = v.measure()
        except Exception as e:                                   # noqa: BLE001
            out["published_deposit"] = {"error": f"{type(e).__name__}: {e}",
                                        "note": "not written as zero; the last committed measurement stands"}

    print(json.dumps(out, indent=1))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {Path(a.out).relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
