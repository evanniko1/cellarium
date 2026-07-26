"""The declared factor schema — what a design ACTUALLY varies (WELL-1 + WELL-6m + the relabelling).

Three problems folded into one module, so the tests cover all three:

  * the factors were trapped in a label string, making "all ppGpp doses" and "the one-factor-differing neighbour"
    inexpressible;
  * the design NAME is not its IDENTITY — the gene→ko_index map is many-to-one, so `KO:pheS` and `KO:thrS` are
    the same run and would be counted as two replicates;
  * the name can be actively WRONG — `KO:flgB` deletes nine genes, `KO:rpoB` silences nothing measured.

`parse` is pure and tested in isolation; `identity` needs the committed caches and is tested against the real
corpus values, which are the ones a mistake would actually corrupt.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")

import pytest  # noqa: E402

from cellarium import factors as F  # noqa: E402

_HAS_CACHE = os.path.exists(os.path.join(os.path.dirname(__file__), "..", "data", "cache", "ko_footprint.json"))


# ---------------------------------------------------------------- parsing (pure)
def test_a_dose_design_yields_a_typed_factor_and_level():
    p = F.parse("ppgpp_conc/basal|ppGpp:0.6x")
    assert p["family"] == "ppgpp_conc" and p["base"] == "basal"
    assert p["factor"] == "ppGpp" and p["level_raw"] == "0.6x" and p["level_num"] == 0.6


@pytest.mark.parametrize("raw,expected", [
    ("0.6x", 0.6), ("2.0x", 2.0), ("4op", 4.0), ("0.01", 0.01), ("1e-4", 1e-4),
    ("1e-7_default", 1e-7),          # the suffix is real in this corpus and must not defeat the parse
    ("", None), (None, None), ("basal", None),
])
def test_level_numbers_parse_including_the_awkward_ones(raw, expected):
    assert F.level_num(raw) == expected


def test_a_knockout_is_a_SET_not_a_dose():
    """Dose-response and set-membership are different query shapes, so they live in different fields."""
    p = F.parse("multi_gene_knockout/KO:gltX+relA+spoT")
    assert p["factor"] == "gene_KO" and p["level_num"] is None
    assert p["genes"] == ["gltX", "relA", "spoT"]          # order-normalised, so A+B and B+A agree
    assert F.parse("multi_gene_knockout/KO:spoT+gltX+relA")["genes"] == p["genes"]


def test_conditions_and_timelines_parse():
    assert F.parse("condition/acetate")["factor"] == "media"
    t = F.parse("timeline/0 minimal, 1200 minimal_plus_amino_acids")
    assert t["factor"] == "timeline" and "1200" in t["level_raw"]


def test_one_factor_neighbours_is_the_correct_control_query():
    keys = ["ppgpp_conc/basal|ppGpp:0.2x", "ppgpp_conc/basal|ppGpp:0.6x", "ppgpp_conc/basal|ppGpp:2.0x",
            "condition/acetate", "gene_knockout/KO:pfkA", "rrna_operon_knockout/minimal|rRNA_KO:4op"]
    n = F.one_factor_neighbours("ppgpp_conc/basal|ppGpp:0.6x", keys)
    assert n == ["ppgpp_conc/basal|ppGpp:0.2x", "ppgpp_conc/basal|ppGpp:2.0x"]   # and in dose order


# ---------------------------------------------------------------- identity (needs the caches)
pytest_cache = pytest.mark.skipif(not _HAS_CACHE, reason="ko_footprint cache not built")


@pytest_cache
def test_alias_names_collapse_to_one_experiment():
    """WELL-6m. KO:pheS and KO:thrS are ONE run. Counted as two, they are a duplicate posing as a replicate."""
    a, b = F.identity("gene_knockout/KO:pheS"), F.identity("gene_knockout/KO:thrS")
    assert a["canonical_id"] == b["canonical_id"]
    assert "thrS" in a["aliases"] and "pheS" in b["aliases"]
    d = F.dedupe(["gene_knockout/KO:pheS", "gene_knockout/KO:thrS", "gene_knockout/KO:pfkA"])
    assert d["n_designs"] == 3 and d["n_experiments"] == 2 and len(d["duplicates"]) == 1


@pytest_cache
def test_a_clean_knockout_is_labelled_unchanged():
    i = F.identity("gene_knockout/KO:pfkA")
    assert i["label_integrity"] == "ok" and i["true_label"] == "gene_KO:pfkA" and i["aliases"] == []


@pytest_cache
def test_an_operon_wide_knockout_is_renamed_after_the_operon():
    i = F.identity("gene_knockout/KO:flgB")
    assert i["label_integrity"] == "operon_wide"
    assert i["true_label"] == "operon_KO:flgBCDEFGHIJ"
    assert {"flgC", "flgJ"} <= set(i["perturbs"])


@pytest_cache
def test_a_misnamed_knockout_says_so_in_its_label():
    """KO:rpoB silences nothing measured — the label must not let that be read as an rpoB knockout."""
    i = F.identity("gene_knockout/KO:rpoB")
    assert i["label_integrity"] == "misnamed"
    assert "TU_KO:" in i["true_label"] and "silences nothing measured" in i["true_label"]
    assert any("NOT silenced" in n for n in i["notes"])


@pytest_cache
def test_the_multi_ko_names_what_it_perturbs_and_flags_what_it_misses():
    """WELL-6n. Measured: gltX and spoT silenced, relA still expressed. The label must carry that."""
    i = F.identity("multi_gene_knockout/KO:gltX+relA+spoT")
    assert i["label_integrity"] == "misnamed"
    assert "relA NOT silenced" in i["true_label"]
    assert "gltX" in i["perturbs"] and "spoT" in i["perturbs"] and "relA" not in i["perturbs"]
    assert i["aliases"] == []                     # a multi-KO's co-addressed genes are NOT aliases of it
    assert i["same_index_genes"]                  # ...but they are recorded, because they ride the same indices


@pytest_cache
def test_rrna_designs_are_relabelled_as_a_dose_not_an_operon_deletion():
    i = F.identity("rrna_operon_knockout/minimal|rRNA_KO:4op")
    assert i["label_integrity"] == "relabel_required"
    assert i["true_label"] == "rRNA_operons_removed:4of7"
    assert i["perturbs"] == ["total_rRNA_capacity"]
    assert any("erases operon identity" in n for n in i["notes"])


@pytest_cache
def test_the_live_corpus_has_no_hidden_duplicate_experiments():
    """A guard for the future: if two shipped designs ever collapse to one canonical id, they are the same run."""
    from cellarium import survey
    rows = survey._deduped_rows(survey.CHANNELS)
    if not rows or "__error__" in rows[0]:
        pytest.skip("no local manifest")
    keys = sorted({survey.design_key(r) for r in rows})
    d = F.dedupe(keys)
    assert not d["duplicates"], f"designs that are secretly the same run: {d['duplicates']}"


@pytest_cache
def test_every_corpus_design_parses_and_gets_a_verdict():
    from cellarium import survey
    rows = survey._deduped_rows(survey.CHANNELS)
    if not rows or "__error__" in rows[0]:
        pytest.skip("no local manifest")
    for k in sorted({survey.design_key(r) for r in rows}):
        i = F.identity(k)
        assert i["family"] and i["true_label"]
        assert i["label_integrity"] in ("ok", "operon_wide", "misnamed", "relabel_required", "no_design_possible")
