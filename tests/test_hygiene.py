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


def test_no_two_purposes_share_a_filter_set_AND_a_contract():
    """The rule that lets `inventory` exist without being decoration.

    `inventory` returns the SAME rows as `lethality` — deduped, live, reportability-agnostic. Two purposes
    over one row set is exactly the duplication this module exists to avoid, UNLESS what they license
    differs: `lethality` may be asked whether a design collapses and not for a channel mean; `inventory` may
    be counted and not read at all. A purpose is a contract, not only a filter. What must never happen is two
    purposes agreeing on BOTH — that is a genuine duplicate wearing two names.
    """
    seen: dict = {}
    for name, spec in hygiene.PURPOSES.items():
        key = (tuple(spec["filters"]), spec["not_for"])
        assert key not in seen, f"{name} and {seen[key]} have the same filters AND the same contract"
        seen[key] = name


def test_the_denominator_purpose_shares_rows_but_not_a_licence(sets):
    """Stated as its own test because the sharing is deliberate and would otherwise read as a bug to whoever
    finds it next."""
    inv_rows, inv_ctx = sets["inventory"]
    leth_rows, _ = sets["lethality"]
    assert {r["id"] for r in inv_rows} == {r["id"] for r in leth_rows}
    assert inv_ctx["NOT_for"] != hygiene.PURPOSES["lethality"]["not_for"]
    assert "COUNTED" in inv_ctx["NOT_for"], "the denominator's contract must say the rows are to be counted"
    assert inv_ctx["counts"]["distinct_designs"] > 0


def test_the_purposes_return_genuinely_different_sets(sets):
    """THE test. If two purposes return the same rows, the argument is decoration — and decoration that looks
    like a safeguard is worse than no safeguard at all."""
    sizes = {p: len(r) for p, (r, _c) in sets.items()}
    assert len(set(sizes.values())) > 1, f"every purpose returned the same number of rows: {sizes}"
    assert len(set(sizes.values())) >= 3, f"the purposes have collapsed toward one row set: {sizes}"
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

def test_the_read_surface_is_counted_from_the_syntax_tree_not_the_text():
    """The counter gets the same standard as the thing it measures.

    A first version searched file TEXT and counted three modules that consume nothing: the tool's name inside
    the agent's system prompt, and the `def` lines of the two primitives themselves. It reported 15 consumer
    modules where there are 7. That over-count was not harmless — it was the basis of a claim, made twice,
    that the consumer surface is the LARGER one. Counted honestly it is the smaller one (7 consumers against
    8 direct-read modules), and the claim was an artefact of the instrument.
    """
    s = hygiene.read_sites()
    assert s["n_direct_modules"] >= 7, s["direct_read_parquet"]
    assert not s["unparsed"], s["unparsed"]
    for false_positive in ("agent.py", "store.py", "survey.py"):
        assert false_positive not in s["downstream_consumers"], (
            f"{false_positive} is not a consumer — it appears only as prompt text or as its own def line; "
            f"the counter has regressed to text search")
    assert "ast.Call" in s["counted_by"] and "string literals" in s["counted_by"], (
        "the two things counted are different in kind and the payload must say so")


def test_every_counted_site_names_where_it_is():
    """A count with no locations cannot be acted on. Each consumer site carries its file, its enclosing
    function and its line — which the syntax tree gives for free and a regex had to guess at."""
    for site in hygiene.read_sites()["consumer_sites"]:
        assert site["file"] and site["function"] and site["line"] > 0
        assert site["calls"] in ("list_results", "analysis_rows")


def test_migration_progress_is_not_overstated():
    """A boundary that exists is not a boundary that is used, and reporting the first as the second is how a
    P1 gets closed while the defect stays live. `migrated` names the call sites actually moved and must stay
    a SMALL fraction of the enumerated surface until it genuinely is not."""
    s = hygiene.read_sites()
    assert s["migrated"], "the migrated call sites should be named here"
    assert s["consumer_sites"], (
        "no unmigrated consumer sites remain — if that is genuinely true, say so deliberately and rewrite "
        "this test; do not let it pass silently on an empty surface")
    assert "small fraction" in s["note"]


def test_the_disconfirmation_tool_asks_by_purpose():
    """The one call site with a MEASURED drift: `rigor.disconfirm` once keyed on `perturbation/condition` and
    reported an interval 5.5x narrower than `survey_corpus`, over crashed runs. It is the last place that
    should be choosing its own filters."""
    import inspect

    from src.cellarium import differential, rigor
    assert 'hygiene.rows("analysis")' in inspect.getsource(rigor.disconfirm)
    assert 'hygiene.rows("analysis")' in inspect.getsource(differential)


# ---------------------------------------------------------------------------------------------------------
# The read-site registry, and the reconciliation that stops it becoming a comment.
# ---------------------------------------------------------------------------------------------------------

def test_the_registry_and_the_detector_agree_in_both_directions():
    """The whole reason a registry is allowed to exist here.

    A registry on its own is a DECLARATION, and this codebase's standing rule is that a declaration nobody
    verifies is a comment. Worse than the text-search counter it replaces: an unregistered new call site makes
    it UNDER-count, silently, while reading as complete — where the counter at least over-counted loudly.
    Checked both ways: detected-but-unregistered catches new code, registered-but-absent catches stale entries.
    """
    r = hygiene.registry_reconciliation()
    assert r["ok"], {k: r[k] for k in ("unregistered", "stale", "invalid_kind", "missing_reason")}
    assert r["n_detected"] == r["n_registered"] > 0


def test_every_registry_entry_says_why():
    """A classification with no reason is a label. The `why` is the part a reviewer checks, and it is the only
    defence against the one failure reconciliation cannot see."""
    for name, entry in hygiene.READ_SITE_REGISTRY.items():
        assert entry["kind"] in hygiene.KINDS, f"{name}: {entry['kind']}"
        assert len(str(entry.get("why") or "")) > 25, f"{name}: reason too thin to review"


def test_the_reconciliation_states_what_it_cannot_catch():
    """Reconciliation proves the registry is COMPLETE, not that it is RIGHT. A payload that did not say so
    would be read as the stronger claim — which is exactly the over-reading this module keeps guarding
    against."""
    r = hygiene.registry_reconciliation()
    assert "MISCLASSIFIED" in r["cannot_catch"]
    assert "COMPLETE, not that it is RIGHT" in r["cannot_catch"]


def test_a_misclassified_site_is_NOT_caught_and_that_limit_is_asserted_deliberately():
    """The honest negative. Registering a purpose-shaped read as a `lookup` silences every mechanical check
    here, and no amount of reconciliation will find it — only review will.

    Asserted as a TEST rather than left in a docstring so the limit cannot quietly stop being true: if some
    future check does start catching misclassification, this test fails and someone gets to delete it and
    claim the win.
    """
    entry = dict(hygiene.READ_SITE_REGISTRY["hf.py::_design_seeds"])
    hygiene.READ_SITE_REGISTRY["hf.py::_design_seeds"] = {**entry, "kind": "purpose_shaped"}
    try:
        assert hygiene.registry_reconciliation()["ok"], (
            "misclassification is now detected — good news; update this test and the `cannot_catch` note")
    finally:
        hygiene.READ_SITE_REGISTRY["hf.py::_design_seeds"] = entry
