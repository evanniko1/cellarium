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
    tok = "eyJhbGci0iJIUzI1NiIsInR5c"                 # token-shaped: long, mixed case, contains digits
    assert tok not in redact.scrub(f"Authorization: Bearer {tok}")
    assert tok not in redact.scrub(f'"x-api-key": "{tok}"')


def test_bearer_does_not_fire_on_ordinary_prose():
    """This scrub runs over every saved transcript, so a false positive silently corrupts scientific text. An
    all-alphabetic word after 'bearer' is English, not a token — real bearer tokens always carry digits."""
    for clean in ("the bearer responsibilities of the operon", "Bearer disambiguation matters here",
                  "bearer of the transcriptional signal"):
        assert redact.scrub(clean) == clean


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


# ---------------------------------------------------------------- H-9(b): credentials stripped from child processes
def test_child_env_removes_secrets_but_keeps_the_platform_variables(monkeypatch):
    """COPY-and-remove, not build-from-scratch. A minimal env breaks children on Windows (no SYSTEMROOT) and loses
    the PATH that finds docker/git everywhere else — so the test pins BOTH halves: secrets gone, platform intact."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANT)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI)
    monkeypatch.setenv("HF_TOKEN", HF)
    env = redact.child_env()
    for gone in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HF_TOKEN"):
        assert gone not in env
    assert ANT not in repr(env)
    for keep in ("PATH", "SYSTEMROOT" if os.name == "nt" else "HOME"):
        if keep in os.environ:                         # present on every real platform; guard for exotic CI
            assert keep in env, f"{keep} must survive — a child process needs it to start"
    assert "WCECOLI_DOCKER" not in redact.child_env({"WCECOLI_DOCKER": "x"}, "WCECOLI_DOCKER")   # extra removals


def test_every_subprocess_call_site_passes_a_scrubbed_env():
    """A new subprocess.run without env=redact.child_env() silently re-opens the hole; fail here if one appears."""
    import re
    root = os.path.join(os.path.dirname(__file__), "..", "src", "cellarium")
    offenders = []
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".py"):
            continue
        src = open(os.path.join(root, fn), encoding="utf-8").read()
        for m in re.finditer(r"subprocess\.(run|Popen|check_output|check_call)\(", src):
            tail = src[m.start():m.start() + 400]
            if "child_env()" not in tail.split("\n\n")[0]:
                offenders.append(f"{fn}:{src[:m.start()].count(chr(10)) + 1}")
    assert not offenders, f"subprocess call(s) without a scrubbed env: {offenders}"


# ---------------------------------------------------------------- H-9(a): the outbound egress path
def test_web_get_refuses_headers_outside_the_allow_list(monkeypatch):
    from cellarium import skills
    sent = []
    monkeypatch.setattr(skills.urllib.request, "build_opener", lambda *a: sent.append(a))   # must never be reached
    for bad in ({"Authorization": "Bearer x"}, {"Cookie": "s=1"}, {"X-Api-Key": "x"}):
        r = skills.web_get("https://api.openalex.org/works", headers=bad)
        assert "not permitted" in r["error"]
    assert sent == [], "a refused fetch must not open a connection"
    assert "allow-list" in skills.web_get("https://not-allowed.example/x",
                                          headers={"Accept": "application/json"})["error"]


def test_web_get_refuses_a_credential_shaped_url_or_header():
    from cellarium import skills
    assert "credential-shaped" in skills.web_get(f"https://api.openalex.org/w?x={ANT}")["error"]
    assert "credential-shaped" in skills.web_get("https://api.openalex.org/w",
                                                 headers={"User-Agent": f"x {ANT}"})["error"]


def test_web_get_refuses_non_http_schemes():
    from cellarium import skills
    for u in ("file:///etc/passwd", "ftp://api.openalex.org/x", "gopher://api.openalex.org/x"):
        assert "error" in skills.web_get(u)


def test_a_redirect_off_the_allow_list_is_refused():
    """The bypass the host allow-list did not cover: urllib follows 30x by default, so an allow-listed host that
    redirects to an arbitrary one would sail straight through. Every hop is re-checked now."""
    import urllib.error

    from cellarium import skills
    h = skills._AllowListRedirects()
    try:
        h.redirect_request(None, None, 302, "Found", {}, "https://evil.example/steal")
        raise AssertionError("a redirect to a non-allow-listed host must be refused")
    except urllib.error.HTTPError as e:
        assert "non-allow-listed" in str(e)


# ---------------------------------------------------------------- H-9(c): the two durable persistence paths
def test_the_session_store_scrubs_before_it_persists(tmp_path):
    """The most durable sink in the app: the model's full context, written to disk and replayed on every turn."""
    from sessions import SessionStore
    st = SessionStore(str(tmp_path / "s.db"))
    st.put("s_x", {"model": "m", "title": "t",
                   "messages": [{"role": "user", "content": f"oops I pasted {ANT}"}]})
    raw = open(tmp_path / "s.db", "rb").read()
    assert ANT.encode() not in raw and redact.MARK.encode() in raw


