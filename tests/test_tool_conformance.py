"""Every tool, swept for the four bug families the option-A discovery leg exposed (src/cellarium/conformance.py).

WHY A SWEEP AND NOT MORE CASES. The eleven faults of 2026-10-27 were found one at a time, by reading a transcript
after a blind run had already failed. Each had its own test afterwards, which pins that tool and says nothing
about the next one. These tests ask the same four questions of EVERY read-only tool at once, so the next tool to
acquire one of these faults fails here instead of inside an investigation:

  1. ABSENCE   — an unreadable source answers with an error, never with an empty success.
  2. SHAPE     — whatever the size, the agent receives valid JSON, and anything dropped is named.
  3. DETERMINISM — two identical calls agree, and reordering the rows changes nothing.
  4. CONTEXT   — the answer does not depend on the process's working directory.
  5. CONTRACT  — a refusal names its KIND: a reason from a closed registry, and an `about` that separates
                 "the corpus does not contain this" from "this machine could not look".
  6. SELECTION — no two tool names are confusable without each saying when to use the other.

The sweeps run against whatever store the checkout has; with no corpus they skip rather than pass vacuously.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cellarium import agent, conformance, errors, raw, reconcile, survey, tools  # noqa: E402


@pytest.fixture(scope="module")
def calls() -> dict:
    rows, _ = survey.analysis_rows()
    keys = sorted({survey.design_key(r) for r in rows})
    if not keys:
        pytest.skip("no reportable designs in this checkout, so the sweeps have nothing to call")
    # PREFER A DESIGN WHOSE RAW SIMOUT IS ON THIS MACHINE. The first knockout in sort order is
    # `gene_knockout/KO:alaS`, one of the 17 designs whose seed directories WELL-PRUNE-2 moved to HuggingFace --
    # so every raw-reading tool answered "no local raw" for the BASELINE call and the sweeps below were quietly
    # probing the absent-data path instead of the present-data one. Measured 2026-10-29 while adding the
    # finer-grained absence sweeps: 23 of the corpus's 40 designs have local raw, and the fixture was choosing
    # from the other 17.
    # The CHEAPEST raw-backed design: one local seed exercises the present-data path, and the sweeps below call
    # each tool up to three times, so extra seeds buy nothing and cost minutes.
    local = dict((k, n) for n, k in conformance.raw_backed_designs())
    backed_ko = sorted((n, k) for k, n in local.items() if "/KO:" in k)
    ko = (backed_ko[0][1] if backed_ko
          else next((k for k in keys if "/KO:" in k), keys[0]))
    ref = next((k for k in keys if k != ko and "KO:" not in k), "wildtype/basal")
    rid = next((r.get("id") for r in rows if survey.design_key(r) == ko), None)
    gene = ko.split("KO:")[-1].split("+")[0].split("#")[0] if "KO:" in ko else "pfkA"
    return conformance.sample_args(ko, ref, rid, gene)


@pytest.fixture(scope="module")
def recording_design() -> str:
    """A design with local raw simOut that actually records `growth_rate`.

    Module-scoped because finding it reads trajectories off disk, and three tests below need the same one."""
    for _n, key in sorted(conformance.raw_backed_designs()):   # fewest seeds first: cheapest probe that works
        runs = raw.seed_runs(key)
        if runs and raw.seed_channel(runs[0]["root"], "growth_rate")[0].size:
            return key
    pytest.skip("no design in this checkout has local raw that records growth_rate")


@pytest.fixture(scope="module")
def fine_absence(calls) -> list:
    """The run- and channel-grain sweep, run ONCE for the whole module: it calls every measurement tool three
    times, so it is the most expensive sweep here."""
    local = dict((k, n) for n, k in conformance.raw_backed_designs())
    backed_ko = sorted((n, k) for k, n in local.items() if "/KO:" in k)
    design = backed_ko[0][1] if backed_ko else next(iter(local), None)
    if design is None:
        pytest.skip("no design in this checkout has raw simOut locally")
    return conformance.fine_absence_sweep(calls, design=design)


def test_the_sweep_actually_calls_a_broad_set_of_tools(calls):
    """A sweep that silently covers three tools would pass forever. This pins the coverage it claims."""
    assert len(calls) >= 40, f"only {len(calls)} tools got a sample call: {sorted(calls)}"
    for name in ("survey_corpus", "list_results", "viability", "differential", "manipulation_check"):
        assert name in calls, f"{name} has no sample call, so no sweep covers it"


# ---- 2. SHAPE ------------------------------------------------------------------------------------------------

def test_no_tool_result_reaches_the_agent_as_a_severed_string(calls):
    """The failure this prevents: survey_corpus at 43k characters against a 6k cap, cut mid-string after 2 of its
    24 channels, leaving `…[truncated]` and no record of what went (discovery leg v4)."""
    bad = [r for r in conformance.budget_sweep(calls) if r["string_cut"] or not r["valid_json"]]
    assert not bad, ("these tools are cut mid-string instead of trimmed structurally: "
                     + json.dumps(bad, indent=1))


def test_a_trimmed_result_names_what_it_dropped(calls):
    """A trim is allowed; a silent one is not. Every trimmed payload must carry its omission record."""
    for r in conformance.budget_sweep(calls):
        if not r["trimmed"]:
            continue
        out = conformance.call(r["tool"], calls[r["tool"]])
        seen = json.loads(agent._truncate_tool_result(out, r["cap"], r["tool"]))
        assert any(k in seen for k in ("_omitted", "_truncated", "truncation")) or seen.get("refusal"), (
            f"{r['tool']} was trimmed from {r['raw']} to {r['seen']} characters without naming the omission")


# ---- 1. ABSENCE ----------------------------------------------------------------------------------------------

def test_an_unreadable_source_is_an_error_not_an_empty_answer(calls):
    """With no manifest and no caches, a corpus tool must say it could not read, not report nothing found.

    This is the shape that made an agent conclude a working knockout never happened: an empty gene map read as
    `INVALID`, and `list_results` returning `n=0` where its own description says 0 means genuinely absent."""
    with tempfile.TemporaryDirectory() as tmp:
        rows = conformance.absence_sweep(calls, Path(tmp))
    assert rows, "the absence sweep called nothing"
    bad = [r for r in rows if r["empty_success"]]
    assert not bad, "these tools answered an unreadable source with an empty success: " + json.dumps(bad, indent=1)


def test_the_absence_sweep_is_scoped_to_the_tools_that_read_the_corpus(calls):
    """The scope is the measurement registry, so the sweep cannot be quietly narrowed to nothing."""
    swept = {r["tool"] for r in conformance.absence_sweep(calls, Path(tempfile.gettempdir()))}
    assert swept <= set(reconcile.MEASUREMENT_TOOLS)
    assert len(swept) >= 25, f"only {len(swept)} corpus-reading tools were swept"


def test_a_description_may_claim_absence_only_where_the_tool_earns_it():
    """`n=0 means genuinely absent` is a promise the tool has to keep when its source is unreadable."""
    unearned = [c for c in conformance.description_claims() if not c.get("earned")]
    assert not unearned, ("these descriptions tell the agent to read nothing as absence, with no entry in "
                          "EARNED_ABSENCE_CLAIMS saying why that holds: " + json.dumps(unearned, indent=1))


# ---- 3. DETERMINISM ------------------------------------------------------------------------------------------

def test_two_identical_calls_give_the_same_answer(calls):
    rows = conformance.determinism_sweep(calls)
    bad = [r for r in rows if not r["repeat_equal"]]
    assert not bad, "these tools answered differently when asked twice: " + json.dumps(bad, indent=1)


def test_reordering_the_rows_changes_no_answer(calls):
    """Rows arrive from a parallel parquet scan in no fixed order. A tie broken by that order made the default
    comparability arm flip between two calls, so a design was reachable and then "in another arm" (v1)."""
    rows = conformance.determinism_sweep(calls)
    bad = [r for r in rows if not r["order_invariant"]]
    assert not bad, "these tools depend on the order their rows arrive in: " + json.dumps(bad, indent=1)


# ---- 4. CONTEXT ----------------------------------------------------------------------------------------------

def test_the_model_caches_do_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    """The caches describe the MODEL, so they resolve from the checkout. Read relative to the working directory,
    they came back empty from an isolated store and every knockout was labelled INVALID."""
    from cellarium import factors, paths
    before = len(factors._scope())
    monkeypatch.chdir(tmp_path)
    factors._SCOPE = None
    assert len(factors._scope()) == before > 0
    assert paths.CACHE_DIR.is_absolute()


# ---- the near-miss: a declaration is not evidence --------------------------------------------------------------

def test_a_column_declared_unwritten_but_carrying_data_is_still_a_measurement(tmp_path):
    """The fix for "unwritten columns read as 0.0" was first written to trust the listener's own declaration.

    The declaration is wrong in this corpus: the steady-state runs list `ppgpp_conc` in `unwritten_columns`
    while that column carries a real 49.15 µM at every timestep. Trusting it deleted a measured channel from all
    24 runs of a store — the same error as reporting the zeros, in the other direction. Both conditions are
    required: declared unwritten AND no data.
    """
    import numpy as np
    so = tmp_path / "simOut"
    (so / "GrowthLimits").mkdir(parents=True)
    (so / "GrowthLimits" / "attributes.json").write_text(
        json.dumps({"unwritten_columns": ["ppgpp_conc", "rela_conc"]}), encoding="utf-8")
    assert raw.unwritten(str(so), "GrowthLimits") == {"ppgpp_conc", "rela_conc"}
    # declared unwritten AND all zero -> not recorded
    assert raw.not_recorded(str(so), "GrowthLimits", "ppgpp_conc", np.zeros(100))
    # declared unwritten BUT carrying data -> a measurement, kept
    assert not raw.not_recorded(str(so), "GrowthLimits", "ppgpp_conc", np.full(100, 49.15))
    # not declared -> kept, even when it is all zero
    assert not raw.not_recorded(str(so), "GrowthLimits", "growth_rate", np.zeros(100))
    # declared but empty -> no evidence either way, so kept
    assert not raw.not_recorded(str(so), "GrowthLimits", "ppgpp_conc", np.zeros(0))


def test_a_channel_that_was_never_recorded_is_absent_from_the_record_not_zero():
    """`build_record` must leave an unrecorded channel OUT of `channels` (so it lands NULL) and say so in the
    note. A 0.0 there reads as a measurement: the survey reported 0.0 ± 0.0 for ppGpp on a dividing cell."""
    from cellarium import manifest
    from cellarium.model import Design
    captured = {}

    class _Reader:
        @staticmethod
        def read_run(_root):
            return {"channels": {"growth_rate": 0.0003, "ppgpp_conc": None, "rela_conc": None},
                    "generations": [], "channel_stats": {}, "series": {}, "media_segments": []}

    import unittest.mock as mock
    with mock.patch.object(manifest, "reader", _Reader):
        rec = manifest.build_record(Path("."), Design(perturbation="wildtype", condition="basal"), 0)
    captured["channels"] = rec.channels
    assert "ppgpp_conc" not in rec.channels and "rela_conc" not in rec.channels
    assert rec.channels["growth_rate"] == 0.0003
    assert "not recorded by this run: ppgpp_conc, rela_conc" in rec.note


def test_the_harness_caps_are_declared_per_tool_and_the_default_is_not_silently_raised():
    """The caps are a context-budget decision, so they are visible and bounded rather than tuned per incident."""
    assert agent._TOOL_CAP == 6000
    assert set(agent._TOOL_CAPS) == {"survey_corpus", "model_capabilities"}
    assert all(6000 < v <= 25000 for v in agent._TOOL_CAPS.values()), agent._TOOL_CAPS


def test_every_tool_with_a_raised_cap_still_fits_it(calls):
    """A raised cap is only useful if the tool's own payload budget stays under it."""
    for name, cap in agent._TOOL_CAPS.items():
        if name not in calls:
            continue
        out = conformance.call(name, calls[name])
        assert len(json.dumps(out, default=str)) <= cap, (
            f"{name} produces more than its own cap of {cap}; raise the cap deliberately or shrink the payload")


