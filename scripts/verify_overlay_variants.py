"""Assert that the KNOCKOUT capabilities Cellarium launches actually work on an overlaid checkout.

WHY THIS EXISTS. `src/cellarium/runner.py:94` emits

    --variant multi_gene_knockout 0 0 --multi-ko-indices <i> <j> ...

on the live launch path. That command line only does something if FOUR separate files agree, and
three of the four failure modes are quiet:

    runSim.py                parses --multi-ko-indices and builds variant_kwargs
                             -> missing: `unrecognized arguments`, loud, but only at launch
    variantSimData.py        carries variant_kwargs as an optional_param
                             -> missing: Fireworks raises on the unlisted kwarg, at variant creation
    apply_variant.py         splats variant_kwargs into the variant function
                             -> missing: TypeError deep inside the firetask
    multi_gene_knockout.py   the variant itself
                             -> missing: ImportError at `import models.ecoli.sim.variants`, on EVERY
                                variant run, because registration is eager

and the WORST case is none of those: a checkout where the flag parses and the gene set is dropped on
the way down would run a WILD TYPE and label it a multi-gene knockout. That is the WELL-NOOP-1
pattern already in the backlog, so this script checks the channel link by link rather than checking
that a run "completed".

It also checks the two things a marker count cannot see:

  * REGISTRATION IN BOTH DIRECTIONS. Every name in `variants/__init__.py` must have a module in the
    tree (a name without one is an ImportError on every variant run), and every variant module in the
    tree must be registered (a module without a name ships fine and answers "unknown variant").
  * THE POSITIONAL-CONDITION LITERALS. Upstream's `ppgpp_conc` / `aa_synthesis_ko` /
    `rrna_operon_knockout` look conditions up by ROW NUMBER. This overlay ships a 21-row
    `condition_defs.tsv`, so `condition(sim_data, 2)` no longer means `with_aa` — it means `glc_5mM`,
    and the run SUCCEEDS while answering a different question. The check is not "the fix is present"
    but "the literal upstream uses now resolves elsewhere", measured against the shipped TSV.

Usage:

    python scripts/verify_overlay_variants.py                        # the shipped overlay bodies
    python scripts/verify_overlay_variants.py --tree C:/tmp/clone    # a checkout the overlay was applied to

Exit 0 only if every check passes. `--tree` additionally enables the whole-tree registration check,
which needs upstream's own variant modules present and so cannot run against `model_overlay/files/`
alone; when it is skipped the script SAYS SO rather than counting it as a pass.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OVERLAY_FILES = os.path.join(REPO, "model_overlay", "files")

VARIANTS_DIR = "models/ecoli/sim/variants"
RUNSIM = "runscripts/manual/runSim.py"
VARIANT_FIRETASK = "wholecell/fireworks/firetasks/variantSimData.py"
APPLY_VARIANT = VARIANTS_DIR + "/apply_variant.py"
MULTI_KO = VARIANTS_DIR + "/multi_gene_knockout.py"
CONDITION_DEFS = "reconstruction/ecoli/flat/condition/condition_defs.tsv"

# The variants Cellarium's envelope declares it launches (src/cellarium/envelope.py), restricted to
# the ones that are variant MODULES. `wildtype`/`timeline`/`new_gene`/`amino_acid_shift` are not
# module names in this tree, so asserting them here would fail on upstream's own naming.
CELLARIUM_LAUNCHED = [
    "gene_knockout",          # SINGLE gene KO — upstream's, must survive the overlay
    "graded_gene_knockout",   # Cellarium's graded KO
    "multi_gene_knockout",    # Cellarium's multi-gene KO
    "condition",
    "tf_activity",
    "ppgpp_conc",
    "rrna_operon_knockout",
]

# Upstream ships these two as COPY-ME SKELETONS and deliberately leaves them out of `variants`
# (`template.py` raises on any index). They are the one legitimate case of "module present, not
# registered", so they are excluded by name rather than by loosening the check — a THIRD unregistered
# module is a real defect and must still fail.
UNREGISTERED_UPSTREAM = {"template", "template_internal_shift"}

# What `scripts/build_model_overlay.py:OVERLAY_VARIANTS` ships. Both directions are asserted for these
# specifically, because these are the ones this repo can get wrong.
OVERLAY_VARIANT_MODULES = ["graded_gene_knockout", "multi_gene_knockout"]

failures: list[str] = []
skipped: list[str] = []
notes: list[str] = []


def ok(msg: str) -> None:
    print("  ok    %s" % msg)


def bad(msg: str) -> None:
    failures.append(msg)
    print("  FAIL  %s" % msg)


def skip(msg: str) -> None:
    skipped.append(msg)
    print("  skip  %s" % msg)


def read(tree: str, rel: str) -> str | None:
    p = os.path.join(tree, rel.replace("/", os.sep))
    if not os.path.isfile(p):
        return None
    return io.open(p, encoding="utf-8").read().replace("\r\n", "\n")


# --------------------------------------------------------------------------------------------------
# 1. Registration
# --------------------------------------------------------------------------------------------------
def registered_names(src: str) -> list[str]:
    """The `variants = [...]` list, read from the AST rather than by grep — a name inside a comment
    or a docstring is not a registration and must not count as one."""
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "variants" for t in node.targets):
            return [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    return []


def check_registration(tree: str, whole_tree: bool) -> None:
    print("\n[1] variant registration")
    src = read(tree, VARIANTS_DIR + "/__init__.py")
    if src is None:
        bad("%s/__init__.py is absent" % VARIANTS_DIR)
        return
    names = registered_names(src)
    if not names:
        bad("could not read the `variants = [...]` list out of __init__.py")
        return
    ok("__init__.py registers %d variants" % len(names))

    for want in CELLARIUM_LAUNCHED:
        if want in names:
            ok("registered: %s" % want)
        else:
            bad("NOT registered: %s — envelope.VALIDATED_PERTURBATIONS launches it" % want)

    # name -> module. Only meaningful on a whole tree; model_overlay/files/ carries our modules only.
    if whole_tree:
        missing = [n for n in names
                   if not os.path.isfile(os.path.join(tree, *(VARIANTS_DIR + "/%s.py" % n).split("/")))]
        if missing:
            bad("registered with NO module (ImportError on every variant run): %s" % missing)
        else:
            ok("all %d registered names have a module — eager import cannot fail" % len(names))

        present = sorted(
            f[:-3] for f in os.listdir(os.path.join(tree, *VARIANTS_DIR.split("/")))
            if f.endswith(".py") and f not in ("__init__.py", "apply_variant.py"))
        unregistered = [m for m in present if m not in names and m not in UNREGISTERED_UPSTREAM]
        if unregistered:
            bad("module present but UNREGISTERED (ships fine, answers 'unknown variant'): %s"
                % unregistered)
        else:
            ok("all %d variant modules on disk are registered (excluding upstream's %s)"
               % (len(present) - len(UNREGISTERED_UPSTREAM), sorted(UNREGISTERED_UPSTREAM)))
        for shipped in OVERLAY_VARIANT_MODULES:
            if shipped in names and shipped in present:
                ok("overlay-shipped variant %s: module present AND registered" % shipped)
            else:
                bad("overlay-shipped variant %s: module=%s registered=%s"
                    % (shipped, shipped in present, shipped in names))
    else:
        skip("name->module correspondence needs a whole checkout (pass --tree)")


# --------------------------------------------------------------------------------------------------
# 2. The multi-KO channel, link by link
# --------------------------------------------------------------------------------------------------
def func_def(src: str, name: str, cls: str | None = None) -> ast.FunctionDef | None:
    tree = ast.parse(src)
    scopes = [tree]
    if cls is not None:
        scopes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls]
    for scope in scopes:
        for node in ast.walk(scope) if cls is None else scope.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
    return None


def check_channel(tree: str) -> None:
    print("\n[2] the multi-KO channel: runSim -> variantSimData -> apply_variant -> the variant")

    # link 1 — runSim.py
    src = read(tree, RUNSIM)
    if src is None:
        bad("%s is absent — --multi-ko-indices cannot exist" % RUNSIM)
    else:
        if "'--multi-ko-indices'" in src or '"--multi-ko-indices"' in src:
            ok("runSim.py defines --multi-ko-indices")
        else:
            bad("runSim.py does NOT define --multi-ko-indices")
        if func_def(src, "multi_ko_variant_kwargs") is not None:
            ok("runSim.py defines multi_ko_variant_kwargs()")
        else:
            bad("runSim.py has no multi_ko_variant_kwargs() — nothing builds the kwargs")
        if "variant_kwargs=variant_kwargs" in src.replace(" ", ""):
            ok("runSim.py hands variant_kwargs to VariantSimDataTask")
        else:
            bad("runSim.py never passes variant_kwargs to VariantSimDataTask — the flag would be INERT")
        # the EXT-PORT-12 provenance fix travels in the same file
        if "resolve_elongation_flags" in src:
            ok("runSim.py calls resolve_elongation_flags — metadata records the RESOLVED flags")
        else:
            bad("runSim.py does not call resolve_elongation_flags — a --kinetic-trna-charging run "
                "would record \"trna_charging\": true")

    # link 2 — variantSimData.py
    src = read(tree, VARIANT_FIRETASK)
    if src is None:
        bad("%s is absent" % VARIANT_FIRETASK)
    else:
        opt = [n for n in ast.parse(src).body if isinstance(n, ast.ClassDef)]
        listed = []
        for cls in opt:
            for node in cls.body:
                if (isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "optional_params"
                                for t in node.targets)):
                    listed = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
        if "variant_kwargs" in listed:
            ok("VariantSimDataTask.optional_params carries variant_kwargs")
        else:
            bad("VariantSimDataTask.optional_params lacks variant_kwargs — Fireworks raises on any "
                "kwarg it has not declared, so the multi-KO run dies at variant creation")
        if 'self.get("variant_kwargs")' in src or "self.get('variant_kwargs')" in src:
            ok("VariantSimDataTask passes variant_kwargs to apply_variant")
        else:
            bad("VariantSimDataTask never reads variant_kwargs — the gene set stops here and the run "
                "becomes a WILD TYPE wearing a knockout's label")

    # link 3 — apply_variant.py
    src = read(tree, APPLY_VARIANT)
    if src is None:
        bad("%s is absent" % APPLY_VARIANT)
    else:
        fn = func_def(src, "apply_variant")
        args = [a.arg for a in fn.args.args] if fn else []
        if "variant_kwargs" in args:
            ok("apply_variant(%s)" % ", ".join(args))
        else:
            bad("apply_variant has no variant_kwargs parameter — signature is (%s)" % ", ".join(args))
        if "**(variant_kwargs or {})" in src.replace(" ", "").replace(
                "**(variant_kwargsor{})", "**(variant_kwargs or {})"):
            ok("apply_variant splats variant_kwargs into the variant function")
        elif "variant_kwargs or {}" in src:
            ok("apply_variant splats variant_kwargs into the variant function")
        else:
            bad("apply_variant accepts variant_kwargs and never uses it")

    # link 4 — the variant module
    src = read(tree, MULTI_KO)
    if src is None:
        bad("%s is absent — the launch path's variant does not exist" % MULTI_KO)
    else:
        fn = func_def(src, "multi_gene_knockout")
        args = [a.arg for a in fn.args.args] if fn else []
        if args[:2] == ["sim_data", "index"] and "ko_indices" in args:
            ok("multi_gene_knockout(%s)" % ", ".join(args))
        else:
            bad("multi_gene_knockout signature is (%s) — expected (sim_data, index, ko_indices=None)"
                % ", ".join(args))


# --------------------------------------------------------------------------------------------------
# 3. Functional: run the shipped variant against a recording stub
# --------------------------------------------------------------------------------------------------
class _StubSimData:
    """The narrowest sim_data the variant touches: a length for the range check and a recorder for
    `adjust_final_expression`. Deliberately not a mock of the real object — the point is to catch a
    variant that silently adjusts NOTHING, and a permissive mock would hide exactly that."""

    def __init__(self, n_rna: int = 3276):
        class _T:
            rna_data = [None] * n_rna
        class _P:
            transcription = _T()
        self.process = _P()
        self.calls: list[tuple[list[int], list[float]]] = []

    def adjust_final_expression(self, idxs, vals):
        self.calls.append(([int(i) for i in idxs], [float(v) for v in vals]))


def load_by_path(tree: str, rel: str, mod_name: str):
    """Import a variant module by FILE PATH, bypassing `models.ecoli.sim.variants.__init__`.

    Importing it normally triggers the package's eager `nameToFunctionMapping`, which pulls in every
    other variant and therefore the whole reconstruction stack — including compiled Cython
    (`wholecell.utils.mc_complexation`) that is built inside the model image and cannot be built here.
    Loading by path tests the shipped file itself, which is what this check is about."""
    p = os.path.join(tree, rel.replace("/", os.sep))
    spec = importlib.util.spec_from_file_location(mod_name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_variant_behaviour(tree: str) -> None:
    print("\n[3] multi_gene_knockout, executed")
    if read(tree, MULTI_KO) is None:
        bad("cannot execute multi_gene_knockout — file absent")
        return
    try:
        mod = load_by_path(tree, MULTI_KO, "_cellarium_multi_ko")
    except Exception as exc:                                  # noqa: BLE001 - reported, not swallowed
        bad("multi_gene_knockout.py does not import: %s: %s" % (type(exc).__name__, exc))
        return
    fn = mod.multi_gene_knockout

    sd = _StubSimData()
    info, out = fn(sd, 0, ko_indices=[3, 7, 11])
    if sd.calls == [([2, 6, 10], [0.0, 0.0, 0.0])]:
        ok("ko_indices [3,7,11] -> adjust_final_expression([2,6,10], [0,0,0])  (1-based -> 0-based)")
    else:
        bad("wrong adjustment: %r" % (sd.calls,))
    if out is sd:
        ok("returns the modified sim_data")
    else:
        bad("does not return the sim_data it modified")
    if "3target_KO" in info.get("shortName", ""):
        ok("shortName %r" % info["shortName"])
    else:
        bad("shortName does not name the target count: %r" % info.get("shortName"))

    # The rejections. Each of these, if accepted, produces a run that completes and is mislabelled.
    rejects = [
        ("single index (that is a gene_knockout, not a multi)", dict(index=0, ko_indices=[5])),
        ("duplicate indexes", dict(index=0, ko_indices=[5, 5, 9])),
        ("zero / negative index", dict(index=0, ko_indices=[0, 5])),
        ("index past len(rna_data)", dict(index=0, ko_indices=[1, 10 ** 9])),
        ("non-integer index", dict(index=0, ko_indices=[1, "2"])),
        ("bool masquerading as int", dict(index=0, ko_indices=[True, 2])),
        ("no ko_indices at all", dict(index=0, ko_indices=None)),
        ("variant index != 0", dict(index=1, ko_indices=[1, 2])),
    ]
    for label, kw in rejects:
        sd2 = _StubSimData()
        try:
            fn(sd2, kw["index"], ko_indices=kw["ko_indices"])
        except (ValueError, TypeError):
            ok("rejects %s" % label)
        else:
            bad("ACCEPTS %s — the run would complete and be mislabelled" % label)


# --------------------------------------------------------------------------------------------------
# 4. Functional: run the shipped runSim validator, and parse runner.py's real command line
# --------------------------------------------------------------------------------------------------
def exec_function_from(src: str, name: str, ns: dict) -> object | None:
    """Compile ONE top-level function out of a source file and return it.

    `runSim.py` cannot be imported here — it pulls in `fireworks` (not installed) and the
    reconstruction stack (compiled Cython, numpy 1.x). Recompiling the single function under test out
    of the SHIPPED text is the difference between testing the file and testing a re-implementation of
    it, which is the failure this whole verification exists to avoid."""
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            mod = ast.Module(body=[node], type_ignores=[])
            exec(compile(mod, "<%s>" % name, "exec"), ns)          # noqa: S102 - our own source
            return ns[name]
    return None


def check_runsim_validation(tree: str) -> None:
    print("\n[4] runSim.multi_ko_variant_kwargs, executed out of the shipped file")
    src = read(tree, RUNSIM)
    if src is None:
        bad("runSim.py absent")
        return
    ns: dict = {}
    fn = exec_function_from(src, "multi_ko_variant_kwargs", ns)
    if fn is None:
        bad("multi_ko_variant_kwargs is not a top-level function in runSim.py")
        return

    spec = ("multi_gene_knockout", 0, 0)
    got = fn(spec, [1234, 2345], False)
    if got == {"ko_indices": [1234, 2345]}:
        ok("(multi_gene_knockout,0,0) + [1234,2345] -> %r" % got)
    else:
        bad("built the wrong kwargs: %r" % (got,))

    if fn(("gene_knockout", 5, 5), None, False) is None:
        ok("a non-multi variant with no --multi-ko-indices -> no kwargs (single KO unaffected)")
    else:
        bad("a plain gene_knockout picked up multi-KO kwargs")

    rejects = [
        ("--multi-ko-indices on a non-multi variant", (("gene_knockout", 5, 5), [1, 2], False)),
        ("a non-zero variant range", (("multi_gene_knockout", 0, 3), [1, 2], False)),
        ("--require-variants (the KO set defines the sim_data)", (spec, [1, 2], True)),
        ("missing --multi-ko-indices", (spec, None, False)),
        ("a single index", (spec, [7], False)),
        ("duplicates", (spec, [7, 7], False)),
        ("a non-positive index", (spec, [0, 7], False)),
    ]
    for label, argv in rejects:
        try:
            fn(*argv)
        except ValueError:
            ok("rejects %s" % label)
        else:
            bad("ACCEPTS %s" % label)


def check_argparse(tree: str) -> None:
    """Build runSim's REAL parser and feed it runner.py's REAL argv.

    `RunSimulation.define_parameters` is recompiled out of the shipped runSim.py and bound to a
    subclass of the shipped `scriptBase.ScriptBase`, so every option comes from shipped code. This is
    the check that `--multi-ko-indices` does not collide with an existing scriptBase option and that
    the argv `src/cellarium/runner.py:94` emits actually parses."""
    print("\n[5] runner.py's command line, against runSim's real parser")
    sys.path.insert(0, tree)
    try:
        import wholecell.utils.scriptBase as scriptBase  # noqa: PLC0415
    except Exception as exc:                                                  # noqa: BLE001
        skip("scriptBase does not import here (%s: %s) — parser check not run"
             % (type(exc).__name__, exc))
        return
    finally:
        pass

    src = read(tree, RUNSIM)
    node = func_def(src, "define_parameters", cls="RunSimulation")
    if node is None:
        bad("RunSimulation.define_parameters not found in runSim.py")
        return

    class RunSimulation(scriptBase.ScriptBase):
        # ScriptBase declares `run` abstract; this harness only ever builds the PARSER, so a stub is
        # what makes the class instantiable. Nothing here overrides define_parameters — that is
        # recompiled from the shipped runSim.py below.
        def run(self, args):
            raise AssertionError("parser-only harness")

    ns = {"scriptBase": scriptBase, "RunSimulation": RunSimulation}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<define_parameters>", "exec"),  # noqa: S102
         ns)
    RunSimulation.define_parameters = ns["define_parameters"]

    parser = argparse.ArgumentParser(prog="runSim.py")
    try:
        RunSimulation().define_parameters(parser)
    except Exception as exc:                                                  # noqa: BLE001
        bad("building runSim's parser raised %s: %s" % (type(exc).__name__, exc))
        return
    ok("runSim's parser builds (%d options)" % len(parser._actions))

    # The exact argv Cellarium emits. Imported from Cellarium so this cannot drift from the launcher.
    sys.path.insert(0, os.path.join(REPO, "src"))
    try:
        from cellarium.model import Design  # noqa: PLC0415
        from cellarium.runner import _variant_args  # noqa: PLC0415
    except Exception as exc:                                                  # noqa: BLE001
        skip("cellarium.runner not importable (%s) — using the literal argv instead" % type(exc).__name__)
        cases = [(["--variant", "multi_gene_knockout", "0", "0", "--multi-ko-indices", "12", "44"],
                  "multi_gene_knockout", [12, 44])]
    else:
        cases = []
        d = Design(perturbation="multi_gene_knockout", condition="KO:a+b",
                   params={"ko_indices": [12, 44]})
        cases.append((_variant_args(d), "multi_gene_knockout", [12, 44]))
        d = Design(perturbation="multi_gene_knockout", condition="KO:a+b",
                   params={"ko_indices": [12, 44]}, elongation_model="kinetic")
        cases.append((_variant_args(d), "multi_gene_knockout", [12, 44]))
        d = Design(perturbation="gene_knockout", condition="basal", params={"variant_index": 1234})
        cases.append((_variant_args(d), "gene_knockout", None))
        d = Design(perturbation="graded_gene_knockout", condition="basal",
                   params={"variant_index": 1789})
        cases.append((_variant_args(d), "graded_gene_knockout", None))

    for argv, want_variant, want_idxs in cases:
        try:
            args = parser.parse_args(["out"] + argv)
        except SystemExit:
            bad("runSim's parser REJECTS %s" % " ".join(argv))
            continue
        got_idxs = getattr(args, "multi_ko_indices", "<absent>")
        if args.variant[0] == want_variant and got_idxs == want_idxs:
            ok("parses %s -> variant=%s multi_ko_indices=%r"
               % (" ".join(argv), args.variant[0], got_idxs))
        else:
            bad("parsed %s to variant=%r multi_ko_indices=%r (wanted %r / %r)"
                % (" ".join(argv), args.variant[0], got_idxs, want_variant, want_idxs))


# --------------------------------------------------------------------------------------------------
# 5. The positional-condition literals
# --------------------------------------------------------------------------------------------------
def condition_order(tree: str) -> list[str]:
    src = read(tree, CONDITION_DEFS)
    if src is None:
        return []
    out = []
    for line in src.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith('"condition"'):
            continue
        out.append(line.split("\t", 1)[0].strip('"'))
    return out


def check_condition_lookups(tree: str) -> None:
    print("\n[6] condition lookups: by name, not by row number")
    order = condition_order(tree)
    if not order:
        skip("condition_defs.tsv not readable from this tree")
    else:
        ok("condition_defs.tsv ships %d rows; ordered_conditions is TSV ROW ORDER" % len(order))
        # The measurement that justifies shipping the fixes: what upstream's literal now resolves to.
        for lit, meant in ((2, "with_aa"), (1, "with_aa")):
            actual = order[lit] if lit < len(order) else "<out of range>"
            if actual != meant:
                ok("upstream's literal index %d resolves to %r here, NOT %r — a run that succeeds "
                   "while answering a different question" % (lit, actual, meant))
                notes.append("index %d -> %r (upstream meant %r)" % (lit, actual, meant))
            else:
                bad("index %d still resolves to %r — the fixes below would be unnecessary; check the "
                    "shipped condition_defs.tsv" % (lit, meant))

    checks = [
        (VARIANTS_DIR + "/ppgpp_conc.py",
         ["CONDITIONS = ['basal', 'with_aa']", "ordered_conditions.index"],
         ["CONDITIONS = [0, 2]"]),
        (VARIANTS_DIR + "/aa_synthesis_ko.py",
         ["condition_index(sim_data, 'with_aa')", "ordered_conditions.index"],
         ["condition(sim_data, 2)"]),
        (VARIANTS_DIR + "/rrna_operon_knockout.py",
         ["RICH_CONDITION_ID = 'with_aa'", "MINIMAL_TO_RICH_TIMELINE_ID", "raise ValueError"],
         ["condition_labels[1]", "timeline_ids[28]"]),
        (VARIANTS_DIR + "/tf_activity.py",
         ["timeline_id = tf +"],
         ["external_state.environment"]),
    ]
    for rel, musts, must_nots in checks:
        src = read(tree, rel)
        if src is None:
            bad("%s is absent" % rel)
            continue
        name = os.path.basename(rel)
        missing = [m for m in musts if m not in src]
        present = [m for m in must_nots if m in src]
        if missing:
            bad("%s: missing %s" % (name, missing))
        elif present:
            bad("%s: still carries the positional form %s" % (name, present))
        else:
            ok("%s: name lookups only" % name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tree", default=OVERLAY_FILES,
                    help="a checkout the overlay was applied to; defaults to model_overlay/files/")
    a = ap.parse_args(argv)
    tree = os.path.abspath(a.tree)
    # Is this a whole wcEcoli checkout, or just the overlay's own bodies? The discriminator has to be
    # a file UPSTREAM has and the overlay does NOT ship — `wholecell/utils/` was the first attempt and
    # is wrong, because the overlay ships `wholecell/utils/scriptBase.py` and so creates that
    # directory. `gene_knockout.py` is upstream's, is never overlaid, and is exactly the "single-gene
    # KO still works" file this script is here to check for.
    whole_tree = os.path.isfile(
        os.path.join(tree, *(VARIANTS_DIR + "/gene_knockout.py").split("/")))
    print("tree: %s%s" % (tree, "" if whole_tree else "   (overlay bodies only — some checks skip)"))

    check_registration(tree, whole_tree)
    check_channel(tree)
    check_variant_behaviour(tree)
    check_runsim_validation(tree)
    if whole_tree:
        check_argparse(tree)
    else:
        print("\n[5] runner.py's command line, against runSim's real parser")
        skip("needs a whole checkout (pass --tree)")
    check_condition_lookups(tree)

    print("\n%d failure(s), %d skipped" % (len(failures), len(skipped)))
    for f in failures:
        print("  FAIL  %s" % f)
    for s in skipped:
        print("  skip  %s" % s)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
