"""The local credential vault — the ONE place Cellarium reads or writes the Anthropic API key.

Why this exists. Every entry point (apps/server.py, the CLI, the eval runners) constructs `llm.client()`
with no explicit api_key, so the SDK reads ANTHROPIC_API_KEY out of the process environment. Historically the only
way to set it was an exported shell variable or a repo-root .env — correct, but a CLI-shaped wall in front of an
app whose whole point is that you can clone it and click through the glass box. This module adds an in-app path
that is *at least as safe as* the .env it replaces: the key goes to the OS keychain (Windows Credential Manager /
macOS Keychain / Linux Secret Service) via `keyring`, and is injected into os.environ once at boot so every
`llm.client()` call site keeps working untouched.

LLM-7a note: clients are now constructed through the `llm` seam, but the KEY this module stores is still the
Anthropic one, under a single fixed service/account and the ANTHROPIC_API_KEY environment variable. Making the
vault provider-aware -- one stored secret per configured provider -- is part of LLM-7b, not of the seam.

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

`keyring` is a CORE dependency (promoted from the `keyvault` extra on 2026-08-11; the extra is kept as a no-op
alias). What is still optional is a working OS keychain BACKEND — absent on CI and on headless boxes — and with
no backend every function here still works; `can_persist` simply reports False and the UI says so in plain
language.
"""

from __future__ import annotations

import os

# LLM-7e — ONE ENTRY PER PROVIDER, in one service namespace.
#
# The vault was single-provider: one env var, one keychain account, one set of globals. Once `llm` could talk
# to an OpenAI-compatible endpoint that became a real gap rather than a cosmetic one — the Settings panel had
# nowhere to put a second key, so it would save it and the adapter would never read it. Keying by provider
# fixes that without changing the storage model: the same `SERVICE`, a different ACCOUNT per provider.
#
# The anthropic account name is UNCHANGED, so a key stored by any earlier version is found exactly where it
# was left. That is the whole of the migration.
PROVIDERS: dict[str, dict] = {
    "anthropic": {"env": "ANTHROPIC_API_KEY", "account": "anthropic-api-key", "label": "Anthropic",
                  "console": "https://console.anthropic.com/settings/keys", "prefix": "sk-ant-"},
    "openai": {"env": "OPENAI_API_KEY", "account": "openai-api-key", "label": "OpenAI-compatible",
               "console": "https://platform.openai.com/api-keys", "prefix": "sk-"},
}

# The aliases `llm.client` accepts, mapped onto the credential bucket they share. A local vLLM/Ollama server
# uses the OpenAI shape and usually ignores the key entirely, but it still reads OPENAI_API_KEY, so it belongs
# in the same bucket rather than in one of its own.
_ALIASES = {"openai_compatible": "openai", "vllm": "openai", "ollama": "openai", "local": "openai"}

SERVICE = "cellarium"                  # keyring "service" namespace, shared by every provider
ENV_VAR = PROVIDERS["anthropic"]["env"]        # back-compat: the DEFAULT provider's names, unchanged
ACCOUNT = PROVIDERS["anthropic"]["account"]    # ditto — existing callers and tests keep working
_MIN_LEN = 20                          # shorter than this is a truncated paste, not a key
_REDACTED = "[redacted]"


def resolve(provider: str | None = None) -> str:
    """Which provider's credential are we talking about? Defaults to the one `llm` is configured to use.

    An unknown name falls back to anthropic rather than raising: this module is on the boot path, and a
    typo in CELLARIUM_LLM_PROVIDER should surface as `llm.client()` refusing by name — which it does, and
    which says what IS supported — not as the credential layer exploding first with a worse message.
    """
    if provider:
        p = provider.strip().lower()
    else:
        try:
            from . import llm
            p = llm.PROVIDER
        except Exception:
            p = "anthropic"
    p = _ALIASES.get(p, p)
    return p if p in PROVIDERS else "anthropic"


def env_var(provider: str | None = None) -> str:
    """The environment variable this provider's SDK reads."""
    return PROVIDERS[resolve(provider)]["env"]


def account(provider: str | None = None) -> str:
    """The keychain account name holding this provider's key."""
    return PROVIDERS[resolve(provider)]["account"]


# How the value currently in os.environ got there, PER PROVIDER. Set ONLY by this module, so "environment"
# (an explicit shell export or a .env the user wrote themselves) stays distinguishable from a key we
# injected — the UI must not offer to "remove" a key it does not actually control.
_SOURCE: dict[str, str | None] = {}    # provider -> "keychain" | "session" | None

# Cached existence flag for the keychain entry, per provider. macOS prompts the user on a Keychain READ, so
# status() must not re-read on every poll; we remember what the last authoritative operation saw.
_IN_KEYCHAIN: dict[str, bool | None] = {}


