"""M-5b: the SCREENING and SPACE-FILLING generators.

`doe.py` could build a full factorial and, past a cap, take a random subsample of it. Its own docstring said
what was wrong with that: "a random sample, NOT a resolution-defined fractional factorial — it does not
control aliasing". A design that cannot say which factor produced an effect saves runs and buys nothing, and
a two-level grid over a continuous lever reports its endpoints and steps straight over anything in between.

Every assertion here is written so that the thing being claimed is MEASURED off the realized design rather
than taken from the generator's own label:

  * resolution and the alias groups are recomputed from the sign matrix and compared against the algebra;
  * Plackett-Burman orthogonality is checked column-pair by column-pair, so a mistyped generating row
    cannot pass by being called a Plackett-Burman row;
  * the Latin-hypercube stratification check is run against a PLAIN RANDOM SAMPLE as well, because a
    stratification test that a random sample also passes is decoration (absence needs an absent machine);
  * the split-plot ordering is checked against full randomization on the same cells, for the same reason.
"""

import itertools
import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import doe  # noqa: E402

# --- helpers that re-derive the claim independently --------------------------------------------------

def _column(matrix, j):
    return [row[j] for row in matrix]


def _product(matrix, idxs):
    return [math.prod(row[j] for j in idxs) for row in matrix]


def _words_by_brute_force(matrix, k):
    """Every subset of columns whose elementwise product is CONSTANT — the defining relation, measured.

    This is the independent instrument. `doe` derives the words algebraically from the generator set (2^p-1
    products of the generators); if that algebra and the actual sign matrix ever disagree, the reported
    resolution describes a design nobody ran."""
    words = []
    for size in range(1, k + 1):
        for subset in itertools.combinations(range(k), size):
            col = _product(matrix, subset)
            if len(set(col)) == 1:
                words.append(frozenset(subset))
    return set(words)


def _balanced(col):
    return col.count(1) == col.count(-1)


# --- fractional factorial ----------------------------------------------------------------------------

def test_fractional_factorial_reproduces_the_textbook_2_4_1():
    """4 factors in 8 runs: I = ABCD, resolution IV, 2-factor interactions aliased in pairs."""
    out = doe.fractional_factorial({n: [0, 1] for n in "ABCD"}, runs=8)
    assert out["n_runs"] == 8 and len(out["cells"]) == 8
    assert out["resolution"] == 4
    assert out["defining_relation"] == ["ABCD"]
    # Main effects CLEAR of two-factor interactions is the whole point of resolution IV.
    assert out["main_effects_clear"] is True
    pairs = {frozenset(g) for g in out["aliases"] if all(len(e) == 2 for e in g)}
    assert pairs == {frozenset({"AB", "CD"}), frozenset({"AC", "BD"}), frozenset({"AD", "BC"})}


def test_fractional_factorial_finds_the_resolution_iv_2_6_2_that_greedy_misses():
    """6 factors in 16 runs. Taking the two LONGEST generator words gives resolution III; the search must
    find a resolution-IV assignment instead. This is the case that makes the search worth having."""
    out = doe.fractional_factorial({n: [0, 1] for n in "ABCDEF"}, runs=16)
    assert out["resolution"] == 4, out["defining_relation"]
    assert out["main_effects_clear"] is True
    assert out["search"] == "exhaustive" and out["minimum_aberration_guaranteed"] is True


def test_fractional_factorial_saturated_design_is_resolution_iii_and_says_so():
    """7 factors in 8 runs is saturated: every main effect is aliased with 2-factor interactions."""
    out = doe.fractional_factorial({n: [0, 1] for n in "ABCDEFG"}, runs=8)
    assert out["resolution"] == 3 and out["main_effects_clear"] is False
    # A resolution-III design that does not hand back the confounds is the random subsample with a better
    # name. Every main effect must appear in an alias group with something else.
    aliased_mains = {e for g in out["aliases"] for e in g if len(e) == 1}
    assert aliased_mains == set("ABCDEFG")


def test_fractional_factorial_resolution_v_leaves_two_factor_interactions_clear():
    out = doe.fractional_factorial({n: [0, 1] for n in "ABCDE"}, runs=16)
    assert out["resolution"] == 5
    assert out["main_effects_clear"] is True and out["two_factor_interactions_clear"] is True
    assert out["aliases"] == []          # nothing of order <= 2 is confounded


