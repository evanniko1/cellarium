"""The tool faults the option-A discovery leg exposed (2026-10-27), each pinned at the point it misled the agent.

Cellwright was asked, blind, what was wrong with how two models handle amino acids. It concluded that a working
leucine knockout "is not actually a knockout in either configuration". Each test below is one of the reasons:

- the label-integrity check read "could not check" as "cannot be done" and flagged the design INVALID, both when
  its gene map was unreadable from another working directory and when the design's family uses another index;
- the mandatory survey was cut by the context cap after 2 of its 24 channels, tRNA charging among the lost ones;
- `top_movers` returned 0 significant at n=3 against ~3,000 tests, and its description said 0 means no response;
- nothing made the agent read the knocked-out proteins before deciding the knockout had failed;
- `viability` pooled a knockout with its control, and two knowledge-base arms under one name.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cellarium import agent, differential, factors, paths, store, survey, tools, truncation  # noqa: E402

# ---- the gene map is found from any working directory -----------------------------------------------------

def test_the_caches_are_anchored_to_the_checkout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # an isolated store runs from its own directory
    assert paths.CACHE_DIR.is_absolute() and (paths.CACHE_DIR / "gene_scope.json").exists()
    assert factors._CACHE == paths.CACHE_DIR


# ---- "could not check" is not "cannot be done" -------------------------------------------------------------

def test_a_family_outside_the_mapped_index_is_unverified_not_invalid():
    i = factors.identity("gene_knockout_shift/KO:leuA+leuB+leuC+leuD#elong:kinetic")
    assert i["label_integrity"] == "unverified"
    assert "INVALID" not in i["true_label"] and "not checked" in i["true_label"]
    assert i["canonical_id"].startswith("gene_knockout_shift#") and i["canonical_id"].endswith("#elong:kinetic")


def test_an_unreadable_gene_map_makes_every_knockout_unverified(monkeypatch):
    monkeypatch.setattr(factors, "_scope", lambda: {})
    i = factors.identity("gene_knockout/KO:pfkA")
    assert i["label_integrity"] == "unverified" and any("could not be read" in n for n in i["notes"])


def test_a_gene_missing_from_the_map_is_unverified(monkeypatch):
    monkeypatch.setattr(factors, "_scope", lambda: {"pfkA": {"ko_index": 1, "monomer_id": "PFKA"}})
    i = factors.identity("gene_knockout/KO:notagene")
    assert i["label_integrity"] == "unverified"


def test_the_mapped_families_still_get_their_real_verdicts():
    """The fix must not blind the check where it works: valS and rpoB are the corpus's documented mislabels."""
    assert factors.identity("gene_knockout/KO:valS")["label_integrity"] == "misnamed"
    assert factors.identity("gene_knockout/KO:pfkA")["label_integrity"] == "ok"


# ---- truncation names what it drops, even from a nested map -----------------------------------------------

def _big_survey_payload(n_channels=24, rows=20):
    return {"coverage": {"n": 4},
            "by_channel": {f"ch{i}": {"ranked": [{"design": f"d{j}", "mean": j} for j in range(rows)]}
                           for i in range(n_channels)}}


def test_trim_nested_drops_whole_named_entries_and_says_how_to_read_them():
    out, dropped = truncation.trim_nested(_big_survey_payload(), 6000, tool="survey_corpus")
    assert len(json.dumps(out)) <= 6000
    assert dropped["by_channel"] and set(dropped["by_channel"]).isdisjoint(out["by_channel"])
    assert len(dropped["by_channel"]) + len(out["by_channel"]) == 24
    assert "survey_corpus(channels=" in out["_omitted"]["how_to_read"]


def test_the_context_funnel_no_longer_cuts_a_nested_payload_mid_string():
    s = agent._truncate_tool_result(_big_survey_payload(), 6000, "survey_corpus")
    parsed = json.loads(s)                     # valid JSON: no "…[truncated]" tail
    assert "_omitted" in parsed


# ---- the survey digest lists every channel and fits -------------------------------------------------------

def _survey(n_channels=24, n_designs=6):
    designs = [f"gene_knockout/KO:gene{j}#tl:{'x' * 30}" for j in range(n_designs)]
    by_channel = {}
    for i in range(n_channels):
        by_channel[f"channel_{i}"] = {"reference": 1.0, "n_dropped": 3, "ranked": [
            {"design": d, "mean": 0.000123 * (j + 1), "ci95": 1e-5, "n": 3, "generations": 3, "z": 1.5,
             "pct_vs_ref": 12.3, "pct_vs_ref_note": "a long repeated note " * 6,
             **({"label_integrity": "misnamed", "true_label": "TU_KO:x"} if j == 0 else {})}
            for j, d in enumerate(designs)]}
    return {"coverage": {"n_designs_ranked": n_designs, "ranked_designs": designs, "note": "long " * 50},
            "by_channel": by_channel, "notable": [], "quiet_designs": {"designs": []},
            "lethality": {"n_designs_collapsing": 0, "note": "x"}, "note": "y"}


def test_the_digest_keeps_every_channel_and_names_each_design_once():
    d = tools._survey_digest(_survey())
    assert len(d["by_channel"]) == 24
    names = [v["design"] for v in d["designs"].values()]
    assert len(names) == len(set(names)) == 6
    flagged = [v for v in d["designs"].values() if "label_integrity" in v]
    assert len(flagged) == 1 and flagged[0]["label_integrity"] == "misnamed"
    assert d["notes"] == ["a long repeated note " * 6]          # one copy of a note repeated 144 times


