"""The local credential vault (src/cellarium/credentials.py) and its Settings endpoints.

These tests exist to hold FOUR invariants that a credential feature has to keep, forever:

  I1  the key never enters the LLM context (there is no agent tool for it, and no prompt/tool output carries it);
  I2  the key never crosses the HTTP boundary — every response is masked-only;
  I3  nothing is written to disk in plaintext: with no SECURE keychain backend we refuse to persist at all;
  I4  every message leaving the module is redacted against the key.

Everything here runs with NO keyring backend and NO API key, which is exactly CI's situation — the vault is meant
to degrade to "can_persist: False" rather than fail. The fake key deliberately does NOT match CI's secret-scan
pattern (`sk-ant-` + 24 chars); it is short on purpose so a test fixture can never trip the scanner.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps"))

import pytest  # noqa: E402

from cellarium import credentials as C  # noqa: E402

FAKE = "sk-ant-notarealkey00lead"          # 22 chars: over _MIN_LEN, under the secret-scanner's 24-char tail
LOCAL = {"base_url": "http://127.0.0.1:8000"}   # the endpoints are loopback-only; TestClient's default Host is not


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Never touch the developer's real key or real keychain: isolate the env and force the no-backend path."""
    monkeypatch.delenv(C.ENV_VAR, raising=False)
    monkeypatch.setattr(C, "_SOURCE", None, raising=False)
    monkeypatch.setattr(C, "_IN_KEYCHAIN", False, raising=False)
    monkeypatch.setattr(C, "backend", lambda: {"name": None, "secure": False, "reason": "test: no backend"})
    yield


# ---------------------------------------------------------------- I2: masked-only, never the key
def test_status_never_contains_the_key():
    C.set_key(FAKE, persist=True)
    st = C.status()
    assert FAKE not in repr(st)                    # the whole structure, not just the obvious field
    assert st["configured"] and st["masked"] == "sk-ant-lead"[:7] + "…" + FAKE[-4:]
    assert st["source"] == "session"               # no secure backend -> not persisted (I3)


def test_mask_reveals_only_the_constant_prefix_and_last_four():
    assert C.mask(FAKE) == f"sk-ant-…{FAKE[-4:]}"
    assert C.mask("short") == "…"                  # too short to mask with margin -> reveal nothing
    assert C.mask(None) is None and C.mask("") is None


# ---------------------------------------------------------------- I3: refuse to persist insecurely
def test_no_secure_backend_means_session_only_and_nothing_written(monkeypatch):
    """The trap this guards: keyring silently selects a PLAINTEXT backend, we call set_password, and the UI's
    'saved to your keychain' becomes an unencrypted file. With secure=False we must never call keyring at all."""
    called = []
    monkeypatch.setitem(sys.modules, "keyring", type("K", (), {
        "set_password": staticmethod(lambda *a: called.append(a)),
        "get_password": staticmethod(lambda *a: None),
        "delete_password": staticmethod(lambda *a: None)})())
    st = C.set_key(FAKE, persist=True)
    assert called == []                            # never handed to an insecure backend
    assert st["can_persist"] is False and st["source"] == "session" and st["in_keychain"] is False


def test_plaintext_and_fail_backends_are_classified_insecure(monkeypatch):
    monkeypatch.undo()                             # use the REAL backend() for this one

    class _Plain: ...
    _Plain.__module__, _Plain.__qualname__ = "keyrings.alt.file", "PlaintextKeyring"

    class _Fail: ...
    _Fail.__module__, _Fail.__qualname__ = "keyring.backends.fail", "Keyring"

    class _Good:
        priority = 5
    _Good.__module__, _Good.__qualname__ = "keyring.backends.Windows", "WinVaultKeyring"

    for cls, secure in ((_Plain, False), (_Fail, False), (_Good, True)):
        monkeypatch.setitem(sys.modules, "keyring", type("K", (), {"get_keyring": staticmethod(lambda c=cls: c())})())
        b = C.backend()
        assert b["secure"] is secure, f"{b['name']} classified wrong"
        if not secure:
            assert b["reason"]                     # an insecure verdict must always say WHY, for the UI to show

    # the trap the wrapper hides: a ChainerBackend reports a healthy priority of its own, but the leaf that would
    # actually RECEIVE the write is a plaintext file. Judging only the wrapper would call this secure.
    class _Chainer:
        priority = 10
        backends = [_Plain(), _Fail()]
    _Chainer.__module__, _Chainer.__qualname__ = "keyring.backends.chainer", "ChainerBackend"
    _Plain.priority, _Fail.priority = 0.5, 0.0     # plaintext wins the chain -> it is what gets written to
    monkeypatch.setitem(sys.modules, "keyring", type("K", (), {"get_keyring": staticmethod(_Chainer)})())
    b = C.backend()
    assert b["secure"] is False and "unencrypted" in b["reason"]
    assert "keyrings.alt.file" in b["name"]        # the UI names the LEAF, so the reason it gives is the true one