def test_fractional_factorial_algebra_matches_the_realized_sign_matrix():
    """The cross-check: the algebraic defining relation must equal the one measured off the matrix."""
    for names, runs in (("ABCD", 8), ("ABCDE", 16), ("ABCDEF", 16), ("ABCDEFG", 8)):
        out = doe.fractional_factorial({n: [0, 1] for n in names}, runs=runs)
        k, matrix = len(names), out["matrix"]
        measured = _words_by_brute_force(matrix, k)
        declared = {frozenset(names.index(ch) for ch in w) for w in out["defining_relation"]}
        assert measured == declared, (names, runs, sorted(map(sorted, measured)))
        assert out["resolution"] == min(len(w) for w in measured)
        for j in range(k):                       # every factor column balanced, or the design is not a design
            assert _balanced(_column(matrix, j))


def test_fractional_factorial_degenerates_to_a_full_factorial_without_pretending_otherwise():
    out = doe.fractional_factorial({n: [0, 1] for n in "ABC"}, runs=8)
    assert out["n_runs"] == 8 and out["fraction"] == "2^(3-0)"
    assert out["resolution"] is None and out["defining_relation"] == []
    assert "full factorial" in out["note"].lower()


def test_fractional_factorial_refuses_what_it_cannot_resolve():
    # Fewer runs than factors+1: not enough degrees of freedom for the main effects alone.
    assert "error" in doe.fractional_factorial({n: [0, 1] for n in "ABCDEFGH"}, runs=8)
    # A factor that is not two-level is not a candidate for a two-level fraction.
    assert "error" in doe.fractional_factorial({"gene": ["a", "b", "c"]}, runs=4)
    # A run count that is not a power of two cannot carry a regular fraction.
    assert "error" in doe.fractional_factorial({n: [0, 1] for n in "ABCD"}, runs=12)
    assert "error" in doe.fractional_factorial({}, runs=8)


def test_fractional_factorial_cells_carry_real_factor_levels():
    out = doe.fractional_factorial({"gene": ["wt", "ko"], "ppgpp": ["fixed", "dynamic"],
                                    "aa_supply": ["medium", "enzymes"], "anchor": ["none", "0.55"]}, runs=8)
    for cell in out["cells"]:
        assert set(cell) == {"gene", "ppgpp", "aa_supply", "anchor"}
        assert cell["gene"] in ("wt", "ko") and cell["anchor"] in ("none", "0.55")
    assert len({tuple(sorted(c.items())) for c in out["cells"]}) == 8      # no repeated cell


# --- Plackett-Burman ---------------------------------------------------------------------------------

@pytest.mark.parametrize("n_factors,expected_runs", [(3, 4), (5, 8), (7, 8), (8, 12), (11, 12),
                                                     (12, 16), (15, 16), (16, 20), (19, 20), (23, 24)])
def test_plackett_burman_run_count_is_the_next_multiple_of_four(n_factors, expected_runs):
    out = doe.plackett_burman({f"f{i}": [0, 1] for i in range(n_factors)})
    assert out["n_runs"] == expected_runs


@pytest.mark.parametrize("n_factors", [3, 5, 7, 8, 11, 12, 15, 16, 19, 23])
def test_plackett_burman_columns_are_balanced_and_pairwise_orthogonal(n_factors):
    """The defining property, checked rather than asserted by naming. A mistyped generating row breaks
    orthogonality on some pair and this test is what finds it."""
    out = doe.plackett_burman({f"f{i}": [0, 1] for i in range(n_factors)})
    matrix, k = out["matrix"], n_factors
    for j in range(k):
        assert _balanced(_column(matrix, j)), (n_factors, j)
    for a, b in itertools.combinations(range(k), 2):
        dot = sum(x * y for x, y in zip(_column(matrix, a), _column(matrix, b)))
        assert dot == 0, (n_factors, a, b, dot)
    assert out["resolution"] == 3
    assert "main effects" in out["note"].lower()


