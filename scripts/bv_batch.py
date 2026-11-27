"""Run a batch of simulations for the biological tests: staged, gated, summarised, indexed and deposited as it goes.

The plan is a JSON file: {"batch": name, "sim_path": "cellarium", "parallel": 6, "min_free_gb": 40,
"gates": {group: {"growth_rate": [lo, hi]}}, "runs": [{"id", "design", "seed", "generations", "group",
"role", "stage"}]}. The driver:

  1. skips every run that already exists: complete on disk, or indexed in the manifest at its run path with at
     least the planned generations (the user's rule: never re-run what exists);
  2. launches stage-1 runs (validity controls first), at most `parallel` at once, and only while the disk has
     `min_free_gb` free;
  3. gates each later stage on its group's stage-1 controls: a control must pass QC and grow at a rate inside
     the group's reference range (the fitted condition's own corpus runs) at generation 0, or the group's
     remaining runs are not launched;
  4. after each run: reads it, applies QC, writes a per-generation summary to the batch ledger, indexes it into a
     manifest shard, and hands it to the deposit worker, which uploads, verifies anonymously and reclaims;
  5. stops the remaining seeds of a design that failed for an integrity reason (crash, empty, degenerate,
     truncated, over-replicated, implausible channel) before any of its seeds finished cleanly in this process.
     Once one seed has, a later seed's failure is that seed's alone: it is recorded and discarded, and the
     design's other seeds still run (BV-14d, 2026-11-27: a skipped seed left an arm short of its pre-registered
     test). A lethal phenotype (no division, death) is data and is kept.

    WCECOLI_DOCKER=<code image> python scripts/bv_batch.py --plan evals/plans/bv12.json --repo <org/corpus>
"""
from __future__ import annotations

import argparse
import json
import queue
import shutil
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

INTEGRITY_FAILURES = {"crashed", "empty", "degenerate", "truncated", "over_replicated", "implausible_channel"}


@dataclass
class RunSpec:
    id: str
    design: dict
    seed: int
    generations: int
    group: str
    role: str = "run"           # "control" runs gate their group's later stages
    stage: int = 1
    priority: int = 0           # lower launches first, across plans
    sim_path: str | None = None  # the knowledge base the run uses (runs/<sim_path>/kb); None = the plan's
    batch: str | None = None    # the plan the run came from, whose ledger records it
    # D28: a refused design runs only under a named override (a pre-registered negative control), recorded beside it
    envelope_override: str = ""
    # D32: the QC verdict(s) a pre-registered run exists to SHOW (a negative control's defect). Such a verdict is the
    # measurement, not an integrity failure, so it does not block the design's other seeds; anything else still does.
    expected_qc: list = field(default_factory=list)
    status: str = "pending"
    why: str = ""
    summary: dict = field(default_factory=dict)


