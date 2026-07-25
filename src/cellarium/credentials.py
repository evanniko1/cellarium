"""The local credential vault — the ONE place Cellarium reads or writes the Anthropic API key.

Why this exists. Every entry point (apps/server.py, the CLI, the eval runners) constructs `anthropic.Anthropic()`
with no explicit api_key, so the SDK reads ANTHROPIC_API_KEY out of the process environment. Historically the only
way to set it was an exported shell variable or a repo-root .env — correct, but a CLI-shaped wall in front of an
app whose whole point is that you can clone it and click through the glass box. This module adds an in-app path
that is *at least as safe as* the .env it replaces: the key goes to the OS keychain (Windows Credential Manager /
macOS Keychain / Linux Secret Service) via `keyring`, and is injected into os.environ once at boot so all twelve
existing `anthropic.Anthropic()` call sites keep working untouched.

The invariants (each one asserted in tests/test_credentials.py):

  I1  The key never enters the LLM context. There is deliberately NO agent tool for this module — Cellwright can
      neither read nor set it. That is the same containment that keeps the agent away from /api/approve: the
      capability simply does not exist in its dispatch table, so it cannot be prompted into using it.
  I2  Nothing here returns the key over HTTP. `status()` is masked-only and is the only shape that crosses the
      boundary; the raw value is reachable solely through the private `_read_keychain()`, whose one caller
      populates os.environ for the SDK.
  I3  Nothing here logs, prints, or writes the key to disk in plaintext. If no SECURE keychain backend exists we
      refuse to persist AT ALL (session-only, gone when the server stops) rather than silently downgrade the
      promise "saved to your keychain" into an unencrypted file.
  I4  Every message leaving this module is redacted against the key first, whatever an SDK put in its exception.

`keyring` is an OPTIONAL dependency (extra: `keyvault`). With it absent — the CI case, and any headless box —
every function here still works; `can_persist` simply reports False and the UI says so in plain language.
"""

from __future__ import annotations

import os

ENV_VAR = "ANTHROPIC_API_KEY"
SERVICE = "cellarium"                  # keyring "service" namespace
ACCOUNT = "anthropic-api-key"          # the entry within that service
_MIN_LEN = 20                          # shorter than this is a truncated paste, not a key
_REDACTED = "[redacted]"

# How the value currently in os.environ got there. Set ONLY by this module, so "environment" (an explicit shell
# export or a .env the user wrote themselves) stays distinguishable from a key we injected — the UI must not
# offer to "remove" a key it does not actually control.
_SOURCE: str | None = None             # "keychain" | "session" | None

# Cached existence flag for the keychain entry. macOS prompts the user on a Keychain READ, so status() must not
# re-read on every poll; we remember what the last authoritative operation saw.
_IN_KEYCHAIN: bool | None = None


# ---------------------------------------------------------------- backend detection
def backend() -> dict:
    """The active keyring backend: {name, secure, reason}.

    `secure` False means we will NOT persist. keyring auto-selects a backend, and two of the possible answers are
    traps for a feature that promises "stored in your OS keychain": `keyrings.alt`'s PlaintextKeyring writes the
    secret to an UNENCRYPTED file, and `backends.fail` (the usual result on headless Linux or in a container)
    stores nothing at all while still accepting set_password. Persisting to either would make the UI lie, so both
    are detected and refused here rather than discovered later by a user reading a plaintext file.
    """
    try:
        import keyring
    except Exception:
        return {"name": None, "secure": False, "reason": "the optional `keyring` package is not installed"}
    try:
        kr = keyring.get_keyring()
    except Exception as exc:
        return {"name": None, "secure": False, "reason": f"no keyring backend is available ({type(exc).__name__})"}
    return _classify(kr)


def _classify(kr, _depth: int = 0) -> dict:
    """Verdict for one backend object. Recurses into a ChainerBackend, because that is where the trap hides: on
    Linux keyring commonly hands back a chainer, the chainer reports a healthy priority, and its FIRST child may
    still be a plaintext file backend. Judging only the wrapper would call that secure. We judge the leaf that
    would actually receive the write — the highest-priority child — and inherit its verdict."""
    mod, cls = (type(kr).__module__ or ""), type(kr).__name__
    name = f"{mod}.{cls}"
    kids = list(getattr(kr, "backends", None) or ())
    if kids and _depth < 4:
        best = max(kids, key=lambda k: float(getattr(k, "priority", 0) or 0), default=None)
        if best is None:
            return {"name": name, "secure": False, "reason": "no OS keychain is reachable on this machine"}
        inner = _classify(best, _depth + 1)
        return {"name": f"{name} -> {inner['name']}", "secure": inner["secure"], "reason": inner["reason"]}
    if mod.startswith("keyrings.alt") or "Plaintext" in cls:
        return {"name": name, "secure": False, "reason": "this backend stores secrets unencrypted on disk"}
    if mod.endswith("backends.fail") or mod.endswith(".fail"):
        return {"name": name, "secure": False, "reason": "no OS keychain is reachable on this machine"}
    try:                                   # backends.fail advertises priority 0; a live backend reports > 0
        if float(getattr(kr, "priority", 0) or 0) <= 0:
            return {"name": name, "secure": False, "reason": "no OS keychain is reachable on this machine"}
    except Exception:
        return {"name": name, "secure": False, "reason": "the keyring backend reported no usable priority"}
    return {"name": name, "secure": True, "reason": ""}