def test_plackett_burman_refuses_beyond_its_tabulated_rows():
    assert "error" in doe.plackett_burman({f"f{i}": [0, 1] for i in range(40)})
    assert "error" in doe.plackett_burman({"gene": ["a", "b", "c"]})


def test_plackett_burman_is_cheaper_than_the_full_factorial_it_replaces():
    """The feasibility claim, as arithmetic: 11 factors is 2048 cells full, 12 runs screened."""
    factors = {f"f{i}": [0, 1] for i in range(11)}
    full = len(doe.full_factorial(factors))
    pb = doe.plackett_burman(factors)
    assert full == 2048 and pb["n_runs"] == 12
    assert pb["n_full_factorial"] == full


# --- Latin hypercube ---------------------------------------------------------------------------------

def _bins_hit(values, lo, hi, n):
    """Which of n equal bins of [lo, hi] each value falls in."""
    out = []
    for v in values:
        idx = int((v - lo) / (hi - lo) * n)
        out.append(min(idx, n - 1))
    return out


def test_latin_hypercube_puts_exactly_one_point_in_every_one_dimensional_bin():
    ranges = {"charged_fraction": (0.55, 0.85), "ko_level": (5.0, 99.0)}
    out = doe.latin_hypercube(ranges, n=12, seed=0)
    assert len(out["points"]) == 12
    for name, (lo, hi) in ranges.items():
        vals = [p[name] for p in out["points"]]
        assert all(lo <= v <= hi for v in vals)
        assert sorted(_bins_hit(vals, lo, hi, 12)) == list(range(12)), name


def test_a_plain_random_sample_fails_the_stratification_check():
    """The instrument is forced to fail. If a uniform random sample also put one point in each bin, the
    test above would be measuring nothing and the generator would be pointless."""
    rng = random.Random(0)
    failures = 0
    for _ in range(20):
        vals = [rng.uniform(0.55, 0.85) for _ in range(12)]
        if sorted(_bins_hit(vals, 0.55, 0.85, 12)) != list(range(12)):
            failures += 1
    assert failures == 20, "a random sample should essentially never be a Latin hypercube"


def test_latin_hypercube_is_deterministic_and_seed_sensitive():
    r = {"x": (0.0, 1.0)}
    assert doe.latin_hypercube(r, n=8, seed=4)["points"] == doe.latin_hypercube(r, n=8, seed=4)["points"]
    assert doe.latin_hypercube(r, n=8, seed=4)["points"] != doe.latin_hypercube(r, n=8, seed=5)["points"]


def test_latin_hypercube_centered_option_puts_points_at_bin_midpoints():
    out = doe.latin_hypercube({"x": (0.0, 1.0)}, n=4, seed=0, center=True)
    assert sorted(p["x"] for p in out["points"]) == [0.125, 0.375, 0.625, 0.875]


def test_latin_hypercube_states_what_it_cannot_do():
    out = doe.latin_hypercube({"x": (0.0, 1.0)}, n=5, seed=0)
    low = out["note"].lower()
    assert "not" in low and ("alias" in low or "factorial" in low or "effect" in low)
    assert out["refuses"]       # a non-empty list of questions this design must not be asked


def test_latin_hypercube_refuses_degenerate_input():
    assert "error" in doe.latin_hypercube({"x": (1.0, 1.0)}, n=4)       # zero-width range
    assert "error" in doe.latin_hypercube({"x": (1.0, 0.0)}, n=4)       # inverted range
    assert "error" in doe.latin_hypercube({}, n=4)
    assert "error" in doe.latin_hypercube({"x": (0.0, 1.0)}, n=1)       # n < 2 strata is not a hypercube


# --- central composite -------------------------------------------------------------------------------

def test_central_composite_face_centred_stays_inside_the_declared_range():
    """Default alpha. Every point legal, because for us a factor range is usually a HARD bound."""
    ranges = {"anchor": (0.55, 0.85), "level": (5.0, 99.0)}
    out = doe.central_composite(ranges, alpha="face", center=2)
    assert out["n_points"] == 2 ** 2 + 2 * 2 + 2 == len(out["points"])
    assert out["alpha"] == 1.0 and out["out_of_range"] == []
    for name, (lo, hi) in ranges.items():
        assert all(lo <= p[name] <= hi for p in out["points"])
    assert out["n_center"] == 2


