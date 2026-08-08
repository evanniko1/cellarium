"""Every appendix the paper cites must exist, and every appendix must be cited.

Renaming or reordering an appendix silently invalidates the pointers to it, and the rename always reports
success. MEASURED 2026-08-07 on this paper: renumbering the clamp appendix from C to D redirected Section 3's
dose-response citation onto the wrong table, and a fifth appendix ended up with no citation at all, so it was
unreachable from the body. Neither showed up in the page count, in the packer's lossless assertion, or in a
read-through by six independent checkers.

The first version of this check passed on the correct document AND on a deliberately broken one, which is
worse than no check: it invites exactly the trust that let the rename through. Its fault was asymmetry --
it searched the RAW appendix for headings while searching an ENTITY-STRIPPED body for citations, so the two
sides were reading different text and the comparison failed open. Hence `test_check_fires_*` below: a check
that cannot be shown to fail is not evidence of anything.
"""
import re

import pytest


def appendix_problems(body_html: str, appendix_html: str) -> list[str]:
    """Cross-check citations against definitions. Both sides are normalised the same way, deliberately."""
    def norm(x: str) -> str:
        x = re.sub(r'&nbsp;|&#160;', ' ', x)
        return re.sub(r'\s+', ' ', x)

    heads = norm(appendix_html)
    defined = set(re.findall(r'<h2>\s*Appendix\s+([A-Z])\b', heads))
    cited = set(re.findall(r'Appendix\s+([A-Z])\b', norm(re.sub(r'<[^>]*>', ' ', body_html))))
    problems = ["body cites Appendix %s, which the appendix file does not define" % x
                for x in sorted(cited - defined)]
    problems += ["Appendix %s is defined but never cited from the body" % x
                 for x in sorted(defined - cited)]
    problems += ["invalid appendix label %r: labels are single letters" % x
                 for x in sorted(set(re.findall(r'Appendix\s+([A-Z]\d)', heads)))]
    return problems


APX = ('<h2>Appendix&nbsp;A&nbsp;&nbsp;The limits test</h2>'
       '<h2>Appendix&nbsp;B&nbsp;&nbsp;The four kinds</h2>'
       '<h2>Appendix&nbsp;C&nbsp;&nbsp;Isoacceptor charging</h2>')
BODY = ('<p>as shown in Appendix&nbsp;A, and the cases in Appendix&nbsp;B, '
        'with charging in Appendix&nbsp;C.</p>')


def test_clean_document_has_no_problems():
    assert appendix_problems(BODY, APX) == []


def test_check_fires_on_a_dangling_citation():
    """The failure that actually happened: a rename left the body pointing at a letter that is not defined."""
    broken = BODY.replace("Appendix&nbsp;C", "Appendix&nbsp;Z")
    problems = appendix_problems(broken, APX)
    assert any("cites Appendix Z" in p for p in problems), problems
    assert any("Appendix C is defined but never cited" in p for p in problems), problems


def test_check_fires_on_an_uncited_appendix():
    """The other half: an appendix nothing points at is unreachable from the body."""
    problems = appendix_problems(BODY.replace(", with charging in Appendix&nbsp;C", ""), APX)
    assert problems == ["Appendix C is defined but never cited from the body"], problems


def test_check_fires_on_an_invalid_label():
    """'B2' is what you get from inserting a section beside an existing B and dodging the duplicate."""
    problems = appendix_problems(BODY, APX + '<h2>Appendix&nbsp;B2&nbsp;&nbsp;Something</h2>')
    assert any("invalid appendix label" in p for p in problems), problems


def test_entities_do_not_hide_a_break():
    """Both sides must be normalised identically; the original check normalised only one and failed open."""
    assert appendix_problems(BODY.replace("&nbsp;", " "), APX) == []
    assert appendix_problems(BODY, APX.replace("&nbsp;", " ")) == []


@pytest.mark.parametrize("sep", ["&nbsp;", " ", "&#160;"])
def test_separator_variants_all_parse(sep):
    assert appendix_problems(BODY.replace("&nbsp;", sep), APX.replace("&nbsp;", sep)) == []
