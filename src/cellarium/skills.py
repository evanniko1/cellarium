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


def web_get(url: str, headers: dict | None = None) -> dict:
    """A narrow HTTP GET for the literature/bioinformatics skills — allow-listed hosts only, size-capped. Returns
    {status, body} or {error}. This is how the vendored skills reach PubMed/OpenAlex/etc.; every call is a normal
    tool result, so it stays in the glass-box trace."""
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        return {"error": f"host '{host}' is not in the literature/bioinformatics allow-list; refusing to fetch.",
                "allowed": list(_ALLOWED_HOSTS)}
    req = urllib.request.Request(url, headers={"User-Agent": "Cellarium/1.0 (research)", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read(_MAX_BYTES + 1)
            body = raw[:_MAX_BYTES].decode("utf-8", errors="replace")
            return {"status": r.status, "truncated": len(raw) > _MAX_BYTES, "body": body}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": (e.read()[:2000].decode("utf-8", errors="replace") if e.fp else "")}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