# The real backend class each platform's keyring selects, and the verdict this code must reach. This is the
# "does it work on every OS?" question turned into an assertion: a secure keychain persists, and everywhere else
# we degrade to session-only with an honest reason — never a silent plaintext downgrade, never a crash.
_PLATFORM_BACKENDS = [
    ("Windows 10/11",          "keyring.backends.Windows",       "WinVaultKeyring",   5.0, True),
    ("macOS",                  "keyring.backends.macOS",         "Keyring",           5.0, True),
    ("Linux / GNOME",          "keyring.backends.SecretService", "Keyring",           5.0, True),
    ("Linux / KDE",            "keyring.backends.kwallet",       "DBusKeyring",       4.9, True),
    ("headless Linux, Docker", "keyring.backends.fail",          "Keyring",           0.0, False),
    ("keyrings.alt installed", "keyrings.alt.file",              "PlaintextKeyring",  0.5, False),
]


@pytest.mark.parametrize("label,mod,cls,prio,secure", _PLATFORM_BACKENDS)
def test_backend_verdict_per_platform(monkeypatch, label, mod, cls, prio, secure):
    monkeypatch.undo()                                 # exercise the REAL backend() classifier

    class _B:
        priority = prio
    _B.__module__, _B.__qualname__ = mod, cls
    monkeypatch.setitem(sys.modules, "keyring", type("K", (), {"get_keyring": staticmethod(_B)})())
    b = C.backend()
    assert b["secure"] is secure, f"{label} ({mod}.{cls}) classified wrong"
    assert bool(b["reason"]) is not secure              # insecure must always explain itself; secure says nothing


def test_a_secure_backend_persists_and_clear_removes(monkeypatch):
    store = {}
    monkeypatch.setattr(C, "backend", lambda: {"name": "test.Secure", "secure": True, "reason": ""})
    monkeypatch.setitem(sys.modules, "keyring", type("K", (), {
        "set_password": staticmethod(lambda s, a, v: store.__setitem__((s, a), v)),
        "get_password": staticmethod(lambda s, a: store.get((s, a))),
        "delete_password": staticmethod(lambda s, a: store.pop((s, a), None))})())
    st = C.set_key(FAKE, persist=True)
    assert st["source"] == "keychain" and st["in_keychain"] and store[(C.SERVICE, C.ACCOUNT)] == FAKE
    st = C.clear()
    assert store == {} and st["configured"] is False and os.environ.get(C.ENV_VAR) is None


def test_environment_wins_over_the_keychain_and_is_not_managed_here(monkeypatch):
    """An exported variable / .env is the more explicit signal, so load_into_env must not clobber it — and the UI
    must not offer to 'Remove' a key Cellarium didn't put there."""
    monkeypatch.setenv(C.ENV_VAR, FAKE)
    monkeypatch.setattr(C, "backend", lambda: {"name": "test.Secure", "secure": True, "reason": ""})
    monkeypatch.setattr(C, "_read_keychain", lambda: "sk-ant-adifferentstored")
    st = C.load_into_env()
    assert os.environ[C.ENV_VAR] == FAKE           # the environment survived
    assert st["source"] == "environment" and st["managed_here"] is False


# ---------------------------------------------------------------- input validation
@pytest.mark.parametrize("bad", ["", "   ", "sk-ant short with spaces", "sk-tooshort"])
def test_malformed_pastes_are_rejected_without_quoting_the_value(bad):
    with pytest.raises(ValueError) as e:
        C.set_key(bad)
    assert bad.strip() not in str(e.value) or not bad.strip()
    assert os.environ.get(C.ENV_VAR) is None       # a rejected paste never reaches the environment


