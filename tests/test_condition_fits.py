"""Y10: who decided to fit a condition, and when. A row only in the local checkout's working tree but committed on the
public campaign branch must be attributed to that public commit and its date, not called "uncommitted"."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import condition_fits as CF  # noqa: E402

HEADER = '"condition"\t"nutrients"\t"doubling time (units.min)"\t"active TFs"\t"inactive TFs"\n'


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "GIT_AUTHOR_DATE": "2026-11-25T12:00:00",
                        "GIT_COMMITTER_DATE": "2026-11-25T12:00:00", "PATH": __import__("os").environ["PATH"]})


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "wc"
    f = root / CF.FLAT / "condition" / "condition_defs.tsv"
    f.parent.mkdir(parents=True)
    f.write_text(HEADER + '"basal"\t"minimal"\t44.0\t[]\t[]\n', encoding="utf-8")
    _git(root.parent, "init", "-q", "-b", "local", str(root))
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "basal")
    _git(root, "checkout", "-q", "-b", "public")
    f.write_text(f.read_text(encoding="utf-8") + '"no_oxygen_plus_nitrate"\t"x"\t82.0\t[]\t[]\n', encoding="utf-8")
    _git(root, "commit", "-q", "-am", "anaerobic nitrate")
    _git(root, "checkout", "-q", "local")
    # the local checkout carries the same row uncommitted, as C:/dev/wcEcoli does
    f.write_text(f.read_text(encoding="utf-8") + '"no_oxygen_plus_nitrate"\t"x"\t82.0\t[]\t[]\n', encoding="utf-8")
    return root


def test_a_row_on_the_public_branch_is_attributed_to_its_public_commit(tmp_path):
    root = _repo(tmp_path)
    got = CF._introduced(root, "no_oxygen_plus_nitrate", public_ref="public")
    assert got["commit"] != "uncommitted" and len(got["commit"]) >= 7
    assert got["date"] == "2026-11-25" and got["subject"] == "anaerobic nitrate"
    assert got["on"] == "public"


def test_a_row_committed_nowhere_stays_uncommitted(tmp_path):
    # forced: without the public ref to look in, the same row is only in the working tree
    root = _repo(tmp_path)
    assert CF._introduced(root, "no_oxygen_plus_nitrate", public_ref=None)["commit"] == "uncommitted"
    assert CF._introduced(root, "no_oxygen_plus_nitrate", public_ref="no_such_ref")["commit"] == "uncommitted"


def test_a_row_on_the_checked_out_branch_is_found_there(tmp_path):
    root = _repo(tmp_path)
    got = CF._introduced(root, "basal", public_ref="public")
    assert got["subject"] == "basal" and got["on"] == "HEAD"
