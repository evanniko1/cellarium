"""Re-derive the regulation-scope findings from the corpus as it stands, offline, with the current read rules.

The findings were first assembled on 2026-07-25 from the corpus of that pass (docs/CASE_MATRIX.md; the evidence base
it fed, docs/REPORT_EVIDENCE.md, was deleted with the interactive report on 2026-09-02 and survives in git at
41f9c98). Since then the corpus has grown, quality control excludes crashed, undivided and implausible runs, effects
are compared within one generation depth, and design labels resolve to what the knockout actually silences. This
script re-runs every finding that summary channels can decide, through the same functions the agent calls
(`rigor.disconfirm`, `rigor.fit_relation`, `factors.identity`, all reading `hygiene.rows("analysis")`), so the
table in the Platform Map's Appendix J can be checked by anyone with the corpus.

Not re-derived here: the gene-level nitrate and arabinose differentials. They need the simulator's own reader (the
`wcecoli-sim` image) over full simOut, and the nitrate reference arm's raw output is no longer local.

    python scripts/regulation_scope.py
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
warnings.filterwarnings("ignore", message=".*Arrow output.*")

from cellarium import factors, rigor  # noqa: E402

WT = "wildtype/basal"
TWO_OPERONS = "rrna_operon_knockout/minimal|rRNA_KO:2op"
SYNTHETASES = ("gene_knockout/KO:argS", "gene_knockout/KO:alaS", "gene_knockout/KO:gltX", "gene_knockout/KO:pheS",
               "multi_gene_knockout/KO:gltX+relA+spoT")
LAW_DESIGNS = [WT, "condition/acetate", "condition/succinate", "condition/with_aa", "condition/glc_2mM",
               "condition/glc_5mM", "condition/glc_20mM", "ppgpp_conc/basal|ppGpp:0.2x",
               "ppgpp_conc/basal|ppGpp:0.6x", "ppgpp_conc/basal|ppGpp:1.6x", "ppgpp_conc/basal|ppGpp:2.0x",
               TWO_OPERONS, "rrna_operon_knockout/minimal|rRNA_KO:4op", "rrna_operon_knockout/minimal|rRNA_KO:6op"]


def effect(target: str, reference: str, channel: str) -> dict:
    r = rigor.disconfirm(target, reference, channel)
    if "error" in r:
        return {"target": target, "channel": channel, "error": r["error"]}
    return {"target": target, "reference": reference, "channel": channel, "effect_pct": r.get("effect_pct"),
            "welch_p": r.get("welch_p"), "n_target": r["target"]["n_seeds"], "n_reference": r["reference"]["n_seeds"],
            "generations": r.get("generations")}


def main() -> int:
    out: dict = {"ribosome_growth_law": {}, "ppgpp_clamps": [], "rrna_dosage": [], "carbon_sources": [],
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
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
