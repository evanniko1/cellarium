"""FAIL-1 — why a run failed, from the evidence the run itself left behind.

THE DEFECT THIS ENDS, MEASURED 2026-10-08. A crash row said THAT a run failed and almost never WHY. The runner
held the last 2,000 characters of the model's output when it raised, and the crash row cut its note to
150-200 characters, most of them the Docker command line — so the traceback was discarded at write time. The
only causes that survived were in hand-redirected campaign logs that existed for some campaigns and not
others, interleaved across parallel sims. `_classify_crash` then defaulted anything unrecognised to "model",
so a cell that ran out of ATP, a NaN inside a solver and a solver giving up all read as the same finding.

THREE PIECES.

  * **The log.** `runner._run_checked` tees the model's full output to `sim.log` in the run root, for EVERY
    run — success and failure. Successful runs matter too: their solver-retry warnings are how a zero
    `n_fba_failures` gets checked rather than believed. A previous log is rotated, never overwritten.
    DEVELOPMENT MATERIAL ONLY: it carries host paths and container settings, so `is_dev_only` names it and
    both upload paths exclude it. What, if anything, ships is a publication decision not taken here.

  * **The identity.** A failure is identified STRUCTURALLY — exception type + the deepest frame in model
    code, e.g. `ValueError@models/ecoli/processes/polypeptide_elongation.py:calculate_trna_charging` — not by
    matching message text. So a failure nobody has seen before still has a precise identity the moment it
    happens, and rewording a message does not change it. The function, not the line number, is in the key:
    line numbers move between model images, and a key that changed with them would split one failure into
    several. `KNOWN` names the identities seen so far, each citing the log that defined it. No evidence is
    `no_log`, never a guess.

  * **The loop.** An identity not in `KNOWN` is NOT parked as "unrecognised" to pile up. Its first sighting
    in a campaign is triaged immediately (`triage`): the cell's state just before the failure, whether the
    unmodified control under the same condition fails, how the design's other seeds failed, and — where the
    caller is authorised to spend a simulation on it — one repeat of the same design and seed. The record is
    written for naming, and `unnamed` is what a publication path refuses on.

WHAT AN IDENTITY IS NOT. It says WHERE the run failed, not WHY. The tRNA-charging failure surfaces inside the
charging solver; a non-finite value arriving there may originate upstream. The field is called `where`, and
`Signature.meaning` says what is and is not established, so a name cannot quietly become a diagnosis.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

SIM_LOG = "sim.log"
_ROTATED = re.compile(r"^sim\.\d{8}T\d{6}(?:_\d+)?\.log$")

# Globs for the upload paths. `is_dev_only` is the predicate; these are the same rule in the form
# `huggingface_hub.upload_folder(ignore_patterns=...)` accepts. A test pins that the two agree.
DEV_ONLY_GLOBS = ("sim.log", "sim.*.log", "**/sim.log", "**/sim.*.log")

# Markers `runner._run_checked` writes into the log. The exit status is not otherwise in the model's output,
# and without it a container killed by the host is indistinguishable from a run that printed nothing.
EXIT_MARK = "[cellarium] model process exited with status"
MARKER_MARK = "[cellarium] failure marker in output:"


def is_dev_only(name: str) -> bool:
    """True for a file that must never leave this machine as is: the run log and its rotations."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    return base == SIM_LOG or bool(_ROTATED.match(base))


def prepare_log(run_root: Path) -> Path:
    """The log path for a run about to start. An existing log is ROTATED, never overwritten: losing an earlier
    attempt's output is exactly how this corpus lost its causes."""
    run_root = Path(run_root)
    path = run_root / SIM_LOG
    if path.exists():
        stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime(path.stat().st_mtime))
        dest, n = run_root / f"sim.{stamp}.log", 1
        while dest.exists():
            dest, n = run_root / f"sim.{stamp}_{n}.log", n + 1
        path.rename(dest)
    return path


