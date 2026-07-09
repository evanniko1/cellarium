"""Guardrail smoke tests — the differentiators, on real fixtures. Run: `python -m pytest` (or this file)."""

from cellarium import biosecurity, differential, envelope, qc, survey
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok:", name)
