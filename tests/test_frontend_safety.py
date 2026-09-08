"""D-1: guard the innerHTML-escaping invariant so it can't silently rot. Escaping in the SPA is hand-maintained
across ~200 el()/innerHTML sinks; this lint fails CI if a NEW dynamic value is interpolated into an HTML string
without esc()/safe`` — the exact XSS-shaped mistake (Council claims, corpus rows, the queue's from_question, error
messages). It scopes to HTML template strings (those containing a `<` tag) and flags a bare data interpolation."""

import os
import re
from pathlib import Path

APP = os.path.join(os.path.dirname(__file__), "..", "apps", "web", "app.js")

# an interpolation is SAFE if it is escaped/rendered by a known-safe helper, or is numeric/index/static.
_SAFE_WRAP = re.compile(r"\b(esc|safe|md|inlineMd|relTime|trunc|pertLabel|primaryLabel|pertIcon|skillIcon)\s*\(")
_NUMERIC = re.compile(r"\.(length|size|rounds|seeds|generations|fid|round|toFixed)\b"
                      r"|\bn_\w+|\bi \+ 1\b|×|^\s*[\d.\s+\-*/()]+$")
_STATIC = re.compile(r"^[A-Z][A-Z0-9_]{2,}\b")   # ALL-CAPS static consts (CHEV_SVG, ARROW_SVG, FLASK_SVG, …)
# reviewed-safe interpolations that are NOT esc-wrapped but carry no attacker-controlled data (static maps,
# computed local labels built from literals, numeric/renderer/pre-escaped locals). Keep this list SHORT + reviewed.
_ALLOW = re.compile(r"""
    \? \s* ["'][^"']*["'] \s* : |          # a ternary whose branches are string literals (class flags etc.)
    \b(blab|bcls|role|st|which|kind|q_?id|count|html|meta|h|it|p)\b |   # numeric / renderer / pre-escaped locals
    it\.[kv]\b                             # the STATIC demo ARCH array (hard-coded copy)
""", re.X)


def _flagged():
    src = open(APP, encoding="utf-8").read().splitlines()
    out = []
    for ln, line in enumerate(src, 1):
        if "<" not in line or "${" not in line:
            continue                                   # only HTML-shaped template strings
        for m in re.finditer(r"\$\{([^{}]*)\}", line):
            expr = m.group(1).strip()
            if _SAFE_WRAP.search(expr) or _NUMERIC.search(expr) or _STATIC.search(expr) or _ALLOW.search(expr):
                continue
            out.append((ln, expr))
    return out


def test_no_unescaped_data_in_html_sinks():
    flagged = _flagged()
    assert not flagged, ("Unescaped interpolation into an HTML string (D-1) — wrap the value in esc() or use the "
                         "safe`` tagged template:\n" + "\n".join(f"  app.js:{ln}  ${{{e}}}" for ln, e in flagged))


def test_lint_is_not_vacuous():
    """Guard the guard: the classifier must FLAG a raw data interpolation, so the lint can't silently pass all."""
    e = "r.userText"                                          # a bare data property, unescaped
    assert not (_SAFE_WRAP.search(e) or _NUMERIC.search(e) or _STATIC.search(e) or _ALLOW.search(e))
    assert _SAFE_WRAP.search("esc(r.userText)")               # ...but the esc()-wrapped form is safe


def test_esc_escapes_quotes():
    """esc() must escape quotes too, or a value in class=\"…\"/title=\"…\" can break out of the attribute."""
    src = open(APP, encoding="utf-8").read()
    esc_def = src[src.index("const esc ="):src.index("const safe")]   # the full multi-line esc definition
    assert "&quot;" in esc_def and "&#39;" in esc_def and "&lt;" in esc_def


# ---------------------------------------------------------------------------------------------------
# UX-3 — palettes
# ---------------------------------------------------------------------------------------------------
def test_every_palette_defines_both_light_and_dark():
    """A palette that defines only a light block renders dark text on a dark ground for anyone whose OS
    is set to dark -- the theme toggle is INDEPENDENT of the palette, so both modes must exist. Three
    blocks each, the same shape the base theme uses."""
    css = Path("apps/web/style.css").read_text(encoding="utf-8")
    for pal in ("lab", "gfp"):
        assert f':root[data-palette="{pal}"]{{' in css, f"{pal}: no light block"
        assert f':root[data-palette="{pal}"][data-theme="dark"]{{' in css, f"{pal}: no explicit dark block"
        assert f':root[data-palette="{pal}"]:not([data-theme="light"])' in css, (
            f"{pal}: no prefers-color-scheme block, so a system-dark user gets the light palette")


def test_no_palette_leaves_a_hardcoded_accent_behind():
    """The brand mark's gradient highlight was a literal clay tint, so the logo kept an orange sheen under
    every palette -- caught by looking at the rendered page, not by reading the CSS. It is a token now, and
    every palette that redefines --clay must redefine it too or the mark stops matching its own accent."""
    css = Path("apps/web/style.css").read_text(encoding="utf-8")
    assert "#E08A63" not in css.split("UX-3 — PALETTES")[0].split(".brand-mark")[1][:400], (
        "the brand mark still hardcodes a clay highlight")
    body = css[css.index("UX-3 — PALETTES"):]
    for block in body.split(":root[data-palette=")[1:]:
        head = block[:block.index("}")]
        if "--clay:" in head:
            assert "--mark-lift:" in head, f"a palette redefines --clay without --mark-lift: {head[:60]}"


def test_the_palette_is_restored_before_paint():
    """Same guarantee the theme toggle already has: applied in a head script, or the first frame renders in
    the default palette and visibly repaints."""
    html = Path("apps/web/index.html").read_text(encoding="utf-8")
    head = html[:html.index("</head>")]
    assert "cellarium-palette" in head, "the palette is not re-applied before paint, so it will flash"


def test_the_brand_mark_is_a_box_not_a_hexagon():
    """The mark is an E. coli rod inside the glass box the project is named for. The first attempt drew the
    cube in ISOMETRIC projection, whose silhouette is a hexagon -- i.e. the exact shape the styling critique
    objected to. Oblique projection reads as a container instead."""
    html = Path("apps/web/index.html").read_text(encoding="utf-8")
    assert "M12 2 21 7v10l-9 5-9-5V7z" not in html, "the old hexagon mark is still present"
    assert html.count('<rect x="4.5" y="8.5" width="11" height="11"') >= 2, "the box face is missing"
    assert html.count('d="M7.9 16.1 12.1 11.9"') >= 2, "the cell rod is missing"
