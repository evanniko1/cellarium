"""The four defects found while reproducing the multi-gene knockouts on the Cellarium-native tree (item 7).

Each was MEASURED before it was fixed, and each test fails if the fix is reverted. None of these need Docker
or a wcEcoli checkout — they exercise the host-side logic and the source ordering.

  (b) `calibration.observe_run` sized `run_root` BEFORE multi-gene KO output was moved into it.
  (c) `runner._EXEC_ENV` was a module global while `manifest.campaign` runs jobs in a thread pool.
  (d) `kb_sha256` (a file hash) reported two identical knowledge bases as different experiments.
  (e) a generation missing its END still passed QC as `ok`.
"""
import ast
import io
import threading
from pathlib import Path

import pytest

from cellarium import provenance, qc
from cellarium.model import GenerationResult, SimResult

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "src" / "cellarium" / "runner.py"


def _fn(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


# --- (b) calibration measures the output AFTER it has been moved --------------------------------------------

def test_calibration_is_observed_after_the_multi_ko_move():
    """`observe_run` sizes the run directory. For a multi-gene KO the output is still in the model's transit
    dir until `run_one` moves it, so measuring first recorded gb_per_generation = 3.26e-07 for a run that
    wrote ~0.5 GB — every multi-gene KO fed the resource estimator a value ~1.5e6x too small."""
    body = _fn(RUNNER, "run_one")
    move_line = observe_line = None
    for node in ast.walk(body):
        if isinstance(node, ast.Compare) and any(
                isinstance(c, ast.Constant) and c.value == "multi_gene_knockout" for c in node.comparators):
            move_line = node.lineno if move_line is None else min(move_line, node.lineno)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "observe_run"):
            observe_line = node.lineno
    assert move_line is not None, "run_one no longer branches on multi_gene_knockout — re-read this test"
    assert observe_line is not None, "run_one no longer calls calibration.observe_run"
    assert move_line < observe_line, (
        f"calibration.observe_run runs at line {observe_line}, BEFORE the multi_gene_knockout move at "
        f"{move_line} — it will size an empty directory")


# --- (c) the per-run exec env is thread-local, not a module global ------------------------------------------

def test_exec_env_is_thread_local_not_a_module_global():
    from cellarium import runner
    assert isinstance(runner._EXEC_LOCAL, threading.local), "the per-run exec env is not thread-local"
    assert not hasattr(runner, "_EXEC_ENV"), (
        "a module-global _EXEC_ENV is back — under manifest.campaign(parallel>1) two graded designs for "
        "different genes can overwrite each other's GRADED_KO_CISTRON and knock out the wrong gene")


def test_two_threads_do_not_see_each_others_exec_env():
    """The actual race, reproduced. With a module global this asserts False in at least one thread."""
    from cellarium import runner
    seen, errors = {}, []
    barrier = threading.Barrier(2)

    def worker(name, env):
        try:
            runner._set_exec_env(env)
            barrier.wait(timeout=5)          # force the interleave: both have written before either reads
            seen[name] = runner._get_exec_env()
        except Exception as exc:             # pragma: no cover - only on a broken barrier
            errors.append(exc)

    a = threading.Thread(target=worker, args=("a", {"GRADED_KO_CISTRON": "EG11358_RNA"}))
    b = threading.Thread(target=worker, args=("b", {"GRADED_KO_CISTRON": "EG10001_RNA"}))
    a.start(); b.start(); a.join(5); b.join(5)
    assert not errors, errors
    assert seen["a"] == {"GRADED_KO_CISTRON": "EG11358_RNA"}, f"thread a saw {seen['a']}"
    assert seen["b"] == {"GRADED_KO_CISTRON": "EG10001_RNA"}, f"thread b saw {seen['b']}"


def test_campaign_still_uses_a_thread_pool():
    """Non-vacuity: the two tests above only matter while campaign is threaded."""
    src = io.open(ROOT / "src" / "cellarium" / "manifest.py", encoding="utf-8").read()
    assert "ThreadPoolExecutor" in src, "campaign is no longer threaded — re-read the tests above"


# --- (d) a differing FILE hash is not evidence of a different experiment ------------------------------------

