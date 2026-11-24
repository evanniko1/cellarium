"""A paid run finds its keys where the app keeps them, or stops before it spends anything.

FOUND 2026-11-24, starting the first approved paid runs of the validation layer (M0, M4): the commands prepared
for approval could not have run on the machine they were prepared on. The app's Settings tab keeps both API keys
in the OS keychain (docs/CREDENTIALS.md); evals/audit.py, evals/ablate.py and evals/trivial_baselines.py read
only `.env` and the environment. run_ab.py had learned this (`_resolve_api_key`); these three had not, so every
Anthropic call would have failed until the outage breaker stopped the run.

The worse half: with no OpenAI key each of the three went on without its GPT grader. The audit printed "Claude
only" and continued; the ablation and the trivial baselines dropped the GPT column without a word. Asked for two
graders, a run returned one, and the cross-family grader is the one whose result currently stands (ABC O.c.1).
Now a missing key stops the run with exit 2 before a client exists, and the estimate prices the plan that was
asked for, not the keys that happened to be present.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in ("src", "evals"):
    sys.path.insert(0, str(REPO / p))

import ablate  # noqa: E402
import api_keys  # noqa: E402
import audit  # noqa: E402
import costs  # noqa: E402
import trivial_baselines as tb  # noqa: E402

from cellarium import credentials, llm  # noqa: E402

STORED_AUDIT = REPO / "evals" / "results" / "audited.json"
VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
FAKE = {"anthropic": "sk-ant-test-not-a-real-key-0000", "openai": "sk-test-not-a-real-key-00000000"}


@pytest.fixture
def keychain(monkeypatch):
    """No key in `.env` or the environment; the stand-in keychain holds what the test puts in it. Nothing real is
    read, no client can be made, and teardown restores the environment exactly as it was."""
    for var in VARS.values():
        monkeypatch.setenv(var, "placeholder")     # records the real state first, so teardown restores it
        monkeypatch.delenv(var)
    monkeypatch.setattr(api_keys, "load_dotenv", lambda *a, **kw: False)
    held: dict = {}
    reads: list = []

    def load_into_env(*, override=False, provider=None):
        reads.append(provider)
        if provider in held:
            monkeypatch.setenv(VARS[provider], held[provider])
        return {}
    monkeypatch.setattr(credentials, "load_into_env", load_into_env)

    def no_client(*a, **kw):
        raise AssertionError("a client was made")
    monkeypatch.setattr(llm, "client", no_client)
    return held, reads


def _clients_allowed(monkeypatch):
    """Both clients as stand-ins. The `openai` package is a stand-in module too: CI does not install it, and the
    first version of these tests imported the real one, so they passed here and failed there (2026-11-24)."""
    import types
    monkeypatch.setattr(llm, "client", lambda **kw: "claude-client")
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda **kw: "openai-client"))


# --- the resolver ----------------------------------------------------------------------------------------------

def test_a_key_kept_only_in_the_keychain_is_found(keychain):
    held, reads = keychain
    held.update(FAKE)
    api_keys.require("anthropic", "openai")
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == FAKE["anthropic"]
    assert os.environ["OPENAI_API_KEY"] == FAKE["openai"]
    assert reads == ["anthropic", "openai"]


def test_a_missing_key_stops_the_run_and_says_where_to_put_it(keychain, capsys):
    held, _ = keychain
    held["anthropic"] = FAKE["anthropic"]
    with pytest.raises(SystemExit) as e:
        api_keys.require("anthropic", "openai", hint="To audit with Claude alone, pass --auditors claude.")
    assert e.value.code == 2
    said = capsys.readouterr()
    said = said.out + said.err
    assert "OPENAI_API_KEY" in said and "ANTHROPIC_API_KEY" not in said
    assert "Settings" in said and ".env" in said and "--auditors claude" in said


# --- the defect audit --------------------------------------------------------------------------------------------

def test_an_audit_asked_for_both_auditors_stops_when_the_gpt_key_is_missing(keychain, monkeypatch, capsys, tmp_path):
    held, _ = keychain
    held["anthropic"] = FAKE["anthropic"]
    monkeypatch.setattr(sys, "argv", ["audit.py", "--only-claude-zeros", str(STORED_AUDIT),
                                      "--out", str(tmp_path / "a.json")])
    with pytest.raises(SystemExit) as e:
        audit.main()
    assert e.value.code == 2
    out = capsys.readouterr().out
    assert "(Claude and GPT)" in out             # the estimate prices the plan asked for, not the keys present
    assert not (tmp_path / "a.json").exists()


def test_a_claude_only_audit_reads_only_the_anthropic_key(keychain, monkeypatch, tmp_path):
    held, reads = keychain
    held["anthropic"] = FAKE["anthropic"]
    _clients_allowed(monkeypatch)
    seen: dict = {}
    monkeypatch.setattr(audit, "run", lambda recs, out, **kw: seen.update(kw, n=len(recs)) or 0)
    monkeypatch.setattr(sys, "argv", ["audit.py", "--only-claude-zeros", str(STORED_AUDIT), "--auditors", "claude",
                                      "--out", str(tmp_path / "a.json")])
    assert audit.main() == 0
    assert reads == ["anthropic"]
    assert (seen["client"], seen["oai"], seen["n"]) == ("claude-client", None, 58)


def test_an_audit_with_both_keys_in_the_keychain_runs_both_auditors(keychain, monkeypatch, tmp_path):
    held, _ = keychain
    held.update(FAKE)
    _clients_allowed(monkeypatch)
    seen: dict = {}
    monkeypatch.setattr(audit, "run", lambda recs, out, **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["audit.py", "--only-claude-zeros", str(STORED_AUDIT),
                                      "--out", str(tmp_path / "a.json")])
    assert audit.main() == 0
    assert (seen["client"], seen["oai"]) == ("claude-client", "openai-client")


# --- the trivial baselines ---------------------------------------------------------------------------------------

def test_the_trivial_baselines_stop_when_the_gpt_key_is_missing(keychain, monkeypatch, capsys, tmp_path):
    held, _ = keychain
    held["anthropic"] = FAKE["anthropic"]
    monkeypatch.setattr(sys, "argv", ["trivial_baselines.py", "--out", str(tmp_path / "t.json")])
    with pytest.raises(SystemExit) as e:
        tb.main()
    assert e.value.code == 2
    full = costs.estimate_trivial(len(ablate.EXPLORATORY_IDS), len(tb.KINDS), gpt=True)
    assert f"{full['total_usd']['central']:.2f}" in capsys.readouterr().out   # priced with the GPT graders


def test_the_trivial_baselines_find_both_keys_in_the_keychain(keychain, monkeypatch, tmp_path):
    held, reads = keychain
    held.update(FAKE)
    _clients_allowed(monkeypatch)
    seen: dict = {}
    monkeypatch.setattr(tb, "run", lambda ids, out, **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["trivial_baselines.py", "--out", str(tmp_path / "t.json")])
    assert tb.main() == 0
    assert reads == ["anthropic", "openai"]
    assert (seen["client"], seen["oai"]) == ("claude-client", "openai-client")


# --- the ablation ------------------------------------------------------------------------------------------------

def test_an_ablation_without_the_rubric_needs_only_the_anthropic_key(keychain, monkeypatch, tmp_path):
    held, reads = keychain
    held["anthropic"] = FAKE["anthropic"]
    seen: dict = {}
    monkeypatch.setattr(ablate, "run", lambda *a, **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["ablate.py", "--configs", "full", "--no-rubric",
                                      "--out", str(tmp_path / "x.json")])
    assert ablate.main() == 0
    assert reads == ["anthropic"] and seen["rubric"] is False


def test_an_ablation_with_the_rubric_stops_when_the_gpt_key_is_missing(keychain, monkeypatch, tmp_path):
    held, _ = keychain
    held["anthropic"] = FAKE["anthropic"]
    monkeypatch.setattr(ablate, "run", lambda *a, **kw: pytest.fail("the sweep started without its GPT grader"))
    monkeypatch.setattr(sys, "argv", ["ablate.py", "--configs", "full", "--out", str(tmp_path / "x.json")])
    with pytest.raises(SystemExit) as e:
        ablate.main()
    assert e.value.code == 2
