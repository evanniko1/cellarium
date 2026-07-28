"""Deterministic guard against SILENT SERIALIZATION LOSS in simOut — generalised from a real, found bug.

The bug that motivated this: wcEcoli writes `FBAResults/media_id` as a NumPy fixed-width unicode column whose
width is fixed by the FIRST value written. A nutrient-upshift run starts in `minimal` (7 chars, dtype `<U7`), so
when the medium later becomes `minimal_plus_amino_acids` (24 chars) it is silently truncated to 7 characters —
and `'minimal_plus_amino_acids'[:7] == 'minimal'`, byte-identical to the starting medium. The media shift
vanished from the record while the simulation performed it correctly. Nothing raised, nothing warned, and the
corpus reported a nutrient-shift experiment whose shift was invisible.

That is a CLASS of failure, not one column. Any fixed-width string column can lose data the same way, in any
variant we run — a condition name, a media id, a molecule label. The loss is invisible by construction, which is
exactly why it needs a mechanical detector rather than an attentive reader.

**The detection is deterministic and needs no knowledge of what SHOULD have been written.** For a `<UN` column,
any recorded value of length exactly N is SATURATED: it either exactly fits or was cut, and the two are
indistinguishable *within that run*.

The discriminator is CROSS-RUN width comparison, and it is what makes this a real detector rather than a
warning. The same listener column is written by every run, but its width is set per-run by that run's first
value. So if `FBAResults/media_id` is `<U24` in one run and `<U7` in another, we have proof from our own data
that the column legitimately carries 24-character values — and the `<U7` run therefore truncated anything
longer. No external expectation is needed: the corpus convicts itself.

A first version of this module scored severity by "does the column CHANGE during the run", which is exactly
backwards for this bug: truncation collapses the post-shift value into the pre-shift one, so the broken run
looks CONSTANT while the healthy run looks variable. That heuristic would have cleared the one run it exists to
catch. The cross-run width rule has no such inversion.

Findings are filed to BACKLOG.md class X through the same dev-gated, idempotent machinery the Council
self-harness uses (`harness.write_gaps`), so a serialization defect surfaces where a developer already looks
instead of in a log nobody reads.
"""

from __future__ import annotations

import hashlib
import os
import re
import struct
from dataclasses import dataclass, field

# `<U24` / `>U7` / `|S12` — the fixed-width string dtypes numpy silently truncates into.
_STR_DTYPE = re.compile(rb'[<>|]([US])(\d+)')


@dataclass
class SerializationFinding:
    listener: str
    column: str
    dtype: str
    width: int
    n_saturated: int
    n_rows: int
    distinct_values: int
    changes_during_run: bool
    example: str = ""
    run: str = ""
    severity: str = "warn"          # "warn" (saturated, constant) | "high" (saturated AND changing)
    detail: str = field(default="")

    @property
    def gap_id(self) -> str:
        # keyed on the COLUMN, not the run — the same defect in a hundred runs is one thing to fix.
        sig = f"serialization|{self.listener}|{self.column}|{self.width}"
        return "GAP-" + hashlib.sha1(sig.encode()).hexdigest()[:8]


def _column_dtype(path: str) -> tuple[str, int] | None:
    """(dtype_string, width) for a fixed-width string column, else None. Reads only the COLM header — no data."""
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"COLM":
                return None
            (size,) = struct.unpack(">I", f.read(4))
            head = f.read(min(size, 512))
    except Exception:
        return None
    m = _STR_DTYPE.search(head)
    if not m:
        return None
    return m.group(0).decode("ascii", "replace"), int(m.group(2))


def scan_run(seed_root: str, max_columns: int = 400) -> list[SerializationFinding]:
    """Every fixed-width string column in a run whose values SATURATE its width — i.e. may be silently truncated.

    Deterministic and local: reads the run's own columns, compares nothing to an external expectation."""
    import numpy as np

    from . import raw
    out: list[SerializationFinding] = []
    sos = raw.simout_dirs(seed_root)
    if not sos:
        return out
    so = sos[-1]
    seen = 0
    for listener in sorted(os.listdir(so)):
        ldir = os.path.join(so, listener)
        if not os.path.isdir(ldir):
            continue
        for col in sorted(os.listdir(ldir)):
            if col == "attributes.json":
                continue
            path = os.path.join(ldir, col)
            if not os.path.isfile(path):
                continue
            seen += 1
            if seen > max_columns:
                return out
            dt = _column_dtype(path)
            if not dt:
                continue
            dtype, width = dt
            try:
                vals = [str(x) for x in np.asarray(raw.read_column(path)).ravel()]
            except Exception:
                continue
            if not vals:
                continue
            sat = [v for v in vals if len(v) >= width]
            if not sat:
                continue
            distinct = sorted(set(vals))
            changes = len(distinct) > 1
            # Severity is assigned by scan_corpus, which alone can compare this run's width against the SAME
            # column in other runs — the only deterministic evidence of truncation available without an
            # external expectation.
            out.append(SerializationFinding(
                listener=listener, column=col, dtype=dtype, width=width,
                n_saturated=len(sat), n_rows=len(vals), distinct_values=len(distinct),
                changes_during_run=changes, example=sat[0][:60], run=seed_root, severity="warn",
                detail=f"{len(sat)}/{len(vals)} values fill the {width}-char width exactly"))
    return out


