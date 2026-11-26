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
import bv11_fluxes  # noqa: E402,F401
import bv12_feba  # noqa: E402,F401

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
    # overflow absent; its question joined with the record that refuses it (BV-OF): 13 questions, 7/1/5/0. BV-7 then
    # found the elongation rate rising as growth slows (BV-EL): 14 questions, 8/1/5/0.
    d = _j("bv1_gate_vs_biology.json")
    assert d["tally"] == {"refused, would mislead": 8, "refused, would have agreed": 1, "answered, agrees": 5}
    # the test proper is the original twelve; the two questions added after BV-6 and BV-7 are a wiring check
    assert d["tally_original_twelve"] == {"refused, would mislead": 6, "refused, would have agreed": 1,
                                          "answered, agrees": 5}
    assert d["first_run_original_twelve"]["answered, misleads"] == 2
    assert {r["id"] for r in d["rows"] if r.get("added_after")} == {"acetate_overflow_on_glucose",
                                                                    "elongation_rate_falls_with_growth"}
    cells = {r["id"]: r["cell"] for r in d["rows"]}
    assert cells["metabolic_gene_essentiality"] == "refused, would mislead"
    assert cells["anaerobic_induction_nar_frd"] == "refused, would mislead"
    assert cells["acetate_overflow_on_glucose"] == "refused, would mislead"
    assert cells["elongation_rate_falls_with_growth"] == "refused, would mislead"
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
    for qid in ("metabolic_gene_essentiality", "anaerobic_induction_nar_frd", "acetate_overflow_on_glucose",
                "elongation_rate_falls_with_growth"):
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
    kb = a["knowledge_base_fold_changes"]
    assert kb["narL"]["narG"] == 1.75 and kb["fold_changes_tsv_alone"]["narL"]["narG"] == 2.75   # the fit uses NCA's
    assert kb["fnr"]["frdA"] == 1.12 and ["fnr", "frdA"] in kb["supplied_by_nca"]


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


def test_the_knowledge_base_reader_takes_the_fits_merge_of_both_tables(tmp_path):
    # ParCa reads fold_changes.tsv, then fold_changes_nca.tsv, whose value replaces the first's for a pair both list;
    # until 2026-11-26 this reader took fold_changes.tsv alone (narL->narG 2.75 where the fit uses 1.75)
    header = '"TF"\t"Target"\t"log2 FC mean"\t"log2 FC std"\t"Regulation_direct"\n'
    rows = '"narL"\t"narG"\t2.75\t1.56\t1\n"narL"\t"frdA"\t-2.18\t1.07\t1\n"fnr"\t"narG"\t1.54\t0.99\t1\n'
    (tmp_path / "fold_changes.tsv").write_text(header + rows, encoding="utf-8")
    nca = "# generated by NCA\n" + header + '"narL"\t"narG"\t1.75\n"fnr"\t"frdA"\t1.12\n'
    (tmp_path / "fold_changes_nca.tsv").write_text(nca, encoding="utf-8")
    kb = AR.kb_fold_changes(tmp_path)
    assert kb["narL"] == {"narG": 1.75, "frdA": -2.18} and kb["fnr"] == {"narG": 1.54, "frdA": 1.12}
    assert kb["fold_changes_tsv_alone"]["narL"]["narG"] == 2.75 and "frdA" not in kb["fold_changes_tsv_alone"]["fnr"]
    assert kb["replaced_by_nca"] == [["narL", "narG"]] and kb["supplied_by_nca"] == [["fnr", "frdA"]]
    # forced: a row the curation disagrees with (Regulation_direct above 2) is not used, as ParCa skips it
    (tmp_path / "fold_changes.tsv").write_text(header + rows + '"arcA"\t"frdA"\t-1.0\t0.5\t3\n', encoding="utf-8")
    assert AR.kb_fold_changes(tmp_path)["arcA"] == {}


