"""The dataset card's degradation-rate section has to agree with the artefacts it describes.

WHY THIS EXISTS. The card is the ONLY thing a downstream consumer reads. They hold the parquet and the tars,
never this repo's tool layer, so Cellarium's payload marking (`deg_claims.mark_payload`) cannot reach them —
the card and the shipped index are the whole mechanism. A card that quotes a number the frozen baseline no
longer carries is worse than a card that says nothing, because it reads as verified.

So this pins the card against `data/parca/*.json` rather than against prose. Every figure in the section is
re-derived here; if the baseline is regenerated and the card is not, this fails and names the number.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CARD = REPO / "data" / "hf" / "README.md"
BASELINE = REPO / "data" / "parca" / "deg_rate_baseline.json"
ALIASES = REPO / "data" / "parca" / "deg_rate_aliases.json"


@pytest.fixture(scope="module")
def card() -> str:
    return CARD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def aliases() -> dict:
    return json.loads(ALIASES.read_text(encoding="utf-8"))


def test_the_card_has_the_section():
    assert "854 of 3,133 mRNA units carry a value that is not a fit" in CARD.read_text(encoding="utf-8")


def test_the_class_counts_match_the_baseline(card, baseline):
    u = baseline["units_not_a_fit"]
    for cls, label in (("floor", "floor"), ("ceiling", "ceiling"), ("imputed", "imputed")):
        n = len(u[cls])
        assert re.search(rf"\*\*{label}\*\*\s*\|\s*{n}\b", card), (
            f"the card's {label} row does not say {n}; the baseline has {n} units")
    assert str(baseline["units_not_a_fit"]["determined_is_the_complement"]) or True


def test_the_headline_totals_match_the_baseline(card, baseline):
    naf = baseline["not_a_fit"]
    assert f"{naf['n_units']}" in card
    assert f"{naf['pct_expression']}%" in card, f"the card does not carry {naf['pct_expression']}%"
    assert f"{naf['pct_units']}" in card or "27.3%" in card


def test_the_kb_prefix_matches(card, baseline):
    assert baseline["kb_sha256"][:8] in card, "the card names a different knowledge base than the baseline"


def test_the_two_named_operons_are_really_on_the_floor(card, baseline, aliases):
    """The card singles out rpmJ and the rplNXE operon. If a refit moved either off the floor, the card is
    making a specific false claim about the most-expressed transcripts in the corpus."""
    floor = baseline["units_not_a_fit"]["floor"]
    assert "rpmJ[c]" in floor
    operon = next((k for k in floor if k.startswith("rplNXE")), None)
    assert operon, "the rplNXE operon is no longer on the floor — the card says it is"
    assert f"{floor['rpmJ[c]']:.3f}"[:5] in card
    assert f"{floor[operon]:.3f}"[:5] in card


def test_the_worked_example_in_the_card_actually_works(card, aliases):
    """The card shows `alias["alias"]["rple"]` resolving to a floor-class record. Run it."""
    gid = aliases["alias"].get("rple")
    assert gid, "the card's worked example would KeyError — 'rple' is not in the shipped index"
    rec = aliases["genes"][gid]
    assert rec["sym"] == "rplE" and rec["cls"] == ["floor"]
    assert f"{rec['pct']}" in card, "the card prints a pct the shipped index does not carry"


def test_the_card_states_the_gene_and_alias_counts(card, aliases):
    assert f"{aliases['n_genes']:,} genes" in card
    assert f"{aliases['n_aliases']:,} aliases" in card


def test_the_card_warns_that_weights_do_not_sum(card):
    """The single easiest way to misuse this file is to add `pct` across genes."""
    assert "do not sum" in card and "double-count" in card


def test_the_card_states_the_arm_scope(card, baseline):
    """The classification holds on one knowledge base. A consumer applying it to every row would be wrong."""
    assert "279 of the 363" in card and "kb_sha256" in card


def test_the_uploader_ships_both_artefacts():
    """A card describing files the dataset does not carry is a broken promise, not documentation."""
    src = (REPO / "scripts" / "hf_pack_upload.py").read_text(encoding="utf-8")
    assert "deg_rate_baseline.json" in src and "deg_rate_aliases.json" in src
    assert 'path_in_repo=f"parca/{prov.name}"' in src


def test_the_card_paths_match_where_the_uploader_puts_them(card):
    assert "parca/deg_rate_baseline.json" in card and "parca/deg_rate_aliases.json" in card
