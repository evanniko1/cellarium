"""scripts/bv_batch.py: the scheduler behind the biological-test batches. Every rule that protects compute or data
is forced: existing runs are never re-run; a group's later stage waits for, and obeys, its validity controls; an
integrity failure stops the design's other seeds unless one of them already finished cleanly, and a lethal phenotype
never does; nothing launches below the
disk floor; and a run the manifest failed to index is never handed to the deposit (which deletes)."""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
_spec = importlib.util.spec_from_file_location("bv_batch", REPO / "scripts" / "bv_batch.py")
B = importlib.util.module_from_spec(_spec)
sys.modules["bv_batch"] = B          # dataclasses resolve their annotations through sys.modules
_spec.loader.exec_module(B)


def _gen(i, divided=True, t=4800.0):
    return SimpleNamespace(index=i, divided=divided, division_time_sec=t, n_steps=2000)


def _rec(mu=1.6e-4):
    return SimpleNamespace(generations=[_gen(0)], channels={"growth_rate": mu}, note="",
                           series={"growth_rate": [[100.0, mu], [4000.0, mu]]})


class Fake:
    def __init__(self, qc=None, mu=None, index_fails=(), free=None, existing=(), crash=()):
        self.qc, self.mu = qc or {}, mu or {}
        self.index_fails, self.existing, self.crash = set(index_fails), set(existing), set(crash)
        self.free = list(free) if free else None
        self.launched, self.indexed, self.deposited = [], [], []
        self.lock = threading.Lock()

    def run_fn(self, spec):
        with self.lock:
            self.launched.append(spec.id)
        if spec.id in self.crash:
            raise RuntimeError("the model script's output contains a traceback")
        return Path(f"/runs/{spec.id}")

    def read_fn(self, spec, root):
        return SimpleNamespace(**{**_rec(self.mu.get(spec.id, 1.6e-4)).__dict__, "_id": spec.id})

    def qc_fn(self, rec):
        status = self.qc.get(rec._id, "ok")
        return SimpleNamespace(value=status), [SimpleNamespace(value=status)]

    def index_fn(self, spec, root, rec):
        if spec.id in self.index_fails:
            raise RuntimeError("shard write failed")
        self.indexed.append(spec.id)

    def deposit_fn(self, root):
        self.deposited.append(Path(root).name)
        return {"verified": True, "reclaimed": True, "why": ""}

    def existing_fn(self, spec):
        return "already there" if spec.id in self.existing else ""

    def free_gb_fn(self):
        if self.free is None:
            return 500.0
        return self.free.pop(0) if len(self.free) > 1 else self.free[0]


def _run(tmp_path, runs, fake, gates=None, parallel=2):
    plan = {"batch": "t", "parallel": parallel, "min_free_gb": 40, "gates": gates or {}}
    specs = [B.RunSpec(**r) for r in runs]
    b = B.Batch(plan, specs, run_fn=fake.run_fn, read_fn=fake.read_fn, qc_fn=fake.qc_fn, index_fn=fake.index_fn,
                deposit_fn=fake.deposit_fn, existing_fn=fake.existing_fn, free_gb_fn=fake.free_gb_fn,
                ledger=tmp_path / "ledger.jsonl", sleep=lambda s: None, poll_s=0.01)
    out = {s.id: s for s in b.run()}
    events = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    return out, events


def _r(id, group="acetate", role="run", stage=1, seed=0, cond=None):
    return {"id": id, "design": {"perturbation": "gene_knockout", "condition": cond or f"KO:{id.split('-')[0]}"},
            "seed": seed, "generations": 1, "group": group, "role": role, "stage": stage}


GATE = {"acetate": {"growth_rate": [1.0e-4, 2.3e-4]}}


def test_an_existing_run_is_never_launched(tmp_path):
    fake = Fake(existing={"fbp-s0"})
    out, _ = _run(tmp_path, [_r("fbp-s0"), _r("ppc-s0")], fake)
    assert fake.launched == ["ppc-s0"] and out["fbp-s0"].status == "exists"


def test_a_passing_control_opens_its_group(tmp_path):
    fake = Fake()
    out, ev = _run(tmp_path, [_r("wt-s0", role="control"), _r("fbp-s0", stage=2)], fake, gates=GATE)
    assert out["fbp-s0"].status == "done"
    assert fake.launched.index("wt-s0") < fake.launched.index("fbp-s0")
    assert any(e["event"] == "gate" and e["open"] for e in ev)


