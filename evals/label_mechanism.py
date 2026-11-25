"""J-2: every design's label set against what its run did, as one catalogue (the data behind item 9).

Knockouts and rRNA designs are rebuilt by the design-identity check (`factors.identity`): what the variant's index
actually silences, read from the model's gene scope and measured footprints. That check found the 25 known positives:
9 misnamed (the named gene is not what is silenced), 13 operon-wide (the whole transcription unit goes), and 3 rRNA
designs that are a dose of total capacity rather than an operon deletion.

Conditions were marked "ok" without being looked at. A condition's label names what was added or removed; the medium
holds the rest. MEDIA below is the knowledge base's own composition of each corpus condition (media_recipes.tsv and
media/*.tsv on the campaign branch, read 2026-11-24, and re-read by tests/test_label_mechanism.py wherever the
checkout is present). Two readings are ruled out by it:
  acceptor_added_under_oxygen          an electron acceptor added to a medium that keeps oxygen: oxygen is the
                                       preferred acceptor, so the run is aerobic growth with the acceptor present
  carbon_source_added_beside_glucose   a carbon source added to a medium that keeps glucose: the run grows on glucose
                                       with the sugar present, not on the sugar

    python evals/label_mechanism.py    # writes evals/results/label_mechanism_catalogue.json

LIMITS. The condition rules are two, each written because it rules out a reading this project made (plus_nitrate as
nitrate respiration and plus_arabinose as a missing on-switch, both in July); a reading nobody has made is not
tested. The knockout classes are the identity check's; a gene it cannot check is "unverified", never "ok".
"""
from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import factors  # noqa: E402

OUT = REPO / "evals" / "results" / "label_mechanism_catalogue.json"

# The manifest's 82 design keys on 2026-11-24, frozen so the catalogue's counts do not move with the local store.
CORPUS_DESIGNS_2026_11_24 = (
    'condition/acetate',
    'condition/glc_20mM',
    'condition/glc_2mM',
    'condition/glc_5mM',
    'condition/minus_magnesium',
    'condition/minus_phosphate',
    'condition/no_oxygen',
    'condition/plus_arabinose',
    'condition/plus_indole',
    'condition/plus_nitrate',
    'condition/succinate',
    'condition/with_aa',
    'gene_knockout/KO:alaS',
    'gene_knockout/KO:argG#tl:38639c',
    'gene_knockout/KO:argG#tl:531be4',
    'gene_knockout/KO:argS',
    'gene_knockout/KO:argS#elong:kinetic',
    'gene_knockout/KO:dapA',
    'gene_knockout/KO:dnaN',
    'gene_knockout/KO:fabI',
    'gene_knockout/KO:flgB',
    'gene_knockout/KO:glmS',
    'gene_knockout/KO:gltA',
    'gene_knockout/KO:gltX',
    'gene_knockout/KO:leuB',
    'gene_knockout/KO:leuB#tl:379e4c',
    'gene_knockout/KO:leuB#tl:38639c',
    'gene_knockout/KO:lpxC',
    'gene_knockout/KO:lysS',
    'gene_knockout/KO:murA',
    'gene_knockout/KO:pfkA',
    'gene_knockout/KO:pgi',
    'gene_knockout/KO:pheS',
    'gene_knockout/KO:rplB',
    'gene_knockout/KO:rpmE',
    'gene_knockout/KO:rpmJ',
    'gene_knockout/KO:rpoB',
    'gene_knockout/KO:selA',
    'gene_knockout/KO:thrC#tl:38639c',
    'gene_knockout/KO:thrC#tl:b0ae2f',
    'gene_knockout/KO:tpiA',
    'gene_knockout/KO:valS',
    'gene_knockout/KO:ymgD',
    'graded_gene_knockout/KO:argS',
    'graded_gene_knockout/KO:argS#expr:0.05',
    'graded_gene_knockout/KO:argS#expr:0.1',
    'graded_gene_knockout/KO:argS#expr:0.25',
    'graded_gene_knockout/KO:argS#expr:0.5',
    'graded_gene_knockout/KO:argS@0.05',
    'graded_gene_knockout/KO:argS@0.10',
    'graded_gene_knockout/KO:argS@0.25',
    'graded_gene_knockout/KO:argS@0.50',
    'graded_gene_knockout/KO:murA#expr:0.1',
    'graded_gene_knockout/KO:murA#expr:0.5',
    'graded_gene_knockout/KO:murA#expr:0.9',
    'metabolism_kinetic_objective_weight/basal',
    'metabolism_kinetic_objective_weight/minimal|kin_w:0',
    'metabolism_kinetic_objective_weight/minimal|kin_w:0.1',
    'metabolism_kinetic_objective_weight/minimal|kin_w:1',
    'metabolism_kinetic_objective_weight/minimal|kin_w:1e-4',
    'metabolism_kinetic_objective_weight/minimal|kin_w:1e-5',
    'metabolism_kinetic_objective_weight/minimal|kin_w:1e-6',
    'metabolism_kinetic_objective_weight/minimal|kin_w:1e-7_default',
    'metabolism_kinetic_objective_weight/minimal|kin_w:1e-8',
    'metabolism_secretion_penalty/minimal|sec_pen:0',
    'metabolism_secretion_penalty/minimal|sec_pen:0.01',
    'metabolism_secretion_penalty/minimal|sec_pen:0.05',
    'metabolism_secretion_penalty/minimal|sec_pen:1e-3',
    'metabolism_secretion_penalty/minimal|sec_pen:5e-4',
    'multi_gene_knockout/KO:gltX+relA+spoT',
    'multi_gene_knockout/KO:pfkA+pfkB',
    'ppgpp_conc/basal|ppGpp:0.2x',
    'ppgpp_conc/basal|ppGpp:0.6x',
    'ppgpp_conc/basal|ppGpp:1.6x',
    'ppgpp_conc/basal|ppGpp:2.0x',
    'rrna_operon_knockout/minimal|rRNA_KO:2op',
    'rrna_operon_knockout/minimal|rRNA_KO:4op',
    'rrna_operon_knockout/minimal|rRNA_KO:6op',
    'timeline/0 minimal, 1200 minimal_plus_amino_acids',
    'timeline/0 minimal_plus_amino_acids, 1200 minimal',
    'wildtype/basal',
    'wildtype/basal#elong:kinetic',
)

