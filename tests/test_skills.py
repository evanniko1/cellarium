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


def test_skills_manifest_groups_and_summaries():
    """The composer-palette SSOT: every skill has a group + a non-empty one-line summary, parsed from BOTH the
    vendored K-Dense YAML-frontmatter format and the Cellarium '# name — summary' format."""
    man = skills.skills_manifest()
    by_name = {s["name"]: s for s in man}
    assert {"peer-review", "scientific-writing", "uncertainty-quantification"} <= set(by_name)
    assert by_name["peer-review"]["group"] == "publication"          # Cellarium-authored
    assert by_name["paper-lookup"]["group"] == "literature"          # vendored K-Dense
    for s in man:
        assert s["summary"] and s["summary"] != "---"                # both formats parsed, no frontmatter leak
        assert len(s["summary"]) <= 161
    # the Cellarium em-dash summary is the post-dash text, not the bare name
    assert by_name["peer-review"]["summary"].lower().startswith("pre-submission")


def test_publication_skills_present_and_loadable():
    """PUB-1: the Cellarium-authored publication skills load through the SAME loader as the vendored ones."""
    have = skills.list_skills()
    for s in ("scientific-writing", "peer-review", "uncertainty-quantification"):
        assert s in have, f"publication skill missing: {s}"
        out = skills.load_skill(s)
        assert "skill" in out and len(out["skill"]) > 400, f"{s} SKILL.md too thin / missing"
    # they must point at the project's OWN rigor tools (grounded), not fetch anything
    uq = skills.load_skill("uncertainty-quantification")["skill"]
    assert "disconfirm" in uq and "power_check" in uq and "robustness_check" in uq
    pr = skills.load_skill("peer-review")["skill"]
    assert "in-sample" in pr.lower() and "model_under_predicts" in pr.lower()


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
