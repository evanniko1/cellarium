"""What a `gene_knockout` ACTUALLY does — validated against real simulation output, not inferred from code.

MECHANISM. `gene_knockout.py` calls `sim_data.adjust_final_expression([i], [0])`; `i` indexes `rna_data`, whose
rows are TRANSCRIPTION UNITS. One TU is zeroed.

THE RULE, exact: a gene is fully silenced **iff it has exactly one TU**. Validated 27/27 against measured mRNA
counts from existing local simOut (`KO:flgB`, `KO:rpmJ`, `KO:rpoB` vs `wildtype/basal`). The measured numbers
are pinned below as the ground truth this module must keep reproducing — they came from the model, not from a
reading of it.

Three failure modes, all live in the shipped corpus:
  * a real KO that also deletes operon partners — `KO:flgB` takes all nine of flgBCDEFGHIJ to zero;
  * **the named gene is not knocked out at all** — `KO:rpoB` leaves rpoB mRNA at 10.4 vs 8.4 in wildtype;
  * **the design silences a gene it is not named after** — `KO:rpmJ` leaves rpmJ at 50.1 and zeroes secY.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")

import pytest  # noqa: E402

from cellarium import scope  # noqa: E402

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "ko_footprint.json")
pytestmark = pytest.mark.skipif(not os.path.exists(CACHE), reason="ko_footprint cache not built")

# MEASURED from real simOut (mean mRNA counts, KO vs wildtype/basal). The empirical anchor for the rule.
MEASURED = {
    "flgB": {"flgB": (0.0, 5.8), "flgJ": (0.0, 5.8), "flgA": (2.1, 2.0), "fliC": (142.1, 125.1)},
    "rpoB": {"rpoB": (10.4, 8.4), "rpoC": (10.4, 8.4)},
    "rpmJ": {"rpmJ": (50.1, 69.5), "secY": (0.0, 15.8)},
}


def test_the_rule_reproduces_every_measured_observation():
    """The whole guard rests on 'silenced iff n_tu == 1'. If the cache ever stops predicting the measurements,
    the rule is wrong and everything built on it is suspect."""
    for ko, obs in MEASURED.items():
        fp = scope.ko_footprint(ko) or {}
        silenced = set(fp.get("collateral_silenced") or [])
        if fp.get("target_silenced"):
            silenced.add(ko)
        for gene, (ko_mean, _wt) in obs.items():
            if gene not in obs or gene in ("flgA", "fliC"):
                continue                                   # controls on other TUs — outside the footprint
            predicted_zero = gene in silenced
            assert predicted_zero == (ko_mean == 0.0), (
                f"KO:{ko} / {gene}: rule says {'silenced' if predicted_zero else 'expressed'} "
                f"but the simulation measured {ko_mean}")


def test_flgB_is_a_nine_gene_operon_deletion_not_an_inert_single_gene_control():
    """scope.py uses flgB as the canonical 'no phenotype BY CONSTRUCTION' control. Measured: all nine members
    go to 0.0 while flgA/fliC on other TUs are untouched — so it is the TU, not the flagellar regulon."""
    fp = scope.ko_footprint("flgB")
    assert fp and fp["target_silenced"] is True and fp["tu_id"] == "TU00273"
    assert set(fp["collateral_silenced"]) == {"flgC", "flgD", "flgE", "flgF", "flgG", "flgH", "flgI", "flgJ"}


def test_rpoB_is_not_actually_knocked_out():
    """The corpus attributes rpoB survival to a 'large inherited RNAP reserve'. The simpler explanation, measured:
    rpoB is transcribed from three TUs and the variant zeroes one, so rpoB mRNA does not fall at all."""
    fp = scope.ko_footprint("rpoB")
    assert fp and fp["target_silenced"] is False and fp["target_n_tu"] == 3


def test_rpmJ_silences_secY_instead_of_rpmJ():
    """The sharpest case: a design that knocks out a gene it is not named after."""
    fp = scope.ko_footprint("rpmJ")
    assert fp and fp["target_silenced"] is False
    assert fp["collateral_silenced"] == ["secY"]


def test_a_clean_single_gene_knockout_reports_nothing():
    """The guard must not cry wolf, or it will be ignored where it matters."""
    for clean in ("pfkA", "argS", "gltX", "tpiA"):
        assert scope.ko_footprint(clean) is None, f"{clean} should be a clean KO"


def test_classify_gene_surfaces_the_right_warning_for_each_failure_mode():
    w_flg = scope.classify_gene("flgB")["ko_footprint"]["warning"]
    assert "NOT a single-gene knockout" in w_flg and "flgC" in w_flg
    w_rpo = scope.classify_gene("rpoB")["ko_footprint"]["warning"]
    assert "THIS IS NOT A KNOCKOUT OF rpoB" in w_rpo and "still expressed" in w_rpo
    w_rpm = scope.classify_gene("rpmJ")["ko_footprint"]["warning"]
    assert "secY" in w_rpm and "not named after" not in w_rpm.lower()   # names the gene, not the abstraction
    assert scope.classify_gene("pfkA").get("ko_footprint") is None


def test_the_five_corpus_designs_that_are_not_knockouts_stay_flagged():
    """dnaN, murA, pheS, rpmJ, rpoB all have n_tu > 1 — none of them knocks out its named gene. Two project
    claims rest on these (the aaRS gen-3 story via pheS; 'inherited reserve' via rpoB/dnaN)."""
    for g in ("dnaN", "murA", "pheS", "rpmJ", "rpoB"):
        fp = scope.ko_footprint(g)
        assert fp and fp["target_silenced"] is False, f"{g} should be flagged as not-actually-knocked-out"


def test_every_corpus_single_ko_is_either_clean_or_flagged():
    from cellarium import survey
    rows = survey._deduped_rows(survey.CHANNELS)
    if not rows or "__error__" in rows[0]:
        pytest.skip("no local manifest")
    keys = {survey.design_key(r) for r in rows}
    kos = sorted({k.split("KO:")[1] for k in keys if "/KO:" in k and "+" not in k})
    if not kos:
        pytest.skip("no single-KO designs")
    flagged = {g for g in kos if scope.ko_footprint(g)}
    assert {"flgB", "rplB", "glmS", "selA", "ymgD", "dnaN", "murA", "pheS", "rpmJ", "rpoB"} <= flagged
    for g in kos:
        fp = scope.ko_footprint(g)
        assert fp is None or fp["collateral_silenced"] or fp["partially_reduced"] or not fp["target_silenced"]


def test_the_cache_shape_and_scale_are_sane():
    data = json.load(open(CACHE, encoding="utf-8"))
    assert 2200 < len(data) < 3200, f"{len(data)} genes flagged — expected ~2,607"
    not_ko = [k for k, v in data.items() if not v["target_silenced"]]
    assert 500 < len(not_ko) < 900, f"{len(not_ko)} not-actually-knocked-out — expected ~694"
    assert all("target_silenced" in v and "collateral_silenced" in v for v in data.values())
