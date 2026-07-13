"""Vendored Agent Skills (K-Dense, MIT): the loader + the allow-listed HTTP fetch that Cellwright runs them over."""

from cellarium import skills, tools


def test_vendored_skills_present_and_loadable():
    have = skills.list_skills()
    for s in ("paper-lookup", "literature-review", "bgpt-paper-search", "cobrapy", "experimental-design"):
        assert s in have, f"vendored skill missing: {s}"
    lit = skills.load_skill("paper-lookup")
    assert "skill" in lit and lit["skill"].strip()               # SKILL.md text present
    assert lit.get("references"), "paper-lookup should carry its per-API reference docs"
    assert any("pubmed" in k for k in lit["references"])          # the PubMed endpoint doc is there


def test_load_skill_unknown_returns_error():
    out = skills.load_skill("not-a-skill")
    assert "error" in out and "available" in out["error"]


def test_web_get_refuses_non_allowlisted_host():
    out = skills.web_get("http://169.254.169.254/latest/meta-data/")   # SSRF target must be refused
    assert "error" in out and "allow-list" in out["error"]
    out2 = skills.web_get("https://evil.example.com/x")
    assert "error" in out2


def test_web_get_allows_scientific_hosts(monkeypatch):
    # an allow-listed host is attempted (we stub the network so the test stays offline)
    class _Resp:
        status = 200
        def read(self, n): return b'{"ok": true}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(skills.urllib.request, "urlopen", lambda *a, **k: _Resp())
    out = skills.web_get("https://api.openalex.org/works?search=aars")
    assert out.get("status") == 200 and "ok" in out["body"]


def test_skill_tools_registered():
    assert "use_skill" in tools._DISPATCH and "web_get" in tools._DISPATCH
    assert any(t["name"] == "use_skill" for t in tools.TOOLS)
    assert any(t["name"] == "web_get" for t in tools.TOOLS)
