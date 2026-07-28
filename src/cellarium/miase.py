"""SCI-QC-1 — declared-vs-executed experiment check (MIASE).

A design DECLARES an experiment (`timeline = "0 minimal, 1200 minimal_plus_amino_acids"` — start in minimal,
switch to minimal+amino-acids at t=1200 s). The simulation then EXECUTES something. **MIASE** (Waltemath et al.
2011, PLoS Comput Biol 7(4):e1001122) requires those to correspond: a published simulation experiment must be
described such that it can be reproduced, which is impossible if the description and the run disagree.

This is not hypothetical here, and what it found is instructive. The corpus's amino-acid UPSHIFT design declares
two media events, but `FBAResults/media_id` shows `minimal` for all 2,574 timesteps, while the DOWNSHIFT records
its switch at exactly t=1200. The obvious reading — "the upshift never ran" — is **WRONG**, and this module was
briefly written on that assumption. A re-run settled it: wcEcoli's own log prints `update media:
minimal_plus_amino_acids`. The shift happened.

The real cause is a RECORDING defect, and it is upstream. `media_id` is a fixed-width string column whose width
is set by the FIRST value written. The upshift starts in `minimal` (7 chars) → the column is `<U7` → the later
`minimal_plus_amino_acids` (24 chars) is silently truncated to 7 characters. And
`'minimal_plus_amino_acids'[:7] == 'minimal'`, so the truncated value is byte-identical to the starting medium:
the shift becomes invisible in the record. The downshift starts with the 24-char name, so its column is `<U24`
and nothing truncates — which is exactly why only one direction looks broken. (Verified: the two columns' dtypes
really are `<U7` and `<U24`.)

The consequence is narrower than "the experiment is void" but still real: the RUN is usable, the media LABELS
are not, and every per-segment mean for that design averages pre- and post-shift timesteps together.

The check is deliberately narrow and deterministic: compare the media events a design DECLARES against the media
the reader recovered. It answers "does the record match the declaration" — and, crucially, distinguishes a bad
RECORD from a bad EXPERIMENT, because conflating them condemns usable data and misattributes an upstream bug.

Scope note: `media_segments` is recorded for the LAST generation only (`_reader_worker.mode_run` reads
`_dynamics(gs[-1])`), so a shift scheduled inside an earlier generation is legitimately invisible to this check
on a multi-generation run. Such rows are reported as `undetermined` rather than as violations — flagging them
would train the reader to ignore the check, which is worse than a smaller check that is always right.
"""

from __future__ import annotations

import json
from collections import defaultdict

from . import manifest, survey


