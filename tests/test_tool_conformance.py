"""Every tool, swept for the four bug families the option-A discovery leg exposed (src/cellarium/conformance.py).

WHY A SWEEP AND NOT MORE CASES. The eleven faults of 2026-10-27 were found one at a time, by reading a transcript
after a blind run had already failed. Each had its own test afterwards, which pins that tool and says nothing
about the next one. These tests ask the same four questions of EVERY read-only tool at once, so the next tool to
acquire one of these faults fails here instead of inside an investigation:

  1. ABSENCE   — an unreadable source answers with an error, never with an empty success.
  2. SHAPE     — whatever the size, the agent receives valid JSON, and anything dropped is named.
  3. DETERMINISM — two identical calls agree, and reordering the rows changes nothing.
  4. CONTEXT   — the answer does not depend on the process's working directory.

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

from cellarium import agent, conformance, raw, reconcile, survey, tools  # noqa: E402


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
