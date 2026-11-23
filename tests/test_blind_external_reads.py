"""Validation-layer item 7: what a run read from outside, recorded; the dataset hosts kept out of blind runs.

Built 2026-11-23 (cellarium.egress). The Council's librarian searches the web with the API's own search tool, so
the block has to travel in the request (`blocked_domains`), and since that filter is the API's to enforce and its
subdomain rule is not documented, every URL the search returned is ALSO audited here. A brief from a search that
touched a blocked host is discarded before any Council role sees it, and the A/B scorer refuses such a run.

Each protection is shown to be load-bearing by removing it once: with the block list emptied, the same leaked
brief DOES reach the proposer (test_the_audit_is_what_keeps_it_out). No live model or network call is made.
"""

from __future__ import annotations

import ast
import json
import os
import socket
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/*.parquet")

from cellarium import council, egress, observability  # noqa: E402
from cellarium.hypothesis import Hypothesis  # noqa: E402

LEAK = "https://huggingface.co/datasets/cSynBioSys/well4cell/blob/main/index.parquet"


def _search_response(*urls, cited=(), error=None, query="selective charging of tRNA isoacceptors"):
    """A web_search response in the documented block shapes, as plain dicts."""
    blocks = [{"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": query}},
              {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
               "content": [{"type": "web_search_result", "url": u, "title": f"t{i}"} for i, u in enumerate(urls)]}]
    if error:
        blocks.append({"type": "web_search_tool_result", "tool_use_id": "srvtoolu_2",
                       "content": {"type": "web_search_tool_result_error", "error_code": error}})
    blocks.append({"type": "text", "text": "a cited brief",
                   "citations": [{"type": "web_search_result_location", "url": u, "title": "c"} for u in cited]})
    return {"content": blocks}


class _Client:
    def __init__(self, resp):
        self.resp, self.kw = resp, None
        self.messages = self

    def create(self, **kw):
        self.kw = kw
        return self.resp


def _fake_emit(seen: dict):
    def fake(client, model, system, tool, payload, *, role="council", **kw):
        seen.setdefault(role, []).append(payload.get("library_brief"))
        if role == "proposer":
            return {"claim": "c"}
        return {"objections": []} if role == "skeptic" else {"falsifiable": True}
    return fake


# ---------------------------------------------------------------------------------------------- the request

def test_the_librarian_request_blocks_the_dataset_hosts_and_this_repository():
    cli = _Client(_search_response("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1"))
    council.web_research("does one isoacceptor de-charge first?", client=cli, labels={})
    tool = cli.kw["tools"][0]
    assert tool["name"] == "web_search"
    assert {"huggingface.co", "hf.co", "github.com/evanniko1/cellarium"} <= set(tool["blocked_domains"])
    assert "allowed_domains" not in tool                          # both in one request is a 400
    assert not any("://" in d for d in tool["blocked_domains"])   # the documented shape has no scheme


def test_every_query_and_every_result_is_kept_cited_or_not():
    resp = _search_response("https://a.org/1", "https://b.org/2", cited=("https://a.org/1",),
                            error="max_uses_exceeded")
    out = council._read_web_brief(resp)
    assert out["queries"] == ["selective charging of tRNA isoacceptors"]
    assert [r["url"] for r in out["fetched"]] == ["https://a.org/1", "https://b.org/2"]   # b was read, not cited
    assert [s["url"] for s in out["sources"]] == ["https://a.org/1"]
    assert out["search_errors"] == ["max_uses_exceeded"]          # a failed search is not a clean one


# ---------------------------------------------------------------------------------------------- the audit

@pytest.mark.parametrize("url, rule", [
    (LEAK, "huggingface.co"),
    ("https://cdn-lfs.huggingface.co/repos/ab/cd", "huggingface.co"),     # subdomains: matched explicitly here
    ("hf.co/datasets/x", "hf.co"),                                         # no scheme still parses
    ("https://github.com/evanniko1/cellarium/blob/main/README.md", "github.com/evanniko1/cellarium"),
    ("https://github.com/evanniko1/cellarium", "github.com/evanniko1/cellarium"),
    ("https://nothuggingface.co/x", None),                                 # a suffix is not a subdomain
    ("https://github.com/evanniko1/cellarium-fork/x", None),               # a path prefix ends at a boundary
    ("https://github.com/CovertLab/wcEcoli", None),
    ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1", None),
])
def test_the_block_list_matches_hosts_subdomains_and_path_prefixes_exactly(url, rule):
    assert egress.blocked_rule(url) == rule


def test_a_search_that_touched_a_dataset_page_never_reaches_a_role(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(council, "_emit", _fake_emit(seen))
    monkeypatch.setattr(council, "web_research",
                        lambda q, **kw: {"brief": "LEAKED RESULT", "fetched": [{"url": LEAK}], "sources": []})
    h = council.deliberate("q", max_rounds=1, use_librarian=True, client=object(), verbose=False)
    assert seen and not any(b for briefs in seen.values() for b in briefs)
    lib = h.external_reads["librarian"]
    assert lib["used"] is False and lib["brief_discarded_for_breach"] is True
    assert lib["audit"]["clean"] is False and lib["audit"]["breaches"][0]["rule"] == "huggingface.co"


def test_the_audit_is_what_keeps_it_out(monkeypatch):
    """The forced failure: empty the block list and the same leaked brief reaches the proposer. Without this,
    the test above could pass because the brief was dropped for some unrelated reason."""
    seen: dict = {}
    monkeypatch.setattr(council, "_emit", _fake_emit(seen))
    monkeypatch.setattr(council, "web_research",
                        lambda q, **kw: {"brief": "LEAKED RESULT", "fetched": [{"url": LEAK}], "sources": []})
    monkeypatch.setattr(egress, "BLIND_BLOCKED_DOMAINS", ())
    h = council.deliberate("q", max_rounds=1, use_librarian=True, client=object(), verbose=False)
    assert "LEAKED RESULT" in seen["proposer"]
    assert h.external_reads["librarian"]["used"] is True


def test_a_failed_librarian_is_recorded_rather_than_read_as_an_empty_search(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(council, "_emit", _fake_emit(seen))

    def boom(*a, **k):
        raise RuntimeError("web search down")
    monkeypatch.setattr(council, "web_research", boom)
    h = council.deliberate("q", max_rounds=1, use_librarian=True, client=object(), verbose=False)
    assert h.external_reads["librarian"] == {"used": False, "error": "RuntimeError: web search down"}


def test_a_run_without_the_librarian_records_no_external_read(monkeypatch):
    monkeypatch.setattr(council, "_emit", _fake_emit({}))
    h = council.deliberate("q", max_rounds=1, client=object(), verbose=False)
    assert h.external_reads == {}


def test_a_blind_council_run_opens_no_connection_of_its_own(monkeypatch):
    """With the model client faked, the Council itself must not touch the network: every external read it can
    make goes through the librarian, which is off here. A socket that refuses to connect proves it."""
    def refuse(*a, **k):
        raise AssertionError("the Council opened a network connection outside the model client")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(council, "_emit", _fake_emit({}))
    council.deliberate("q", max_rounds=2, client=object(), verbose=False)


# ---------------------------------------------------------------------------------------------- scoring

def _hyp(reads: dict) -> Hypothesis:
    h = Hypothesis(question="q", claim="ppGpp rises.", h1="h1", h0="h0")
    h.external_reads = reads
    return h


def test_the_ab_scorer_refuses_a_run_whose_audit_failed():
    import shared_metric as SM
    bad = _hyp({"librarian": {"audit": egress.audit([LEAK])}})
    with pytest.raises(SM.BlindnessBreach, match="never scored"):
        SM.from_council(bad)
    good = _hyp({"librarian": {"audit": egress.audit(["https://www.ncbi.nlm.nih.gov/x"])}})
    assert "ppGpp rises." in SM.from_council(good)


def test_what_was_read_never_reaches_a_grader():
    """Every harness grades model_dump(); a grader that saw the reads would know the arm."""
    h = _hyp({"librarian": {"audit": egress.audit([LEAK])}})
    assert "external_reads" not in h.model_dump(by_alias=True, mode="json")
    assert "external_reads" not in json.loads(h.model_dump_json())


def _enables_librarian_without_guard(src: str) -> bool:
    tree = ast.parse(src)
    enables = any(isinstance(n, ast.keyword) and n.arg == "use_librarian"
                  and not (isinstance(n.value, ast.Constant) and n.value.value is False)
                  for n in ast.walk(tree))
    return enables and "from_council" not in src


def test_no_eval_harness_turns_the_librarian_on_without_the_guarded_scorer():
    assert _enables_librarian_without_guard("council.deliberate(q, use_librarian=True)")          # control
    assert not _enables_librarian_without_guard("council.deliberate(q, use_librarian=False)")
    offenders = [p.name for p in sorted((REPO / "evals").glob("*.py"))
                 if _enables_librarian_without_guard(p.read_text(encoding="utf-8"))]
    assert offenders == []


# ---------------------------------------------------------------------------------------------- the stream

def test_an_external_read_is_on_the_stream_but_is_not_counted_as_a_model_call():
    with observability.meter() as m:
        egress.record("hf_hub_download", "https://huggingface.co/datasets/x/blob/main/a.json", purpose="test")
        observability.emit({"role": "librarian", "model": "m", "input_tokens": 3, "output_tokens": 4,
                            "cost_usd": 0.001, "latency_ms": 5})
    assert m.n_calls == 1 and len(m.reads) == 1
    assert m.reads[0]["host"] == "huggingface.co" and m.reads[0]["purpose"] == "test"
    assert m.summary()["cost_partial"] is False


def test_a_corpus_listing_is_recorded_as_an_external_read(monkeypatch):
    pytest.importorskip("huggingface_hub")
    from cellarium import corpora

    class _Api:
        def list_repo_tree(self, repo, **kw):
            return []
    monkeypatch.setattr(corpora, "_clients", lambda: [_Api()])
    got = []
    unsubscribe = observability.subscribe(got.append)
    try:
        corpora._repo_files("cSynBioSys/well4cell")
    finally:
        unsubscribe()
    reads = [r for r in got if r.get("kind") == "external_read"]
    assert [r["url"] for r in reads] == ["https://huggingface.co/datasets/cSynBioSys/well4cell"]
