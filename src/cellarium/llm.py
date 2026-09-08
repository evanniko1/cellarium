"""LLM-7a — the provider seam: the ONE place a model client is constructed and provider policy is decided.

WHY THIS EXISTS. Nothing in Cellarium's science is vendor-specific. The Council/Cellwright split, the
capability registry, the import-level blindness quarantine and the selective-answering claim are all
statements about *agents*. The code did not match: `anthropic.Anthropic()` was constructed at eight sites
under `src/`, once in `apps/server.py` and eight more under `evals/`, and the sampling policy keyed on
Claude family names inside `agent.py`. The practical cost is that **a user without a Claude key cannot run
the agent at all**, and the publication cost is that a paper about capability-gated routing which only runs
on one vendor invites the reading that the gating is a property of that vendor rather than of the design.

WHAT THIS MODULE OWNS, AND WHAT IT DELIBERATELY DOES NOT. It owns *client construction* and *sampling
policy* — the two things that are purely about the provider. It does NOT own the message shape: callers
still build `messages.create(...)` themselves. That is LLM-7b's job, and separating the two keeps this
change mechanical and reviewable. `council._emit` is the single forced-tool call site, so the adapter that
follows has a small blast radius.

THE INVARIANT THIS BUYS, and it is checkable rather than aspirational: **no module outside this one imports
`anthropic`**. `tests/test_llm_seam.py` asserts it over the tree, so the next call site cannot quietly
reintroduce the coupling.

`max_retries` is threaded rather than fixed because the existing values are deliberate (LLM-5): 4 in the
runtime, 6 in the eval sweeps where concurrency provokes 429s, 1 on the fast keyword-fallback router and
the credential probe, where a slow retry storm would be worse than a clean failure.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROVIDER = "anthropic"

# Where the UI's provider choice persists. Same idiom as launch.QUEUE: an env override, else a file under
# data/. Gitignored -- it is per-install state, not part of the artifact.
PROVIDER_FILE = Path(os.environ.get("CELLARIUM_PROVIDER_FILE") or (_ROOT / "data" / "provider.json"))


def _persisted_provider() -> str | None:
    try:
        return (json.loads(PROVIDER_FILE.read_text(encoding="utf-8")) or {}).get("provider") or None
    except Exception:
        return None          # absent or unreadable is "no choice recorded", never a crash on the boot path


def set_active_provider(provider: str) -> str:
    """Record the UI's choice and apply it to THIS process. Returns the normalised value.

    Updates the module global as well as the file, because `client()` reads `PROVIDER` -- a switch that
    only wrote the file would take effect on the next boot and silently keep using the old provider until
    then, which is exactly the class of confusion this whole thread exists to remove.
    """
    global PROVIDER
    p = (provider or "").strip().lower()
    if p not in SUPPORTED and p not in _PROVIDER_ALIASES:
        raise ValueError(f"unknown provider {provider!r}; supported: {', '.join(SUPPORTED)}")
    PROVIDER = _PROVIDER_ALIASES.get(p, p)
    try:
        PROVIDER_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROVIDER_FILE.write_text(json.dumps({"provider": PROVIDER}, indent=1), encoding="utf-8")
    except Exception:
        pass                 # the switch still holds for this process; persistence is best-effort
    return PROVIDER


_PROVIDER_ALIASES = {"openai_compatible": "openai", "vllm": "openai", "ollama": "openai", "local": "openai"}

# PRECEDENCE: an explicit CELLARIUM_LLM_PROVIDER wins, because an operator export is the more explicit,
# more local signal -- the same rule credentials.load_into_env uses for the key itself. Otherwise the UI's
# remembered choice, otherwise the default.
_ENV_PROVIDER = (os.environ.get("CELLARIUM_LLM_PROVIDER") or "").strip().lower()
PROVIDER = _PROVIDER_ALIASES.get(_ENV_PROVIDER, _ENV_PROVIDER) or _persisted_provider() or DEFAULT_PROVIDER

# "openai" is the OpenAI-compatible shape: OpenAI itself, most hosted endpoints, and local vLLM /
# Ollama / LM Studio, which all serve /v1/chat/completions. OPENAI_BASE_URL points it at a local one.
SUPPORTED = ("anthropic", "openai")


def client(max_retries: int = 4, **kwargs):
    """Construct the configured provider's client. The only place in the tree that may do so.

    Raises a NAMED error for an unimplemented provider rather than falling back to Anthropic: a silent
    fallback would run the whole eval on a different model than the operator asked for and report it under
    the requested name, which is the one failure this seam exists to make impossible.
    """
    if PROVIDER == "anthropic":
        import anthropic
        return anthropic.Anthropic(max_retries=max_retries, **kwargs)
    if PROVIDER in ("openai", "openai_compatible", "vllm", "ollama", "local"):
        from ._openai_compat import OpenAICompatClient
        return OpenAICompatClient(max_retries=max_retries, **kwargs)
    raise NotImplementedError(
        f"CELLARIUM_LLM_PROVIDER={PROVIDER!r} is not implemented; supported: {', '.join(SUPPORTED)} "
        "(and the openai-compatible aliases openai_compatible / vllm / ollama / local).")


# ------------------------------------------------------------------------------------------------------
# Sampling policy. Moved here from agent.py unchanged; agent re-exports it, so every existing caller and
# test keeps working and the behaviour is identical.
# ------------------------------------------------------------------------------------------------------
# Reproducibility (M-2/LLM-3): pin sampling temperature instead of the API default. Anthropic exposes no
# seed, so temperature is the only reproducibility lever — and it's recorded per run so the sampling
# variance is named.
TEMPERATURE = float(os.environ.get("CELLARIUM_TEMPERATURE", "0.0"))

# Model families that REJECT an explicit `temperature` outright (HTTP 400, "`temperature` is deprecated for
# this model"). Kept as a family list rather than exact ids because ids carry dated suffixes.
#
# MEASURED 2026-08-05: the default model (claude-sonnet-5) began rejecting `temperature`, and because the
# old rule omitted it only for names containing "opus", EVERY Cellwright call failed with a 400 before
# reaching a single tool. Nine of nine protocol questions returned the same 210-character error in under a
# second. A name-based allow/deny list drifts the moment a family is added, so the caller ALSO treats the
# 400 as authoritative and retries without it — the list is the fast path, the retry is the guarantee.
#
# This list is Claude-specific by nature. Under another provider it simply does not match, which is the
# right default: an unknown model gets the pinned temperature and, if the endpoint refuses it, the same
# retry-without-it path applies.
_NO_EXPLICIT_TEMPERATURE = ("opus", "sonnet-5", "fable", "mythos")


def temperature_for(model: str | None, *, thinking: bool = False) -> float | None:
    """The temperature to SEND to the API (None => omit). Pinned to CELLARIUM_TEMPERATURE only for models
    that accept an explicit temperature with thinking OFF. None for reasoning models, and whenever extended
    thinking is on (the API forces temperature=1 there, so pinning would error).

    Reproducibility note: for a model that refuses an explicit temperature, sampling is NOT pinned and
    cannot be. Anything depending on run-to-run identity must say so rather than cite CELLARIUM_TEMPERATURE.
    """
    m = (model or "").lower()
    if thinking or any(fam in m for fam in _NO_EXPLICIT_TEMPERATURE):
        return None
    return TEMPERATURE


def temperature_is_rejected(exc: BaseException) -> bool:
    """Is this the API telling us the model will not accept an explicit temperature?

    Matched on the message rather than the status code alone, so an unrelated 400 (a malformed tool schema,
    an over-long request) is never silently retried into a second failure with a misleading cause.
    """
    s = str(exc).lower()
    return "temperature" in s and ("deprecat" in s or "not supported" in s or "unsupported" in s)
