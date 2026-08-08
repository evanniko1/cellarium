"""The elongation model is part of a run's IDENTITY, not a note about it.

Cellarium's model tree carries three elongation models. They answer different questions and cannot both be
right about the same run, and the thing that makes that dangerous rather than merely untidy is that they
disagree INVISIBLY: `GrowthLimits/fraction_trna_charged` is 86 columns wide under all three. Under
steady_state it is one per-amino-acid scalar broadcast across the family, so within-family spread is 0.00 as
an algebraic identity. Under kinetic those 86 are genuinely independent numbers. Under coarse_kinetic they
are 86 exact zeros, because that model does not solve charging at all. Same column name, same width, three
different quantities — so an analysis that pools two modes compares a measurement against an identity and
cannot tell.

These tests pin the three places that failure would actually happen: the command line (a design labelled
kinetic that runs the steady-state model), the output directory (wcEcoli rmtree's its output dir before every
run, so a shared directory is data DESTRUCTION, not mislabelling), and the dedup key (two arms collapsing to
one row, with `ts DESC` silently picking a winner).
"""

from __future__ import annotations

import pytest

from cellarium import capability, envelope, factors, manifest, runner
from cellarium.model import Design

_MODES = capability.ELONGATION_MODES


def _pair(**kw):
    """One design and its otherwise-identical kinetic twin — the contrast every test here is about."""
    d = Design(**kw)
    return d, d.model_copy(update={"elongation_model": "kinetic"})


# --- the design carries it, and refuses what it cannot express -------------------------------------------

def test_the_default_is_steady_state_so_every_historical_design_keeps_its_meaning():
    """Not a convenience. Every one of the ~300 design.json files on disk is validated back through this
    class by `runner._evacuate` and `manifest._design_from_dir`; without the default each would fail
    validation, `_evacuate` would report 'unreadable provenance', and `run_one` would RAISE rather than run."""
    assert Design().elongation_model == "steady_state"
    assert Design.model_validate_json('{"perturbation": "wildtype"}').elongation_model == "steady_state"


def test_an_unknown_elongation_model_is_refused_loudly_not_passed_through():
    """An unvalidated string reaches `_variant_args`, which maps modes to runSim flags. A typo would either
    die inside a container minutes in, or — worse — emit no flag and run the steady-state model under another
    model's name: the WELL-NOOP-1 pattern (a wild type wearing a knockout's label) on a new axis."""
    with pytest.raises(Exception) as e:
        Design(elongation_model="kinetic_trna_charging")     # a plausible near-miss, not gibberish
    assert "elongation_model" in str(e.value)
    # and the feasibility gate in front of run_one refuses it too, for a Design built around the validator
    d = Design.model_construct(perturbation="wildtype", params={}, condition=None, timeline=None,
                               seeds=1, generations=1, elongation_model="kinetic_trna_charging")
    v = envelope.check(d)
    assert v.in_envelope is False and "not a declared model" in v.reason


def test_the_field_round_trips_through_the_provenance_file():
    """`design.json` is written before the sim and read back by `_evacuate` / `_design_from_dir`; an axis that
    does not survive that round trip is an axis the reader re-derives, and every drift incident in this repo
    came from a reader re-deriving something."""
    _, k = _pair(perturbation="gene_knockout", condition="KO:argS", params={"variant_index": 644})
    assert Design.model_validate_json(k.model_dump_json()).elongation_model == "kinetic"


# --- the command line ------------------------------------------------------------------------------------

def test_a_steady_state_design_adds_nothing_to_the_command_line():
    """Byte-identical behaviour for every design that existed before this axis is the whole reason the
    default emits no flag. If this ever changes, ~300 runs stop being reproducible from their own record."""
    d, _ = _pair(perturbation="gene_knockout", condition="KO:argS", params={"variant_index": 644})
    args = runner._variant_args(d)
    assert args == ["--variant", "gene_knockout", "644", "644"]
    assert not [a for a in args if "kinetic" in a or "elongation" in a]


