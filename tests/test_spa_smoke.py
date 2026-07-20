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

    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "function stream" in js.text and "function handle" in js.text   # the SPA's entry points still exist
    assert "cellarium-theme" in js.text                  # D-2: the toggle persists the choice

    css = client.get("/static/style.css")
    assert css.status_code == 200 and ".inline-err" in css.text            # UX-2's standardized error style present
    assert 'data-theme="dark"' in css.text               # D-2: the dark palette override is present