def test_a_control_growing_outside_the_reference_closes_its_group(tmp_path):
    fake = Fake(mu={"wt-s0": 4.0e-4})                       # a glucose-like rate in "acetate": the wrong physiology
    out, ev = _run(tmp_path, [_r("wt-s0", role="control"), _r("fbp-s0", stage=2)], fake, gates=GATE)
    assert out["fbp-s0"].status == "skipped" and "fbp-s0" not in fake.launched
    assert any(e["event"] == "gate" and not e["open"] for e in ev)


def test_a_control_failing_qc_closes_its_group(tmp_path):
    fake = Fake(qc={"wt-s0": "degenerate"})
    out, _ = _run(tmp_path, [_r("wt-s0", role="control"), _r("fbp-s0", stage=2)], fake, gates=GATE)
    assert out["fbp-s0"].status == "skipped"


def test_other_groups_are_not_held_by_a_closed_gate(tmp_path):
    fake = Fake(mu={"wt-s0": 4.0e-4})
    out, _ = _run(tmp_path, [_r("wt-s0", role="control"), _r("fbp-s0", stage=2), _r("ppc-s0", group="glucose")],
                  fake, gates=GATE)
    assert out["ppc-s0"].status == "done"


def test_an_integrity_failure_stops_the_designs_other_seeds(tmp_path):
    fake = Fake(qc={"fbp-s0": "degenerate"})
    out, _ = _run(tmp_path, [_r("fbp-s0", seed=0, cond="KO:fbp"), _r("fbp-s1", seed=1, cond="KO:fbp")], fake,
                  parallel=1)
    assert out["fbp-s1"].status == "skipped" and "fbp-s1" not in fake.launched


def test_a_crash_of_the_designs_first_seed_stops_its_other_seeds(tmp_path):
    fake = Fake(crash={"fbp-s0"})
    out, _ = _run(tmp_path, [_r("fbp-s0", seed=0, cond="KO:fbp"), _r("fbp-s1", seed=1, cond="KO:fbp")], fake,
                  parallel=1)
    assert out["fbp-s0"].status == "failed"
    assert out["fbp-s1"].status == "skipped" and "fbp-s1" not in fake.launched


def test_a_seed_crashing_after_the_design_has_run_does_not_stop_its_other_seeds(tmp_path):
    """BV-14d, 2026-11-27: seed 330 of the FNR-off anaerobic design finished, seed 331 crashed in its second
    generation, and the batch skipped seed 332, leaving the arm one seed short of its pre-registered test. A design
    that has run once is not broken; a later seed's failure is that seed's, and the docstring's rule is the first
    run's."""
    runs = [_r(f"nar-s{i}", seed=i, cond="KO:nar") for i in range(3)]
    fake = Fake(crash={"nar-s1"})
    out, _ = _run(tmp_path, runs, fake, parallel=1)
    assert out["nar-s0"].status == "done" and out["nar-s1"].status == "failed"
    assert "nar-s2" in fake.launched and out["nar-s2"].status == "done"


def test_an_integrity_failure_after_the_design_has_run_does_not_stop_its_other_seeds(tmp_path):
    runs = [_r(f"nar-s{i}", seed=i, cond="KO:nar") for i in range(3)]
    fake = Fake(qc={"nar-s1": "truncated"})
    out, events = _run(tmp_path, runs, fake, parallel=1)
    assert any(e["event"] == "integrity_failure" and e.get("id") == "nar-s1" for e in events)
    assert "nar-s2" in fake.launched and out["nar-s2"].status == "done"


def test_a_lethal_phenotype_is_data_not_an_integrity_failure(tmp_path):
    fake = Fake(qc={"lysA-s0": "no_division"})
    out, _ = _run(tmp_path, [_r("lysA-s0", seed=0, cond="KO:lysA"), _r("lysA-s1", seed=1, cond="KO:lysA")], fake,
                  parallel=1)
    assert out["lysA-s1"].status == "done"