def read_log(run_root) -> str | None:
    """The run's own log, or None when it has none. None is reported as `no_log`, never as a clean run."""
    if not run_root:
        return None
    p = Path(run_root) / SIM_LOG
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# --------------------------------------------------------------------------------------------- identity

@dataclass(frozen=True)
class Signature:
    name: str
    category: str          # ran_out | numerical | solver | writer | infrastructure | refused | no_evidence
    result: bool           # True: a statement about the CELL. False: about the software, the host, or nothing.
    meaning: str           # what is established — and what is not
    evidence: str          # the log that defined it, or an explicit statement that none in this corpus has


@dataclass(frozen=True)
class Identity:
    key: str
    source: str                         # "log" | "note" | "none"
    exc_type: str | None = None
    where: str | None = None            # model-relative file:function of the deepest model frame
    line: int | None = None
    message: str | None = None
    detail: dict = field(default_factory=dict)

    @property
    def signature(self) -> Signature | None:
        return KNOWN.get(self.key) or (TYPE_RULES.get(self.exc_type) if self.exc_type else None)

    @property
    def named(self) -> bool:
        return self.signature is not None

    def as_dict(self) -> dict:
        s = self.signature
        return {**asdict(self), "named": s is not None, "name": s.name if s else None,
                "category": s.category if s else None, "result": s.result if s else None}


KNOWN: dict[str, Signature] = {
    "NegativeCountsError@wholecell/states/bulk_molecules.py:merge": Signature(
        "molecule pool exhausted", "ran_out", True,
        "A process requested more of a molecule than the cell held; `detail` names the molecule and process. "
        "In a depleted medium this is the cell failing to sustain itself — a result about the cell. It does "
        "not by itself prove the depletion caused it; the control and the pre-failure state say that.",
        "runs/stress_run.log — condition/minus_phosphate seed0: ATP[c] in PolypeptideElongation (-13690)"),
    "ValueError@models/ecoli/processes/polypeptide_elongation.py:calculate_trna_charging": Signature(
        "tRNA-charging solve received non-finite values", "numerical", False,
        "The stiff solver inside tRNA charging was handed infs or NaNs. This is WHERE it failed, not why: the "
        "non-finite value may originate upstream (an amino-acid pool reaching zero is the leading suspect) "
        "and that is not diagnosed in this corpus.",
        "runs/leu_arm.log + runs/arg_arm.log — 10 tracebacks, KO:leuB and KO:argG auxotroph arms"),
    "RuntimeError@wholecell/utils/_netflow/nf_glpk.py:_solve": Signature(
        "FBA solver failed (GLPK)", "solver", False,
        "The metabolism LP failed after the retry ladder ran out; `detail.glpk` carries the solver status. "
        "A cell that had already stopped growing can reach this on the way down, so the pre-failure state "
        "decides whether it is a software failure on a healthy cell or one recorded during a death.",
        "runs/gltx_run.log — GLP_EFAIL via metabolism.py:evolveState"),
    "refused:envelope": Signature(
        "refused by Cellarium's envelope", "refused", False,
        "Cellarium refused the design before anything ran. NOTHING WAS SIMULATED — this is not a crash and "
        "says nothing about the cell.",
        "41 objective-weight rows (kin_w, sec_pen) in the corpus index"),
    "refused:overwrite_guard": Signature(
        "refused to overwrite existing output", "refused", False,
        "The run would have overwritten output with no provenance, so it did not start. Nothing simulated.",
        "2 KO:argG rows in the corpus index"),
    "no_log": Signature(
        "no evidence retained", "no_evidence", False,
        "The run left no log (it predates log retention, or never started). Its cause is UNKNOWN, and is "
        "reported as unknown rather than inferred from the row.", "—"),
    "no_traceback": Signature(
        "log present, no failure in it", "no_evidence", False,
        "The log holds no traceback and no failing exit status. If the row says it crashed, the crash "
        "happened outside the model process.", "—"),
}

