"""Every evaluation artefact records the stack that produced it (Agentic Benchmark Checklist T.1).

`requirements.lock` pins 119 packages, and the project's `.venv` matches 117 of them. But nothing said which
interpreter ran a given evaluation, and on 2026-11-23 the system Python this suite runs on differed from the lock
on 70 of the 119, `anthropic` among them (0.92.0 installed, 0.116.0 locked). A lock file says what SHOULD run; an
artefact has to say what DID. Since 2026-11-23 the gate eval, the ablation and each A/B arm record the
interpreter, the git commit, the installed versions of the packages that can change a result, and where those
differ from the lock. No path is recorded: the artefacts are public.

Expectations are literals, except the installed versions, which are read independently through
`importlib.metadata` so the test holds on any machine.
"""

from __future__ import annotations

import json
import sys
from importlib import metadata as md
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "scripts", "evals", "tests"):
    sys.path.insert(0, str(REPO / p))

import ablate  # noqa: E402
import run_ab  # noqa: E402
import run_gate_eval as ev  # noqa: E402
import test_runs_stop_on_an_outage as OUTAGE  # noqa: E402

from cellarium import llm, provenance  # noqa: E402

PACKAGES = ("anthropic", "openai", "pydantic", "numpy", "scipy", "duckdb", "pyarrow", "huggingface_hub")


def _installed(pkg):
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return None


def test_the_recorded_packages_are_the_ones_that_can_change_a_result():
    env = provenance.code_environment()
    assert tuple(env["packages"]) == PACKAGES
    assert env["packages"] == {p: _installed(p) for p in PACKAGES}
    assert isinstance(env["python"], str) and env["python"].count(".") == 2
    assert isinstance(env["in_a_venv"], bool)


def test_no_path_is_recorded_because_the_artefacts_are_public():
    text = json.dumps(provenance.code_environment())
    assert sys.executable not in text and str(Path.home()) not in text and str(REPO) not in text


def test_a_difference_from_the_lock_is_named(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("# header\nanthropic==0.0.1\nNumPy==" + str(_installed("numpy")) + "\nhuggingface-hub==0.0.2\n",
                    encoding="utf-8")
    env = provenance.code_environment(lock=lock)
    assert env["lock_file"] == "requirements.lock"
    assert env["differs_from_lock"] == {
        "anthropic": {"locked": "0.0.1", "installed": _installed("anthropic")},
        "huggingface_hub": {"locked": "0.0.2", "installed": _installed("huggingface_hub")}}


def test_no_lock_means_no_comparison_rather_than_no_differences(tmp_path):
    env = provenance.code_environment(lock=tmp_path / "absent.lock")
    assert (env["lock_file"], env["differs_from_lock"]) == (None, None)


def test_the_council_run_bundle_carries_the_same_packages():
    assert tuple(provenance.run_environment()["packages"]) == PACKAGES


def test_a_gate_eval_artefact_records_its_environment(monkeypatch, tmp_path):
    code, out, _ = OUTAGE.gate_run_with(monkeypatch, tmp_path, ok_first=10 ** 6)
    env = json.loads(out.read_text(encoding="utf-8"))["report"].get("environment") or {}
    assert "packages" in env, f"the gate eval artefact records no environment: {env!r}"
    assert code == 0 and env["packages"]["anthropic"] == _installed("anthropic")


def test_a_stopped_gate_eval_records_its_environment_too(monkeypatch, tmp_path):
    code, out, _ = OUTAGE.gate_run_with(monkeypatch, tmp_path, ok_first=0)
    part = json.loads(out.with_name("gate_eval.partial.json").read_text(encoding="utf-8"))
    assert code == 3 and part["report"]["environment"]["packages"]["anthropic"] == _installed("anthropic")


def test_a_rescore_keeps_the_environment_the_run_recorded(tmp_path):
    src = json.loads((REPO / "evals" / "results" / "gate_eval.json").read_text(encoding="utf-8"))
    src["report"]["environment"] = {"python": "3.0.0", "packages": {"anthropic": "0.1"}}
    f = tmp_path / "r.json"
    f.write_text(json.dumps(src), encoding="utf-8")
    assert ev.main(["--rescore", str(f)]) == 0
    assert json.loads(f.read_text(encoding="utf-8"))["report"]["environment"] == {
        "python": "3.0.0", "packages": {"anthropic": "0.1"}}, "the environment is the RUN's, not the rescorer's"


def test_an_ablation_records_its_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(ablate, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "client", lambda **kw: object())
    monkeypatch.setattr(ablate, "_one_cell", lambda case, cfg, rep, *a: {"id": case["id"], "config": cfg, "rep": rep})
    out = tmp_path / "ablation.json"
    assert ablate.run(["1.1"], ["full"], 1, 0.7, str(out), "gpt-4o", "claude-opus-4-8", workers=1) == 0
    env = json.loads(out.read_text(encoding="utf-8"))["environment"]
    assert env["packages"]["anthropic"] == _installed("anthropic")


def test_each_ab_arm_records_its_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(run_ab, "LEDGER", tmp_path / "ab_ledger.json")
    monkeypatch.setattr(run_ab, "RESULTS", tmp_path)
    monkeypatch.setattr(run_ab, "_resolve_api_key", lambda log=print: None)
    monkeypatch.setattr(run_ab, "_aggregate", lambda *a, **kw: None)
    monkeypatch.setattr(run_ab, "_log", lambda m: None)
    monkeypatch.setattr(llm, "client", lambda **kw: object())
    monkeypatch.setattr(run_ab, "run_arm_b", lambda case, *a, **kw: {"id": case["id"], "status": "ok"})
    monkeypatch.setattr(sys, "argv", ["run_ab.py", "1.1", "--arm", "b"])
    assert run_ab.main() == 0
    slot = json.loads(run_ab.LEDGER.read_text(encoding="utf-8"))["1.1"]["b"]
    assert slot["environment"]["packages"]["anthropic"] == _installed("anthropic")