# ---------------------------------------------------------------- masking / redaction
def mask(key: str | None) -> str | None:
    """'sk-ant-…AB12' — the constant prefix plus the last four, the standard way to show WHICH key is set without
    showing the key. Anything too short to mask with margin reveals nothing at all."""
    k = (key or "").strip()
    if not k:
        return None
    if len(k) < 16:
        return "…"
    return f"{k[:7]}…{k[-4:]}"


def _redact(text: str, *keys: str | None) -> str:
    """I4. No string leaves this module carrying a key — not an SDK exception, not a traceback fragment, not a
    validation message. Redacts the candidate value AND whatever is currently in the environment."""
    out = str(text)
    for k in (*keys, os.environ.get(ENV_VAR)):
        k = (k or "").strip()
        if len(k) >= 8:
            out = out.replace(k, _REDACTED)
    return out


# ---------------------------------------------------------------- read / write
def _read_keychain() -> str | None:
    """The ONLY function that returns the raw secret. Its one legitimate caller is load_into_env()."""
    if not backend()["secure"]:
        return None
    try:
        import keyring
        return keyring.get_password(SERVICE, ACCOUNT) or None
    except Exception:
        return None                        # a locked or absent keychain is a miss, never a crash


def status() -> dict:
    """I2 — the masked-only credential state; the only shape that crosses the HTTP boundary. Never the key."""
    global _IN_KEYCHAIN
    env = os.environ.get(ENV_VAR) or ""
    b = backend()
    if _IN_KEYCHAIN is None:               # probe once per process, then trust the cache (macOS prompts on read)
        _IN_KEYCHAIN = bool(_read_keychain()) if b["secure"] else False
    return {
        "configured": bool(env),
        # keychain / session = we put it there and can remove it; environment = the user's own export or .env,
        # which this UI must report but must never claim to manage.
        "source": (_SOURCE or "environment") if env else None,
        "masked": mask(env),
        "managed_here": _SOURCE in ("keychain", "session") and bool(env),
        "in_keychain": bool(_IN_KEYCHAIN),
        "backend": b["name"],
        "backend_secure": b["secure"],
        "backend_reason": b["reason"],
        "can_persist": b["secure"],
    }


def load_into_env(*, override: bool = False) -> dict:
    """Boot hook: make the stored key visible to every `anthropic.Anthropic()` in this process.

    Precedence is deliberate — an explicit shell export or a .env value WINS over the keychain, because it is the
    more explicit, more local signal (and it is how CI, the eval runners and `docker run -e` all work). Only when
    the environment is empty do we reach for the keychain.
    """
    global _SOURCE, _IN_KEYCHAIN
    if os.environ.get(ENV_VAR) and not override:
        return status()
    val = _read_keychain()
    _IN_KEYCHAIN = bool(val)
    if val:
        os.environ[ENV_VAR] = val
        _SOURCE = "keychain"
    return status()


def set_key(key: str, *, persist: bool = True) -> dict:
    """Set the key for this process and, when a SECURE keychain exists and persist is asked for, store it there.

    Returns masked status only (I2). Raises ValueError with a plain-language message on an obviously malformed
    value — the three ways a pasted key actually goes wrong, caught before we bother the API with them.
    """
    global _SOURCE, _IN_KEYCHAIN
    k = (key or "").strip()
    if not k:
        raise ValueError("No key provided.")
    if any(c.isspace() for c in k):
        raise ValueError("That value contains a space or line break — an API key is one unbroken token.")
    if len(k) < _MIN_LEN:
        raise ValueError("That looks too short to be an API key — check for a truncated paste.")
    os.environ[ENV_VAR] = k
    _SOURCE = "session"                    # true unless the keychain write below succeeds
    if persist and backend()["secure"]:
        try:
            import keyring
            keyring.set_password(SERVICE, ACCOUNT, k)
            _SOURCE, _IN_KEYCHAIN = "keychain", True
        except Exception as exc:
            # The key still works for this session — say so, and be honest that it did not persist. I4 applies:
            # a keychain error can quote what it was handed.
            return dict(status(), persist_error=_redact(f"{type(exc).__name__}: {exc}", k))
    return status()


def clear() -> dict:
    """Remove the key from this process AND from the keychain. Idempotent; deleting a missing entry is a no-op."""
    global _SOURCE, _IN_KEYCHAIN
    os.environ.pop(ENV_VAR, None)
    _SOURCE = None
    if backend()["secure"]:
        try:
            import keyring
            keyring.delete_password(SERVICE, ACCOUNT)
        except Exception:
            pass
    _IN_KEYCHAIN = False
    return status()


def probe() -> dict:
    """Is the configured key live? Uses messages.count_tokens — it authenticates like any other call but is FREE,
    so 'Test key' costs the user nothing. Returns {ok, detail}; the detail is redacted (I4) and never echoes."""
    key = os.environ.get(ENV_VAR)
    if not key:
        return {"ok": False, "detail": "No key is configured."}
    try:
        import anthropic
    except Exception:
        return {"ok": False, "detail": "The `anthropic` package is not installed."}
    try:
        anthropic.Anthropic(max_retries=1).messages.count_tokens(
            model="claude-haiku-4-5-20251001", messages=[{"role": "user", "content": "ping"}])
        return {"ok": True, "detail": "Accepted by the Anthropic API."}
    except Exception as exc:
        name = type(exc).__name__
        if "Authentication" in name or "PermissionDenied" in name:
            return {"ok": False, "detail": "The Anthropic API rejected this key."}
        return {"ok": False, "detail": _redact(f"Could not reach the API ({name}).", key)}
