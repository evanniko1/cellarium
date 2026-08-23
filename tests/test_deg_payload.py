"""PARCA-6 Tier 1 — the payload stamp, and the gene-space index it depends on.

The load-bearing tests here are the ones that would have caught the two mistakes made while building it:

  * `test_secy_is_not_in_the_map` — the first resolution pass prefix-matched the baseline unit
    `rplNXE-rpsNH-rplFR-rpsE-rpmD-rplO` onto the base table's LONGER `…-secY-rpmJ`, which attributed a floor
    rate to two genes that do not carry one. Applying `transcription_units_{added,modified,removed}.tsv`
    resolves it exactly instead. `secY` absent from the index IS the regression guard.
  * `test_stamp_reads_the_map_not_itself` — the stamp must derive its verdict from the frozen artefact.
    A previous check in this repo computed its diagnostic from its own expression, so injecting a fault
    changed both together and it stayed green. Here the fault is injected into the MAP and the stamp has to
    notice.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import deg_claims as D  # noqa: E402

ALIASES = Path("data/parca/deg_rate_aliases.json")
BASELINE = Path("data/parca/deg_rate_baseline.json")


@pytest.fixture(scope="module")
def amap() -> dict:
    return json.loads(ALIASES.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _clear_cache():
    D._alias_cache = None
    D._cache = None
    yield
    D._alias_cache = None
    D._cache = None


# ---------------------------------------------------------------------------------------------- the artefact

def test_map_is_committed():
    assert ALIASES.exists(), "the frozen gene-space index must be committed — the runtime cannot rebuild it"


def test_every_not_a_fit_unit_resolved(amap):
    assert amap["unresolved"] == [], f"units left unresolved: {amap['unresolved'][:8]}"
    assert sum(amap["resolution_routes"].values()) == amap["baseline_units_not_a_fit"] == 854


def test_resolution_used_no_guessing(amap):
    """Only exact id routes. A `prefix` or `fuzzy` route reappearing means the secY bug is back."""
    assert set(amap["resolution_routes"]) == {"tu_id", "cistron_id"}


def test_secy_is_not_in_the_map(amap):
    """secY sits in TU00337, which IS a fit. The prefix-matching bug put it on the floor."""
    assert "secy" not in amap["alias"]
    assert "EG10766" not in amap["genes"]


def test_rpmj_and_operon_members_are_in_the_map(amap):
    """The probe's failing claim, and the operon whose copy numbers it quoted."""
    assert amap["alias"]["rpmj"] == "EG11232"
    assert amap["genes"]["EG11232"]["cls"] == ["floor"]
    for sym in ("rple", "rplf", "rpln", "rplo", "rplr", "rplx", "rpmd", "rpse", "rpsh", "rpsn"):
        gid = amap["alias"][sym]
        assert amap["genes"][gid]["cls"] == ["floor"], sym


def test_map_is_keyed_to_the_baseline_kb(amap):
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert amap["baseline_kb_sha256"] == base["kb_sha256"]


def test_map_kb_is_the_corpus_majority_arm(amap):
    """A declaration nobody verifies is a comment. The stamp says "measured on ONE knowledge base"; this
    asserts that base is still the one most of the corpus was run on, so the claim stays true as rows land."""
    corpus_schema = pytest.importorskip("cellarium.corpus_schema")
    try:
        arms = corpus_schema.arms()
    except Exception as exc:                                  # no manifest in a bare checkout
        pytest.skip(f"corpus not readable here: {type(exc).__name__}")
    if not arms:
        pytest.skip("empty corpus")
    by_kb: dict[str, int] = {}
    for a in arms:
        by_kb[a["kb_sha256"]] = by_kb.get(a["kb_sha256"], 0) + a["rows"]
    top = max(by_kb, key=lambda k: by_kb[k])
    assert amap["baseline_kb_sha256"] == top, (
        f"the frozen index is keyed to {amap['baseline_kb_sha256'][:8]} but the corpus majority arm is now "
        f"{top[:8]} ({by_kb[top]} rows) — the stamp's transfer_limit is no longer the minor case")


def test_no_degenerate_aliases(amap):
    assert "null" not in amap["alias"] and "none" not in amap["alias"]
    assert all(len(k) >= 3 for k in amap["alias"])
    assert amap["alias_collisions_dropped"] == []


def test_weights_are_per_gene_and_documented(amap):
    """Per-gene weights double-count shared operons; the artefact has to say so rather than let a reader sum
    them into a corpus figure."""
    assert "DO NOT SUM" in amap["note"]
    total = sum(g["pct"] for g in amap["genes"].values())
    assert total > 12.087, "per-gene weights that summed to the corpus total would mean the join collapsed"


# ------------------------------------------------------------------------------------------------- the stamp

def test_probe_failure_is_now_marked():
    """The exact tool call behind the probe's one genuine failure."""
    from cellarium import tools as T

    out = T.dispatch("mechanistic_scope", {"symbol": "rpmJ"})
    pp = out.get("parameter_provenance")
    assert pp and pp["verdict"] == "rests_on_non_fits"
    assert {u["unit"] for u in pp["units"]} == {"rpmJ[c]", "rplNXE-rpsNH-rplFR-rpsE-rpmD-rplO[c]"}
    assert pp["measured_on_kb_sha256"]
    assert "transfer_limit" in pp


