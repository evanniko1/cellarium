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


def test_propose_experiments_queues_a_whole_panel_in_one_call(tmp_path, monkeypatch):
    """The batch tool: a Council panel (reference + KO + a multi-KO control) queues atomically in ONE call, so the
    agent never runs out of turns mid-panel and drops the discriminating controls. Unresolvable genes are refused,
    not queued; multi-KO indices are resolved."""
    import json

    from cellarium import tools
    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    res = tools.propose_experiments(designs=[
        {"perturbation": "wildtype", "condition": "basal", "seeds": 6, "generations": 3},
        {"perturbation": "gene_knockout", "condition": "basal", "genes": ["pfkA"], "seeds": 6, "generations": 3},
        {"perturbation": "multi_gene_knockout", "condition": "basal", "genes": ["pfkA", "pfkB"], "seeds": 6, "generations": 3},
        {"perturbation": "gene_knockout", "condition": "basal", "gene": "notagene"},   # unresolvable -> refused
    ])
    assert res["queued"] == 3 and res["refused"] == 1 and res["total"] == 4
    q = json.loads((tmp_path / "q.json").read_text())
    assert len(q) == 3                                                   # only the 3 resolvable designs landed
    multi = next(r for r in q if r["design"]["perturbation"] == "multi_gene_knockout")
    assert multi["design"]["params"]["ko_indices"] == [1594, 2073]      # gene set resolved to indices in the batch


def test_reconcile_heals_orphaned_running_jobs(tmp_path, monkeypatch):
    """A server restart mid-run leaves approve_and_run's in-process job stuck at 'running'. On boot, reconcile
    flips it by what actually landed: a run indexed in the manifest -> 'done'; nothing indexed -> 'failed'. Live
    drafts (pending_approval) are untouched, and a re-run is a no-op (idempotent)."""
    import json

    from cellarium import manifest
    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    q = [
        {"id": "req_landed", "status": "running",
         "design": {"perturbation": "gene_knockout", "condition": "basal", "timeline": "",
                    "params": {"target_genes": ["pfkA"]}}},
        {"id": "req_orphan", "status": "running",
         "design": {"perturbation": "gene_knockout", "condition": "basal", "timeline": "",
                    "params": {"target_genes": ["ghostZ"]}}},
        {"id": "req_pending", "status": "pending_approval",
         "design": {"perturbation": "wildtype", "condition": "basal", "timeline": "", "params": {}}},
    ]
    (tmp_path / "q.json").write_text(json.dumps(q))
    # stand in for the manifest: pfkA's run landed, ghostZ's did not
    monkeypatch.setattr(manifest, "has_run", lambda d: "pfkA" in (d.params or {}).get("target_genes", []))

    res = launch.reconcile()
    assert res["reconciled"] == 2                                    # only the two 'running' jobs are touched
    by_id = {r["id"]: r for r in launch._load()}
    assert by_id["req_landed"]["status"] == "done"                  # indexed -> done
    assert by_id["req_orphan"]["status"] == "failed" and by_id["req_orphan"]["error"]   # nothing indexed -> failed
    assert by_id["req_pending"]["status"] == "pending_approval"     # live draft left alone
    assert launch.reconcile()["reconciled"] == 0                    # idempotent


def test_revise_supersedes_old_draft_and_requeues(tmp_path, monkeypatch):
    """Changing an argument on a pending draft must WITHDRAW the old one (no duplicate) and queue a re-vetted new
    draft — the flow when a user asks to modify a queued experiment."""
    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    r1 = launch.propose("gene_knockout", condition="basal", gene="pfkA", seeds=6, generations=1)
    old_id = r1["request_id"]
    r2 = launch.revise(old_id, seeds=10)
    assert r2.get("revised_from") == old_id and r2["status"] == "pending_approval"
    reqs = {r["id"]: r for r in launch._load()}
    assert reqs[old_id]["status"] == "superseded"                       # old draft withdrawn
    assert reqs[old_id]["superseded_by"] == r2["request_id"]            # linked for traceability
    new = reqs[r2["request_id"]]
    assert new["seeds"] == 10 and new["design"]["params"]["variant_index"] == 1594   # kept pfkA, new seed count
    pending = launch.list_requests(status="pending_approval")           # only the revised draft is live
    assert len(pending) == 1 and pending[0]["id"] == r2["request_id"]