def _reset_state() -> None:
    """Forget what this process learned about every provider's credential. TEST + boot hook.

    Exists so a caller resets through one supported call instead of assigning to `_SOURCE` and
    `_IN_KEYCHAIN` directly — the shape of those changed when the vault became provider-aware (LLM-7e),
    and every test that had reached into them broke. A named seam keeps the next such change internal.
    """
    _SOURCE.clear()
    _IN_KEYCHAIN.clear()


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
        return {"name": None, "secure": False, "reason": "the `keyring` package is not installed (it is a core dependency; reinstall with `pip install -e .`)"}
    try:
        kr = keyring.get_keyring()
    except Exception as exc:
        return {"name": None, "secure": False, "reason": f"no keyring backend is available ({type(exc).__name__})"}
    return _classify(kr)


def _classify(kr, _depth: int = 0) -> dict:
    """Verdict for one backend object. Recurses into a ChainerBackend, because that is where the trap hides: on
    Linux keyring commonly hands back a chainer, the chainer reports a healthy priority, and a plaintext file
    backend sits inside it. Judging only the wrapper would call that secure."""
    mod, cls = (type(kr).__module__ or ""), type(kr).__name__
    name = f"{mod}.{cls}"
    kids = list(getattr(kr, "backends", None) or ())
    if kids and _depth < 4:
        if not kids:
            return {"name": name, "secure": False, "reason": "no OS keychain is reachable on this machine"}
        # EVERY child must be secure, not just the highest-priority one. A chainer tries its backends in order and
        # falls through when one declines the write, so a read-only plugin at priority 9 followed by a plaintext
        # backend at 0.5 means the plaintext one silently receives the key. We cannot know which will accept, so
        # any insecure child condemns the chain — degrading to session-only is the safe failure, writing plaintext
        # is not. (Cost: a box with both a real keychain AND keyrings.alt installed loses persistence, and is told
        # exactly why.)
        inner = [_classify(k, _depth + 1) for k in kids]
        weak = next((i for i in inner if not i["secure"]), None)
        if weak is not None:
            return {"name": f"{name} -> {weak['name']}", "secure": False,
                    "reason": f"{weak['reason']} (reachable in the keyring chain)"}
        return {"name": f"{name} -> {inner[0]['name']}", "secure": True, "reason": ""}
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
def _read_keychain(provider: str | None = None) -> str | None:
    """The ONLY function that returns the raw secret. Its one legitimate caller is load_into_env()."""
    if not backend()["secure"]:
        return None
    try:
        import keyring
        return keyring.get_password(SERVICE, account(provider)) or None
    except Exception:
        return None                        # a locked or absent keychain is a miss, never a crash


def status(provider: str | None = None) -> dict:
    """I2 — the masked-only credential state; the only shape that crosses the HTTP boundary. Never the key."""
    prov = resolve(provider)
    env = os.environ.get(env_var(prov)) or ""
    b = backend()
    if _IN_KEYCHAIN.get(prov) is None:     # probe once per provider, then trust it (macOS prompts on read)
        _IN_KEYCHAIN[prov] = bool(_read_keychain(prov)) if b["secure"] else False
    return {
        # Which credential this describes, and what else could be configured. The UI needs both to label the
        # field and to offer the other providers without hard-coding a list that would drift from PROVIDERS.
        "provider": prov,
        "provider_label": PROVIDERS[prov]["label"],
        "env_var": env_var(prov),
        "console_url": PROVIDERS[prov]["console"],
        "providers": {k: {"label": v["label"], "env": v["env"]} for k, v in PROVIDERS.items()},
        "configured": bool(env),
        # keychain / session = we put it there and can remove it; environment = the user's own export or .env,
        # which this UI must report but must never claim to manage.
        "source": (_SOURCE.get(prov) or "environment") if env else None,
        "masked": mask(env),
        "managed_here": _SOURCE.get(prov) in ("keychain", "session") and bool(env),
        "in_keychain": bool(_IN_KEYCHAIN.get(prov)),
        "backend": b["name"],
        "backend_secure": b["secure"],
        "backend_reason": b["reason"],
        "can_persist": b["secure"],
    }


def load_into_env(*, override: bool = False, provider: str | None = None) -> dict:
    """Boot hook: make the stored key visible to every `llm.client()` in this process.

    Precedence is deliberate — an explicit shell export or a .env value WINS over the keychain, because it is the
    more explicit, more local signal (and it is how CI, the eval runners and `docker run -e` all work). Only when
    the environment is empty do we reach for the keychain.
    """
    prov = resolve(provider)
    var = env_var(prov)
    if os.environ.get(var) and not override:
        return status(prov)
    val = _read_keychain(prov)
    _IN_KEYCHAIN[prov] = bool(val)
    if val:
        os.environ[var] = val
        _SOURCE[prov] = "keychain"
    from . import redact
    redact.register_secret(os.environ.get(var))       # covers the .env / exported-variable case too
    return status(prov)


