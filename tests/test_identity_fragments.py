"""A design key's tag fragments are all identity (D27, 2026-11-27).

The tag writer (`manifest._design_tag`) appends fragments in a fixed order: `#expr`, `#tl`, `#ic`, `#tf`, `#occ`,
`#ppgpp`, `#it`, `#elong`. The reader (`factors.parse`) lifted `#tl:` and `#expr:` by partitioning, as if each were
the LAST fragment. Every fragment written after them was swallowed:

- after `#tl:` into the timeline id (`175649#ic:acetate`), and for a non-knockout design out of the canonical id
  altogether, so CRIT V1's medium and relaxed acetate arms, and S4b's shifted wildtype and rRNA knockouts, collapsed
  onto the static designs' canonical experiments;
- after `#expr:` into the dose, which then failed to parse, so S2's three ppGpp-clamped argS doses collapsed onto one
  canonical id with neither dose nor clamp.

Every expectation below is a literal string: the old ids that must not move, and the merged ones that must split.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cellarium import corpus_schema, factors  # noqa: E402


def cid(key: str) -> str:
    return factors.identity(key)["canonical_id"]


def test_a_fragment_after_the_timeline_stays_in_the_identity():
    assert cid("wildtype/acetate#tl:175649#ic:acetate") == "wildtype#wildtype:acetate#tl:175649#ic:acetate"
    assert cid("wildtype/acetate#tl:175649#ic:acetate#it:relaxed") == \
        "wildtype#wildtype:acetate#tl:175649#ic:acetate#it:relaxed"
    p = factors.parse("wildtype/acetate#tl:175649#ic:acetate#it:relaxed")
    assert p["timeline_id"] == "175649" and p["initial_condition"] == "acetate"
    assert p["extras"] == ["ic:acetate", "it:relaxed"]


def test_a_fragment_after_the_dose_keeps_the_dose_and_the_fragment():
    p = factors.parse("graded_gene_knockout/KO:argS#expr:0.25#ppgpp:basal")
    assert p["level_num"] == 0.25 and p["level_raw"] == "0.25" and p["genes"] == ["argS"]
    assert cid("graded_gene_knockout/KO:argS#expr:0.25#ppgpp:basal") == "graded_gene_knockout#idx:644@0.25#ppgpp:basal"
    doses = [cid(f"graded_gene_knockout/KO:argS#expr:{x}#ppgpp:basal") for x in ("0.1", "0.25", "0.5")]
    assert len(set(doses)) == 3


def test_a_shifted_design_does_not_merge_with_the_static_one():
    """S4b: started fitted to rich medium, then downshifted. Its wildtype control and its rRNA arms."""
    assert cid("wildtype/basal#tl:93af15#ic:with_aa") == "wildtype#wildtype:basal#tl:93af15#ic:with_aa"
    assert cid("rrna_operon_knockout/minimal|rRNA_KO:4op#tl:93af15#ic:with_aa") == \
        "rrna_operon_knockout#rrna_removed:4of7#tl:93af15#ic:with_aa"
    assert factors.parse("rrna_operon_knockout/minimal|rRNA_KO:4op#tl:93af15#ic:with_aa")["level_num"] == 4
    keys = ["wildtype/basal", "wildtype/basal#tl:93af15#ic:with_aa", "rrna_operon_knockout/minimal|rRNA_KO:4op",
            "rrna_operon_knockout/minimal|rRNA_KO:4op#tl:93af15#ic:with_aa"]
    assert not factors.dedupe(keys).get("duplicates")


def test_todays_designs_are_four_sets_of_distinct_experiments():
    keys = ["wildtype/acetate#tl:175649#ic:acetate", "wildtype/acetate#tl:175649#ic:acetate#it:relaxed",
            "wildtype/no_oxygen#tl:77fb74#ic:no_oxygen", "wildtype/no_oxygen#tl:77fb74#ic:no_oxygen#it:relaxed",
            "graded_gene_knockout/KO:argS#expr:0.1#ppgpp:basal", "graded_gene_knockout/KO:argS#expr:0.25#ppgpp:basal",
            "graded_gene_knockout/KO:argS#expr:0.5#ppgpp:basal", "graded_gene_knockout/KO:argS#expr:0.25",
            "wildtype/basal#tl:93af15#ic:with_aa", "wildtype/basal",
            "rrna_operon_knockout/minimal|rRNA_KO:2op#tl:93af15#ic:with_aa", "rrna_operon_knockout/minimal|rRNA_KO:2op"]
    assert not factors.dedupe(keys).get("duplicates")


def test_an_unknown_fragment_separates_rather_than_merges():
    assert cid("wildtype/basal#tl:93af15#ic:with_aa#zz:1") != cid("wildtype/basal#tl:93af15#ic:with_aa")
    assert cid("graded_gene_knockout/KO:argS#expr:0.25#zz:1") != cid("graded_gene_knockout/KO:argS#expr:0.25")


def test_every_id_already_in_the_corpus_stays_put():
    """No existing canonical id, base, level or medium moves; only the merged ones split."""
    assert cid("gene_knockout/KO:cyaA#tl:175649#ic:acetate") == "gene_knockout#idx:1428#tl:175649#ic:acetate"
    assert cid("gene_knockout/KO:leuB#tl:379e4c") == "gene_knockout#idx:1818#tl:379e4c"
    assert cid("graded_gene_knockout/KO:argS#expr:0.25") == "graded_gene_knockout#idx:644@0.25"
    assert cid("graded_gene_knockout/KO:leuS#expr:0.25#elong:kinetic") == \
        "graded_gene_knockout#idx:255@0.25#elong:kinetic"
    assert cid("rrna_operon_knockout/minimal|rRNA_KO:4op") == "rrna_operon_knockout#rrna_removed:4of7"
    assert cid("ppgpp_conc/basal|ppGpp:1x") == "ppgpp_conc#ppGpp:1x"
    assert cid("wildtype/basal#it:relaxed") == "wildtype#wildtype:basal#it:relaxed"
    occ = "condition/no_oxygen#occ:FNR-4FE-4S-CPLX=0+PHOSPHO-NARL=fit"
    assert cid(occ) == "condition#media:no_oxygen#occ:FNR-4FE-4S-CPLX=0+PHOSPHO-NARL=fit"
    assert factors.parse(occ)["base"] == "no_oxygen#occ:FNR-4FE-4S-CPLX=0+PHOSPHO-NARL=fit"
    assert factors.parse("wildtype/basal#it:relaxed")["base"] == "basal#it:relaxed"
    p = factors.parse("gene_knockout/KO:cyaA#tl:175649#ic:acetate")
    assert (p["base"], p["level_raw"], p["genes"]) == ("basal", "cyaA", ["cyaA"])


def test_the_medium_key_keeps_the_initial_condition_it_used_to_carry_by_accident():
    """`medium_of` keyed on (base, timeline_id), and the timeline id carried the swallowed `#ic:`. The fitted start is
    part of the medium history, so the key keeps it, now on purpose and with the same value."""
    row = {"perturbation": "gene_knockout", "label": "gene_knockout·KO:cyaA#tl:175649#ic:acetate·s0"}
    assert corpus_schema.medium_of(row) == ("basal", "175649#ic:acetate")
    row2 = {"perturbation": "gene_knockout", "label": "gene_knockout·KO:leuB#tl:379e4c·s0"}
    assert corpus_schema.medium_of(row2) == ("basal", "379e4c")