# ---------------------------------------------------------------- I4: redaction
def test_every_message_is_redacted_against_the_key(monkeypatch):
    monkeypatch.setenv(C.ENV_VAR, FAKE)
    msg = C._redact(f"boom: the server said {FAKE} was bad")
    assert FAKE not in msg and "[redacted]" in msg


def test_a_keychain_write_failure_reports_without_leaking(monkeypatch):
    def _boom(*a):
        raise RuntimeError(f"could not store {FAKE} in the vault")   # an SDK that quotes what it was handed
    monkeypatch.setattr(C, "backend", lambda: {"name": "test.Secure", "secure": True, "reason": ""})
    monkeypatch.setitem(sys.modules, "keyring", type("K", (), {
        "set_password": staticmethod(_boom), "get_password": staticmethod(lambda *a: None),
        "delete_password": staticmethod(lambda *a: None)})())
    st = C.set_key(FAKE, persist=True)
    assert FAKE not in repr(st) and "[redacted]" in st["persist_error"]
    assert st["source"] == "session"               # honest: it works now, but it did not persist


def test_probe_without_a_key_is_a_clean_no():
    assert C.probe() == {"ok": False, "detail": "No key is configured."}


# ---------------------------------------------------------------- I1: the key never reaches the model
def test_no_agent_tool_can_read_or_write_the_key():
    """Containment, the same shape as the launch airlock: the capability does not exist in the dispatch table, so
    no prompt can talk Cellwright into using it. If someone ever adds one, this fails."""
    from cellarium import test_registry, tools
    names = {t["name"] for t in tools.TOOLS} | set(tools._DISPATCH)
    assert not [n for n in names if "key" in n.lower() or "secret" in n.lower() or "credential" in n.lower()]
    assert test_registry.unclassified_tools({t["name"] for t in tools.TOOLS}) == []   # reverse invariant still holds


def test_the_key_is_absent_from_the_agent_prompt_and_from_tool_output(monkeypatch):
    """A sentinel in the environment must not surface in anything the model sees: not the system prompt, not the
    first user turn, and not the output of the tools that report machine state."""
    monkeypatch.setenv(C.ENV_VAR, FAKE)
    from cellarium import agent, tools
    seen = agent.SYSTEM + agent.first_user_content("Is pfkA essential?", None)
    assert FAKE not in seen
    for fn in (tools.system_resources, tools.estimate_sim_resources):
        try:
            out = repr(fn())
        except TypeError:
            out = repr(fn(n_runs=2, parallel=1))
        assert FAKE not in out, f"{fn.__name__} echoed the environment"


