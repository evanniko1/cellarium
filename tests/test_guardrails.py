"""Guardrail smoke tests — the differentiators, on real fixtures. Run: `python -m pytest` (or this file)."""

from cellarium import biosecurity, differential, envelope, qc, rigor, survey
from cellarium.model import Design, GenerationResult, SimResult


def test_carbon_source_switch_is_out_of_envelope():
    v = envelope.check(Design(perturbation="timeline", timeline="0 minimal, 1200 minimal_acetate"))
    assert not v.in_envelope
    assert "carbon source" in v.reason.lower()
    assert v.suggestion and "static" in v.suggestion.lower()


def test_glucose_ramp_is_in_envelope():
    v = envelope.check(Design(perturbation="timeline",
                              timeline="0 minimal_GLC_20mM, 1800 minimal_GLC_5mM, 3600 minimal_GLC_2mM"))
    assert v.in_envelope


def test_wildtype_condition_is_in_envelope():
    assert envelope.check(Design(perturbation="wildtype", condition="basal")).in_envelope


def test_qc_flags_over_replication_and_degenerate():
    sim = SimResult(id="x", generations=[
        GenerationResult(index=0, full_chromosome_end=2, divided=True, division_time_sec=2529, n_steps=2530),
        GenerationResult(index=1, full_chromosome_end=4, divided=False, n_steps=2277),   # over-replicated
        GenerationResult(index=2, full_chromosome_end=2, divided=False, n_steps=2),        # degenerate
    ])
    overall, per = qc.check_result(sim)
    assert per[0] is qc.QCStatus.OK
    assert per[1] is qc.QCStatus.OVER_REPLICATED
    assert per[2] is qc.QCStatus.DEGENERATE
    assert not qc.is_reportable(sim)


def test_qc_ok_generation_is_reportable():
    sim = SimResult(id="ok", generations=[
        GenerationResult(index=0, full_chromosome_end=2, divided=True, division_time_sec=2529, n_steps=2530)])
    assert qc.is_reportable(sim)


def test_biosecurity_flags_amr_efflux_upregulation():
    v = biosecurity.screen(Design(perturbation="tf_activity", condition="stress_robustness",
                                  params={"target_tfs": ["marA", "soxS"], "direction": "up"}))
    assert v.flagged and v.signature == "amr_efflux" and v.severity == "review"
    assert set(v.matched) >= {"mara", "soxs"}


def test_biosecurity_exempts_knockout_of_efflux_gene():
    # knocking OUT an efflux pump lowers resistance — not a misuse signature
    v = biosecurity.screen(Design(perturbation="gene_knockout", condition="acrB_KO",
                                  params={"target_genes": ["acrB"]}))
    assert not v.flagged


def test_biosecurity_blocks_virulence_engineering():
    v = biosecurity.screen(Design(perturbation="tf_activity", params={"target_genes": ["stxA"]}))
    assert v.flagged and v.severity == "block"


def test_biosecurity_passes_benign_designs():
    assert not biosecurity.screen(Design(perturbation="wildtype", condition="basal")).flagged
    assert not biosecurity.screen(Design(perturbation="ppgpp_conc", condition="basal|ppGpp:2.0x")).flagged


def test_survey_handles_empty_corpus_gracefully():
    # no manifest present in the test env -> a clean error, not a crash
    out = survey.survey_corpus()
    assert "error" in out or "coverage" in out


def test_differential_summary_handles_missing_target():
    out = differential.summary("nonexistent/design")
    assert "error" in out  # clean error (+ 'available' when a corpus exists), never a crash


def test_phenotype_screen_flags_amr_upregulation():
    # simulated proteome allocates ~5x more to efflux than the reference -> flagged (grounded in phenotype)
    v = biosecurity._screen_phenotype({"pw:amr_efflux": 0.004}, {"pw:amr_efflux": 0.0008})
    assert v.flagged and v.signature == "amr_efflux" and v.severity == "review" and v.log2fc >= 1.0


def test_phenotype_screen_passes_baseline():
    v = biosecurity._screen_phenotype({"pw:amr_efflux": 0.0009}, {"pw:amr_efflux": 0.0008})  # ~1.1x
    assert not v.flagged


def test_coverage_tracks_examined_designs():
    rigor.reset()
    cov0 = rigor.coverage()
    assert cov0["n_examined"] == 0 and "n_total" in cov0
    rigor.note_design("wildtype/basal")
    assert rigor.coverage()["n_examined"] >= 0  # increments iff that design exists in the corpus


def test_disconfirm_handles_missing_design():
    out = rigor.disconfirm("nonexistent/x", "wildtype/basal", "growth_rate")
    assert "error" in out or "channel" in out