def test_central_composite_rotatable_reports_the_points_it_pushes_outside_and_does_not_clamp():
    """A rotatable alpha is >1 in coded units, so star points leave the box. For a charged fraction or a
    graded-KO percentage that box is physics, not preference — so the violation is REPORTED, never clamped
    behind the caller's back, which is how an illegal design reaches a cluster looking legal."""
    ranges = {"anchor": (0.55, 0.85), "level": (5.0, 99.0)}
    out = doe.central_composite(ranges, alpha="rotatable")
    assert out["alpha"] == pytest.approx(2 ** 0.5)
    assert {v["factor"] for v in out["out_of_range"]} == {"anchor", "level"}
    outside = [p for p in out["points"] if not (0.55 <= p["anchor"] <= 0.85)]
    assert outside, "the violation must be visible in the points, not silently corrected"
    assert out["legal"] is False


def test_central_composite_centre_point_is_what_detects_curvature():
    """The knowledge-discovery mechanism, as arithmetic. Two levels cannot tell a line from a step; the
    centre point's departure from the endpoint average is the signal that something happens in between."""
    assert doe.center_point_curvature(1.0, 1.5, 2.0)["curvature"] == pytest.approx(0.0)   # linear
    step = doe.center_point_curvature(1.0, 1.0, 2.0)                                      # a cliff above 0.5
    assert step["curvature"] == pytest.approx(-0.5) and step["linear"] is False
    assert "two-level" in step["note"].lower() or "two level" in step["note"].lower()


def test_central_composite_can_build_its_cube_as_a_fraction():
    """6 factors would be 64 corners plus 12 star points. A resolution-V fraction keeps the surface model
    estimable at a quarter of the cost, and the resolution is reported so the trade is visible."""
    ranges = {f"f{i}": (0.0, 1.0) for i in range(6)}
    out = doe.central_composite(ranges, cube_runs=32)
    assert out["cube"]["n_runs"] == 32 and out["cube"]["resolution"] >= 5
    assert out["n_points"] == 32 + 2 * 6 + 1


def test_central_composite_refuses_degenerate_input():
    assert "error" in doe.central_composite({})
    assert "error" in doe.central_composite({"x": (1.0, 1.0)})
    assert "error" in doe.central_composite({"x": (0.0, 1.0)}, alpha="nonsense")


# --- split-plot run order ----------------------------------------------------------------------------

def test_whole_plot_order_groups_the_factor_that_cannot_be_re_randomized():
    """A knowledge base is BUILT once and many runs share it. Randomizing it per run is an instruction to
    rebuild it per run — which is both unaffordable and not what the operator will actually do."""
    cells = doe.full_factorial({"anchor": ["none", "0.55", "0.85"], "gene": ["argS", "hisS", "leuS"]})
    out = doe.whole_plot_order(cells, whole_plot="anchor", seed=1)
    order = out["order"]
    assert sorted(map(str, order)) == sorted(map(str, cells))             # still every cell, once
    changes = sum(1 for a, b in zip(order, order[1:]) if a["anchor"] != b["anchor"])
    assert changes == 2 == out["n_level_changes"]                          # 3 levels -> 2 changes, the minimum
    assert out["whole_plots"] == {"none": 3, "0.55": 3, "0.85": 3}


def test_full_randomization_interleaves_the_same_cells():
    """Forced comparison: without the split-plot ordering the whole-plot factor changes far more often."""
    cells = doe.full_factorial({"anchor": ["none", "0.55", "0.85"], "gene": ["argS", "hisS", "leuS"]})
    worse = max(sum(1 for a, b in zip(r, r[1:]) if a["anchor"] != b["anchor"])
                for r in (doe.randomize(cells, seed=s) for s in range(10)))
    assert worse > 2


def test_whole_plot_order_randomizes_within_and_between_plots():
    cells = doe.full_factorial({"arm": ["A", "B"], "gene": list("abcdef")})
    a = doe.whole_plot_order(cells, whole_plot="arm", seed=1)["order"]
    b = doe.whole_plot_order(cells, whole_plot="arm", seed=2)["order"]
    assert a != b                                                      # seeded, but not a fixed order
    assert a == doe.whole_plot_order(cells, whole_plot="arm", seed=1)["order"]