def test_a_kinetic_design_passes_the_kinetic_flag():
    d, k = _pair(perturbation="gene_knockout", condition="KO:argS", params={"variant_index": 644})
    args = runner._variant_args(k)
    assert "--kinetic-trna-charging" in args
    # the flag is APPENDED to the steady-state command line, so the variant/timeline args are untouched
    assert args[:len(runner._variant_args(d))] == runner._variant_args(d)


def test_exactly_one_elongation_flag_is_ever_emitted():
    """The two flags are mutually exclusive ALTERNATIVES, not modifiers. Passing both is accepted by argparse,
    `polypeptide_elongation.py` then silently picks kinetic, and `runSim.py` writes BOTH into metadata — which
    is why the mapping is a single string lookup and not a pair of bools that can disagree."""
    seen = {}
    for mode in _MODES:
        args = runner._elongation_args(Design(elongation_model=mode))
        assert len(args) <= 1, f"{mode} emitted {args}"
        seen[mode] = args
    assert seen["steady_state"] == []
    assert seen["kinetic"] == ["--kinetic-trna-charging"]
    assert seen["coarse_kinetic"] == ["--coarse-kinetic-elongation"]
    assert len({tuple(v) for v in seen.values()}) == len(_MODES), "two modes map to the same command line"


def test_a_multi_gene_knockout_also_carries_the_flag():
    """This branch returns EARLY from `_variant_args`, so it is the one place a new argument silently does not
    arrive. A multi-KO labelled kinetic that ran steady-state would look exactly like a real result."""
    k = Design(perturbation="multi_gene_knockout", condition="KO:pfkA+pfkB",
               params={"ko_indices": [1594, 1595]}, elongation_model="kinetic")
    assert "--kinetic-trna-charging" in runner._variant_args(k)


# --- the output directory: this one destroys data, it does not merely mislabel ----------------------------

def test_two_modes_of_one_design_never_share_an_output_directory():
    """wcEcoli does `shutil.rmtree(self._outputDir)` before every run (wholecell/sim/simulation.py:173-175),
    so a shared directory means the second run DELETES the first's simOut. `_evacuate` cannot save it: it
    reads the stranded design.json, recomputes `_run_subpath`, finds it equal, and lets the run proceed.

    A plain KO is the dangerous shape, and it is the one this test uses: it carries an explicit
    `variant_index` (so `_variant_index`'s content hash is short-circuited) and no timeline (so the old
    `_needs_distinct_dir` test was False too) — it bypassed every existing guard. That is the SCI-TRNA-4
    leu-arm race, which destroyed generation 0 of four seeds, reproduced on a new axis."""
    d, k = _pair(perturbation="gene_knockout", condition="KO:argS", params={"variant_index": 644})
    assert runner._run_subpath(d, 0, "cellarium") != runner._run_subpath(k, 0, "cellarium")


def test_every_pair_of_modes_gets_its_own_directory():
    roots = {m: runner._run_subpath(Design(perturbation="gene_knockout", condition="KO:argS",
                                           params={"variant_index": 644}, elongation_model=m), 0, "cellarium")
             for m in _MODES}
    assert len(set(roots.values())) == len(_MODES), roots


def test_a_run_directory_with_no_provenance_still_recovers_its_mode():
    """`_design_from_dir` falls back to parsing the variant directory when `design.json` is missing, and that
    fallback is the one place a kinetic run could be silently indexed as steady_state. Worse, unparsed it
    does not even fail cleanly: `gene_knockout_000644__elkinetic`.rpartition('_') yields 'elkinetic', and
    int() on that would take down `record_existing` for the whole campaign."""
    from pathlib import Path
    d, k = _pair(perturbation="gene_knockout", condition="KO:argS", params={"variant_index": 644})
    for design in (d, k):
        root = runner._run_subpath(design, 2, "cellarium")
        got, seed = manifest._design_from_dir(Path(root))
        assert seed == 2
        assert got.elongation_model == design.elongation_model, root
        assert got.params["variant_index"] == 644, root