# Each corpus condition's medium, from the knowledge base: the carbon sources present, whether oxygen is present, and
# what the recipe adds to its base medium (MIX0-57 is glucose minimal medium with oxygen).
# J-2b (2026-11-25): the media and the condition rules now live in the platform (cellarium.labels), read from the
# knowledge base's own tables for every condition (data/parca/condition_fits.json), not from a hand-entered table of
# the twelve corpus conditions. This catalogue uses them, so it and every surface say the same thing.
from cellarium import labels as _labels  # noqa: E402


def condition_hazards(condition: str) -> list[dict]:
    """The readings a condition's label invites and its medium rules out; [] when there are none to find."""
    from cellarium import provenance
    fit = provenance.condition_fits().get(condition)
    return _labels.condition_hazards(fit.get("medium") if fit else None)


def classify(design: str) -> list[dict]:
    """One design's findings: the identity check's class for a knockout or an rRNA design, the condition rules for
    a condition. [] for a design whose label describes its run."""
    family, _, tag = design.partition("/")
    if family == "condition":
        return condition_hazards(tag)
    ident = factors.identity(design)
    if ident["label_integrity"] == "ok":
        return []
    return [{"class": ident["label_integrity"], "true_label": ident.get("true_label"),
             "notes": list(ident.get("notes") or [])[:3]}]


def catalogue(designs) -> dict:
    classes: dict[str, dict] = collections.defaultdict(lambda: {"designs": [], "examples": []})
    flagged = unverified = 0
    for d in designs:
        found = classify(d)
        # "could not check" is not a finding: counted apart, never as a mismatch and never as clean
        flagged += any(f["class"] != "unverified" for f in found)
        unverified += any(f["class"] == "unverified" for f in found)
        for f in found:
            c = classes[f["class"]]
            c["designs"].append(d)
            if len(c["examples"]) < 3:
                c["examples"].append({"design": d, **{k: v for k, v in f.items() if k != "class"}})
    return {"n_designs": len(designs), "n_flagged": flagged, "n_unverified": unverified,
            "classes": {k: {**v, "n": len(v["designs"])} for k, v in sorted(classes.items())}}


def main() -> int:
    from cellarium import provenance
    out = {"spec": "J-2", "designs": "the 82-design manifest of 2026-11-24 (CORPUS_DESIGNS_2026_11_24)",
           **catalogue(CORPUS_DESIGNS_2026_11_24),
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "environment": provenance.code_environment()}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: (v["n"] if isinstance(v, dict) and "n" in v else v)
                      for k, v in out["classes"].items()}), out["n_flagged"], "of", out["n_designs"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
