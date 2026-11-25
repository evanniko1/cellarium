"""Write data/parca/condition_fits.json: for every condition in the knowledge base's table, what ParCa fits and who
decided to fit it.

ParCa builds a cell specification for EVERY row of condition_defs.tsv (fit_sim_data_1.
buildCombinedConditionCellSpecifications): composition is fitted to the row's doubling time, and the expression of
every target of the row's active and inactive transcription factors is set from their fitted fold changes. So for
a condition, growth and composition are in-sample, the fitted factors' targets are in-sample, and the rest is
emergent from that fitted state. What differs between conditions is the basis of the fit:

  fitted_by        "base" for rows the upstream simulator ships (CovertLab/wcEcoli master), "campaign" for rows the
                   campaign branch added, with the commit and date that introduced each row ("uncommitted" for rows
                   only in the working tree).
  doubling_basis   "base_model" for the upstream values; "placeholder" for a campaign value equal to another
                   condition's (copied, not measured); "derived" where a source is recorded below.

Upstream membership was checked against CovertLab/wcEcoli master with the GitHub compare API on 2026-11-25
(03b327f7 acetate/succinate: in upstream; 4bc5d952 glc_*: not; 65284c86 the 13 media conditions: not).

    python scripts/condition_fits.py --wcecoli C:/dev/wcEcoli
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "parca" / "condition_fits.json"
FLAT = "reconstruction/ecoli/flat"
UPSTREAM_COMMITS = {"03b327f7": True, "4bc5d952": False, "65284c86": False}   # GitHub compare API, 2026-11-25
DERIVED = {"no_oxygen_plus_nitrate": "PRECISE-1K no3_anaero growth 0.35/h against its aerobic glucose 0.649/h "
                                     "(Lamoureux et al. 2023), scaled to the model's 44-min basal: 82 min (BV-14)"}


def _rows(text: str) -> list[dict]:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    return list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter="\t"))


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=120).stdout.strip()


PUBLIC_REF = "origin/feature/wcecoli-platform"   # the public campaign branch (MohammedNagdi/wcEcoli)


def _introduced(root: Path, cond: str, public_ref: str | None = PUBLIC_REF) -> dict:
    """The commit that first added this row: on the checked-out branch, else on the public campaign branch (the local
    checkout can be behind it while carrying the same rows uncommitted); 'uncommitted' if on neither."""
    rel = f"{FLAT}/condition/condition_defs.tsv"
    for ref in ("HEAD", public_ref):
        if not ref or f'"{cond}"\t' not in _git(root, "show", f"{ref}:{rel}"):
            continue
        log = _git(root, "log", ref, "--reverse", "--abbrev=8", "--format=%h|%ad|%s", "--date=short",
                   f"-S\"{cond}\"\t", "--", rel)
        first = (log.splitlines() or ["?|?|?"])[0].split("|", 2)
        out = {"commit": first[0], "date": first[1], "subject": first[2], "on": ref}
        if ref != "HEAD":
            out["date_meaning"] = ("the date the row was committed on the public branch; the campaign checkout "
                                   "carried it uncommitted before that, from a date not recorded, so this is the "
                                   "latest date the decision to fit can have been taken")
        return out
    return {"commit": "uncommitted", "date": None, "on": None,
            "subject": "only in the campaign checkout's working tree; the date it was added is not recorded"}


# Knowledge-base ids written as names in a medium's description (the condition's own name says which: plus_gallate
# adds CPD-183, plus_quercetin CPD-520)
NAMES = {"CPD-183": "gallate", "CPD-520": "quercetin", "PI": "phosphate", "MG+2": "magnesium", "CA+2": "calcium",
         "LEU": "leucine", "THR": "threonine", "ARG": "arginine", "NITRATE": "nitrate", "NITRITE": "nitrite",
         "INDOLE": "indole", "TUNGSTATE": "tungstate"}
CARBON = {"GLC": "glucose", "ACET": "acetate", "SUC": "succinate", "FUM": "fumarate", "MAL": "malate",
          "GLYCEROL": "glycerol", "ARABINOSE": "arabinose", "LACTOSE": "lactose", "L-ARABINOSE": "arabinose"}


def _medium(flat: Path, media_id: str, recipes: dict) -> dict:
    """A medium from the knowledge base's own tables: its base mixture, carbon sources and oxygen, and what the
    recipe adds (+Infinity) or removes (-Infinity) (media_recipes.tsv, media/*.tsv)."""
    r = recipes.get(media_id) or {"base media": media_id, "added media": "", "ingredients": "[]",
                                  "ingredients weight (units.g)": "[]"}
    base = r["base media"]
    comp = {}
    mf = flat / "condition" / "media" / f"{base}.tsv"
    if mf.is_file():
        for row in _rows(mf.read_text(encoding="utf-8")):
            try:
                comp[row["molecule id"]] = float(row["concentration (units.mmol / units.L)"])
            except (KeyError, ValueError):
                continue
    ingredients = json.loads(r.get("ingredients") or "[]")
    weights = json.loads((r.get("ingredients weight (units.g)") or "[]").replace("Infinity", "1e999"))
    added = [m for m, w in zip(ingredients, weights) if w > 0]
    removed = [m for m, w in zip(ingredients, weights) if w < 0]
    present = {m for m, c in comp.items() if c > 0} | set(added)
    present -= set(removed)
    carbon = sorted({CARBON[m] for m in present if m in CARBON})
    oxygen = "OXYGEN-MOLECULE" in present
    supplement = (r.get("added media") or "").strip('" ') or None
    parts = [("aerobic" if oxygen else "anaerobic"), (" + ".join(carbon) or "no carbon source"), "medium",
             f"({base})"]
    desc = " ".join(parts)
    if supplement:
        desc += " with amino acids" if "EZ" in supplement else f" with {supplement}"
    extra = [m for m in added if m not in CARBON and m not in ("4FE-4S",)]
    if extra:
        desc += ", plus " + ", ".join(NAMES.get(m.upper(), m.lower()) for m in extra)
    gone = [m for m in removed if m != "OXYGEN-MOLECULE"]
    if gone:
        desc += ", without " + ", ".join(NAMES.get(m.upper(), m.lower()) for m in gone)
    return {"media_id": media_id, "base": base, "carbon": carbon, "oxygen": oxygen, "added": added,
            "removed": removed, "supplement": supplement, "description": desc}


def build(root: Path) -> dict:
    flat = root / FLAT
    conds = _rows((REPO / "model_overlay" / "files" / FLAT / "condition" / "condition_defs.tsv").read_text(encoding="utf-8"))
    tf_rows = _rows((flat / "condition" / "tf_condition.tsv").read_text(encoding="utf-8"))
    recipes = {r["media id"]: r for r in _rows((flat / "condition" / "media_recipes.tsv").read_text(encoding="utf-8"))}
    complex_to_tf = {r["active TF"]: r["TF"] for r in tf_rows}
    targets: dict[str, list[str]] = {}
    for r in _rows((flat / "fold_changes.tsv").read_text(encoding="utf-8")):
        targets.setdefault(r["TF"], []).append(r["Target"])
    base_doubling = {}
    out = {}
    for r in conds:
        name = r["condition"]
        dt = float(r["doubling time (units.min)"])
        active = json.loads(r["active TFs"] or "[]")
        inactive = json.loads(r["inactive TFs"] or "[]")
        intro = _introduced(root, name)
        upstream = UPSTREAM_COMMITS.get(intro.get("commit", "")[:8])
        if upstream is None and intro.get("commit") not in ("uncommitted", "?"):
            # rows introduced before the campaign's first commit on this file are upstream's
            upstream = intro.get("date", "9999") < "2026-01-01"
        fitted_by = "base" if upstream else "campaign"
        if fitted_by == "base":
            base_doubling[name] = dt
        tfs = [complex_to_tf.get(c, c) for c in active + inactive]
        genes = sorted({g for tf in tfs for g in targets.get(tf, [])})
        out[name] = {"nutrients": r["nutrients"], "medium": _medium(flat, r["nutrients"], recipes),
                     "doubling_min": dt, "fitted_by": fitted_by, **intro,
                     "active_tfs": active, "inactive_tfs": inactive, "tf_genes": tfs, "fitted_targets": genes}
    for name, row in out.items():
        if row["fitted_by"] == "base":
            row["doubling_basis"] = "base_model"
        elif name in DERIVED:
            row["doubling_basis"], row["doubling_source"] = "derived", DERIVED[name]
        else:
            same = sorted(k for k, v in base_doubling.items() if v == row["doubling_min"])
            row["doubling_basis"] = "placeholder"
            row["doubling_source"] = (f"equals {', '.join(same)} (copied, not measured)" if same
                                      else "no source recorded")
    return {"spec": "what ParCa fits per condition, and who decided to fit it (Y10)",
            "rule": "growth and composition are fitted for every condition; the fitted factors' targets' expression "
                    "is fitted; everything else is emergent from the fitted state; perturbations are out-of-sample",
            "campaign_commit": _git(root, "rev-parse", "--short=8", "HEAD"),
            "public_ref": PUBLIC_REF, "public_commit": _git(root, "rev-parse", "--short=8", PUBLIC_REF) or None,
            "conditions": out,
            "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wcecoli", required=True, type=Path)
    a = ap.parse_args(argv)
    res = build(a.wcecoli)
    OUT.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    for k, v in res["conditions"].items():
        print(f"{k:24s} {v['fitted_by']:8s} {v.get('commit', ''):12s} {v['doubling_min']:6.1f} {v['doubling_basis']:11s} "
              f"targets {len(v['fitted_targets']):4d}  {v.get('doubling_source', '')[:50]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
