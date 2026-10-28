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
    ko = next((k for k in keys if "/KO:" in k), keys[0])
    ref = next((k for k in keys if k != ko and "KO:" not in k), "wildtype/basal")
    rid = next((r.get("id") for r in rows if survey.design_key(r) == ko), None)
    gene = ko.split("KO:")[-1].split("+")[0].split("#")[0] if "KO:" in ko else "pfkA"
    return conformance.sample_args(ko, ref, rid, gene)


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
    src = Path(ROOT / "src" / "cellarium")
    used = {r for _, r in errors.PATTERNS}
    calls = "".join(f.read_text(encoding="utf-8") for f in sorted(src.glob("*.py")))
    for reason in errors.REASONS:
        if reason == "unclassified":            # the fallback; produced by classify(), not by a pattern
            continue
        assert reason in used or f'fail("{reason}"' in calls, f"{reason} is registered and unreachable"
