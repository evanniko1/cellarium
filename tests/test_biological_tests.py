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
import bv6_overflow  # noqa: E402,F401
import bv8_half_lives  # noqa: E402,F401

RES = REPO / "evals" / "results"


def _j(name):
    return json.loads((RES / name).read_text(encoding="utf-8"))


# ---- BV-1 -------------------------------------------------------------------------------------------------------

def test_the_gate_still_gives_the_stored_verdicts():
    stored = {r["id"]: r["verdict"] for r in _j("bv1_gate_vs_biology.json")["rows"]}
    for q in B1.QUESTIONS:
        assert B1._verdict(q["requirement"]) == stored[q["id"]], q["id"]


def test_the_bv1_tally_is_the_one_read_by_hand():
    # 2026-11-25: the two answered-and-misleading rows of the first run (4/1/5/2) became registry records
    # (BV-G2 essentiality, BV-AN anaerobic magnitude), and the gate now refuses both. Later the same day BV-6 found
    # overflow absent; its question joined with the record that refuses it (BV-OF): 13 questions, 7/1/5/0.
    d = _j("bv1_gate_vs_biology.json")
    assert d["tally"] == {"refused, would mislead": 7, "refused, would have agreed": 1, "answered, agrees": 5}
    cells = {r["id"]: r["cell"] for r in d["rows"]}
    assert cells["metabolic_gene_essentiality"] == "refused, would mislead"
    assert cells["anaerobic_induction_nar_frd"] == "refused, would mislead"
    assert cells["acetate_overflow_on_glucose"] == "refused, would mislead"
    assert cells["arabinose_induction"] == "refused, would mislead"
    assert cells["growth_across_saturating_glucose_doses"] == "refused, would have agreed"


def test_the_cells_follow_from_verdict_and_agreement():
    assert B1.cell("refuse", "misleads") == "refused, would mislead"
    assert B1.cell("refuse", "agrees") == "refused, would have agreed"
    assert B1.cell("answer (calibrated)", "agrees, calibrated: x") == "answered, agrees"
    assert B1.cell("answer", "misleads: y") == "answered, misleads"
    assert B1.cell("answer", None) == "unjudged"


def test_without_the_new_records_the_misleading_questions_would_be_answered():
    # forced: the same requirements without the BV-G2 and BV-AN tokens are the first run's two registry gaps
    for qid in ("metabolic_gene_essentiality", "anaerobic_induction_nar_frd", "acetate_overflow_on_glucose"):
        q = next(q for q in B1.QUESTIONS if q["id"] == qid)
        bare = {**q["requirement"], "regulatory_dependencies": []}
        assert B1._verdict(bare).startswith("answer"), qid


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
    # Y10 (2026-11-25): the seven condition designs are fitted for growth and composition, so the out-of-sample
    # fit is the seven perturbations, the README's figure; before the quantity-aware tag it counted nine
    assert (law["fit_all"]["n"], law["fit_out_of_sample_only"]["n"]) == (14, 7)
    assert (law["fit_out_of_sample_only"]["r_squared"], law["fit_out_of_sample_only"]["slope_p_value"]) == (0.623, 0.0348)
    assert law["before_y10"]["fit_out_of_sample_only"]["n"] == 9


def test_after_the_reader_correction_narX_is_no_longer_the_nitrate_runs_top_mover():
    # BV-R1 (2026-11-25): re-run through the corrected reader, NarX in nitrate reads -0.20 against basal (was -5.07,
    # q 0.0003, the top mover); only narG and narH stay significant, and two proteins leave the significant set
    reg = _j("regulation_scope.json")
    nar = next(r for r in reg["gene_level"] if r["regulon"] == "nar_nitrate" and r["reference"] == "wildtype/basal")
    assert nar["regulon_levels"]["narX"] == {"target": 52.6, "reference": 60.5, "log2fc": -0.1997}
    assert (nar["n_significant_in_regulon"], nar["n_significant_total"]) == (2, 317)
    assert [m["gene"] for m in nar["movers"]] == ["narg", "narh"]
    vs_an = next(r for r in reg["gene_level"] if r["regulon"] == "nar_nitrate" and r["reference"] == "condition/no_oxygen")
    assert vs_an["regulon_levels"]["narX"]["log2fc"] == 1.5462
    assert "BV-R1" in reg["reader_correction"] and "-5.07" in reg["reader_correction"]


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


# ---- BV-R1: the two-component reader correction, measured -----------------------------------------------------------

def test_the_two_component_correction_moves_only_the_sensors_it_should():
    rows = {r["protein"]: r for r in _j("bv_r1_two_component.json")["rows"]}
    # the two artefacts: a sensor that vanished in exactly its activating condition
    assert (rows["NarX"]["log2fc_before"], rows["NarX"]["log2fc_after"]) == (-5.07, -0.2)
    assert (rows["DcuS"]["log2fc_before"], rows["DcuS"]["log2fc_after"]) == (-4.04, 0.96)
    # a sensor whose phosphorylated complex is absent is untouched; a partly phosphorylated one moves a little
    assert rows["ArcB"]["log2fc_before"] == rows["ArcB"]["log2fc_after"] == 2.9
    assert (rows["PhoQ"]["log2fc_before"], rows["PhoQ"]["log2fc_after"]) == (0.3, 0.28)
    # the organism: NarX unchanged by nitrate (PRECISE-1K, anaerobic), as the corrected model reads it
    assert rows["NarX"]["organism"]["log2fc"] == -0.11 and rows["NarX"]["organism"]["padj"] > 0.5
    assert rows["PhoR"]["n_target_runs"] == 0 and "no QC-clean run" in rows["PhoR"]["why_missing"]