def test_credentials_is_not_reachable_from_the_agent_module():
    """agent.py must not import the vault — the module boundary is what makes I1 checkable rather than hopeful."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "cellarium", "agent.py"), encoding="utf-8").read()
    assert "credentials" not in src


# ---------------------------------------------------------------- the HTTP surface
def _client(csrf: bool = True):
    import server
    from starlette.testclient import TestClient
    c = TestClient(server.app, **LOCAL)
    if csrf:
        c.headers.update({"x-cellarium-csrf": server._CSRF})   # what the SPA reads out of index.html
    return c


def test_a_mutating_call_without_the_page_token_is_refused():
    """Sec-Fetch-Site fails open when absent (old Safari, embedded WebViews) and a legacy form POST can omit
    Origin too, so the write path additionally demands proof the caller actually loaded our page."""
    c = _client(csrf=False)
    assert c.get("/api/settings").status_code == 200                       # reads stay open
    for path in ("/api/settings_key", "/api/settings_key_delete", "/api/settings_key_test"):
        r = c.post(path, json={"key": FAKE})
        assert r.status_code == 403 and "page token" in r.json()["error"], path
    assert c.post("/api/settings_key", json={"key": FAKE},
                  headers={"x-cellarium-csrf": "wrong"}).status_code == 403


def test_the_page_token_is_stamped_into_the_shell():
    import server
    html = _client().get("/").text
    assert "__CSRF__" not in html and server._CSRF in html                 # substituted, not left as a placeholder


def test_endpoints_never_echo_the_key_in_any_response(monkeypatch):
    """The end-to-end form of I2: POST a key, then assert the literal value appears in NO response body."""
    monkeypatch.setattr(C, "backend", lambda: {"name": None, "secure": False, "reason": "test: no backend"})
    c = _client()
    bodies = [c.post("/api/settings_key", json={"key": FAKE}).text,
              c.get("/api/settings").text,
              c.post("/api/settings_key_test", json={}).text,
              c.post("/api/settings_key_delete", json={}).text]
    for b in bodies:
        assert FAKE not in b
    assert "sk-ant-…" in bodies[0]                 # ...but the mask IS returned, so the user can see WHICH key


def test_a_malformed_key_gets_a_400_not_a_500():
    r = _client().post("/api/settings_key", json={"key": "nope"})
    assert r.status_code == 400 and "short" in r.json()["error"]


def test_credential_endpoints_refuse_a_non_loopback_or_cross_site_caller():
    """DNS rebinding arrives carrying the attacker's hostname; a cross-site form post carries Sec-Fetch-Site.
    Both are refused before any credential work happens."""
    import server
    from starlette.testclient import TestClient
    assert TestClient(server.app, base_url="http://evil.example").get("/api/settings").status_code == 403
    c = _client()
    assert c.get("/api/settings", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert c.post("/api/settings_key", json={"key": FAKE},
                  headers={"origin": "http://evil.example"}).status_code == 403
    assert c.get("/api/settings").status_code == 200          # the local caller still works


def test_an_origin_that_merely_starts_with_a_loopback_name_is_refused():
    """From the adversarial review, proven against this app: the Origin check was a string PREFIX match, so
    `http://localhost.evil.example` satisfied `startswith("http://localhost")` — an attacker only had to register
    a name beginning with a loopback literal. No DNS rebinding required."""
    c = _client()
    for evil in ("http://localhost.evil.example", "http://127.0.0.1.evil.example",
                 "https://127.0.0.1.attacker.tld", "http://localhost@evil.example"):
        assert c.get("/api/settings", headers={"origin": evil}).status_code == 403, evil
        assert c.post("/api/settings_key", json={"key": FAKE}, headers={"origin": evil}).status_code == 403, evil
    for good in ("http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000"):
        assert c.get("/api/settings", headers={"origin": good}).status_code == 200, good


def test_clear_removes_from_the_keychain_even_when_the_backend_looks_insecure(monkeypatch):
    """From the adversarial review: gating the delete on the CURRENT secure verdict meant a key stored while a
    keychain was available could survive a later run where it isn't — while the UI reported it removed."""
    store = {(C.SERVICE, C.ACCOUNT): FAKE}
    monkeypatch.setitem(sys.modules, "keyring", type("K", (), {
        "set_password": staticmethod(lambda s, a, v: store.__setitem__((s, a), v)),
        "get_password": staticmethod(lambda s, a: store.get((s, a))),
        "delete_password": staticmethod(lambda s, a: store.pop((s, a), None))})())
    C.clear()                                       # backend() is patched insecure by the autouse fixture
    assert store == {}, "Remove must never report a deletion it did not perform"


def test_a_chainer_is_condemned_by_any_insecure_child_not_just_the_strongest(monkeypatch):
    """A chainer falls through when a backend declines the write, so a read-only plugin at priority 9 in front of
    a plaintext backend at 0.5 means PLAINTEXT receives the key. Judging only the top child called that secure."""
    monkeypatch.undo()

    class _Plugin:                                   # high priority, but read-only: declines the write
        priority = 9.0
    _Plugin.__module__, _Plugin.__qualname__ = "keyrings.envvars", "Keyring"

    class _Plain:
        priority = 0.5
    _Plain.__module__, _Plain.__qualname__ = "keyrings.alt.file", "PlaintextKeyring"

    class _Chain:
        priority = 10
        backends = [_Plugin(), _Plain()]
    _Chain.__module__, _Chain.__qualname__ = "keyring.backends.chainer", "ChainerBackend"

    monkeypatch.setitem(sys.modules, "keyring", type("K", (), {"get_keyring": staticmethod(_Chain)})())
    b = C.backend()
    assert b["secure"] is False and "unencrypted" in b["reason"] and "chain" in b["reason"]


