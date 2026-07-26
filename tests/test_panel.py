"""PUB-A2: the judge panel's reliability machinery — validated against published values, not against itself.

The panel exists because a single judge's number cannot be trusted. That argument collapses if the statistic
used to check the judge is itself unchecked, so α is pinned against **Krippendorff's own worked example**
(4 observers × 12 units with missing cells, α_nominal = 0.743) rather than against a reimplementation of the
same formula — which would only prove the two agree, not that either is right.

Everything here is pure: no API key, no model call. The reliability half of PUB-A2 has to be re-checkable for
free or it stops being re-checked.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "evals"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import panel as P  # noqa: E402

# Krippendorff's canonical reliability-data matrix ("Computing Krippendorff's Alpha-Reliability", 2011).
# 12 units, 4 observers, `None` where an observer did not rate the unit. Unit 12 is rated by nobody and
# units 1 and 11 by fewer than all — the missing data is the point of the example.
_KRIPP = {
    "A": [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None],
    "B": [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, None],
    "C": [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None],
    "D": [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None],
}


def _kripp_ratings():
    out: dict = {}
    for rater, row in _KRIPP.items():
        for i, v in enumerate(row):
            if v is not None:
                out.setdefault(f"u{i + 1}", {})[rater] = v
    return out


# ---------------------------------------------------------------- alpha, against published values
def test_alpha_reproduces_krippendorffs_own_worked_example():
    """The load-bearing test. 0.743 is the value published for this matrix; reproducing it exercises the
    unequal-rater weighting, the missing cells and the dropped unit all at once."""
    r = P.krippendorff_alpha(_kripp_ratings(), level="nominal")
    assert abs(r["alpha"] - 0.743) < 0.001, r
    # u1 has 3 raters, u10 has 3, u11 has 2, u2-u9 have 4 -> 11 usable. u12 is rated by nobody, so it never
    # enters `ratings` at all and is not a "drop" — the drop path is for units reaching exactly one rater.
    assert r["n_units"] == 11 and r["n_units_dropped"] == 0, r


def test_alpha_is_1_for_perfect_agreement_and_reports_it_as_such():
    r = P.krippendorff_alpha({"u1": {"a": 0.0, "b": 0.0}, "u2": {"a": 1.0, "b": 1.0}}, level="interval")
    assert r["alpha"] == 1.0 and "acceptable" in r["interpretation"]


def test_alpha_goes_NEGATIVE_on_systematic_disagreement():
    """Negative α is a real, diagnostic outcome — raters disagreeing MORE than random assignment would. It must
    not be clamped to zero, because 'worse than chance' and 'chance' mean different things about the rubric."""
    r = P.krippendorff_alpha({"u1": {"a": 0.0, "b": 1.0}, "u2": {"a": 1.0, "b": 0.0},
                              "u3": {"a": 0.0, "b": 1.0}, "u4": {"a": 1.0, "b": 0.0}}, level="interval")
    assert r["alpha"] < 0, r
    assert "CHANCE" in r["interpretation"]


def test_a_constant_rating_is_undefined_not_perfect():
    """Every judge saying 0.5 to everything scores identically to a broken judge that always says 0.5. D_e = 0,
    so α is undefined — returning 1.0 here would launder a degenerate grader as a flawless one."""
    r = P.krippendorff_alpha({"u1": {"a": 0.5, "b": 0.5}, "u2": {"a": 0.5, "b": 0.5}}, level="interval")
    assert r["alpha"] is None and "undefined" in r["note"]


def test_interval_and_nominal_differ_where_it_matters():
    """`quality_score` is a fraction, so 0.4-vs-0.6 must count as closer than 0.0-vs-0.6. Nominal cannot express
    that, which is why interval is the default."""
    near = {"u1": {"a": 0.4, "b": 0.6}, "u2": {"a": 0.9, "b": 1.0}, "u3": {"a": 0.1, "b": 0.0}}
    far = {"u1": {"a": 0.0, "b": 0.6}, "u2": {"a": 0.9, "b": 0.0}, "u3": {"a": 0.1, "b": 1.0}}
    assert P.krippendorff_alpha(near, "interval")["alpha"] > P.krippendorff_alpha(far, "interval")["alpha"]
    # Under NOMINAL both sets are total disagreement — every pair differs — so the observed disagreement is
    # identical and only the marginals distinguish them. That is the wrong reading for a graded score: it says
    # "0.4 vs 0.6" is exactly as wrong as "0.0 vs 1.0". (Their alphas are not equal, because D_e still moves
    # with the value distribution; it is D_o that has gone blind.)
    assert P.krippendorff_alpha(near, "nominal")["d_o"] == P.krippendorff_alpha(far, "nominal")["d_o"] == 1.0


def test_single_rater_units_are_dropped_and_SAID_to_be_dropped():
    r = P.krippendorff_alpha({"u1": {"a": 1.0}, "u2": {"a": 0.0, "b": 1.0}, "u3": {"a": 1.0, "b": 0.0}})
    assert r["n_units"] == 2 and r["n_units_dropped"] == 1


def test_it_degrades_rather_than_raising():
    assert P.krippendorff_alpha({})["alpha"] is None
    assert P.krippendorff_alpha({"u1": {"a": 1.0}})["alpha"] is None


# ---------------------------------------------------------------- reading a real ledger
def _ledger(with_text=True):
    def cell(q, t):
        s = {"quality_score": q, "judge_model": "claude-opus-4-8"}
        if with_text:
            s["graded_text"] = t
        return {"quality_score": q, "shared": s}
    return {
        "1.1#r0": {"_case": "1.1", "_rep": 0, "a": cell(0.8, "A says X"), "b": cell(0.4, "B says Y")},
        "1.1#r1": {"_case": "1.1", "_rep": 1, "a": cell(0.6, "A says X2"), "b": cell(0.4, "B says Y2")},
        "2.1#r0": {"_case": "2.1", "_rep": 0, "a": cell(1.0, "A says Z"), "b": cell(0.6, "B says W")},
        "2.1#r1": {"_case": "2.1", "_rep": 1, "a": cell(0.8, "A says Z2"), "b": cell(0.4, "B says W2")},
    }


def test_every_stored_artifact_is_found_with_the_text_it_was_scored_on():
    us = P.artifacts(_ledger())
    assert len(us) == 8
    a = next(u for u in us if u["unit"] == "1.1#r0#a")
    assert a["text"] == "A says X" and a["original_score"] == 0.8 and a["arm"] == "a"


def test_an_old_ledger_without_stored_text_is_flagged_not_silently_skipped():
    """A ledger written before `graded_text` existed cannot be re-graded at all. Quietly running the panel over
    whatever remains would report an agreement statistic computed on a different set than the sweep."""
    us = P.artifacts(_ledger(with_text=False))
    assert len(us) == 8 and all(u["text"] is None for u in us)


# ---------------------------------------------------------------- the three reported numbers
def _panel():
    # judge_x and judge_y agree on the RANKING but judge_y is uniformly harsher; judge_x is also noisier.
    return {
        "1.1#r0#a": {"jx": [0.8, 0.7], "jy": [0.6, 0.6]},
        "1.1#r0#b": {"jx": [0.4, 0.5], "jy": [0.2, 0.2]},
        "2.1#r0#a": {"jx": [1.0, 0.9], "jy": [0.8, 0.8]},
        "2.1#r0#b": {"jx": [0.6, 0.5], "jy": [0.4, 0.4]},
    }


def test_the_summary_separates_agreement_leniency_and_noise():
    """Three different failure modes; collapsing them into one number is how a panel becomes theatre. A uniform
    offset between judges cancels in a PAIRED test and is survivable; a judge's own wobble does not and is not."""
    s = P.summarise(_panel())
    assert s["judges"] == ["jx", "jy"] and s["n_units"] == 4
    assert s["leniency_spread"] > 0.15, s              # jy is systematically harsher
    assert s["within_judge_sd"]["jy"] == 0.0           # jy is perfectly repeatable...
    assert s["within_judge_sd"]["jx"] > 0.0            # ...jx is not
    assert s["pairwise"]["jx vs jy"]["n"] == 4