def test_nothing_launches_below_the_disk_floor(tmp_path):
    fake = Fake(free=[10.0, 10.0, 10.0, 200.0])
    out, ev = _run(tmp_path, [_r("fbp-s0")], fake)
    assert out["fbp-s0"].status == "done"
    waits = [i for i, e in enumerate(ev) if e["event"] == "waiting_for_disk"]
    launch = next(i for i, e in enumerate(ev) if e["event"] == "launched")
    assert waits and max(waits) < launch


def test_a_run_the_manifest_failed_to_index_is_never_deposited(tmp_path):
    fake = Fake(index_fails={"fbp-s0"})
    out, ev = _run(tmp_path, [_r("fbp-s0"), _r("ppc-s0")], fake)
    assert fake.deposited == ["ppc-s0"] and "fbp-s0" not in fake.deposited
    assert any(e["event"] == "index_failed" and e["id"] == "fbp-s0" for e in ev)


def test_every_designs_first_seed_launches_before_any_second_seed(tmp_path):
    fake = Fake()
    _run(tmp_path, [_r("fbp-s0", seed=0, cond="KO:fbp"), _r("fbp-s1", seed=1, cond="KO:fbp"),
                    _r("ppc-s0", seed=0, cond="KO:ppc"), _r("ppc-s1", seed=1, cond="KO:ppc")], fake, parallel=1)
    assert fake.launched == ["fbp-s0", "ppc-s0", "fbp-s1", "ppc-s1"]


def test_the_summary_keeps_per_generation_qc_and_the_growth_series(tmp_path):
    fake = Fake()
    out, _ = _run(tmp_path, [_r("fbp-s0")], fake)
    s = out["fbp-s0"].summary
    assert s["qc"] == "ok" and s["generations"][0]["qc"] == "ok" and s["growth_rate_series"]


# ---- several plans in one queue (2026-11-25: BV-14 and the depth-matched glucose controls beside BV-12) ----------

def _plan_file(tmp_path, name, runs, **kw):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"batch": name, "sim_path": kw.pop("sim_path", "cellarium"), "parallel": 2,
                             "min_free_gb": 40, "runs": runs, **kw}), encoding="utf-8")
    return p


def test_plans_merge_with_each_run_keeping_its_plans_sim_path_batch_and_priority(tmp_path):
    a = _plan_file(tmp_path, "bv12", [_r("fbp-s0")], gates=GATE)
    b = _plan_file(tmp_path, "bv14", [_r("no3-s0", group="anaerobic", cond="no_oxygen_plus_nitrate")],
                   sim_path="bv14_no3_anaerobic", priority=-1)
    plan, runs = B.load_plans([a, b])
    by = {r.id: r for r in runs}
    assert (by["fbp-s0"].sim_path, by["fbp-s0"].batch, by["fbp-s0"].priority) == ("cellarium", "bv12", 0)
    assert (by["no3-s0"].sim_path, by["no3-s0"].batch, by["no3-s0"].priority) == ("bv14_no3_anaerobic", "bv14", -1)
    assert plan["gates"] == GATE and plan["parallel"] == 2


def test_a_run_id_in_two_plans_is_refused(tmp_path):
    import pytest
    a = _plan_file(tmp_path, "bv12", [_r("fbp-s0")])
    b = _plan_file(tmp_path, "bv14", [_r("fbp-s0")])
    with pytest.raises(ValueError, match="fbp-s0"):
        B.load_plans([a, b])


def test_a_higher_priority_plan_launches_first_and_logs_to_its_own_ledger(tmp_path):
    a = _plan_file(tmp_path, "bv12", [_r("fbp-s0"), _r("ppc-s0")])
    b = _plan_file(tmp_path, "bv14", [_r("no3-s0", group="anaerobic", cond="no_oxygen_plus_nitrate")], priority=-1)
    plan, runs = B.load_plans([a, b])
    fake = Fake()
    ledgers = {"bv12": tmp_path / "bv12_ledger.jsonl", "bv14": tmp_path / "bv14_ledger.jsonl"}
    bt = B.Batch({**plan, "parallel": 1}, runs, run_fn=fake.run_fn, read_fn=fake.read_fn, qc_fn=fake.qc_fn,
                 index_fn=fake.index_fn, deposit_fn=fake.deposit_fn, existing_fn=fake.existing_fn,
                 free_gb_fn=fake.free_gb_fn, ledger=ledgers["bv12"], ledgers=ledgers, sleep=lambda s: None,
                 poll_s=0.01)
    bt.run()
    assert fake.launched[0] == "no3-s0"
    ev = {k: [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] for k, p in ledgers.items()}
    assert {e.get("id") for e in ev["bv14"] if e.get("id")} == {"no3-s0"}
    assert {e.get("id") for e in ev["bv12"] if e.get("id")} == {"fbp-s0", "ppc-s0"}
    assert all(any(e["event"] == "batch_done" for e in v) for v in ev.values())