# Exception types specific enough to name without knowing the frame. Consulted only when the exact key is
# not in `KNOWN`. Each says plainly whether this corpus has ever produced it.
TYPE_RULES: dict[str, Signature] = {
    "VariableEntrySizeError": Signature(
        "listener row written at the wrong width", "writer", False,
        "A table writer rejected a row whose width differs from the column's. Output bookkeeping, not "
        "biology. The known candidate is `aaCountInSequence` built with np.bincount and no minlength.",
        "not yet observed in this corpus; the unguarded bincount is at model_overlay/cleaned/models/ecoli/"
        "processes/polypeptide_elongation.py:409"),
    "OSError": Signature(
        "host I/O failure", "infrastructure", False,
        "The filesystem failed under the run (the Docker bind mount saturates above 6 concurrent sims). "
        "Says nothing about the cell; re-run.",
        "observed at --parallel 8 (operations note); not attributed to a specific row"),
}

_TB = "Traceback (most recent call last):"
_CHAINED = ("During handling of the above exception", "The above exception was the direct cause")
_FRAME = re.compile(r'^\s+File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')
_EXC = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)(?::\s?(?P<msg>.*))?$")
_RAN_OUT = re.compile(r"^(?P<molecule>\S+\[\w+\]) in (?P<process>\w+) \((?P<count>-?\d+)\)\s*$")
_GLPK = re.compile(r"\bGLP_[A-Z]+\b")


def _model_relpath(path: str) -> str | None:
    """Model-relative path for a frame in MODEL code, or None for the interpreter and third-party libraries."""
    p = path.replace("\\", "/")
    if "site-packages/" in p or "dist-packages/" in p or re.search(r"/lib/python\d", p):
        return None
    if "/wcEcoli/" in p:
        return p.split("/wcEcoli/", 1)[1]
    root = os.environ.get("WCECOLI_DIR", "").replace("\\", "/").rstrip("/")
    if root and p.startswith(root + "/"):
        return p[len(root) + 1:]
    return None


def _tracebacks(text: str) -> list[tuple[int, int, list[dict], str, str, list[str]]]:
    """Every traceback block: (start, end, frames, exc_type, message, lines after the exception line)."""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        if lines[i].strip() != _TB:
            i += 1
            continue
        start, frames, j = i, [], i + 1
        while j < len(lines) and (lines[j].startswith(" ") or not lines[j].strip()):
            m = _FRAME.match(lines[j])
            if m:
                frames.append({"path": m["path"], "line": int(m["line"]), "func": m["func"]})
            j += 1
        if j >= len(lines):
            break
        m = _EXC.match(lines[j].strip())
        etype = m["type"] if m else lines[j].strip()
        msg = (m["msg"] or "") if m else ""
        out.append((start, j, frames, etype, msg, lines[j + 1:j + 21]))
        i = j + 1
    return out


def _root_block(text: str):
    """The block that names the ROOT failure. Normally the last traceback; when the last one is a re-raise
    ("During handling of the above exception..."), walk back to the exception that started the chain."""
    blocks = _tracebacks(text)
    if not blocks:
        return None
    lines = text.splitlines()
    k = len(blocks) - 1
    while k > 0:
        between = "\n".join(lines[blocks[k - 1][1] + 1:blocks[k][0]])
        if any(c in between for c in _CHAINED):
            k -= 1
        else:
            break
    return blocks[k]


