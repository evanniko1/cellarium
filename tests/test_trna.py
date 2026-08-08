"""SCI-TRNA-1 — per-family charged tRNA.

The corpus reports ONE `fraction_trna_charged` (~0.95). The raw listener is 86 tRNA species x timesteps, and the
mean across them is the wrong instrument: an aminoacyl-tRNA synthetase knockout starves ONE family while the
other ~19 stay charged, so the aggregate barely moves and the mechanism is averaged away (Elf et al. 2003,
selective charging).

The validating test is the blind one: given no hint about which amino acid to look at, `KO:argS` must come back
with ARGININE collapsed and `KO:pheS` with PHENYLALANINE — recovered from the data, not asserted.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")
os.environ.setdefault("CELLARIUM_OUT", "runs")

import pytest  # noqa: E402


def _needs_raw(design):
    from cellarium import raw
    if not raw.seed_runs(design):
        pytest.skip(f"no local raw simOut for {design}")


def test_family_parsing_handles_the_real_id_shapes():
    from cellarium import trna
    assert trna.family_of("alaT-tRNA[c]") == "ala"
    assert trna.family_of("argQ-tRNA[c]") == "arg"
    assert trna.family_of("selC-tRNA[c]") == "sel"       # a real special case, not an error
    assert trna.family_of("not-a-trna") is None


def test_wildtype_resolves_about_twenty_families_and_the_mean_hides_spread():
    """The motivating fact: even in WILD TYPE the families are not uniform — tryptophan sits far below the mean.
    A single aggregate cannot represent that, let alone a knockout's selective collapse."""
    _needs_raw("wildtype/basal")
    from cellarium import trna
    r = trna.per_family("wildtype/basal")
    if "error" in r:
        pytest.skip(r["error"])
    assert 15 <= r["n_families"] <= 25, f"expected ~20 amino-acid families, got {r['n_families']}"
    vals = [f["charged_fraction"] for f in r["families"]]
    assert vals == sorted(vals), "families must be sorted ascending — the starved one first"
    assert max(vals) - min(vals) > 0.2, "the per-family spread the aggregate hides should be substantial"


@pytest.mark.parametrize("design", ["gene_knockout/KO:argS", "gene_knockout/KO:pheS"])
def test_arrested_synthetase_knockouts_are_REFUSED_not_reported_as_selectivity(design):
    """The withdrawn validation, inverted into a guard.

    These two runs were the tool's headline evidence ("argS starves arginine, blind"). They are translationally
    ARRESTED: the elongation rate is pinned at 0 for every timestep. The per-family table is then
    (86 - n_target)/86 — computable from the knockout's isoacceptor count with no simulation. Reporting it as a
    measurement of selective charging was reporting arithmetic as biology, so the tool must now REFUSE.

    WHAT THIS TEST NO LONGER ASSERTS, and why. It used to require `row_mean_total_variation < 1e-6`. That is
    one of TWO sufficient arrest detectors (`trna.py:120` is `tv < 1e-6 OR elongation_zero_fraction >= 0.999`),
    so pinning it asserted WHICH detector fired rather than the contract. It also characterised the original
    1-generation runs; the verified-index re-runs go to 3 generations, and MEASURED over those the row-mean
    total variation is ~3.0e-3 to 4.0e-3 per seed while elongation stays exactly 0 and protein mass ends at
    0.976x its start. The charged pools drift slowly across divisions with nothing consuming them — the run is
    arrested, not still. The threshold was loosened by the DATA changing, which is the one reason a threshold
    must never be quietly widened, so it is replaced rather than relaxed: what follows asserts the claim the
    refusal actually rests on — that the table is arithmetic.
    """
    _needs_raw(design)
    import numpy as np

    from cellarium import raw, trna
    r = trna.per_family(design)
    if "error" in r:
        pytest.skip(r["error"])
    st = r["translation_state"]
    assert st["arrested"] is True, f"{design} should be detected as arrested: {st}"
    assert r["most_starved"] is None, "an arrested run must not name a starved family"
    assert "refused" in r and "ARRESTED" in r["refused"]

    # THE ACTUAL GROUND OF THE REFUSAL: translation never runs, so the table carries no charging dynamics.
    assert st["elongation_zero_fraction"] >= 0.999, (
        f"{design} is called arrested but elongation is not pinned at zero: {st}")

    # ...and the table is therefore reproducible from the zeroed-isoacceptor COUNT alone, with no simulation.
    # This is the sentence in the docstring, asserted rather than restated.
    v, ids, _t = trna._read(raw.seed_runs(design)[0]["root"])
    col_mean = np.nanmean(v, axis=0)
    n = len(col_mean)
    zeroed = int((col_mean <= 1e-9).sum())
    assert 0 < zeroed < n, f"expected some but not all isoacceptors zeroed, got {zeroed}/{n}"
    assert abs(float(col_mean.mean()) - (n - zeroed) / n) < 5e-3, (
        f"{design}: the table is NOT the arithmetic identity (86-n)/86 — mean {col_mean.mean():.6f} vs "
        f"{(n - zeroed) / n:.6f}. If this diverges the run carries real charging dynamics and the blanket "
        f"refusal needs revisiting, not the tolerance.")


