"""H-13 — a REAL end-to-end credential round-trip on the Linux Secret Service backend.

WHY THIS SCRIPT EXISTS. `tests/test_credentials.py::test_backend_verdict_per_platform` asserts how each
platform's backend CLASS is classified, by faking the class name. That is a useful unit test and it is not
evidence that the thing works: it never stores a secret, never restarts, never reads one back. Until now
only **Windows** had been round-tripped for real, so on Linux the promise "your key is stored in your OS
keychain" rested on an inference from the code rather than on an observation.

WHAT IT ACTUALLY EXERCISES. The genuine `keyring` -> `SecretStorage` -> D-Bus -> `gnome-keyring-daemon`
chain, with a real encrypted keyring, doing what a user does: store a key, read it back in a FRESH process
(the part a same-process assertion cannot test), then clear it and confirm it is gone.

HOW TO RUN IT (from the repo root; needs Docker, nothing else):

    docker run --rm -v "$PWD/src:/app/src:ro" -v "$PWD/scripts:/app/scripts:ro" -w /app python:3.12-slim \
      bash -c "apt-get -qq update && apt-get -qq install -y gnome-keyring dbus-x11 libsecret-1-0 >/dev/null \
               && pip -q install keyring secretstorage \
               && dbus-run-session -- python scripts/verify_credentials_linux.py"

HONEST LIMITS, stated so the result is not over-read:
  * This is `gnome-keyring-daemon` unlocked with a known password in a container, not a logged-in desktop
    session. The BACKEND and the round-trip are real; the session is not a user's.
  * KDE Wallet (`kwallet`) is a different backend and is NOT covered here.
  * macOS Keychain cannot be tested from Linux or Windows at all — it needs a Mac. That platform stays
    unverified until someone runs the equivalent there.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

PROVIDER = "anthropic"
# Obviously fake, and shaped like the real thing so any prefix validation is exercised too.
FAKE_KEY = "sk-ant-api03-" + ("VERIFY" * 6) + "-LINUXROUNDTRIP"

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def unlock_keyring() -> None:
    """Start gnome-keyring-daemon inside this D-Bus session and unlock it, as a login would."""
    p = subprocess.run(["gnome-keyring-daemon", "--unlock", "--components=secrets"],
                       input="verify\n", capture_output=True, text=True)
    for line in (p.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ[k] = v
    print(f"gnome-keyring-daemon started (rc={p.returncode}); "
          f"CONTROL={os.environ.get('GNOME_KEYRING_CONTROL', '(unset)')}\n", flush=True)


def main() -> int:
    unlock_keyring()
    from cellarium import credentials as C

    b = C.backend()
    print(f"backend: {b}\n", flush=True)
    check("a backend is detected", bool(b.get("name")), str(b.get("name")))
    check("it is classified SECURE (not plaintext, not fail)", bool(b.get("secure")), b.get("reason") or "")
    if not b.get("secure"):
        print("\nAborting: an insecure backend must not be written to, which is the correct behaviour — "
              "but it also means this run proves nothing about the Secret Service path.")
        return 2

    check("can_persist reports True", bool(C.overview().get("can_persist")))

    # STORE ---------------------------------------------------------------------------------------
    res = C.set_key(FAKE_KEY, provider=PROVIDER)
    check("set_key stores without error", not res.get("error"), str(res)[:120])

    # `_read_keychain` is the keychain read itself. `resolve()` returns a PROVIDER NAME, not a key --
    # exactly the near-miss that would have made this script report a confident false result.
    # READ BACK IN A FRESH PROCESS -- the half a same-process assertion cannot reach -----------------
    reader = (
        "import sys; sys.path.insert(0, '/app/src')\n"
        "from cellarium import credentials as C\n"
        f"v = C._read_keychain({PROVIDER!r})\n"
        "print('READBACK:' + (v or ''))\n"
    )
    p = subprocess.run([sys.executable, "-c", reader], capture_output=True, text=True, env=os.environ.copy())
    got = ""
    for line in (p.stdout or "").splitlines():
        if line.startswith("READBACK:"):
            got = line[len("READBACK:"):]
    check("a FRESH process reads the same key back", got == FAKE_KEY,
          f"got {len(got)} chars" + ("" if got else f"; stderr={(p.stderr or '')[-160:]}"))

    # The value must never appear in the clear anywhere the user could stumble on it.
    ov = C.overview()
    masked = ((ov.get("providers") or {}).get(PROVIDER) or {}).get("masked") or ""
    check("overview() masks the key rather than echoing it", FAKE_KEY not in str(ov), f"masked={masked!r}")

    # CLEAR ---------------------------------------------------------------------------------------
    C.clear(provider=PROVIDER)
    p2 = subprocess.run([sys.executable, "-c", reader], capture_output=True, text=True, env=os.environ.copy())
    after = ""
    for line in (p2.stdout or "").splitlines():
        if line.startswith("READBACK:"):
            after = line[len("READBACK:"):]
    check("clear() really removes it (fresh process sees nothing)", not after, f"got {len(after)} chars")

    print("\n" + "=" * 72)
    passed = sum(1 for _, ok, _ in _results if ok)
    print(f"LINUX SECRET SERVICE ROUND-TRIP: {passed}/{len(_results)} checks passed")
    for n, ok, d in _results:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