def identify(*, log_text: str | None = None, note: str | None = None, run_root=None) -> Identity:
    """The identity of a failure, from the run's log first and the row's note second.

    Refusals are read from the note FIRST: they happen before the model starts, so any log in that run root
    belongs to an EARLIER attempt and would attribute its failure to this one."""
    n = note or ""
    if "Refusing out-of-envelope design" in n:
        return Identity("refused:envelope", "note", message=n[:240])
    if "Refusing to run:" in n:
        return Identity("refused:overwrite_guard", "note", message=n[:240])
    text = log_text if log_text is not None else read_log(run_root)
    if text is None:
        return Identity("no_log", "none")
    blk = _root_block(text)
    if blk is None:
        m = re.search(re.escape(EXIT_MARK) + r" (-?\d+)", text)
        if m and int(m.group(1)) != 0:
            return Identity(f"exit:{int(m.group(1))}", "log")
        mk = re.search(re.escape(MARKER_MARK) + r" (.+)", text)
        if mk:
            return Identity(f"marker:{mk.group(1).strip()}", "log")
        return Identity("no_traceback", "log")
    _, _, frames, etype, msg, after = blk
    short = etype.rsplit(".", 1)[-1]
    model = [(f, rel) for f in frames if (rel := _model_relpath(f["path"]))]
    where, line = (f"{model[-1][1]}:{model[-1][0]['func']}", model[-1][0]["line"]) if model else (None, None)
    detail: dict = {}
    if short == "NegativeCountsError":
        ran = [m.groupdict() for ln in after if (m := _RAN_OUT.match(ln.strip()))]
        if ran:
            detail["ran_out"] = [{**r, "count": int(r["count"])} for r in ran]
    g = _GLPK.search(msg)
    if g:
        detail["glpk"] = g.group(0)
    key = f"{short}@{where}" if where else f"{short}@<no model frame>"
    return Identity(key, "log", exc_type=short, where=where, line=line, message=msg[:400], detail=detail)


# --------------------------------------------------------------------------------------------- the loop

_PROGRESS_HEAD = re.compile(r"^\s*Time \(s\)\s+Dry mass")
_PROGRESS_ROW = re.compile(r"^\s*(-?\d+\.\d+)" + r"\s+(-?\d+\.\d+)" * 6 + r"\s*$")


def pre_failure_state(log_text: str | None) -> dict:
    """The cell just before it failed, from the model's own progress table — no simulation, no simOut read.

    Columns: time, dry mass, then fold changes of dry mass / protein / RNA / small molecules, and the EXPECTED
    dry-mass fold change. `growth_vs_expected` is dry-mass fold over expected: a cell on track sits near 1, a
    cell that has stopped growing falls far below it. The 0.5 cut-off for `stalled` is a reading aid, stated
    as such, not a calibrated threshold."""
    if not log_text:
        return {"available": False, "why": "no log"}
    lines = log_text.splitlines()
    tb = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == _TB), len(lines))
    if not any(_PROGRESS_HEAD.match(ln) for ln in lines[:tb]):
        return {"available": False, "why": "no progress table before the failure"}
    rows = [m for ln in lines[:tb] if (m := _PROGRESS_ROW.match(ln))]
    if not rows:
        return {"available": False, "why": "progress table has no rows before the failure"}
    v = [float(x) for x in rows[-1].groups()]
    ratio = v[2] / v[6] if v[6] else None
    return {"available": True, "time_s": v[0], "dry_mass_fg": v[1], "dry_mass_fold": v[2],
            "expected_fold": v[6], "growth_vs_expected": round(ratio, 3) if ratio is not None else None,
            "stalled": (ratio < 0.5) if ratio is not None else None}


def _resolve(simout_path: str | None) -> Path | None:
    if not simout_path:
        return None
    p = Path(simout_path)
    return p if p.is_absolute() else Path.cwd() / p


def control_outcome(design, rows: list[dict]) -> dict:
    """Did the UNMODIFIED cell fail under the same condition? Looked up in the corpus, never simulated here.

    Same condition, same timeline, same elongation model. If the control fails too, the condition is the
    problem; if it does not, the failure is specific to the perturbation. Absent from the corpus is reported
    as absent — it is not evidence either way."""
    if design.perturbation == "wildtype":
        return {"is_control": True}
    ctrl = [r for r in rows if r.get("perturbation") == "wildtype"
            and r.get("condition") == design.condition and r.get("timeline") == design.timeline
            and (r.get("elongation_model") or "steady_state") == design.elongation_model]
    if not ctrl:
        return {"in_corpus": False, "note": "no unmodified control under this condition in the corpus"}
    crashed = [r for r in ctrl if r.get("crashed")]
    return {"in_corpus": True, "n": len(ctrl), "n_crashed": len(crashed),
            "qc": sorted({str(r.get("qc")) for r in ctrl}),
            "identities": sorted({identify(note=r.get("note"), run_root=_resolve(r.get("simout_path"))).key
                                  for r in crashed})}