@pytest.mark.parametrize("design,family", [("gene_knockout/KO:dapA", "lys"), ("gene_knockout/KO:lysS", "lys")])
def test_non_degenerate_runs_still_name_the_right_cognate_family(design, family):
    """What genuinely survives: where translation CONTINUES, the cognate-family axis of Dittmar 2005 is
    recovered. dapA (a lysine-pathway lesion) and lysS both name `lys`, and nothing tells the tool that."""
    _needs_raw(design)
    from cellarium import trna
    r = trna.per_family(design)
    if "error" in r:
        pytest.skip(r["error"])
    assert r["translation_state"]["arrested"] is False
    assert r["most_starved"] == family, f"{design} should starve {family}, got {r['most_starved']}"


def test_the_steady_state_model_has_no_isoacceptor_resolution():
    """Why the Elf 2003 citation was withdrawn. Elf's result is BETWEEN isoacceptors of one amino acid; the
    STEADY-STATE elongation model gives every isoacceptor in a family an identical charged fraction, so that
    axis cannot be represented and must never be claimed. Asserted from the data, not from a comment.

    Scoped to steady_state deliberately, and the scope is asserted rather than assumed. The claim is a
    property of ONE elongation model, not of the tree: the kinetic model solves charging per isoacceptor and
    a within-family spread there is a real measurement (GLY 0.32, LEU 0.25). A test whose name generalised
    beyond its evidence is how a 'cannot' becomes a lie that later instructs a reader to discard real data.
    """
    import json
    import os
    from collections import defaultdict

    import numpy as np

    from cellarium import factors, raw, trna
    design = "wildtype/basal"
    assert factors.parse(design)["elongation_model"] == "steady_state", \
        "this test's claim holds only under the steady-state model — re-point it and it inverts"
    runs = raw.seed_runs(design)
    if not runs:
        pytest.skip("no local wild-type raw")
    so = raw.simout_dirs(runs[0]["root"])[0]
    ids = json.load(open(os.path.join(so, "GrowthLimits", "attributes.json"), encoding="utf-8")
                    )["uncharged_trna_ids"]
    g = defaultdict(list)
    for k, i in enumerate(ids):
        fam = trna.family_of(i)
        if fam:
            g[fam].append(k)
    multi = {f: ix for f, ix in g.items() if len(ix) >= 2}
    assert multi, "expected several families with >1 isoacceptor"
    v = np.asarray(raw.read_column(os.path.join(so, "GrowthLimits", "fraction_trna_charged")), dtype=float)[1:]
    spread = max(float(np.nanmax(v[:, ix].max(axis=1) - v[:, ix].min(axis=1))) for ix in multi.values())
    assert spread == 0.0, f"isoacceptors within a family differ by {spread} — re-examine the Elf 2003 claim"


def test_selective_charging_returns_no_verdict_and_always_carries_its_null():
    """A threshold without a null is not a detector. The old boolean fired on unperturbed wild-type, so it is
    gone — and the wild-type-vs-wild-type null must ride along on every call so the gap is never read bare."""
    _needs_raw("gene_knockout/KO:dapA")
    from cellarium import trna
    r = trna.selective_charging("gene_knockout/KO:dapA")
    if "error" in r:
        pytest.skip(r["error"])
    assert "selective_charging" not in r, "the uncalibrated boolean verdict must not come back"
    null = r["wildtype_null"]
    if "error" in null:
        pytest.skip(null["error"])
    assert null["n_distinct_by_content_hash"] >= 2
    # the null is a FALSE-POSITIVE rate: unperturbed runs still name a 'most starved' family
    assert null["worst_family_named_on_pure_wildtype"], "the null must show what wild-type alone produces"
    assert isinstance(r["exceeds_wildtype_null_max"], bool)


