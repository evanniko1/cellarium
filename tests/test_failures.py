"""FAIL-1 — a failed run keeps the evidence of why, and an unnamed failure is triaged on first sighting.

The fixtures under tests/fixtures/failures/ are excerpts of real campaign logs (container paths only); the
`[cellarium]` footer lines are synthesised. Each known identity is pinned to the log that defined it.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest

from cellarium import failures as F
from cellarium import manifest, runner
from cellarium.model import Design

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "failures"


def _fx(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------ identity, on real logs

def test_atp_exhaustion_is_named_a_result_and_names_the_molecule():
    i = F.identify(log_text=_fx("atp_exhausted.log"))
    assert i.key == "NegativeCountsError@wholecell/states/bulk_molecules.py:merge"
    assert i.named and i.signature.category == "ran_out" and i.signature.result is True
    assert i.detail["ran_out"] == [{"molecule": "ATP[c]", "process": "PolypeptideElongation", "count": -13690}]


def test_trna_charging_nan_is_numerical_and_says_where_not_why():
    i = F.identify(log_text=_fx("trna_charging_nan.log"))
    assert i.key == "ValueError@models/ecoli/processes/polypeptide_elongation.py:calculate_trna_charging"
    assert i.signature.category == "numerical" and i.signature.result is False
    assert i.where.endswith("calculate_trna_charging")      # the deepest MODEL frame, not scipy's
    assert "not why" in i.signature.meaning or "WHERE it failed" in i.signature.meaning


def test_glpk_failure_is_solver_and_carries_the_status():
    i = F.identify(log_text=_fx("glpk_efail.log"))
    assert i.key == "RuntimeError@wholecell/utils/_netflow/nf_glpk.py:_solve"
    assert i.signature.category == "solver" and i.detail["glpk"] == "GLP_EFAIL"


def test_every_known_traceback_identity_has_a_fixture():
    """A name must cite the evidence that defined it. Refusals and absences are read from notes, not logs."""
    seen = {F.identify(log_text=p.read_text(encoding="utf-8")).key for p in FIX.glob("*.log")}
    traceback_keys = {k for k in F.KNOWN if "@" in k}
    assert traceback_keys <= seen, traceback_keys - seen


# ------------------------------------------------------------------------------------ identity is structural

def test_rewording_the_message_does_not_change_the_identity():
    t = _fx("trna_charging_nan.log").replace("array must not contain infs or NaNs", "non-finite input to LU")
    assert F.identify(log_text=t).key == F.identify(log_text=_fx("trna_charging_nan.log")).key


def test_a_moved_line_number_does_not_change_the_identity():
    t = _fx("trna_charging_nan.log").replace("line 1081, in calculate_trna_charging",
                                             "line 1203, in calculate_trna_charging")
    i = F.identify(log_text=t)
    assert i.key == F.identify(log_text=_fx("trna_charging_nan.log")).key and i.line == 1203


_NEW = """Traceback (most recent call last):
  File "/wcEcoli/wholecell/sim/simulation.py", line 289, in run_incremental
    self._evolveState(processes)
  File "/wcEcoli/models/ecoli/processes/chromosome_replication.py", line 138, in evolveState
    x = table[medium]
  File "/usr/local/lib/python3.10/site-packages/numpy/core/fromnumeric.py", line 9, in take
    raise KeyError(k)
