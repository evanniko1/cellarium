# Credentials — where the API key lives, and what happens on your OS

Cellarium needs an Anthropic API key for live reasoning (the read-only tier — corpus browser, recorded
investigations, recorded Council runs — needs none). This document is the specification for how that key is
stored, what guarantees hold, and exactly how the behaviour differs per operating system.

Implementation: [`src/cellarium/credentials.py`](../src/cellarium/credentials.py) (the vault),
[`src/cellarium/redact.py`](../src/cellarium/redact.py) (the outbound scrub). Invariants are pinned by
[`tests/test_credentials.py`](../tests/test_credentials.py) and [`tests/test_redact.py`](../tests/test_redact.py).

## Three ways to supply a key, in precedence order

Resolved **once at server boot**, then injected into `os.environ` so every `anthropic.Anthropic()` call site in
the codebase picks it up unchanged:

1. **An exported shell variable** — `ANTHROPIC_API_KEY=…`. Wins over everything; this is how CI, the eval
   runners, and `docker run -e` work.
2. **A repo-root `.env`** — `cp .env.example .env`. (Until the vault landed, `apps/server.py` never called
   `load_dotenv`, so this documented path only ever worked for the CLI. It works for the web app now.)
3. **The OS keychain** — the in-app **Settings** panel (gear icon, top bar).

The precedence is deliberate: the environment is the more explicit, more local signal, so the vault never
clobbers it. When a key comes from the environment the UI says so and **does not offer to remove it** — Cellarium
did not put it there, so it will not claim to manage it.

## The four invariants

Each is stated so a test can assert it, and each has one.