# ---- Y12: what a new user's clone of the public campaign branch gets --------------------------------------------------

def test_a_new_users_clone_resolves_everything_but_the_held_port():
    d = _j("dependency_audit_public.json")
    assert d["public_commit"].startswith("8e7dd6c") and (d["resolve_publicly"], d["n_references"]) == (26, 33)
    assert set(d["records_resting_on_unpublished_code"]) == {"per_isoacceptor_trna_charging",
                                                             "codon_level_elongation",
                                                             "per_amino_acid_trna_charging"}
    from cellarium import capability as C
    assert set(C.BUILD["records_not_reproducible_from_public_code"]) == set(d["records_resting_on_unpublished_code"])


# ---- BV-8: mRNA half-lives against Bernstein et al. 2002 -----------------------------------------------------------

def test_the_stored_half_life_comparison():
    d = _j("bv8_half_lives.json")
    assert d["organism_bernstein_2002"]["m9"]["n"] == 3826 and d["organism_bernstein_2002"]["m9"]["share_3_to_8_min"] == 0.767
    assert d["model_final_half_lives"]["n"] == 3133 and d["model_final_half_lives"]["share_3_to_8_min"] == 0.619
    cls = d["model_by_class"]
    assert (cls["fit"]["n"], cls["floor"]["n"], cls["ceiling"]["n"], cls["imputed"]["n"]) == (2279, 245, 7, 602)
    assert cls["floor"]["median_min"] == 91.2 and cls["imputed"]["median_min"] == 5.19
    pg = d["per_gene_monocistronic_fit_units"]
    # ParCa keeps its inputs; the two input sources disagree for the genes where the model took Chen's value
    assert pg["input_from_bernstein"]["spearman_model_vs_bernstein_m9"] == 0.946
    assert pg["input_from_chen"]["spearman_model_vs_bernstein_m9"] == 0.094
    assert pg["input_from_chen"]["median_log2_model_over_bernstein"] == -0.943


def test_the_half_life_analysis_on_a_small_case():
    import bv8_half_lives as B8
    units = {"units": [{"half_life_min": 5.0, "class": "fit", "pct_of_mrna_expression": 50.0, "cistrons": ["aaaA"]},
                       {"half_life_min": 2.0, "class": "fit", "pct_of_mrna_expression": 10.0, "cistrons": ["bbbB"]},
                       {"half_life_min": 91.2, "class": "floor", "pct_of_mrna_expression": 40.0, "cistrons": ["cccC"]}],
             "cistrons": [{"symbol": "aaaA", "input_half_life_min": 5.0, "measured": True},
                          {"symbol": "bbbB", "input_half_life_min": 2.0, "measured": True},
                          {"symbol": "cccC", "input_half_life_min": 5.19, "measured": False}]}
    bern = {"aaaA": {"m9": 5.0}, "bbbB": {"m9": 4.0}, "cccC": {"m9": 6.0}}
    r = B8.analyse(units, bern)
    assert r["model_final_half_lives"]["share_3_to_8_min"] == 0.333
    assert r["model_final_half_lives"]["share_3_to_8_min_expression_weighted"] == 0.5
    assert r["per_gene_monocistronic_fit_units"]["input_from_bernstein"]["n"] == 1      # aaaA: input equals Bernstein
    assert r["per_gene_monocistronic_fit_units"]["input_from_chen"]["n"] == 1           # bbbB: input differs
    assert r["per_gene_monocistronic_fit_units"]["input_from_chen"]["median_log2_model_over_bernstein"] == -1.0


# ---- BV-6: overflow metabolism -------------------------------------------------------------------------------------

def test_the_stored_overflow_reading():
    d = _j("bv6_overflow.json")
    fit = d["fixed_medium_fit_acetate_vs_growth"]
    assert fit["n"] == 37 and fit["constant_response"] == 0.0 and fit["p"] is None     # no variation, no p-value
    assert d["designs"]["wildtype/basal"]["ACET[p]"]["mean"] == 0.0
    assert d["designs"]["condition/acetate"]["direction"] == "taken up"                # the read is not just zeros
    an = d["designs"]["condition/no_oxygen"]
    assert an["ETOH[p]"]["mean"] == 0.0 and an["ACET[p]"]["mean"] < 0.001


def test_a_constant_response_has_no_p_value():
    import bv6_overflow as B6
    assert B6._ols([0.5, 0.7, 0.9], [0.0, 0.0, 0.0])["p"] is None
    f = B6._ols([0.5, 0.7, 0.9], [0.0, 1.0, 2.1])                                       # forced: a real slope
    assert f["slope"] > 4 and f["p"] is not None and f["p"] < 0.05
