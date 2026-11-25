"""BV-R1: two-component sensor proteins before and after the reader's correction, each in its activating condition.

wcEcoli's MonomerCounts listener drops the monomers of phosphorylated two-component sensor complexes (see
`_reader_agg.tcs_dropped_subunits`). Each affected sensor is read in the corpus condition that activates it and in
basal, through the reader's protein path, which now adds the dropped subunits back and reports how much it added.
"Before" is the corrected mean minus what was added, i.e. what every protein read returned until 2026-11-25.

    WCECOLI_DOCKER=<code image> python evals/bv_r1_two_component.py     # writes bv_r1_two_component.json
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "evals" / "results" / "bv_r1_two_component.json"

SENSORS = [  # monomer, protein, activating condition design, what activates it
    ("NARX-MONOMER[i]", "NarX", "condition/plus_nitrate", "nitrate (NarX binds nitrate and autophosphorylates)"),
    ("PHOR-MONOMER[i]", "PhoR", "condition/minus_phosphate", "phosphate limitation"),
    ("ARCB-MONOMER[i]", "ArcB", "condition/no_oxygen", "anaerobiosis"),
    ("DCUS-MONOMER[i]", "DcuS", "condition/succinate", "C4-dicarboxylates (succinate)"),
    ("PHOQ-MONOMER[i]", "PhoQ", "condition/minus_magnesium", "low magnesium"),
]
REFERENCE = "wildtype/basal"


def _roots(design: str) -> list[str]:
    from cellarium import survey, tools
    rows, _ = survey.analysis_rows()
    out = []
    for r in rows:
        if survey.design_key(r) == design and r.get("qc") == "ok" and tools._run_root(r["id"]) is not None:
            out.append(r["id"])
    return sorted(set(out))


def _read(run_id: str, monomer: str) -> dict | None:
    from cellarium import tools
    s = tools.read_species(run_id, monomer, kind="protein")
    if not isinstance(s, dict) or s.get("mean") is None:
        return None
    added = sum(v for v in (s.get("two_component_correction") or {}).values() if v)
    return {"after": float(s["mean"]), "before": float(s["mean"]) - added, "added": added}


def _lfc(t: list[float], r: list[float]) -> float | None:
    if not t or not r:
        return None
    return round(math.log2((sum(t) / len(t) + 1.0) / (sum(r) / len(r) + 1.0)), 2)


# The organism, where PRECISE-1K (Lamoureux et al. 2023) has a matched contrast: RNA log2 fold change (DESeq2,
# unshrunk, MG1655). Its MG1655 samples include no succinate and no low-magnesium condition, so DcuS and PhoQ have
# none; phosphate limitation appears only as phoB deletions.
ORGANISM = {"NarX": ("narX", {"column": "condition", "cond_A": "wt_glc_anaero", "cond_B": "no3_anaero"},
                     "anaerobic nitrate against anaerobic glucose (the organism has no aerobic nitrate samples)"),
            "ArcB": ("arcB", {"column": "condition", "cond_A": "wt_glc", "cond_B": "wt_glc_anaero"},
                     "anaerobic against aerobic glucose")}


def organism() -> int:
    """Add the organism's measurement to the stored rows (run in the environment that has pydeseq2)."""
    from cellarium import sci2
    d = json.loads(OUT.read_text(encoding="utf-8"))
    bmap = json.loads((REPO / "data" / "cache" / "bnumber_map.json").read_text(encoding="utf-8"))
    for r in d["rows"]:
        spec = ORGANISM.get(r["protein"])
        if not spec:
            r["organism"] = None
            continue
        gene, contrast, what = spec
        ref = sci2.build_reference(contrast)
        v = (ref.get("reference_lfc") or {}).get(bmap.get(gene)) if "error" not in ref else None
        r["organism"] = ({"gene": gene, "contrast": what, "log2fc": round(v["log2FC"], 2),
                          "padj": None if v.get("padj") is None else round(v["padj"], 3)} if v else None)
    d["organism_source"] = "PRECISE-1K (Lamoureux et al. 2023, doi:10.1093/nar/gkad750), RNA, DESeq2 unshrunk"
    OUT.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8")
    print(json.dumps([(r["protein"], r["log2fc_after"], r["organism"]) for r in d["rows"]]))
    return 0


def main() -> int:
    if "--organism" in sys.argv[1:]:
        return organism()
    from cellarium import provenance
    rows = []
    ref_ids = _roots(REFERENCE)
    for monomer, protein, design, why in SENSORS:
        ids = _roots(design)
        tv = [x for x in (_read(i, monomer) for i in ids) if x]
        rv = [x for x in (_read(i, monomer) for i in ref_ids) if x]
        row = {"protein": protein, "monomer": monomer, "design": design, "activated_by": why,
               "n_target_runs": len(tv), "n_reference_runs": len(rv),
               "target_mean_before": round(sum(x["before"] for x in tv) / len(tv), 1) if tv else None,
               "target_mean_after": round(sum(x["after"] for x in tv) / len(tv), 1) if tv else None,
               "reference_mean_before": round(sum(x["before"] for x in rv) / len(rv), 1) if rv else None,
               "reference_mean_after": round(sum(x["after"] for x in rv) / len(rv), 1) if rv else None,
               "log2fc_before": _lfc([x["before"] for x in tv], [x["before"] for x in rv]),
               "log2fc_after": _lfc([x["after"] for x in tv], [x["after"] for x in rv])}
        if not tv:
            row["why_missing"] = f"no QC-clean run of {design} with raw output on this machine"
        rows.append(row)
        print(json.dumps(row))
    out = {"spec": "BV-R1", "reference": REFERENCE, "rows": rows,
           "listener_gap": "two_component_system.stoich_matrix_monomers keeps a subunit only if it is in the system's "
                           "molecule list; 7 of 18 complexes lose their sensor monomers (DcuS, NarX, PhoQ, PhoR, "
                           "ArcB). Equilibrium (39) and complexation (1,131) lose none.",
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