def test_the_stored_anaerobic_artefact_names_its_generator_and_an_unmodified_table():
    a = _j("anaerobic_response.json")
    assert "evals/anaerobic_response.py" in a["source"]
    src = a["knowledge_base_fold_changes"]["read_from"]
    assert src["files"] == [f"{AR.FLAT}/fold_changes.tsv", f"{AR.FLAT}/fold_changes_nca.tsv"]
    assert src["modified_in_working_tree"] is False and len(src["commit"]) == 8


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
    # unique references (27 of 33 since BV-OF and BV-EL; 29 of 35 since the two fold_changes_nca.tsv references,
    # 2026-11-26; 32 of 38 since CRIT's three, read through the GitHub API, which reproduced the clone's 29 of 35 first);
    # the first version divided a unique count by the total
    assert d["public_commit"].startswith("8e7dd6c") and (d["resolve_publicly"], d["n_unique"]) == (32, 38)
    assert len(d["missing_publicly"]) == d["n_unique"] - d["resolve_publicly"] == 6
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


# ---- BV-11: the Toya parser (the data ship with the model checkout, which CI does not have) ------------------------

def test_the_toya_table_parses_with_its_units_and_standard_deviations(tmp_path):
    import bv11_fluxes as B11
    f = tmp_path / "toya.tsv"
    f.write_text('"reactionID"\t"flux (units.mmol / units.g / units.h)"\t'
                 '"flux standard deviation (units.mmol / units.g / units.h)"\n'
                 '"TRANS-RXN-157"\t10.17\t2.16\n"PGLUCISOM-RXN"\t6.04\t0.84\n', encoding="utf-8")
    assert B11.toya(f) == {"TRANS-RXN-157": (10.17, 2.16), "PGLUCISOM-RXN": (6.04, 0.84)}


# ---- BV-7, BV-9, BV-10, BV-11: stored readings ----------------------------------------------------------------------

def test_the_elongation_rate_rises_as_growth_slows_across_media():
    d = _j("bv7_elongation.json")
    f = d["fits"]
    assert f["by_medium"]["slope"] < -4 and f["by_medium"]["p"] < 1e-3          # the wrong direction (BV-EL)
    assert f["fixed_medium"]["p"] > 0.5                                           # and no growth dependence at all
    rate = {k: v["elongation_aa_per_s"] for k, v in d["designs"].items()}
    assert rate["condition/acetate"] > rate["wildtype/basal"] and rate["condition/no_oxygen"] > rate["wildtype/basal"]


def test_the_initiation_threshold_is_built_in_and_lowered_by_rule_in_slow_media():
    d = _j("bv10_initiation.json")
    a = d["across_designs"]
    assert a["designs_at_975_fg"] == 8
    assert set(a["designs_with_a_lowered_threshold"]) == {"condition/acetate", "condition/no_oxygen",
                                                          "condition/succinate"}
    assert d["designs"]["wildtype/basal"]["mass_per_origin_fg_median"] == 975.1


def test_the_noise_floor_is_half_the_organisms():
    d = _j("bv9_noise.json")
    org = d["taniguchi_per_gene"]["organism_scaling"]
    assert d["floor_median_cv2_above_1000"] < 0.6 * org["floor_median_cv2_above_1000"]
    assert d["taniguchi_per_gene"]["n_joined"] == 708 and d["taniguchi_per_gene"]["spearman_cv2"] == 0.456


def test_the_flux_control_correlates_while_the_tca_cycle_is_off():
    d = _j("bv11_fluxes.json")
    assert (d["n_reactions_compared"], d["pearson_r"]) == (23, 0.737)
    rx = {r["reaction"]: r for r in d["reactions"]}
    assert rx["2OXOGLUTARATEDEH-RXN"]["model"] == 0.0 and rx["2OXOGLUTARATEDEH-RXN"]["toya"] == 4.62
    assert rx["FUMHYDR-RXN"]["model"] * rx["FUMHYDR-RXN"]["toya"] < 0              # runs in reverse
    assert rx["MALATE-DEH-RXN"]["model"] * rx["MALATE-DEH-RXN"]["toya"] < 0