| | Invariant | How it is enforced |
|---|---|---|
| **I1** | The key never enters the LLM context | There is deliberately **no agent tool** for the vault. Cellwright cannot read or set the key — the capability is absent from the dispatch table, so no prompt can talk it into using one. Same containment that keeps the agent off `/api/approve`. `agent.py` does not import `credentials`; a test asserts the module boundary. |
| **I2** | The key never crosses the HTTP boundary | `status()` is masked-only (`sk-ant-…AB12`). Asserted end-to-end: POST a key, then check the literal appears in **no** response body. |
| **I3** | The key is never written to disk in plaintext | If no *secure* keychain backend exists we refuse to persist **at all** (session-only) rather than silently downgrade. See the matrix below. |
| **I4** | Every message leaving the vault is redacted | Belt-and-braces against a library that echoes a malformed key — which [really happens](#why-the-scrubbing-exists). |

## Per-OS behaviour

`keyring` auto-selects a backend. We treat one as usable only if it is *secure*; otherwise we keep the key in
memory for the server session and say so in plain language. **This is a degrade, not a break** — the key still
works for the whole session, and `.env` remains available everywhere.

| Platform | Backend selected | Persist? | What you see |
|---|---|---|---|
| **Windows 10/11** | `keyring.backends.Windows.WinVaultKeyring` | ✅ Credential Manager | "Save to keychain". *Verified end-to-end on Windows 11 + keyring 25.7.0.* |
| **macOS** (GUI login) | `keyring.backends.macOS.Keyring` | ✅ Keychain | "Save to keychain"; appears in Keychain Access as a generic password named `cellarium`. |
| **Linux — GNOME** | `keyring.backends.SecretService.Keyring` | ✅ Secret Service | "Save to keychain"; lands in the login keyring. Needs the keyring **unlocked**. |
| **Linux — KDE** | `keyring.backends.kwallet.DBusKeyring` | ✅ KWallet | Needs the distro `dbus-python` package (`python3-dbus`) — it is not a `keyring` dependency. |
| **Headless Linux / SSH / systemd** | `keyring.backends.fail.Keyring` | ❌ session-only | "Use for this session" + *"no OS keychain is reachable on this machine"*. Use `.env`. |
| **Docker container** | `keyring.backends.fail.Keyring` | ❌ session-only | Intended path is `docker run -e ANTHROPIC_API_KEY=…`, which takes precedence anyway. |
| **WSL2** | `keyring.backends.fail.Keyring` | ❌ session-only | WSL2 does not see the Windows side's Credential Manager. Use `.env` or `export`. |
| **BSD** | `keyring.backends.fail.Keyring` | ❌ session-only | Use `.env`. |
| **any, with `keyrings.alt` installed** | `PlaintextKeyring` | ❌ **refused** | *"this backend stores secrets unencrypted on disk"*. We will not write a key there. |
| **CI** | `keyring` absent entirely | ❌ session-only | *"the `keyring` package is not installed (it is a core dependency; reinstall with `pip install -e .`)"*. |

`tests/test_credentials.py::test_backend_verdict_per_platform` pins the verdict for each of these backend
classes, so the table is CI-enforced rather than prose.

**Chained backends.** On Linux `keyring` often returns a `ChainerBackend`. A chain is judged by **every** child,
not the highest-priority one: a chainer falls through to the next backend when one declines a write, so a
read-only plugin at priority 9 in front of a plaintext backend at 0.5 means *plaintext* receives the key.
Any insecure child condemns the chain — you lose persistence and are told exactly why.

### Install

```bash
pip install -e .                  # `keyring` is a core dependency; nothing extra to add
```

(`pip install -e ".[keyvault]"` still works: the extra was kept as a no-op alias when `keyring` was promoted
to a core dependency on 2026-08-11.)

Windows and macOS need nothing further. Linux/GNOME is covered by the extra (`SecretStorage` + `jeepney` install
under a `sys_platform == "linux"` marker); KDE additionally needs `python3-dbus`.

### Known, documented behaviours — not bugs

- **macOS re-prompts when the Python executable changes.** The keychain item's ACL binds to the executable that
  created it, so a new venv or an upgraded interpreter triggers a fresh "allow?" dialog. Keychain reads run in a
  threadpool and the existence flag is cached, so a prompt never stalls the server or repeats on every poll.
- **macOS over SSH with a locked keychain** reads as "No key set" even though the item exists. Run
  `security unlock-keychain` first, or just use `.env` (which takes precedence anyway).
- **Windows Credential Manager is readable by any process running as the same user.** This is weaker than macOS's
  per-executable ACL, and is exactly what the UI claims: *"readable only by your user account."*
- **Non-loopback deployments 403 the credential endpoints** — a container reached by bridge IP, or a server
  started with `--host 0.0.0.0` and reached over the LAN. This is intentional (see below); use `.env` there.
- **WSL2 boot hang, guarded.** `import keyring` can hang when `DISPLAY` is set with no X server (D-Bus autolaunch
  waits out its timeout — jaraco/keyring#531). A hang is not an exception, so the boot probe runs in a thread with
  an 8-second join; the worst case is "not configured", which the UI already handles.

## The HTTP surface

Four endpoints, all **loopback-only**: `GET /api/settings`, `POST /api/settings_key`,
`POST /api/settings_key_delete`, `POST /api/settings_key_test`. None can return the key.

Three layers guard them, because a locally-bound server is not automatically safe:

1. **Host must be loopback.** DNS rebinding necessarily arrives carrying the attacker's registrable name in
   `Host`, so this defeats it.
2. **Origin is parsed, not prefix-matched.** An adversarial review proved the original prefix check wrong:
   `"http://localhost.evil.example".startswith("http://localhost")` is `True`, so an attacker only had to
   register a name *beginning* with a loopback literal — and a reviewer used it to write a key into a real
   Windows Credential Manager. The hostname is now parsed and compared exactly.
3. **A per-page token on every mutating call.** `Sec-Fetch-Site` fails open when absent (Safari < 16.4, embedded
   WebViews) and a legacy cross-site form POST can omit `Origin` too — so browser vintage was load-bearing.
   `index.html` carries a per-process token that the write endpoints require in `X-Cellarium-CSRF`. A
   cross-origin page cannot read our document, so it cannot forge one. Reads stay open.

The token is not a secret from the *local* user — anyone who can `curl 127.0.0.1` can read it out of `/`, and
they already have your `.env`. It exists to stop a *remote page* driving your local server.

## Why the scrubbing exists

A leak-surface audit reproduced this against this repo's own venv: a key pasted with a **trailing newline** — the
single most likely artifact of a paste-into-a-text-field UI, which the Settings panel now is — makes httpx raise
`LocalProtocolError: Illegal header value b'sk-ant-…\n'`. The outermost SDK exception is clean, but
`traceback.format_exc()` is not, and that is exactly what `exc_info=True` logging emits.

So `redact.scrub` sits on the funnels everything drains through:

| Funnel | Why it is the right place |
|---|---|
| `server._jsonsafe` | everything streamed to the browser, and thence to `localStorage` |
| `agent._truncate_tool_result` | everything a tool puts into the model's context — re-sent every turn, persisted, and carried past compaction |
| `redact.install_log_filter()` | the only hook that reaches rendered `exc_info` traceback text |
| `SessionStore.put` / `HypothesisStore._write` | the durable SQLite sinks, which are also served back over HTTP |
| `redact.child_env()` | strips credentials from every `subprocess.run` environment |

Two design notes. **Patterns are prefix-anchored and conservative** — a false positive silently corrupts
scientific output, so the `bearer` rule requires 20+ characters *and* a digit (otherwise "bearer
responsibilities" gets redacted). And because a **shape-less** key (an LLM-gateway, LiteLLM, or Bedrock-proxy
token) matches no known prefix, the vault *pushes* the literal value to `redact.register_secret()`. `redact`
still reads no environment and no keychain, so I1's module boundary is unchanged.

`child_env()` **copies and removes** rather than building a minimal environment: a minimal env breaks child
processes on Windows (no `SYSTEMROOT`) and loses the `PATH` that finds `docker` and `git` everywhere else.

## What is deliberately *not* protected

- **The local user.** Anyone with your OS account can read your `.env`, your keychain, and the CSRF token. This
  is a single-user, clone-and-run-local research tool; the threat model is a *remote page* or a *leaked
  artifact*, not a local adversary.
- **Rows written before the scrub landed.** Scrubbing happens at write time. The committed
  `data/sessions.seed.db` is a frozen pre-scrub snapshot (byte-scanned in CI), and SQLite does not zero freed
  pages, so a superseded value could survive in a pre-existing DB. If you ever suspect a key reached a
  transcript, rotate it — do not rely on the scrub retroactively.