def test_the_settings_surface_is_mounted_in_the_shell():
    html = _client().get("/").text
    for mount in ('id="settingsBtn"', 'id="settingsDrawer"', 'id="settingsBody"'):
        assert mount in html, f"index.html is missing {mount} — the Settings panel won't mount"
    app_js = open(os.path.join(os.path.dirname(__file__), "..", "apps", "web", "app.js"), encoding="utf-8").read()
    assert 'inp.type = "password"' in app_js                   # the field is never a plain text input...
    assert 'inp.type = "text"' not in app_js                   # ...and nothing flips it back (no reveal toggle)
    assert "cellarium.key" not in app_js                       # no client-side copy of the credential
    assert 'inp.value = ""' in app_js                          # the plaintext leaves the DOM once it is sent


def test_a_stale_page_token_is_refused_after_a_server_restart(monkeypatch):
    """H-13(e). `_CSRF` is minted once at import, so a RESTART rotates it — and a browser tab left open still
    holds the old one. That flow was never exercised: the copy promises a clear "reload the app" path, but
    nothing proved the stale token is actually refused rather than, say, matching a regenerated-but-equal value
    or slipping through a comparison against a falsy default.

    Faithfully simulated in-process, no subprocess: the handler reads `_CSRF` as a module global at request time
    (apps/server.py:544), so rebinding it IS what a restart looks like to an already-loaded page. The client
    below keeps the pre-restart token."""
    import secrets

    import server
    stale = _client()                                   # holds the token minted at import
    old = server._CSRF
    monkeypatch.setattr(server, "_CSRF", secrets.token_urlsafe(32))   # "restart"
    assert server._CSRF != old

    for path in ("/api/settings_key", "/api/settings_key_delete", "/api/settings_key_test"):
        r = stale.post(path, json={"key": FAKE})
        assert r.status_code == 403, f"{path} accepted a pre-restart token"
        assert "page token" in r.json()["error"], path
    assert stale.get("/api/settings").status_code == 200               # reads stay open, as before

    # ...and the remedy the copy promises actually works: re-reading the shell hands back the NEW token.
    fresh = _client()
    assert server._CSRF in fresh.get("/").text
    assert fresh.post("/api/settings_key_test", json={"key": FAKE}).status_code != 403


# ------------------------------------------------------------------------------------------------------------
# DURABILITY — does a key a user saves actually survive the app closing?
#
# Everything above this line runs against a FAKE keyring, which is right for testing logic and useless for
# testing persistence: a stub that remembers a value in a dict will "persist" no matter how broken the real
# backend is. The user-facing fear — "every time I launch the app I have to paste my key again" — is a claim
# about a REAL vault and a NEW PROCESS, so it is tested that way or not at all.
#
# The whole section writes to a throwaway SERVICE namespace, never `credentials.SERVICE`. Running the suite
# must not touch, overwrite or delete the key the user actually stored.
# ------------------------------------------------------------------------------------------------------------

import subprocess  # noqa: E402
import sys as _sys  # noqa: E402
import textwrap  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

_FAKE_KEY = "sk-ant-test-" + "0" * 40          # long enough for _MIN_LEN, obviously not a real credential


# The autouse `_clean_env` fixture above stubs `backend()` to "no backend" for EVERY test in this file, so the
# suite can never touch the developer's real keychain. That is exactly right as a default and exactly wrong
# here, since these tests are ABOUT the real vault. Capture the genuine function at import — before any
# fixture rebinds the attribute — and hand it back only inside this section.
_REAL_BACKEND = C.backend


def _real_secure_backend() -> bool:
    try:
        return bool(_REAL_BACKEND()["secure"])
    except Exception:
        return False


@pytest.fixture()
def real_keychain(monkeypatch):
    """Undo the file-wide no-backend stub for one test."""
    monkeypatch.setattr(C, "backend", _REAL_BACKEND)
    return _REAL_BACKEND()


@pytest.fixture()
def scratch_service():
    """A unique keychain namespace, deleted afterwards whatever happens."""
    from cellarium import credentials
    name = f"cellarium-test-{uuid.uuid4().hex[:12]}"
    yield name
    try:
        import keyring
        keyring.delete_password(name, credentials.ACCOUNT)
    except Exception:
        pass