def test_the_tools_excluded_from_the_sweeps_are_named_and_justified():
    """An exclusion list is how a sweep stops testing things. It is pinned so growth is a decision."""
    assert conformance.SIDE_EFFECT_OR_EXTERNAL <= set(tools._DISPATCH)
    assert conformance.HEAVY <= set(tools._DISPATCH)
    assert conformance.ENVIRONMENT_PROBES <= set(tools._DISPATCH)
    overlap = conformance.HEAVY & conformance.SIDE_EFFECT_OR_EXTERNAL
    assert not overlap, f"a tool is in two exclusion lists: {overlap}"


# ---- 5. CONTRACT -----------------------------------------------------------------------------------------

def test_every_registered_reason_declares_whose_fault_it_is():
    """`about` is the field the discovery leg needed and did not have. A reason without it is useless, and a
    value outside the four kinds cannot be branched on."""
    assert set(errors.REASONS) >= {"store_unreadable", "no_local_raw", "unknown_design", "insufficient_data"}
    for reason, (about, nxt) in errors.REASONS.items():
        assert about in ("request", "corpus", "environment", "policy"), (reason, about)
        assert nxt and isinstance(nxt, str), reason


def test_an_unreadable_store_and_a_missing_design_do_not_share_a_cause():
    """The whole point: one is evidence about the corpus, the other is a fault in this machine. If these two
    ever collapse to the same `about`, the agent is back to reading prose."""
    assert errors.REASONS["unknown_design"][0] == "request"
    assert errors.REASONS["insufficient_data"][0] == "corpus"
    assert errors.REASONS["store_unreadable"][0] == "environment"
    assert errors.REASONS["no_local_raw"][0] == "environment"