def test_whole_plot_order_refuses_a_factor_the_cells_do_not_have():
    cells = doe.full_factorial({"gene": ["a", "b"]})
    assert "error" in doe.whole_plot_order(cells, whole_plot="arm")


# --- panel integration ------------------------------------------------------------------------------

def test_panel_full_design_is_unchanged():
    """No regression: the default path must produce exactly what it produced before the generators landed."""
    out = doe.panel({"gene": ["pfkA", "pfkB", "tpiA"], "condition": ["basal", "acetate"]},
                    seeds=4, generations=3, cv=0.05, effect_pct=10.0, block_by="condition", seed=1)
    assert out["n_full_factorial"] == 6 and out["n_cells"] == 6 and out["subsampled"] is False
    assert out["total_sims"] == 24 and out["design"] == "full"


def test_panel_fractional_design_reports_resolution_and_aliases():
    factors = {n: [0, 1] for n in "ABCDEF"}
    out = doe.panel(factors, design="fractional", runs=16, seeds=4, cv=0.05)
    assert out["design"] == "fractional" and out["n_cells"] == 16
    assert out["n_full_factorial"] == 64 and out["resolution"] == 4
    assert out["main_effects_clear"] is True and "aliases" in out
    assert out["total_sims"] == 64                                     # 16 cells x 4 seeds
    # The honesty requirement: a reduced design must say what it bought and what it gave up.
    assert "resolution" in out["note"].lower()


def test_panel_plackett_burman_design_screens_many_factors():
    out = doe.panel({f"f{i}": [0, 1] for i in range(11)}, design="plackett_burman", seeds=2, cv=0.05)
    assert out["n_cells"] == 12 and out["n_full_factorial"] == 2048 and out["resolution"] == 3
    assert out["main_effects_clear"] is False


def test_panel_random_screen_keeps_its_old_warning_and_is_now_named():
    out = doe.panel({"g": list("abcdefgh"), "c": list("12345678")}, design="random_screen", cap=10, cv=0.05)
    assert out["n_cells"] == 10 and out["subsampled"] is True
    assert out["resolution"] is None                # a random subsample HAS no resolution — not a number
    assert "aliasing NOT controlled" in out["note"]


def test_panel_rejects_an_unknown_design():
    out = doe.panel({"g": ["a", "b"]}, design="latin_hypercube")
    assert "error" in out and "latin_hypercube" in out["error"]


def test_panel_propagates_the_split_plot_penalty_into_the_power_annotation():
    """The arm factor is replicated by WHOLE PLOTS, not by seeds. Reporting one MDE for both is how a panel
    claims power it does not have for the factor the operator cares most about."""
    factors = {"anchor": ["none", "0.55", "0.85"], "gene": ["argS", "hisS"]}
    out = doe.panel(factors, seeds=8, cv=0.05, effect_pct=10.0, whole_plot="anchor", seed=0)
    wp = out["power"]["whole_plot"]
    assert wp["factor"] == "anchor" and wp["n_whole_plots"] == 3
    assert wp["mde_pct_at_n_whole_plots"] > out["power"]["mde_pct_at_n"]      # strictly worse, as it must be
    assert "whole" in wp["note"].lower()
    changes = sum(1 for a, b in zip(out["run_order"], out["run_order"][1:]) if a["anchor"] != b["anchor"])
    assert changes == 2


def test_panel_screens_cells_through_a_legality_predicate_and_reports_the_drops():
    """A generator picks corners the operator never looked at, so a reduced design is MORE likely to propose
    an illegal cell than a hand-written grid. Dropping them silently would shrink the design without
    saying so — the panel must hand back what it removed and why."""
    def legal(cell):
        if cell["condition"] == "acetate" and cell["gene"] == "pfkA":
            return False, "glucose-fitted expression; a shift into acetate does not reach steady state"
        return True

    out = doe.panel({"gene": ["pfkA", "pfkB"], "condition": ["basal", "acetate"]}, cv=0.05, legal=legal)
    assert out["n_cells"] == 3 and out["n_full_factorial"] == 4
    assert len(out["illegal_cells"]) == 1
    dropped = out["illegal_cells"][0]
    assert dropped["cell"] == {"gene": "pfkA", "condition": "acetate"}
    assert "steady state" in dropped["reason"]
    assert all(c != dropped["cell"] for c in out["run_order"])
    assert "illegal" in out["note"].lower() or "dropped" in out["note"].lower()


