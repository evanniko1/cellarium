"""J-2: every design's label set against what its run did, as one catalogue, with the known positives as recall.

Knockouts are rebuilt by the design-identity check that found the 25 (`factors.identity`): what the variant's
index actually silences. Conditions were marked "ok" without being looked at. A condition's label names what was
added or removed; the knowledge base says what else the medium holds, and two of the corpus's conditions are read
as something their medium rules out: plus_nitrate keeps oxygen, so it is not nitrate respiration, and
plus_arabinose keeps glucose, so it is not growth on arabinose.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))

import label_mechanism as L  # noqa: E402


def test_an_acceptor_added_under_oxygen_is_flagged():
    h = L.condition_hazards("plus_nitrate")
    assert [x["class"] for x in h] == ["acceptor_added_under_oxygen"]
    assert "not nitrate respiration" in h[0]["reading_ruled_out"]


def test_a_carbon_source_added_beside_glucose_is_flagged():
    h = L.condition_hazards("plus_arabinose")
    assert [x["class"] for x in h] == ["carbon_source_added_beside_glucose"]
    assert "not growth on arabinose" in h[0]["reading_ruled_out"]


@pytest.mark.parametrize("condition", ["acetate", "succinate", "no_oxygen", "with_aa", "plus_indole",
                                       "minus_magnesium", "glc_2mM"])
def test_a_condition_whose_medium_matches_its_reading_is_not_flagged(condition):
    assert L.condition_hazards(condition) == []


def test_an_unknown_condition_is_unverified_not_clean():
    assert L.condition_hazards("plus_unobtainium") == [{"class": "unverified",
                                                         "reading_ruled_out": "no medium on record to compare"}]


def test_the_catalogue_carries_the_known_positives():
    cat = L.catalogue(sorted(L.CORPUS_DESIGNS_2026_11_24))
    by = {c: set(v["designs"]) for c, v in cat["classes"].items()}
    # the 25 the identity check found, by class (literal: read from the 82-design manifest on 2026-11-24)
    assert (len(by["misnamed"]), len(by["operon_wide"]), len(by["relabel_required"])) == (9, 13, 3)
    assert "gene_knockout/KO:rpoB" in by["misnamed"] and "gene_knockout/KO:flgB" in by["operon_wide"]
    # and the condition read as nitrate respiration
    assert "condition/plus_nitrate" in by["acceptor_added_under_oxygen"]
    assert "condition/plus_arabinose" in by["carbon_source_added_beside_glucose"]
    assert (cat["n_designs"], cat["n_flagged"], cat["n_unverified"]) == (82, 27, 4)
    # the four the identity check could not verify are named apart, not counted as findings
    assert by["unverified"] == {f"graded_gene_knockout/KO:argS@{x}" for x in ("0.05", "0.10", "0.25", "0.50")}


def _kb(*parts):
    return Path(os.environ["WCECOLI_DIR"]) / "reconstruction" / "ecoli" / "flat" / "condition" / Path(*parts)


def _tsv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader([line for line in f if not line.startswith("#")], delimiter="\t"))


def test_the_knowledge_base_still_says_what_the_media_table_cites():
    if not (os.environ.get("WCECOLI_DIR") and os.path.isdir(os.environ["WCECOLI_DIR"])):
        pytest.skip("no model checkout: the media cannot be re-read from the knowledge base here")
    recipes = {r["media id"]: r for r in _tsv(_kb("media_recipes.tsv"))}
    nutrients = {r["condition"]: r["nutrients"] for r in _tsv(_kb("condition_defs.tsv"))}
    for condition, med in L.MEDIA.items():
        recipe = recipes[nutrients[condition]]
        base = {r["molecule id"]: r for r in _tsv(_kb("media", recipe["base media"] + ".tsv"))}
        added = [x.strip().strip('"') for x in recipe["ingredients"].strip("[]").split(",") if x.strip()]
        weights = [x.strip() for x in recipe["ingredients weight (units.g)"].strip("[]").split(",") if x.strip()]
        present = set(base) | {a for a, w in zip(added, weights) if w != "-Infinity"}
        present -= {a for a, w in zip(added, weights) if w == "-Infinity"}
        if recipe.get("added media"):
            present |= {"amino acids"}
        assert ("OXYGEN-MOLECULE" in present) == med["oxygen"], condition
        assert ("GLC" in present) == ("GLC" in med["carbon"]), condition
        for a in med["added"]:
            assert a in present, (condition, a)
