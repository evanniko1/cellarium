"""Write data/parca/fits.json: the ParCa fits (knowledge bases) available, one record per kb_sha256, each with how it
was built, from what inputs, why, and how many corpus rows ran on it.

A run's manifest row carries `kb_sha256`, so every run joins to its fit here; `kb_sha256` is also an arm key, so rows
on different fits are never pooled (docs/CORPUS_ARMS.md). Hashes are MEASURED from the files on this machine; the
hand-recorded facts in KNOWN (basis, purpose, decision, inputs) attach by hash prefix and never override a measured
hash. A fit seen only in the manifest is listed with `file_on_this_machine: false`; a fit with no hand record says
"not recorded" rather than guessing.

    python scripts/parca_fits.py           # reads runs/*/kb/simData.cPickle and data/manifest
"""
from __future__ import annotations

import collections
import hashlib
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "parca" / "fits.json"
RUNS = REPO / "runs"

IMAGE = "${USER}-wcm-code:latest"
KNOWN = {
    "3b2f8ebd": {
        "basis": "the code image's default ParCa (operons on); the knowledge base of most of the corpus",
        "built": "2026-07-08 (parca_ts)", "decided_by": "the campaign's first corpus build"},
    "0d861f80": {
        "basis": "not recorded: a second knowledge base mixed into wildtype/basal and condition/with_aa, seen in the "
                 "corpus from 2026-07-29 with no parca_ts (docs/DECISIONS.md I2); the file is not on this machine"},
    "5f19d040": {
        "basis": "built 2026-08-06 (parca_ts), reconstruction_sha 14c6d826; carries steady-state and kinetic rows; "
                 "the file is not on this machine"},
    "e491a580": {
        "basis": "refit1, PARCA-3: the default fit with G0-10634_RNA retyped from mRNA to pseudo (BACKLOG PARCA-3)",
        "built": "2026-08-08"},
    "4965d619": {
        "basis": "refit2, PARCA-3: the default fit with the coverage filter (BACKLOG PARCA-3)", "built": "2026-08-09"},
    "9055ee3b": {
        "basis": "BV-14 refit: the code image's flat tree with two files overridden (runner.parca_rebuild "
                 "flat_overrides, which mounts only the named files)",
        "image": IMAGE, "built": "2026-11-25, 9.8 min", "purpose": "BV-14: anaerobic nitrate respiration "
                                                                   "against PRECISE-1K (Platform Map M.6)",
        "decided_by": "the user, 2026-11-25 (BV-12 to BV-14: 'Run them on this machine, 6 in parallel')",
        "flat_overrides": {
            "condition/condition_defs.tsv": "6985c6a8af2e29989a448203fb8f85f2a9ce7094b6279e402d0bc8152e1afa96",
            "condition/media_recipes.tsv": "fcc6ae551335c8a68b83c753d3fec14af1a84a689369b8ebc0cdbe01a68f7935"},
        "overrides_from": "model_overlay/files/reconstruction/ecoli/flat/condition/ (identical to the campaign "
                          "checkout's working tree)",
        "conditions_added": ["no_oxygen_plus_nitrate"],
        "conditions_added_against": "the code image's own condition_defs.tsv (24 rows; the override has 25)",
        "against_the_corpus_fit": ("the corpus fit 3b2f8ebd has 21 ordered conditions (read from its pickle, "
                                   "2026-11-25); this fit has 25, the same 21 at indices 0-20, then minus_leu, "
                                   "minus_thr, minus_arg (from the image's own table) and no_oxygen_plus_nitrate "
                                   "at 24. It was built from the current image, so anything else that image "
                                   "changed since July is in it too: its validity controls test that basal and "
                                   "anaerobic growth stay inside the corpus fit's range"),
        "condition_indices": {"basal": 0, "no_oxygen": 7, "plus_nitrate": 17, "no_oxygen_plus_nitrate": 24},
        "differs_from_public_branch": (
            "the public campaign branch at 8e7dd6c5 carries the same no_oxygen_plus_nitrate row and medium; its "
            "condition_defs.tsv also has plus_cytidine, added there by a commit the local checkout lacks, so it "
            "hashes 33b5e1dc..., not 6985c6a8..., and every condition index after plus_cytidine's position is one "
            "higher on the public branch. Runs on this fit compute their condition index by name from this fit's "
            "own table"),
        "doubling_time": "82 min, derived: PRECISE-1K no3_anaero 0.35/h against aerobic glucose 0.649/h, scaled to "
                         "the 44-min basal (data/parca/condition_fits.json)"},
}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_rows() -> list[dict]:
    import duckdb
    m = (REPO / "data" / "manifest").as_posix()
    return [{"kb_sha256": k, "elongation_model": e} for k, e in duckdb.connect().sql(
        f"SELECT kb_sha256, elongation_model FROM read_parquet('{m}/*.parquet', union_by_name=true)").fetchall()]


def build(runs_root: Path, rows: list[dict], known: dict) -> dict:
    on_disk = {}
    for kb in sorted(runs_root.glob("*/kb/simData.cPickle")):
        on_disk[_sha(kb)] = {"sim_path": kb.parent.parent.name, "kb_bytes": kb.stat().st_size,
                             "file_mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(kb.stat().st_mtime))}
    n = collections.Counter(r.get("kb_sha256") for r in rows if r.get("kb_sha256"))
    modes = collections.defaultdict(set)
    for r in rows:
        if r.get("kb_sha256"):
            modes[r["kb_sha256"]].add(r.get("elongation_model") or "unknown")
    fits = []
    for sha in sorted(set(on_disk) | set(n), key=lambda s: (-n.get(s, 0), s)):
        hand = next((v for k, v in known.items() if sha.startswith(k)), {})
        rec = {"basis": "not recorded", **{k: v for k, v in hand.items() if k != "kb_sha256"},
               "kb_sha256": sha, "sim_path": None, "file_on_this_machine": sha in on_disk,
               "manifest_rows": n.get(sha, 0), "elongation_models": sorted(modes.get(sha, ())),
               "deposited_to_hf": False}
        rec.update(on_disk.get(sha, {}))
        fits.append(rec)
    return {"spec": "the ParCa fits available, joined to runs by kb_sha256",
            "deposit_note": ("no knowledge base is on the Hugging Face corpus: a deposited run is re-readable for "
                             "its stored channels, but a read that needs the fit (the two-component sensor "
                             "correction, BV-R1) needs the fit on the reading machine; publishing fits is held for "
                             "the user (WAITING_ON_YOU)"),
            "fits": fits, "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def main() -> int:
    res = build(RUNS, _manifest_rows(), KNOWN)
    OUT.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    for f in res["fits"]:
        print(f"{f['kb_sha256'][:8]} {str(f['sim_path']):22s} rows {f['manifest_rows']:4d} "
              f"on_disk {f['file_on_this_machine']!s:5s} {f['basis'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