def test_the_steady_state_run_path_is_unchanged_by_this_axis():
    """`_evacuate`, `_crash_row` and `reconcile_disk` all RECOMPUTE this path for runs already on disk, so a
    changed spelling would strand the entire existing corpus. Pinned literally, not against a recomputation."""
    d = Design(perturbation="gene_knockout", condition="KO:argS", params={"variant_index": 644},
               timeline="0 minimal_plus_amino_acids, 1200 minimal_aa_minus_arg")
    p = runner._run_subpath(d, 3, "cellarium")
    assert p.parent.name.startswith("gene_knockout_000644__tl") and "__el" not in p.parent.name
    assert p.name == "000003"
    plain = runner._run_subpath(Design(perturbation="wildtype", condition="basal"), 0, "cellarium")
    assert plain.parent.name == "wildtype_%06d" % runner._variant_index(Design(perturbation="wildtype",
                                                                              condition="basal"))


# --- the design tag, and therefore every analysis grouping ------------------------------------------------

def test_the_design_tag_names_the_mode_and_leaves_steady_state_alone():
    """The tag flows into `label` -> `survey.design_tag` -> every analysis grouping in the repo, plus the
    stored design_key, `count_runs`' prefix and the deterministic crash-row id. Steady-state tags must stay
    byte-identical or invariant D2 (stored design_key vs derived) breaks on ~300 historical rows."""
    d, k = _pair(perturbation="gene_knockout", condition="KO:argS", params={"variant_index": 644})
    assert manifest._design_tag(d) == "KO:argS"
    assert manifest._design_tag(k) == "KO:argS#elong:kinetic"
    assert manifest._design_tag(Design(perturbation="wildtype", condition="basal")) == "basal"


def test_the_tag_survives_the_label_parse_that_every_analysis_uses():
    """`survey.design_tag` re-derives the tag by parsing `label`, splitting on `·`/`/` and stripping the seed
    suffix. A separator that collided with any of those would put the two arms back in one design cell."""
    from cellarium import survey
    _, k = _pair(perturbation="gene_knockout", condition="KO:argS", params={"variant_index": 644})
    tag = manifest._design_tag(k)
    for label in (f"gene_knockout·{tag}·s0", f"gene_knockout/{tag} seed0"):   # both live conventions
        row = {"label": label, "perturbation": "gene_knockout", "condition": None}
        assert survey.design_tag(row) == tag
        assert survey.design_key(row) != "gene_knockout/KO:argS", "the two arms must not share a design key"


def test_the_axis_comes_back_as_its_own_field_not_folded_into_a_level():
    """Folding it into `base` or `level_raw` would corrupt the very fields `one_factor_neighbours` filters
    on — and that function is surfaced to the agent as THE control-selection primitive."""
    plain = factors.parse("ppgpp_conc/basal|ppGpp:0.6x")
    kin = factors.parse("ppgpp_conc/basal|ppGpp:0.6x#elong:kinetic")
    assert plain["elongation_model"] == "steady_state" and kin["elongation_model"] == "kinetic"
    for field in ("family", "base", "factor", "level_raw", "level_num"):
        assert plain[field] == kin[field], f"{field} was polluted by the elongation tag"


def test_a_steady_state_run_is_never_offered_as_the_control_for_a_kinetic_one():
    """`one_factor_neighbours` promises a neighbour differs 'in exactly one factor', which an agent reads as
    'exchangeable except for that factor'. Two runs under different elongation models are not exchangeable at
    all — the same column names carry different quantities."""
    keys = ["ppgpp_conc/basal|ppGpp:0.2x", "ppgpp_conc/basal|ppGpp:0.6x",
            "ppgpp_conc/basal|ppGpp:0.6x#elong:kinetic", "ppgpp_conc/basal|ppGpp:2.0x#elong:kinetic"]
    steady = factors.one_factor_neighbours("ppgpp_conc/basal|ppGpp:0.6x", keys)
    assert steady == ["ppgpp_conc/basal|ppGpp:0.2x"]
    kin = factors.one_factor_neighbours("ppgpp_conc/basal|ppGpp:0.6x#elong:kinetic", keys)
    assert kin == ["ppgpp_conc/basal|ppGpp:2.0x#elong:kinetic"]