def _as_list(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return v or []


def declared_events(timeline: str | None) -> list[tuple[float, str]]:
    """Parse a declared timeline into (time, media) events, mirroring wcEcoli's own parser
    (`wholecell/utils/make_media.py::make_timeline`, which splits on ', ' then on whitespace). Kept identical on
    purpose: if we parsed more leniently than the model does, we would 'verify' a declaration the model never
    understood."""
    out: list[tuple[float, str]] = []
    for ev in str(timeline or "").split(", "):
        parts = ev.split()
        if len(parts) == 2:
            try:
                out.append((float(parts[0]), parts[1]))
            except ValueError:
                continue
    return out


def _rows() -> list[dict]:
    import duckdb
    con = duckdb.connect()
    cols = ("id, label, perturbation, condition, timeline, media_segments, reportable, generations, simout_path")
    q = (f"SELECT {cols} FROM read_parquet('{survey.MANIFEST_GLOB}', union_by_name=true) "
         f"{manifest.DEDUP_QUALIFY}")
    try:
        return survey._mark_dropped(con.execute(q).fetch_arrow_table().to_pylist())
    except Exception as exc:
        return [{"__error__": str(exc)}]
    finally:
        con.close()


def _truncation_signature(want: list[str], got: list[str]) -> str | None:
    """Is the mismatch explained by the recorder TRUNCATING a media name rather than by the shift not happening?

    wcEcoli writes `FBAResults/media_id` as a FIXED-WIDTH string column whose width is set by the FIRST value.
    A run that starts in `minimal` gets a `<U7` column; when the media later becomes `minimal_plus_amino_acids`
    (24 chars) numpy silently truncates it to 7 characters — and `'minimal_plus_amino_acids'[:7] == 'minimal'`,
    so the truncated value is INDISTINGUISHABLE from the starting medium. The reader then sees one unbroken
    segment and the shift vanishes from the record.

    Verified on this corpus: the upshift's column is `<U7` and the downshift's is `<U24` (it starts with the long
    name, so everything fits). The upshift's own run log contains `update media: minimal_plus_amino_acids` — the
    shift DID occur. Returns a human-readable explanation when the signature matches, else None."""
    if not want or not got:
        return None
    first = got[0]
    w = len(first)
    # every declared medium truncates to the same recorded string => the record cannot distinguish them
    if len(set(got)) == 1 and len(set(m[:w] for m in want)) == 1 and any(len(m) > w for m in want):
        longer = [m for m in want if len(m) > w]
        return (f"RECORDER TRUNCATION, not a missing shift: `media_id` is a fixed-width string column sized from "
                f"the first value (`{first}`, {w} chars), so {longer!r} is cut to {w} chars — which spells "
                f"`{longer[0][:w]}`, identical to the starting medium. The shift may well have occurred; the "
                f"RECORD cannot show it. Check the run log for wcEcoli's own `update media:` line.")
    return None


def check_run(row: dict) -> dict:
    """Declared vs RECORDED for ONE run. Verdicts:
      `ok`             — declared media sequence matches the recorded one
      `recorder_truncation` — they disagree, but the disagreement is fully explained by the fixed-width-column
                         truncation above: the experiment likely RAN and the record is what is wrong
      `violation`      — they disagree, single-generation, and truncation does NOT explain it
      `undetermined`   — multi-generation: media_segments covers only the last generation, so an earlier shift
                         can be neither confirmed nor refuted from the manifest alone
      `not_applicable` — no declared timeline (a static-media design legitimately has one segment)

    The `recorder_truncation` verdict exists because the first version of this check reported the upshift as
    "the experiment was not performed", which was WRONG — the model logged the switch. Conflating a bad record
    with a bad experiment would have condemned usable data (and mis-reported an upstream bug as ours).
    """
    declared = declared_events(row.get("timeline"))
    segs = _as_list(row.get("media_segments"))
    exec_media = [s.get("media") for s in segs if isinstance(s, dict)]
    if not declared:
        return {"verdict": "not_applicable", "declared": [], "executed": exec_media}
    want = [m for _, m in declared]
    gens = row.get("generations") or 0
    base = {"declared": want, "executed": exec_media, "declared_events": len(want),
            "executed_segments": len(exec_media)}
    if want == exec_media:
        return {"verdict": "ok", **base}
    trunc = _truncation_signature(want, exec_media)
    if trunc:
        return {"verdict": "recorder_truncation", **base, "note": trunc}
    if gens and gens > 1:
        return {"verdict": "undetermined", **base,
                "note": (f"the run spans {gens} generations but `media_segments` covers only the LAST one, so an "
                         f"earlier shift is invisible here — inconclusive, not a violation")}
    return {"verdict": "violation", **base,
            "note": ("single-generation run, and truncation does not explain the mismatch: the whole declared "
                     "timeline had to occur inside the recorded window, so the run did NOT perform the declared "
                     "experiment")}


def check_corpus() -> dict:
    """MIASE check across the corpus. Returns violations grouped by design + a corpus verdict.

    `ok=False` means at least one run is REPORTABLE while provably not having executed its declared experiment —
    the case that must never reach a dataset or a figure."""
    rows = _rows()
    if rows and "__error__" in rows[0]:
        return {"error": rows[0]["__error__"], "ok": False}
    by_design: dict = defaultdict(lambda: {"violation": 0, "ok": 0, "undetermined": 0,
                                           "recorder_truncation": 0, "examples": []})
    n_checked = 0
    for r in rows:
        if r.get("_dropped"):
            continue
        res = check_run(r)
        if res["verdict"] == "not_applicable":
            continue
        n_checked += 1
        d = by_design[survey.design_key(r)]
        d[res["verdict"]] += 1
        if res["verdict"] in ("violation", "recorder_truncation") and len(d["examples"]) < 3:
            d["examples"].append({"id": r.get("id"), "reportable": bool(r.get("reportable")),
                                  "verdict": res["verdict"], "declared": res["declared"],
                                  "executed": res["executed"], "note": res.get("note", ""),
                                  "simout_path": r.get("simout_path")})
    violations = {k: v for k, v in by_design.items() if v["violation"]}
    truncated = {k: v for k, v in by_design.items() if v["recorder_truncation"]}
    # A violation on a NON-reportable run is already excluded from analysis; the blocking case is a violation
    # that is still marked reportable, because that row feeds figures and the dataset.
    blocking = {k: v for k, v in violations.items() if any(e["reportable"] for e in v["examples"])}
    return {
        "ok": not blocking, "n_runs_checked": n_checked,
        "n_designs_with_violations": len(violations), "n_designs_blocking": len(blocking),
        "n_designs_recorder_truncation": len(truncated),
        "recorder_truncation": {k: dict(v) for k, v in sorted(truncated.items())},
        "violations": {k: dict(v) for k, v in sorted(violations.items())},
        "summary": {k: dict(v) for k, v in sorted(by_design.items())},
        "standard": "MIASE (Waltemath et al. 2011, PLoS Comput Biol 7(4):e1001122, PMID 21552546)",
        "note": ("Declared-vs-executed check: does each run's `timeline` declaration match the media the model "
                 "actually recorded (`FBAResults/media_id` -> `media_segments`)? A `violation` on a REPORTABLE "
                 "run is publication-blocking: the corpus would be advertising an experiment that was not "
                 "performed. `recorder_truncation` = the mismatch is explained by wcEcoli's fixed-width "
                 "`media_id` column silently cutting a long medium name to the width of the first one (the "
                 "upshift case): the experiment likely RAN and the RECORD is wrong — usable data, unusable "
                 "media labels, and an upstream bug to report. `undetermined` = multi-generation run whose "
                 "earlier generations are not covered by the recorded segments — inconclusive by construction."),
    }
