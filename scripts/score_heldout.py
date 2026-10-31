"""The held-out run, as a committed script: read the sealed documents, compute every number, print nothing
anybody had to work out by hand.

GATE G6_SCORING_IS_MECHANICAL. One annotator built every vocabulary in this pipeline and has read the
development set five times; what keeps that out of the held-out numbers is that the numbers come from code
which existed before the seal was broken. This is that code's entry point. It is committed ahead of the
run, deliberately, so the commit preceding the run is the version of the scorer that governed it -- the
same rule `holdout.OUTCOME_RULES["separate_commit"]` states for the registration.

    python scripts/score_heldout.py <seal.json> <reports_dir> <out.json> [--partition development]
                                   [--signoff=<file.signoff.json>]
                                   [--signed-off-by "Name, YYYY-MM-DD"]

WHAT IT REFUSES TO DO, which is most of its value:
  * score a document whose bytes do not match the seal, or one the seal never named;
  * average over the reports that worked when one of them did not read;
  * report a rate whose denominator is empty as 0.0, which would clear two thresholds;
  * supply G5's reviewer. Nobody has reviewed the mapping table. `--signoff` takes the file
    `scripts/mapping_review.py` writes, which carries the reviewed mappings and their digest, so the name
    is tied to WHAT was reviewed and any mapping these documents use that the sign-off never covered is
    reported separately. `--signed-off-by` is the weaker form: it records WHO but not what they saw.

THE ARCHIVE IS A COLLABORATOR'S UNPUBLISHED OUTPUT and is local only, so both paths are ARGUMENTS and
neither has a default. A machine that cannot see the archive must fail by not being given a path, not by
quietly scoring an empty corpus. Run it with `python -I`: the reports directory holds extracted
third-party files, and an interpreter started with that directory importable loads code from it.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import credentials, holdout, holdout_score, llm, observability  # noqa: E402


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = {a.split("=", 1)[0]: (a.split("=", 1)[1] if "=" in a else "")
             for a in argv if a.startswith("--")}
    if len(args) < 3:
        print(__doc__)
        return 2
    seal_path, reports_dir, out_path = args[0], args[1], args[2]
    partition = flags.get("--partition") or "held_out"
    signed_off = flags.get("--signed-off-by") or ""
    signoff_path = flags.get("--signoff") or ""

    sealed = holdout.sealed_digests(partition, seal_path)
    if sealed["digests"] is None:
        # An unreadable seal is an environment fact, and the run does not happen. It is NOT "no documents".
        print(f"REFUSED: {sealed['note']}")
        return 1
    names = sorted(sealed["digests"])
    print(f"{len(names)} document(s) sealed in {partition!r}, from {sealed['path']}")

    read = holdout_score.read_reports(reports_dir, names)
    if read["missing"]:
        print(f"REFUSED: {read['note']}")
        return 1

    credentials.load_into_env()
    with observability.meter() as meter:
        out = holdout_score.score(read["texts"], client=llm.client(max_retries=3),
                                  mappings_signed_off_by=signed_off, digests=read["digests"],
                                  partition=partition, seal_path=seal_path,
                                  signoff_path=signoff_path)
    try:
        out["spend"] = meter.summary()
    except Exception as exc:                                               # noqa: BLE001
        out["spend"] = {"note": f"meter unreadable: {type(exc).__name__}"}

    if out.get("refused"):
        print(f"REFUSED: {out['refused']}")
        io.open(out_path, "w", encoding="utf-8").write(json.dumps(out, indent=1, default=str))
        return 1

    m = out["measurements"]
    ready = holdout.readiness(m)
    out["readiness"] = ready
    io.open(out_path, "w", encoding="utf-8").write(json.dumps(out, indent=1, default=str))

    print("\nmeasurements, every one from committed code:")
    for k in sorted(m):
        print(f"  {k:36s} {m[k]!r}")
    print("\ndenominators:")
    for k, v in out["denominators"].items():
        print(f"  {k:36s} {v!r}")
    print("\nbeside the gates, because the aggregation was a choice:")
    for k, v in out["beside_the_gates"].items():
        print(f"  {k:46s} {v!r}")
    print(f"\nseal: {out['seal']['note']}")
    print(f"mappings: {out['mapping_sheet']['n_mappings']} fired, digest "
          f"{out['mapping_sheet']['digest'][:16]}")
    print(f"signoff : {out['signoff']['note']}")
    for row in (out["signoff"].get("unreviewed") or [])[:12]:
        # A mapping these documents use that nobody reviewed. Listed, because G5's single
        # string cannot say "reviewed, except for these".
        print(f"  UNREVIEWED {row}")
    if out["g5_note"]:
        print(f"G5  : {out['g5_note']}")
    print(f"\nmet       : {[g['id'] for g in ready['met']]}")
    print(f"UNMET     : {[(g['id'], g['value']) for g in ready['unmet']]}")
    print(f"unmeasured: {[g['id'] for g in ready['unmeasured']]}")
    print(f"reported  : {[(g['id'], g['value']) for g in ready['reported']]}")
    print(f"\nwrote {out_path}")
    print("spend:", json.dumps(out['spend'])[:300])
    # The script's exit code is NOT the gate's verdict. A held-out result that fails a gate is a finding
    # about the tool and the run succeeded in producing it; `OUTCOME_RULES` says it is reported as it comes
    # out. Exit 1 here would read as "re-run it", which is the one thing a one-shot set forbids.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