def test_a_raised_exception_classifies_as_a_runtime_fault_not_as_corpus_evidence():
    """The four `f"{type(exc).__name__}: {exc}"` sites carry no words to classify statically, so their
    classification is pinned here instead of assumed by the static audit."""
    for msg in ("ValueError: boom", "KeyError: 'x'", "OSError: disk gone", "RuntimeError: nope"):
        assert errors.classify(msg) == "runtime_fault", msg
        assert errors.REASONS[errors.classify(msg)][0] == "environment"


def test_fail_refuses_an_unregistered_reason():
    """A free-text reason would reopen the prose problem one tool at a time."""
    with pytest.raises(KeyError):
        errors.fail("something_new", "a message")


def test_annotate_keeps_a_reason_a_tool_set_itself_and_does_not_touch_a_success():
    assert errors.annotate({"n": 3}) == {"n": 3}
    assert errors.annotate("not a dict") == "not a dict"
    kept = errors.annotate({"error": "corpus unreadable", "reason": "store_unreadable"})
    assert kept["reason"] == "store_unreadable" and kept["about"] == "environment"
    # prose in `reason` is preserved rather than dropped, and the code is classified from the message
    moved = errors.annotate({"error": "'x' is not a design in the corpus", "reason": "because I said so"})
    assert moved["reason"] == "unknown_design" and moved["reason_note"] == "because I said so"