def test_differing_file_hashes_alone_are_undecidable_not_different():
    """MEASURED: two ParCa runs of identical code produced different file hashes, bit-identical exp_ppgpp
    (0/3276) and bitwise identical simulations over 2530 timesteps. Calling that 'different' refuses valid
    pooling."""
    v = provenance.same_kb({"kb_sha256": "94325a1e"}, {"kb_sha256": "9881c39e"})
    assert v["same"] is None, f"differing file hashes reported as {v['same']!r} — must be undecidable"
    assert "not" in v["why"].lower()


def test_identical_file_hashes_are_decisive():
    v = provenance.same_kb({"kb_sha256": "abc"}, {"kb_sha256": "abc"})
    assert v["same"] is True and v["basis"] == "kb_sha256"


def test_content_hash_overrides_the_file_hash_in_both_directions():
    same = provenance.same_kb({"kb_sha256": "94325a1e", "kb_content_sha256": "99ab9368"},
                              {"kb_sha256": "9881c39e", "kb_content_sha256": "99ab9368"})
    assert same["same"] is True and same["basis"] == "kb_content_sha256", same
    diff = provenance.same_kb({"kb_sha256": "x", "kb_content_sha256": "99ab9368"},
                              {"kb_sha256": "x", "kb_content_sha256": "624d5a9f"})
    assert diff["same"] is False and diff["basis"] == "kb_content_sha256", diff


def test_a_missing_hash_is_undecidable_never_a_match():
    for a, b in (({}, {"kb_sha256": "x"}), ({"kb_sha256": "x"}, {}), ({}, {})):
        assert provenance.same_kb(a, b)["same"] is None


def test_kb_provenance_declares_the_content_field():
    out = provenance.kb_provenance("does-not-exist")
    assert "kb_content_sha256" in out, "kb_provenance no longer reports a content hash"


# --- (e) a generation missing its END must not pass QC ------------------------------------------------------

def _gen(i, t0, t1, **kw):
    return GenerationResult(index=i, t_start=t0, t_end=t1, n_steps=int(t1 - t0) + 1,
                            divided=True, division_time_sec=t1, **kw)


def _sim(gens):
    return SimResult(id="t", generations=gens)


def test_the_measured_truncation_is_caught():
    """wildtype_374656/000000: generation 0 stops at 2047 s, generation 1 starts at 2530 s. Recorded ok."""
    sim = _sim([_gen(0, 0.0, 2047.0), _gen(1, 2530.0, 5268.0)])
    assert qc.truncated_generations(sim) == [0]
    overall, per = qc.check_result(sim)
    assert per[0] is qc.QCStatus.TRUNCATED, per
    assert overall is qc.QCStatus.TRUNCATED
    assert not qc.is_reportable(sim), "a lineage missing 19% of a generation is still reportable"


def test_the_81_percent_truncation_is_caught():
    """seed 1 of the same design: generation 0 stops at 478 s against a 2574 s start."""
    sim = _sim([_gen(0, 0.0, 478.0), _gen(1, 2574.0, 5000.0)])
    assert qc.truncated_generations(sim) == [0]


def test_a_continuous_lineage_stays_ok():
    """Non-vacuity: the intact boundaries in the same design must NOT trip. Measured spacing is ~1 s."""
    sim = _sim([_gen(0, 0.0, 2521.0), _gen(1, 2522.0, 5361.0), _gen(2, 5362.0, 8183.0)])
    assert qc.truncated_generations(sim) == []
    overall, per = qc.check_result(sim)
    assert overall is qc.QCStatus.OK, per
    assert qc.is_reportable(sim)


def test_the_last_generation_is_never_called_truncated():
    """Nothing follows it, so there is no witness — and a terminal generation legitimately ends the lineage."""
    sim = _sim([_gen(0, 0.0, 2521.0), _gen(1, 2522.0, 5361.0)])
    assert 1 not in qc.truncated_generations(sim)


def test_missing_times_are_skipped_not_assumed_continuous():
    """Every manifest row written before t_start/t_end existed has neither. Absent must not read as 'fine' —
    but it must also not fabricate a truncation."""
    # Otherwise-healthy generations (they divided) that simply carry no times — the pre-existing corpus shape.
    old = [GenerationResult(index=0, divided=True, division_time_sec=2047.0),
           GenerationResult(index=1, divided=True, division_time_sec=2738.0)]
    assert all(g.t_start is None and g.t_end is None for g in old)
    sim = _sim(old)
    assert qc.truncated_generations(sim) == []
    assert qc.check_result(sim)[0] is qc.QCStatus.OK, "absent times must not fabricate a failure either"