def load_plan(path: Path) -> tuple[dict, list[RunSpec]]:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    runs = [RunSpec(**{k: r[k] for k in ("id", "design", "seed", "generations", "group")},
                    role=r.get("role", "run"), stage=int(r.get("stage", 1)),
                    priority=int(r.get("priority", plan.get("priority", 0))),
                    sim_path=r.get("sim_path") or plan.get("sim_path", "cellarium"), batch=plan["batch"],
                    envelope_override=str(r.get("envelope_override") or ""),
                    expected_qc=[str(q) for q in (r.get("expected_qc") or [])])
            for r in plan["runs"]]
    ids = [r.id for r in runs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate run ids in the plan")
    return plan, runs


def load_plans(paths: list[Path]) -> tuple[dict, list[RunSpec]]:
    """Several plans in ONE queue, so they share the machine's parallel limit instead of each taking it. Each run
    keeps its plan's knowledge base (sim_path), ledger (batch) and priority; scheduling settings come from the
    first plan; gates merge, and a run id may appear in only one plan."""
    merged, runs, seen = None, [], {}
    for path in paths:
        plan, rs = load_plan(Path(path))
        if merged is None:
            merged = {**{k: v for k, v in plan.items() if k != "runs"}, "gates": dict(plan.get("gates", {})),
                      "batches": [plan["batch"]], "keep_raw_by_batch": {}}
        else:
            for g, rule in plan.get("gates", {}).items():
                if g in merged["gates"] and merged["gates"][g] != rule:
                    raise ValueError(f"plans disagree on the gate for group {g}")
                merged["gates"][g] = rule
            merged["batches"].append(plan["batch"])
        if plan.get("keep_raw"):
            merged["keep_raw_by_batch"][plan["batch"]] = True
        for r in rs:
            if r.id in seen:
                raise ValueError(f"run id {r.id} is in both {seen[r.id]} and {plan['batch']}")
            seen[r.id] = plan["batch"]
        runs += rs
    return merged, runs


def design_key(spec: RunSpec) -> str:
    d = spec.design
    return json.dumps({k: d.get(k) for k in ("perturbation", "condition", "timeline", "params", "elongation_model")},
                      sort_keys=True)


def summarize(rec, qc_overall: str, qc_per: list) -> dict:
    """What the biological tests need from a run, kept after its raw output is reclaimed."""
    gens = []
    for g, q in zip(rec.generations, qc_per):
        gens.append({"index": g.index, "divided": g.divided, "division_time_sec": g.division_time_sec,
                     "n_steps": g.n_steps, "qc": getattr(q, "value", str(q))})
    keep = ("growth_rate", "cell_mass", "dry_mass", "protein_mass", "rna_mass", "ppgpp_conc", "ribosome_conc",
            "rnap_conc", "elongation_rate", "division_rate")
    return {"qc": qc_overall, "generations": gens,
            "channels": {k: v for k, v in (rec.channels or {}).items() if k in keep},
            "growth_rate_series": (rec.series or {}).get("growth_rate"),
            "note": rec.note}


def gate_result(spec: RunSpec, rule: dict | None, occupancy=None) -> tuple[bool, str]:
    """A control passes when it is QC-clean, its generation-0 growth sits inside the group's reference range (when
    one is declared), and (BV-14d) each clamped factor's promoters were bound at the set fraction. `occupancy(spec)`
    returns {factor: bound fraction} read from the control's raw output; a clamp sets a probability, and binding is
    capped by the factor's free active molecules, so a clamp in force can still fail to hold."""
    s = spec.summary
    finished = spec.status in ("done", "adopted") or (spec.status == "exists" and spec.summary.get("qc"))
    if not finished:                                   # adopted or exists: finished under a previous process
        return False, f"control did not finish: {spec.status} {spec.why}"
    if s.get("qc") != "ok":
        return False, f"control QC {s.get('qc')}"
    if not rule:
        return True, "no reference range declared"
    checks = []
    if "growth_rate" in rule:
        lo, hi = rule["growth_rate"]
        series = s.get("growth_rate_series") or []
        g0 = (s.get("generations") or [{}])[0]
        t_div = g0.get("division_time_sec")
        vals = [v for t, v in series if v is not None and (t_div is None or t <= t_div)]
        mu = sum(vals) / len(vals) if vals else s.get("channels", {}).get("growth_rate")
        if mu is None:
            return False, "no growth rate to check"
        checks.append(f"generation-0 growth {mu:.3g}/s against the reference [{lo:.3g}, {hi:.3g}]")
        if not lo <= mu <= hi:
            return False, checks[-1]
    if rule.get("occupancy"):
        got = occupancy(spec) if occupancy else None
        if not isinstance(got, dict):
            return False, f"the clamped factors' occupancy was unread ({got!r}), so the clamp is unverified"
        for tf, (lo, hi) in rule["occupancy"].items():
            v = got.get(tf)
            checks.append(f"{tf} bound fraction {v if v is None else round(v, 3)} against [{lo}, {hi}]")
            if v is None or not lo <= v <= hi:
                return False, checks[-1]
    return True, "; ".join(checks) or "no reference range declared"


class Batch:
    def __init__(self, plan: dict, runs: list[RunSpec], *, run_fn, read_fn, qc_fn, index_fn, deposit_fn,
                 existing_fn, free_gb_fn, ledger: Path, ledgers: dict | None = None, sleep=time.sleep,
                 poll_s: float = 30.0, busy_fn=None, root_fn=None, clock=time.time, on_disk_fn=None,
                 deposit_elsewhere=(), keep_raw_batches=(), recorded_summaries=None, crash_index_fn=None,
                 variant_key_fn=None, occupancy_fn=None, transit_fn=None):
        self.plan, self.runs = plan, runs
        self.run_fn, self.read_fn, self.qc_fn, self.index_fn = run_fn, read_fn, qc_fn, index_fn
        self.deposit_fn, self.existing_fn, self.free_gb_fn = deposit_fn, existing_fn, free_gb_fn
        # busy_fn: simulations running on this machine that THIS process did not start (a previous batch's runs
        # left in flight by a restart, anyone's); they take slots, so the parallel limit is the machine's
        self.busy_fn = busy_fn or (lambda: 0)
        self.root_fn = root_fn                    # a run's output directory, to adopt one found on disk
        self.clock = clock
        self.on_disk = on_disk_fn or (lambda root: Path(root).is_dir())
        self.deposit_elsewhere = set(deposit_elsewhere)   # ids another running depositor has already listed
        # plans scored from raw output after their runs finish (BV-14): indexed, never deposited or reclaimed here
        self.keep_raw = set(keep_raw_batches)
        # each run's summary as its plan's ledger recorded it when it finished: a control indexed, deposited and
        # reclaimed by an earlier process is gated on this (it cannot be re-read)
        self.recorded = dict(recorded_summaries or {})
        self.crash_index_fn = crash_index_fn       # a crashed run becomes a manifest crash row (manifest._crash_row)
        # the model variant dir a run writes into; the runner serialises a variant's runs on a lock, so two of this
        # process's runs of one variant side by side would park a slot: the second waits in the queue instead
        self.variant_key_fn = variant_key_fn
        self.occupancy_fn = occupancy_fn          # BV-14d: a clamped control's bound fractions, for its gate
        self.transit_fn = transit_fn              # the dir the MODEL writes a run into (its root, or a sibling's)
        self._waiting_since: dict[str, float] = {}
        self._deferred: set[str] = set()          # runs whose "deferred" event is logged (once each)
        self._own_running: dict = {}
        self.ledger, self.sleep, self.poll_s = ledger, sleep, poll_s
        self.ledgers = dict(ledgers or {})      # batch name -> its ledger; a run logs to its own plan's
        self.parallel = int(plan.get("parallel", 6))
        self.min_free = float(plan.get("min_free_gb", 40))
        self.gates = plan.get("gates", {})
        self.gate_open: dict[str, bool | None] = {}
        self.blocked_designs: set[str] = set()
        # designs with a seed that finished in this process without an integrity failure: shown to run, so a later
        # seed's failure does not block the rest (the block is for designs that cannot run at all)
        self.proven_designs: set[str] = set()
        self.deposits: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

    def _ledgers_for(self, spec: RunSpec | None, group: str | None) -> list[Path]:
        """A run's events go to its own plan's ledger; a group's gate to the ledgers of the plans in that group;
        an event of the whole batch (batch_done, waiting_for_disk) to every ledger."""
        if spec is not None and spec.batch in self.ledgers:
            return [self.ledgers[spec.batch]]
        if group is not None:
            hits = {self.ledgers[r.batch] for r in self.runs if r.group == group and r.batch in self.ledgers}
            if hits:
                return sorted(hits)
        if spec is None and group is None and self.ledgers:
            return sorted(set(self.ledgers.values()))
        return [self.ledger]

    def log(self, event: str, spec: RunSpec | None = None, **kw) -> None:
        row = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event,
               **({"id": spec.id, "group": spec.group, "seed": spec.seed} if spec else {}), **kw}
        with self._lock:
            for path in self._ledgers_for(spec, kw.get("group") if spec is None else None):
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, default=str) + "\n")

    # ---- scheduling ------------------------------------------------------------------------------------------
    def _controls(self, group: str) -> list[RunSpec]:
        return [r for r in self.runs if r.group == group and r.role == "control" and r.stage == 1]

    def _gate(self, group: str) -> bool | None:
        """True/False once the group's stage-1 controls have all settled; None while any is still pending."""
        if group in self.gate_open and self.gate_open[group] is not None:
            return self.gate_open[group]
        ctl = self._controls(group)
        if not ctl:
            self.gate_open[group] = True
            return True
        if any(c.status in ("pending", "running") for c in ctl):
            return None
        results = [gate_result(c, self.gates.get(group), occupancy=self.occupancy_fn) for c in ctl]
        ok = all(r[0] for r in results)
        self.gate_open[group] = ok
        self.log("gate", None, group=group, open=ok, checks=[r[1] for r in results])
        return ok

    def _launchable(self, spec: RunSpec) -> bool:
        if spec.status != "pending":
            return False
        if design_key(spec) in self.blocked_designs and design_key(spec) not in self.proven_designs:
            spec.status, spec.why = "skipped", "an earlier seed of this design failed an integrity check"
            self.log("skipped", spec, why=spec.why)
            return False
        if spec.stage > 1:
            g = self._gate(spec.group)
            if g is None:
                return False
            if g is False:
                spec.status, spec.why = "skipped", "the group's validity controls failed"
                self.log("skipped", spec, why=spec.why)
                return False
        return True

    def _transit_sibling(self, spec: RunSpec) -> tuple[RunSpec, str] | None:
        """A kept run whose home is ANOTHER run's transit dir goes second.

        The model writes every design of one variant index and seed into that index's dir, and a plain design's run
        root IS that dir. A suffixed sibling's output moves out when its run finishes; the plain run's never does,
        and a keep_raw plan never deposits it, so a sibling queued behind it waits for a reclaim that cannot come.
        CRIT tier 1 V1 (2026-11-27): two relaxed arms parked behind their kept medium arms, to be skipped after
        max_wait_s. A sibling in a later stage is left alone: it may be gated on this very run.

        Returns (sibling, "first") while the sibling has still to finish, (sibling, "left_output") when it failed
        with this run's home on disk (its partial output: running here would rmtree it, and a run complete on disk
        here would be adopted under the wrong design), else None."""
        if spec.batch not in self.keep_raw or not (self.transit_fn and self.root_fn):
            return None
        home = Path(self.root_fn(spec))
        for other in self.runs:
            if other is spec or other.stage > spec.stage:
                continue
            transit = Path(self.transit_fn(other))
            if transit != home or Path(self.root_fn(other)) == transit:
                continue
            if other.status in ("pending", "running", "adopting"):
                return other, "first"
            if other.status == "failed" and self.on_disk(home):
                return other, "left_output"
        return None

    def _existing(self, spec: RunSpec) -> dict | None:
        """existing_fn's answer, normalised: None (absent), or {"where", "why"} with where one of "indexed"
        (exists, nothing to do), "disk_unindexed" (finished on disk, unknown to the manifest: adopt it) or
        "writing" (another process is writing it now: look again later). A bare string means indexed."""
        e = self.existing_fn(spec)
        if not e:
            return None
        return {"where": "indexed", "why": e} if isinstance(e, str) else e

    def run(self) -> list[RunSpec]:
        leftover = []
        for spec in self.runs:
            e = self._existing(spec)
            if e and e["where"] == "indexed":
                spec.status, spec.why = "exists", e["why"]
                self.log("exists", spec, why=e["why"])
                root = self.root_fn(spec) if self.root_fn else None
                if root is not None and self.on_disk(root):
                    leftover.append((spec, root))
                    if spec.role == "control":
                        self._summarise_for_gate(spec, root)
                elif spec.role == "control" and self.recorded.get(spec.id):
                    spec.summary = self.recorded[spec.id]
                    self.log("control_gated_on_its_ledger", spec, qc=spec.summary.get("qc"),
                             why="indexed and reclaimed earlier; its summary as recorded when it finished")
        depositor = threading.Thread(target=self._deposit_worker, daemon=True)
        depositor.start()
        # indexed, but still on disk: a restart dropped the previous process's deposit queue. The deposit is
        # idempotent (already on the hub -> verify -> reclaim), and each of these may be the transit dir another
        # design is waiting for.
        for spec, root in leftover:
            if spec.batch in self.keep_raw:
                self.log("kept_local", spec, why="its plan is scored from raw output; deposit after scoring")
                continue
            if spec.id in self.deposit_elsewhere:
                self.log("deposit_left_elsewhere", spec, why="another depositor listed this run before the batch "
                                                             "started; two would race to reclaim it")
                continue
            self.log("deposit_queued", spec, why="indexed and still on disk")
            self.deposits.put((spec, root))
        # Seeds of one design serialise on the variant's shared knowledge base (runner._variant_dir_lock), so
        # launching seed 1 beside seed 0 parks a slot. Every design's first seed goes before any second seed.
        order = sorted((r for r in self.runs if r.status == "pending"),
                       key=lambda r: (r.priority, r.stage, r.role != "control", r.seed, r.id))
        running = self._own_running
        with ThreadPoolExecutor(max_workers=self.parallel) as ex:
            while True:
                capacity = self.parallel - max(0, int(self.busy_fn() or 0))
                busy_variants = ({self.variant_key_fn(r) for r in running.values()} if self.variant_key_fn else set())
                for spec in order:
                    if len(running) >= capacity:
                        break
                    if not self._launchable(spec):
                        continue
                    sib = self._transit_sibling(spec)
                    if sib and sib[1] == "first":
                        if spec.id not in self._deferred:
                            self._deferred.add(spec.id)
                            self.log("deferred", spec, why=f"its home is the transit dir of {sib[0].id}, which "
                                                           f"runs first: kept output here would strand it")
                        continue
                    if sib:
                        spec.status, spec.why = "skipped", (
                            f"{sib[0].id} failed after the model wrote into this run's home, and its partial output "
                            f"may still be there; running here would delete it. Move it deliberately, then rerun")
                        self.log("skipped", spec, why=spec.why)
                        continue
                    if self.variant_key_fn and self.variant_key_fn(spec) in busy_variants:
                        continue                                     # its variant is running here; next gene first
                    # existence is checked again when the run comes up: another process may have finished it,
                    # or may be writing it right now, since the batch started
                    e = self._existing(spec)
                    if e and e["where"] in WAIT_STATES:
                        self._wait(spec, e["why"])
                        continue
                    if e and e["where"] == "disk_unindexed":
                        self._adopt(spec, e["why"])
                        continue
                    if e:
                        spec.status, spec.why = "exists", e["why"]
                        self.log("exists", spec, why=e["why"])
                        continue
                    free = self.free_gb_fn()
                    if free < self.min_free:
                        self.log("waiting_for_disk", None, free_gb=round(free, 1))
                        break
                    spec.status = "running"
                    self.log("launched", spec, design=spec.design, generations=spec.generations)
                    running[ex.submit(self._one, spec)] = spec
                    if self.variant_key_fn:
                        busy_variants.add(self.variant_key_fn(spec))
                if not running:
                    if all(r.status != "pending" for r in order):
                        break
                    self.sleep(self.poll_s)
                    continue
                done, _ = wait(list(running), timeout=self.poll_s, return_when=FIRST_COMPLETED)
                for fut in done:
                    running.pop(fut)
        self.deposits.put(None)
        depositor.join()
        self.log("batch_done", None, counts=_counts(self.runs))
        return self.runs

    # ---- one run ---------------------------------------------------------------------------------------------
    def _summarise_for_gate(self, spec: RunSpec, root) -> None:
        """A control another process already finished and indexed: read it for the gate only (never re-indexed or
        re-deposited here). A control no longer on disk cannot be read, and its group stays closed."""
        try:
            rec = self.read_fn(spec, root)
            overall, per = self.qc_fn(rec)
            spec.summary = summarize(rec, getattr(overall, "value", str(overall)), per)
            self.log("control_read_for_gate", spec, qc=spec.summary.get("qc"))
        except Exception as e:                                       # noqa: BLE001
            self.log("read_failed", spec, why=f"{type(e).__name__}: {str(e)[:300]}")

    def _wait(self, spec: RunSpec, why: str) -> None:
        """Not launchable NOW: another process is writing the run, or its transit dir is another run's home that
        the deposit has not reclaimed yet. Look again next pass; give up, with the reason, after max_wait_s."""
        now = self.clock()
        since = self._waiting_since.setdefault(spec.id, now)
        if since == now:
            self.log("waiting", spec, why=why)
        limit = float(self.plan.get("max_wait_s", 6 * 3600))
        if now - since > limit:
            spec.status, spec.why = "skipped", f"waited {(now - since) / 3600:.1f} h: {why}"
            self.log("skipped", spec, why=spec.why)

    def _one(self, spec: RunSpec) -> None:
        try:
            root = self.run_fn(spec)
        except Exception as e:                                       # noqa: BLE001
            spec.status, spec.why = "failed", f"{type(e).__name__}: {str(e)[:300]}"
            # D29: a run REFUSED before the model started produced nothing; a crash row for it has no knowledge base
            # and a NULL condition, and filed V3's refused anaerobic-start control under another design. The ledger
            # still records a terminal run_failed, marked refused.
            refused = bool(getattr(e, "refused", False))
            self.log("run_failed", spec, why=spec.why, **({"refused": True} if refused else {}))
            self.blocked_designs.add(design_key(spec))
            if self.crash_index_fn and not refused:
                try:
                    self.crash_index_fn(spec, e)
                    self.log("crash_indexed", spec)
                except Exception as e2:                              # noqa: BLE001
                    self.log("crash_index_failed", spec, why=f"{type(e2).__name__}: {e2}")
            return
        self._after(spec, root, status="done", event="finished")

    def _adopt(self, spec: RunSpec, why: str) -> None:
        """A run finished on disk that the manifest never saw (a crash, a restart, another process): read, QC,
        summarise, index and deposit it exactly as if this batch had run it. It is never re-run."""
        root = self.root_fn(spec) if self.root_fn else None
        if root is None:
            spec.status, spec.why = "exists", f"{why}; no root_fn to adopt it with, so it stays unindexed"
            self.log("exists", spec, why=spec.why)
            return
        spec.status = "adopting"
        self.log("adopting", spec, why=why)
        self._after(spec, root, status="adopted", event="adopted")

    def _after(self, spec: RunSpec, root, *, status: str, event: str) -> None:
        try:
            rec = self.read_fn(spec, root)
            overall, per = self.qc_fn(rec)
            spec.summary = summarize(rec, getattr(overall, "value", str(overall)), per)
        except Exception as e:                                       # noqa: BLE001
            spec.status, spec.why = "unread", f"{type(e).__name__}: {str(e)[:300]}"
            self.log("read_failed", spec, why=spec.why)
            return
        spec.status = status
        self.log(event, spec, summary=spec.summary)
        if spec.summary["qc"] in INTEGRITY_FAILURES and spec.summary["qc"] not in (spec.expected_qc or []):
            self.blocked_designs.add(design_key(spec))
            self.log("integrity_failure", spec, qc=spec.summary["qc"])
        else:
            if spec.summary["qc"] in (spec.expected_qc or []):
                self.log("expected_qc", spec, qc=spec.summary["qc"],
                         why="the QC verdict this pre-registered run exists to show, declared in its plan")
            self.proven_designs.add(design_key(spec))
        try:
            self.index_fn(spec, root, rec)
            self.log("indexed", spec)
        except Exception as e:                                       # noqa: BLE001
            self.log("index_failed", spec, why=f"{type(e).__name__}: {e}")
            return                                                   # never reclaim a run the manifest lacks
        if spec.batch in self.keep_raw:
            self.log("kept_local", spec, why="its plan is scored from raw output; deposit after scoring")
            return
        self.deposits.put((spec, root))

    def _deposit_worker(self) -> None:
        while True:
            item = self.deposits.get()
            if item is None:
                return
            spec, root = item
            try:
                row = self.deposit_fn(root)
                self.log("deposited", spec, verified=row.get("verified"), reclaimed=row.get("reclaimed"),
                         why=row.get("why"))
            except Exception as e:                                   # noqa: BLE001
                self.log("deposit_failed", spec, why=f"{type(e).__name__}: {e}")


