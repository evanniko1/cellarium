"""Item 4c — which lineages continue past a generation that may not have divided, and was it the time cap?

Read-only. For every indexed row whose `per_generation` has a non-final generation that is not known to have
divided, read each generation's first and last timestep from raw simOut (through the model image) and classify
it with `cellarium.lineage`. Rows indexed before t_start/t_end were recorded are classified from raw here;
nothing in the manifest is changed — re-indexing is the full re-run's job (FAIL-3).

    python scripts/check_undivided_generations.py            # print a table
    python scripts/check_undivided_generations.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_env() -> None:
    p = Path(".env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def candidates() -> list[dict]:
    from cellarium import lineage, survey
    out = []
    for r in survey._leth_rows():
        pg = survey._as_list(r.get("per_generation"))
        if lineage.first_suspect_parent(pg) is not None:
            out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", default="", help="write the full result here")
    args = ap.parse_args()
    _load_env()
    from cellarium import lineage, reader, store, survey

    rows = candidates()
    results = []
    for r in rows:
        root = store._resolve_run(r.get("simout_path"))
        pg = survey._as_list(r.get("per_generation"))
        rec = {"label": r.get("label"), "qc": r.get("qc"), "simout_path": r.get("simout_path"),
               "from_manifest": lineage.summary(pg)}
        if root and Path(root).exists():
            # The reader mounts ONE output root; runs live under runs/ or a runs_<suffix>/ root.
            parts = Path(root).resolve().parts
            k = next((i for i, c in enumerate(parts) if c == "runs" or c.startswith("runs_")), None)
            if k is not None:
                reader.OUT_ROOT = Path(*parts[:k + 1])
            try:
                raw = reader.gen_times(Path(root))
            except Exception as exc:
                raw = {"error": f"{type(exc).__name__}: {exc}"}
            if "generations" in raw:
                merged = []
                for g in pg:
                    t = next((x for x in raw["generations"] if x.get("i") == g.get("i")), {})
                    merged.append({**g, "t_start": t.get("t_start"), "t_end": t.get("t_end"),
                                   "fc_end": t.get("fc_end")})
                rec["from_raw"] = lineage.summary(merged)
            else:
                rec["raw_error"] = raw.get("error") or raw
        else:
            rec["raw_error"] = "raw simOut not on local disk"
        results.append(rec)

    print(f"{len(results)} lineage(s) continue past a generation not known to have divided "
          f"(cap {lineage.CAP_S:.0f} s)\n")
    for rec in results:
        src = rec.get("from_raw") or rec["from_manifest"]
        basis = "raw" if "from_raw" in rec else f"manifest only ({rec.get('raw_error')})"
        print(f"{rec['label']}  [qc={rec['qc']}]  basis={basis}")
        for g in src["generations"]:
            extra = " flag_disagrees" if g.get("flag_disagrees") else ""
            print(f"    gen {g['i']}: {g['status']:<22} duration={g['duration_s']}  divided_flag={g['divided_flag']}{extra}")
        print(f"    excluded from per-generation comparisons: {src['excluded_generations']}\n")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