def test_truncation_does_not_mask_a_worse_status():
    """A generation that is already DEAD/NO_DIVISION keeps that status — truncation only overturns `ok`."""
    sim = _sim([_gen(0, 0.0, 2047.0, is_dead=True), _gen(1, 2530.0, 5268.0)])
    _, per = qc.check_result(sim)
    assert per[0] is qc.QCStatus.DEAD, per


def test_a_hole_in_the_lineage_is_not_reported_as_truncation():
    """Generations 0 and 2 with 1 missing: a different defect. Do not guess across the gap."""
    sim = _sim([_gen(0, 0.0, 2047.0), _gen(2, 9000.0, 11000.0)])
    assert qc.truncated_generations(sim) == []


def test_the_reader_records_generation_times():
    """The QC above is inert unless the reader actually fills the fields."""
    src = io.open(ROOT / "src" / "cellarium" / "_reader_worker.py", encoding="utf-8").read()
    assert src.count('"t_start"') >= 2 and src.count('"t_end"') >= 2, \
        "the reader does not record t_start/t_end on both generation paths"


@pytest.mark.parametrize("gap,expected", [(0.0, []), (1.0, []), (5.0, []), (5.1, [0]), (482.0, [0])])
def test_the_gap_threshold(gap, expected):
    sim = _sim([_gen(0, 0.0, 1000.0), _gen(1, 1000.0 + gap, 3000.0)])
    assert qc.truncated_generations(sim) == expected


def test_the_content_hash_is_disk_cached_and_never_caches_a_failure():
    """Computing it spawns the model image and unpickles ~90 MB. `manifest` asks for provenance on the first
    row of every process, so an unconditional spawn there would tax every CLI invocation. Keyed by the FILE
    hash, which is safe precisely because that is the direction the file hash IS sound in."""
    import json
    import tempfile
    from unittest import mock
    calls = []

    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "kb_content_hash.json"
        with mock.patch.object(provenance, "CONTENT_HASH_CACHE", str(cache)):
            def ok(_sim_path):
                calls.append("ok")
                return {"kb_content_sha256": "99ab9368"}
            with mock.patch("cellarium.reader.kb_content_hash", ok):
                assert provenance._cached_content_hash("cellarium", "FILEHASH") == "99ab9368"
                assert provenance._cached_content_hash("cellarium", "FILEHASH") == "99ab9368"
            assert len(calls) == 1, f"the container was spawned {len(calls)} times — the cache is not working"
            assert json.loads(cache.read_text(encoding="utf-8")) == {"FILEHASH": "99ab9368"}

            # A FAILURE must stay retryable — caching None would make one Docker-less run poison the record.
            fails = []

            def boom(_sim_path):
                fails.append(1)
                raise RuntimeError("no docker")
            with mock.patch("cellarium.reader.kb_content_hash", boom):
                assert provenance._cached_content_hash("cellarium", "OTHER") is None
                assert provenance._cached_content_hash("cellarium", "OTHER") is None
            assert len(fails) == 2, "a failure was cached — it must stay retryable"
            assert "OTHER" not in json.loads(cache.read_text(encoding="utf-8"))


def test_kb_provenance_does_not_spawn_a_container_when_there_is_no_kb():
    """No file hash means nothing to key the cache on, and nothing to hash — it must not try."""
    from unittest import mock
    with mock.patch("cellarium.reader.kb_content_hash", side_effect=AssertionError("must not be called")):
        out = provenance.kb_provenance("definitely-not-a-real-sim-path")
    assert out["kb_sha256"] is None and out["kb_content_sha256"] is None


def test_the_manifest_row_carries_the_content_hash():
    """The predicate is useless if the corpus never STORES the field. `union_by_name=true` on every read means
    a new column is NULL on older shards rather than an error — the codebase already relies on that for
    `elongation_model`."""
    src = io.open(ROOT / "src" / "cellarium" / "manifest.py", encoding="utf-8").read()
    assert '"kb_content_sha256": _kb.get("kb_content_sha256")' in src, \
        "manifest rows do not store kb_content_sha256 — only the file hash reaches the corpus"
    assert "union_by_name=true" in src, "reads are no longer union_by_name — a new column would now break them"