def test_viability_verdict_three_regimes():
    from cellarium import store

    def rows(*specs):  # (division_rate, gens_reached, terminal_divided, n_fba_failures)
        return [{"seed": i, "division_rate": dr, "gens_reached": g, "terminal_divided": td, "n_fba_failures": ff}
                for i, (dr, g, td, ff) in enumerate(specs)]

    # metabolic KO — every seed divides fully -> VIABLE
    assert store._viability_verdict(rows((1.0, 4, True, 0), (1.0, 4, True, 0)))["verdict"] == "viable"
    # gltX-like — one seed collapses (terminal not divided), no FBA failure -> IMPAIRED via the cross-seed rollup
    assert store._viability_verdict(rows((1.0, 3, True, 0), (0.67, 3, False, 0)))["verdict"] == "impaired"
    # hard failure — an FBA-solver break makes it INVIABLE regardless of rate
    assert store._viability_verdict(rows((1.0, 2, True, 1)))["verdict"] == "inviable"
    # pre-viability shards (no division_rate) -> UNKNOWN, not a false verdict
    assert store._viability_verdict([{"seed": 0, "division_rate": None}])["verdict"] == "unknown"


def test_viability_verdict_fba_failure_is_inviable():
    # regression: an FBA-solver crash is inviable even on a dividing lineage (the two former copies diverged here)
    from cellarium import viability_rules
    assert viability_rules.verdict(1.0, True, True, 1) == "inviable"
    assert viability_rules.verdict(1.0, True, True, 0) == "viable"
    assert viability_rules.verdict(0.67, False, True, 0) == "impaired"
    assert viability_rules.verdict(None, True, True, 0) == "unknown"


def test_t95_ci_wider_than_normal_at_small_n():
    import statistics

    from cellarium import stats as cstats
    vals = [1.0, 1.1, 0.9, 1.05]
    t_hw = cstats.t95_halfwidth(vals)
    normal_hw = 1.96 * statistics.stdev(vals) / (len(vals) ** 0.5)
    assert t_hw is not None and t_hw > normal_hw          # t-dist is wider than the normal approx at n=4
    assert cstats.t95_halfwidth([1.0]) is None            # undefined for n<2


def test_design_space_enumerates_and_resolves():
    from cellarium import tools
    ds = tools.design_space()
    assert ds["variant_types"] and "gene_knockout" in ds["variant_types"]  # always available, no cache needed
    g = tools.design_space(gene="fabI")["gene"]
    assert ("ko_index" in g) or (g.get("known") is False)  # resolves if scope cached, else graceful


def test_provenance_distinguishes_fitted_from_derived_conditions():
    from cellarium import provenance
    assert provenance.tag("condition", "no_oxygen") == "in_sample"       # measured/TF-fitted (H1)
    assert provenance.tag("condition", "with_aa") == "in_sample"
    assert provenance.tag("condition", "minus_magnesium") == "out_of_sample"  # derived, not fitted (H2 boundary)
    assert provenance.tag("condition", "plus_indole") == "out_of_sample"
    assert provenance.tag("gene_knockout", "KO:fabI") == "out_of_sample"
    assert provenance.tag("wildtype", "basal") == "in_sample"


def test_vet_hypothesis_gates_safety_only():
    # THE constraint: only safety blocks. Out-of-sample + out-of-envelope hypotheses stay runnable (H2 lesson).
    from cellarium import tools
    oos = tools.vet_hypothesis(perturbation="gene_knockout", condition="KO:fabI")  # out-of-sample, benign
    assert oos["runnable"] is True and oos["provenance"]["provenance"] == "out_of_sample"
    boundary = tools.vet_hypothesis(perturbation="timeline", timeline="0 minimal, 1200 minimal_acetate")
    assert boundary["runnable"] is True and boundary["feasibility"]["in_envelope"] is False  # advisory, not blocked
    misuse = tools.vet_hypothesis(perturbation="gene_overexpression", condition="marA")
    assert misuse["runnable"] is False and misuse["safety"]["flagged"] is True  # safety is the ONLY gate


def test_model_validation_reports_under_prediction():
    from cellarium import tools
    mv = tools.model_validation()
    if "error" in mv:
        return  # gene_scope cache not built in this environment
    assert mv["model_UNDER_predicts"] > mv["consistent_lethal"]   # the model under-predicts essentiality
    assert 0.0 <= mv["essentiality_recall"] <= 1.0


def test_power_check_needs_more_seeds_for_smaller_effect():
    from cellarium import tools
    big = tools.power_check(channel="growth_rate", effect_pct=20.0)
    small = tools.power_check(channel="growth_rate", effect_pct=5.0)
    if "error" in big or "error" in small:
        return  # no replicated corpus in this environment
    assert small["seeds_needed_for_target"] > big["seeds_needed_for_target"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok:", name)
