"""Remote corpora are read at a named commit, never at whatever the Hub serves today (ABC T.6).

The Agentic Benchmark Checklist's T.6 asks that an evaluation's environment be frozen at release rather than
read live. Two remote corpora are read: well4cell, a third-party release that Cellarium's claims are measured
against, and the deposit of Cellarium's own runs. Until 2026-11-23 every read of either went to the Hub's
current head: the registry RECORDED the revision it had measured (well4cell 4ab4aa37, 2026-11-21) and no read
used it. Now:

  * well4cell is pinned in code to 1.0.0-rc2's commit, and every listing and download names that commit;
  * a remote corpus with no pin (the deposit, or one the user plugs in) resolves ONE commit per plan, reads only
    at it and reports it, so a read is reproducible after the fact even where it is not frozen;
  * the cache knows which commit it holds, from the hub library's own download records rather than a stamp of
    ours, and a cache fetched at another commit is `stale_cache`, not `ready`;
  * `verify_cache` recomputes every cached file's hash against the etag recorded when it was downloaded;
  * a static check fails any hub read in the package that does not name a revision.

Expectations are literals. The fakes stand in for the network only; the code under test is the real code.
"""

from __future__ import annotations

import ast
import hashlib
import os
import sys
import time
import types
from pathlib import Path

import huggingface_hub
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cellarium import corpora, egress, hf  # noqa: E402

PIN = "4ab4aa379afb51150b565e3afd05dddac7e27bd6"      # well4cell 1.0.0-rc2, measured live 2026-11-21
OTHER = "9f2c5d1e8b7a6c5d4e3f2a1b0c9d8e7f6a5b4c3d"    # some other commit of the same repo
HEAD = "e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8"     # what an unpinned repo's head resolves to


# --- fakes for the network only --------------------------------------------------------------------

class _Entry:
    def __init__(self, path: str, size: int):
        self.path, self.size = path, size


class FakeApi:
    """A hub client that records every call and its revision."""

    def __init__(self, files=None, head=HEAD):
        self.files = files if files is not None else {"index.parquet": 10, "README.md": 3}
        self.head = head
        self.calls: list[tuple] = []

    def list_repo_tree(self, repo, path_in_repo=None, repo_type=None, recursive=False, revision=None, **kw):
        self.calls.append(("list_repo_tree", repo, revision))
        return [_Entry(p, s) for p, s in self.files.items()]

    def repo_info(self, repo, repo_type=None, revision=None, **kw):
        self.calls.append(("repo_info", repo, revision))
        return types.SimpleNamespace(sha=self.head)


def _record_download(local_dir: Path, rel: str, content: bytes, commit: str, etag: str | None = None) -> None:
    """Write a file and the record huggingface_hub writes beside it on a local-dir download: three lines in
    `.cache/huggingface/download/<path>.metadata` (commit, etag, time written). The format was read from the
    installed library and checked against the real well4cell cache on 2026-11-23 (24 of 24 records)."""
    f = local_dir / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(content)
    meta = local_dir / ".cache" / "huggingface" / "download" / (rel + ".metadata")
    meta.parent.mkdir(parents=True, exist_ok=True)
    etag = etag or hashlib.sha256(content).hexdigest()
    meta.write_text(f"{commit}\n{etag}\n{time.time() + 1}\n", encoding="utf-8")


def _fake_download(calls: list):
    def dl(repo, filename, repo_type=None, local_dir=None, revision=None, **kw):
        calls.append(("hf_hub_download", repo, filename, revision))
        _record_download(Path(local_dir), filename, b"x" * 10, revision or "UNNAMED")
        return str(Path(local_dir) / filename)
    return dl