KeyError: 'minimal_plus_x'
"""


def test_a_never_seen_failure_gets_a_precise_identity_not_unrecognised():
    i = F.identify(log_text=_NEW)
    assert i.key == "KeyError@models/ecoli/processes/chromosome_replication.py:evolveState"
    assert not i.named and i.line == 138


def test_a_chained_reraise_is_traced_to_the_root_exception():
    wrapper = ("\nDuring handling of the above exception, another exception occurred:\n\n"
               "Traceback (most recent call last):\n"
               '  File "/wcEcoli/wholecell/fireworks/firetasks/simulation.py", line 90, in run_task\n'
               "    sim.run()\nRuntimeError: task failed\n")
    assert F.identify(log_text=_NEW + wrapper).key.startswith("KeyError@")


def test_refusals_are_read_from_the_note_even_when_a_stale_log_sits_in_the_run_root(tmp_path):
    (tmp_path / F.SIM_LOG).write_text(_fx("atp_exhausted.log"), encoding="utf-8")
    i = F.identify(note="sim crashed (no data): Refusing out-of-envelope design: Perturbation 'x' ...",
                   run_root=tmp_path)
    assert i.key == "refused:envelope" and i.signature.category == "refused"
    i = F.identify(note="sim crashed: Refusing to run: <repo>/runs/... holds output with no design.json",
                   run_root=tmp_path)
    assert i.key == "refused:overwrite_guard"


def test_no_evidence_is_named_as_no_evidence_never_guessed(tmp_path):
    assert F.identify(run_root=tmp_path).key == "no_log"
    assert F.identify(note="sim crashed: Command 'docker run' returned non-zero", run_root=None).key == "no_log"
    assert F.identify(log_text="hello\n" + F.EXIT_MARK + " 0\n").key == "no_traceback"


def test_a_killed_process_without_a_traceback_is_an_unnamed_exit_identity():
    i = F.identify(log_text="progress...\n" + F.EXIT_MARK + " 137\n")
    assert i.key == "exit:137" and not i.named


# ------------------------------------------------------------------------------------ the log itself

def test_prepare_log_rotates_and_never_overwrites(tmp_path):
    for k in range(3):
        p = F.prepare_log(tmp_path)
        p.write_text(f"attempt {k}", encoding="utf-8")
    texts = sorted(q.read_text(encoding="utf-8") for q in tmp_path.iterdir())
    assert texts == ["attempt 0", "attempt 1", "attempt 2"]
    assert all(F.is_dev_only(q.name) for q in tmp_path.iterdir())


def test_run_checked_keeps_the_whole_output_not_the_tail(tmp_path):
    script = ("import sys\n"
              "for i in range(1000): print(f'line {i}')\n"
              "print('Traceback (most recent call last):')\n"
              "print('  File \"/wcEcoli/models/ecoli/processes/x.py\", line 1, in f')\n"
              "print('ValueError: boom')\n")
    log = tmp_path / F.SIM_LOG
    with pytest.raises(RuntimeError):            # exit 0 with a traceback is still a failure
        runner._run_checked([sys.executable, "-c", script], None, log)
    text = log.read_text(encoding="utf-8")
    assert "line 0\n" in text and "line 999\n" in text     # the in-memory tail drops the early lines; the log may not
    assert f"{F.EXIT_MARK} 0" in text and F.MARKER_MARK in text
    assert F.identify(log_text=text).key == "ValueError@models/ecoli/processes/x.py:f"


def test_run_one_hands_the_log_path_to_the_model_process():
    """Static: the path is set around `_exec` and cleared after, on the same thread-local `_exec` reads."""
    src = (ROOT / "src" / "cellarium" / "runner.py").read_text(encoding="utf-8")
    assert "log_path = failures.prepare_log(run_root)" in src
    assert "_EXEC_LOCAL.log_path = log_path" in src and "_EXEC_LOCAL.log_path = None" in src
    assert src.count('getattr(_EXEC_LOCAL, "log_path", None)') == 2      # docker AND native transports


# ------------------------------------------------------------------------------------ never shipped as is

def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", ["sim.log", "sim.20261008T120000.log", "sim.20261008T120000_2.log"])
def test_dev_only_predicate_and_upload_globs_agree(name):
    assert F.is_dev_only(name) and F.is_dev_only(f"gene_knockout_000001/000000/{name}")
    for rel in (name, f"gene_knockout_000001/000000/{name}"):
        assert any(fnmatch.fnmatch(rel, g) for g in F.DEV_ONLY_GLOBS), rel


def test_packing_a_run_leaves_the_log_out(tmp_path):
    rr = tmp_path / "runs" / "cellarium" / "gene_knockout_000001" / "000000"
    (rr / "generation_000000" / "000000" / "simOut").mkdir(parents=True)
    (rr / "generation_000000" / "000000" / "simOut" / "Main").write_text("x")
    (rr / "design.json").write_text("{}")
    (rr / "sim.log").write_text("host path C:/Users/someone")
    (rr / "sim.20261008T120000.log").write_text("older")
    tarp = tmp_path / "out.tar.gz"
    _load_script("hf_pack_upload").pack_run(rr, "cellarium/gene_knockout_000001/000000", tarp)
    names = tarfile.open(tarp).getnames()
    assert any(n.endswith("design.json") for n in names) and any(n.endswith("Main") for n in names)
    assert not any(F.is_dev_only(n) for n in names), names


def test_folder_upload_passes_the_exclusion():
    tree = ast.parse((ROOT / "scripts" / "hf_upload.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "upload_folder"]
    assert calls and all(any(k.arg == "ignore_patterns" and "DEV_ONLY_GLOBS" in ast.unparse(k.value)
                             for k in c.keywords) for c in calls)


# ------------------------------------------------------------------------------------ the first-sighting loop

def _crash_case(tmp_path, log_text: str, seed: int = 0):
    d = Design(perturbation="gene_knockout", params={"variant_index": 1818}, condition="basal")
    rr = tmp_path / "runs" / "cellarium" / "gene_knockout_001818" / f"{seed:06d}"
    rr.mkdir(parents=True)
    (rr / F.SIM_LOG).write_text(log_text, encoding="utf-8")
    row = {"label": manifest._label(d, seed), "perturbation": "gene_knockout", "condition": "basal",
           "timeline": None, "seed": seed, "crashed": True, "qc": "crashed", "note": "sim crashed: ...",
           "simout_path": str(rr)}
    return d, rr, row


def test_an_unnamed_failure_is_triaged_at_once_without_a_simulation(tmp_path, monkeypatch):
    monkeypatch.setenv("CELLARIUM_TRIAGE", str(tmp_path / "triage"))
    d, rr, row = _crash_case(tmp_path, _NEW)
    ctrl = {"perturbation": "wildtype", "condition": "basal", "timeline": None, "crashed": False, "qc": "ok",
            "label": "wildtype/basal seed0", "seed": 0}
    out = F.after_campaign([(d, 0, row)], 2, "cellarium", repeat=False, rows=[row, ctrl])
    key = "KeyError@models/ecoli/processes/chromosome_replication.py:evolveState"
    assert out["unnamed"] == [key]
    rec = json.loads(Path(out["triage_records"][key]).read_text(encoding="utf-8"))
    assert rec["control"] == {"in_corpus": True, "n": 1, "n_crashed": 0, "qc": ["ok"], "identities": []}
    assert rec["repeat"]["ran"] is False and "not authorised" in rec["repeat"]["why"]
    assert "pre_failure" in rec and rec["identity"]["named"] is False


def test_named_failures_are_counted_not_triaged(tmp_path, monkeypatch):
    monkeypatch.setenv("CELLARIUM_TRIAGE", str(tmp_path / "triage"))
    d, rr, row = _crash_case(tmp_path, _fx("atp_exhausted.log"))
    out = F.after_campaign([(d, 0, row)], 2, "cellarium", repeat=True, rows=[row],
                           run_one=lambda *a, **k: pytest.fail("a named failure must not spend a simulation"))
    assert out["unnamed"] == [] and not (tmp_path / "triage").exists()
    assert out["failures"]["NegativeCountsError@wholecell/states/bulk_molecules.py:merge"]["category"] == "ran_out"


def test_the_repeat_preserves_the_original_and_keeps_itself_out_of_the_run_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("CELLARIUM_TRIAGE", str(tmp_path / "triage"))
    d, rr, row = _crash_case(tmp_path, _NEW)
    (rr / "design.json").write_text("ORIGINAL")
    monkeypatch.setattr(runner, "_run_subpath", lambda design, seed, sim_path: rr)

    def fake_run_one(design, seed, generations, sim_path="cellarium"):
        assert not rr.exists()                    # the original was moved aside BEFORE the repeat started
        rr.mkdir(parents=True)
        (rr / "design.json").write_text("REPEAT")
        (rr / F.SIM_LOG).write_text(_NEW, encoding="utf-8")
        raise RuntimeError("The model script exited 0 but its output contains 'Traceback'")

    out = F.after_campaign([(d, 0, row)], 2, "cellarium", repeat=True, rows=[row], run_one=fake_run_one)
    (path,) = out["triage_records"].values()
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    assert rec["repeat"]["same_identity"] is True and "deterministic" in rec["repeat"]["reading"]
    assert (rr / "design.json").read_text() == "ORIGINAL"          # evidence restored, untouched
    kept = Path(rec["repeat"]["kept_at"])
    assert (kept / "design.json").read_text() == "REPEAT" and (tmp_path / "triage") in kept.parents


def test_a_repeat_that_does_not_reproduce_points_at_the_host(tmp_path, monkeypatch):
    monkeypatch.setenv("CELLARIUM_TRIAGE", str(tmp_path / "triage"))
    d, rr, row = _crash_case(tmp_path, _NEW)
    monkeypatch.setattr(runner, "_run_subpath", lambda design, seed, sim_path: rr)

    def completes(design, seed, generations, sim_path="cellarium"):
        rr.mkdir(parents=True)
        (rr / F.SIM_LOG).write_text("ok\n" + F.EXIT_MARK + " 0\n", encoding="utf-8")

    rep = F.repeat_once(d, 0, 2, "cellarium", F.identify(log_text=_NEW), run_one=completes)
    assert rep["outcome"] == "completed" and rep["same_identity"] is False and "host" in rep["reading"]


def test_unnamed_lists_triageable_rows_but_not_absences(tmp_path):
    d, rr, row = _crash_case(tmp_path, _NEW)
    legacy = {**row, "simout_path": str(tmp_path / "nowhere"), "label": "legacy seed9"}
    assert [u["label"] for u in F.unnamed([row, legacy])] == [row["label"]]


def test_the_repeat_is_off_unless_a_caller_turns_it_on():
    """A path that runs exactly what a person approved must not gain a simulation they did not approve."""
    import inspect
    assert inspect.signature(manifest.campaign).parameters["triage_repeat"].default is False
    launch = ast.parse((ROOT / "src" / "cellarium" / "launch.py").read_text(encoding="utf-8"))
    for c in (n for n in ast.walk(launch) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "campaign"):
        assert not any(k.arg == "triage_repeat" for k in c.keywords)


def test_campaign_runs_the_loop_after_the_shard_and_survives_it_breaking(tmp_path, monkeypatch, capsys):
    d = Design(perturbation="gene_knockout", params={"variant_index": 1818})
    order = []
    monkeypatch.setattr(manifest, "_run_job", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(manifest, "_crash_row", lambda *a, **k: {"label": "x", "crashed": True, "note": "boom"})
    monkeypatch.setattr(manifest, "append_shard", lambda rows: order.append("shard") or tmp_path / "s.parquet")

    def broken(*a, **k):
        order.append("loop")
        raise ValueError("loop broke")
    monkeypatch.setattr(F, "after_campaign", broken)
    assert manifest.campaign([d], [0], 1) == tmp_path / "s.parquet"
    assert order == ["shard", "loop"]
    assert "FAILURE TRIAGE DID NOT RUN" in capsys.readouterr().out
