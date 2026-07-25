"""Vendored Agent Skills (K-Dense, MIT) — loader + a domain-allow-listed HTTP fetch.

The skills under `skills/vendor/k-dense/` are prompt+reference packages (a SKILL.md plus per-API
reference docs) that instruct an agent to call scientific REST APIs. Cellwright loads a skill's text
with `load_skill()` and executes it over `web_get()` (a narrow, allow-listed HTTP GET that rides through
the normal tool dispatch, so every fetch shows up in the glass-box trace). See skills/vendor/k-dense/ATTRIBUTION.md.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

_SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent / "skills"
SKILLS_DIR = _SKILLS_ROOT / "vendor" / "k-dense"           # vendored, MIT/K-Dense (literature + bioinformatics)
CELLARIUM_SKILLS_DIR = _SKILLS_ROOT / "cellarium"          # PUB-1: Cellarium-authored publication/rigor skills
# collections searched, in order, by list_skills/load_skill — vendored first, then this project's own.
_ROOTS = (SKILLS_DIR, CELLARIUM_SKILLS_DIR)

# only scientific literature / bioinformatics endpoints the vendored skills actually call — a GET allow-list so the
# agent's web access can't be turned into an SSRF (no internal hosts, no arbitrary browsing).
_ALLOWED_HOSTS = (
    "eutils.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "api.openalex.org", "api.crossref.org",
    "api.semanticscholar.org", "api.biorxiv.org", "api.core.ac.uk", "api.unpaywall.org",
    "export.arxiv.org", "www.ebi.ac.uk", "rest.uniprot.org", "rest.kegg.jp", "www.rcsb.org",
    "api.biorxiv.org", "www.medrxiv.org", "pmc.ncbi.nlm.nih.gov",
)
_MAX_BYTES = 200_000


def list_skills() -> list[str]:
    names: set[str] = set()
    for root in _ROOTS:
        if root.exists():
            names.update(p.name for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").exists())
    return sorted(names)


def _skill_dir(name: str) -> Path | None:
    """First root (vendored, then Cellarium-authored) that carries this skill's SKILL.md."""
    for root in _ROOTS:
        if (root / name / "SKILL.md").exists():
            return root / name
    return None


def _summary(md_text: str, name: str) -> str:
    """One-line summary from a SKILL.md, bounded so the palette stays compact. Vendored K-Dense skills carry a YAML
    'description:' in frontmatter; the Cellarium-authored ones are '# name — summary'. Handle both."""
    lines = md_text.splitlines()
    if lines and lines[0].strip() == "---":                       # YAML frontmatter (K-Dense)
        for ln in lines[1:]:
            if ln.strip() == "---":
                break
            if ln.lower().startswith("description:"):
                first = ln.split(":", 1)[1].strip().split(". ")[0]   # first sentence only
                return first[:160].rstrip(".") + "."
    heading = next((ln for ln in lines if ln.startswith("# ")), "")  # '# name — summary' (Cellarium)
    for sep in ("—", " - ", "–"):
        if sep in heading:
            return heading.split(sep, 1)[1].strip()[:160]
    body = next((ln.strip() for ln in lines if ln.strip() and not ln.startswith(("#", "---"))), "")
    return (body[:160] or name)


def skills_manifest() -> list[dict]:
    """The available skills as presentation-ready metadata — the SSOT the surface reads so its palette never drifts
    from what's actually vendored/authored. group: 'publication' (Cellarium-authored) vs 'literature' (vendored)."""
    out = []
    for name in list_skills():
        root = _skill_dir(name)
        if root is None:
            continue
        group = "publication" if root.parent == CELLARIUM_SKILLS_DIR else "literature"
        out.append({"name": name, "group": group,
                    "summary": _summary((root / "SKILL.md").read_text(encoding="utf-8", errors="replace"), name)})
    return out


def load_skill(name: str, include_references: bool = True) -> dict:
    """Return a skill's SKILL.md (and, by default, its reference docs) so the agent has the instructions in context,
    then runs them (literature skills fetch with web_get; publication skills point at the toolkit's own tools).
    Bounded so a large skill can't blow the context. Searches the vendored K-Dense set and the Cellarium set."""
    root = _skill_dir(name)
    if root is None:
        return {"error": f"unknown skill '{name}'. available: {list_skills()}"}
    md = root / "SKILL.md"
    out = {"name": name, "skill": md.read_text(encoding="utf-8", errors="replace")}
    refs = root / "references"
    if include_references and refs.exists():
        out["references"] = {p.name: p.read_text(encoding="utf-8", errors="replace")[:20_000]
                             for p in sorted(refs.glob("*.md"))}
    return out


