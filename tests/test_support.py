"""Every raw-derived claim must carry its own n — enforced, not promised.

The failure this guards against is not a wrong number, it is an unlabelled one: a value computed from a single
seed's single generation looks exactly like a value computed from 7 seeds. That ambiguity produced three real
withdrawals in this project (the one-seed mass decomposition, the n=1 lysS charging result, the 1-generation
shift magnitudes whose CI excluded the true steady state). A tool that omits `support` is therefore treated as
a bug here, so the guarantee cannot rot back.
"""

from __future__ import annotations

import pytest

from cellarium import agent, raw, store, support, survey


def _a_design_with_raw() -> str | None:
    for r in store.list_results():
        d = survey.design_key(r)
        if raw.seed_runs(d):
            return d
    return None


def test_coverage_reports_both_axes_and_never_only_seeds():
    """Seeds bound precision; generations bound whether the value has settled. Reporting one without the other
    is the exact mistake — more seeds makes a transient more precise, not more correct."""
    d = _a_design_with_raw()
    if not d:
        pytest.skip("no design with local raw")
    c = support.coverage(d)
    for key in ("n_seeds", "generations_per_seed", "max_generations", "min_generations",
                "single_seed", "single_generation", "sufficient"):
        assert key in c, f"coverage must report {key}"
    assert c["n_seeds"] >= 1
    assert c["sufficient"] == (not c["single_seed"] and not c["single_generation"])


def test_a_thin_design_is_marked_insufficient_and_says_why():
    """A 1-seed or 1-generation design must announce itself. Silence here is what let n=1 become a rule."""
    thin = None
    for r in store.list_results():
        d = survey.design_key(r)
        c = support.coverage(d)
        if c["n_seeds"] and not c["sufficient"]:
            thin = (d, c)
            break
    if not thin:
        pytest.skip("no thin design with local raw in this corpus")
    d, c = thin
    assert c["sufficient"] is False
    assert "warning" in c and c["warning"], d
    assert c["single_seed"] or c["single_generation"]


def test_absence_is_reported_as_absence_not_as_zero_support():
    """The silent-absence rule again: no raw must read as 'nothing rests on measured data', never as a
    well-formed coverage block that a caller would treat as a real (if small) n."""
    c = support.coverage("not_a_real_design_xyz")
    assert c["n_seeds"] == 0 and c["sufficient"] is False
    assert "ABSENCE" in c["warning"]


def test_compare_flags_a_depth_mismatch_between_designs():
    """Comparing a 4-generation design against a 1-generation one compares a settled value against a transient
    — the most common way a real difference is manufactured out of depth alone."""
    designs = [survey.design_key(r) for r in store.list_results()]
    depths = {}
    for d in dict.fromkeys(designs):
        c = support.coverage(d)
        if c["n_seeds"]:
            depths[d] = c["max_generations"]
    pair = None
    for a, da in depths.items():
        for b, db in depths.items():
            if da != db:
                pair = (a, b)
                break
        if pair:
            break
    if not pair:
        pytest.skip("no two designs with differing local depth")
    out = support.compare(*pair)
    assert out["depth_mismatch"] is True
    assert "warning" in out and "compare_at_generation" in out["warning"]
    assert out["common_generation_depth"] == min(depths[pair[0]], depths[pair[1]])


@pytest.mark.parametrize("tool,arg", [
    ("shift_response", "timeline/0 minimal, 1200 minimal_plus_amino_acids"),
    ("trna_families", "gene_knockout/KO:dapA"),
    ("segment_means", "timeline/0 minimal, 1200 minimal_plus_amino_acids"),
])
def test_raw_derived_tools_attach_their_support(tool, arg):
    """THE enforcement. Each of these reads raw and makes a claim, so each must state the n it rests on."""
    from cellarium import tools
    fn = tools.TOOL_FUNCS.get(tool) if hasattr(tools, "TOOL_FUNCS") else getattr(tools, tool, None)
    if fn is None:
        fn = getattr(tools, tool, None)
    if fn is None:
        pytest.skip(f"{tool} not exposed")
    out = fn(arg)
    # An UNAVAILABILITY report is not a claim, and must not be forced to carry a support block — doing so
    # would dress "I could not read anything" as "I measured this with n=0", which is the silent-absence
    # failure mode in a new costume. Both refusal shapes count: `error` and `available: False`. CI hits this
    # path for every raw-reading tool because it has no simOut, which is exactly why it is worth pinning.
    if not isinstance(out, dict) or "error" in out or out.get("available") is False:
        pytest.skip(f"{tool} reports unavailable here (no local raw): {str(out)[:100]}")
    assert "support" in out, f"{tool} returned a claim with no seed/generation support block"
    s = out["support"]
    assert "n_seeds" in s and "sufficient" in s


def test_an_unavailable_result_is_a_refusal_not_a_zero_n_claim():
    """The companion rule. A tool with no raw must return a refusal shape (`error` or `available: False`) and
    must NOT return a well-formed result carrying support with n_seeds=0 — that would read as a measurement
    made on nothing."""
    from cellarium import segments
    out = segments.diff("definitely_not_a_result_id")
    assert out.get("available") is False and "why" in out
    assert "channels" not in out, "an unavailable result must not carry claim-shaped fields"


def test_the_agent_is_instructed_on_both_axes():
    """Cellwright must be told the rule, in terms that distinguish the two axes — the user's requirement is
    that hard rails are never built on one generation of one seed."""
    sys_prompt = agent.SYSTEM
    assert "support" in sys_prompt
    low = sys_prompt.lower()
    assert "one seed" in low and "one generation" in low
    assert "transient" in low, "the prompt must explain WHY generations matter, not just that they do"
    assert "sufficient" in sys_prompt
