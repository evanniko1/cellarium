"""Pattern-based secret scrubbing for strings on their way OUT of the process.

Separate from `credentials` on purpose. This module holds no secret, reads no keychain and touches no environment
— it is pure text substitution — so the modules that must never reach the vault (agent.py above all) can still
scrub what they emit. That keeps invariant I1 ("the key never enters the LLM context") checkable as a module
boundary while still letting every funnel defend itself.

Why pattern-based rather than "replace the key we know about": the leak the audit actually found is not the
configured key being printed on purpose, it is a MALFORMED one being echoed by a library. A key pasted with a
trailing newline — the single most likely artifact of a paste-into-a-text-field UI, which is exactly what the
Settings panel now is — makes httpx raise `LocalProtocolError: Illegal header value b'sk-ant-…\\n'`. The outermost
SDK exception is clean, but `traceback.format_exc()` is not, and that is what `exc_info=True` logging emits. A
pattern catches that (and an OpenAI or HuggingFace token in the same position) whether or not it is the value we
currently hold.

Three funnels use this, chosen because everything else drains through them:
  * apps/server.py `_jsonsafe`        — everything the browser is sent (and thence localStorage)
  * agent.py `_truncate_tool_result`  — everything a tool puts into the model's context
  * `install_log_filter()`            — the only mechanism that reaches `exc_info` traceback text
"""

from __future__ import annotations

import os
import re

MARK = "[redacted]"

# Environment variables stripped before handing an environment to a child process (see child_env). Names, not
# shapes — a credential's variable name is the reliable signal here, and the list is identical on every OS.
_SECRET_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
               "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACEHUB_API_TOKEN", "AWS_ACCESS_KEY_ID",
               "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")
# ANTHROPIC_AUTH_TOKEN is the SDK's gateway/proxy bearer variable — and exactly the shape-less token class that
# no pattern can recognise, so leaving it out was the one real gap in this list. Windows normalises environment
# names to uppercase and POSIX is case-sensitive, so an uppercase list matches correctly on both.

# High-signal, known-prefix token shapes — the same family CI's secret scan looks for, plus the generic Bearer
# header. Deliberately NOT entropy-based: a false positive here silently corrupts scientific output, so this only
# fires on shapes that are unambiguously credentials.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), f"sk-ant-{MARK}"),
    (re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_\-]{20,}"), f"sk-{MARK}"),            # OpenAI-style
    (re.compile(r"\bhf_[A-Za-z0-9]{16,}"), f"hf_{MARK}"),                       # HuggingFace
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), f"ghp_{MARK}"),
    # The token must contain a DIGIT and run 20+ chars. Without that guard "bearer responsibilities" — a plain
    # English phrase, 16 letters — is redacted, and this scrub now runs over every saved transcript, so a false
    # positive would silently corrupt scientific text. Real bearer tokens are never all-alphabetic.
    (re.compile(r"(?i)\b(bearer\s+)(?=[A-Za-z0-9._\-]*\d)[A-Za-z0-9._\-]{20,}"), r"\1" + MARK),
    (re.compile(r"(?i)\b(x-api-key['\"\s:=]+)(?=[A-Za-z0-9._\-]*\d)[A-Za-z0-9._\-]{16,}"), r"\1" + MARK),
)

# Field names whose VALUE is a secret regardless of shape — used when scrubbing structured data.
_SECRET_FIELD = re.compile(r"(?i)(^|_)(api[_-]?key|apikey|secret|token|authorization|password|passwd|credential)s?($|_)")


# Literal values registered by the vault at set/load time. Patterns only catch KNOWN prefixes, so a key with no
# recognisable shape — an LLM-gateway, LiteLLM, Bedrock-proxy or self-hosted-router token, all of which the vault
# accepts — would sail through every funnel untouched. Registering the literal closes that without teaching this
# module how to READ a credential: it never touches the keychain or the environment, it is only ever told.
_LITERALS: set[str] = set()