def test_lifecycle_reflects_queue_by_semantic_match(tmp_path, monkeypatch):
    """SP-1: each Council falsifier design's lifecycle is derived from the launch queue by SEMANTIC identity
    (perturbation / condition / gene set / key params), IGNORING the resolved variant_index — so a job the design
    spawned is matched regardless of who queued it, and the most-advanced matching job wins."""
    import json

    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    q = [
        # a KO that RAN — carries the RESOLVED variant_index the Council design never had
        {"id": "req_done", "status": "done", "shard": "shard_7",
         "design": {"perturbation": "gene_knockout", "condition": "basal", "timeline": None,
                    "params": {"target_genes": ["pfkA"], "variant_index": 1594}}},
        # an earlier superseded draft of the SAME design — must NOT win over 'done'
        {"id": "req_old", "status": "superseded",
         "design": {"perturbation": "gene_knockout", "condition": "basal", "timeline": None,
                    "params": {"target_genes": ["pfkA"]}}},
        # a ppGpp clamp still awaiting approval, matched by its multiplier
        {"id": "req_pending", "status": "pending_approval",
         "design": {"perturbation": "ppgpp_conc", "condition": "basal", "timeline": None, "params": {"multiplier": 2.0}}},
    ]
    (tmp_path / "q.json").write_text(json.dumps(q))
    designs = [
        {"perturbation": "gene_knockout", "condition": "basal", "timeline": None, "params": {"target_genes": ["pfkA"]}},
        {"perturbation": "ppgpp_conc", "condition": "basal", "timeline": None, "params": {"multiplier": 2.0}},
        {"perturbation": "gene_knockout", "condition": "basal", "timeline": None, "params": {"target_genes": ["acrB"]}},
    ]
    life = launch.lifecycle_for_designs(designs)
    assert life[0] == {"status": "done", "request_id": "req_done", "shard": "shard_7"}   # advanced wins, not 'superseded'
    assert life[1]["status"] == "pending_approval" and life[1]["request_id"] == "req_pending"
    assert life[2] == {"status": "proposed", "request_id": None, "shard": None}          # no matching job


# --- AG-1: absolute config-rooted path + lock-serialized, atomic read-modify-write ---------------------------

def test_queue_path_is_absolute():
    """The queue must not be a CWD-relative path (a job launched from a different directory wrote a stray queue)."""
    assert launch.QUEUE.is_absolute()


def test_txn_serializes_concurrent_writes_no_lost_update(tmp_path, monkeypatch):
    """The old lock-free load->mutate->save lost updates under concurrency. `_txn` holds `_LOCK` across each RMW, so
    N threads each appending land ALL N entries (a lost-update race would drop some)."""
    import threading

    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    launch._save([])
    ready = threading.Barrier(40)

    def worker(i):
        ready.wait()                                   # release all threads at once to maximize contention
        with launch._txn() as q:
            q.append({"id": f"r{i}"})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ids = {r["id"] for r in launch._load()}
    assert len(ids) == 40                              # every append survived — no lost update


def test_save_is_atomic_leaves_no_partial_file(tmp_path, monkeypatch):
    """`_save` writes a temp file then os.replace, so the queue is never half-written; the temp is gone afterward."""
    import json

    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    launch._save([{"id": "a"}, {"id": "b"}])
    assert json.loads((tmp_path / "q.json").read_text()) == [{"id": "a"}, {"id": "b"}]
    assert not (tmp_path / "q.json.tmp").exists()      # no leftover temp
