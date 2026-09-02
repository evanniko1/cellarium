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
    """A server restart mid-run leaves approve_and_run's in-process job stuck at 'running'. On boot, reconcile flips
    it by what actually landed vs what was REQUESTED: ALL seeds indexed -> 'done'; SOME but not all -> 'partial' (the
    false-'done' fix — a crash mid-campaign no longer hides behind a green status); nothing -> 'failed'. Live drafts
    (pending_approval) are untouched, and a re-run is a no-op (idempotent)."""
    import json

    from cellarium import manifest
    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")

    def _job(rid, gene, seeds=4):
        return {"id": rid, "status": "running", "seeds": seeds,
                "design": {"perturbation": "gene_knockout", "condition": "basal", "timeline": "",
                           "params": {"target_genes": [gene]}}}
    q = [_job("req_done", "pfkA"), _job("req_partial", "tpiA"), _job("req_orphan", "ghostZ"),
         {"id": "req_pending", "status": "pending_approval",
          "design": {"perturbation": "wildtype", "condition": "basal", "timeline": "", "params": {}}}]
    (tmp_path / "q.json").write_text(json.dumps(q))
    # stand in for the manifest: pfkA landed all 4 seeds, tpiA only 1 (crashed mid-campaign), ghostZ none
    landed = {"pfkA": 4, "tpiA": 1, "ghostZ": 0}
    monkeypatch.setattr(manifest, "count_runs",
                        lambda d: next((landed[g] for g in (d.params or {}).get("target_genes", []) if g in landed), 0))

    res = launch.reconcile()
    assert res["reconciled"] == 3                                    # only the three 'running' jobs are touched
    by_id = {r["id"]: r for r in launch._load()}
    assert by_id["req_done"]["status"] == "done"                    # 4/4 seeds indexed -> done
    assert by_id["req_partial"]["status"] == "partial" and "1/4" in by_id["req_partial"]["error"]   # 1/4 -> partial
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


def test_a_campaign_where_nothing_passed_qc_says_so(tmp_path, monkeypatch):
    """The approval gate must not hand a human a bare "done" for a request that produced nothing usable.

    manifest.campaign is crash-isolated on purpose -- a failed sim is logged and skipped so a long
    unattended batch still leaves a usable corpus -- so it returns a shard path and raises nothing even
    when every run died, AND a crashed run still writes a row, because a lethal design is a result.
    approve_and_run therefore had no signal at all and reported status="done", error=None. MEASURED on a
    fresh clone with no ParCa output: the sim died in the container on a missing simData.cPickle and the
    caller was told "done", with the failure visible only in a log line.

    The fix is not a boolean. _classify_crash documents crash_type="container" as ambiguous between a
    broken container and an inviable design, so the counts are reported and the reader decides.
    """
    from cellarium import launch, manifest

    # Isolate the queue, as every other test here does: propose() writes to launch.QUEUE, which
    # defaults to the tracked data/launch_queue.json. Without this the suite dirties a committed file.
    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    monkeypatch.setattr(manifest, "campaign", lambda *a, **k: tmp_path / "s.parquet")
    monkeypatch.setattr(manifest, "compact", lambda *a, **k: {"shard": "compacted.parquet"})
    monkeypatch.setattr(manifest, "shard_outcome",
                        lambda s: {"rows": 1, "ok": 0, "qc": {"crashed": 1}, "crash": {"container": 1}})

    p = launch.propose(perturbation="wildtype", condition="basal", seeds=1, generations=1,
                       elongation_model="steady_state")
    assert p.get("status") == "pending_approval", p
    out = launch.approve_and_run(p["request_id"], parallel=1, index=True)

    assert out["recorded"]["ok"] == 0
    assert out.get("note"), "a request that produced nothing usable reported no note"
    assert "0 of 1 recorded run(s) passed QC" in out["note"]
    assert "ambiguous" in out["note"], "the container/inviable ambiguity must not be hidden"
    assert "simData.cPickle" in out["note"], "the usual cause is not named"


def test_a_campaign_that_produced_usable_runs_carries_no_note(tmp_path, monkeypatch):
    """The converse: a run that passed QC must not be decorated with a failure note."""
    from cellarium import launch, manifest

    # Isolate the queue, as every other test here does: propose() writes to launch.QUEUE, which
    # defaults to the tracked data/launch_queue.json. Without this the suite dirties a committed file.
    monkeypatch.setattr(launch, "QUEUE", tmp_path / "q.json")
    monkeypatch.setattr(manifest, "campaign", lambda *a, **k: tmp_path / "s.parquet")
    monkeypatch.setattr(manifest, "compact", lambda *a, **k: {"shard": "compacted.parquet"})
    monkeypatch.setattr(manifest, "shard_outcome",
                        lambda s: {"rows": 1, "ok": 1, "qc": {"ok": 1}, "crash": {}})

    p = launch.propose(perturbation="wildtype", condition="basal", seeds=1, generations=1,
                       elongation_model="steady_state")
    out = launch.approve_and_run(p["request_id"], parallel=1, index=True)
    assert out["status"] == "done" and out["recorded"]["ok"] == 1
    assert "note" not in out


def test_shard_outcome_treats_unreadable_as_nothing_landed(tmp_path):
    """Absent or unreadable reports zeros: the question is "what landed", and a file we cannot read is
    nothing. Raising here would turn a reporting helper into a second failure mode."""
    from cellarium import manifest

    assert manifest.shard_outcome(tmp_path / "nope.parquet") == {"rows": 0, "ok": 0, "qc": {}, "crash": {}}
    junk = tmp_path / "junk.parquet"
    junk.write_bytes(b"not a parquet file")
    assert manifest.shard_outcome(junk)["rows"] == 0
