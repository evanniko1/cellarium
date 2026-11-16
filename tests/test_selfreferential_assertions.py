"""The committed ledger of self-referential threshold assertions, and the instrument that finds them.

WHAT THIS REPLACES, AND WHY THE SHAPE M-11 ASKED FOR IS THE WRONG DETECTOR. The finding this module
closes was discovered by a JOIN: `tests_naming` from `data/mutation/threshold_test_map.json`, intersected
with the thresholds the recorded Tier 0 run did not kill. Nine tests were in that join on 2026-11-02 and
seven of them assert a constant against itself, so a mutation moves the expectation along with the code
and the assertion holds at every value. `BACKLOG.md`'s remedy was a sweep for the AST shape
`<expr with CONST> == <expr with the same CONST>`. That shape was implemented and MEASURED over all 139
test files (4,978 `ast.Assert` statements, recounted 2026-11-14): it matches exactly ONE assertion in the
whole suite -- `tests/test_llm_seam.py:91`, on `TEMPERATURE`, where it is a CORRECT assertion that two
modules agree -- and NONE of the nine cases it was generalised from. The reason is visible once the nine
are read: in every one of them the constant appears on ONE side only, and the other side is a value the
PRODUCTION code derived from that same constant. That is a data-flow property, not a syntactic one.

So the detector here is two stages and neither is the backlog's shape:

  * STAGE 1, static. Four classes, assigned per (comparison side, constant) and reduced to one class per
    (test, constant) pair: `both_sides` (the constant on two sides of one comparison), `literal_pinned`
    (the constant pinned by literals -- an equality, or literals on both sides of a chain),
    `one_sided_bound` (an inequality whose other sides are not pure literals, so the bound moves with the
    constant), `computed_equality` (an equality against something a call produced). `one_sided_bound` and
    `computed_equality` are the two shapes that catch all nine.
  * STAGE 2, measurement. For every candidate naming one of the declared numeric thresholds, perturb the
    literal both ways and run THAT ONE TEST ALONE. Not its covering set: running the covering set is what
    let the join lose seven of its own nine entries, because a sibling test's kill masks the
    self-referential one. `test_the_per_test_discriminator_is_not_masked_by_a_sibling_test_and_reports_an_empty_run_as_unmeasured`
    forces that masking on purpose and shows the per-test discriminator is not fooled by it.

WHAT IS MEASURED HERE AND WHAT IS NOT. Only a candidate whose constant is a declared numeric threshold
has a mutation operator at all, and that is a minority of the sweep. The remainder -- set, dict, tuple,
string and expression-valued constants, including `runner.WALL_MIN_PER_GEN`, which is
`float(os.environ.get(...))` and therefore outside `thresholds()`'s universe by construction -- is a
STATIC classification and nothing else. It is recorded `unmeasured`, never as reviewed and never as a
pass, and `test_the_non_numeric_remainder_is_reported_UNMEASURED_and_never_as_reviewed` is what stops
that remainder reading as a closed finding. This is the project's named silent-absence class, so the
instrument says which questions it did not ask.

THE POSITIVE CONTROL IS THE LOAD-BEARING TEST IN THIS FILE. A detector that replaces a join must find
everything the join found, and `test_the_selfref_sweep_rediscovers_every_case_the_join_found` asserts
all nine ids of `SELF_REFERENTIAL_REVIEW` are candidates, with each one's measured class declared as a
literal. The same test runs the backlog's own shape and records its failure executably: one pair, none
of the nine. That forced failure lives in the suite rather than in a commit message, because a commit
message cannot be re-run.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

# Imported, not re-stated. `SELF_REFERENTIAL_REVIEW` is the nine-entry review the join produced and the
# thing this sweep must not be weaker than; a second copy of it here would be a second definition of the
# control, which is the conformance failure the mutation harness already learned once (`thresholds()` is
# imported by `test_threshold_boundaries.py` rather than re-implemented). `_REVIEW_VERDICTS` comes along
# for the same reason: one vocabulary for "what a reviewed assertion was decided to be".
from test_threshold_boundaries import (  # noqa: E402
    _REVIEW_VERDICTS,
    SELF_REFERENTIAL_REVIEW,
)

REPO = Path(__file__).resolve().parents[1]
SELFREF = REPO / "data" / "mutation" / "selfref.json"


def _harness():
    """`scripts/mutate_thresholds.py`, loaded by path for its classifier and its discriminator.

    The same loader `test_threshold_boundaries.py` uses, and for the same reason: the rule for what counts
    as a declared threshold, a referenced name and a self-referential shape must have exactly one
    definition, and it lives in the harness that runs the sweep.
    """
    import importlib.util
    path = REPO / "scripts" / "mutate_thresholds.py"
    spec = importlib.util.spec_from_file_location("_mutate_thresholds_selfref", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------------------------------------
# (i) The positive control: the sweep must rediscover every case the join found.
# ----------------------------------------------------------------------------------------------------

# id -> (constant, the class stage 1 assigns it, the reviewed assertion AS IT WAS WRITTEN).
#
# THE ASSERTION SOURCE IS FROZEN HERE ON PURPOSE, and the reason is a defect that landed while this file
# was being written. The nine are a HISTORICAL finding, and the point of fixing a finding is that the
# defect goes away -- `tests/test_audit.py:7` was repaired (it now asserts the literals 5.2 and 7.8) while
# this sweep was being built, so a control that only asks "is this id a live candidate" started failing
# for the best possible reason and would have been weakened to make it pass. Freezing each reviewed
# assertion makes the control permanent: the classifier is re-run against the nine shapes themselves,
# which cannot be repaired out from under it, AND against the live tree, where a repair must be declared
# in `_REPAIRED` and is checked by asserting the shape is really gone.
#
# Whitespace-normalised (`" ".join(src.split())`) so a re-wrap of a long line is not a false alarm, and
# read out of the files with `ast.get_source_segment` rather than typed by hand. The one entry taken from
# `git show HEAD:` is the repaired one, and it is marked as such below.
_NINE_REVIEWED: dict[str, tuple[str, str, str]] = {
    "tests/test_audit.py::test_gb_estimate_scales_with_generations_and_seeds": (
        "GB_PER_GENERATION", "computed_equality",
        'assert audit._gb(8, 1) == round(8 * audit.GB_PER_GENERATION, 2)'),
    "tests/test_extraction.py::test_the_per_span_budget_stays_under_the_streaming_threshold": (
        "AGENT_MAX_TOKENS_CAP", "one_sided_bound",
        'assert all(k["max_tokens"] <= extraction.AGENT_MAX_TOKENS_CAP for k in c.calls)'),
    "tests/test_extraction.py::test_a_long_unwrapped_paragraph_is_split_into_sentence_sized_units": (
        "CITABLE_UNIT_MAX", "one_sided_bound",
        'assert max(len(u["text"]) for u in units) <= extraction.CITABLE_UNIT_MAX'),
    "tests/test_failures.py::test_the_wall_limit_scales_with_generations_and_can_be_turned_off": (
        "WALL_STARTUP_MIN", "computed_equality",
        'assert runner.wall_limit_s(4) == 60 * (runner.WALL_STARTUP_MIN + 4 * runner.WALL_MIN_PER_GEN)'),
    "tests/test_deg_payload.py::test_walk_is_bounded": (
        "_MAX_NODES", "one_sided_bound",
        'assert len(seen) <= D._MAX_NODES'),
    "tests/test_discovery_leg_fixes.py::test_the_survey_fits_its_budget_by_showing_fewer_rows_and_saying_so": (
        "SURVEY_DIGEST_CHARS", "one_sided_bound",
        'assert len(json.dumps(d)) <= tools.SURVEY_DIGEST_CHARS < agent._TOOL_CAPS["survey_corpus"]'),
    "tests/test_surrogate.py::test_train_reports_baseline_and_abstains_when_underpowered": (
        "MIN_LABELS", "one_sided_bound",
        'assert out["trained"] is False and out["n"] < surrogate.MIN_LABELS'),
    "tests/test_threshold_boundaries.py::test_the_agent_token_cap_has_a_FLOOR_and_not_only_a_ceiling": (
        "AGENT_MAX_TOKENS_CAP", "literal_pinned",
        'assert extraction.AGENT_MAX_TOKENS_CAP == 12000'),
    "tests/test_extraction.py::test_a_long_line_with_no_sentence_boundary_stays_ONE_unit_and_is_not_truncated": (
        "CITABLE_UNIT_MAX", "one_sided_bound",
        'assert len(row) > extraction.CITABLE_UNIT_MAX'),
}

# The reviewed ids whose assertion has since been REPAIRED out of the tree, with the measured reason. An
# entry here is a claim about the tree and is checked both ways: the frozen shape must be ABSENT from the
# live file, and the pair must not be a live candidate. Re-introduce the old assertion and both halves
# fail, so "repaired" cannot decay into "no longer looked at".
_REPAIRED: dict[str, str] = {
    "tests/test_audit.py::test_gb_estimate_scales_with_generations_and_seeds":
        "repaired 2026-11-14 alongside the `GB_PER_GENERATION_ARRESTED` wiring: the expectations are now "
        "the literals 5.2 and 7.8 (8 x 0.65 and 4 x 0.65 x 3, recomputed from the declared 0.65), so the "
        "`round(8 * audit.GB_PER_GENERATION, 2)` shape is gone and no comparison in that test names the "
        "constant at all. This is the first of the nine to be closed rather than catalogued.",
}

# The single pair M-11's stated shape finds, written out so the forced failure is an equality and not a
# count. `assert llm.TEMPERATURE == agent.TEMPERATURE` names the same constant on both sides of one `==`,
# which is the backlog's rule exactly -- and it is a CORRECT assertion (two modules must agree), so the
# backlog's detector finds one true positive that is not a defect and misses all nine that are.
_BOTH_SIDES_EQUALITY_ONLY = {
    "tests/test_llm_seam.py::test_the_sampling_policy_moved_without_changing_behaviour::TEMPERATURE",
}


def test_the_selfref_sweep_rediscovers_every_case_the_join_found():
    """The positive control, in two halves, plus the backlog shape's failure recorded executably.

    FROZEN HALF -- the classifier is handed each of the nine reviewed assertions as source and must assign
    it the declared class. This half cannot be repaired out from under the control and cannot be satisfied
    by the sweep agreeing with itself, which is why it exists: reading `data/mutation/selfref.json` here
    would let a sweep that stopped finding these write an artefact that validated it.

    LIVE HALF -- every reviewed id that is still in the tree must be a live candidate with the same class,
    and every id in `_REPAIRED` must be genuinely gone: the frozen shape absent from the file AND no
    candidate for the pair. The cost of the live sweep is one AST parse per test file -- 139 of them on
    2026-11-14 -- and it runs in under a second.

    FORCED BEFORE IT WAS TRUSTED. With the classifier restricted to the backlog's shape the candidate set
    collapses to `_BOTH_SIDES_EQUALITY_ONLY` and every one of the nine is missing -- asserted below, so
    the demonstration is re-run on every suite rather than remembered. Restricting it further, by dropping
    `computed_equality`, loses `test_gb_estimate_scales_with_generations_and_seeds` and
    `test_the_wall_limit_scales_with_generations_and_can_be_turned_off`; dropping `one_sided_bound` loses
    the remaining six.
    """
    mt = _harness()
    cands = mt._sweep_candidates()

    assert set(_NINE_REVIEWED) == set(SELF_REFERENTIAL_REVIEW), (
        "the frozen shape table and the reviewed join have drifted apart: "
        f"{sorted(set(_NINE_REVIEWED) ^ set(SELF_REFERENTIAL_REVIEW))}")
    assert set(_REPAIRED) <= set(_NINE_REVIEWED), (
        f"_REPAIRED names ids that were never reviewed: {sorted(set(_REPAIRED) - set(_NINE_REVIEWED))}")

    for tid, (const, want, shape) in sorted(_NINE_REVIEWED.items()):
        frozen = mt._assert_shapes(f"def test_reviewed():\n    {shape}\n",
                                   "tests/test_frozen.py", {const: ["frozen.py"]})
        got = {r["constant"]: r["class"] for r in frozen}
        assert got.get(const) == want, (
            f"{tid}: the frozen shape {shape!r} classifies as {got.get(const)!r}, declared {want!r}")

        live = (REPO / tid.partition("::")[0]).read_text(encoding="utf-8")
        present = shape in " ".join(live.split())
        if tid in _REPAIRED:
            assert not present, (
                f"{tid} is declared repaired ({_REPAIRED[tid]}) yet the reviewed assertion {shape!r} is "
                f"back in the file")
            assert f"{tid}::{const}" not in cands, (
                f"{tid} is declared repaired yet is still a live candidate: {cands[f'{tid}::{const}']}")
            continue
        assert present, (
            f"{tid}: the reviewed assertion {shape!r} is no longer in the file and nothing declares it "
            f"repaired. Add it to _REPAIRED with the reason, or the review has silently lost a case.")
        assert f"{tid}::{const}" in cands, (
            f"the sweep is WEAKER than the join it replaces: {tid}::{const} was found by "
            f"`tests_naming` x survivors and is not a candidate here")
        assert cands[f"{tid}::{const}"]["class"] == want, (
            f"{tid}::{const}: live class {cands[f'{tid}::{const}']['class']!r}, declared {want!r}")

    # The backlog's shape, run as its own classifier over the same files.
    restricted = {k for k, v in cands.items()
                  if any(o["class"] == "both_sides" and o["equality"] for o in v["occurrences"])}
    assert restricted == _BOTH_SIDES_EQUALITY_ONLY, (
        f"M-11's `<expr with CONST> == <expr with the same CONST>` shape now matches {sorted(restricted)}. "
        f"If a new one arrived, read it: the shape itself found one pair in 139 test files and that pair "
        f"is a "
        f"correct assertion.")
    assert not (restricted & {f"{t}::{c}" for t, (c, _k, _s) in _NINE_REVIEWED.items()}), (
        "the backlog's shape must find NONE of the nine; that is the measurement that replaced it")


# ----------------------------------------------------------------------------------------------------
# (ii) The classifier, on planted source.
# ----------------------------------------------------------------------------------------------------

# One plant per class, plus the two legitimate false positives the rule has to refuse: a constant named
# only in prose, and the singular of a plural that IS in use. Both of those are the repairs
# `_referenced_names` already carries (scripts/mutate_thresholds.py's own docstring records them), and
# they are re-plated here rather than assumed to carry over, because this sweep calls that function on a
# COMPARISON SIDE instead of a whole test body and nothing says a rule survives a change of domain.
_PLANTED = '''
def test_pins_a_literal():
    assert mod.CAP == 12000

def test_pins_a_two_sided_band():
    assert 8000 <= mod.CAP <= 16000

def test_a_bound_that_moves_with_its_constant():
    sent = mod.build_request()["max_tokens"]
    assert sent <= mod.CAP

def test_recomputes_the_implementation():
    assert mod.gb(8) == round(8 * mod.RATE, 2)

def test_compares_the_constant_with_itself():
    assert mod.CAP == mod.CAP + 0

def test_guards_its_fixture():
    row = "x" * 400
    assert len(row) > mod.CAP
    units = mod.split_units(row)
    assert len(units) == 1

def test_mentions_a_constant_only_in_prose():
    """ZZZ_PROSE_ONLY is the floor, and this sentence is the only place it is named."""
    assert True

def test_the_plural_is_not_the_singular():
    assert mod.CAPS["a"] == 1
'''

# The inventory the plants are classified against. Deliberately holds CAP and not CAPS: the pair exists
# because substring matching once credited `_TOOL_CAPS` usage to the unrelated `_TOOL_CAP`.
_PLANT_INVENTORY = {"CAP": ["mod.py"], "RATE": ["mod.py"], "ZZZ_PROSE_ONLY": ["mod.py"]}

# "test::CONST" -> (class, fixture_precondition, why). A plant with no entry is an unclassified shape and
# fails below, so a new shape has to be decided here rather than arriving silently.
_PLANT_EXPECTS: dict[str, tuple[str, bool, str]] = {
    "test_pins_a_literal::CAP": (
        "literal_pinned", False,
        "an equality against a literal is the form this ledger exists to write: the expectation does not "
        "move with the mutant"),
    "test_pins_a_two_sided_band::CAP": (
        "literal_pinned", False,
        "literals on BOTH sides of the chain pin the constant inside a band, so either mutant that leaves "
        "the band is caught"),
    "test_a_bound_that_moves_with_its_constant::CAP": (
        "one_sided_bound", False,
        "the other side is a Name holding a value the code derived from the same constant -- this is the "
        "shape seven of the nine have, and declaring it `literal_pinned` is the forced failure"),
    "test_recomputes_the_implementation::RATE": (
        "computed_equality", False,
        "the expectation re-implements the function under test with the same constant, so every value of "
        "it passes -- `test_audit.py`'s `_gb(8, 1) == round(8 * GB_PER_GENERATION, 2)` exactly"),
    "test_compares_the_constant_with_itself::CAP": (
        "both_sides", False,
        "the backlog's own shape; it is the rarest of the four and the only one the backlog could see"),
    "test_guards_its_fixture::CAP": (
        "one_sided_bound", True,
        "a bound by syntax but a precondition by position: the assertion runs BEFORE the module under "
        "test is called, so it is keeping the fixture honest and its slackness is correct"),
}

# Constants that must NOT become candidates, with the reason each one is a legitimate false positive.
_PLANT_REFUSES = {
    "ZZZ_PROSE_ONLY": "a docstring mention asserts nothing about a value",
    "CAPS": "the plural in use is not a reference to the singular; exact identifiers, never substrings",
}


def test_the_classifier_separates_a_pinned_literal_from_a_bound_that_moves_with_its_constant():
    """Every class on planted source, in the `_PLANTED` / `_PLANT_EXPECTS` form.

    FORCED, both ways. Declaring `test_a_bound_that_moves_with_its_constant::CAP` as `literal_pinned`
    fails with `classified 'one_sided_bound'`, because the other side of the comparison is a Name and not
    a literal -- which is the whole distinction between a bound that can catch a mutant and one that
    cannot. Adding `ZZZ_PROSE_ONLY` to `_PLANT_EXPECTS` fails with `credited a candidate`, because a
    docstring is excluded from `_referenced_names` and a plant that disagrees says the exclusion broke.
    """
    mt = _harness()
    rows = mt._assert_shapes(_PLANTED, "tests/test_plant.py", _PLANT_INVENTORY)
    got = {f"{r['test'].rpartition('::')[2]}::{r['constant']}": r for r in rows}

    unclassified = sorted(set(got) - set(_PLANT_EXPECTS))
    assert not unclassified, f"planted shapes nobody decided a class for: {unclassified}"
    for key, (want, want_fixture, why) in sorted(_PLANT_EXPECTS.items()):
        assert key in got, f"{key}: credited no candidate at all -- {why}"
        assert got[key]["class"] == want, f"{key}: classified {got[key]['class']!r}, declared {want!r} -- {why}"
        assert got[key]["fixture_precondition"] is want_fixture, (
            f"{key}: fixture_precondition {got[key]['fixture_precondition']}, declared {want_fixture} -- {why}")
    for name, why in sorted(_PLANT_REFUSES.items()):
        credited = sorted(k for k in got if k.endswith(f"::{name}"))
        assert not credited, f"{name}: credited a candidate {credited} -- {why}"


# ----------------------------------------------------------------------------------------------------
# (iii) The per-test discriminator, and the masking it exists to remove.
# ----------------------------------------------------------------------------------------------------

_PLANT_PAIR_TEST = '''import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import mod_plant as mod


def test_selfref():
    assert mod.CAP <= mod.CAP + 1


def test_pins():
    assert mod.CAP == 12000
'''


def test_the_per_test_discriminator_is_not_masked_by_a_sibling_test_and_reports_an_empty_run_as_unmeasured(tmp_path):
    """Two tests over one constant: one self-referential, one that pins the literal.

    THE MASKING IS FORCED, NOT ARGUED. Pointed at the FILE, the discriminator reports `detects_it`,
    because `test_pins` fails under both mutants -- and under that reading `test_selfref` would be
    recorded as a test that notices its constant move, which it provably does not. Pointed at
    `::test_selfref` alone it reports `cannot_see_it_move`. That difference is why stage 2 runs one test
    id instead of the covering set, and it is the same defect in miniature that lost seven of the join's
    own nine entries.

    AND AN EMPTY RUN IS NEVER A PASS. A second plant writes the literal as `12_000` and the discriminator
    is handed `12000` -- which is what `repr(12000)` yields and what the first Tier 0 run substituted,
    turning 8 mutants into `error` instead of `SURVIVED`. The substitution refuses, and the verdict is
    `unmeasured` with the literal named, rather than a clean run reported as a survivor.
    """
    mt = _harness()
    target = tmp_path / "mod_plant.py"
    target.write_text("CAP = 12000\n", encoding="utf-8")
    (tmp_path / "test_plant_pair.py").write_text(_PLANT_PAIR_TEST, encoding="utf-8")

    per_test_selfref = mt._discriminate(target, 1, "12000", 12000,
                                        "test_plant_pair.py::test_selfref", cwd=tmp_path)
    per_test_pins = mt._discriminate(target, 1, "12000", 12000,
                                     "test_plant_pair.py::test_pins", cwd=tmp_path)
    per_file = mt._discriminate(target, 1, "12000", 12000, "test_plant_pair.py", cwd=tmp_path)

    assert per_test_selfref["verdict"] == "cannot_see_it_move", per_test_selfref
    assert per_test_pins["verdict"] == "detects_it", per_test_pins
    assert per_file["verdict"] == "detects_it", (
        f"the whole-file run reported {per_file['verdict']!r}; the plant is built so that the sibling "
        f"kills both mutants, which is the masking this discriminator avoids by running one test id")
    assert target.read_text(encoding="utf-8") == "CAP = 12000\n", "the mutant was not restored"

    underscored = tmp_path / "mod_underscored.py"
    underscored.write_text("CAP = 12_000\n", encoding="utf-8")
    not_found = mt._discriminate(underscored, 1, "12000", 12000,
                                 "test_plant_pair.py::test_selfref", cwd=tmp_path)
    assert not_found["verdict"] == "unmeasured", not_found
    assert "12000" in not_found["reason"], not_found


# ----------------------------------------------------------------------------------------------------
# (iv) The ledger, and the declared limit.
# ----------------------------------------------------------------------------------------------------

# A `cannot_see_it_move` verdict is a MEASUREMENT, not a conviction: `MAP_AUDIT_2026-11-13.md`'s own risk
# list names the false-positive route (a fixture, a monkeypatch or a module-level cache holding the
# pre-mutation value -- `differential._REF_TRAJ_CACHE` and `_CISTRON_MAP_CACHE` are live examples), so
# every one is read by hand before it enters this ledger. Two verdicts beyond `_REVIEW_VERDICTS` exist for
# what that reading can conclude: the cache case, and a mutant that cannot change behaviour at all.
_SELFREF_VERDICTS = (*_REVIEW_VERDICTS, "cache_held_the_value", "equivalent_mutant")

# "tests/file.py::test_name::CONST" -> (verdict, reason). Keyed on the pair, not the test, because one
# test can name several thresholds and be self-referential about exactly one of them --
# `tests/test_truncation.py::test_the_floor_is_the_projects_own_constant_not_a_new_one` pins `MIN_SEEDS`
# against the literal 2 and names `MIN_GENERATIONS` only inside a source string, so the same test is a
# kill for one constant and blind for the other. A test-keyed ledger could not say that.
#
# MEASURED 2026-11-14 over 25 mutatable candidates, 50 single-test mutant runs, 94 s: 11 `detects_it`,
# 13 `cannot_see_it_move`, 1 `unmeasured` (a skip). Each of the 13 below was read in its source before it
# was given a verdict, which is why five of them are `equivalent_mutant` rather than findings: a test that
# asserts a constant is REFERENCED, or that a call site names it, cannot be moved by changing its value,
# and reporting those as defects would inflate the finding with correct tests.
SELFREF_DISPOSITIONS: dict[str, tuple[str, str]] = {
    "tests/test_agent.py::test_converse_circuit_breaker_stops_on_repeated_identical_tool_call::_REPEAT_CAP": (
        "self_referential",
        "`calls['n'] <= agent._REPEAT_CAP + 2` derives its own bound from the cap, so the expectation "
        "moves with the mutant by construction: at _REPEAT_CAP 3 the breaker trips after 3 rounds plus one "
        "forced synthesis and the bound is 5; at 2 it trips after 2 and the bound is 4; at 4, 5 and 6. "
        "Both mutants passed. What the test DOES establish is that the breaker fires far below the 30-turn "
        "budget, which is the property its name claims and is worth keeping; where the cap sits is not "
        "pinned anywhere, and `_REPEAT_CAP` is a declared judgement about patience rather than a number "
        "the paper rests on."),
    "tests/test_deg_payload.py::test_walk_is_bounded::_MAX_NODES": (
        "self_referential",
        "the original finding, re-measured by the new instrument rather than inherited: `len(seen) <= "
        "D._MAX_NODES` is the bound asserting itself and both the 2000 and 8000 mutants passed. The test's "
        "own docstring now says to read it as 'this returns at all'. Where the bound sits is pinned by the "
        "literal 3999 in test_threshold_boundaries.py, which came back `detects_it` for the same constant, "
        "so the pair is blind and the threshold is not."),
    "tests/test_extraction.py::test_a_citation_wider_than_the_cap_is_rejected::MAX_CITED_UNITS": (
        "correct_precondition",
        "`len(units) > extraction.MAX_CITED_UNITS` keeps the fixture wide enough to be refused, and the "
        "citation it then builds is `MAX_CITED_UNITS + 1` wide, so the property under test -- a citation "
        "one unit past the cap is refused -- is correctly independent of where the cap is. MEASURED "
        "margin: LONG_PROSE yields 16 citable units against a cap of 12, so both the 11 and 13 mutants "
        "left the precondition true; it would go red at a cap of 16, which is the fixture's own limit and "
        "not a defect in the assertion."),
    "tests/test_extraction.py::test_a_long_line_with_no_sentence_boundary_stays_ONE_unit_and_is_not_truncated::CITABLE_UNIT_MAX": (
        "correct_precondition",
        "the one entry of the original nine the join itself classified as correct, and the only candidate "
        "in the whole sweep that stage 1 flags `fixture_precondition`: `len(row) > CITABLE_UNIT_MAX` runs "
        "one line BEFORE `extraction.citable_units(row)`, so it is validating the fixture rather than the "
        "result. The property -- a row with no sentence boundary stays one unit at full length -- is "
        "genuinely cap-independent, so passing under both the 150 and 600 mutants is the correct outcome."),
    "tests/test_extraction.py::test_a_long_unwrapped_paragraph_is_split_into_sentence_sized_units::CITABLE_UNIT_MAX": (
        "self_referential",
        "`max(len(u['text']) for u in units) <= extraction.CITABLE_UNIT_MAX` holds at every cap because "
        "the splitter shrinks the units to whatever the cap is: lower it and they shrink with it, raise it "
        "and they stay inside. Both the 150 and 600 mutants passed. Positionally this one sits AFTER the "
        "call, which is what separates it from its neighbour three lines down in the same file -- same "
        "operator, same constant, opposite meaning. Where the cap sits is pinned by literal span lengths "
        "in test_threshold_boundaries.py."),
    "tests/test_factors.py::test_the_rrna_label_uses_the_named_constant::N_RRN_OPERONS": (
        "self_referential",
        "the expectation interpolates the constant -- `== f'rRNA_operons_removed:4of{F.N_RRN_OPERONS}'` -- "
        "so the string the test compares against is rebuilt from the mutant and both 6 and 8 passed. The "
        "test's name is accurate about what it checks: the label is BUILT from the constant rather than "
        "typed again. AND THE SIBLING THAT WOULD PIN THE VALUE DID NOT RUN HERE: "
        "`test_the_rrna_denominator_matches_the_models_own_operon_list` compares 7 against the model's own "
        "operon list and SKIPPED under both mutants, recorded `unmeasured`, so on this machine nothing "
        "pins the 7 at all. That is a gap in the environment, not a pass."),
    "tests/test_failures.py::test_the_wall_limit_scales_with_generations_and_can_be_turned_off::WALL_STARTUP_MIN": (
        "self_referential",
        "`wall_limit_s(4) == 60 * (runner.WALL_STARTUP_MIN + 4 * runner.WALL_MIN_PER_GEN)` restates the "
        "implementation with both of its own constants, so it asserts that the arithmetic was typed twice "
        "the same way; both the 15.0 and 60.0 mutants passed. Kept as a finding about the test's FORM, not "
        "about the number -- `WALL_STARTUP_MIN` is a declared estimate term the ledger in "
        "test_threshold_boundaries.py records as intentionally unpinned. Note the companion constant "
        "`runner.WALL_MIN_PER_GEN` is `float(os.environ.get(...))` and so has no mutation operator at all; "
        "it is in this sweep's candidate set only because the inventory is a superset of `thresholds()`."),
    "tests/test_reader_agg.py::test_no_threshold_in_sci2_is_declared_without_an_executable_reference::DEG_SIG": (
        "equivalent_mutant",
        "the constant is named as a STRING inside a membership assertion (`>= {'PADJ_SIG', 'DEG_SIG', "
        "'NULL_PERMUTATIONS'}`) that is the positive control for an enumerator: the test asserts each "
        "declared sci2 threshold has an executable reference, which is a property of the NAME and of the "
        "AST, not of the value. No numeric mutation can move it, so `cannot_see_it_move` is the correct "
        "outcome and not a blind spot. Its value is pinned behaviourally elsewhere by "
        "`test_the_log2FC_significance_cut_decides_WHICH_genes_sign_concordance_is_scored_on`."),
    "tests/test_reader_agg.py::test_no_threshold_in_sci2_is_declared_without_an_executable_reference::NULL_PERMUTATIONS": (
        "equivalent_mutant",
        "same assertion and same reason as the DEG_SIG entry above: the name appears in the control set of "
        "a deadness test, so changing the number cannot change the verdict. `NULL_PERMUTATIONS` is "
        "separately recorded as intentionally unpinned -- more draws is strictly better, so no value is "
        "correct -- which is why no behavioural case pins it either, and that is a declared decision "
        "rather than an unmeasured one."),
    "tests/test_reader_agg.py::test_no_threshold_in_sci2_is_declared_without_an_executable_reference::PADJ_SIG": (
        "equivalent_mutant",
        "same assertion and same reason as the two entries above. `PADJ_SIG` is the one threshold the Tier "
        "0 ledger records as `unreachable_here` -- pinning it behaviourally needs `build_reference` and "
        "therefore the reference dataset -- so this pair being value-independent does not change what is "
        "and is not measured about it; that is recorded in test_threshold_boundaries.py and stays open."),
    "tests/test_surrogate.py::test_train_reports_baseline_and_abstains_when_underpowered::MIN_LABELS": (
        "self_referential",
        "`out['n'] < surrogate.MIN_LABELS` on a three-label set holds at every floor above three, so it "
        "cannot see the floor move, and both the 7 and 9 mutants passed. The abstention itself IS asserted "
        "and is the product, which is why the test is worth keeping; where the surrogate starts trusting a "
        "fit is pinned by the literal 8 in test_threshold_boundaries.py, which needs scikit-learn and "
        "therefore skips on a machine without the surrogate extra."),
    "tests/test_truncation.py::test_the_agent_passes_the_tool_name_so_the_schema_can_be_used::_TOOL_CAP": (
        "equivalent_mutant",
        "the assertion is `'_truncate_tool_result(out, _TOOL_CAPS.get(tu.name, _TOOL_CAP), tu.name)' in "
        "inspect.getsource(agent.converse)` -- a check that the CALL SITE passes the tool name so the "
        "declared result schema can be looked up. The constant appears as a token inside that source "
        "string, which `_referenced_names` correctly counts as a reference, and no change to its value can "
        "alter the text of the call. Its value is pinned by "
        "`test_the_harness_caps_are_declared_per_tool_and_the_default_is_not_silently_raised`, which came "
        "back `detects_it` in this same sweep."),
    "tests/test_truncation.py::test_the_floor_is_the_projects_own_constant_not_a_new_one::MIN_GENERATIONS": (
        "equivalent_mutant",
        "the test asserts that `truncation.floor_refusal`'s source names `support.MIN_SEEDS` and "
        "`support.MIN_GENERATIONS` rather than declaring private copies, which is a property of the source "
        "text; both the 1 and 3 mutants passed, correctly. THE ASYMMETRY IS WORTH RECORDING: the same test "
        "then asserts `support.MIN_SEEDS == 2`, a literal, and that pair came back `detects_it` in this "
        "sweep -- so one of the two floors it is about is pinned to a number here and the other is only "
        "pinned to a name."),
}


@pytest.mark.skipif(not SELFREF.is_file(),
                    reason="selfref sweep absent; run `python scripts/mutate_thresholds.py selfref`")
def test_every_measured_blind_assertion_has_a_disposition():
    """Completeness over the sweep's own measurement. A candidate the discriminator could not make move is
    the finding; an undispositioned one is a hole in the finding rather than a hole in the suite -- the
    same rule `test_every_threshold_tier0_recorded_as_a_survivor_has_a_disposition` applies to Tier 0.

    FORCED by planting a test that asserts `_TOOL_CAP <= _TOOL_CAP` and re-running the sweep: the pair
    arrived with no disposition and this failed, naming it. Removed again afterwards.
    """
    art = json.loads(SELFREF.read_text(encoding="utf-8"))
    blind = sorted(k for k, v in art["candidates"].items() if v["verdict"] == "cannot_see_it_move")
    missing = sorted(set(blind) - set(SELFREF_DISPOSITIONS))
    assert not missing, f"measured `cannot_see_it_move` with no recorded disposition: {missing}"
    for key, (verdict, reason) in sorted(SELFREF_DISPOSITIONS.items()):
        assert verdict in _SELFREF_VERDICTS, f"{key}: unknown verdict {verdict!r}"
        assert len(reason) >= 80, f"{key}: a disposition needs a reason, got {reason!r}"
        rel, _sep, rest = key.partition("::")
        name, _sep2, _const = rest.partition("::")
        src = (REPO / rel).read_text(encoding="utf-8")
        assert f"def {name}(" in src, f"{key}: no such test any more"


@pytest.mark.skipif(not SELFREF.is_file(),
                    reason="selfref sweep absent; run `python scripts/mutate_thresholds.py selfref`")
def test_the_non_numeric_remainder_is_reported_UNMEASURED_and_never_as_reviewed():
    """The declared limit. Most candidates have no mutation operator -- their constant is a set, a dict, a
    tuple, a string, or an expression `thresholds()` never declares -- so the sweep asked them nothing.

    If that remainder were reported as anything but UNMEASURED it would manufacture exactly the false
    reassurance the static vacuity audit produced for the original seven: 2,092 assertions scored
    non-vacuous while seven of them could not see their own constant move. So: every candidate without a
    mutation operator carries `unmeasured` and a reason that says why, none of them is counted as
    reviewed, and both the class tally and the verdict tally partition the candidate total -- the
    summary-line defect the Tier 0 runner was repaired for, where four of five categories were printed
    and the fifth was left out of its own denominator.
    """
    art = json.loads(SELFREF.read_text(encoding="utf-8"))
    cands = art["candidates"]
    assert len(cands) == art["n_candidates"], (
        f"the artefact says {art['n_candidates']} candidates and carries {len(cands)}")
    assert sum(art["by_class"].values()) == art["n_candidates"], (
        f"the four classes {art['by_class']} do not partition {art['n_candidates']} candidates")
    assert sum(art["by_verdict"].values()) == art["n_candidates"], (
        f"the five verdicts {art['by_verdict']} do not partition {art['n_candidates']} candidates")

    unmutatable = {k: v for k, v in cands.items() if not v["threshold"]}
    assert unmutatable, "every candidate carries a mutation operator; this limit has nothing to declare"
    for key, row in sorted(unmutatable.items()):
        assert row["verdict"] == "unmeasured", (
            f"{key} has no mutation operator yet carries the verdict {row['verdict']!r}")
        assert "no mutation operator" in row["reason"], f"{key}: {row['reason']!r} does not say why"
        assert not row["runs"], f"{key}: reports {len(row['runs'])} mutant run(s) it cannot have made"
    reviewed = {k for k, v in cands.items() if v["verdict"] in ("detects_it", "cannot_see_it_move")}
    assert not (reviewed & set(unmutatable)), (
        f"candidates with no operator counted as measured: {sorted(reviewed & set(unmutatable))}")


@pytest.mark.skipif(not SELFREF.is_file(),
                    reason="selfref sweep absent; run `python scripts/mutate_thresholds.py selfref`")
def test_the_recorded_sweep_is_not_older_than_the_tests_it_classified():
    """A stale artefact is the decay this ledger exists to stop: the dispositions above are read against
    `data/mutation/selfref.json`, so a sweep recorded before a test file changed can report a pair that no
    longer exists and miss one that does. Compared against the test tree's own newest mtime rather than
    against a date in a comment, and reported as a SKIP-free failure so re-running the sweep is the fix.
    """
    art = json.loads(SELFREF.read_text(encoding="utf-8"))
    swept = time.strptime(art["generated_utc"], "%Y-%m-%dT%H:%M:%SZ")
    newest = max((REPO / "tests").glob("test_*.py"), key=lambda p: p.stat().st_mtime)
    assert time.mktime(swept) + time.timezone <= newest.stat().st_mtime + 86400.0 * 30, (
        f"the sweep was recorded {art['generated_utc']} and {newest.name} has moved since; re-run "
        f"`python scripts/mutate_thresholds.py selfref`")


def test_every_test_in_this_module_is_a_declared_part_of_the_ledger():
    """The four parts of this file are declared, so a new test has to join one of them rather than drift
    in unaccounted for -- the rule `test_threshold_boundaries.py` enforces with `META_TESTS`."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    own = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}
    declared = {
        "test_the_selfref_sweep_rediscovers_every_case_the_join_found",
        "test_the_classifier_separates_a_pinned_literal_from_a_bound_that_moves_with_its_constant",
        "test_the_per_test_discriminator_is_not_masked_by_a_sibling_test_and_reports_an_empty_run_as_unmeasured",
        "test_every_measured_blind_assertion_has_a_disposition",
        "test_the_non_numeric_remainder_is_reported_UNMEASURED_and_never_as_reviewed",
        "test_the_recorded_sweep_is_not_older_than_the_tests_it_classified",
        "test_every_test_in_this_module_is_a_declared_part_of_the_ledger",
    }
    assert own == declared, f"undeclared tests in the ledger module: {sorted(own ^ declared)}"
