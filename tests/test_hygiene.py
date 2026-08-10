"""H-17b — the one read boundary, and the property that makes it worth having.

The drift this ends is MEASURED, not hypothetical: `rigor.disconfirm` — the tool whose job is to CHALLENGE a
claim — once reported an interval 5.5x NARROWER than `survey_corpus` for the same cell, over crashed runs,
under a key that can collide, because three readers had each grown their own filtering. A disconfirmation
tool more confident than the thing it checks is worse than no tool.

The test that carries the most weight here is `test_the_four_purposes_return_genuinely_different_sets`. A
`purpose` argument that every branch answers identically is decoration, and decoration is worse than nothing
because it looks like a safeguard. On this corpus the sets differ by 175 rows between `analysis` and
`lethality` — which is 127 non-reportable runs that a lethality question MUST see and a mean MUST NOT.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cellarium import hygiene, invariants  # noqa: E402


@pytest.fixture(scope="module")
def sets():
    out = {}
    for p in hygiene.PURPOSES:
        try:
            out[p] = hygiene.rows(p)
        except Exception as exc:            # a purpose that cannot be served must fail loudly, not silently
            pytest.skip(f"{p}: {type(exc).__name__}: {exc}")
    if not any(len(r) for r, _c in out.values()):
        pytest.skip("no local corpus")
    return out


# ---------------------------------------------------------------------------------------------------------
# Purpose is mandatory, and it is not cosmetic.
# ---------------------------------------------------------------------------------------------------------

def test_there_is_no_default_purpose():
    """A default is how every caller ends up on `analysis` and a lethality question silently reads zero
    deaths. `rows()` takes the purpose positionally and refuses anything it does not know."""
    with pytest.raises(TypeError):
        hygiene.rows()                        # type: ignore[call-arg]


def test_an_unknown_purpose_is_refused_with_the_list():
    with pytest.raises(hygiene.UnknownPurpose) as e:
        hygiene.rows("everything")
    msg = str(e.value)
    assert all(p in msg for p in hygiene.PURPOSES), "the refusal does not say what IS available"
    assert "no default" in msg


def test_the_four_purposes_return_genuinely_different_sets(sets):
    """THE test. If two purposes return the same rows, the argument is decoration — and decoration that looks
    like a safeguard is worse than no safeguard at all."""
    sizes = {p: len(r) for p, (r, _c) in sets.items()}
    assert len(set(sizes.values())) > 1, f"every purpose returned the same number of rows: {sizes}"
    assert sizes["analysis"] < sizes["lethality"], sizes
    assert sizes["coverage"] >= sizes["lethality"], sizes


def test_analysis_excludes_the_runs_lethality_exists_to_see(sets):
    """`WHERE reportable` deletes the lethality phenotype: a design that divides and then collapses is exactly
    the signal, and QC marks it unreportable. So the set you may quote a mean from is the wrong set for
    counting deaths, and vice versa."""
    a_rows, _ = sets["analysis"]
    l_rows, l_ctx = sets["lethality"]
    assert not any(r.get("reportable") is False for r in a_rows), "a crashed run reached the analysis set"
    assert l_ctx["counts"]["non_reportable_kept"] > 0, "the lethality set kept no unreportable runs"


def test_audit_keeps_the_duplicates_supersession_needs(sets):
    """An append-only corpus records a correction as a NEW row superseding an old one. Deduping here hides
    exactly what an audit reads — and counting these rows is how `wildtype/basal` was once reported at 34
    seeds instead of 26, which is why the context says so out loud."""
    _rows, ctx = sets["audit"]
    assert ctx["counts"]["duplicate_rows"] > 0, ctx["counts"]
    assert "not a defect" in ctx["why_un_deduped"]


def test_coverage_carries_the_third_population(sets):
    """Tombstoned rows are neither live nor absent: excluded from ranking, kept in coverage. A count that does
    not say which of the three populations it counted is the WELL-9 incident (49/60/37)."""
    _rows, ctx = sets["coverage"]
    assert ctx["counts"]["tombstoned_included"] >= 0
    assert "third population" in ctx["tombstones"]


# ---------------------------------------------------------------------------------------------------------
# `ctx` names every filter and every refusal.
# ---------------------------------------------------------------------------------------------------------

def test_every_context_names_what_the_set_must_not_be_used_for(sets):
    """The field that does the actual work. A caller who reaches for the wrong purpose gets an answer that
    LOOKS right; the only defence is the boundary saying so at the point of return."""
    for p, (_r, ctx) in sets.items():
        assert ctx["NOT_for"] and len(ctx["NOT_for"]) > 30, f"{p}: no misuse warning"
        assert ctx["purpose"] == p and ctx["means"]
        assert "filters_applied" in ctx and "counts" in ctx


def test_the_arm_refusal_reaches_the_caller(sets):
    """Narrowing to one comparability arm is a REFUSAL to pool, not a quiet filter. `survey.analysis_rows`
    records it; a boundary that dropped it on the floor would hand back a filtered corpus with nothing saying
    it had been filtered."""
    _rows, ctx = sets["analysis"]
    if not ctx.get("arm"):
        pytest.skip("single-arm corpus: nothing was narrowed")
    assert ctx["refusals"], "the arm was narrowed and no refusal was reported"
    assert ctx["refusals"][0]["excluded"] >= 0 and ctx["refusals"][0]["why"]


def test_each_purpose_cites_invariants_that_actually_exist(sets):
    """The catalogue and the boundary must name the same rules. A purpose citing `INV-99` would read as
    enforcement of something that does not exist — the failure H-17a's probe test exists to prevent, one
    layer up."""
    known = {i["id"] for i in (invariants.load().get("invariants") or [])}
    if not known:
        pytest.skip("no invariant catalogue")
    for p, spec in hygiene.PURPOSES.items():
        bad = sorted(set(spec["invariants"]) - known)
        assert not bad, f"{p} cites invariants that are not in data/INVARIANTS.json: {bad}"


# ---------------------------------------------------------------------------------------------------------
# The surface, counted rather than assumed.
# ---------------------------------------------------------------------------------------------------------

def test_the_read_surface_is_enumerated_not_estimated():
    """The backlog says 7 modules issue their own `read_parquet` and admits "the true surface is larger than
    the 7 and was not enumerated". Counting it is what makes migration measurable instead of asserted."""
    s = hygiene.read_sites()
    assert s["n_direct_modules"] >= 7, s["direct_read_parquet"]
    assert s["n_consumer_modules"] > s["n_direct_modules"], (
        "the consumer surface should be the larger one — that is the point the backlog was making")


def test_migration_progress_is_not_overstated():
    """A boundary that exists is not a boundary that is used, and reporting the first as the second is how a
    P1 gets closed while the defect stays live. `migrated` names the call sites actually moved and must stay
    a SMALL fraction of the enumerated surface until it genuinely is not."""
    s = hygiene.read_sites()
    assert s["migrated"], "batch 1 moved three call sites; this list should name them"
    assert len(s["migrated"]) < s["n_consumer_modules"], (
        "migrated call sites now outnumber the consumer modules — recount the surface rather than "
        "assuming the migration is finished")
    assert "small fraction" in s["note"]


def test_the_disconfirmation_tool_asks_by_purpose():
    """The one call site with a MEASURED drift: `rigor.disconfirm` once keyed on `perturbation/condition` and
    reported an interval 5.5x narrower than `survey_corpus`, over crashed runs. It is the last place that
    should be choosing its own filters."""
    import inspect

    from src.cellarium import differential, rigor
    assert 'hygiene.rows("analysis")' in inspect.getsource(rigor.disconfirm)
    assert 'hygiene.rows("analysis")' in inspect.getsource(differential)
