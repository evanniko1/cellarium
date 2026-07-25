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

import re

MARK = "[redacted]"

# High-signal, known-prefix token shapes — the same family CI's secret scan looks for, plus the generic Bearer
# header. Deliberately NOT entropy-based: a false positive here silently corrupts scientific output, so this only
# fires on shapes that are unambiguously credentials.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), f"sk-ant-{MARK}"),
    (re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_\-]{20,}"), f"sk-{MARK}"),            # OpenAI-style
    (re.compile(r"\bhf_[A-Za-z0-9]{16,}"), f"hf_{MARK}"),                       # HuggingFace
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), f"ghp_{MARK}"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{16,}"), r"\1" + MARK),
    (re.compile(r"(?i)\b(x-api-key['\"\s:=]+)[A-Za-z0-9._\-]{16,}"), r"\1" + MARK),
)

# Field names whose VALUE is a secret regardless of shape — used when scrubbing structured data.
_SECRET_FIELD = re.compile(r"(?i)(^|_)(api[_-]?key|apikey|secret|token|authorization|password|passwd|credential)s?($|_)")


def scrub(text: str) -> str:
    """Replace every credential-shaped run in `text`. Safe on any string; returns it unchanged when clean."""
    out = str(text)
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out


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