def scan_corpus(limit_runs: int = 40) -> dict:
    """Scan local runs for saturated string columns. Returns findings grouped by column (the unit of repair).

    Deliberately bounded: this is a guard meant to run often, not an exhaustive audit."""
    from . import raw, store, survey
    rows = survey._deduped_rows(survey.CHANNELS + ["simout_path"]) if True else []
    roots, seen_roots = [], set()
    for r in rows:
        p = store._resolve_run(r.get("simout_path"))
        if p and os.path.isdir(p) and p not in seen_roots and raw.simout_dirs(p):
            seen_roots.add(p)
            roots.append((survey.design_key(r), p))
        if len(roots) >= limit_runs:
            break
    # collect per (column, run) so widths can be compared ACROSS runs — the deterministic truncation evidence
    per_col: dict = {}
    for design, root in roots:
        for f in scan_run(root):
            key = f"{f.listener}/{f.column}"
            per_col.setdefault(key, []).append((design, f))

    by_col: dict = {}
    for key, entries in per_col.items():
        widths = {f.width for _d, f in entries}
        wmax = max(widths)
        # A column written at DIFFERENT widths in different runs, where the narrow runs saturate, is
        # STRUCTURALLY PRONE to silent truncation: the writer sizes per-run from the first value, so any run
        # whose later values are longer loses them.
        #
        # This flags the COLUMN, not the runs. An earlier version accused every narrow run of "provably losing
        # characters" — wrong: a static run in `minimal` has a 7-char medium and a <U7 column, which is exactly
        # right for its content. Saturation plus narrowness proves the column is FRAGILE, never that a
        # particular run lost data. Confirming an individual loss needs an external expectation (what the run
        # DECLARED), which is `miase.check_corpus`'s job — it confirmed exactly one case, the upshift.
        narrow = [(d, f) for d, f in entries if f.width < wmax and f.n_saturated]
        f0 = entries[0][1]
        e = {"listener": f0.listener, "column": f0.column, "gap_id": f0.gap_id,
             "widths_seen": sorted(widths), "max_width": wmax,
             "designs": sorted({d for d, _f in entries}), "n_runs": len(entries),
             "severity": "high" if narrow else "warn",
             "example": f0.example}
        if narrow:
            e["at_risk_runs"] = [{"design": d, "width": f.width, "run": f.run,
                                  "saturated": f"{f.n_saturated}/{f.n_rows}"} for d, f in narrow[:5]]
            e["detail"] = (f"TRUNCATION-PRONE COLUMN: written at widths {sorted(widths)} across runs (the "
                           f"writer sizes it per-run from the first value), and {len(narrow)} run(s) saturate a "
                           f"width below the {wmax} this column is known to carry. Any such run whose value "
                           f"LATER grew past its own width lost the excess silently. This flags the COLUMN as "
                           f"fragile — it does NOT mean each listed run lost data (a run whose medium is "
                           f"genuinely short is correctly narrow). Confirm an individual loss against what the "
                           f"run DECLARED (see miase.check_corpus, which confirmed the amino-acid upshift).")
        else:
            e["detail"] = (f"all runs declare the same width (<U{wmax}) and some values saturate it — possible "
                           f"truncation, but no run in this corpus proves a longer value exists, so this is a "
                           f"risk flag rather than evidence of loss.")
        by_col[key] = e
    high = {k: v for k, v in by_col.items() if v["severity"] == "high"}
    return {
        "n_runs_scanned": len(roots), "n_columns_flagged": len(by_col), "n_high": len(high),
        "high": high, "all": by_col,
        "ok": not high,
        "note": ("Fixed-width string columns whose values SATURATE their declared width. NumPy truncates silently, "
                 "so a saturated value either exactly fits or lost characters — indistinguishable afterwards. "
                 "`high` = the column is written at DIFFERENT widths across runs and narrow runs saturate, so "
                 "the COLUMN is structurally prone to silent truncation — the failure mode confirmed for "
                 "FBAResults/media_id, where the upshift's 'minimal_plus_amino_acids' truncated to exactly "
                 "'minimal'. It flags the column, NOT each run: a run whose value is genuinely short is "
                 "correctly narrow. Confirm a specific loss with miase.check_corpus, which compares against what "
                 "the run DECLARED. `warn` = saturated but all runs agree on the width."),
    }


def scan_and_file(limit_runs: int = 40, backlog_path=None, today: str | None = None) -> dict:
    """Scan, then file HIGH findings to BACKLOG.md class X via the same idempotent, dev-gated machinery the
    Council self-harness uses — so a serialization defect lands where a developer already looks.

    Only `high` findings are filed. A saturated-but-constant column is recorded in the scan result but is not
    worth a backlog row: filing every one would bury the signal, which is how a guard stops being read."""
    from . import harness
    res = scan_corpus(limit_runs=limit_runs)
    records = []
    for key, f in sorted(res.get("high", {}).items()):
        records.append(harness.GapRecord(
            test_id=f"serialization:{key}", family="serialization", kind="silent_truncation",
            matched=f"widths {f['widths_seen']}", hyp_id="", rule="",
            question=(f"TRUNCATION-PRONE column {key}: written at widths {f['widths_seen']} across runs "
                      f"(sized per-run from the first value), with {len(f.get('at_risk_runs') or [])} run(s) "
                      f"saturating a width below the {f['max_width']} it is known to carry. A run whose value "
                      f"grows past its own width loses the excess SILENTLY — confirmed once for "
                      f"FBAResults/media_id, where 'minimal_plus_amino_acids' truncated to exactly 'minimal' and "
                      f"a nutrient shift vanished from the record. Report upstream to CovertLab; confirm "
                      f"individual runs via miase.check_corpus.")))
    filed = {}
    if records:
        kw = {} if backlog_path is None else {"backlog_path": backlog_path}
        if today:
            kw["today"] = today
        filed = harness.write_gaps(records, **kw)
    return {**res, "n_filed": len(records), "filed": filed,
            "note_filing": ("HIGH findings are filed to BACKLOG class X (idempotent, dedup'd by column). "
                            "Saturated-but-constant columns are reported here but NOT filed — filing every one "
                            "would bury the signal.")}
