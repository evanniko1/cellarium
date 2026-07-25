"""Defense-in-depth: the credential scrubber and the three funnels that carry it.

The vault (tests/test_credentials.py) guarantees the key is never PUT anywhere it shouldn't be. This file guards
the other half — that if one ever arrives somewhere by accident, it does not become durable. A 6-agent leak-surface
audit of this repo found the paths these tests pin, including one confirmed empirically: a key pasted with a
trailing newline makes httpx raise `LocalProtocolError: Illegal header value b'sk-ant-…\\n'`, and while the
outermost SDK exception is clean, `traceback.format_exc()` is not — which is exactly what `exc_info=True` emits.

Fake tokens here are shaped like the real thing but are not real, and are kept under the 24-char tail that CI's
secret scan matches so a fixture can never trip the scanner.
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps"))

from cellarium import redact  # noqa: E402

ANT = "sk-ant-notarealkey00lead"
OPENAI = "sk-proj0notarealopenaikey00"
HF = "hf_notarealhuggingfacetok"


def test_known_token_shapes_are_scrubbed():
    for tok in (ANT, OPENAI, HF, "ghp_notarealgithubtokenvalue"):
        out = redact.scrub(f"failed with {tok} at the edge")
        assert tok not in out and redact.MARK in out


def test_the_empirical_leak_shape_is_caught():
    """The exact text the audit reproduced against this repo's own venv."""
    msg = f"httpcore.LocalProtocolError: Illegal header value b'{ANT}\\n'"
    assert ANT not in redact.scrub(msg)


def test_bearer_and_x_api_key_headers_are_scrubbed():
    assert "abcdefghijklmnopqrstuvwx" not in redact.scrub("Authorization: Bearer abcdefghijklmnopqrstuvwx")
    assert "abcdefghijklmnopqrstuvwx" not in redact.scrub('"x-api-key": "abcdefghijklmnopqrstuvwx"')


def test_ordinary_scientific_text_is_untouched():
    """A false positive silently corrupts results, so the patterns must not fire on real output."""
    for clean in ("pfkA knockout reduced growth 0.42 -> 0.31 h^-1", "shard sk-1 was not a token",
                  "gene b1723, seed 12345, generation 4", "hf_v1 is a column name"):
        assert redact.scrub(clean) == clean


def test_scrub_obj_walks_structures_and_blanks_secret_field_names():
    obj = {"rows": [{"note": f"key {ANT}"}], "api_key": "whatever-shape-this-is", "growth": 0.42, "n": 3}
    out = redact.scrub_obj(obj)
    assert ANT not in json.dumps(out)
    assert out["api_key"] == redact.MARK          # caught by NAME, not shape — covers unknown token formats
    assert out["growth"] == 0.42 and out["n"] == 3   # non-strings pass through untouched


def test_scrub_obj_survives_pathological_nesting():
    deep = cur = {}
    for _ in range(40):
        cur["x"] = {}
        cur = cur["x"]
    redact.scrub_obj(deep)                        # must return, not blow the stack


# ---------------------------------------------------------------- funnel 1: the logging filter (exc_info)
def test_the_log_filter_scrubs_a_chained_traceback(caplog):
    """A Filter, not a Formatter: it is the only hook that can rewrite rendered exc_info text."""
    redact.install_log_filter("cellarium.tools")
    log = logging.getLogger("cellarium.tools")
    try:
        try:
            raise ValueError(f"Illegal header value b'{ANT}'")
        except ValueError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError:
        with caplog.at_level(logging.ERROR, logger="cellarium.tools"):
            log.error("tool %r raised", "some_tool", exc_info=True)
    rendered = "".join(r.exc_text or "" for r in caplog.records) + caplog.text
    assert ANT not in rendered and redact.MARK in rendered


def test_installing_the_filter_twice_does_not_stack_it():
    redact.install_log_filter("cellarium.tools")
    redact.install_log_filter("cellarium.tools")
    lg = logging.getLogger("cellarium.tools")
    assert sum(isinstance(f, redact._Filter) for f in lg.filters) == 1


def test_tools_installs_the_filter_on_import():
    from cellarium import tools  # noqa: F401
    assert any(isinstance(f, redact._Filter) for f in logging.getLogger("cellarium.tools").filters)


# ---------------------------------------------------------------- funnel 2: everything sent to the browser
def test_the_browser_funnel_scrubs_tool_payloads():
    """_jsonsafe is what every streamed tool input/output passes through before the SPA writes it to localStorage."""
    import server
    out = server._jsonsafe({"tool": "x", "output": {"note": f"boom {ANT}", "token": "some-opaque-value-here"}})
    blob = json.dumps(out)
    assert ANT not in blob and "some-opaque-value-here" not in blob


def test_the_streamed_error_text_is_scrubbed():
    import server
    assert ANT not in server._safe_err(ValueError(f"Illegal header value b'{ANT}'"))


# ---------------------------------------------------------------- funnel 3: the model's context
def test_the_llm_context_funnel_scrubs_a_tool_result():
    """_truncate_tool_result is the single door every tool result walks through into the message history — which
    is re-sent to the model each turn, persisted to SQLite, and carried past compaction."""
    from cellarium import agent
    s = agent._truncate_tool_result({"error": f"failed: {ANT}", "rows": [1, 2, 3]}, cap=100_000)
    assert ANT not in s and redact.MARK in s


def test_the_context_funnel_still_truncates_after_scrubbing():
    """The scrub must not disturb DD-ENG-2's structural trim: big lists still shrink and the JSON stays valid."""
    from cellarium import agent
    s = agent._truncate_tool_result({"rows": [{"g": f"b{i:04d}", "v": i} for i in range(2000)]}, cap=2000)
    assert len(s) <= 2200 and json.loads(s)["rows"]


# ---------------------------------------------------------------- the committed binary CI's scanner cannot see
def test_no_committed_binary_carries_a_key_shaped_string():
    """CI's secret scan is `git grep -nIE …`, and -I SKIPS binary files. data/sessions.seed.db is a tracked SQLite
    snapshot written from LIVE recorded transcripts by scripts/record_demo_sessions.py, so it is exactly the
    tracked file a key could reach while staying invisible to the scanner. Scan its bytes directly."""
    import re
    root = os.path.join(os.path.dirname(__file__), "..")
    pat = re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{32,}|hf_[A-Za-z0-9]{30,}")
    for rel in ("data/sessions.seed.db",):
        p = os.path.join(root, *rel.split("/"))
        if not os.path.exists(p):
            continue                                   # a fresh clone may not have bootstrapped it yet
        with open(p, "rb") as fh:
            assert not pat.search(fh.read()), f"{rel} contains a key-shaped string — rotate it and rebuild the seed"


# ---------------------------------------------------------------- funnel 4: the durable Council error row
def test_a_failed_council_run_persists_a_scrubbed_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CELLARIUM_SESSIONS_DB", str(tmp_path / "s.db"))
    import hypotheses
    store = hypotheses.HypothesisStore()
    rid = "h_test1"
    store.create(rid, "does argS matter?", model="test")
    store.fail(rid, f"APIConnectionError: Illegal header value b'{ANT}'")
    row = store.get(rid)
    assert ANT not in json.dumps(row) and redact.MARK in json.dumps(row)