def recorded_summaries(ledgers) -> dict:
    """{run id: the summary of its LAST finished or adopted event} over the given ledgers."""
    out = {}
    for path in ledgers:
        path = Path(path)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") in ("finished", "adopted") and e.get("id") and e.get("summary"):
                out[e["id"]] = e["summary"]
    return out


def _counts(runs: list[RunSpec]) -> dict:
    out: dict[str, int] = {}
    for r in runs:
        out[r.status] = out.get(r.status, 0) + 1
    return out


# ---- wiring to the real platform ---------------------------------------------------------------------------------

def _wire(plan: dict, repo: str, ledger: Path):
    from cellarium import manifest, qc, runner
    from cellarium.generate import Design
    default_sim_path = plan.get("sim_path", "cellarium")
    out_root = runner._out_root(default_sim_path).parent    # runs/, the parent of every sim_path

    def sp(spec):
        """The knowledge base this run uses: its own plan's sim_path (runs/<sim_path>/kb)."""
        return spec.sim_path or default_sim_path
    sys.path.insert(0, str(REPO / "scripts"))
    import hf_deposit
    from huggingface_hub import HfApi

    def design(spec):
        return Design(**spec.design)

    def run_fn(spec):
        return runner.run_one(design(spec), spec.seed, spec.generations, sim_path=sp(spec),
                              envelope_override=spec.envelope_override or None)

    def read_fn(spec, root):
        return manifest.build_record(Path(root), design(spec), spec.seed)

    def index_fn(spec, root, rec):
        row = manifest._flat_row(rec, spec.seed, Path(root), requested_generations=spec.generations,
                                 sim_path=sp(spec))
        manifest.append_shard([row], name=f"{spec.batch or plan['batch']}-{spec.id}")

    up, anon = HfApi(), HfApi(token=False)

    def deposit_fn(root):
        return hf_deposit.deposit_one(Path(root), out=str(out_root), repo=repo, upload_api=up, anon_api=anon,
                                      ledger=REPO / "data" / "hf" / "deposit_ledger.jsonl", reclaim=True)

    import os
    import subprocess

    import duckdb
    m = (REPO / "data" / "manifest").as_posix()

    def indexed(rel, generations):
        # re-read at every check: a run indexed since the batch started must not be adopted a second time
        rows = duckdb.connect().sql(f"SELECT simout_path, generations, qc FROM read_parquet('{m}/*.parquet', "
                                    f"union_by_name=true)").fetchall()
        return any(str(r[0] or "").replace("\\", "/").find(rel) >= 0 and (r[1] or 0) >= generations for r in rows)

    def existing_fn(spec):
        d = design(spec)
        root = runner._run_subpath(d, spec.seed, sp(spec))
        rel = root.relative_to(out_root).as_posix()
        if indexed(rel, spec.generations):
            return f"in the manifest at {rel}"
        # BEFORE "complete": a run in its last generation already has that generation's directory, and adopting
        # it would deposit and reclaim a directory a container is still writing. The model writes into its own
        # dir, which is not the run root when the design carries a discriminator suffix.
        model_dir = runner._model_output_dir(d, spec.seed, sp(spec))
        if any(_recently_written(p, WRITING_S) for p in {root, model_dir}):
            return {"where": "writing", "why": f"output under {rel} modified in the last {WRITING_S} s"}
        # Seeds of one design share the variant's knowledge base file, which each run rewrites at its start and
        # each generation re-reads: the runner's lock serialises them within ONE process only, so a seed another
        # process is running (an orphan after a restart) makes the whole variant dir busy (the P1 race).
        if _recently_written(model_dir.parent, WRITING_S):
            return {"where": "writing", "why": f"another seed of {model_dir.parent.name} was written in the last "
                                               f"{WRITING_S} s (the variant's shared knowledge base)"}
        last = root / f"generation_{spec.generations - 1:06d}"
        if last.exists() and any(last.glob("**/simOut")):
            return {"where": "disk_unindexed", "why": f"complete on disk at {rel}, not in the manifest"}
        # the model writes into its transit dir; when that dir is ANOTHER run's home (a plain knockout of the same
        # gene and seed) the runner refuses (runner._evacuate), so wait for the deposit to reclaim the occupant
        if model_dir != root and model_dir.is_dir() and any(model_dir.iterdir()):
            return {"where": "occupied", "why": f"its transit dir {model_dir.relative_to(out_root).as_posix()} "
                                                f"holds another run until that run is deposited and reclaimed"}
        return ""

    def occupancy_fn(spec):
        """BV-14d: the bound fraction of each factor the control's group gate names, from its raw output."""
        from cellarium import reader
        tfs = list((((plan.get("gates") or {}).get(spec.group) or {}).get("occupancy")) or {})
        if not tfs:
            return {}
        root = runner._run_subpath(design(spec), spec.seed, sp(spec))
        got = reader.synthesis_per_run([root], [], tfs)
        r = got.get(reader._container_path(root)) if isinstance(got, dict) else None
        return None if not isinstance(r, dict) or r.get("error") else r.get("bound_fraction")

    def free_gb_fn():
        return shutil.disk_usage(str(out_root)).free / 1e9

    def busy_fn():
        """Simulation containers on this machine that this process did not start. Unreadable is not zero: if
        docker cannot be asked, nothing launches until it can."""
        try:
            r = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True,
                               timeout=60)
        except (OSError, subprocess.SubprocessError):
            return 10 ** 6
        if r.returncode != 0:
            return 10 ** 6
        mine = f"cellarium-{os.getpid()}-"
        return sum(1 for n in r.stdout.split() if n.startswith("cellarium-") and not n.startswith(mine))

    def root_fn(spec):
        return runner._run_subpath(design(spec), spec.seed, sp(spec))

    def variant_key_fn(spec):
        return str(runner._model_output_dir(design(spec), spec.seed, sp(spec)).parent)

    def transit_fn(spec):
        return runner._model_output_dir(design(spec), spec.seed, sp(spec))

    def crash_index_fn(spec, exc):
        row = manifest._crash_row(design(spec), spec.seed, spec.generations, exc, sp(spec))
        manifest.append_shard([row], name=f"{spec.batch or plan['batch']}-{spec.id}-crash")

    return dict(run_fn=run_fn, read_fn=read_fn, qc_fn=qc.check_result, index_fn=index_fn, deposit_fn=deposit_fn,
                existing_fn=existing_fn, free_gb_fn=free_gb_fn, ledger=ledger, busy_fn=busy_fn, root_fn=root_fn,
                crash_index_fn=crash_index_fn, variant_key_fn=variant_key_fn, occupancy_fn=occupancy_fn,
                transit_fn=transit_fn)