def test_protein_changes_agree_with_the_proteome_only_where_the_fit_set_them():
    d = _j("bv5_proteome.json")
    assert d["table"]["sha256"].startswith("c7c7f918") and d["table"]["bytes"] == 16460041
    rows = {(r["design"], r["count_floor"]): r for r in d["rows"]}
    a = rows[("condition/acetate", 20.0)]
    # 2026-11-26 (D15): one basal reference per fit; the 18th run had been BV-14's refit control (0.271 -> 0.263)
    assert a["n_reference_runs"] == 17
    assert a["absolute_spearman"]["glucose"] == {"n": 2121, "rho": 0.727}
    fc = a["fold_change_concordance"]
    assert (fc["fitted"]["n_genes"], fc["fitted"]["pearson_r"]) == (128, 0.263)
    assert (fc["not_fitted"]["n_genes"], fc["not_fitted"]["spearman_rho"]) == (1992, 0.006)
    s = rows[("condition/succinate", 20.0)]["fold_change_concordance"]
    assert s["fitted"]["pearson_r"] > 5 * s["not_fitted"]["pearson_r"]


# ---- BV-12: the scoring rule ---------------------------------------------------------------------------------------

def test_the_bv12_score_keeps_a_collapsed_knockout_and_reads_generation_two():
    import bv12_feba as B12
    gens = json.dumps([{"growth": 2.4e-4}, {"growth": 2.5e-4}, {"growth": 0.35e-4}, {"growth": 0.30e-4}])
    # translation collapse is the fitness phenotype (lysA, serA, proC): kept, and read at generation 2, not the last
    assert B12.select_row("runs/cellarium/gene_knockout_002720/000000", "3b2f8ebd" + "0" * 56,
                          "translation_collapse", gens) == (0.35e-4, "translation_collapse")
    # forced: an integrity failure, another fit, or a run too short to have generation 2 is not scored
    assert B12.select_row("p", "3b2f8ebd" + "0" * 56, "crashed", gens) is None
    assert B12.select_row("p", "9055ee3b" + "0" * 56, "ok", gens) is None
    assert B12.select_row("p", "3b2f8ebd" + "0" * 56, "ok", json.dumps([{"growth": 1.0}, {"growth": 1.0}])) is None


# ---- BV-14: the join to the organism -------------------------------------------------------------------------------

def test_the_bv14_scorer_names_proteins_before_joining_and_refuses_an_empty_join():
    import bv14_nitrate as B14
    import pytest

    from cellarium import differential
    raw = {"kind": "protein", "lfc": {"NARG-MONOMER[m]": {"log2fc": 2.0, "target": 50.0, "reference": 12.0},
                                      "FUM-FLAVO[c]": {"log2fc": -1.5, "target": 10.0, "reference": 30.0}}}
    named_out = differential.annotate_lfc(raw, "protein",
                                          annot={"NARG-MONOMER[m]": "narG", "FUM-FLAVO[c]": "frdA"})
    assert "symbol" not in raw["lfc"]["NARG-MONOMER[m]"]          # the reader's output is not modified in place
    sim, named = B14._join(named_out["lfc"], {"narG": "b1224", "frdA": "b4154"}, {"b1224": 3.5, "b4154": -4.48})
    assert sim == {"b1224": 2.0, "b4154": -1.5}
    assert (named["narG"]["model"], named["narG"]["organism"]) == (2.0, 3.5)
    assert (named["frdA"]["model"], named["frdA"]["organism"]) == (-1.5, -4.48)
    # forced: the reader's own monomer ids, unannotated (the first scoring, 2026-11-26), join no gene and are refused
    with pytest.raises(ValueError, match="joined no gene"):
        B14._join(raw["lfc"], {"narG": "b1224", "frdA": "b4154"}, {"b1224": 3.5, "b4154": -4.48})


def test_the_bv14_diagnostic_compares_arms_per_seed_and_reports_the_spread():
    import bv14_nitrate as B14
    # narGHJI synthesis probability, last generation, nitrate seeds 0-3 against anaerobic seeds 0-3 (2026-11-26)
    c = B14._compare_arms([4.48e-6, 4.17e-6, 4.07e-6, 4.59e-6], [2.97e-6, 3.87e-6, 3.59e-6, 4.08e-6])
    assert (c["log2_ratio"], c["welch_t"]) == (0.255, 2.584)
    assert c["n"] == [4, 4] and c["target"][0] == 4.48e-6
    # forced: one seed per arm has no spread to test, so no t is reported rather than a number
    one = B14._compare_arms([1.0], [2.0])
    assert one["welch_t"] is None and one["p"] is None


