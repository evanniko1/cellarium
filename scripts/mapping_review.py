"""The value-to-member mapping worksheet, for somebody other than the author to sign. Gate G5 / ADJ-W5.

WHAT THE GATE ASKS, and why no amount of code closes it. A machine checks MEMBERSHIP -- that the value a
cell was mapped to is in the authority's own set -- and does, at call time. Which member is RIGHT for what
the author wrote is a judgement, and a round-trip through the envelope validates the DESIGN rather than
the mapping: `Acetate minimal -> minimal_acetate` is a correct mapping whose timeline the envelope rightly
refuses as a carbon switch, so a round-trip would report a correct mapping as broken.

So the only honest mitigation is to make the judgement cheap, which is what this writes. Over the 33
development reports there are 55 distinct mappings that actually fired, each shown with the members it was
chosen over. That is a page, not a corpus.

    python -I scripts/mapping_review.py <reports_dir> <seal.json> <out.md> [--partition development]

It also writes `<out.md>.signoff.json` next to it, pre-filled with the mapping triples and their digest
and with the name left BLANK. The reviewer reads the worksheet, fixes anything wrong, writes their name
and the date into that file, and `scripts/score_heldout.py --signoff=<file>` then supplies `G5`'s
measurement from it. The digest is why the file is not just a name: a signature on a worksheet that has
since changed means nothing, so `holdout_score.read_signoff` refuses a sign-off whose recorded mappings do
not hash to its recorded digest, and separately REPORTS any mapping firing now that the sign-off never
covered -- a held-out document inventing a 56th spelling has found a gap in the review, not in the
reviewer.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import extraction, holdout  # noqa: E402


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = {a.split("=", 1)[0]: (a.split("=", 1)[1] if "=" in a else "") for a in argv
             if a.startswith("--")}
    if len(args) < 3:
        print(__doc__)
        return 2
    reports_dir, seal_path, out_path = args[0], args[1], args[2]
    partition = flags.get("--partition") or "development"

    sealed = holdout.sealed_digests(partition, seal_path)
    if sealed["digests"] is None:
        print(f"REFUSED: {sealed['note']}")
        return 1
    if partition == "held_out":
        # The worksheet is built by READING the documents. Building it from the held-out twelve would read
        # them, which is the one thing the seal forbids before the run.
        print("REFUSED: the worksheet is built by reading the documents, and reading the held-out set is "
              "what the seal exists to prevent. Review the development mappings; the held-out run then "
              "REPORTS any mapping it meets that the sign-off did not cover.")
        return 1

    records, missing = [], []
    for name in sorted(sealed["digests"]):
        try:
            text = io.open(Path(reports_dir) / name, encoding="utf-8", errors="replace").read()
        except OSError:
            missing.append(name)
            continue
        records += extraction.verify_quotes(extraction.extract_structural(text), text)["kept"]
    if missing:
        print(f"REFUSED: {len(missing)} report(s) could not be read under {reports_dir}. This machine "
              f"could not look; nothing about the mappings follows from it.")
        return 1

    sheet = extraction.mapping_review_sheet(records, partial=False)
    lines = [
        "# Mapping review worksheet — gate `G5_MAPPINGS_REVIEWED`",
        "",
        f"Built from the **{partition}** partition ({len(sealed['digests'])} reports), "
        f"{sheet['n_mappings']} distinct mappings that fired.",
        f"Mapping digest: `{sheet['digest']}`",
        "",
        "**What you are being asked.** Not whether the target exists — that is checked mechanically on "
        "every call. Whether it is the **right** member for what the author wrote. The `could have been` "
        "column is what else the authority offers.",
        "",
        "| role | the author wrote | mapped to | could have been | times |",
        "|---|---|---|---|---|",
    ]
    for r in sheet["rows"]:
        alts = ", ".join(f"`{x}`" for x in r["other_members"]) or "— *(no closed vocabulary)*"
        wrote = r["author_wrote"].replace("|", "\\|")
        lines += [f"| `{r['role']}` | {wrote} | `{r['mapped_to']}` | {alts} | {r['occurrences']} |"]
    if sheet["unnormalised_by_role"]:
        lines += ["", "## Values that mapped to nothing", "",
                  "Not mappings to review — a gap in the declared tables, listed so the gap is "
                  "closeable. They are frozen against the held-out reports, where a new spelling is "
                  "counted rather than accommodated.", ""]
        for role, values in sheet["unnormalised_by_role"].items():
            lines += [f"- `{role}`: " + ", ".join(f"`{v}`" for v in values)]
    lines += ["", "## How to sign", "",
              f"Edit `{Path(out_path).name}.signoff.json`: put your name in `signed_off_by` and today's "
              f"date in `date`. Leave `mappings` and `mapping_digest` alone — they are what your name "
              f"attaches to, and the scorer refuses a sign-off whose mappings do not hash to its own "
              f"digest.", "",
              "If a mapping is **wrong**, do not sign: say which row and what it should be. The tables "
              "are frozen against the held-out set, so a correction has to land before the seal is "
              "broken.", ""]
    io.open(out_path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))

    triples = sorted((r["role"], r["author_wrote"], r["mapped_to"]) for r in sheet["rows"])
    signoff = {
        "signed_off_by": "",
        "date": "",
        "partition": partition,
        "n_mappings": len(triples),
        "mapping_digest": hashlib.sha256(
            json.dumps([list(t) for t in triples], sort_keys=True).encode("utf-8")).hexdigest(),
        "mappings": [list(t) for t in triples],
        "what_this_attests": "that somebody other than the author of the mapping tables read each "
                             "mapping above and judged the chosen member right for what the author "
                             "wrote. It attests nothing about mappings not listed here.",
    }
    sign_path = str(out_path) + ".signoff.json"
    io.open(sign_path, "w", encoding="utf-8", newline="\n").write(json.dumps(signoff, indent=1))
    print(f"wrote {out_path}\nwrote {sign_path}")
    print(f"{sheet['n_mappings']} mapping(s) to review; fraction of values normalised "
          f"{sheet['fraction_normalised']}")
    print("G5 stays unmet until somebody other than the author puts their name in that file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