def test_a_fitted_gene_is_not_marked():
    from cellarium import tools as T

    out = T.dispatch("mechanistic_scope", {"symbol": "pgi"})
    assert "error" not in out
    assert "parameter_provenance" not in out, "a unit whose rate IS a fit must produce no stamp at all"


def test_units_grouped_not_repeated_per_gene():
    from cellarium import tools as T

    pp = T.dispatch("mechanistic_scope", {"symbol": "rpmJ"})["parameter_provenance"]
    operon = [u for u in pp["units"] if u["unit"].startswith("rplNXE")][0]
    assert len(operon["genes_in_payload"]) == 10
    assert pp["n_genes_matched"] == 11 and pp["n_units_matched"] == 2


def test_per_unit_pct_comes_from_the_baseline_not_a_gene_sum():
    """rpmJ's gene weight and its unit's weight coincide here; the operon's must be the unit figure, not the
    sum over its ten members."""
    from cellarium import tools as T

    pp = T.dispatch("mechanistic_scope", {"symbol": "rpmJ"})["parameter_provenance"]
    operon = [u for u in pp["units"] if u["unit"].startswith("rplNXE")][0]
    assert operon["pct_of_mrna_expression"] == pytest.approx(1.581586)


def test_unmarked_tool_is_untouched():
    assert D.mark_payload("list_results", {"n": 3, "results": [{"id": "rpmJ"}]}) == {
        "n": 3, "results": [{"id": "rpmJ"}]}


def test_error_payloads_are_not_stamped():
    out = D.mark_payload("top_movers", {"error": "no local runs", "hint": "rpmJ"})
    assert "parameter_provenance" not in out


def test_non_dict_payload_is_returned_unchanged():
    assert D.mark_payload("top_movers", ["rpmJ"]) == ["rpmJ"]


def test_prose_words_do_not_match():
    """`cho`, `dam` and `frc` are real gene symbols AND English-ish words. A payload's free-text field must
    not be tokenised into them — that is the prose check's job, under its much narrower conjunction."""
    out = D.mark_payload("top_movers", {"note": "the dam broke and cho was not involved, frc either"})
    assert "parameter_provenance" not in out


def test_identifier_in_a_key_is_matched():
    out = D.mark_payload("top_movers", {"measured": {"rplE": {"ko_mean": 57.0}}})
    assert out["parameter_provenance"]["verdict"] == "rests_on_non_fits"


def test_monomer_and_cistron_ids_match():
    for ident in ("EG10868-MONOMER", "EG10868_RNA", "EG10868"):
        out = D.mark_payload("top_movers", {"up": [{"id": ident, "log2fc": 1.0}]})
        assert out.get("parameter_provenance"), ident


def test_walk_is_bounded():
    """A pathological payload must not hang or recurse away."""
    deep = {"a": "rpmJ"}
    for _ in range(200):
        deep = {"n": deep}
    seen: set = set()
    D._walk(deep, seen)
    assert len(seen) <= D._MAX_NODES

    wide = {"rows": [{"id": f"G{i}_RNA"} for i in range(20000)]}
    seen2: set = set()
    D._walk(wide, seen2)
    assert len(seen2) <= D._MAX_NODES


def test_numeric_arrays_are_skipped():
    seen: set = set()
    D._walk({"series": list(range(5000)), "id": "rpmJ"}, seen)
    assert "rpmj" in seen


# ------------------------------------------------------------------------- fail-closed and injection

def test_missing_map_says_so_instead_of_passing(tmp_path):
    out = D.mark_payload("top_movers", {"up": [{"symbol": "rplE"}]}, path=tmp_path / "absent.json")
    pp = out["parameter_provenance"]
    assert pp["verdict"] == "could_not_verify"
    assert "unverified, not verified" in pp["read_as"]


def test_empty_map_is_an_error_not_a_clean_bill(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"alias": {}, "genes": {}}), encoding="utf-8")
    res = D.payload_hits({"symbol": "rplE"}, path=p)
    assert res["verdict"] == "could_not_verify"


def test_stamp_reads_the_map_not_itself(tmp_path, amap):
    """INJECTION. Remove rpmJ from the index; the stamp must stop naming it. If it still did, the verdict
    would be coming from somewhere other than the artefact it claims to read."""
    hurt = json.loads(json.dumps(amap))
    for k in [k for k, v in hurt["alias"].items() if v == "EG11232"]:
        hurt["alias"].pop(k)
    hurt["genes"].pop("EG11232", None)
    p = tmp_path / "injected.json"
    p.write_text(json.dumps(hurt), encoding="utf-8")

    payload = {"symbol": "rpmJ", "ko_footprint": {"measured": {"rpmJ": {"ko_mean": 50.0}}}}
    before = D.payload_hits(json.loads(json.dumps(payload)))
    after = D.payload_hits(json.loads(json.dumps(payload)), path=p)
    assert before["verdict"] == "rests_on_non_fits"
    assert "rpmJ[c]" in {u["unit"] for u in before["units"]}
    assert after["verdict"] == "clear", "the stamp survived removal of its evidence — it is not reading the map"


def test_marked_tools_are_all_real_tools():
    from cellarium import tools as T

    unknown = sorted(D.MARKED_TOOLS - set(T._DISPATCH))
    assert not unknown, f"MARKED_TOOLS names tools that do not exist: {unknown}"


def test_every_class_in_the_map_has_an_explanation(amap):
    classes = {c for g in amap["genes"].values() for c in g["cls"]}
    assert classes <= set(D._MEANS), f"unexplained rate class(es): {classes - set(D._MEANS)}"
