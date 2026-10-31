"""DOC-1 — the documentation site's navigation must describe what a CLONER receives, not what I have locally.

THE FAILURE THIS PREVENTS, caught the first time within minutes of writing the nav. Two planning documents
(`HYPOTHESIS_MODE_PLAN.md`, `ROADMAP.md`) are deliberately gitignored — planning docs stay local so a person
cloning the repo does not receive a list of unbuilt ideas. They are present in my working tree, so
`mkdocs build --strict` passed here; they are absent from a fresh checkout, so the same command would have
failed in CI on a page it could not find. Green locally, red in CI, for a reason invisible from the machine
that wrote it.

`mkdocs --strict` already catches a nav entry with no file. It cannot catch a nav entry whose file exists
only for me, because by the time CI notices, the build has already failed and the signal is a missing page
rather than an untracked one. This test asks the question directly and gives the actionable answer.

The second assertion is the mirror: a tracked document that no section lists is unreachable from the site,
which is precisely the condition DOC-1 exists to remove (24 files, ~400 KB, no way in). Adding a doc without
a nav entry recreates it one file at a time.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MKDOCS = ROOT / "mkdocs.yml"

# Pages the site is allowed to render without a nav entry. `index.md` IS the landing page — it is reachable
# by definition and listing it twice would show it twice in the sidebar.
NAV_EXEMPT = {"index.md"}


def _nav_pages() -> list[str]:
    yaml = pytest.importorskip("yaml", reason="pyyaml is needed to read mkdocs.yml")

    # mkdocs.yml legitimately carries MkDocs-specific tags — `!!python/name:material.extensions.emoji.…`
    # wires Material's icon index into pymdownx.emoji. `safe_load` refuses them outright (it is refusing to
    # import arbitrary Python, which is correct of it), so this test crashed on a perfectly valid config the
    # moment those icons were enabled. Only the `nav` tree is read here, so the tags are irrelevant to the
    # question being asked: ignore them rather than executing them.
    class _TagTolerant(yaml.SafeLoader):
        pass

    _TagTolerant.add_multi_constructor(
        "tag:yaml.org,2002:python/name:", lambda loader, suffix, node: suffix)

    cfg = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=_TagTolerant)
    out: list[str] = []

    def walk(node):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(cfg["nav"])
    return out


def _tracked_docs() -> set[str]:
    """Markdown under docs/ as GIT sees it — the set a fresh clone actually receives."""
    p = subprocess.run(["git", "ls-files", "docs/"], cwd=ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        pytest.skip("not a git checkout, so 'what a cloner receives' is unanswerable here")
    return {line[len("docs/"):] for line in p.stdout.split() if line.endswith(".md")}


@pytest.mark.skipif(not MKDOCS.is_file(), reason="no mkdocs.yml in this checkout")
def test_every_nav_entry_is_a_file_a_cloner_would_receive():
    """A nav entry pointing at a gitignored file builds for me and fails for everyone else."""
    tracked = _tracked_docs()
    missing = [f for f in _nav_pages() if f not in tracked]
    assert not missing, (
        "these nav entries are not tracked by git, so `mkdocs build --strict` will fail on a fresh clone "
        f"and in CI even though it passes locally: {missing}. Either track the file or drop it from the nav "
        "— do not leave the site describing documents only one machine has.")


@pytest.mark.skipif(not MKDOCS.is_file(), reason="no mkdocs.yml in this checkout")
def test_every_tracked_doc_is_reachable_from_the_navigation():
    """An unlisted page is the exact condition DOC-1 removed: present, and findable only by guessing."""
    listed = set(_nav_pages()) | NAV_EXEMPT
    orphans = sorted(_tracked_docs() - listed)
    assert not orphans, (
        f"these documents ship but no section lists them, so nobody finds them without knowing the "
        f"filename: {orphans}. That is the problem the site was built to fix — add each to `nav` in "
        "mkdocs.yml under the question a reader would be asking.")


def test_no_shipped_doc_links_to_a_file_a_cloner_will_not_have():
    """The gap the first version of this file left open, and CI found it within one push.

    `test_every_nav_entry_is_a_file_a_cloner_would_receive` checks the NAV. It says nothing about a link in
    the BODY of a page — and `index.md` linked to `ROADMAP.md`, which is gitignored. Locally the file is
    present so `mkdocs build --strict` passed; in CI the page does not exist and the build aborted. Same
    class, one level down, and the lesson is that "tracked" has to be checked wherever a path is written,
    not only where the nav lists one.
    """
    import re

    tracked = _tracked_docs()
    offenders = []
    for name in sorted(tracked):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        for m in re.finditer(r"\]\(([^)#]+\.md)(?:#[^)]*)?\)", text):
            target = m.group(1)
            if target.startswith(("http://", "https://")):
                continue          # an absolute URL is someone else's problem to resolve
            resolved = (ROOT / "docs" / name).parent.joinpath(target).resolve()
            try:
                rel = resolved.relative_to(ROOT / "docs").as_posix()
            except ValueError:
                continue          # points outside docs/ (e.g. a GitHub blob link) — not mkdocs's to resolve
            if rel not in tracked:
                offenders.append(f"{name} -> {target}")
    assert not offenders, (
        "these links point at documents a fresh clone does not receive, so `mkdocs build --strict` fails in "
        f"CI while passing locally: {offenders}. Either track the target or drop the link.")


# --- NMI-3: the citation file ------------------------------------------------------------------------

def test_the_citation_file_agrees_with_the_LICENSE_and_the_package_metadata():
    """A published artefact nobody checks drifts. NMI-3 exists because the absence of our own citation
    metadata was conspicuous next to the DOIs this repo cites correctly for everyone else's work; a
    CITATION.cff that disagreed with LICENSE or pyproject would be the same defect wearing a file."""
    import re

    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "cff-version: 1.2.0" in text
    # The author is the copyright holder named in LICENSE, not an inference from the commit log.
    holder = re.search(r"Copyright \(c\) \d{4} (.+)", (ROOT / "LICENSE").read_text(encoding="utf-8"))
    assert holder and holder.group(1).strip() == "Evangelos-Marios Nikolados"
    assert "family-names: Nikolados" in text and "given-names: Evangelos-Marios" in text
    version = re.search(r'^version = "(.+?)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                        re.M)
    assert version and f"version: {version.group(1)}" in text
    assert "license: MIT" in text


def test_the_citation_file_asserts_NO_DOI_rather_than_a_plausible_one():
    """The half of NMI-3 that cannot be done here: a DOI needs a deposit only the owner can make. A
    fabricated identifier resolves to somebody else's work, so its absence is pinned -- and the two other
    gaps (co-authorship, and the data-availability wording that waits on the upstream licence question)
    are named in the file rather than quietly left out."""
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    own = [ln for ln in text.splitlines()
           if ln.startswith("doi:") or ln.startswith("identifiers:")]
    assert not own, f"CITATION.cff claims a DOI for Cellarium itself: {own}"
    # Other people's DOIs under `references:` are exactly what SHOULD be there.
    assert "10.5281/zenodo.7859480" in text
    for gap in ("Zenodo", "co-authors", "ORCID", "DATA-AVAILABILITY"):
        assert gap in text, gap
