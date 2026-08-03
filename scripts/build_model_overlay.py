"""Build `model_overlay/` — the finished wcEcoli files Cellarium ships, plus the manifest that pins them.

WHY THIS EXISTS. Cellarium used to transform a wcEcoli checkout by matching TEXT ANCHORS and
substituting (`apply_trna_port.py` + `ext_port_10_patch.py` + `ext_port_11_patch.py`). That recipe
replayed on NO committed tree: measured against upstream `a4497e17` it aborted four separate times
(see `docs/OVERLAY.md` for each). An overlay ships the FINISHED file and copies it, so there are no
anchors to drift, no CRLF sensitivity, and no partial application — it either works or it fails on a
checksum.

The cost of an overlay is VERSION PINNING: if upstream changes a file we overlay, our copy is stale.
That is what `MANIFEST.json` records the upstream SHA256 for, and what `apply_model_overlay.py`
refuses to proceed past.

WHAT THIS SCRIPT DOES. It harvests each shipped file from a SOURCE tree (the working checkout that
produced the published corpus), gates it, and writes `model_overlay/files/<wcEcoli path>` plus
`model_overlay/MANIFEST.json`. Three gates, and each one exists because of a measured defect:

  1. ROUTE1 REFUSAL. The isoacceptor exploration was deliberately extracted to
     `github.com/evanniko1/wcecoli-extension-tRNA-isoacceptors` (BACKLOG.md:176) and only the port
     stayed. Seven files in the working tree still carry ROUTE1 code, and it is interwoven with the
     port rather than appended to it (28 markers inside function bodies in
     `polypeptide_elongation.py`). Copying them verbatim would re-import exactly what was extracted.
     Any file whose content contains the marker `ROUTE1` is REFUSED, recorded as `blocked`, and
     named by `apply_model_overlay.py --check`. It is NOT silently stripped: removing interwoven
     model code without review is how a tree that runs becomes a tree that is quietly wrong.

     THE REVIEW HAS NOW BEEN DONE for the five files this gate used to block, and its OUTPUT lives
     in `model_overlay/cleaned/` — see the note on CLEANED below. The gate itself is unchanged and
     still runs against the cleaned bodies, so a cleaned file that reacquired a ROUTE1 marker would
     be blocked exactly as before.

CLEANED. `harvest()` reads each file from `model_overlay/cleaned/<wcEcoli path>` when that file
exists, and from `--source` otherwise. It exists for exactly one reason: five port files in the
working tree are ROUTE1-contaminated, the working tree is the ONLY artifact the port was ever
written into, and `C:/dev/wcEcoli` is not ours to edit. The cleaned copies are those five files with
every ROUTE1 addition reverted to upstream `a4497e17` and NOTHING else changed — measured as a diff
against upstream that contains only insertions (the port, plus the `initial_condition` runtime
alignment), with the kinetic elongation model intact:

    models/ecoli/processes/polypeptide_elongation.py    28 ROUTE1 markers -> 0
    wholecell/utils/scriptBase.py                        5 -> 0
    wholecell/sim/simulation.py                          3 -> 0
    wholecell/fireworks/firetasks/simulation.py          1 -> 0
    wholecell/fireworks/firetasks/simulationDaughter.py  1 -> 0

A cleaned file is a SOURCE, not a shipped artifact: it still passes through every gate below, and
its `upstream_sha256` is still taken against `--upstream`, so upstream drift still invalidates it.
Records harvested this way carry `"source": "model_overlay/cleaned"` so the manifest says where each
body came from rather than leaving it to be inferred.

  2. CONDITION ORDERING. `models/ecoli/sim/variants/condition.py` reads `sim_data.ordered_conditions`,
     which is TSV ROW ORDER, and Cellarium hardcodes condition INDICES
     (`src/cellarium/generate.py:50,74,118-121`). The working-tree `condition_defs.tsv` INSERTS the
     three amino-acid dropouts at rows 5/6/7, shifting acetate/succinate/no_oxygen/minus_magnesium
     down by three and contradicting Cellarium's own cached `data/cache/variant_map.json`. The
     overlay ships the 21-row ordering that `variant_map.json` asserts, with the dropouts APPENDED at
     21/22/23. This script ASSERTS that agreement rather than trusting it.

  3. VARIANT REGISTRATION. `models/ecoli/sim/variants/__init__.py` imports every registered name
     EAGERLY (`nameToFunctionMapping = {v: get_function(v) for v in variants}`), so registering a
     variant whose module is not shipped is an ImportError on every run, not a lazy failure. The
     shipped `__init__.py` is rewritten to register exactly the variant modules the overlay carries.

Run it after changing anything under `model_overlay/`, and commit the result:

    python scripts/build_model_overlay.py --source C:/dev/wcEcoli --upstream C:/tmp/upstream_a4497e17
    python scripts/build_model_overlay.py --check     # CI: rebuild in memory, diff, write nothing

LINE ENDINGS. Everything is normalised to LF on the way in and shipped as LF. The upstream SHA256s
recorded in the manifest are also over LF-normalised bytes, so the staleness check gives the same
answer on a Windows CRLF checkout and a Linux LF one. `git archive` applies the repo's eol
attributes, so a Windows materialisation of upstream is CRLF and an unnormalised hash would flag
every file as stale on one platform and none on the other.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OVERLAY = os.path.join(REPO, "model_overlay")
FILES = os.path.join(OVERLAY, "files")
CLEANED = os.path.join(OVERLAY, "cleaned")
MANIFEST = os.path.join(OVERLAY, "MANIFEST.json")

# The upstream commit every `upstream_sha256` below is taken against. This is the last
# CovertLab-authored commit on the fork, i.e. the newest point at which our tree and the public tree
# agree. Materialise it read-only with:
#     git -C <wcEcoli> archive a4497e17 | tar -x -C <dir>
UPSTREAM_COMMIT = "a4497e17"
UPSTREAM_REPO = "https://github.com/CovertLab/wcEcoli"

ROUTE1_MARKER = "ROUTE1"

# --------------------------------------------------------------------------------------------------
# What ships.
#
# CATEGORY (a) THE PORT — v3.0.1 kinetic tRNA charging (EXT-PORT 1/10/11) plus the EXT-PORT-12 /
# UNIFY-2 flag split and RNG determinism fix. Derived from CovertLab/WholeCellEcoliRelease v3.0.1
# (Choi & Covert 2023, NAR 51(12):5911, doi:10.1093/nar/gkad435) under its non-commercial LICENSE.md,
# redistributed with Prof. Covert's permission — see the header of scripts/apply_trna_port.py.
# --------------------------------------------------------------------------------------------------
PORT_MODIFIED = [
    "reconstruction/ecoli/dataclasses/relation.py",
    "reconstruction/ecoli/dataclasses/molecule_groups.py",
    "reconstruction/ecoli/dataclasses/molecule_ids.py",
    "reconstruction/ecoli/dataclasses/process/translation.py",
    "reconstruction/ecoli/simulation_data.py",
    "reconstruction/ecoli/knowledge_base_raw.py",
    "reconstruction/ecoli/fit_sim_data_1.py",
    "reconstruction/ecoli/flat/rnas.tsv",
    "wholecell/fireworks/firetasks/parca.py",
    "wholecell/fireworks/firetasks/fitSimData.py",
    "wholecell/fireworks/firetasks/simulation.py",
    "wholecell/fireworks/firetasks/simulationDaughter.py",
    "wholecell/sim/simulation.py",
    "wholecell/utils/scriptBase.py",
    "models/ecoli/sim/simulation.py",
    "models/ecoli/processes/polypeptide_elongation.py",
    "models/ecoli/processes/metabolism.py",
    "models/ecoli/listeners/growth_limits.py",
    "models/ecoli/sim/initial_conditions.py",
    "setup.py",
]

PORT_NEW = [
    "models/ecoli/listeners/trna_charging.py",
    "wholecell/utils/_trna_charging.pyx",
    "reconstruction/ecoli/flat/trna_charging_kinetics.tsv",
    "reconstruction/ecoli/flat/trna_charging_kinetics_curated.tsv",
    "reconstruction/ecoli/flat/optimization/trna_charging_kinetics_constants.tsv",
    "reconstruction/ecoli/flat/optimization/trna_charging_kinetics_solutions.tsv",
    "reconstruction/ecoli/flat/optimization/trna_synthetase_dynamic_range.tsv",
    "validation/ecoli/flat/trna_synthetase_kinetics.tsv",
]

# CATEGORY (b) SCRIPT-WRITTEN — what apply_model_variants.py and apply_model_patches.py produce.
SCRIPT_WRITTEN_NEW = [
    "models/ecoli/sim/variants/graded_gene_knockout.py",
]
SCRIPT_WRITTEN_MODIFIED = [
    "models/ecoli/sim/variants/__init__.py",
    "reconstruction/ecoli/flat/condition/media_recipes.tsv",
    "reconstruction/ecoli/flat/condition/condition_defs.tsv",
]

# DEPENDENCIES OF CATEGORY (b). Not category (b) themselves, but the category (b) files are INVALID
# without them, so shipping (b) alone would produce a checkout that fails on the first ParCa.
# `condition_defs.tsv` rows 1/2/3 (glc_20mM / glc_5mM / glc_2mM — Cellarium's variant_map indices
# 1,2,3) name media `minimal_GLC_{20,5,2}mM`, whose recipes in `media_recipes.tsv` name base
# `MIX0-57-GLC-{20,5,2}mM`, whose TSVs do not exist upstream. Three files, 512 bytes each.
DEPENDENCIES_NEW = [
    "reconstruction/ecoli/flat/condition/media/MIX0-57-GLC-20mM.tsv",
    "reconstruction/ecoli/flat/condition/media/MIX0-57-GLC-5mM.tsv",
    "reconstruction/ecoli/flat/condition/media/MIX0-57-GLC-2mM.tsv",
]

# The variant modules the overlay actually carries. `__init__.py` is rewritten to register upstream's
# list plus exactly these — see gate 3 in the module docstring.
OVERLAY_VARIANTS = ["graded_gene_knockout"]

# The three amino-acid dropout condition rows, APPENDED (never inserted) — see gate 2.
DROPOUT_CONDITION_ROWS = [
    '"minus_leu"\t"minimal_aa_minus_leu"\t{}\t25.0\t[]\t[]',
    '"minus_thr"\t"minimal_aa_minus_thr"\t{}\t25.0\t[]\t[]',
    '"minus_arg"\t"minimal_aa_minus_arg"\t{}\t25.0\t[]\t[]',
]

# The condition ordering Cellarium's cached variant_map.json asserts. Checked, not assumed.
EXPECTED_CONDITION_ORDER = [
    "basal", "glc_20mM", "glc_5mM", "glc_2mM", "with_aa", "acetate", "succinate", "no_oxygen",
    "fumarate", "malate", "minus_calcium", "minus_magnesium", "minus_phosphate", "no_glucose",
    "plus_arabinose", "plus_gallate", "plus_indole", "plus_nitrate", "plus_nitrite",
    "plus_quercetin", "plus_tungstate",
]

NOTES = {
    "wholecell/utils/_trna_charging.pyx":
        "Cython source only. The built .so is Linux-specific and is compiled INSIDE the model image "
        "by setup.py; it is deliberately not shipped.",
    "reconstruction/ecoli/flat/optimization/trna_charging_kinetics_solutions.tsv":
        "4.7 MB, ~80% of the whole overlay. It is a tRNA-charging OPTIMISER OUTPUT, not a "
        "hand-authored input; scripts/verify_trna_objective.py reproduces its rows. Kept in-tree so "
        "a clone reproduces the corpus without a refit, but it is the obvious candidate for "
        "out-of-band hosting if repo size becomes a problem.",
    "reconstruction/ecoli/flat/condition/condition_defs.tsv":
        "Row order IS the condition index space (models/ecoli/sim/variants/condition.py reads "
        "sim_data.ordered_conditions). Rebuilt here rather than copied — see gate 2.",
    "models/ecoli/sim/variants/__init__.py":
        "Rewritten, not copied — see gate 3. Registers upstream's variants plus %s."
        % ", ".join(OVERLAY_VARIANTS),
    "setup.py":
        "Registers _trna_charging.pyx with cythonize, so `make compile` and any image build produce "
        "the extension.",
}

# The five files the ROUTE1 gate used to block, now harvested from model_overlay/cleaned/. The note
# records what was removed and what had to survive, per file, because "de-ROUTE1'd" on its own does
# not say whether the KINETIC MODEL came out with it — which is the whole point of the exercise:
# src/cellarium/capability.py maps mode "kinetic" -> --kinetic-trna-charging, and that flag is dead
# on a public clone unless these five ship.
_DE_ROUTE1 = (
    "De-ROUTE1'd from the working tree (28/5/3/1/1 markers -> 0) and harvested from "
    "model_overlay/cleaned/. Every ROUTE1 addition was reverted to upstream %s; the diff against "
    "upstream is insertions only. What SURVIVES is the port: KineticTrnaChargingModel, "
    "CoarseKineticTrnaChargingModel, resolve_elongation_flags, and the kinetic_trna_charging / "
    "coarse_kinetic_elongation flags on all four allow-lists (scriptBase ANALYSIS_KEYS + SIM_KEYS "
    "and both firetask optional_params). What is GONE is the isoacceptor exploration: "
    "trna_charging_resolution, trna_demand_split, dcdt_jit_iso, clamp_charging_shared, T2A/A2T/"
    "KMtf_trna/n_trna_per_aa/trna_charging_mask, and the occupancy-form rewrite of "
    "ribosome_conc_a_site." % UPSTREAM_COMMIT)
for _p in ("models/ecoli/processes/polypeptide_elongation.py",
           "wholecell/utils/scriptBase.py",
           "wholecell/sim/simulation.py",
           "wholecell/fireworks/firetasks/simulation.py",
           "wholecell/fireworks/firetasks/simulationDaughter.py"):
    NOTES[_p] = _DE_ROUTE1


def read_lf(path: str) -> bytes | None:
    """File bytes with CRLF collapsed to LF, or None if absent. Every hash in the manifest is over
    this form, so the staleness check answers the same on Windows and Linux."""
    if not os.path.isfile(path):
        return None
    return io.open(path, "rb").read().replace(b"\r\n", b"\n")


def sha256(blob: bytes | None) -> str | None:
    return hashlib.sha256(blob).hexdigest() if blob is not None else None


def build_condition_defs(source_blob: bytes, upstream_blob: bytes) -> bytes:
    """Rebuild condition_defs.tsv with the dropout rows APPENDED, and assert the ordering.

    Gate 2. The working-tree file inserts the dropouts at rows 5/6/7, which shifts every condition
    after `with_aa` and makes every hardcoded index in src/cellarium/generate.py wrong by three.
    """
    lines = source_blob.decode("utf-8").split("\n")
    header = [ln for ln in lines if ln.startswith("#") or ln.startswith('"condition"')]
    rows = [ln for ln in lines if ln.strip() and ln not in header]

    def cid(row: str) -> str:
        return row.split("\t", 1)[0].strip('"')

    dropouts = {cid(r) for r in DROPOUT_CONDITION_ROWS}
    base = [r for r in rows if cid(r) not in dropouts]
    order = [cid(r) for r in base]
    if order != EXPECTED_CONDITION_ORDER:
        raise SystemExit(
            "condition_defs.tsv ordering does not match Cellarium's cached variant_map.json.\n"
            "  built: %s\n  expected: %s\n"
            "Cellarium hardcodes condition INDICES; shipping a different order silently reassigns "
            "every one of them. Reconcile data/cache/variant_map.json and the source tree before "
            "rebuilding the overlay." % (order, EXPECTED_CONDITION_ORDER))
    # The dropouts must sit AFTER every condition variant_map.json knows about, so adding them
    # cannot move an existing index.
    out = header + base + DROPOUT_CONDITION_ROWS
    return ("\n".join(out) + "\n").encode("utf-8")


def build_variants_init(upstream_blob: bytes) -> bytes:
    """Rewrite variants/__init__.py to register upstream's variants plus the ones we ship.

    Gate 3. `__init__.py` imports every registered name eagerly, so a name without a module is an
    ImportError on EVERY variant run, including ones that do not use it.
    """
    text = upstream_blob.decode("utf-8")
    add = ""
    for name in sorted(OVERLAY_VARIANTS):
        entry = "\t'%s',\n" % name
        if entry in text:
            continue
        # keep the list alphabetical, which is how upstream maintains it
        marker = "variants = [\n"
        i = text.index(marker) + len(marker)
        j = text.index("\t]\n", i)
        block = text[i:j]
        rows = [ln for ln in block.split("\n") if ln.strip()]
        rows.append("\t'%s'," % name)
        rows.sort(key=lambda ln: ln.strip().strip("',"))
        text = text[:i] + "\n".join(rows) + "\n" + text[j:]
        add += name + " "
    banner = (
        "# Cellarium overlay: this file registers upstream's variants plus the variant modules the\n"
        "# overlay ships (%s). Registration is EAGER --\n"
        "# nameToFunctionMapping imports every name below at import time -- so a name here whose\n"
        "# module is absent is an ImportError on every variant run, not a lazy failure. Do not add a\n"
        "# name without adding its module to model_overlay/files/.\n"
        % ", ".join(OVERLAY_VARIANTS))
    return (banner + text).encode("utf-8")


def harvest(source: str, upstream: str) -> tuple[list[dict], dict[str, bytes]]:
    """Produce the manifest records and the file bodies. Pure: writes nothing."""
    records: list[dict] = []
    bodies: dict[str, bytes] = {}

    plan = (
        [(p, "port", "modify") for p in PORT_MODIFIED]
        + [(p, "port", "create") for p in PORT_NEW]
        + [(p, "script-written", "create") for p in SCRIPT_WRITTEN_NEW]
        + [(p, "script-written", "modify") for p in SCRIPT_WRITTEN_MODIFIED]
        + [(p, "dependency", "create") for p in DEPENDENCIES_NEW]
    )

    for rel, category, action in plan:
        # See CLEANED in the module docstring. A de-ROUTE1'd copy in model_overlay/cleaned/ WINS over
        # the source tree; everything downstream of here, gates included, is identical either way.
        cleaned = read_lf(os.path.join(CLEANED, rel.replace("/", os.sep)))
        src = cleaned if cleaned is not None else read_lf(
            os.path.join(source, rel.replace("/", os.sep)))
        ups = read_lf(os.path.join(upstream, rel.replace("/", os.sep)))
        rec: dict = {
            "path": rel,
            "category": category,
            "action": action,
            "upstream_sha256": sha256(ups),
            "upstream_bytes": len(ups) if ups is not None else None,
        }
        if cleaned is not None:
            rec["source"] = "model_overlay/cleaned"
        if NOTES.get(rel):
            rec["note"] = NOTES[rel]

        if src is None:
            rec.update(status="blocked",
                       reason="not present in the source tree %r — nothing to harvest" % source)
            records.append(rec)
            continue

        if action == "modify" and ups is None:
            rec.update(status="blocked",
                       reason="declared as a MODIFY but absent from upstream %s — it is a CREATE, "
                              "or the path is wrong" % UPSTREAM_COMMIT)
            records.append(rec)
            continue
        if action == "create" and ups is not None:
            rec.update(status="blocked",
                       reason="declared as a CREATE but already present upstream at %s — it is a "
                              "MODIFY" % UPSTREAM_COMMIT)
            records.append(rec)
            continue

        # ---- gate 2 / gate 3: files that are BUILT rather than copied
        if rel == "reconstruction/ecoli/flat/condition/condition_defs.tsv":
            body = build_condition_defs(src, ups)
        elif rel == "models/ecoli/sim/variants/__init__.py":
            body = build_variants_init(ups)
        else:
            body = src

        # ---- gate 1: ROUTE1 refusal
        n_route1 = body.decode("utf-8", "replace").count(ROUTE1_MARKER)
        if n_route1:
            rec.update(
                status="blocked",
                route1_markers=n_route1,
                reason="carries %d ROUTE1 marker(s). The isoacceptor exploration was extracted to "
                       "github.com/evanniko1/wcecoli-extension-tRNA-isoacceptors (BACKLOG.md:176) "
                       "and only the port stayed; shipping this file verbatim would re-import it. "
                       "No clean port-only version of this file exists in ANY commit — the port was "
                       "never committed, so its only artifact anywhere is the mixed working tree. "
                       "Producing one is code surgery on interwoven changes and is not done "
                       "silently here." % n_route1)
            records.append(rec)
            continue

        rec.update(status="ship",
                   overlay_sha256=sha256(body),
                   overlay_bytes=len(body))
        records.append(rec)
        bodies[rel] = body

    return records, bodies


def write_overlay(records: list[dict], bodies: dict[str, bytes]) -> None:
    if os.path.isdir(FILES):
        shutil.rmtree(FILES)
    for rel, body in bodies.items():
        dst = os.path.join(FILES, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        io.open(dst, "wb").write(body)

    shipped = [r for r in records if r["status"] == "ship"]
    blocked = [r for r in records if r["status"] == "blocked"]
    manifest = {
        "schema": 1,
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "hash": "sha256 over CRLF-normalised (LF) bytes",
        "generated_by": "scripts/build_model_overlay.py",
        "licence": (
            "The `port` category derives from CovertLab/WholeCellEcoliRelease v3.0.1 (Choi & Covert "
            "2023, NAR 51(12):5911, doi:10.1093/nar/gkad435) under its non-commercial LICENSE.md, "
            "redistributed with Prof. Covert's permission. wcEcoli itself is under the Covert Lab "
            "academic non-commercial licence."),
        "counts": {
            "ship": len(shipped),
            "blocked": len(blocked),
            "ship_bytes": sum(r["overlay_bytes"] for r in shipped),
        },
        "files": records,
    }
    io.open(MANIFEST, "w", encoding="utf-8", newline="\n").write(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", default=os.environ.get("WCECOLI_PATH", r"C:\dev\wcEcoli"),
                    help="the finished checkout to harvest from")
    ap.add_argument("--upstream", default=r"C:\tmp\upstream_a4497e17",
                    help="a read-only materialisation of %s" % UPSTREAM_COMMIT)
    ap.add_argument("--check", action="store_true",
                    help="rebuild in memory and report; write nothing")
    a = ap.parse_args(argv)

    for label, path in (("--source", a.source), ("--upstream", a.upstream)):
        if not os.path.isdir(path):
            print("ERROR: %s %r is not a directory" % (label, path), file=sys.stderr)
            return 2

    records, bodies = harvest(a.source, a.upstream)
    shipped = [r for r in records if r["status"] == "ship"]
    blocked = [r for r in records if r["status"] == "blocked"]

    if a.check:
        stale = []
        for r in shipped:
            dst = os.path.join(FILES, r["path"].replace("/", os.sep))
            if sha256(read_lf(dst)) != r["overlay_sha256"]:
                stale.append(r["path"])
        print("would ship %d files (%d bytes); %d blocked; %d on-disk mismatches"
              % (len(shipped), sum(r["overlay_bytes"] for r in shipped), len(blocked), len(stale)))
        for p in stale:
            print("  STALE  %s" % p)
        return 1 if stale else 0

    write_overlay(records, bodies)
    print("model_overlay/: %d files, %d bytes"
          % (len(shipped), sum(r["overlay_bytes"] for r in shipped)))
    for r in blocked:
        print("  BLOCKED  %-62s %s" % (r["path"], r["reason"].split(".")[0]))
    print("manifest: %s (upstream pinned at %s)" % (MANIFEST, UPSTREAM_COMMIT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