def test_panel_legality_predicate_can_empty_the_design_without_crashing():
    """Forced empty branch: a panel whose every cell is illegal must say so, not return a cheerful zero."""
    out = doe.panel({"gene": ["pfkA"]}, cv=0.05, legal=lambda cell: (False, "out of envelope"))
    assert out["n_cells"] == 0 and out["total_sims"] == 0
    assert out["run_order"] == [] and len(out["illegal_cells"]) == 1
    assert "error" in out or "no legal" in out["note"].lower()


# --- surface panel ----------------------------------------------------------------------------------

def test_surface_panel_wraps_the_space_filling_generators_with_a_budget():
    out = doe.surface_panel({"anchor": (0.55, 0.85)}, design="latin_hypercube", n=10, seeds=4,
                            generations=4, cv=0.05)
    assert out["design"] == "latin_hypercube" and out["n_points"] == 10 and out["total_sims"] == 40
    assert out["power"]["observed_replicate_cv"] == 0.05


def test_surface_panel_central_composite_counts_its_budget_and_legality():
    out = doe.surface_panel({"a": (0.0, 1.0), "b": (0.0, 1.0)}, design="central_composite", seeds=2,
                            alpha="rotatable", cv=0.05)
    assert out["legal"] is False and out["out_of_range"]
    assert out["total_sims"] == out["n_points"] * 2


def test_surface_panel_rejects_a_factorial_design_name():
    out = doe.surface_panel({"a": (0.0, 1.0)}, design="fractional")
    assert "error" in out


# --- rule 4: a factor whose levels are FITTED parameters is an arm, not a factor --------------------

def test_refit_levers_are_declared_not_guessed():
    assert "trna_charged_fraction_target" in doe.REFIT_FACTORS
    assert "operons" in doe.REFIT_FACTORS
    found = doe.refit_factors_in({"gene": ["a", "b"], "operons": ["on", "off"]})
    assert found == ["operons"]
    assert doe.refit_factors_in({"gene": ["a", "b"]}) == []


def test_panel_refuses_to_cross_a_refit_lever_as_an_ordinary_factor():
    """Crossing it asks for a ParCa refit per cell, and the resulting rows carry different knowledge-base
    hashes — the non-poolability boundary. A panel that emits those cells looks runnable and is not."""
    out = doe.panel({"gene": ["argS", "hisS"], "operons": ["on", "off"]}, cv=0.05)
    assert "error" in out and "operons" in out["error"]
    assert "arm" in out["error"].lower() and "whole_plot" in out["error"]


def test_panel_allows_a_refit_lever_as_a_whole_plot_and_says_how_many_arms_it_spans():
    out = doe.panel({"gene": ["argS", "hisS"], "operons": ["on", "off"]}, cv=0.05, whole_plot="operons")
    assert "error" not in out and out["n_cells"] == 4
    assert out["arms_spanned"] == {"factor": "operons", "n_arms": 2, "levels": ["on", "off"]}
    assert "not poolable" in out["note"].lower()


def test_panel_refuses_two_refit_levers_because_only_one_can_be_the_whole_plot():
    out = doe.panel({"operons": ["on", "off"], "trna_charged_fraction_target": ["none", "0.55"]},
                    cv=0.05, whole_plot="operons")
    assert "error" in out and "trna_charged_fraction_target" in out["error"]


def test_a_refit_looking_name_is_FLAGGED_not_refused():
    """The declared list is exact; a name that merely looks like a refit lever gets a warning. Refusing on a
    proxy would block valid panels, and this project has withdrawn findings for exactly that reason."""
    out = doe.panel({"gene": ["a", "b"], "charging_anchor": ["lo", "hi"]}, cv=0.05)
    assert "error" not in out
    assert out["possible_refit_factors"] == ["charging_anchor"]
    assert "check" in out["note"].lower()
