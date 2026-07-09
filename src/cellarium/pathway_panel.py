"""Curated species panel, grouped by pathway — the P2.1 depth layer.

This is the *committed, human-readable* curation: pathways -> E. coli K-12 gene symbols. It is deliberately
**interchangeable** — edit it (e.g. add the genes relevant to a KO) and re-run `python -m cellarium.pathway_panel`
to re-resolve. `resolve()` maps symbols -> the model's monomer IDs via the gene map (dumped from sim_data), and
writes `_pathway_resolved.json` (gitignored, model-derived) next to the reader worker, which reads it to record
per-pathway **proteome fractions** (size-independent) into the manifest. survey_corpus then ranks pathways as
first-class channels — surveying ~14 pathways instead of ~4,500 proteins is itself an anti-anchoring win.
"""

from __future__ import annotations

import json
from pathlib import Path

GENE_MAP_CACHE = Path("data/cache/gene_map.json")            # {symbol: monomer_id}, model-derived (gitignored)
RESOLVED = Path(__file__).with_name("_pathway_resolved.json")  # {pathway: [monomer_id]} (gitignored)

PATHWAY_PANEL: dict[str, list[str]] = {
    "translation_ribosome": [
        "rpsA", "rpsB", "rpsC", "rpsD", "rpsE", "rpsF", "rpsG", "rpsH", "rpsI", "rpsJ", "rpsK", "rpsL",
        "rpsM", "rpsN", "rpsO", "rpsP", "rpsQ", "rpsR", "rpsS", "rpsT", "rpsU",
        "rplA", "rplB", "rplC", "rplD", "rplE", "rplF", "rplI", "rplJ", "rplK", "rplL", "rplM", "rplN",
        "rplO", "rplP", "rplQ", "rplR", "rplS", "rplT", "rplU", "rplV", "rplW", "rplX", "rplY",
        "rpmA", "rpmB", "rpmC", "rpmD", "rpmE", "rpmF", "rpmG", "rpmH", "rpmI", "rpmJ",
        "tufA", "tufB", "tsf", "fusA", "infA", "infB", "infC", "efp",
    ],
    "transcription_rnap": ["rpoA", "rpoB", "rpoC", "rpoD", "rpoE", "rpoH", "rpoN", "rpoS", "rpoZ"],
    "stringent_response": ["relA", "spoT", "dksA"],
    "glycolysis": ["pgi", "pfkA", "pfkB", "fbaA", "tpiA", "gapA", "pgk", "gpmA", "gpmM", "eno", "pykF", "pykA"],
    "tca_cycle": ["gltA", "acnA", "acnB", "icd", "sucA", "sucB", "sucC", "sucD", "sdhA", "sdhB", "sdhC",
                  "sdhD", "fumA", "fumB", "fumC", "mdh"],
    "pentose_phosphate": ["zwf", "pgl", "gnd", "rpe", "rpiA", "rpiB", "tktA", "tktB", "talA", "talB"],
    "respiration_atp": ["nuoA", "nuoB", "nuoC", "nuoE", "nuoF", "nuoG", "nuoH", "cyoA", "cyoB", "cyoC",
                        "cyoD", "cydA", "cydB", "atpA", "atpB", "atpC", "atpD", "atpE", "atpF", "atpG", "atpH"],
    "aa_biosynthesis": ["ilvB", "ilvC", "ilvD", "ilvE", "leuA", "leuB", "trpA", "trpB", "trpE", "hisG",
                        "argA", "thrA", "metA", "serA", "aroA", "glnA", "gltB"],
    "amr_efflux": ["acrA", "acrB", "acrD", "acrF", "tolC", "marA", "marR", "soxS", "soxR", "rob",
                   "emrA", "emrB", "mdtK", "mdfA"],
    "oxidative_stress": ["sodA", "sodB", "katG", "katE", "ahpC", "ahpF", "oxyR"],
    "global_regulators": ["crp", "fnr", "arcA", "fis", "hns", "lrp", "ihfA", "ihfB", "fur", "cra"],
    "proteostasis": ["groL", "groS", "dnaK", "dnaJ", "grpE", "clpB", "clpP", "clpX", "lon", "htpG"],
    "cell_division": ["ftsZ", "ftsA", "ftsW", "ftsI", "zipA", "minC", "minD", "minE"],
}


def resolve() -> dict:
    """Resolve PATHWAY_PANEL symbols -> monomer IDs via the gene map (dumping it from sim_data if absent).
    Writes _pathway_resolved.json for the reader worker; returns per-pathway counts + any unresolved symbols."""
    if not GENE_MAP_CACHE.exists():
        from . import reader
        gm = reader.gene_map()
        if "error" in gm:
            raise RuntimeError(f"gene map failed: {gm['error']}")
        GENE_MAP_CACHE.parent.mkdir(parents=True, exist_ok=True)
        GENE_MAP_CACHE.write_text(json.dumps(gm["symbols"]), encoding="utf-8")
    symbols: dict[str, str] = json.loads(GENE_MAP_CACHE.read_text(encoding="utf-8"))

    resolved, missing = {}, {}
    for pathway, syms in PATHWAY_PANEL.items():
        resolved[pathway] = [symbols[s] for s in syms if s in symbols]
        miss = [s for s in syms if s not in symbols]
        if miss:
            missing[pathway] = miss
    RESOLVED.write_text(json.dumps(resolved), encoding="utf-8")
    return {"resolved": {p: len(v) for p, v in resolved.items()}, "missing": missing, "path": str(RESOLVED)}


if __name__ == "__main__":  # `python -m cellarium.pathway_panel` -> (re)resolve the panel to monomer IDs
    print(json.dumps(resolve(), indent=2))