def _corpus(key: str, revision: str = "") -> corpora.Corpus:
    return corpora.Corpus(key=key, title=key.upper(), kind="hf", locator=f"org/{key}", index="index.parquet",
                          metadata_files=("index.parquet", "README.md"), row_unit="one trajectory",
                          revision=revision)


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """A pinned remote corpus `w` and an unpinned one `u`, a fake client, and a log of egress records."""
    monkeypatch.setattr(corpora, "REGISTRY_FILE", tmp_path / "none.json")
    monkeypatch.setattr(corpora, "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(corpora, "DECLARED", (_corpus("w", PIN), _corpus("u")))
    api = FakeApi()
    monkeypatch.setattr(corpora, "_clients", lambda: [api])
    reads: list[tuple] = []
    monkeypatch.setattr(egress, "record", lambda via, url, **kw: reads.append((via, url)))
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", _fake_download(api.calls))
    return api, reads


# --- the pin ---------------------------------------------------------------------------------------

def test_well4cell_is_read_at_the_rc2_commit():
    assert corpora.WELL4CELL.revision == "4ab4aa379afb51150b565e3afd05dddac7e27bd6"


@pytest.mark.parametrize("bad", ["main", "4ab4aa37", "v1.0.0-rc2", PIN.upper(), PIN + "0"])
def test_a_revision_must_be_a_full_lowercase_commit(bad):
    """A branch or tag moves, a short sha is ambiguous, and the hub reports commits in lower case, so any of
    these would either pin nothing or never match the commit the cache records."""
    with pytest.raises(ValueError, match="40"):
        _corpus("x", bad)


def test_a_local_corpus_cannot_carry_a_revision():
    with pytest.raises(ValueError, match="remote"):
        corpora.Corpus(key="x", title="X", kind="local", locator="d", row_unit="r", revision=PIN)


def test_a_pinned_plan_lists_at_the_pin_and_never_asks_for_the_head(remote):
    api, reads = remote
    plan = corpora.metadata_plan("w")
    assert (plan["revision"], plan["pinned"]) == (PIN, True)
    assert api.calls == [("list_repo_tree", "org/w", PIN)]
    assert reads == [("hf_list_repo_tree", f"https://huggingface.co/datasets/org/w/tree/{PIN}")]


def test_every_download_of_a_pinned_corpus_names_the_pin(remote):
    api, reads = remote
    out = corpora.fetch_metadata("w", confirm=True)
    assert (out["fetched"], out["failed"], out["revision"]) == (2, [], PIN)
    assert [c[3] for c in api.calls if c[0] == "hf_hub_download"] == [PIN, PIN]
    assert [u for v, u in reads if v == "hf_hub_download"] == [
        f"https://huggingface.co/datasets/org/w/blob/{PIN}/README.md",
        f"https://huggingface.co/datasets/org/w/blob/{PIN}/index.parquet"]
    st = corpora.status("w")
    assert (st["state"], st["cache_revision"], st["cache_matches_pin"]) == ("ready", PIN, True)


def test_an_unpinned_remote_corpus_reads_one_resolved_commit_and_says_so(remote):
    api, _ = remote
    plan = corpora.metadata_plan("u")
    assert (plan["revision"], plan["pinned"]) == (HEAD, False)
    assert api.calls == [("repo_info", "org/u", None), ("list_repo_tree", "org/u", HEAD)]
    api.calls.clear()
    out = corpora.fetch_metadata("u", confirm=True)
    assert out["revision"] == HEAD
    assert {c[3] for c in api.calls if c[0] == "hf_hub_download"} == {HEAD}
    st = corpora.status("u")
    assert (st["state"], st["cache_revision"], st["cache_matches_pin"]) == ("ready", HEAD, None)


def test_a_head_that_cannot_be_resolved_is_an_error_not_a_read_at_main(remote, monkeypatch):
    class Down(FakeApi):
        def repo_info(self, *a, **kw):
            raise ConnectionError("no route to host")
    down = Down()
    monkeypatch.setattr(corpora, "_clients", lambda: [down])
    plan = corpora.metadata_plan("u")
    assert "no route to host" in plan["error"]
    assert [c for c in down.calls if c[0] == "list_repo_tree"] == [], "nothing may be listed at an unknown commit"


# --- the cache knows what it holds -----------------------------------------------------------------

def test_a_cache_recorded_at_another_commit_is_stale_and_is_pulled_again(remote):
    d = corpora.cache_dir("w")
    for rel in ("index.parquet", "README.md"):
        _record_download(d, rel, b"y" * 10, OTHER)
    st = corpora.status("w")
    assert (st["state"], st["cache_revision"], st["cache_matches_pin"]) == ("stale_cache", OTHER, False)
    assert "4ab4aa379afb" in st["why"]
    plan = corpora.metadata_plan("w")
    assert (plan["n_already_local"], plan["n_to_pull"]) == (0, 2)


def test_a_cache_at_the_pin_is_ready_and_nothing_is_pulled(remote):
    d = corpora.cache_dir("w")
    for rel in ("index.parquet", "README.md"):
        _record_download(d, rel, b"y" * 10, PIN)
    st = corpora.status("w")
    assert (st["state"], st["cache_revision"], st["cache_matches_pin"]) == ("ready", PIN, True)
    plan = corpora.metadata_plan("w")
    assert (plan["n_already_local"], plan["n_to_pull"]) == (2, 0)


def test_a_file_edited_after_it_was_downloaded_has_no_valid_record(remote):
    """The library's own rule: a file modified after its record was written has no valid record."""
    d = corpora.cache_dir("w")
    for rel in ("index.parquet", "README.md"):
        _record_download(d, rel, b"y" * 10, PIN)
    later = time.time() + 3600
    os.utime(d / "index.parquet", (later, later))
    st = corpora.status("w")
    assert (st["state"], st["cache_revision"]) == ("stale_cache", None)
    assert st["cache_revisions"] == {PIN: 1, "unrecorded": 1}


def test_the_cached_file_count_is_data_files_not_the_hub_librarys_bookkeeping(remote):
    """Before 2026-11-23 the count included `.cache/huggingface/**`: the real well4cell cache reported 49 files
    for 24 data files (24 download records and a .gitignore)."""
    d = corpora.cache_dir("w")
    for rel in ("index.parquet", "README.md"):
        _record_download(d, rel, b"y" * 10, PIN)
    (d / ".cache" / "huggingface" / ".gitignore").write_text("*\n", encoding="utf-8")
    assert corpora.status("w")["n_cached_files"] == 2


def test_verify_cache_recomputes_each_files_hash_against_its_recorded_etag(remote):
    """Large files are stored by SHA-256 of their bytes, small ones by git's blob hash; the real well4cell
    cache had 22 of the first kind and 2 of the second, and all 24 matched on 2026-11-23."""
    d = corpora.cache_dir("w")
    _record_download(d, "index.parquet", b"abc", PIN)
    blob = b"hello\n"
    _record_download(d, "README.md", blob, PIN,
                     etag=hashlib.sha1(b"blob %d\0" % len(blob) + blob).hexdigest())
    v = corpora.verify_cache("w")
    assert (v["verified"], v["n_files"], v["n_bytes_verified"], v["mismatches"], v["unrecorded"]) == (
        True, 2, 2, [], [])
    assert v["revisions"] == {PIN: 2}
    before = (d / "README.md").stat().st_mtime
    (d / "README.md").write_bytes(b"HELLO\n")          # same size, different bytes
    os.utime(d / "README.md", (before, before))         # and a time the record still accepts
    v = corpora.verify_cache("w")
    assert (v["verified"], v["mismatches"]) == (False, ["README.md"])


def test_verify_cache_on_a_pinned_corpus_fails_a_cache_at_another_commit(remote):
    d = corpora.cache_dir("w")
    _record_download(d, "index.parquet", b"abc", OTHER)
    v = corpora.verify_cache("w")
    assert v["verified"] is False and v["revisions"] == {OTHER: 1}
    assert "pin" in v["why"]


# --- the deposit (hf.py) ---------------------------------------------------------------------------

@pytest.fixture
def deposit(monkeypatch):
    """The deposit's plan with one seed missing locally; the hub client and the commit resolution faked."""
    rel = "runs/cellarium/d/s0/simOut.tar.gz"
    monkeypatch.setattr(hf, "_design_seeds", lambda d: [{"id": "r0", "seed": 0}])
    monkeypatch.setattr(hf.store, "simout_path", lambda rid: "x")
    monkeypatch.setattr(hf, "_hf_rel", lambda p: rel)
    monkeypatch.setattr(hf, "_full_simout_local", lambda p: False)
    api = FakeApi(files={rel: 5_000})
    monkeypatch.setattr(huggingface_hub, "HfApi", lambda token=None: api)
    reads: list[tuple] = []
    monkeypatch.setattr(egress, "record", lambda via, url, **kw: reads.append((via, url)))
    monkeypatch.setattr(hf, "HF_REVISION_PIN", "")
    return api, reads, rel


def test_the_deposit_plan_resolves_one_commit_and_lists_at_it(deposit):
    api, reads, rel = deposit
    plan = hf.download_plan("d")
    assert (plan["revision"], plan["pinned"], plan["n_to_pull"]) == (HEAD, False, 1)
    assert [c for c in api.calls if c[0] == "list_repo_tree"] == [("list_repo_tree", hf.HF_REPO, HEAD)]
    assert f"/tree/{HEAD}/" in [u for v, u in reads if v == "hf_list_repo_tree"][0]


def test_the_deposit_downloads_at_the_commit_its_plan_listed(deposit, monkeypatch, tmp_path):
    api, reads, rel = deposit
    got = []
    monkeypatch.setattr(huggingface_hub, "hf_hub_download",
                        lambda repo, path, repo_type=None, revision=None, **kw: got.append(revision) or "t.tar.gz")

    class _Tar:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extractall(self, *a, **kw):
            pass
    import tarfile
    monkeypatch.setattr(tarfile, "open", lambda p, mode="r:gz": _Tar())
    out = hf.download_raw("d", confirm=True)
    assert (out["downloaded"], got, out["revision"]) == (["r0"], [HEAD], HEAD)
    assert f"/blob/{HEAD}/{rel}" in [u for v, u in reads if v == "hf_hub_download"][0]


def test_an_environment_pin_is_used_without_asking_the_hub(deposit, monkeypatch):
    api, _, _ = deposit
    monkeypatch.setattr(hf, "HF_REVISION_PIN", OTHER)
    plan = hf.download_plan("d")
    assert (plan["revision"], plan["pinned"]) == (OTHER, True)
    assert [c[0] for c in api.calls] == ["list_repo_tree"]


def test_a_malformed_environment_pin_is_an_error_not_a_branch(deposit, monkeypatch):
    api, _, _ = deposit
    monkeypatch.setattr(hf, "HF_REVISION_PIN", "main")
    plan = hf.download_plan("d")
    assert plan["revision"] is None and "40" in plan["revision_error"]
    assert api.calls == [], "nothing may be read when the pin is not a commit"
    out = hf.download_raw("d", confirm=True)
    assert out["downloaded"] == []


def test_the_copy_paste_command_names_the_commit_it_verified(deposit, monkeypatch):
    api, _, rel = deposit
    monkeypatch.setattr(hf, "HF_HAS_RAW", True)
    monkeypatch.setattr(hf, "HF_REPO_REDACTED", False)
    monkeypatch.setattr(hf.store, "list_results", lambda: [{"id": "r0"}])
    alt = hf.data_availability("r0")["alternatives"]["1_download_from_hf"]
    assert alt["available"] is True and alt["revision"] == HEAD
    assert f"--revision {HEAD}" in alt["command"]


# --- the static guard ------------------------------------------------------------------------------

HUB_READS = ("list_repo_tree", "list_repo_files", "hf_hub_download", "snapshot_download", "get_paths_info",
             "hf_hub_url")


def hub_reads_without_revision(source: str, name: str = "<src>") -> list[str]:
    """Every call of a hub READ in `source` that does not pass `revision=` by name. `**kwargs` does not count:
    a revision that might be inside a dict is not a revision the reader can see."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            fn = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if fn in HUB_READS and not any(k.arg == "revision" for k in node.keywords):
                out.append(f"{name}:{node.lineno} {fn}")
    return out


def test_every_hub_read_in_the_package_names_a_revision():
    files = sorted((REPO / "src" / "cellarium").rglob("*.py"))
    found = [x for p in files for x in hub_reads_without_revision(p.read_text(encoding="utf-8"), p.name)]
    assert found == [], f"hub reads with no revision: {found}"
    n = sum(len([1 for node in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
                 if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None))
                 in HUB_READS]) for p in files)
    assert n == 4, f"the package should make exactly four hub reads (two listings, two downloads), found {n}"


def test_the_static_guard_catches_a_read_with_its_revision_removed():
    """Forced: the real corpora.py with `revision=` stripped from its download is caught."""
    src = (REPO / "src" / "cellarium" / "corpora.py").read_text(encoding="utf-8")
    assert "revision=rev," in src, "the plant's anchor moved; re-aim it"
    planted = src.replace("revision=rev,", "", 1)
    assert len(hub_reads_without_revision(planted)) == 1
    assert hub_reads_without_revision("api.hf_hub_download(r, p, **kw)") == ["<src>:1 hf_hub_download"]