def sibling_identities(design, seed: int, rows: list[dict]) -> list[dict]:
    """How the design's OTHER seeds ended. One seed failing alone and all seeds failing identically are
    different findings, and the corpus already knows which this is."""
    from . import manifest, survey
    mine = survey.design_key({"perturbation": design.perturbation, "label": manifest._label(design, seed)})
    out = []
    for r in rows:
        if r.get("seed") == seed or survey.design_key(r) != mine:
            continue
        ident = identify(note=r.get("note"), run_root=_resolve(r.get("simout_path"))) if r.get("crashed") else None
        out.append({"seed": r.get("seed"), "crashed": bool(r.get("crashed")), "qc": r.get("qc"),
                    "identity": ident.key if ident else None})
    return sorted(out, key=lambda x: (x["seed"] is None, x["seed"]))


def triage_dir() -> Path:
    """Outside the run tree on purpose: every scanner finds runs by globbing for simOut under runs/<sim_path>,
    and a repeat kept there would be indexed as a run. `runs_*/` is already gitignored."""
    from .runner import OUT_ROOT
    return Path(os.environ.get("CELLARIUM_TRIAGE") or (OUT_ROOT.parent / "runs_triage"))


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:120]


def repeat_once(design, seed: int, generations: int, sim_path: str, original: Identity, *, run_one=None) -> dict:
    """Run the same design and seed once more and compare identities. ONE simulation, deliberately spent.

    The model is deterministic per seed, so a model fault should recur with the same identity; one that does
    not recur points at the host. The original run root is moved aside BEFORE the repeat and restored after
    it, so the evidence being triaged is never overwritten — and the repeat is kept beside the triage record,
    outside the run tree, where no scanner will index it."""
    from . import runner
    run_one = run_one or runner.run_one
    run_root = runner._run_subpath(design, seed, sim_path)
    dest = triage_dir() / "repeats" / f"{_slug(run_root.parent.name)}__{run_root.name}__{time.strftime('%Y%m%dT%H%M%S')}"
    dest.mkdir(parents=True, exist_ok=False)
    aside = dest / "original"
    moved = False
    if run_root.exists():
        os.replace(run_root, aside)
        moved = True
    outcome, err = "completed", None
    try:
        try:
            run_one(design, seed, generations, sim_path=sim_path)
        except Exception as exc:          # the repeat failing is the expected outcome, not an error here
            outcome, err = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
        again = identify(note=err, run_root=run_root)
    finally:
        if run_root.exists():
            os.replace(run_root, dest / "repeat")
        if moved:
            os.replace(aside, run_root)
    same = outcome == "failed" and again.key == original.key
    return {"ran": True, "outcome": outcome, "identity": again.key, "same_identity": same,
            "reading": ("reproduced: same identity on the same seed — a model fault, deterministic"
                        if same else
                        "NOT reproduced on the same seed — suspect the host or a nondeterministic path"),
            "kept_at": str(dest / "repeat")}


