"""BV-1 to BV-4 and the nitrate re-check: the gate and the model against measurements of the organism.

The stored artefacts were computed from corpus runs, PRECISE-1K and iML1515, which CI has none of. What can be checked
everywhere is checked here: the gate's verdicts are recomputed live from the hand-built requirements and must equal
the stored ones; the counts read by hand are pinned literally; the BV-2 figure regenerates byte for byte from the
stored artefacts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))

import anaerobic_response as AR  # noqa: E402
import bv1_gate_vs_biology as B1  # noqa: E402
import bv2_figure as B2  # noqa: E402
import bv3_essentiality as B3  # noqa: E402

RES = REPO / "evals" / "results"


def _j(name):
    return json.loads((RES / name).read_text(encoding="utf-8"))


# ---- BV-1 -------------------------------------------------------------------------------------------------------

def test_the_gate_still_gives_the_stored_verdicts():
    stored = {r["id"]: r["verdict"] for r in _j("bv1_gate_vs_biology.json")["rows"]}
    for q in B1.QUESTIONS:
        assert B1._verdict(q["requirement"]) == stored[q["id"]], q["id"]


def test_the_bv1_tally_is_the_one_read_by_hand():
    d = _j("bv1_gate_vs_biology.json")
    assert d["tally"] == {"refused, would mislead": 4, "refused, would have agreed": 1, "answered, agrees": 5,
                          "answered, misleads": 2}
    cells = {r["id"]: r["cell"] for r in d["rows"]}
    assert cells["metabolic_gene_essentiality"] == "answered, misleads"
    assert cells["anaerobic_induction_nar_frd"] == "answered, misleads"
    assert cells["arabinose_induction"] == "refused, would mislead"
    assert cells["growth_across_saturating_glucose_doses"] == "refused, would have agreed"


def test_the_cells_follow_from_verdict_and_agreement():
    assert B1.cell("refuse", "misleads") == "refused, would mislead"
    assert B1.cell("refuse", "agrees") == "refused, would have agreed"
    assert B1.cell("answer (calibrated)", "agrees, calibrated: x") == "answered, agrees"
    assert B1.cell("answer", "misleads: y") == "answered, misleads"
    assert B1.cell("answer", None) == "unjudged"


def test_removing_the_arabinose_token_would_let_the_misleading_question_through():
    # forced: the same question without its dependency is answered, and its cell becomes a registry gap
    q = next(q for q in B1.QUESTIONS if q["id"] == "arabinose_induction")
    bare = {**q["requirement"], "regulatory_dependencies": []}
    v = B1._verdict(bare)
    assert v.startswith("answer") and B1.cell(v, q["agreement"]) == "answered, misleads"


# ---- BV-2 -------------------------------------------------------------------------------------------------------

def test_the_bv2_figure_regenerates_from_the_stored_artefacts():
    assert B2.svg(B2.data()) + "\n" == (RES / "bv2_calibrated_vs_predicted.svg").read_text(encoding="utf-8")


def test_the_figure_shows_the_model_nearer_its_input_than_the_organism_for_acetate():
    (_, inp, mod, org), _ = B2.data()["growth"]
    assert (inp, mod, org) == (-67.6, -33.4, -60.4)


# ---- BV-3 -------------------------------------------------------------------------------------------------------

def test_the_confusion_counts_are_computed_as_stated():
    c = B3.confusion([(True, True), (True, False), (False, True), (False, False), (None, True)])
    assert (c["tp"], c["fp"], c["fn"], c["tn"], c["n"]) == (1, 1, 1, 1, 4)


def test_the_stored_essentiality_comparison():
    d = _j("bv3_essentiality.json")["on_iml1515_metabolic_genes"]
    assert d["n_genes"] == 1357
    f, w = d["iml1515_fba"], d["whole_cell_prior"]
    assert (f["tp"], f["fn"], f["fp"], f["tn"], f["mcc"]) == (163, 51, 25, 1118, 0.78)
    assert (w["tp"], w["fn"], w["fp"], w["tn"]) == (1, 213, 1, 1142)


# ---- BV-4 -------------------------------------------------------------------------------------------------------

def test_the_stored_expression_concordance_at_both_floors():
    rows = {(r["design"], r["count_floor"]): r for r in _j("bv4_expression.json")["rows"]}
    assert set(rows) == {("condition/acetate", 20.0), ("condition/acetate", 0.05),
                         ("condition/no_oxygen", 20.0), ("condition/no_oxygen", 0.05)}
    for design in ("condition/acetate", "condition/no_oxygen"):
        wide, narrow = rows[(design, 0.05)], rows[(design, 20.0)]
        assert wide["n_genes"] > 3000 and narrow["n_genes"] < 80
        # wide floor: clearly above the shuffled null; default floor: not
        assert wide["pearson_r"] > wide["null_pearson_r"] + 5 * wide["null_pearson_sd"]
        assert narrow["pearson_r"] < narrow["null_pearson_r"] + 2 * narrow["null_pearson_sd"]
        assert wide["deming_slope"] < 0.2          # the model compresses the organism's changes
    assert (rows[("condition/acetate", 0.05)]["pearson_r"], rows[("condition/no_oxygen", 0.05)]["pearson_r"]) == (
        0.286, 0.205)


# ---- the nitrate re-check -----------------------------------------------------------------------------------------

def test_the_regulation_rerun_holds_the_published_numbers():
    reg = _j("regulation_scope.json")
    nar = next(r for r in reg["gene_level"] if r["regulon"] == "nar_nitrate" and r["reference"] == "wildtype/basal")
    lv = nar["regulon_levels"]
    assert round(lv["narG"]["log2fc"], 2) == 2.04 and round(lv["narH"]["log2fc"], 2) == 1.57
    assert (nar["n_target_runs"], nar["n_reference_runs"]) == (2, 17)
    vs_anaerobic = next(r for r in reg["gene_level"] if r["regulon"] == "nar_nitrate"
                        and r["reference"] == "condition/no_oxygen")
    assert vs_anaerobic["n_significant_in_regulon"] == 0 and vs_anaerobic["n_significant_total"] == 1641
    law = reg["ribosome_growth_law"]
    assert (law["fit_all"]["n"], law["fit_out_of_sample_only"]["n"]) == (14, 9)


def test_the_anaerobic_response_under_induces_against_the_organism():
    a = _j("anaerobic_response.json")
    model, measured = a["no_oxygen_vs_basal_protein"], a["measured_precise1k"]["anaerobic_vs_aerobic_glucose"]
    assert model["frdA"] < measured["frdA"] - 1.0 and model["narG"] < measured["narG"] - 2.0
    assert a["knowledge_base_fold_changes"]["narL"]["narG"] == 2.75


# ---- the anaerobic artefact's generator ---------------------------------------------------------------------------

def test_the_below_floor_figures_recompute_from_the_regulation_artefact():
    # the nar proteins' anaerobic change is not read by the differential (under its floor); it is derived from the
    # regulation artefact's arm means. Recomputed here from that artefact, it must equal what is stored.
    stored = _j("anaerobic_response.json")
    rows = AR.below_floor(_j("regulation_scope.json"))
    assert set(rows) == {"narG", "narH", "narJ", "narI"}
    for g, row in rows.items():
        assert row == {k: stored["below_the_count_floor"][g][k] for k in row}, g
        assert stored["no_oxygen_vs_basal_protein"][g] == row["log2fc_from_means"], g
    assert rows["narG"] == {"no_oxygen_mean": 9.6, "basal_mean": 5.8, "log2fc_from_means": 0.727}


def test_the_knowledge_base_reader_takes_the_fitted_means_and_flags_frdA(tmp_path):
    header = '"TF"\t"Target"\t"log2 FC mean"\t"log2 FC std"\t"Regulation_direct"\n'
    rows = '"narL"\t"narG"\t2.75\t1.56\t1\n"narL"\t"frdA"\t-2.18\t1.07\t1\n"fnr"\t"narG"\t1.54\t0.99\t1\n'
    p = tmp_path / "fold_changes.tsv"
    p.write_text(header + rows, encoding="utf-8")
    kb = AR.kb_fold_changes(p)
    assert kb["narL"] == {"narG": 2.75, "frdA": -2.18} and kb["fnr"] == {"narG": 1.54}
    assert kb["frdA_has_no_fnr_or_arcA_entry"] is True
    # forced: an ArcA entry at frdA must flip the flag
    p.write_text(header + rows + '"arcA"\t"frdA"\t-1.0\t0.5\t1\n', encoding="utf-8")
    assert AR.kb_fold_changes(p)["frdA_has_no_fnr_or_arcA_entry"] is False


def test_the_stored_anaerobic_artefact_names_its_generator_and_an_unmodified_table():
    a = _j("anaerobic_response.json")
    assert "evals/anaerobic_response.py" in a["source"]
    src = a["knowledge_base_fold_changes"]["read_from"]
    assert src["file"] == AR.FOLD_CHANGES and src["modified_in_working_tree"] is False and len(src["commit"]) == 8