def test_every_error_message_in_the_package_is_classifiable():
    """The ratchet. The taxonomy is applied at one boundary rather than written into 223 call sites, so it can
    only stay complete if an unregistered message fails here."""
    unreg = [r for r in conformance.unregistered_messages() if not r["dynamic"]]
    assert not unreg, "error messages that errors.PATTERNS cannot name: " + json.dumps(unreg, indent=1)


def test_no_tool_refuses_without_a_reason_or_answers_an_unresolvable_argument_silently(calls):
    """Family 5 over every read-only tool: an unresolvable value for every argument it accepts. Either it
    refuses with a registered reason, or it answers and says the input was not recognised."""
    rows = conformance.contract_sweep()
    assert rows, "no tool was swept"
    failures = [r for r in rows if r["verdict"] == "fail"
                or (r["verdict"] == "answered" and not r["marks_unknown_input"])]
    assert not failures, json.dumps(failures, indent=1, default=str)


def test_the_dispatch_boundary_is_where_the_contract_is_applied():
    """If the annotate call leaves dispatch, every error loses its reason at once and nothing else fails."""
    out = tools.dispatch("__no_such_tool__", {})
    assert out["reason"] == "unknown_tool" and out["about"] == "request"
    out = tools.dispatch("list_results", {"__no_such_arg__": 1})
    assert out["reason"] == "bad_argument" and out["about"] == "request"


def test_an_exact_match_filter_with_an_unknown_value_is_an_argument_error_not_a_count_of_zero():
    """`list_results(perturbation=...)` is an exact match on a closed set, and its own docstring tells the agent
    that n=0 means genuinely absent. An unknown value can only ever give 0, so it has to be an error."""
    out = tools.dispatch("list_results", {"perturbation": "__no_such_perturbation__"})
    assert "error" in out and out["reason"] == "bad_argument"
    assert out.get("did_you_mean"), "an argument error should carry the values that would work"
    assert out.get("n") is None, "it must not also report a count that reads as absence"


# ---- 6. SELECTION ----------------------------------------------------------------------------------------

def test_every_confusable_pair_of_tool_names_says_when_to_use_the_other():
    """TRAJECT-Bench's "similar tool confusion": with 73 tools the model reads names before descriptions, so two
    tools sharing half their name tokens must each say what the other is for. Found `fba_gene_knockout` against
    `fba_gene_deletion` — per-gene against all-at-once, nothing in either description to tell them apart."""
    pairs = conformance.confusable_pairs()
    assert pairs, "the measurement returned nothing; the name-overlap threshold or the tool list changed"
    silent = [p for p in pairs if not p["cross_referenced"]]
    assert not silent, "confusable tool names with no cross-reference: " + json.dumps(silent, indent=1)


def test_a_numeric_error_field_is_a_statistic_and_is_left_alone():
    """Several payloads carry `error` as a number — a standard error, a residual. Classifying one would attach a
    cause to a measurement, which is the inverse of what this module is for."""
    assert errors.annotate({"error": 0.023, "fit": "ok"}) == {"error": 0.023, "fit": "ok"}