def triage(identity: Identity, design, seed: int, run_root, *, rows: list[dict] | None = None) -> dict:
    """The immediate checks on a first sighting — everything that needs no simulation. The repeat is added
    by the caller, because only the caller knows whether it is authorised to spend one."""
    if rows is None:
        from . import hygiene
        rows = hygiene.rows("audit")[0]
    from . import manifest
    text = read_log(run_root)
    return {"identity": identity.as_dict(), "design": manifest._label(design, seed), "seed": seed,
            "run_root": str(run_root) if run_root else None,
            "pre_failure": pre_failure_state(text),
            "control": control_outcome(design, rows),
            "siblings": sibling_identities(design, seed, rows),
            "repeat": {"ran": False, "why": "pending"},
            "drafted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "unnamed — name it in failures.KNOWN with the log that defined it, and add that "
                      "traceback as a test fixture"}


def write_triage(record: dict) -> Path:
    d = triage_dir() / _slug(record["identity"]["key"])
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{_slug(record['design'])}.json"
    p.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return p


def after_campaign(crashes: list[tuple], generations: int, sim_path: str, *, repeat: bool,
                   rows: list[dict] | None = None, run_one=None) -> dict:
    """Identify every failure of a campaign and run the first-sighting loop on each unnamed identity.

    Called AFTER the shard is written, so nothing here can lose a completed run. Repeats run serially at
    this point, after every job has finished, so the loop never pushes concurrency past the campaign's own
    parallel setting (the Docker bind mount fails above 6). `repeat=False` is the default for any path where
    a person approved a specific simulation — an extra one they did not approve is not the loop's to spend."""
    from . import manifest
    by_key: dict[str, list] = {}
    for design, seed, row in crashes:
        ident = identify(note=row.get("note"), run_root=_resolve(row.get("simout_path")))
        by_key.setdefault(ident.key, []).append((design, seed, row, ident))
    records = {}
    for key, hits in by_key.items():
        design, seed, row, ident = hits[0]
        if ident.named:                    # includes no_log / no_traceback: nothing there to triage
            continue
        run_root = _resolve(row.get("simout_path"))
        rec = triage(ident, design, seed, run_root, rows=rows)
        if repeat:
            try:
                rec["repeat"] = repeat_once(design, seed, generations, sim_path, ident, run_one=run_one)
            except Exception as exc:
                rec["repeat"] = {"ran": False, "why": f"repeat could not run: {type(exc).__name__}: {exc}"}
        else:
            rec["repeat"] = {"ran": False, "why": "not authorised on this path (repeat=False)"}
        rec["also_seen_in"] = [manifest._label(d, s) for d, s, _, _ in hits[1:]]
        records[key] = str(write_triage(rec))
    summary = {k: {"n": len(v), "name": v[0][3].signature.name if v[0][3].named else None,
                   "category": v[0][3].signature.category if v[0][3].named else None}
               for k, v in by_key.items()}
    unnamed_keys = sorted(records)
    return {"failures": summary, "unnamed": unnamed_keys, "triage_records": records}


def render_summary(s: dict) -> str:
    if not s["failures"]:
        return "No failures."
    lines = ["Failures by identity:"]
    for k, v in sorted(s["failures"].items(), key=lambda kv: -kv[1]["n"]):
        label = f"{v['name']} [{v['category']}]" if v["name"] else "UNNAMED"
        lines.append(f"  {v['n']:>3}  {label}  — {k}")
    if s["unnamed"]:
        lines.append(f"{len(s['unnamed'])} unnamed identit{'y' if len(s['unnamed']) == 1 else 'ies'} — triage "
                     f"records written; this corpus cannot be published until each is named:")
        lines += [f"  {k}\n    -> {s['triage_records'][k]}" for k in s["unnamed"]]
    return "\n".join(lines)


def unnamed(rows: list[dict]) -> list[dict]:
    """Crashed rows whose failure has an identity nobody has named — what a publication path refuses on.
    `no_log` is not here: an absence of evidence is named as such and cannot be triaged."""
    out = []
    for r in rows:
        if not r.get("crashed"):
            continue
        ident = identify(note=r.get("note"), run_root=_resolve(r.get("simout_path")))
        if not ident.named:
            out.append({"label": r.get("label"), "key": ident.key, "simout_path": r.get("simout_path")})
    return out
