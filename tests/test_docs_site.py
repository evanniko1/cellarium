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
    cfg = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))
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