# ---- restarting beside runs another process left in flight (2026-11-25) ------------------------------------------

def _batch(tmp_path, runs, fake, parallel=2, **kw):
    plan = {"batch": "t", "parallel": parallel, "min_free_gb": 40, "gates": {}}
    return B.Batch(plan, [B.RunSpec(**r) for r in runs], run_fn=fake.run_fn, read_fn=fake.read_fn,
                   qc_fn=fake.qc_fn, index_fn=fake.index_fn, deposit_fn=fake.deposit_fn,
                   existing_fn=fake.existing_fn, free_gb_fn=fake.free_gb_fn, ledger=tmp_path / "ledger.jsonl",
                   sleep=lambda s: None, poll_s=0.01, root_fn=lambda spec: Path(f"/runs/{spec.id}"), **kw)


def _events(tmp_path):
    return [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_run_complete_on_disk_but_not_indexed_is_adopted_not_skipped(tmp_path):
    # a crash or a restart leaves finished runs the manifest never saw; skipping them leaves them invisible
    fake = Fake()
    fake.existing_fn = lambda spec: {"where": "disk_unindexed", "why": "complete on disk"} if spec.id == "fbp-s0" else ""
    out = {s.id: s for s in _batch(tmp_path, [_r("fbp-s0"), _r("ppc-s0")], fake).run()}
    assert fake.launched == ["ppc-s0"]                       # never re-run
    assert "fbp-s0" in fake.indexed and "fbp-s0" in fake.deposited and out["fbp-s0"].status == "adopted"
    assert any(e["event"] == "adopted" and e["id"] == "fbp-s0" for e in _events(tmp_path))


def test_existence_is_rechecked_when_a_run_comes_up_not_only_at_the_start(tmp_path):
    # another process finished the run while this batch waited on its earlier runs
    fake = Fake()
    calls = {"n": 0}

    def existing(spec):
        if spec.id != "late-s0":
            return ""
        calls["n"] += 1
        return "" if calls["n"] == 1 else "in the manifest at x"
    fake.existing_fn = existing
    out = {s.id: s for s in _batch(tmp_path, [_r("a-s0"), _r("late-s0")], fake, parallel=1).run()}
    assert "late-s0" not in fake.launched and out["late-s0"].status == "exists"


def test_a_run_being_written_by_another_process_waits_and_is_then_adopted(tmp_path):
    fake = Fake()
    state = {"n": 0}

    def existing(spec):
        if spec.id != "orphan-s0":
            return ""
        state["n"] += 1
        return {"where": "writing", "why": "output modified 30 s ago"} if state["n"] < 4 else \
            {"where": "disk_unindexed", "why": "complete on disk"}
    fake.existing_fn = existing
    out = {s.id: s for s in _batch(tmp_path, [_r("orphan-s0")], fake).run()}
    assert fake.launched == [] and out["orphan-s0"].status == "adopted"


def test_simulations_this_process_did_not_start_count_against_the_parallel_limit(tmp_path):
    fake = Fake()
    seen = []
    orig = fake.run_fn

    def run_fn(spec):
        seen.append(len(b._own_running))       # how many of ours were running beside it
        return orig(spec)
    fake.run_fn = run_fn
    external = {"n": 1}
    b = _batch(tmp_path, [_r("a-s0"), _r("b-s0"), _r("c-s0")], fake, parallel=2, busy_fn=lambda: external["n"])
    b.run()
    assert max(seen) <= 1                       # 2 slots, 1 taken by someone else's simulation


def test_recent_output_reads_as_written_and_old_output_does_not(tmp_path):
    import os
    import time as _t
    d = tmp_path / "run" / "generation_000002" / "simOut"
    d.mkdir(parents=True)
    f = d / "Main"
    f.write_text("x", encoding="utf-8")
    assert B._recently_written(tmp_path / "run", 600)
    old = _t.time() - 3600
    os.utime(f, (old, old))
    assert not B._recently_written(tmp_path / "run", 600)          # forced: the same tree, an hour old
    assert not B._recently_written(tmp_path / "absent", 600)


def test_a_run_whose_transit_dir_holds_another_designs_run_waits_until_it_is_reclaimed(tmp_path):
    # BV-12: the acetate knockout of a gene writes into the glucose knockout's home; the runner now refuses that,
    # so the batch must not launch it (a refusal would block the design) but wait for the deposit to reclaim it
    fake = Fake()
    state = {"n": 0}

    def existing(spec):
        if spec.id != "ppsA-acetate-s0":
            return ""
        state["n"] += 1
        return {"where": "occupied", "why": "transit dir holds KO:ppsA glucose"} if state["n"] < 4 else ""
    fake.existing_fn = existing
    out = {s.id: s for s in _batch(tmp_path, [_r("ppsA-acetate-s0")], fake).run()}
    assert fake.launched == ["ppsA-acetate-s0"] and out["ppsA-acetate-s0"].status == "done"


def test_a_wait_that_never_ends_is_given_up_with_its_reason(tmp_path):
    fake = Fake()
    fake.existing_fn = lambda spec: {"where": "occupied", "why": "transit dir holds KO:ppsA glucose"}
    t = {"now": 0.0}

    def clock():
        t["now"] += 1800.0
        return t["now"]
    b = _batch(tmp_path, [_r("ppsA-acetate-s0")], fake, clock=clock)
    b.plan["max_wait_s"] = 7200
    out = {s.id: s for s in b.run()}
    assert fake.launched == [] and out["ppsA-acetate-s0"].status == "skipped"
    assert "transit dir holds" in out["ppsA-acetate-s0"].why and "waited" in out["ppsA-acetate-s0"].why


def test_an_indexed_run_still_on_disk_is_handed_to_the_deposit(tmp_path):
    # a restart drops the previous process's deposit queue: its finished, indexed runs would stay on disk forever,
    # and each one is the transit dir another design is waiting for
    fake = Fake(existing={"fbp-s0", "gone-s0"})
    b = _batch(tmp_path, [_r("fbp-s0"), _r("gone-s0")], fake, on_disk_fn=lambda root: Path(root).name == "fbp-s0")
    out = {s.id: s for s in b.run()}
    assert fake.launched == [] and fake.deposited == ["fbp-s0"]
    assert out["fbp-s0"].status == "exists"
    assert any(e["event"] == "deposit_queued" and e["id"] == "fbp-s0" for e in _events(tmp_path))


def test_a_run_another_depositor_has_queued_is_left_to_it(tmp_path):
    fake = Fake(existing={"pgi-s0", "fbp-s0"})
    b = _batch(tmp_path, [_r("pgi-s0"), _r("fbp-s0")], fake, on_disk_fn=lambda root: True,
               deposit_elsewhere={"pgi-s0"})
    b.run()
    assert fake.deposited == ["fbp-s0"]
    assert any(e["event"] == "deposit_left_elsewhere" and e["id"] == "pgi-s0" for e in _events(tmp_path))


def test_an_adopted_control_opens_its_group_like_a_finished_one(tmp_path):
    # a restart leaves a control running; the new process adopts it when it finishes. The gate read only "done",
    # so an adopted control would have closed its group and skipped every later run
    fake = Fake()
    state = {"n": 0}

    def existing(spec):
        if spec.id != "wt-s0":
            return ""
        state["n"] += 1
        return {"where": "writing", "why": "in flight"} if state["n"] < 3 else \
            {"where": "disk_unindexed", "why": "complete on disk"}
    fake.existing_fn = existing
    b = _batch(tmp_path, [_r("wt-s0", role="control"), _r("fbp-s0", stage=2)], fake)
    b.gates = GATE
    out = {s.id: s for s in b.run()}
    assert out["wt-s0"].status == "adopted" and out["fbp-s0"].status == "done"


def test_a_plan_that_keeps_its_raw_output_is_indexed_but_not_deposited(tmp_path):
    # BV-14 is scored from raw protein counts after its runs finish; depositing reclaims (deletes) the raw output
    fake = Fake(existing={"old-s0"})
    specs = [_r("no3-s0", group="anaerobic", cond="no_oxygen_plus_nitrate"), _r("old-s0", group="anaerobic")]
    b = _batch(tmp_path, specs, fake, on_disk_fn=lambda root: True, keep_raw_batches={"t"})
    for sp in b.runs:
        sp.batch = "t"
    out = {s.id: s for s in b.run()}
    assert out["no3-s0"].status == "done" and "no3-s0" in fake.indexed
    assert fake.deposited == []                       # neither the new run nor the leftover is deposited
    ev = _events(tmp_path)
    assert any(x["event"] == "kept_local" and x["id"] == "no3-s0" for x in ev)


def test_keep_raw_is_recorded_for_the_first_plan_as_well_as_later_ones(tmp_path):
    a = _plan_file(tmp_path, "bv14", [_r("no3-s0", group="anaerobic", cond="no_oxygen_plus_nitrate")], keep_raw=True)
    b = _plan_file(tmp_path, "bv12", [_r("fbp-s0")])
    plan, _ = B.load_plans([a, b])
    assert plan["keep_raw_by_batch"] == {"bv14": True}
    plan2, _ = B.load_plans([b, a])
    assert plan2["keep_raw_by_batch"] == {"bv14": True}


def test_a_control_another_process_already_indexed_is_read_for_the_gate_not_skipped(tmp_path):
    # 2026-11-25: after a restart the basal control "existed" (indexed by the previous process), the gate read only
    # finished or adopted controls, and closed the group: both main runs were skipped
    fake = Fake(existing={"wt-s0"})
    b = _batch(tmp_path, [_r("wt-s0", role="control"), _r("fbp-s0", stage=2)], fake, on_disk_fn=lambda root: True)
    b.gates = GATE
    out = {s.id: s for s in b.run()}
    assert out["fbp-s0"].status == "done" and out["wt-s0"].summary.get("qc") == "ok"
    assert "wt-s0" not in fake.indexed                 # read for the gate only: never indexed twice
    # forced: a control that exists but is no longer on disk cannot be read, and its group stays closed
    fake2 = Fake(existing={"wt-s0"})
    b2 = _batch(tmp_path / "x", [_r("wt-s0", role="control"), _r("fbp-s0", stage=2)], fake2,
                on_disk_fn=lambda root: False)
    b2.gates = GATE
    out2 = {s.id: s for s in b2.run()}
    assert out2["fbp-s0"].status == "skipped"


def test_a_reclaimed_control_is_gated_on_the_summary_its_ledger_recorded(tmp_path):
    # 2026-11-26: BV-12's acetate and succinate controls were indexed, deposited and reclaimed before any process
    # reached their gate; after a restart they "existed" but were gone from disk, and both groups closed unchecked.
    # The ledger recorded each control's summary when it finished: the gate reads it from there.
    fake = Fake(existing={"wt-s0"})
    good = B.summarize(_rec(1.6e-4), "ok", [SimpleNamespace(value="ok")])
    b = _batch(tmp_path, [_r("wt-s0", role="control"), _r("fbp-s0", stage=2)], fake, on_disk_fn=lambda root: False,
               recorded_summaries={"wt-s0": good})
    b.gates = GATE
    out = {s.id: s for s in b.run()}
    assert out["fbp-s0"].status == "done"
    # forced: a recorded summary outside the reference closes the group
    bad = B.summarize(_rec(0.5e-4), "ok", [SimpleNamespace(value="ok")])
    b2 = _batch(tmp_path / "x", [_r("wt-s0", role="control"), _r("fbp-s0", stage=2)], Fake(existing={"wt-s0"}),
                on_disk_fn=lambda root: False, recorded_summaries={"wt-s0": bad})
    b2.gates = GATE
    assert {s.id: s for s in b2.run()}["fbp-s0"].status == "skipped"


def test_recorded_summaries_come_from_the_last_finished_or_adopted_event(tmp_path):
    led = tmp_path / "l.jsonl"
    led.write_text("\n".join(json.dumps(x) for x in [
        {"event": "finished", "id": "wt-s0", "summary": {"qc": "ok", "n": 1}},
        {"event": "adopted", "id": "wt-s0", "summary": {"qc": "ok", "n": 2}},
        {"event": "indexed", "id": "wt-s0"},
        {"event": "finished", "id": "other", "summary": {"qc": "crashed"}}]) + "\n", encoding="utf-8")
    got = B.recorded_summaries([led])
    assert got["wt-s0"]["n"] == 2 and got["other"]["qc"] == "crashed"


def test_a_crashed_run_is_recorded_in_the_manifest_as_a_crash_not_only_in_the_ledger(tmp_path):
    # serA-glucose-s1 (2026-11-25) crashed in generation 2; the batch logged it and indexed nothing, so the crash was
    # invisible to the manifest (corpus_integrity listed it as an unindexed design on disk)
    fake = Fake()
    crashes = []

    def run_fn(spec):
        raise RuntimeError("model crashed")
    fake.run_fn = run_fn
    b = _batch(tmp_path, [_r("serA-s1")], fake, crash_index_fn=lambda spec, exc: crashes.append((spec.id, str(exc))))
    out = {s.id: s for s in b.run()}
    assert out["serA-s1"].status == "failed" and crashes == [("serA-s1", "model crashed")]
    assert any(e["event"] == "crash_indexed" for e in _events(tmp_path))


def test_runs_sharing_a_variant_dir_are_not_launched_side_by_side(tmp_path):
    # the runner serialises a variant's seeds on a lock, so a second run of the same variant launched beside the first
    # parks a slot; BV-12's queue put each gene's acetate and succinate runs next to each other and halved throughput
    fake = Fake()
    order = []
    lock = threading.Lock()
    active = {"cyaA": 0}
    peak = {"cyaA": 0}
    orig = fake.run_fn

    def run_fn(spec):
        gene = spec.id.split("-")[0]
        with lock:
            order.append(spec.id)
            active[gene] = active.get(gene, 0) + 1
            peak[gene] = max(peak.get(gene, 0), active[gene])
        import time as _t
        _t.sleep(0.05)
        with lock:
            active[gene] -= 1
        return orig(spec)
    fake.run_fn = run_fn
    specs = [_r("cyaA-acetate-s0", cond="KO:cyaA"), _r("cyaA-succinate-s0", cond="KO:cyaA2"),
             _r("dctA-acetate-s0", cond="KO:dctA")]
    b = _batch(tmp_path, specs, fake, parallel=3, variant_key_fn=lambda spec: spec.id.split("-")[0])
    b.run()
    assert peak["cyaA"] == 1                                    # never two cyaA runs at once
    assert order.index("dctA-acetate-s0") < order.index("cyaA-succinate-s0")   # the free slot went to another gene


def test_a_control_whose_clamp_did_not_hold_closes_its_group():
    """BV-14d: a clamped control passes only if each clamped factor's promoters were bound at the set fraction. The
    clamp sets a probability; binding is capped by the factor's free active molecules, so a clamp can be in force
    and still not held. FORCED: unread occupancy fails the gate instead of passing it."""
    done = {"qc": "ok", "generations": [{"division_time_sec": 4000.0}], "growth_rate_series": [[10.0, 1.2e-4]]}
    c = B.RunSpec(id="ctl", design={}, seed=310, generations=1, group="g", role="control", status="done",
                  summary=done)
    rule = {"growth_rate": [7.7e-5, 1.73e-4], "occupancy": {"FNR-4FE-4S-CPLX": [0.73, 0.83]}}
    ok, why = B.gate_result(c, rule, occupancy=lambda spec: {"FNR-4FE-4S-CPLX": 0.78})
    assert ok, why
    ok, why = B.gate_result(c, rule, occupancy=lambda spec: {"FNR-4FE-4S-CPLX": 0.61})
    assert not ok and "FNR-4FE-4S-CPLX" in why and "0.61" in why
    ok, why = B.gate_result(c, rule, occupancy=lambda spec: None)
    assert not ok and "unread" in why
    ok, why = B.gate_result(c, rule)                          # no reader wired: cannot pass an occupancy gate
    assert not ok
    # a perturbation's control (FNR held off) is gated on its clamp alone, with no growth range
    off = {"occupancy": {"FNR-4FE-4S-CPLX": [0.0, 0.0]}}
    assert B.gate_result(c, off, occupancy=lambda spec: {"FNR-4FE-4S-CPLX": 0.0})[0]
