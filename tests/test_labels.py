"""J-2b: every surface that names a design can say what the design is, from one function.

A condition's label names what was added or removed; the medium holds the rest. `plus_nitrate` is an aerobic
glucose medium with nitrate added (so not nitrate respiration), and `plus_arabinose` keeps glucose (so not growth on
arabinose). J-2 (2026-11-24) catalogued this in evals/; `cellarium.labels` is the platform's copy, built from the
knowledge base's own tables (data/parca/condition_fits.json), so the survey, the Council's instrument, the
interface and the dataset card all say the same thing."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import labels  # noqa: E402


def test_plus_nitrate_reads_as_aerobic_glucose_with_nitrate():
    d = labels.describe("condition/plus_nitrate")
    assert "aerobic glucose medium" in d["true_label"] and "nitrate" in d["true_label"]
    assert [h["class"] for h in d["hazards"]] == ["acceptor_added_under_oxygen"]
    assert "NarL" in d["true_label"] or "narL" in d["true_label"]


def test_plus_arabinose_keeps_glucose():
    d = labels.describe("condition/plus_arabinose")
    assert [h["class"] for h in d["hazards"]] == ["carbon_source_added_beside_glucose"]


def test_anaerobic_nitrate_is_not_flagged():
    # BV-14's condition: nitrate with oxygen removed IS nitrate respiration
    assert labels.describe("condition/no_oxygen_plus_nitrate")["hazards"] == []


def test_a_medium_with_no_carbon_says_so():
    d = labels.describe("condition/no_glucose")
    assert "no carbon source" in d["medium"]["description"]
    assert [h["class"] for h in d["hazards"]] == ["no_carbon_source"]


def test_a_plain_condition_has_no_hazard_and_names_its_fit():
    d = labels.describe("condition/acetate")
    assert d["hazards"] == [] and "aerobic acetate medium" in d["true_label"]
    assert "base model" in d["true_label"]


def test_wildtype_basal_is_the_reference():
    d = labels.describe("wildtype/basal")
    assert d["hazards"] == [] and "aerobic glucose medium" in d["true_label"]


def test_a_misnamed_knockout_carries_its_true_label():
    d = labels.describe("gene_knockout/KO:rpoB")
    assert d["hazards"] and d["hazards"][0]["class"] == "misnamed"
    assert "rplKAJL-rpoBC" in d["true_label"]


def test_compound_ids_read_as_names():
    assert "gallate" in labels.describe("condition/plus_gallate")["medium"]["description"]


def test_an_unknown_condition_is_unverified_not_clean():
    d = labels.describe("condition/made_up_medium")
    assert [h["class"] for h in d["hazards"]] == ["unverified"]