WRITING_S = 600        # output modified this recently belongs to a run some process is still writing
WAIT_STATES = ("writing", "occupied")


def _recently_written(path: Path, within_s: float) -> bool:
    if not path.exists():
        return False
    import os
    cutoff = time.time() - within_s
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                if os.stat(os.path.join(dirpath, f)).st_mtime > cutoff:
                    return True
            except OSError:
                continue
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", required=True, action="append",
                    help="a plan file; repeat to run several plans in one queue under one parallel limit")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--dry-run", action="store_true", help="list what would run and what already exists")
    ap.add_argument("--deposit-elsewhere", default="",
                    help="comma-separated run ids another running depositor has already listed")
    a = ap.parse_args(argv)
    plan, runs = load_plans([Path(x) for x in a.plan])
    ledgers = {b: REPO / "evals" / "results" / f"{b}_ledger.jsonl" for b in plan["batches"]}
    wiring = _wire(plan, a.repo, ledgers[plan["batch"]])
    if a.dry_run:
        for r in runs:
            why = wiring["existing_fn"](r)
            print(f"{'EXISTS ' if why else 'RUN    '} {r.batch:6s} p{r.priority:<3d} {r.id:40s} stage {r.stage} "
                  f"{r.role:7s} {r.sim_path} {why}")
        return 0
    elsewhere = {x for x in a.deposit_elsewhere.split(",") if x}
    keep = {b for b in plan["batches"] if plan.get("keep_raw_by_batch", {}).get(b)}
    runs = Batch(plan, runs, **wiring, ledgers=ledgers, deposit_elsewhere=elsewhere, keep_raw_batches=keep,
                 recorded_summaries=recorded_summaries(sorted(set(ledgers.values())))).run()
    print(json.dumps(_counts(runs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
