"""CORPUS-REBUILD-1 step 1: decide WHAT to re-run before re-running anything.

WHY THE AUDIT COMES FIRST. Every one of the 363 rows lacks executed provenance — which image, which model
class — and that information is destroyed rather than merely unrecorded, so re-running is the only way to
recover it. But re-running all 363 at their recorded depths is days of wall-clock AND re-imports whatever
redundancy is already there. The point of this pass is to shrink the number honestly before spending it.

WHAT THIS DELIBERATELY DOES NOT DO. It does not retire anything on "not reportable". That flag means the row
does not enter a mean, NOT that it carries no information:

  * a KO that CRASHED is the evidence that the knockout is lethal — `hygiene.rows("lethality")` reads all 363
    rows for exactly this reason;
  * `noop_knockout` is a FINDING (the perturbation did not do what its name says — the paper's third failure
    mode), not junk;
  * `no_division` distinguishes "arrested" from "never measured".

So the only rows this proposes to retire are ones where re-running recovers nothing that is not already
present in a sibling row. Everything else is either RE-RUN or flagged for a human decision.

    python scripts/corpus_audit.py                  # the report
    python scripts/corpus_audit.py --json out.json  # machine-readable, for the campaign driver
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

# Minutes of wall-clock per generation on the machine that produced this corpus, measured 2026-08-24 across
# 11 one-generation runs: 9m13s to 13m03s. Deliberately the UPPER end — an estimate that flatters the plan is
# worse than one that over-books.
MIN_PER_GENERATION = 13.0

HF_REPO = os.environ.get("CELLARIUM_HF_REPO", "evanniko1/cellarium-corpus")


def _rows() -> list[dict]:
    import duckdb

    from cellarium import manifest
    con = duckdb.connect()
    q = f"read_parquet('{manifest.MANIFEST_DIR}/*.parquet', union_by_name=true)"
    # Names listed explicitly rather than parsed back out of the SQL: `elongation_sql` emits
    # `COALESCE(elongation_model, 'steady_state') AS elongation_model`, whose internal comma-space split the
    # naive `cols.split(", ")` mid-expression and produced a column called `'steady_state')`.
    names = ["id", "label", "perturbation", "condition", "timeline", "seed", "qc", "reportable", "crashed",
             "crash_type", "generations", "gens_reached", "simout_path", "kb_sha256", "operons",
             "elongation_model"]
    cols = ", ".join(names[:-1]) + ", " + manifest.elongation_sql("elongation_model")
    return [dict(zip(names, r)) for r in con.execute(f"SELECT {cols} FROM {q}").fetchall()]


def _hf_archives() -> set[str]:
    """Which runs are archived on Hugging Face. A row whose raw is gone locally is NOT lost if HF has it."""
    try:
        from huggingface_hub import HfApi
        return {f for f in HfApi().list_repo_files(HF_REPO, repo_type="dataset") if f.endswith(".tar.gz")}
    except Exception:
        return set()


def _hf_key(simout_path) -> str | None:
    q = str(simout_path or "").replace("\\", "/")
    m = re.search(r"/(cellarium|aadrop)/([^/]+)/(\d{6})/", q + "/")
    return f"runs/{m.group(1)}/{m.group(2)}/{m.group(3)}.tar.gz" if m else None


def _design_of(r: dict) -> tuple:
    return (r["perturbation"], r["condition"] or "", r["timeline"] or "", r["elongation_model"])


def audit() -> dict:
    rows = _rows()
    tars = _hf_archives()
    for r in rows:
        p = r.get("simout_path")
        r["raw_local"] = bool(p) and os.path.isdir(str(p))
        r["raw_hf"] = _hf_key(p) in tars
        r["raw_anywhere"] = r["raw_local"] or r["raw_hf"]

    designs: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in rows:
        designs[_design_of(r)].append(r)

    out = []
    for key, rs in sorted(designs.items(), key=lambda kv: -len(kv[1])):
        rep = [r for r in rs if r["reportable"]]
        qc = collections.Counter(r["qc"] for r in rs)
        # LETHALITY EVIDENCE: a crashed or non-dividing knockout is a result, not a failure to clean up.
        evidence = [r for r in rs if not r["reportable"] and (r["crashed"] or r["qc"] in
                                                              ("no_division", "noop_knockout"))]
        # The only safe retire: rows the corpus itself flagged as surplus or contentless, AND where a sibling
        # row of the same design already carries the same information.
        surplus = [r for r in rs if r["qc"] in ("over_replicated", "empty")]
        retirable = surplus if (len(rep) or len(evidence)) else []
        gens = sum(int(r["gens_reached"] or r["generations"] or 1) for r in rs)

        if len(rep) or len(evidence):
            verdict, why = "RERUN", "load-bearing: carries analysis rows or lethality evidence"
        elif all(r["qc"] in ("crashed", "empty") for r in rs) and not any(r["raw_anywhere"] for r in rs):
            verdict, why = "DECIDE", "every row crashed and no raw survives — re-run to confirm, or retire"
        else:
            verdict, why = "DECIDE", "no reportable rows and no clear evidentiary role"

        out.append({
            "perturbation": key[0], "condition": key[1], "timeline": key[2], "elongation_model": key[3],
            "n_rows": len(rs), "n_seeds": len({r["seed"] for r in rs}), "n_reportable": len(rep),
            "n_evidence": len(evidence), "n_retirable": len(retirable),
            "qc": dict(qc), "generations_total": gens,
            "raw_local": sum(1 for r in rs if r["raw_local"]),
            "raw_hf": sum(1 for r in rs if r["raw_hf"]),
            "raw_gone": sum(1 for r in rs if not r["raw_anywhere"]),
            "arm": f"{str(rs[0]['kb_sha256'])[:8]}/{rs[0]['operons']}/{key[3]}",
            "verdict": verdict, "why": why,
            "rerun_minutes": round(gens * MIN_PER_GENERATION),
        })

    tot = {
        "n_rows": len(rows), "n_designs": len(out),
        "n_reportable": sum(1 for r in rows if r["reportable"]),
        "raw_local": sum(1 for r in rows if r["raw_local"]),
        "raw_hf": sum(1 for r in rows if r["raw_hf"]),
        "raw_gone": sum(1 for r in rows if not r["raw_anywhere"]),
        "raw_gone_reportable": sum(1 for r in rows if not r["raw_anywhere"] and r["reportable"]),
        "qc": dict(collections.Counter(r["qc"] for r in rows)),
        "by_arm": dict(collections.Counter(
            f"{str(r['kb_sha256'])[:8]}/{r['operons']}/{r['elongation_model']}" for r in rows)),
    }
    return {"totals": tot, "designs": out, "min_per_generation": MIN_PER_GENERATION,
            "hf_archives_seen": len(tars)}


def report(a: dict) -> None:
    t = a["totals"]
    print("CORPUS AUDIT — CORPUS-REBUILD-1 step 1\n" + "=" * 78)
    print(f"{t['n_rows']} rows, {t['n_designs']} distinct designs, {t['n_reportable']} analysis-reportable\n")

    print("RAW TRACE AVAILABILITY  (a row whose raw is gone can still be re-run — the DESIGN is recorded)")
    print(f"  local on disk   {t['raw_local']:>4}")
    print(f"  on Hugging Face {t['raw_hf']:>4}   ({a['hf_archives_seen']} archives seen)")
    print(f"  NEITHER         {t['raw_gone']:>4}   of which reportable: {t['raw_gone_reportable']}")
    print()
    print("QC VERDICTS")
    for k, v in sorted(t["qc"].items(), key=lambda kv: -kv[1]):
        print(f"  {str(k):22} {v:>4}")
    print()
    print("ARMS  (re-run packages; a partially migrated corpus keeps complete comparable sets)")
    for k, v in sorted(t["by_arm"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:44} {v:>4} rows")
    print()

    # WHERE THE WORK ACTUALLY IS. Classifying by DESIGN put 71 of 72 in "re-run", which is true and useless:
    # almost every design is load-bearing. The scope decision is per SEED — how many replicates each design
    # needs — and it is dominated by a handful of heavily-seeded designs.
    print("SEED DEPTH  (the real scope lever — designs sorted by re-run cost)")
    print(f"  {'design':<50}{'rows':>5}{'seeds':>6}{'rep':>5}{'hours':>7}")
    for d in sorted(a["designs"], key=lambda x: -x["rerun_minutes"])[:12]:
        name = f"{d['perturbation']}/{d['condition']}"[:48]
        print(f"  {name:<50}{d['n_rows']:>5}{d['n_seeds']:>6}{d['n_reportable']:>5}"
              f"{d['rerun_minutes']/60:>7.1f}")
    top = sorted(a["designs"], key=lambda x: -x["rerun_minutes"])[:5]
    print(f"  -> the 5 costliest designs are {sum(d['n_rows'] for d in top)} rows and "
          f"{sum(d['rerun_minutes'] for d in top)/60:.1f} h of the total.")
    print()
    # A floor worth stating: nothing below this can support a cross-seed claim at all.
    thin = [d for d in a["designs"] if d["n_reportable"] and d["n_reportable"] < 3]
    print(f"  designs with 1-2 reportable rows (too thin for a cross-seed claim): {len(thin)}")
    print()

    verdicts = collections.Counter(d["verdict"] for d in a["designs"])
    print("VERDICT PER DESIGN")
    for k, v in verdicts.most_common():
        rows = sum(d["n_rows"] for d in a["designs"] if d["verdict"] == k)
        mins = sum(d["rerun_minutes"] for d in a["designs"] if d["verdict"] == k)
        print(f"  {k:8} {v:>3} designs  {rows:>4} rows   ~{mins/60:.1f} h to re-run")
    print()
    surplus = sum(d["n_retirable"] for d in a["designs"])
    print(f"  rows the corpus itself flagged surplus/empty: {surplus}")
    print()
    print("DECIDE — these need a human call before the campaign starts")
    for d in a["designs"]:
        if d["verdict"] != "DECIDE":
            continue
        print(f"  {d['perturbation']:<26} {d['condition'][:26]:<28} n={d['n_rows']:<3} "
              f"qc={d['qc']}  raw_gone={d['raw_gone']}")
    print()
    total_h = sum(d["rerun_minutes"] for d in a["designs"]) / 60
    rerun_h = sum(d["rerun_minutes"] for d in a["designs"] if d["verdict"] == "RERUN") / 60
    print(f"COST  everything: ~{total_h:.1f} h   RERUN-only: ~{rerun_h:.1f} h "
          f"(at {a['min_per_generation']} min/generation, serial)")
    print(f"      at parallel-6: ~{total_h/6:.1f} h / ~{rerun_h/6:.1f} h — parallel is safe for provenance "
          f"since the per-run metadata fix (PROV-2).")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", default="", help="also write the machine-readable audit here")
    args = ap.parse_args(argv)
    a = audit()
    report(a)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(a, indent=1) + "\n", encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