def register_secret(value: str | None) -> None:
    """Tell the scrubber about a literal secret so shape-blind values are caught too. Idempotent; short values are
    ignored, because replacing a common short string everywhere would corrupt far more than it protects."""
    v = (value or "").strip()
    if len(v) >= 16:
        _LITERALS.add(v)


def forget_secret(value: str | None = None) -> None:
    """Drop one literal (or all of them) — called when the key is cleared or replaced."""
    if value is None:
        _LITERALS.clear()
    else:
        _LITERALS.discard((value or "").strip())


def scrub(text: str) -> str:
    """Replace every credential-shaped run in `text`. Safe on any string; returns it unchanged when clean."""
    out = str(text)
    for lit in _LITERALS:                     # exact registered values first — these have no recognisable shape
        if lit in out:
            out = out.replace(lit, MARK)
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out


def looks_like_secret(text: str) -> bool:
    """True if `text` contains a credential-shaped run. The detect-only twin of scrub(), for the callers that must
    REFUSE rather than sanitise — an outbound request, or a snapshot about to be committed to git."""
    return scrub(text) != str(text)


def child_env(base: dict | None = None, *extra: str) -> dict:
    """A copy of the environment with credentials removed, for handing to a subprocess.

    COPY-and-remove, never build-from-scratch: a minimal env breaks child processes on Windows (which needs
    SYSTEMROOT/PATH/TEMP to start almost anything) and loses the PATH that finds `docker` and `git` everywhere
    else. The removals are the same on every OS, so behaviour does not diverge by platform.

    Docker was never the exposure here — `docker run` passes only explicitly `-e`'d variables into the container,
    so the key never crossed into the sim. What this closes is the host-side child (the `docker`/`git` CLI itself)
    inheriting a credential it has no use for."""
    env = dict(base if base is not None else os.environ)
    for k in (*_SECRET_ENV, *extra):
        env.pop(k, None)
    return env


def scrub_obj(obj, _depth: int = 0):
    """Recursively scrub strings inside dicts/lists/tuples, and blank any value under a secret-looking KEY name.

    The key-name rule is what catches a credential that does not match a known prefix (a Bedrock or self-hosted
    token, say) but was nonetheless placed in a field honestly called `api_key`."""
    if _depth > 12:                                   # pathological nesting: stop rather than recurse forever
        return obj
    if isinstance(obj, str):
        return scrub(obj)
    if isinstance(obj, dict):
        return {k: (MARK if (isinstance(k, str) and _SECRET_FIELD.search(k) and isinstance(v, str) and v)
                    else scrub_obj(v, _depth + 1)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub_obj(v, _depth + 1) for v in obj]
    return obj


class _Filter:
    """A logging.Filter that rewrites the formatted record — including the traceback that `exc_info=True` adds.

    Filters are the only hook that sees a record before formatting AND can mutate it, which is why this is not a
    Formatter: `tools.py` logs internal defects with `exc_info=True`, and the chained traceback is precisely where
    the audit found a malformed key surviving in plaintext."""

    def filter(self, record) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = scrub(record.msg)
            if record.args:
                record.args = (tuple(scrub_obj(a) for a in record.args) if isinstance(record.args, tuple)
                               else scrub_obj(record.args))
            if record.exc_info and record.exc_info[1] is not None:
                import traceback
                record.exc_text = scrub("".join(traceback.format_exception(*record.exc_info)))
                record.exc_info = None                # we own the rendered text now; drop the live objects
        except Exception:
            pass                                      # a logging filter must never raise into the caller
        return True


def install_log_filter(*names: str) -> None:
    """Attach the scrubbing filter to Cellarium's loggers. Idempotent — re-installing does not stack filters."""
    import logging
    for name in (names or ("cellarium", "cellarium.tools")):
        lg = logging.getLogger(name)
        if not any(isinstance(f, _Filter) for f in lg.filters):
            lg.addFilter(_Filter())