def test_the_aggregate_would_have_MISSED_it():
    """Why this module exists: the corpus's single number barely moves for a selective knockout, because ~19 of
    20 families stay charged. Assert that gap explicitly, so the motivation cannot quietly become false."""
    _needs_raw("gene_knockout/KO:argS")
    from cellarium import trna
    ko = trna.selective_charging("gene_knockout/KO:argS")
    if "error" in ko:
        pytest.skip(ko["error"])
    assert ko["worst_family"]["drop_pct"] < -90          # the family: essentially total collapse
    assert abs(ko["median_drop_pct"]) < 15               # the typical family: barely moves


# ---------------------------------------------------------------------------------------------------------
# TRNA-8: the charged-fraction channel must never be averaged across elongation models.
#
# It is a broadcast identity under steady_state and 86 independent values under kinetic, so a table built
# across them describes neither. The backlog filed this as "per_family takes a design string with no mode
# filter"; the exact design key DOES carry the mode (`#elong:kinetic`), so that path was always safe. The live
# hole was `raw.seed_runs`' FALLBACK match — perturbation plus a SUBSTRING of condition, neither of which
# carries the model, while the kinetic `KO:argS` rows carry exactly the same perturbation and condition as the
# steady-state ones.
# ---------------------------------------------------------------------------------------------------------

def _modes(runs):
    from cellarium.capability import DEFAULT_MODE
    return {(r.get("elongation_model") or DEFAULT_MODE) for r in runs}


def test_the_fallback_match_does_not_merge_elongation_models():
    """MEASURED before the fix: seed_runs('gene_knockout/KO:arg') returned 4 steady_state + 4 kinetic."""
    from cellarium import raw
    exact = raw.seed_runs("gene_knockout/KO:argS")
    if not exact:
        pytest.skip("no local raw for argS")
    for probe in ("gene_knockout/KO:arg", "gene_knockout/KO:ar"):
        runs = raw.seed_runs(probe)
        assert len(_modes(runs)) <= 1, (
            f"{probe!r} resolved to runs from {_modes(runs)} — the fallback pooled two instruments")


def test_a_run_carries_the_model_it_ran_under():
    """Without this a raw-reading tool cannot check what it read; it can only trust the narrowing."""
    from cellarium import raw
    runs = raw.seed_runs("gene_knockout/KO:argS")
    if not runs:
        pytest.skip("no local raw for argS")
    assert all(r.get("elongation_model") for r in runs)


def test_the_exact_key_still_reaches_the_kinetic_arm():
    """The narrowing must not make the kinetic runs unreachable — that would be silent absence, not a fix."""
    from cellarium import raw
    runs = raw.seed_runs("gene_knockout/KO:argS#elong:kinetic")
    if not runs:
        pytest.skip("no local kinetic raw for argS")
    assert _modes(runs) == {"kinetic"}, _modes(runs)


def test_per_family_refuses_when_its_runs_are_not_the_model_it_would_report(monkeypatch):
    """Defence in depth: the label must be checked, not assumed.

    `mode` is parsed from the design STRING and is what every downstream reader will call the result; the runs
    come from `seed_runs`. Nothing tied the two together, so a mismatch produced a kinetic measurement labelled
    steady_state — which reads exactly like a result.
    """
    from cellarium import raw, trna
    real = raw.seed_runs("gene_knockout/KO:argS")
    if not real:
        pytest.skip("no local raw for argS")
    monkeypatch.setattr(raw, "seed_runs",
                        lambda d: [dict(x, elongation_model="kinetic") for x in real])
    r = trna.per_family("gene_knockout/KO:argS")          # parses as steady_state
    assert r["most_starved"] is None
    assert "REFUSED" in r.get("refused", ""), r
    assert r.get("runs_by_model") == {"kinetic": len(real)}
