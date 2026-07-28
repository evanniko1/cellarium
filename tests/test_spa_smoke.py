"""UX-3: a CI-runnable smoke test for the SPA — the ASGI app boots, serves the shell + its static assets, and the
shell carries the DOM mount points app.js queries (a removed mount / missing asset / renamed entry point breaks
here). Uses Starlette's TestClient — no browser, so it runs in CI; a full Playwright interaction test (which needs a
browser in CI) can layer on later."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps"))


def test_spa_shell_and_assets_serve():
    import server  # constructs the ASGI app (module-level stores bootstrap their SQLite; no model calls)
    from starlette.testclient import TestClient

    client = TestClient(server.app)

    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    for mount in ('id="app"', 'id="thread"', 'id="q"', 'id="srLive"'):   # the mount points app.js queries
        assert mount in html, f"index.html is missing {mount} — the SPA won't mount"
    assert "/static/app.js" in html and "/static/style.css" in html

    assert 'id="themeBtn"' in html                       # D-2: the theme toggle mount point
    assert "cellarium-theme" in html                     # D-2: the no-flash head init reads the saved theme
    for mount in ('id="skillsBtn"', 'id="skillsPalette"', 'id="skillChip"'):   # skills-discovery mount points
        assert mount in html, f"index.html is missing {mount} — the skills UX won't mount"

    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "function stream" in js.text and "function handle" in js.text   # the SPA's entry points still exist
    assert "cellarium-theme" in js.text                  # D-2: the toggle persists the choice
    for fn in ("function loadSkills", "function matchSkillFromInput", "function attachSkill"):
        assert fn in js.text, f"skills-discovery entry point {fn} missing"

    # the skills palette SSOT endpoint the composer reads on boot
    sk = client.get("/api/skills")
    assert sk.status_code == 200
    body = sk.json()
    assert "skills" in body and any(s["name"] == "peer-review" for s in body["skills"])

    css = client.get("/static/style.css")
    assert css.status_code == 200 and ".inline-err" in css.text            # UX-2's standardized error style present
    assert 'data-theme="dark"' in css.text               # D-2: the dark palette override is present


# ---------------- theming + overlay regressions (reported from screenshots) ----------------
def _css() -> str:
    import pathlib
    return pathlib.Path(__file__).parent.parent.joinpath("apps", "web", "style.css").read_text(encoding="utf-8")


def test_no_hardcoded_light_background_outside_the_token_blocks():
    """The dark-mode bug, generalised. `.topbar` carried a literal `rgba(250,249,245,.8)` — the light `--paper`
    inlined — so in dark mode the bar stayed near-white and the conversation title became unreadable against
    it. The whole stylesheet is otherwise token-driven, which is why exactly one rule broke: nothing else can
    fail this way unless someone reintroduces a literal. So the guard is structural rather than about one
    selector: after the palette definitions, no rule may set a light background literal."""
    import re
    css = _css()
    body = css[css.index("/* ---------------- main column"):]          # past every :root palette block
    bad = []
    for m in re.finditer(r"background\s*:\s*([^;}]+)", body):
        val = m.group(1).strip()
        if re.search(r"rgba?\(\s*2[0-4][0-9]\s*,\s*2[0-4][0-9]", val) or \
           re.search(r"#(?:[Ff]{3}\b|[Ff]{6}\b|[Ff][Aa][Ff]|[Ee][Ff][Ee])", val) or "white" in val.lower():
            if "--" in val or "gradient" in val:      # tokens and gradients are fine; literals are not
                continue
            bad.append(val)
    # the toggle knob is deliberately white in both themes (standard switch affordance)
    bad = [b for b in bad if b != "#fff"]
    assert not bad, f"hardcoded light background(s) will not flip in dark mode: {bad}"


def test_the_topbar_uses_a_theme_token_defined_in_every_palette():
    """The specific fix, pinned: the token must exist in the light root, the explicit dark root, AND the
    prefers-color-scheme block — a token missing from any one of them reintroduces the white bar for the
    users on that path."""
    css = _css()
    assert "background:var(--paper-blur)" in css, "the topbar must read a token, not a literal"
    assert css.count("--paper-blur:") >= 3, (
        "--paper-blur must be defined in :root, :root[data-theme=dark] and the @media dark block")


def test_chart_actions_cannot_paint_over_the_drawer():
    """vega-embed injects its own stylesheet giving the chart's '...' actions button a z-index in the
    thousands, so it rendered ON TOP of the settings drawer and stayed clickable there. Raising the drawer
    would only start an arms race with a vendored stylesheet; the fix is a stacking context on the chart
    container, which no descendant z-index can escape."""
    css = _css()
    i = css.index(".fig-chart{")
    assert "isolation:isolate" in css[i:i + 200], (
        ".fig-chart must create a stacking context so vendored z-indexes cannot escape it")


def test_the_page_declares_a_favicon_that_needs_no_network():
    """A missing favicon left the browser tab blank. It is inlined as a data URI so it survives the static
    policy, works offline, and needs no extra route."""
    import pathlib
    html = pathlib.Path(__file__).parent.parent.joinpath("apps", "web", "index.html").read_text(encoding="utf-8")
    assert 'rel="icon"' in html, "no favicon declared"
    assert "data:image/svg+xml" in html, "the favicon must be inlined, not a fetched file"
