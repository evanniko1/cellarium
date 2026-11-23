"""Every Agentic Benchmark Checklist item the self-audit marks MET with a guard test, broken once, on purpose.

docs/ABC_SELF_AUDIT.md scores Cellarium's evaluations against the 42 items of the Agentic Benchmark Checklist
(arXiv:2507.02825, v5). The project's standing rule, and the checklist's own warning about benchmarks whose checks
were never exercised: a check that has never been made to fail is decoration. So for each item the audit claims
on the strength of a test, this file plants the fault that item is about and asserts the guard goes red. If a
guard stops noticing its fault, the claim in the audit stops being true, and this file says so.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "scripts", "tests"):
    sys.path.insert(0, str(REPO / p))

import run_gate_eval as ev  # noqa: E402
import test_blind_external_reads as BLIND  # noqa: E402
import test_gate_error_accounting as ACCOUNT  # noqa: E402
import test_gate_error_causes as CAUSES  # noqa: E402
import test_gate_oracle as ORACLE  # noqa: E402
import test_gate_reliability as RELIABILITY  # noqa: E402
import test_remote_reads_are_pinned as PINNED  # noqa: E402

from cellarium import capability as C  # noqa: E402
from cellarium import corpora, egress, gate  # noqa: E402

RUN = REPO / "evals" / "results" / "gate_eval_8framings.json"


@pytest.fixture(scope="module")
def recs() -> list[dict]:
    return json.loads(RUN.read_text(encoding="utf-8"))["records"]


def _goes_red(fn, *args) -> bool:
    try:
        fn(*args)
    except (AssertionError, ValueError):
        return True
    return False


def test_T5_isolation_from_ground_truth(monkeypatch):
    """T.5: agents isolated from the results. Plant: the blind-run block list emptied."""
    monkeypatch.setattr(egress, "BLIND_BLOCKED_DOMAINS", ())
    assert _goes_red(BLIND.test_a_search_that_touched_a_dataset_page_never_reaches_a_role, monkeypatch)


def test_T6_remote_reads_name_a_commit(monkeypatch):
    """T.6: an environment frozen at release. Plants: well4cell unpinned; the revision removed from the real
    corpora.py download call. Each must turn its guard red."""
    monkeypatch.setattr(corpora, "WELL4CELL", dataclasses.replace(corpora.WELL4CELL, revision=""))
    assert _goes_red(PINNED.test_well4cell_is_read_at_the_rc2_commit)
    src = (REPO / "src" / "cellarium" / "corpora.py").read_text(encoding="utf-8")
    assert "revision=rev," in src, "the plant's anchor moved; re-aim it"
    assert PINNED.hub_reads_without_revision(src.replace("revision=rev,", "", 1)) == [
        f"<src>:{next(i for i, line in enumerate(src.splitlines(), 1) if 'hf_hub_download(c.locator' in line)} "
        "hf_hub_download"]


def test_T9_the_oracle_solver(monkeypatch, recs):
    """T.9: an oracle shows the task configuration. Plant: a capability loses its canonical requirement row."""
    monkeypatch.setattr(gate, "modes_with_runs", lambda: tuple(C.MODES_IN_CORPUS))
    row = next(k for k, v in gate.REQUIRES.items() if "nutrient_shift_timelines" in v)
    monkeypatch.delitem(gate.REQUIRES, row)
    assert _goes_red(ORACLE.test_a_perfect_parser_matches_26_of_27_cells_and_the_27th_is_gate_8b_d, recs, None)


def test_T10_every_pilot_error_is_explained(monkeypatch, recs):
    """T.10: outliers inspected. Plant: one dependency rule removed, so 9 refusals lose their explanation."""
    monkeypatch.delitem(gate.DEPENDENCY_REQUIRES, "amino_acid_supply")
    assert _goes_red(CAUSES.test_every_wrong_verdict_in_the_8_framing_run_has_a_registered_cause, recs)


def test_R13_and_Ob3_trivial_baselines(monkeypatch, recs):
    """R.13 / O.b.3: trivial agents reported; success by guessing measured. Plant: a wrong baseline."""
    real = ev._reliability
    monkeypatch.setattr(ev, "_reliability", lambda rs: {**real(rs), "trivial_baselines": {
        "always_refuse": 0.3333, "always_answer": 0.3333, "always_propose": 0.3333}})
    assert _goes_red(RELIABILITY.test_a_system_that_refuses_everything_scores_0_556_on_this_surface, recs)


def test_R10_the_interval_respects_the_clustering(monkeypatch, recs):
    """R.10: confidence intervals. Plant: the naive interval reported as the clustered one."""
    real = ev._reliability

    def naive(rs):
        r = real(rs)
        r["ci95_half_width_clustered"] = r["ci95_half_width_naive"]
        return r
    monkeypatch.setattr(ev, "_reliability", naive)
    assert _goes_red(RELIABILITY.test_the_interval_is_clustered_on_the_cell_not_the_record, recs)


def test_R9_every_error_is_counted(monkeypatch):
    """R.9: quantitative analysis of flaws. Plant: one error shape removed from the count."""
    trimmed = {k: v for k, v in ev.ERROR_SHAPES.items() if k != ("propose", "refuse")}
    monkeypatch.setattr(ev, "ERROR_SHAPES", trimmed)
    assert _goes_red(ACCOUNT.test_the_8_framing_run_has_27_wrong_verdicts_and_2_of_them_answer_with_no_run_behind_them)


def test_the_guards_pass_unplanted(monkeypatch, recs):
    """The control: without a plant every guard passes, so a red above is the plant's doing."""
    monkeypatch.setattr(gate, "modes_with_runs", lambda: tuple(C.MODES_IN_CORPUS))
    for fn, args in ((CAUSES.test_every_wrong_verdict_in_the_8_framing_run_has_a_registered_cause, (recs,)),
                     (RELIABILITY.test_a_system_that_refuses_everything_scores_0_556_on_this_surface, (recs,)),
                     (ORACLE.test_a_perfect_parser_matches_26_of_27_cells_and_the_27th_is_gate_8b_d, (recs, None)),
                     (ACCOUNT.test_the_8_framing_run_has_27_wrong_verdicts_and_2_of_them_answer_with_no_run_behind_them,
                      ()),
                     (PINNED.test_well4cell_is_read_at_the_rc2_commit, ()),
                     (PINNED.test_every_hub_read_in_the_package_names_a_revision, ())):
        assert not _goes_red(fn, *args), fn.__name__
