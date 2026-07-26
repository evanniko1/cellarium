"""What a `gene_knockout` ACTUALLY silences — the operon-footprint guard.

The variant does not knock out a gene. `gene_knockout.py` calls `sim_data.adjust_final_expression([geneIndex],
[0])` where the index addresses a row of `rna_data` — a TRANSCRIPTION UNIT. For a polycistronic TU the whole
operon goes to zero, so a design labelled `KO:flgB` is a nine-gene deletion. Verified against the model's own
`transcription_units.tsv`: **2,436 of 4,724 genes (52%) sit on a multi-gene TU**, and 11 of the corpus's 21
single-KO designs are affected.

Three of those carry interpretive weight, which is why this is a correctness guard and not a nicety:
  * `flgB` is used as the canonical "no phenotype BY CONSTRUCTION" inert control — it is the flgBCDEFGHIJ operon;
  * `pheS` also removes infC (IF3), thrS (a SECOND aaRS), pheT and ihfA — confounding the aaRS crash story;
  * `rpoB` also removes rpoC and four ribosomal proteins — confounding "survives on inherited RNAP reserve".
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")

import pytest  # noqa: E402

from cellarium import scope  # noqa: E402

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "ko_footprint.json")
_HAS_CACHE = os.path.exists(CACHE)
pytestmark = pytest.mark.skipif(not _HAS_CACHE, reason="ko_footprint cache not built")


def test_flgB_is_a_nine_gene_operon_not_an_inert_single_gene_control():
    """The one that matters most: scope.py calls flgB 'no phenotype BY CONSTRUCTION'. It is nine genes."""
    fp = scope.ko_footprint("flgB")
    assert fp and fp["n_genes"] == 9 and fp["tu_id"] == "TU00273"
    assert set(fp["co_silenced"]) == {"flgC", "flgD", "flgE", "flgF", "flgG", "flgH", "flgI", "flgJ"}


def test_the_aaRS_and_rnap_stories_are_flagged_as_confounded():
    ph = scope.ko_footprint("pheS")
    assert ph and {"infC", "thrS", "pheT", "ihfA"} <= set(ph["co_silenced"])   # IF3 + a second aaRS
    rp = scope.ko_footprint("rpoB")
    assert rp and "rpoC" in rp["co_silenced"]
    assert sum(1 for g in rp["co_silenced"] if g.startswith(("rpl", "rpm", "rps"))) >= 4


def test_a_genuinely_monocistronic_ko_reports_no_footprint():
    """The guard must not cry wolf — pfkA really is a single-gene knockout."""
    assert scope.ko_footprint("pfkA") is None


def test_classify_gene_surfaces_an_unmissable_warning():
    """The agent reads mechanistic_scope; the footprint has to arrive there, phrased as a constraint on the claim."""
    c = scope.classify_gene("flgB")
    w = (c.get("ko_footprint") or {}).get("warning", "")
    assert "NOT a single-gene knockout" in w and "flgC" in w
    assert "attributable to the OPERON" in w
    assert scope.classify_gene("pfkA").get("ko_footprint") is None


def test_every_corpus_single_ko_is_either_clean_or_flagged():
    """No corpus KO may be silently multi-gene: each is either monocistronic or carries a footprint."""
    from cellarium import survey
    rows = survey._deduped_rows(survey.CHANNELS)
    if not rows or "__error__" in rows[0]:
        pytest.skip("no local manifest")
    keys = {survey.design_key(r) for r in rows}
    kos = sorted({k.split("KO:")[1] for k in keys if "/KO:" in k and "+" not in k})
    if not kos:
        pytest.skip("no single-KO designs")
    flagged = [g for g in kos if scope.ko_footprint(g)]
    # the 11 known-affected designs; if this shrinks, the cache or the mapping regressed
    assert {"flgB", "pheS", "rpoB", "rplB", "rpmJ", "dnaN", "glmS", "dapA", "lysS", "selA", "ymgD"} <= set(flagged)
    for g in kos:
        fp = scope.ko_footprint(g)
        assert fp is None or (fp["n_genes"] > 1 and fp["co_silenced"])


def test_the_cache_covers_the_expected_share_of_the_genome():
    """Roughly half the genome sits on a polycistronic TU — a large drop means the build broke."""
    data = json.load(open(CACHE, encoding="utf-8"))
    assert 2000 < len(data) < 3200, f"{len(data)} genes flagged — expected ~2,436"
    assert all(v["n_genes"] > 1 for v in data.values())