def test_the_digest_returns_full_entries_for_the_channels_asked(monkeypatch):
    monkeypatch.setattr(tools.survey, "survey_corpus", lambda **kw: _survey())
    d = tools.survey_corpus(channels=["channel_3", "nope"])
    assert d["full"]["channel_3"]["ranked"][0]["pct_vs_ref_note"]
    assert d["unknown_channels"]["asked"] == ["nope"]


def test_the_survey_fits_its_budget_by_showing_fewer_rows_and_saying_so(monkeypatch):
    monkeypatch.setattr(tools.survey, "survey_corpus", lambda **kw: _survey(n_designs=12))
    d = tools.survey_corpus()
    assert len(json.dumps(d)) <= tools.SURVEY_DIGEST_CHARS < agent._TOOL_CAPS["survey_corpus"]
    assert len(d["by_channel"]) == 24
    shown = len(d["by_channel"]["channel_0"]["rows"])
    assert d["by_channel"]["channel_0"]["n_not_shown"] == 3 + 12 - shown


# ---- an empty top_movers is a power limit, and the knockout is checked -------------------------------------

def test_an_empty_top_movers_says_it_is_a_power_limit_and_checks_the_targets(monkeypatch):
    monkeypatch.setattr(tools._diff, "top_movers", lambda *a, **k: {
        "kind": "protein", "n_compared": 3000, "n_significant_fdr10": 0, "up": [], "down": [],
        "power": {"n_target": 3, "n_reference": 3, "n_tests": 3000, "smallest_q": 0.41,
                  "bh_p_needed_for_first_discovery": 0.10 / 3000}})
    monkeypatch.setattr(tools._diff, "manipulation_check", lambda t, r: {"genes": [{"gene": "leuA", "verdict": "reduced"}]})
    out = tools.top_movers("gene_knockout_shift/KO:leuA", "gene_knockout_shift/basal")
    assert "POWER limit" in out["power_note"] and "not evidence that nothing changed" in out["power_note"]
    assert out["manipulation_check"]["genes"][0]["verdict"] == "reduced"


def test_manipulation_check_verdicts(monkeypatch):
    monkeypatch.setattr(factors, "_scope", lambda: {g: {"monomer_id": g.upper()} for g in ("leuA", "leuB", "leuC")})
    counts = {"T": {"leuA": [300.0, 310.0], "leuB": [650.0, 660.0], "leuC": [950.0, 960.0]},
              "R": {"leuA": [1000.0, 1000.0], "leuB": [1000.0, 1000.0], "leuC": [1000.0, 1000.0]}}
    monkeypatch.setattr(differential, "_last_gen_counts",
                        lambda design, monomers: counts["T" if "KO:" in design else "R"])
    out = differential.manipulation_check("gene_knockout_shift/KO:leuA+leuB+leuC+leuQ", "gene_knockout_shift/basal")
    verdicts = {g["gene"]: g["verdict"] for g in out["genes"]}
    assert verdicts == {"leuA": "reduced", "leuB": "partly_reduced", "leuC": "not_reduced"}
    assert out["unmapped_genes"] == ["leuQ"]
    assert "error" in differential.manipulation_check("gene_knockout_shift/basal")


def test_the_agent_is_told_to_check_the_manipulation_first():
    assert "CHECK THE MANIPULATION FIRST" in agent.SYSTEM and "manipulation_check" in agent.SYSTEM
    assert "manipulation_check" in tools._DISPATCH
    assert any(t["name"] == "manipulation_check" for t in tools.TOOLS)


# ---- viability: one entry per design, and per arm when a design spans two ----------------------------------

def test_viability_separates_designs_and_arms(monkeypatch):
    def row(label, seed, kb="kbA", elong="steady_state"):
        return {"perturbation": "gene_knockout_shift", "condition": "basal", "label": label, "seed": seed,
                "division_rate": 1.0, "gens_reached": 3, "terminal_divided": True, "n_fba_failures": 0,
                "median_division_time_sec": 3000.0, "requested_generations": 3, "crashed": False,
                "kb_sha256": kb, "operons": "on", "elongation_model": elong}
    # Real-format labels, so the real design key separates them (patching design_key does not survive a full run,
    # where the package is imported under two names).
    ko, ctl = "gene_knockout_shift·KO:leuA·s0", "gene_knockout_shift·basal·s0"
    rows = [row(ko, s) for s in range(3)] + [row(ctl, s) for s in range(3)] + [row(ko, s, kb="kbB") for s in range(3)]
    monkeypatch.setattr(store, "has_manifest", lambda: True)
    monkeypatch.setattr(store, "_duck", lambda sql, params: rows)
    out = store.viability("gene_knockout_shift")
    got = sorted(((d["design"], d.get("arm", {}).get("kb_sha256"), d["n_seeds"]) for d in out["designs"]), key=str)
    k_ko, k_ctl = survey.design_key(rows[0]), survey.design_key(rows[3])
    assert k_ko != k_ctl, (k_ko, k_ctl)
    assert got == sorted([(k_ctl, None, 3), (k_ko, "kbA", 3), (k_ko, "kbB", 3)], key=str)