def test_decision_stability_agrees_when_the_judges_only_differ_by_an_offset():
    """The point of pairing: a constant leniency difference must NOT change the conclusion."""
    st = P.decision_stability(_panel(), P.artifacts(_ledger()))
    assert st["sign_agrees"] and st["stable"], st
    for r in st["per_judge"].values():
        assert r["paired_test"]["mean_diff_b_minus_a"] < 0     # arm A scores higher under both judges


def test_decision_stability_SHOUTS_when_a_judge_flips_the_result():
    """The failure this whole module exists for — already observed in this project, where the one significant
    ablation cell flips under `generic_judge`. It must be impossible to read the report and miss it."""
    flipped = {
        "1.1#r0#a": {"jx": [0.8], "jy": [0.2]}, "1.1#r0#b": {"jx": [0.4], "jy": [0.9]},
        "2.1#r0#a": {"jx": [0.9], "jy": [0.1]}, "2.1#r0#b": {"jx": [0.5], "jy": [0.8]},
    }
    st = P.decision_stability(flipped, P.artifacts(_ledger()))
    assert not st["sign_agrees"] and not st["stable"]
    assert "DEPENDS ON THE JUDGE" in st["verdict"]


def test_noise_is_compared_against_the_effect_not_just_reported():
    """A grader wobbling as much as the arms differ makes the sweep unreadable, and no number of replicates
    fixes it. That comparison has to be computed, not left for a reader to make."""
    noisy = {u: {"jx": [0.1, 0.9]} for u in ("1.1#r0#a", "1.1#r0#b", "2.1#r0#a", "2.1#r0#b")}
    nv = P.noise_vs_effect(P.summarise(noisy), P.decision_stability(noisy, P.artifacts(_ledger())))
    assert nv["readable"] is False and nv["largest_within_judge_sd"] > 0.5
    clean = P.noise_vs_effect(P.summarise(_panel()), P.decision_stability(_panel(), P.artifacts(_ledger())))
    assert clean["effect_to_noise"] is not None


def test_a_single_family_panel_is_called_out_as_not_answering_PUB_A2():
    """PUB-A2 is about self-preference AND noise. Three Opus judges measure noise only, and shipping that as
    'the panel' would answer half the objection while looking like it answered all of it."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "evals", "panel.py"), encoding="utf-8").read()
    assert "measures NOISE but not SELF-PREFERENCE" in src