@pytest.mark.skipif(not _real_secure_backend(), reason="no secure OS keychain here (CI, headless)")
def test_a_saved_key_is_found_by_a_BRAND_NEW_process(scratch_service, real_keychain, monkeypatch):
    """THE test behind "my key disappears when I restart".

    Writes through the same `set_key` the Settings panel calls, then reads back from a subprocess that shares
    no memory with this one — which is what "close the app and open it again" actually is.
    """
    from cellarium import credentials
    monkeypatch.setattr(credentials, "SERVICE", scratch_service)
    monkeypatch.delenv(credentials.ENV_VAR, raising=False)
    st = credentials.set_key(_FAKE_KEY, persist=True)
    assert st["in_keychain"], f"set_key did not persist: {st.get('persist_error') or st}"

    reader = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, "src")
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from cellarium import credentials
        credentials.SERVICE = {scratch_service!r}
        st = credentials.load_into_env()
        # masked only — a test that printed the key would be the leak it is meant to prevent
        print("FOUND" if st["configured"] else "MISSING", st["source"], st["masked"])
    """)
    proc = subprocess.run([_sys.executable, "-c", reader], capture_output=True, text=True, timeout=300)
    out = proc.stdout.strip()
    assert out.startswith("FOUND"), (
        f"a key saved through the Settings panel was NOT visible to a fresh process — this is exactly the "
        f"'I have to paste my key every launch' symptom. subprocess said: {out!r} / {proc.stderr[-400:]!r}")
    assert "keychain" in out
    assert _FAKE_KEY not in proc.stdout and _FAKE_KEY not in proc.stderr, "the subprocess echoed the key"


@pytest.mark.skipif(not _real_secure_backend(), reason="no secure OS keychain here (CI, headless)")
def test_nothing_but_an_explicit_remove_deletes_the_entry(scratch_service, real_keychain, monkeypatch):
    """A stored key must survive every ordinary operation. `clear()` is the ONE path that removes it, and it
    has exactly one caller (`POST /api/settings_key_delete`, the Remove button)."""
    from cellarium import credentials
    monkeypatch.setattr(credentials, "SERVICE", scratch_service)
    monkeypatch.delenv(credentials.ENV_VAR, raising=False)
    credentials.set_key(_FAKE_KEY, persist=True)

    import keyring
    for _ in range(3):                      # the reads the UI does on every settings poll
        credentials.status()
        credentials.load_into_env(override=True)
        credentials.backend()
    assert keyring.get_password(scratch_service, credentials.ACCOUNT) == _FAKE_KEY, (
        "an ordinary status/reload cycle removed the stored key")

    credentials.clear()
    assert keyring.get_password(scratch_service, credentials.ACCOUNT) is None


def test_delete_has_exactly_one_caller_and_it_is_the_remove_button():
    """Pins the blast radius. If a second caller of `clear()` ever appears, the "keys do not vanish" promise
    needs re-checking rather than re-asserting."""
    server = Path("apps/server.py").read_text(encoding="utf-8")
    assert server.count("credentials.clear()") == 1
    assert "settings_key_delete" in server


def test_the_remove_button_requires_two_clicks():
    """One misclick used to delete the key from the OS keychain with no confirmation, which is indistinguishable
    afterwards from the app losing it. The control arms on the first click and reverts if ignored."""
    js = Path("apps/web/app.js").read_text(encoding="utf-8")
    i = js.index('el("button", "set-btn danger", "Remove")')
    handler = js[i:i + 900]
    assert "click again" in handler.lower(), "the Remove button deletes on a single click"
    assert "settings_key_delete" in handler
    assert handler.index("click again") < handler.index("settings_key_delete"), (
        "the arming step must come BEFORE the delete call, not after it")


def test_an_expired_key_is_not_something_the_vault_can_notice():
    """Recorded because it was asked and the answer is structural, not empirical.

    An OS credential store holds an opaque blob. It has no notion of an Anthropic key's validity window, and
    Anthropic revoking a key server-side cannot reach into Windows Credential Manager. So "the key expired"
    can explain an API 401 — `probe()` reports that as 'The Anthropic API rejected this key' — and can NEVER
    explain a MISSING vault entry. This test pins the only two things that can: an explicit clear(), or a
    write that never happened.
    """
    from cellarium import credentials
    src = Path("src/cellarium/credentials.py").read_text(encoding="utf-8")
    assert src.count("delete_password") == 1, "a second deletion path appeared"
    assert "def clear()" in src
    assert "expir" not in src.lower(), "nothing here reasons about expiry, and nothing should"
    assert credentials.probe()  # shape only; no network assertion
