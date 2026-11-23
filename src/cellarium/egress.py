"""Every external read a run makes, recorded -- and the dataset hosts kept out of the runs that must stay blind.

VALIDATION_LAYER_SPEC item 7, built 2026-11-23. Since 2026-11-14 Cellarium can read two remote corpora
(`corpora.py`: its own Hugging Face deposit and cSynBioSys/well4cell), and the Socratic Council's librarian can
search the web. The Council is supposed to frame its hypothesis BLIND to the corpus results (the quarantine
control; tests/test_blindness.py). Until now nothing recorded what the librarian's searches returned, and nothing
kept a search away from the dataset pages, so a blind run could not afterwards be shown to have stayed blind --
and a blind run made without a record can never be shown clean later, which is why this lands before the next
one rather than after.

Three parts, each small:

  * `BLIND_BLOCKED_DOMAINS` -- the hosts a blind run may not read: the Hugging Face hub (both corpora live
    there, and a dataset card summarises results) and this project's own repository (its committed eval results
    and docs quote corpus findings). The librarian passes them to the web-search tool as `blocked_domains`.
  * `audit()` -- checks every URL a run actually saw against the same list, AFTER the fact. The request-side block
    is the API's to enforce and its subdomain rule is not documented; this check is ours, matches subdomains
    explicitly, and is what decides. A run whose audit is not clean has its librarian brief discarded before any
    Council role sees it, and is refused by the eval scorer (`evals/shared_metric.from_council`) as an
    environment fault -- never a score.
  * `record()` -- puts every remote corpus or dataset read on the observability stream, so a run's trace lists
    what it fetched (repository, path, purpose) next to what it cost.

LIMITS, stated rather than implied. (1) The live API has not been called with `blocked_domains` in this build;
the request shape follows the documented tool (platform.claude.com, web search tool) and is pinned by test, and a
rejected request would surface as a recorded librarian error rather than a silent absence. (2) This guards the
WEB path only. What the underlying model already knows from training is not a fetch and is not caught here: that
is the cutoff-dating question (PUB-A4), which this module does not answer. (3) Text the search engine returns
from an UNLISTED host that happens to quote a corpus result is not caught; the list names hosts, not content.
"""

from __future__ import annotations

from urllib.parse import urlparse

from . import observability

# Bare domains match the host and every subdomain; an entry with a path matches that host and path prefix.
# The web-search tool takes the same shape: "bare domains with an optional path ... without a scheme".
BLIND_BLOCKED_DOMAINS: tuple[str, ...] = (
    "huggingface.co",                       # both corpora, their dataset cards, and the hub's file CDN subdomains
    "hf.co",                                # the hub's short domain
    "github.com/evanniko1/cellarium",       # this project's own repository: committed results and docs
)


class BlindnessBreach(RuntimeError):
    """A run that must stay blind read a blocked host. An environment fault, never a score."""


def _rule_for(url: str, blocked: tuple[str, ...]) -> str | None:
    p = urlparse(url if "://" in url else f"https://{url}")
    host = (p.hostname or "").lower()
    path = (p.path or "/").lower()
    for rule in blocked:
        dom, _, prefix = rule.lower().partition("/")
        if host == dom or host.endswith("." + dom):
            if not prefix or path == "/" + prefix or path.startswith("/" + prefix + "/"):
                return rule
    return None


def blocked_rule(url: str, blocked: tuple[str, ...] | None = None) -> str | None:
    """The blocking rule `url` falls under, or None. `nothuggingface.co` is NOT under `huggingface.co`."""
    return _rule_for(url, BLIND_BLOCKED_DOMAINS if blocked is None else blocked)


def audit(urls: list[str], blocked: tuple[str, ...] | None = None) -> dict:
    """Every URL a blind run saw, checked against the block list. `clean` is False on any breach."""
    blocked = BLIND_BLOCKED_DOMAINS if blocked is None else blocked
    seen = sorted({u for u in urls if u})
    breaches = [{"url": u, "rule": r} for u in seen if (r := _rule_for(u, blocked))]
    return {"n_urls": len(seen), "hosts": sorted({(urlparse(u).hostname or "") for u in seen}),
            "breaches": breaches, "clean": not breaches, "rules": list(blocked)}


def record(via: str, url: str, *, purpose: str, **detail) -> dict:
    """One external read on the observability stream. Never raises: a broken sink must not break a read."""
    host = urlparse(url if "://" in url else f"https://{url}").hostname or ""
    return observability.emit({"kind": "external_read", "via": via, "url": url, "host": host,
                               "purpose": purpose, **detail})