def test_the_two_arms_are_not_aliases_of_one_experiment():
    """Without the mode in `canonical_id`, integrity check D4 does not merely miss the collision — it
    INVERTS, flagging the two arms as aliases wrongly counted as replicates and telling the operator to
    'merge them, do not treat as replicates'. The check would argue for the merge the axis exists to
    prevent."""
    a, b = "gene_knockout/KO:argS", "gene_knockout/KO:argS#elong:kinetic"
    assert factors.identity(a)["canonical_id"] != factors.identity(b)["canonical_id"]
    assert not factors.dedupe([a, b])["duplicates"]


# --- the dedup key: THE one that silently supersedes a whole arm ------------------------------------------

def test_the_dedup_key_separates_two_modes_of_one_design():
    """The load-bearing test.

    A SUCCESSFUL row's `id` is a uuid4, so successful runs never collide. The collision is in the CRASH row,
    whose id is DETERMINISTIC — `{perturbation}_{seed}_{sha256(perturbation|design_tag|seed)[:8]}_crash` — and
    whose path comes from `_run_subpath`. With the elongation model absent from both, a kinetic crash and a
    steady-state crash at the same design and seed produce an IDENTICAL id AND an identical path: one dedup
    key, and `ORDER BY ts DESC` silently supersedes one of them. That is not hypothetical for the first
    kinetic campaign, whose rows are the ones most likely to be crashes.

    Asserted on BOTH HALVES of the key, not just the key itself. `DEDUP_KEY` is the pair (id, normalised
    path); pinning only the composite would let someone narrow it to either half tomorrow and silently
    re-merge these two rows. Each half must separate them on its own.
    """
    d, k = _pair(perturbation="gene_knockout", condition="KO:argS", params={"variant_index": 644})
    assert d.model_dump(exclude={"elongation_model"}) == k.model_dump(exclude={"elongation_model"}), \
        "the two designs must differ in NOTHING but the elongation model, or this proves nothing"

    exc = RuntimeError("boom")
    row_s = manifest._crash_row(d, 0, 4, exc)
    row_k = manifest._crash_row(k, 0, 4, exc)

    assert row_s["id"] != row_k["id"], \
        "the deterministic crash id collides — narrowing DEDUP_KEY to `id` would merge the two arms"
    assert row_s["simout_path"] != row_k["simout_path"], \
        "the run paths collide — narrowing DEDUP_KEY to the path would merge the two arms"
    assert manifest.dedup_key_py(row_s) != manifest.dedup_key_py(row_k), \
        "one dedup key for two elongation models: `ts DESC` would silently supersede one arm"


def test_the_crash_row_says_which_model_was_attempted():
    """The no-data branch of `_crash_row` hand-writes its column dict instead of going through `_flat_row`,
    so a column added there does not appear on it — and these are the rows that MOST need to say which model
    was attempted. Left off, a kinetic failure lands NULL and the backfill then records it, permanently, as a
    steady-state failure."""
    d, k = _pair(perturbation="gene_knockout", condition="KO:argS", params={"variant_index": 644})
    assert manifest._crash_row(k, 0, 4, RuntimeError("boom"))["elongation_model"] == "kinetic"
    assert manifest._crash_row(d, 0, 4, RuntimeError("boom"))["elongation_model"] == "steady_state"