def set_key(key: str, *, persist: bool = True, provider: str | None = None) -> dict:
    """Set the key for this process and, when a SECURE keychain exists and persist is asked for, store it there.

    Returns masked status only (I2). Raises ValueError with a plain-language message on an obviously malformed
    value — the three ways a pasted key actually goes wrong, caught before we bother the API with them.
    """
    prov = resolve(provider)
    var = env_var(prov)
    k = (key or "").strip()
    if not k:
        raise ValueError("No key provided.")
    if any(c.isspace() for c in k):
        raise ValueError("That value contains a space or line break — an API key is one unbroken token.")
    if len(k) < _MIN_LEN:
        raise ValueError("That looks too short to be an API key — check for a truncated paste.")
    # A hazard the multi-provider vault CREATES: with two fields there is now a wrong one to paste into,
    # and an Anthropic key in the OpenAI slot fails later as an opaque 401 from a different vendor. WARN,
    # never reject — key formats change, and a vault that refuses a valid new-format key is worse than one
    # that lets a mistake through with a note. anthropic's sk-ant- is the discriminating prefix; OpenAI's
    # bare sk- is a prefix OF it, so only the specific direction is checkable.
    wrong = None
    if prov == "openai" and k.startswith("sk-ant-"):
        wrong = "This looks like an Anthropic key (sk-ant-…), but Cellarium is configured for OpenAI."
    elif prov == "anthropic" and k.startswith("sk-") and not k.startswith("sk-ant-"):
        wrong = "This does not look like an Anthropic key (they start sk-ant-…)."
    os.environ[var] = k
    from . import redact
    redact.forget_secret()                 # a replaced key stops being a literal we scrub for
    redact.register_secret(k)              # ...and the new one starts, so a SHAPE-LESS key is caught too
    _SOURCE[prov] = "session"              # true unless the keychain write below succeeds
    if persist and backend()["secure"]:
        try:
            import keyring
            keyring.set_password(SERVICE, account(prov), k)
            _SOURCE[prov], _IN_KEYCHAIN[prov] = "keychain", True
        except Exception as exc:
            # The key still works for this session — say so, and be honest that it did not persist. I4 applies:
            # a keychain error can quote what it was handed.
            return dict(status(prov), persist_error=_redact(f"{type(exc).__name__}: {exc}", k))
    st = status(prov)
    return dict(st, prefix_warning=wrong) if wrong else st


def clear(provider: str | None = None) -> dict:
    """Remove the key from this process AND from the keychain. Idempotent; deleting a missing entry is a no-op."""
    prov = resolve(provider)
    os.environ.pop(env_var(prov), None)
    from . import redact
    redact.forget_secret()
    _SOURCE[prov] = None
    # ALWAYS attempt the delete — never gate it on the current secure verdict. A key stored while a keychain was
    # available must still be removable from a later run where it is not (a different venv without the extra, a
    # Secret Service daemon that isn't up, a container). Gating meant "Remove" could report success while the
    # credential quietly survived in the keychain — the worst kind of security-UI lie.
    try:
        import keyring
        keyring.delete_password(SERVICE, account(prov))
    except Exception:
        pass                                   # already absent, or no backend at all — both are "nothing to do"
    _IN_KEYCHAIN[prov] = False
    return status(prov)


def probe(provider: str | None = None) -> dict:
    """Is the configured key live? Returns {ok, detail}; the detail is redacted (I4) and never echoes.

    THE PROBE MUST ACTUALLY REACH THE NETWORK, and that is why this is not one call for both providers.
    Anthropic's `messages.count_tokens` authenticates like any other request but is FREE, so "Test key"
    costs nothing. The OpenAI-compatible adapter implements `count_tokens` LOCALLY (tiktoken or chars//4,
    because Chat Completions has no such endpoint), so calling it there would return a number without ever
    contacting the server and this would report a wrong, missing or revoked key as live. For that provider
    the probe is a real 1-token completion instead — a few cents per year, and it answers the question
    actually being asked.
    """
    prov = resolve(provider)
    key = os.environ.get(env_var(prov))
    label = PROVIDERS[prov]["label"]
    if not key:
        return {"ok": False, "detail": "No key is configured.", "provider": prov}
    try:
        from . import llm
    except Exception:
        return {"ok": False, "detail": "The provider package is not installed.", "provider": prov}
    try:
        client = llm.client(max_retries=1)
        if prov == "anthropic":
            client.messages.count_tokens(model="claude-haiku-4-5-20251001",
                                         messages=[{"role": "user", "content": "ping"}])
        else:
            model = os.environ.get("CELLARIUM_MODEL") or "gpt-4o-mini"
            client.messages.create(model=model, max_tokens=1,
                                   messages=[{"role": "user", "content": "ping"}])
        return {"ok": True, "detail": f"Accepted by {label}.", "provider": prov}
    except Exception as exc:
        name = type(exc).__name__
        if "Authentication" in name or "PermissionDenied" in name:
            return {"ok": False, "detail": f"{label} rejected this key.", "provider": prov}
        # A wrong MODEL name is the other common answer here, and it is not a credential problem -- saying
        # "could not reach" for it would send the user to debug their key instead of their model id.
        msg = str(exc).lower()
        if "model" in msg and ("not found" in msg or "does not exist" in msg or "unknown" in msg):
            return {"ok": False, "provider": prov,
                    "detail": _redact(f"The key was accepted but the model was not recognised ({name}). "
                                      "Check CELLARIUM_MODEL.", key)}
        return {"ok": False, "provider": prov,
                "detail": _redact(f"Could not reach {label} ({name}).", key)}
