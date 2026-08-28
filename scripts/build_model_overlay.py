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

AUTHORED. `model_overlay/authored/<wcEcoli path>` is checked BEFORE `cleaned/` and before `--source`.
It is for files Cellarium wrote outright because the change exists in no tree at all — as opposed to
`cleaned/`, which is a working-tree file with ROUTE1 removed. Today it holds exactly one:

    cloud/docker/runtime/Dockerfile   three added pip lines, because upstream's own local image build
                                      is BROKEN on a clean a4497e17 (Equation==1.2.1's sdist downloads
                                      a setuptools from a dead pypi.python.org path; see the banner in
                                      the file itself for the measurement and the fix)

Keeping the two directories separate matters: `cleaned/` carries an implicit claim ("this is the
source tree minus ROUTE1, and the diff against upstream is insertions only") that an authored file
does not satisfy and should not be read as making.

A cleaned or authored file is a SOURCE, not a shipped artifact: it still passes through every gate below, and
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
     `harvest()` asserts the correspondence in BOTH directions: a registered name with no module is
     that ImportError, and a shipped module with no registration is a checkout that carries
     `multi_gene_knockout.py` and still answers "unknown variant" — the quieter of the two.

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
AUTHORED = os.path.join(OVERLAY, "authored")
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

# CATEGORY (c) CELLARIUM — the model changes Cellarium itself needs and that are NOT part of the
# v3.0.1 port. Two clusters, and both are on the LIVE launch path rather than nice-to-haves:
#
#   THE MULTI-KO CHANNEL. `src/cellarium/runner.py:94` emits
#   `--variant multi_gene_knockout 0 0 --multi-ko-indices …` for every multi-gene design, and the gene
#   set has to travel from that command line down to the variant function. It crosses FOUR files, and
#   any one of them missing makes the flag INERT rather than loud:
#     runSim.py                  parses --multi-ko-indices, validates it, builds variant_kwargs
#     variantSimData.py          carries variant_kwargs as an optional_param (Fireworks raises on an
#                                unlisted kwarg, so an un-updated firetask is a hard error)
#     apply_variant.py           splats variant_kwargs into the variant function
#     multi_gene_knockout.py     the variant itself
#   runSim.py additionally carries the EXT-PORT-12 metadata fix — it is the SECOND call site of
#   `resolve_elongation_flags`, the one that writes the RESOLVED flags into metadata.json. Without it
#   a `--kinetic-trna-charging` run simulates correctly and RECORDS `"trna_charging": true`.
#
#   THE POSITIONAL-CONDITION FIXES. Upstream's `ppgpp_conc` / `aa_synthesis_ko` look conditions up by
#   ROW NUMBER (`condition(sim_data, 2)` meaning "with_aa"), and `rrna_operon_knockout` indexes
#   `ordered_conditions[1]` and `sorted(saved_timelines)[28]` the same way. This overlay ships a
#   21-row `condition_defs.tsv` (gate 2), so `with_aa` is row 4 and every one of those literals now
#   resolves to a DIFFERENT condition — silently, with the run completing and reporting success. They
#   are rewritten to look up by NAME. `tf_activity.py` fixes an upstream `AttributeError`
#   (`sim_data.external_state.environment` does not exist).
#
# These are modifications of CovertLab-licensed files and inherit that licence; `multi_gene_knockout.py`
# is Cellarium-authored. None of them is ROUTE1-contaminated — measured 0 markers in all eight — so
# they harvest straight from the source tree with no `cleaned/` intermediate.
CELLARIUM_NEW = [
    "models/ecoli/sim/variants/multi_gene_knockout.py",
    # PROV-1. Cellarium-authored and present in NO checkout, so its body lives in `authored/`. It was
    # hand-added to `files/` and MANIFEST.json when PROV-1 landed and never registered here, which is why
    # the manifest carried 45 entries while `counts.ship` said 44 — and why re-running this script DELETED
    # it from `files/`. A shipped file the generator cannot reproduce is a file that silently disappears on
    # the next regenerate.
    "models/ecoli/listeners/parameter_provenance.py",
]
CELLARIUM_MODIFIED = [
    "cloud/docker/runtime/Dockerfile",
    "runscripts/manual/runSim.py",
    "wholecell/fireworks/firetasks/variantSimData.py",
    "models/ecoli/sim/variants/apply_variant.py",
    "models/ecoli/sim/variants/rrna_operon_knockout.py",
    "models/ecoli/sim/variants/ppgpp_conc.py",
    "models/ecoli/sim/variants/aa_synthesis_ko.py",
    "models/ecoli/sim/variants/tf_activity.py",
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
# list plus exactly these — see gate 3 in the module docstring. Gate 3 now checks BOTH directions:
# every name here must have a shipped module (else ImportError on every variant run), and every shipped
# variant module must be named here (else the module ships and `--variant <it>` reports "unknown").
OVERLAY_VARIANTS = ["graded_gene_knockout", "multi_gene_knockout"]

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
    "cloud/docker/runtime/Dockerfile":
        "AUTHORED (model_overlay/authored/), not harvested — the change exists in no tree. Upstream's "
        "own cloud/build-containers-locally.sh FAILS on a clean a4497e17, for two independent reasons "
        "and before any Cellarium code is reached. (1) requirements.txt:79 pins Equation==1.2.1, an "
        "sdist-only package whose setup.py downloads setuptools from a pypi.python.org path that now "
        "returns HTML -> BadZipFile; it is imported by wholecell/utils/enzymeKinetics.py:10 so it "
        "cannot be dropped. (2) requirements.txt:98 pins stochastic-arrow==1.0.0, whose setup.py "
        "imports numpy with no build-requires, so PEP 517 build isolation hides the numpy installed "
        "one line earlier. Four added pip lines install both with --no-build-isolation (Equation "
        "against a temporarily pinned setuptools<66, restored immediately) BEFORE the requirements "
        "pass, so every other requirement installs exactly as upstream intended. Nothing else in the "
        "file differs from upstream.",
    "models/ecoli/sim/variants/multi_gene_knockout.py":
        "Cellarium-authored. Index-0-only variant that zeroes several gene_knockout indexes at once "
        "via sim_data.adjust_final_expression. The gene set arrives as the ko_indices kwarg, NOT as "
        "the variant index — so it needs the variant_kwargs channel (runSim.py -> variantSimData.py "
        "-> apply_variant.py) to be shipped with it or it is unreachable. NOTE the semantics: "
        "adjust_final_expression indexes rna_data, whose rows are TRANSCRIPTION UNITS, so a k-target "
        "multi-KO can silence more than k genes — see docs/KNOCKOUT_SEMANTICS.md.",
    "runscripts/manual/runSim.py":
        "Two independent reasons, either of which alone would require shipping it. (1) It defines "
        "--multi-ko-indices and multi_ko_variant_kwargs(), which is where the multi-KO gene set is "
        "validated and turned into variant_kwargs. (2) It is the SECOND call site of "
        "resolve_elongation_flags — the one that writes the RESOLVED elongation flags into "
        "metadata.json. Without it a --kinetic-trna-charging run simulates correctly and records "
        "\"trna_charging\": true, and every corpus row inherits that. It also wraps the per-variant "
        "loop in try/except so one failing variant does not abandon the rest of a sweep. 0 ROUTE1 "
        "markers, so it harvests directly with no cleaning.",
    "wholecell/fireworks/firetasks/variantSimData.py":
        "Adds variant_kwargs to optional_params and passes it to apply_variant. Fireworks raises on "
        "any kwarg not listed in required_params/optional_params, so without this the multi-KO run "
        "does not silently ignore the gene set — it dies at variant creation.",
    "models/ecoli/sim/variants/apply_variant.py":
        "Adds the variant_kwargs parameter and splats it into the variant function. This is the last "
        "link of the multi-KO channel; upstream's signature takes (sim_data, index) only.",
    "models/ecoli/sim/variants/ppgpp_conc.py":
        "CONDITIONS was [0, 2] — POSITIONAL row numbers into condition_defs.tsv, meaning "
        "basal/with_aa in upstream's 5-row table. This overlay ships 21 rows (gate 2), where row 2 is "
        "glc_5mM, so upstream's literal silently runs the wrong condition and the run still succeeds. "
        "Rewritten to CONDITIONS = ['basal', 'with_aa'] resolved through sim_data.ordered_conditions.",
    "models/ecoli/sim/variants/aa_synthesis_ko.py":
        "Same defect as ppgpp_conc: `condition(sim_data, 2)` meant with_aa in a 5-row table and means "
        "glc_5mM in ours. Rewritten to look 'with_aa' up by name. (Its OTHER known defect — cistron "
        "indices passed into a TU-indexed adjust_final_expression, docs/KNOCKOUT_SEMANTICS.md — is "
        "NOT fixed here; Cellarium does not use this variant.)",
    "models/ecoli/sim/variants/rrna_operon_knockout.py":
        "Two positional lookups, both wrong against a 21-row condition table: ordered_conditions[1] "
        "for the rich-media condition (now the named 'with_aa') and sorted(saved_timelines)[28] for "
        "the minimal-to-rich shift (now the named '000028_add_aa_long', which also RAISES rather than "
        "shifting silently if the timeline set changes). Cellarium runs this variant "
        "(envelope.VALIDATED_PERTURBATIONS), so the fix is on the live path.",
    "models/ecoli/sim/variants/tf_activity.py":
        "Fixes an upstream AttributeError: it wrote through "
        "sim_data.external_state.environment.current_timeline_id, and external_state has no "
        "`environment` attribute. Cellarium runs this variant "
        "(envelope.VALIDATED_PERTURBATIONS).",
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
        + [(p, "cellarium", "create") for p in CELLARIUM_NEW]
        + [(p, "cellarium", "modify") for p in CELLARIUM_MODIFIED]
        + [(p, "dependency", "create") for p in DEPENDENCIES_NEW]
    )

    # Gate 3, the direction the old check could not see. `__init__.py` is built from OVERLAY_VARIANTS,
    # so a name there with no module is an ImportError on every run — but a MODULE with no name is
    # just as broken and fails much later: `--variant multi_gene_knockout` reports "unknown variant"
    # from a checkout that is carrying the file. Both are asserted here, before anything is written.
    shipped_variant_modules = {
        os.path.basename(p)[:-3]
        for p in (PORT_NEW + SCRIPT_WRITTEN_NEW + CELLARIUM_NEW)
        if p.startswith("models/ecoli/sim/variants/") and p.endswith(".py")
    }
    if shipped_variant_modules != set(OVERLAY_VARIANTS):
        raise SystemExit(
            "OVERLAY_VARIANTS and the shipped variant modules disagree.\n"
            "  registered but not shipped: %s   (ImportError on EVERY variant run)\n"
            "  shipped but not registered: %s   (module present, `--variant <it>` says unknown)\n"
            % (sorted(set(OVERLAY_VARIANTS) - shipped_variant_modules),
               sorted(shipped_variant_modules - set(OVERLAY_VARIANTS))))

    for rel, category, action in plan:
        # Three possible bodies, in priority order — see CLEANED and AUTHORED in the module docstring.
        # Everything downstream of here, gates included, is identical whichever one wins; only the
        # recorded `source` differs, so the manifest says where each body came from rather than
        # leaving it to be inferred.
        authored = read_lf(os.path.join(AUTHORED, rel.replace("/", os.sep)))
        cleaned = read_lf(os.path.join(CLEANED, rel.replace("/", os.sep)))
        src = authored if authored is not None else (
            cleaned if cleaned is not None else read_lf(
                os.path.join(source, rel.replace("/", os.sep))))
        ups = read_lf(os.path.join(upstream, rel.replace("/", os.sep)))
        rec: dict = {
            "path": rel,
            "category": category,
            "action": action,
            "upstream_sha256": sha256(ups),
            "upstream_bytes": len(ups) if ups is not None else None,
        }
        if authored is not None:
            rec["source"] = "model_overlay/authored"
        elif cleaned is not None:
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


def carry_patches(records: list[dict], bodies: dict[str, bytes]) -> list[str]:
    """Re-apply Cellarium-authored edits over the freshly harvested bodies. Returns the paths carried.

    `harvest` copies from --source (the finished wcEcoli checkout) and `write_overlay` rmtree's
    model_overlay/files first, so ANY edit made to a shipped file here is silently reverted by the next
    rebuild — the file would go back to the harvested body and the manifest hash would follow it, leaving
    nothing to notice. That is not hypothetical: the EXT-PORT-13 listener gate is exactly such an edit, and
    without this it would vanish on the next `python scripts/build_model_overlay.py` with a clean exit.

    A patched file is declared by a `cellarium_patch` block on its record in the EXISTING manifest, which
    records the pre-patch (`harvested_*`) hash. When the harvest still produces that pre-patch body the
    patch is carried forward silently. When the harvest produces something ELSE the upstream file has moved
    underneath the patch, so the patch is dropped and the path is reported — re-applying a stale edit to a
    changed file is worse than losing it, and it must be a human decision either way."""
    if not os.path.isfile(MANIFEST):
        return []
    prior = {r["path"]: r for r in json.load(io.open(MANIFEST, encoding="utf-8")).get("files", [])
             if r.get("cellarium_patch")}
    carried, dropped = [], []
    for rec in records:
        rel = rec["path"]
        p = prior.get(rel)
        if not p or rel not in bodies:
            continue
        patch = p["cellarium_patch"]
        if sha256(bodies[rel]) != patch.get("harvested_sha256"):
            dropped.append(rel)
            continue
        kept = read_lf(os.path.join(FILES, rel.replace("/", os.sep)))
        if kept is None or sha256(kept) != p["overlay_sha256"]:
            dropped.append(rel)                      # the patched file on disk is not what the manifest says
            continue
        bodies[rel] = kept
        rec.update(overlay_sha256=p["overlay_sha256"], overlay_bytes=p["overlay_bytes"],
                   cellarium_patch=patch)
        carried.append(rel)
    for rel in dropped:
        print("  PATCH DROPPED  %-58s upstream moved, or the patched file is not what the manifest "
              "records — re-apply by hand" % rel, file=sys.stderr)
    return carried


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
            "academic non-commercial licence. The `cellarium` and `script-written` categories are "
            "Cellarium's own work; where they MODIFY a wcEcoli file they are derivative of it and "
            "inherit the same non-commercial terms."),
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
    _wc = os.environ.get("WCECOLI_PATH") or os.environ.get("WCECOLI_DIR")
    ap.add_argument("--source", default=_wc, required=_wc is None,
                    help="the finished checkout to harvest from (or set WCECOLI_PATH / WCECOLI_DIR). No default: harvesting silently reached into whichever checkout sat at the hard-coded path, and a file missing from it is DELETED from model_overlay/files.")
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
    carried = carry_patches(records, bodies)         # BEFORE the ship/blocked split: it rewrites hashes
    shipped = [r for r in records if r["status"] == "ship"]
    blocked = [r for r in records if r["status"] == "blocked"]
    for rel in carried:
        print("  patch carried  %s" % rel)

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