def test_bv14_the_stored_result():
    d = _j("bv14_nitrate.json")
    c = d["contrasts"]
    # pre-registered: protein, last generation, 4 nitrate against 4 anaerobic seeds on the refit; every run read
    n = c["nitrate_under_anaerobiosis"]["floor_20.0"]
    assert n["n_runs_read"] == [4, 4] and (n["n_genes"], n["pearson_r"]) == (2698, -0.019)
    assert (n["named_genes"]["narG"]["model"], n["named_genes"]["narG"]["organism"]) == (-0.687, 3.332)
    assert (n["named_genes"]["frdA"]["model"], n["named_genes"]["frdA"]["organism"]) == (1.015, -4.475)
    # the combination: frd raised by nitrate-anaerobic growth where the organism lowers it
    m = c["nitrate_anaerobic_vs_aerobic"]["floor_20.0"]["named_genes"]["frdA"]
    assert (m["model"], m["organism"]) == (2.776, -1.621)
    # post hoc, beside it: the protein readout is unresolved, the synthesis readout right-signed and weak
    dg = d["diagnostic_post_hoc"]
    assert "does not replace" in dg["added"] and dg["n_seeds"] == {"basal": 2, "no_oxygen": 4, "no_oxygen_plus_nitrate": 4}
    under = dg["contrasts"]["nitrate_under_anaerobiosis"]
    assert under["protein_per_seed"]["narG"]["p"] > 0.3 and under["protein_per_seed"]["frdA"]["p"] > 0.1
    s = under["actual_synth_prob"]
    assert (s["narGHJI"]["log2_ratio"], s["frdABCD"]["log2_ratio"]) == (0.254, -0.465)
    assert under["fitted_log2_synth_ratio"]["narGHJI"] == 1.294 and under["fitted_log2_synth_ratio"]["frdABCD"] == -1.074
    assert dg["contrasts"]["nitrate_anaerobic_vs_aerobic"]["actual_synth_prob"]["frdABCD"]["log2_ratio"] == 2.15
    # the simulation's occupancies are not the ones the fit assumed
    occ = dg["promoter_occupancy"]["no_oxygen"]
    assert (occ["simulated"]["FNR-4FE-4S-CPLX"], occ["fit_assumed"]["FNR-4FE-4S-CPLX"]) == (0.99, 0.781)


def test_bv_an_the_corpus_fits_transcription_rises_about_fourfold_where_the_organisms_rises_sixteen():
    # added 2026-11-26 after BV-14: the corpus fit's depth-1 runs, 8 anaerobic against 12 basal, per seed
    s = _j("anaerobic_response.json")["synthesis_depth_1"]["contrasts"]["no_oxygen_vs_basal"]
    assert s["model"].endswith("8 against 12 runs") and s["arm"] == "default (largest)"
    syn = s["actual_synth_prob"]
    assert (syn["narGHJI"]["log2_ratio"], syn["frdABCD"]["log2_ratio"]) == (1.836, 1.945)
    assert syn["narGHJI"]["p"] < 0.001 and syn["frdABCD"]["p"] < 0.001
    assert (s["fitted_log2_synth_ratio"]["narGHJI"], s["fitted_log2_synth_ratio"]["frdABCD"]) == (1.458, 1.856)
    # the protein readout lags it: narG not resolved within one generation
    assert s["protein_per_seed"]["narG"]["p"] > 0.1
    occ = s["promoter_occupancy"]["target"]
    assert (occ["simulated"]["FNR-4FE-4S-CPLX"], occ["fit_assumed"]["FNR-4FE-4S-CPLX"]) == (0.99, 0.781)
    # forced: still far short of the organism, so the magnitude stays refused
    measured = _j("anaerobic_response.json")["measured_precise1k"]["anaerobic_vs_aerobic_glucose"]
    assert measured["narG"] - syn["narGHJI"]["log2_ratio"] > 2.0