def test_no_registered_reason_is_dead():
    """A reason nothing can produce is a taxonomy that looks more complete than it is. Each one has to be
    reachable: named by a pattern, or passed to `errors.fail` somewhere in the package. (It caught
    `unknown_channel`, which read well and no message ever produced — the channel cases are either a bad
    argument or a column the corpus does not carry.)"""
    import ast

    src = Path(ROOT / "src" / "cellarium")
    used = {r for _, r in errors.PATTERNS}
    # Read the FIRST ARGUMENT of every errors.fail call from the syntax tree. The literal search this used to
    # do -- `f'fail("{reason}"' in calls` -- only matched a call written on one line, so the newly added
    # `shift_time_not_declared` read as unreachable while being raised four lines further down. One fact
    # ("which reasons can be produced"), several textual forms, and the check read one of them: family 9, in
    # the test suite.
    for f in sorted(src.glob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            if (getattr(node.func, "attr", None) or getattr(node.func, "id", None)) != "fail":
                continue
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                used.add(node.args[0].value)
    for reason in errors.REASONS:
        if reason == "unclassified":            # the fallback; produced by classify(), not by a pattern
            continue
        assert reason in used, f"{reason} is registered and unreachable"


# ---- 7. AGREEMENT ----------------------------------------------------------------------------------------

def test_every_view_of_what_can_be_run_agrees_with_the_envelope():
    """Three views answered "what can be run" and all three disagreed, while families 1-6 passed on each: every
    answer was complete, deterministic, correctly shaped and correct in isolation. `design_space` omitted
    `graded_gene_knockout` (22 corpus rows, its own variant module and capability record) and offered two levers
    `check_feasibility` refuses."""
    rows = conformance.enumeration_agreement()
    assert rows, "no capability views were compared"
    bad = [r for r in rows if not r["agrees"]]
    assert not bad, json.dumps(bad, indent=1)


def test_a_view_may_differ_from_the_envelope_only_by_declaring_it():
    """The two metabolism objective levers are deliberately outside the envelope — `generate.py` records that arm
    as untested and the question as open work. The rule is not that the lists are identical, it is that a
    difference is declared; so `design_space` must still name them, under a key that says they are out."""
    from cellarium import envelope
    space = tools.dispatch("design_space", {})
    declared = space.get("not_in_envelope") or {}
    assert "metabolism_kinetic_objective_weight" in declared and "metabolism_secretion_penalty" in declared
    assert not (set(declared) & set(envelope.VALIDATED_PERTURBATIONS)), "a lever cannot be both in and out"


def test_a_conditionally_recorded_channel_says_so_where_it_is_advertised():
    """The capability view listed ppGpp, RelA and ribosome concentration unconditionally, and under kinetic
    charging none of them is written — which is how a run came to call a never-recorded column non-physical."""
    bad = [r for r in conformance.channels_declare_when_they_are_recorded() if not r["ok"]]
    assert not bad, json.dumps(bad, indent=1)


# ---- 8. DECLARED SETS ------------------------------------------------------------------------------------

def test_a_closed_value_set_is_declared_as_an_enum_not_as_a_free_string():
    """OpenAI's function-calling rule: if the values are enumerable, do not use a free-form string. Measured
    before this change, 15 of 123 string parameters carried an enum and six `channel` parameters had no
    description at all, so the model was asked to guess a member of an 11-value namespace from nothing."""
    from cellarium import instrument
    declared = set(instrument.channel_names())
    checked = 0
    for spec in tools.TOOLS:
        for param, meta in ((spec.get("input_schema") or {}).get("properties") or {}).items():
            if (spec["name"], param) not in tools._CHANNEL_PARAMS:
                continue
            checked += 1
            assert set(meta.get("enum") or []) == declared, f"{spec['name']}.{param} does not declare the namespace"
            assert meta.get("description"), f"{spec['name']}.{param} has no description"
    assert checked == len(tools._CHANNEL_PARAMS)


def test_a_narrower_enum_a_tool_set_itself_is_not_overwritten():
    """`trajectory` and `compare_at_generation` take only the two per-generation channels. Broadening them to the
    whole namespace would be an enum that lies in the other direction."""
    from cellarium import instrument
    for name in ("trajectory", "compare_at_generation"):
        spec = next(t for t in tools.TOOLS if t["name"] == name)
        enum = set((spec["input_schema"]["properties"]["channel"].get("enum")) or [])
        assert enum and enum < set(instrument.channel_names()), f"{name} lost its narrower channel set"


def test_no_declared_enum_value_is_rejected_by_its_own_tool(calls):
    """An enum narrower than reality silently forbids valid calls, and the agent cannot tell that from a real
    refusal. So every declared value is called. This caught `chart`, whose schema had no `required` list at all
    while the tool refuses any call naming no run."""
    rows = conformance.enum_honesty(calls)
    assert rows, "no enum was exercised"
    failures = [r for r in rows if r["verdict"] == "fail"]
    assert not failures, json.dumps(failures, indent=1)


def test_a_one_of_requirement_is_expressed_in_the_schema():
    """`chart` needs a result_id, a results list or a design label, and `required` cannot say "one of these"."""
    spec = next(t for t in tools.TOOLS if t["name"] == "chart")
    branches = [set(b.get("required") or []) for b in (spec["input_schema"].get("anyOf") or [])]
    assert {"result_id"} in branches and {"results"} in branches and {"design"} in branches


def test_every_string_parameter_says_what_it_means():
    """39 string parameters carried no description at all (measured 2026-10-28), and the same names WERE
    described on other tools — so what the model knew about `reference` depended on which tool it reached for.
    The glossary in tools.py fills them from one place; this is the check that keeps it true."""
    rows = conformance.every_string_parameter_says_what_it_means()
    bare = [f"{r['tool']}.{r['param']}" for r in rows if not r["ok"]]
    assert rows, "no string parameter was inspected"
    assert not bare, f"string parameters with no description: {bare}"


def test_the_glossary_only_speaks_where_one_sentence_can_be_true():
    """One sentence keyed by a parameter NAME is only safe while every site it reached means the same thing.
    `kind` is a species class on three tools and a chart type on `chart`; the glossary must not have reached
    both. A future bare `kind` on a chart-like tool has to fail here."""
    rows = conformance.glossary_sites_agree()
    assert rows, "the glossary reached no site"
    bad = [r for r in rows if not r["ok"]]
    assert not bad, json.dumps(bad, indent=1)


def test_a_site_whose_meaning_differs_writes_its_own_sentence():
    """read_series resolves a design label through `_resolve_result`; list_species/read_species go straight to a
    run path and a label is simply not found. The difference is DECLARED rather than smoothed over, because
    making the species tools resolve labels would silently pick a representative seed."""
    for name in ("list_species", "read_species"):
        spec = next(t for t in tools.TOOLS if t["name"] == name)
        text = spec["input_schema"]["properties"]["result_id"]["description"]
        assert "does NOT accept a design label" in text, f"{name} no longer declares the difference"
    read_series = next(t for t in tools.TOOLS if t["name"] == "read_series")
    assert "resolves here" in read_series["input_schema"]["properties"]["result_id"]["description"]


def test_a_description_a_tool_wrote_itself_is_never_overwritten():
    """The filler writes only into an EMPTY description. `chart.kind` already says what a chart kind is."""
    spec = next(t for t in tools.TOOLS if t["name"] == "chart")
    assert "line = trajectory over time" in spec["input_schema"]["properties"]["kind"]["description"]
    assert "chart" not in [t for t, _ in tools.glossary_sites().get("kind", [])]


# ---- 9. ONE FACT, ONE RESOLVER --------------------------------------------------------------------------------

def test_a_fact_with_several_homes_has_exactly_one_reader():
    """The last open item of the discovery-leg audit was `shift_response` reading ONE of the places a shift time
    can live and reporting that as a fact about the design. Families 1-8 cannot see it: the answer was complete,
    deterministic, correctly shaped, carried a registered reason and came from an honest value set, and the
    question had been asked of the wrong field."""
    rows = conformance.one_fact_one_resolver()
    assert rows, "no fact is registered"
    bad = [r for r in rows if not r["ok"]]
    assert not bad, json.dumps(bad, indent=1)


def test_each_resolver_answers_from_every_place_its_fact_can_live():
    """A resolver that exists but reads one place is the original defect with an extra function in front of it."""
    rows = conformance.a_resolver_reads_every_place_a_fact_can_live()
    assert len(rows) >= 8
    assert all(r["ok"] for r in rows), json.dumps([r for r in rows if not r["ok"]], indent=1)


def test_the_knockout_resolver_does_not_read_an_rrna_dose_as_a_gene():
    """`rrna_operon_knockout/minimal|rRNA_KO:4op` is a real corpus design, and the first version of the resolver
    returned `['4op']` for it — the fault this family exists to catch, in the family's own resolver. The marker
    must begin a segment."""
    from cellarium import model
    assert model.knockout_genes("rrna_operon_knockout/minimal|rRNA_KO:4op") == []
    assert model.knockout_genes("multi_gene_knockout/KO:gltX+relA+spoT") == ["gltX", "relA", "spoT"]


def test_no_corpus_design_changes_its_knockout_reading():
    """Measured: 40 of the corpus's designs resolve to a non-empty gene list, and none of them is an rRNA dose."""
    from cellarium import model, store, survey
    keys = sorted({survey.design_key(r) for r in store.list_results()})
    ko = [k for k in keys if model.knockout_genes(k)]
    assert len(ko) == 40, f"the knockout reading moved: {len(ko)} designs"
    assert not [k for k in ko if "rRNA" in k]


def test_shift_response_names_where_the_shift_time_came_from():
    """A time read out of a label is weaker evidence than one declared in a timeline, so the answer says which."""
    from cellarium import dynamics
    assert dynamics.shift_sources("d", {"timeline": "0 minimal, 1200 minimal_plus_amino_acids"})[0] == \
        (1200.0, "the design's declared timeline")
    assert dynamics.shift_sources("d", {"condition": "with_aa_then_minus_LEU_at_600s"})[0][1].startswith("a time")
    assert dynamics.shift_sources("d", {}, at_seconds=900)[0] == (900.0, "the caller's at_seconds")


def test_shift_response_refuses_with_a_caller_side_remedy_not_a_claim_about_the_design():
    """It used to say "'X' declares no nutrient shift", which is a limit of the tool stated as a fact about the
    design. It is a `request` fault now, with the argument that fixes it."""
    out = tools.dispatch("shift_response", {"design": "wildtype/basal"})
    assert out["reason"] == "shift_time_not_declared"
    assert out["about"] == "request"
    assert "at_seconds" in out["pass_instead"]
    assert out["looked_in"] == ["timeline", "condition", "label"]


def test_a_timeline_design_still_resolves_exactly_as_before():
    out = tools.dispatch("shift_response",
                         {"design": "timeline/0 minimal, 1200 minimal_plus_amino_acids"})
    assert out.get("declared_shift_s") == 1200.0
    assert out.get("shift_time_from") == "the design's declared timeline"


def test_an_absent_trajectory_still_reports_the_shift_time_it_resolved(monkeypatch):
    """The machine not holding the trajectory must not erase a fact the tool already established.

    This is the failure CI found and the local suite could not: on a runner with no raw simOut, the answer
    above came back with no `declared_shift_s` at all, so "this design declares no shift" and "this machine
    has no data for it" were again indistinguishable to the reader. The refusal now carries the resolution."""
    from cellarium import dynamics
    monkeypatch.setattr(dynamics.raw, "seed_runs", lambda design: [])
    out = tools.dispatch("shift_response",
                         {"design": "timeline/0 minimal, 1200 minimal_plus_amino_acids"})
    assert out["about"] == "environment", out            # not corpus: nothing here is evidence about the model
    assert out["declared_shift_s"] == 1200.0
    assert out["shift_time_from"] == "the design's declared timeline"


# ---- 1b. ABSENCE AT THE RUN AND CHANNEL GRAIN -----------------------------------------------------------------
#
# Family 1 takes the whole store away. These take away one run, and then one column of a run that is present --
# the two absences that actually occur in this corpus, and the grain at which continuous integration found a
# defect the local suite could not reach (`shift_response` dropping a shift time it had already resolved).

def test_the_forced_absences_are_faithful_to_the_real_conditions(recording_design):
    """The contexts must reproduce what the machine really does, or every verdict below is about a fiction.

    Run grain: `_seed_root` is the predicate the real condition turns on, so `seed_runs` must come back empty
    through its own logic. Channel grain: `_col_1d` answers all-NaN for a column `not_recorded` marks, and
    `seed_channel` filters non-finite values, so a forced-unwritten channel must yield an empty series while
    every other channel keeps its own."""
    design = recording_design
    runs = raw.seed_runs(design)
    assert runs, design
    with conformance._no_local_runs():
        assert raw.seed_runs(design) == []
    assert raw.seed_runs(design), "the context did not restore seed_runs"

    root = runs[0]["root"]
    t_before, _v = raw.seed_channel(root, "growth_rate")
    if not t_before.size:
        pytest.skip(f"{design} does not record growth_rate, so it cannot be blinded")
    with conformance._unwritten_channel("growth_rate"):
        t_blind, _ = raw.seed_channel(root, "growth_rate")
        t_other, _ = raw.seed_channel(root, "fba_objective")
    assert t_blind.size == 0, "a forced-unwritten channel still returned a series"
    assert t_other.size, "blinding one channel also blinded another"
    assert raw.seed_channel(root, "growth_rate")[0].size == t_before.size, "the context did not restore _col_1d"


def test_a_sweep_with_no_data_to_remove_reports_that_rather_than_passing(calls):
    """An unexercised sweep reported as a pass is the same defect as an unread store reported as a finding.

    This is how the sweep's own first run misled me: the probe was a design whose seed directories had been
    pruned, 34 of 36 tools answered identically before and after, and the result read as clean."""
    absent = next((k for _n, k in [(0, d) for d in
                                   sorted({survey.design_key(r) for r in survey.analysis_rows()[0]})]
                   if not raw.seed_runs(k)), None)
    if absent is None:
        pytest.skip("every design in this checkout has local raw, so there is no probe without a baseline")
    rows = conformance.fine_absence_sweep(calls, design=absent)
    assert rows and all(r["verdict"] == "no_baseline" for r in rows), (absent, rows[:3])
    assert all(r["n_baseline_seeds"] == 0 for r in rows)


def test_an_absent_run_or_an_unwritten_column_is_never_an_empty_success(fine_absence):
    """The family-1 criterion, one and two grains finer."""
    bad = [r for r in fine_absence if r.get("empty_success")]
    assert not bad, ("these tools answered an absent run or an unwritten column with a well-formed empty "
                     "success: " + json.dumps(bad, indent=1))


def test_a_refusal_blames_the_grain_that_is_actually_missing(fine_absence):
    """An absent run directory is `environment`; an unwritten listener column is `corpus`.

    Not cosmetic. `environment` tells the agent this machine could not look, which invites a re-download that
    cannot help when the data is already here; `corpus` tells it to ask for another channel, which is the true
    and actionable answer. `read_raw_series` and `scan_series` both refused an unwritten column as
    `no_local_raw`/`environment` until this sweep measured it (2026-10-29)."""
    bad = [r for r in fine_absence if r.get("about_ok") is False]
    assert not bad, ("these refusals name the wrong `about` class for the absence they met: "
                     + json.dumps(bad, indent=1))


def test_a_fact_resolved_from_the_declaration_survives_an_absent_measurement(fine_absence):
    """The generalisation of the defect continuous integration found on 2026-10-28.

    A design's declared shift time and its knocked-out genes come from the design, not from the trajectory, so a
    tool that reported them with data present must still report them when the data turns out to be absent."""
    bad = [r for r in fine_absence if r.get("facts_dropped")]
    assert not bad, ("these tools resolved a fact from the design's own declaration and then dropped it when "
                     "the measurement turned out to be absent: " + json.dumps(bad, indent=1))


def test_a_narrowed_answer_names_what_it_narrowed(fine_absence):
    """`scan_overview` answered `channels_scanned: 3` where the full read says 5, naming neither of the two it
    skipped -- so "no transient in growth_rate" and "growth_rate was never scanned" arrived identical. Neither
    empty nor an error, which is why the two checks above could not see it."""
    bad = [r for r in fine_absence if r.get("narrowed_silently")]
    assert not bad, ("these answers lost count without naming the omission: " + json.dumps(bad, indent=1))


def test_the_finer_sweep_is_exercised_and_not_merely_green(fine_absence):
    """A sweep whose every row says 'not exercised' proves nothing. This pins that real tools are reached."""
    assert not any(r["verdict"] == "no_baseline" for r in fine_absence), "the probe design had no local raw"
    exercised = [r for r in fine_absence if r.get("reads_source")]
    assert len(exercised) >= 10, f"only {len(exercised)} tool/grain pairs read the source: {exercised}"
    assert {r["grain"] for r in exercised} == {"run", "channel"}, "one of the two grains reached nothing"


def test_a_count_like_key_is_recognised_by_shape_not_by_a_hand_list():
    """`serialization_check` returned `{"n_runs_scanned": 0, "n_columns_flagged": 0, "n_high": 0, "ok": true}`
    with nothing on disk -- a clean bill of health over a corpus it never opened -- and the detector walked past
    it because that spelling was not in the set. All counts zero is the test, so flagging zero columns out of
    real runs is still not an empty success."""
    assert conformance.empty_success({"n_runs_scanned": 0, "n_columns_flagged": 0, "n_high": 0, "ok": True})
    assert not conformance.empty_success({"n_runs_scanned": 18, "n_columns_flagged": 0, "n_high": 0, "ok": True})
    assert conformance.empty_success({"total": 0, "rows": []})
    assert not conformance.empty_success({"error": "nope", "n_runs": 0})
    # a bool is not a count: `ok: False` must not be read as "a count of zero"
    assert not conformance.empty_success({"ok": False, "verdict": "x"})


def test_the_narrowing_detector_passes_an_answer_that_names_its_omission():
    """Otherwise the fix for `scan_overview` would be to hide the number rather than to name the gap."""
    full = {"channels_scanned": 5, "by_channel": [1, 2, 3, 4, 5]}
    silent = {"channels_scanned": 3, "by_channel": [1, 2, 3]}
    named = {"channels_scanned": 3, "by_channel": [1, 2, 3],
             "channels_not_recorded": [{"channel": "growth_rate", "why": "no usable timesteps"}]}
    assert conformance.narrowed_silently(full, silent) == ["channels_scanned"]
    assert conformance.narrowed_silently(full, named) == []
    assert conformance.narrowed_silently(full, {"error": "refused"}) == []


def test_every_exempt_tool_is_exempt_for_a_stated_reason():
    """`raw_available` answering `n_seeds_local: 0` is the ANSWER to the question it was asked, not a silent
    absence -- the sweep's first run flagged it, and that was the sweep's error. The exemption is named so it
    cannot grow quietly."""
    assert conformance.AVAILABILITY_PROBES <= set(reconcile.MEASUREMENT_TOOLS) | set(
        conformance.SIDE_EFFECT_OR_EXTERNAL)
    assert "raw_available" in conformance.AVAILABILITY_PROBES
    for t in conformance.AVAILABILITY_PROBES:
        assert t in {x["name"] for x in tools.TOOLS}, f"{t} is exempt from a sweep but is not a tool"


# ---- the three tools the two grains caught, each pinned on its own ---------------------------------------------

def test_the_truncation_guard_gives_no_verdict_when_it_scanned_nothing():
    with conformance._no_local_runs():
        out = tools.dispatch("serialization_check", {})
    assert "error" in out, out
    assert out["reason"] == "no_local_raw" and out["about"] == "environment", out
    assert out.get("ok") is not True, "a guard that scanned nothing must not report a pass"


@pytest.mark.parametrize("tool", ["read_raw_series", "scan_series"])
def test_an_unwritten_column_is_the_corpus_not_this_machine(tool, recording_design):
    rid = raw.seed_runs(recording_design)[0]["result_id"]
    with conformance._unwritten_channel("growth_rate"):
        out = tools.dispatch(tool, {"result_id": rid, "channel": "growth_rate"})
    assert out.get("reason") == "channel_not_recorded", out
    assert out.get("about") == "corpus", out
    assert "recorded_here" in out, "the refusal must say which channels this run DOES record"


def test_the_channel_overview_names_the_channels_it_did_not_scan(recording_design):
    design = recording_design
    full = tools.dispatch("scan_overview", {"design": design})
    with conformance._unwritten_channel("growth_rate"):
        out = tools.dispatch("scan_overview", {"design": design})
    assert out["channels_scanned"] < full["channels_scanned"], (full, out)
    named = [c["channel"] for c in out["channels_not_recorded"]]
    assert "growth_rate" in named, out
    assert out["channels_requested"] >= out["channels_scanned"]
    assert all(c.get("why") for c in out["channels_not_recorded"]), "an omission must say why"