# The ONLY request headers a caller may set. `web_get` is the one tool whose URL *and* headers are model-supplied,
# which makes it the natural egress path for anything that ever leaks into context — so it is deliberately the
# narrowest surface in the codebase: no Authorization, no Cookie, no X-* passthrough.
_ALLOWED_HEADERS = frozenset({"accept", "accept-language", "user-agent", "if-modified-since", "if-none-match"})


class _AllowListRedirects(urllib.request.HTTPRedirectHandler):
    """Re-check the host allow-list on every hop.

    Without this the allow-list is decorative: urllib follows 30x by default, so an allow-listed host that
    redirects to an arbitrary one is a straight bypass. (NCBI and EBI both redirect in normal use, so refusing
    redirects outright is not an option — they have to be followed, and checked.)"""

    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        from urllib.parse import urlparse
        p = urlparse(newurl)
        if p.scheme not in ("http", "https") or (p.hostname or "").lower() not in _ALLOWED_HOSTS:
            raise urllib.error.HTTPError(newurl, code, f"redirect to non-allow-listed host '{p.hostname}'", hdrs, fp)
        return super().redirect_request(req, fp, code, msg, hdrs, newurl)


def web_get(url: str, headers: dict | None = None) -> dict:
    """A narrow HTTP GET for the literature/bioinformatics skills — allow-listed hosts only, size-capped. Returns
    {status, body} or {error}. This is how the vendored skills reach PubMed/OpenAlex/etc.; every call is a normal
    tool result, so it stays in the glass-box trace.

    Both arguments are model-supplied, so this is the one place where a credential that had somehow reached the
    model's context could leave the machine. It cannot today — there is no tool that can read the key — but the
    egress path is cheap to close and expensive to discover later, so: allow-listed hosts (re-checked across
    redirects), an allow-list of header NAMES, and a refusal if anything credential-shaped appears in either."""
    from urllib.parse import urlparse

    from . import redact
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https"):
        return {"error": f"scheme '{p.scheme}' is not fetchable; only http/https."}
    if host not in _ALLOWED_HOSTS:
        return {"error": f"host '{host}' is not in the literature/bioinformatics allow-list; refusing to fetch.",
                "allowed": list(_ALLOWED_HOSTS)}
    bad = sorted(k for k in (headers or {}) if k.lower() not in _ALLOWED_HEADERS)
    if bad:
        return {"error": f"header(s) {bad} are not permitted on an outbound fetch.",
                "allowed_headers": sorted(_ALLOWED_HEADERS)}
    # Refuse rather than scrub: a request carrying credential-shaped text is a bug or an injection, and silently
    # sending a sanitised version of it would hide that.
    if redact.looks_like_secret(url) or any(redact.looks_like_secret(str(v)) for v in (headers or {}).values()):
        return {"error": "refusing to fetch: the URL or headers contain credential-shaped text."}
    req = urllib.request.Request(url, headers={"User-Agent": "Cellarium/1.0 (research)", **(headers or {})})
    opener = urllib.request.build_opener(_AllowListRedirects)
    try:
        with opener.open(req, timeout=25) as r:
            raw = r.read(_MAX_BYTES + 1)
            body = raw[:_MAX_BYTES].decode("utf-8", errors="replace")
            return {"status": r.status, "truncated": len(raw) > _MAX_BYTES, "body": body}
    except urllib.error.HTTPError as e:
        # a refusal raised by _AllowListRedirects arrives here as an HTTPError too — keep ITS message, otherwise a
        # blocked redirect reads as a plain "HTTP 302" and neither the agent nor the user learns why.
        if "non-allow-listed" in str(getattr(e, "msg", "") or ""):
            return {"error": f"refused to follow a redirect: {e.msg}"}
        return {"error": f"HTTP {e.code}", "body": (e.read()[:2000].decode("utf-8", errors="replace") if e.fp else "")}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
