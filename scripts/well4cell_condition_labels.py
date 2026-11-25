"""J-2b, the dataset side: a release candidate that says what each well4cell condition's medium IS.

well4cell names conditions as the campaign did (`plus_nitrate`, `plus_arabinose`, `no_glucose`, ...). The name says
what was added or removed; the medium holds the rest, and two kinds of name invite a reading the medium rules out
(`plus_nitrate` keeps oxygen: aerobic growth with nitrate present, not nitrate respiration; `plus_arabinose` keeps
glucose). This builds, LOCALLY, the table a next release can join on `condition`, and the card section that explains
it. Nothing is uploaded: publishing a release is the dataset owners' decision (WAITING_ON_YOU).

    python scripts/well4cell_condition_labels.py      # writes data/corpora/well4cell/rc3_candidate/
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
W4C = REPO / "data" / "corpora" / "well4cell"
OUT = W4C / "rc3_candidate"


def build(conditions: list[str]) -> list[dict]:
    from cellarium import labels, provenance
    fits = provenance.condition_fits()
    rows = []
    for c in sorted(conditions):
        fit = fits.get(c)
        medium = (fit or {}).get("medium") or {}
        hz = labels.condition_hazards(medium if fit else None)
        rows.append({"condition": c, "condition_medium": medium.get("description"),
                     "condition_reading_ruled_out": "; ".join(h["reading_ruled_out"] for h in hz
                                                              if h.get("reading_ruled_out")) or None,
                     "condition_fitted_by": (fit or {}).get("fitted_by"),
                     "condition_doubling_basis": (fit or {}).get("doubling_basis")})
    return rows


CARD = """### Condition media (proposed for the next release)

A condition's name says what the campaign added or removed; the medium holds the rest. `condition_medium` gives each
condition's medium as the knowledge base composes it (media_recipes.tsv and media/*.tsv), and
`condition_reading_ruled_out` names the reading the name invites that the medium rules out:

{table}

Two kinds matter. An electron acceptor added to a medium that keeps oxygen (`plus_nitrate`, `plus_nitrite`) is aerobic
growth with the acceptor present: oxygen is the preferred acceptor, so this is not nitrate or nitrite respiration. A
carbon source added beside glucose (`plus_arabinose`) is growth on glucose with the sugar present. `no_glucose` has
no carbon source at all. `condition_doubling_basis` says whether the condition's doubling time is the base model's
(`base_model`) or a value the campaign copied from another condition (`placeholder`); the fit sets growth and
composition from it, so growth in a placeholder condition is neither measured nor predicted.
"""


def main() -> int:
    import duckdb
    idx = W4C / "index.parquet"
    if not idx.is_file():
        print(f"{idx.relative_to(REPO)} is not on this machine; nothing to build.", file=sys.stderr)
        return 2
    conds = [r[0] for r in duckdb.connect().sql(
        f"SELECT DISTINCT condition FROM read_parquet('{idx.as_posix()}') WHERE condition IS NOT NULL").fetchall()]
    rows = build(conds)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "condition_labels.json").write_text(json.dumps({"rows": rows, "built_utc": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": "data/parca/condition_fits.json (cellarium.labels)"},
        indent=1) + "\n", encoding="utf-8")
    table = "| condition | condition_medium | condition_reading_ruled_out |\n|---|---|---|\n" + "\n".join(
        f"| `{r['condition']}` | {r['condition_medium']} | {r['condition_reading_ruled_out'] or ''} |" for r in rows)
    (OUT / "CARD_SECTION.md").write_text(CARD.format(table=table), encoding="utf-8")
    print(f"{len(rows)} conditions -> {OUT.relative_to(REPO).as_posix()}; "
          f"{sum(1 for r in rows if r['condition_reading_ruled_out'])} with a reading ruled out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
