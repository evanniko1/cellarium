"""The keys a paid eval run needs, found where the app keeps them, or the run stops before it spends anything.

The app's Settings tab stores the API keys in the OS keychain (docs/CREDENTIALS.md). A runner that reads only
`.env` and the environment cannot see them, which is how the commands prepared for the first paid runs of the
validation layer would have failed on the machine they were prepared on (2026-11-24). run_ab.py has its own
`_resolve_api_key` for the same reason; this is the shared form, for the runners that grade with two families.

`require` looks in `.env`, then the environment, then the keychain (the order `credentials.load_into_env` keeps:
the more local, more explicit source wins), and exits 2 naming every key still missing. It never degrades: a run
that asked for a GPT grader and has no OpenAI key does not become a Claude-only run. That was the old behaviour of
the audit, the ablation and the trivial baselines, and a grader dropped without a word is the silent-absence
defect this project keeps finding (tests/test_paid_runs_find_their_keys.py).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
ANTHROPIC, OPENAI = "anthropic", "openai"


def require(*providers: str, hint: str = "", log=print) -> None:
    """Make each provider's key visible to this process, or exit 2 before any client exists."""
    load_dotenv(str(REPO / ".env"))
    from cellarium import credentials
    missing = []
    for prov in providers:
        var = credentials.env_var(prov)
        if not os.environ.get(var):
            try:
                credentials.load_into_env(provider=prov)
            except Exception:
                pass                    # no keyring extra or no backend: fall through to the message
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        log(f"ERROR: {' and '.join(missing)} not found. Provide each in any of these ways:\n"
            "    1. the app's Settings tab (stored in your OS keychain)\n"
            f"    2. a .env at the repo root: {REPO / '.env'}\n"
            "    3. an exported shell variable\n"
            + (f"{hint}\n" if hint else "")
            + "Stopped before any model call; nothing was spent.")
        raise SystemExit(2)
