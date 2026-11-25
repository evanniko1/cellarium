"""Re-derive the regulation-scope findings from the corpus as it stands, offline, with the current read rules.

The findings were first assembled on 2026-07-25 from the corpus of that pass (docs/CASE_MATRIX.md; the evidence base
it fed, docs/REPORT_EVIDENCE.md, was deleted with the interactive report on 2026-09-02 and survives in git at
41f9c98). Since then the corpus has grown, quality control excludes crashed, undivided and implausible runs, effects
are compared within one generation depth, and design labels resolve to what the knockout actually silences. This
script re-runs every finding that summary channels can decide, through the same functions the agent calls
(`rigor.disconfirm`, `rigor.fit_relation`, `factors.identity`, all reading `hygiene.rows("analysis")`), so the
table in the Platform Map's Appendix J can be checked by anyone with the corpus.

The gene-level nitrate and arabinose rows need the simulator's own reader (the model image, through Docker) over
both arms' full simOut, so they run only with `--with-reader`. A row the reader cannot compute is kept, with the
reason: on 2026-11-24 the nitrate rows could not be, because the anaerobic reference arm's raw output is not on this
machine. Runs the reader cannot see are reported as counts and output-tree names, never paths.

    python scripts/regulation_scope.py
    python scripts/regulation_scope.py --with-reader
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
warnings.filterwarnings("ignore", message=".*Arrow output.*")

from cellarium import controls, differential, factors, rigor, tools  # noqa: E402

WT = "wildtype/basal"
TWO_OPERONS = "rrna_operon_knockout/minimal|rRNA_KO:2op"
SYNTHETASES = ("gene_knockout/KO:argS", "gene_knockout/KO:alaS", "gene_knockout/KO:gltX", "gene_knockout/KO:pheS",
               "multi_gene_knockout/KO:gltX+relA+spoT")
LAW_DESIGNS = [WT, "condition/acetate", "condition/succinate", "condition/with_aa", "condition/glc_2mM",
               "condition/glc_5mM", "condition/glc_20mM", "ppgpp_conc/basal|ppGpp:0.2x",
               "ppgpp_conc/basal|ppGpp:0.6x", "ppgpp_conc/basal|ppGpp:1.6x", "ppgpp_conc/basal|ppGpp:2.0x",
               TWO_OPERONS, "rrna_operon_knockout/minimal|rRNA_KO:4op", "rrna_operon_knockout/minimal|rRNA_KO:6op"]


# (regulon, condition, reference): the July pass's gene-level comparisons. Nitrate is read against the anaerobic
# reference, which isolates nitrate from the loss of oxygen, and against aerobic basal, which shows why that matters.
READER_COMPARISONS = [
    ("ara_arabinose", "condition/plus_arabinose", WT),
    ("nar_nitrate", "condition/plus_nitrate", "condition/no_oxygen"),
    ("fnr_anaerobic", "condition/plus_nitrate", "condition/no_oxygen"),
    ("nar_nitrate", "condition/plus_nitrate", WT),
]
_UNREACHABLE_FIELDS = ("role", "n_reachable", "n_unreachable", "output_trees_not_mounted")


def wants_reader(argv: list[str]) -> bool:
    return "--with-reader" in argv


def reader_rows() -> list[dict]:
    """The gene-level rows through the simulator's reader: the regulon's FDR-significant movers, every regulon
    protein's level in both arms, the run counts, and the runs the reader could not see (counts only)."""
    rows = []
    for regulon, cond, ref in READER_COMPARISONS:
        row: dict = {"regulon": regulon, "condition": cond, "reference": ref}
        r = tools.regulon_response(regulon, cond, ref)
        if r.get("needs_raw") or "error" in r:
            row.update(re_derived=False, why_not=str(r.get("message") or r.get("error"))[:300])
            rows.append(row)
            continue
        row.update(re_derived=True, **{k: r.get(k) for k in ("verdict", "n_regulon_genes", "n_significant_in_regulon",
                                                            "n_significant_total", "movers")})
        lfc = differential.all_gene_lfc(cond, ref, kind="protein")
        if "error" in lfc:
            row["regulon_levels_error"] = str(lfc["error"])[:300]
        else:
            genes = {g.lower() for g in tools._REGULONS.get(regulon, [])}
            # sorted by gene, so two runs of the same reader diff only where a value changed
            row["regulon_levels"] = dict(sorted(
                (v.get("symbol"), {k: v.get(k) for k in ("target", "reference", "log2fc")})
                for v in (lfc.get("lfc") or {}).values() if str(v.get("symbol", "")).lower() in genes))
            row["n_target_runs"], row["n_reference_runs"] = lfc.get("n_target_runs"), lfc.get("n_reference_runs")
            row["unreachable"] = [{k: u.get(k) for k in _UNREACHABLE_FIELDS}
                                  for u in (lfc.get("_unreachable_runs") or [])]
        rows.append(row)
    return rows


def effect(target: str, reference: str, channel: str) -> dict:
    r = rigor.disconfirm(target, reference, channel)
    if "error" in r:
        return {"target": target, "channel": channel, "error": r["error"]}
    return {"target": target, "reference": reference, "channel": channel, "effect_pct": r.get("effect_pct"),
            "welch_p": r.get("welch_p"), "n_target": r["target"]["n_seeds"], "n_reference": r["reference"]["n_seeds"],
            "generations": r.get("generations")}


def main() -> int:
    # Controls first (A-1): a known result reproduced on each channel the rows below read, through the same
    # function, before any of them is trusted. A channel without a control is reported as uncontrolled.
    out: dict = {"controls": {ch: controls.check(ch) for ch in ("growth_rate", "ribosome_conc", "ppgpp_conc",
                                                                "rela_conc")},
                 "ribosome_growth_law": {}, "ppgpp_clamps": [], "rrna_dosage": [], "carbon_sources": [],
                 "synthetase_knockouts": []}
    law = rigor.fit_relation(LAW_DESIGNS, "growth_rate", "ribosome_conc")
    if "error" in law:
        print(json.dumps({"error": law["error"]}))
        return 1
    for k in ("fit_all", "fit_out_of_sample_only"):
        f = law.get(k) or {}
        out["ribosome_growth_law"][k] = {x: f.get(x) for x in ("n", "r_squared", "pearson_r", "slope_p_value")}
    for level in ("0.2x", "0.6x", "1.6x", "2.0x"):
        for ch in ("growth_rate", "ribosome_conc"):        # ribosomes: the downstream ppGpp -> ribosome link
            out["ppgpp_clamps"].append(effect(f"ppgpp_conc/basal|ppGpp:{level}", WT, ch))
    for n in ("4op", "6op"):
        for ch in ("growth_rate", "ribosome_conc"):
            out["rrna_dosage"].append(effect(f"rrna_operon_knockout/minimal|rRNA_KO:{n}", TWO_OPERONS, ch))
    for c in ("condition/acetate", "condition/succinate"):
        out["carbon_sources"].append(effect(c, WT, "growth_rate"))
    for d in SYNTHETASES:
        ident = factors.identity(d)
        row = {"design": d, "label_integrity": ident.get("label_integrity"), "true_label": ident.get("true_label")}
        for ch in ("ppgpp_conc", "rela_conc", "growth_rate"):
            e = effect(d, WT, ch)
            row[ch] = {k: e.get(k) for k in ("effect_pct", "welch_p", "n_target", "generations", "error") if k in e}
        out["synthetase_knockouts"].append(row)
    if wants_reader(sys.argv[1:]):
        out["gene_level"] = reader_rows()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
