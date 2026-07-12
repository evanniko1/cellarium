"""The launch airlock — the KO index-resolution guard (never run the wrong gene) and the propose refusal.

A gene KO runs on a variant INDEX; a symbolic target_genes with no index makes the runner hash to a random
variant and silently knock out the WRONG gene. propose() must resolve symbol -> ko_index or refuse to queue.
"""

from cellarium import launch


def test_resolve_ko_injects_index_from_symbol():
    p, err = launch._resolve_ko("gene_knockout", {"target_genes": ["pfkA"]}, None)
    assert err is None and p["variant_index"] == 1594 and p["target_genes"] == ["pfkA"]

    p, err = launch._resolve_ko("gene_knockout", {}, "rpoB")          # gene= kwarg path
    assert err is None and p["variant_index"] == 2095

    p, err = launch._resolve_ko("multi_gene_knockout", {"target_genes": ["pfkA", "pfkB"]}, None)
    assert err is None and p["ko_indices"] == [1594, 2073]


def test_resolve_ko_refuses_unknown_gene_and_passes_through_non_ko():
    _, err = launch._resolve_ko("gene_knockout", {}, "notagene")
    assert err and "notagene" in err
    _, err = launch._resolve_ko("gene_knockout", {}, None)           # no gene at all
    assert err and "needs a target gene" in err
    p, err = launch._resolve_ko("wildtype", {"foo": 1}, None)        # non-KO untouched
    assert err is None and p == {"foo": 1}


def test_resolve_ko_trusts_explicit_index():
    p, err = launch._resolve_ko("gene_knockout", {"variant_index": 7}, "pfkA")
    assert err is None and p["variant_index"] == 7                   # explicit index wins; never overridden


def test_propose_refuses_unresolvable_ko_without_queuing(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    res = launch.propose("gene_knockout", gene="notagene")
    assert res["status"] == "unresolved" and "notagene" in res["error"]
    assert not (tmp_path / "q.json").exists()                        # refused BEFORE any queue write


def test_propose_experiment_multi_gene_ko_resolves_indices(tmp_path, monkeypatch):
    """The agent-facing tool: perturbation='multi_gene_knockout' + genes=[...] must queue a design whose params
    carry the resolved ko_indices (the fix that lets Coli actually queue a synthetic-lethal double KO)."""
    import json

    from cellarium import tools
    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    res = tools.propose_experiment(perturbation="multi_gene_knockout", condition="basal",
                                   genes=["pfkA", "pfkB"], seeds=1, generations=1)
    assert res["status"] == "pending_approval"
    queued = json.loads((tmp_path / "q.json").read_text())[-1]
    assert queued["design"]["params"]["ko_indices"] == [1594, 2073]
    assert queued["design"]["params"]["target_genes"] == ["pfkA", "pfkB"]