def test_a_failed_launch_persists_a_scrubbed_error():
    from cellarium import launch  # noqa: F401
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "cellarium", "launch.py"), encoding="utf-8").read()
    assert "redact.scrub(str(exc))" in src           # the queue JSON is served by /api/queue and lives on disk


# ---------------------------------------------------------------- H-9(d): the tracked seed snapshot
def test_the_seed_writer_refuses_a_transcript_carrying_a_key():
    src = open(os.path.join(os.path.dirname(__file__), "..", "scripts", "record_demo_sessions.py"),
               encoding="utf-8").read()
    i = src.index("if write_seed:")
    guard = src[i:i + 700]
    assert "looks_like_secret" in guard and "REFUSED" in guard
    assert guard.index("looks_like_secret") < guard.index("SessionStore(SEED)")   # refuse BEFORE writing


# ---------------------------------------------------------------- from the adversarial review (wf_119eb7a2)
def test_a_shapeless_key_is_scrubbed_once_the_vault_registers_it():
    """Patterns only know KNOWN prefixes. A gateway / LiteLLM / Bedrock-proxy token is just 32 hex chars, so the
    vault hands the literal to the scrubber; without that, every funnel would pass it straight through."""
    opaque = "9f2b7c41d0e84a6fbb35c7e2a1d90f4c"
    assert redact.scrub(f"boom {opaque}") == f"boom {opaque}"       # invisible to the patterns, as expected
    redact.register_secret(opaque)
    try:
        assert opaque not in redact.scrub(f"boom {opaque}")
        assert opaque not in json.dumps(redact.scrub_obj({"e": f"boom {opaque}"}))
    finally:
        redact.forget_secret(opaque)
    assert redact.scrub(f"boom {opaque}") == f"boom {opaque}"       # forgotten again after clear()


def test_register_secret_ignores_values_too_short_to_replace_safely():
    redact.register_secret("abc")
    try:
        assert redact.scrub("abc def abc") == "abc def abc"          # replacing a 3-char string would wreck text
    finally:
        redact.forget_secret("abc")


def test_the_funnels_scrub_a_secret_used_as_a_dict_key_or_buried_deep():
    """scrub_obj walks VALUES and stops at a depth guard; the serialised final pass is what closes both."""
    import server

    from cellarium import agent
    deep = cur = {}
    for _ in range(16):
        cur["x"] = {}
        cur = cur["x"]
    cur["leak"] = f"boom {ANT}"
    for blob in (agent._truncate_tool_result({"d": deep, f"key-{ANT}": 1}, cap=1_000_000),
                 json.dumps(server._jsonsafe({"d": deep, f"key-{ANT}": 1}))):
        assert ANT not in blob


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