def test_a_crash_rows_label_also_carries_the_mode():
    """The crash row uses the `perturbation/tag seed{n}` label form, which `survey.design_tag` also
    recognises — so a crash row labelled without the mode would group a kinetic failure into the
    steady-state design cell."""
    _, k = _pair(perturbation="wildtype", condition="basal")
    assert manifest._label(k, 0) == "wildtype/basal#elong:kinetic seed0"
    assert manifest._label(Design(perturbation="wildtype", condition="basal"), 0) == "wildtype/basal seed0"


# --- the corpus reads as steady_state, and says so rather than guessing -----------------------------------

def test_charging_is_never_compared_across_two_elongation_models():
    """`selective_charging`'s default reference is `wildtype/basal`, which is steady_state. Pointed at a
    kinetic design it would divide 86 genuinely independent values by a broadcast identity and report the
    quotient as a per-family drop — a ratio of two different kinds of quantity, in the one tool most likely
    to be aimed at a kinetic run. It must refuse before reading anything."""
    from cellarium import trna
    res = trna.selective_charging("gene_knockout/KO:argS#elong:kinetic", "wildtype/basal")
    assert res.get("refused"), "a cross-mode charging comparison must refuse, not compute"
    assert res["worst_family"] is None and res["selectivity_gap_pp"] is None
    assert "kinetic" in res["refused"] and "steady_state" in res["refused"]


def test_every_corpus_row_reads_as_a_known_mode_and_never_as_null():
    """Design decision 4. NULL must never reach a consumer, because each would then decide for itself — the
    exact shape of the `division_rate` bug where `bool(None)` turned 'we did not measure whether this divided'
    into 'it did not divide' and produced three false IMPAIRED verdicts.

    RENAMED AND NARROWED 2026-08-08. This asserted every row reads as `steady_state`, which was true when
    written — Cellarium had no way to express any other choice — and is now FALSE BY DESIGN: the kinetic
    campaign this repository deliberately ran put 8 kinetic rows in the manifest. The invariant it was
    protecting is not "the corpus is single-mode"; it is that the field is never NULL and never a value no
    consumer can interpret. Keeping the old assertion would have made a successful, intended campaign look
    like corruption — and, worse, would pressure someone to relabel real kinetic rows as steady_state to get
    a green suite, which is the mislabelling this whole axis exists to prevent.
    """
    from cellarium import store
    rows = store.list_results()
    if not rows:
        pytest.skip("no corpus")
    null = [r["id"] for r in rows if r.get("elongation_model") in (None, "")]
    assert not null, f"{len(null)} rows carry NULL elongation_model: {null[:5]}"
    unknown = sorted({r.get("elongation_model") for r in rows} - set(capability.ELONGATION_MODES))
    assert not unknown, f"rows carry elongation model(s) no consumer can interpret: {unknown}"
    # And the declaration must match what is actually there — the guard against a campaign landing silently.
    present = sorted({r.get("elongation_model") for r in rows})
    assert set(present) <= set(capability.MODES_IN_CORPUS), (
        f"the corpus contains {present} but MODES_IN_CORPUS declares {list(capability.MODES_IN_CORPUS)} — "
        "a mode with runs that the registry does not know about makes every refusal quoting it a falsehood")


def test_the_registry_never_claims_a_corpus_mode_it_cannot_verify():
    """MODES_IN_CORPUS is the one declaration a ROUTINE action — running a campaign — invalidates without
    anyone touching capability.py, so it is probed. The two rot directions are not symmetric: a declared mode
    with no runs behind it green-lights an unanswerable question and must FAIL; an undeclared mode that has
    runs only over-refuses and is a warning. And an unreadable manifest must report UNVERIFIED rather than
    fall back to assuming steady-state-only, which would be a 'could not read' reported as a fact."""
    res = capability.probe_corpus_modes()
    assert res["ok"], res
    if res["verified"]:
        assert not res["declared_modes_with_no_runs"]
    else:
        assert res["note"].startswith("UNVERIFIED"), res["note"]
