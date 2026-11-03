"""The tRNA charging refit must be reproducible when a seed is given, and unchanged when it is not.

THE DEFECT, measured by Alexey Yermakov on the cluster, 2026-10-30: `Relation.
optimize_trna_charging_kinetics` draws its random-restart initial points from the unseeded GLOBAL numpy
generator, so two Parca builds of the same knowledge base produce different synthetase constants. Every
comparison in the kinetic campaign that pits one knowledge base against another -- anchored against
unanchored, one anchor weight against the next -- rests on that not being true. scipy's Powell is
deterministic given x0, so seeding the four draws in `get_random_initial_solution` is sufficient.

WHY FOUR, AND WHY THAT IS THE TEST WITH TEETH. There are exactly four executable `uniform` draws in that
function: K_A, K_T, f and min_f. Routing three of them through the seeded generator and leaving one on
`np.random` restores the original defect in full -- the fit is still irreproducible -- while every
smoke test, every Parca run and every simulation continues to pass. Nothing else in this repository
would notice. `test_all_four_draws_are_seeded` is therefore the assertion this module exists for, and it
counts both directions: four through `rng`, zero through `np.random`.

Seeding is also load-bearing for the anchor-weight diagnostics: sweeping w_a on ONE synthetase is only a
valid comparison if that synthetase's restart sequence is independent of fitting order, which is what
`_synthetase_rng`'s crc32 keying buys over a single global seed.

These tests read the OVERLAY SOURCE and parse it, so they need neither Docker nor a wcEcoli checkout and
hold on CI. Two commented-out `np.random.uniform` alternatives survive in the vendor code; they are
absent from the AST by construction, which is why this is parsed rather than grepped.
"""
import ast
import hashlib
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "model_overlay" / "files"
MANIFEST = ROOT / "model_overlay" / "MANIFEST.json"

RELATION = "reconstruction/ecoli/dataclasses/relation.py"
FIT = "reconstruction/ecoli/fit_sim_data_1.py"
SCRIPTBASE = "wholecell/utils/scriptBase.py"
PARCA_TASK = "wholecell/fireworks/firetasks/parca.py"
FIT_TASK = "wholecell/fireworks/firetasks/fitSimData.py"

PATCHED = (RELATION, FIT, SCRIPTBASE, PARCA_TASK, FIT_TASK)
OPTION = "trna_charging_kinetics_seed"


def src(rel: str) -> str:
    p = OVERLAY / rel
    if not p.is_file():
        pytest.skip(f"{rel} is not shipped in this overlay")
    return io.open(p, encoding="utf-8").read()


def tree(rel: str) -> ast.Module:
    return ast.parse(src(rel))


def _func(node: ast.AST, name: str) -> ast.FunctionDef:
    for n in ast.walk(node):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"no function named {name!r}")


def _arg_names(fn: ast.FunctionDef) -> list[str]:
    a = fn.args
    return [x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs)]


def _default_for(fn: ast.FunctionDef, name: str):
    """The default expression for a keyword argument, or raise if it has none."""
    positional = [x.arg for x in (*fn.args.posonlyargs, *fn.args.args)]
    defaults = fn.args.defaults
    if name in positional:
        i = positional.index(name)
        first_with_default = len(positional) - len(defaults)
        assert i >= first_with_default, f"{name} has no default"
        return defaults[i - first_with_default]
    kwonly = [x.arg for x in fn.args.kwonlyargs]
    assert name in kwonly, f"{name} is not an argument"
    d = fn.args.kw_defaults[kwonly.index(name)]
    assert d is not None, f"{name} has no default"
    return d


# ---------------------------------------------------------------------------------------------------
# relation.py -- the generator, and the four draws
# ---------------------------------------------------------------------------------------------------

def test_synthetase_rng_is_defined_at_module_level():
    """Module level, not nested: the behavioural test below executes it in isolation, and a nested
    definition could not be reached that way."""
    fns = [n.name for n in tree(RELATION).body if isinstance(n, ast.FunctionDef)]
    assert "_synthetase_rng" in fns, (
        "_synthetase_rng is not a module-level function of relation.py")


def test_the_refit_takes_a_seed_defaulting_to_none():
    """Default None is what keeps an unseeded Parca bit-identical to v3.0.1."""
    fn = _func(tree(RELATION), "optimize_trna_charging_kinetics")
    assert "seed" in _arg_names(fn), "optimize_trna_charging_kinetics has no `seed` argument"
    d = _default_for(fn, "seed")
    assert isinstance(d, ast.Constant) and d.value is None, (
        "seed must default to None, so that not passing it reproduces the upstream fit")


def test_the_initial_solution_builder_takes_an_rng():
    fn = _func(tree(RELATION), "get_random_initial_solution")
    assert "rng" in _arg_names(fn), "get_random_initial_solution does not take an `rng`"


def _uniform_calls(fn: ast.FunctionDef) -> tuple[int, int]:
    """(draws through a bare `rng`, draws through `np.random`) inside this function."""
    via_rng = via_global = 0
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "uniform"):
            continue
        recv = n.func.value
        if isinstance(recv, ast.Name) and recv.id == "rng":
            via_rng += 1
        elif isinstance(recv, ast.Attribute) and recv.attr == "random":
            via_global += 1
        else:  # pragma: no cover - a third receiver would mean the code moved under us
            raise AssertionError(f"unrecognised uniform() receiver at line {n.lineno}")
    return via_rng, via_global


def test_all_four_draws_are_seeded():
    """THE assertion of this module. K_A, K_T, f and min_f must every one come from `rng`.

    Leaving a single draw on the global generator re-breaks reproducibility while every other check in
    this repository still passes, so this is counted in both directions rather than asserted as a
    presence."""
    fn = _func(tree(RELATION), "get_random_initial_solution")
    via_rng, via_global = _uniform_calls(fn)
    assert via_global == 0, (
        f"{via_global} random draw(s) in get_random_initial_solution still come from the global numpy "
        f"generator; the refit is not reproducible")
    assert via_rng == 4, (
        f"expected 4 seeded draws (K_A, K_T, f, min_f), found {via_rng} -- a draw was added or removed "
        f"and this test needs re-reading, not relaxing")


def test_every_call_site_passes_the_rng():
    """Three call sites (full-saturation, and the two restart branches). A site that omits `rng` would
    raise rather than silently mis-seed, but it would raise HOURS into a fit."""
    module = tree(RELATION)
    sites = [n for n in ast.walk(module)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "get_random_initial_solution"]
    assert len(sites) == 3, f"expected 3 call sites, found {len(sites)}"
    for call in sites:
        kw = {k.arg for k in call.keywords}
        assert "rng" in kw, f"call at line {call.lineno} does not pass rng="


def test_rng_falls_back_to_the_global_generator_when_unseeded():
    """`rng = _synthetase_rng(seed, synthetase) if seed is not None else np.random`.

    Without the else-branch an unseeded Parca would crash rather than reproduce v3.0.1, which is the
    compatibility promise the whole patch rests on."""
    fn = _func(tree(RELATION), "optimize_trna_charging_kinetics")
    found = None
    for n in ast.walk(fn):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "rng"
                and isinstance(n.value, ast.IfExp)):
            found = n.value
            break
    assert found is not None, "no conditional `rng = ... if seed is not None else ...` assignment"
    assert isinstance(found.body, ast.Call) and isinstance(found.body.func, ast.Name) \
        and found.body.func.id == "_synthetase_rng", "the seeded branch does not call _synthetase_rng"
    assert ast.unparse(found.orelse) == "np.random", (
        f"the unseeded branch is {ast.unparse(found.orelse)!r}, not np.random")


# ---------------------------------------------------------------------------------------------------
# _synthetase_rng, executed
# ---------------------------------------------------------------------------------------------------

def _rng_factory():
    """`_synthetase_rng` lifted out and executed on its own -- it needs only numpy and zlib, so this
    runs without the wcEcoli tree on sys.path."""
    np = pytest.importorskip("numpy")
    import zlib
    fn = next(n for n in tree(RELATION).body
              if isinstance(n, ast.FunctionDef) and n.name == "_synthetase_rng")
    ns: dict = {"np": np, "zlib": zlib}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<relation>", "exec"), ns)
    return ns["_synthetase_rng"]


def test_the_same_seed_and_synthetase_reproduce():
    f = _rng_factory()
    a = f(0, "LEUS-MONOMER[c]").uniform(0, 1, 8).tolist()
    b = f(0, "LEUS-MONOMER[c]").uniform(0, 1, 8).tolist()
    assert a == b, "the same (seed, synthetase) gave two different restart sequences"


def test_different_synthetases_get_different_streams():
    """Otherwise all 20 systems would start from identical points and the restart search would be
    correlated across them."""
    f = _rng_factory()
    a = f(0, "LEUS-MONOMER[c]").uniform(0, 1, 8).tolist()
    b = f(0, "ALAS-CPLX[c]").uniform(0, 1, 8).tolist()
    assert a != b, "two different synthetases drew the same sequence from the same seed"


def test_different_seeds_give_different_streams():
    f = _rng_factory()
    a = f(0, "LEUS-MONOMER[c]").uniform(0, 1, 8).tolist()
    b = f(1, "LEUS-MONOMER[c]").uniform(0, 1, 8).tolist()
    assert a != b, "changing the seed did not change the restart sequence"


def test_a_synthetases_stream_is_independent_of_fitting_order():
    """The property a single global seed does NOT have, and the reason an anchor-weight sweep on one
    synthetase is a valid comparison at all.

    The generator for LeuRS is taken BEFORE the intervening work and drawn from AFTER it. Taking a
    fresh one on each side instead would make this vacuous: an implementation that re-seeds the global
    generator per call and hands it back would pass, because each call would reset it. Measured — that
    mutation went undetected until this was restructured."""
    f = _rng_factory()
    reference = f(0, "LEUS-MONOMER[c]").uniform(0, 1, 8).tolist()

    leu = f(0, "LEUS-MONOMER[c]")                      # obtained first, read last
    for other in ("ALAS-CPLX[c]", "ARGS-MONOMER[c]", "TRPS-CPLX[c]"):
        f(0, other).uniform(0, 1, 100)                  # other systems fitted in between
    after = leu.uniform(0, 1, 8).tolist()

    assert after == reference, (
        "LeuRS's restart sequence was disturbed by work on other synthetases, so the refit's draws are "
        "shared state and a per-synthetase comparison is not valid")


# ---------------------------------------------------------------------------------------------------
# the option, plumbed through all four layers
# ---------------------------------------------------------------------------------------------------

def test_the_option_is_in_parca_keys():
    """PARCA_KEYS is what decides whether a command-line value reaches the Parca at all. Defining the
    option without listing it here produces a flag that parses and is silently dropped."""
    module = tree(SCRIPTBASE)
    keys = None
    for n in module.body:
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "PARCA_KEYS"):
            keys = [e.value for e in n.value.elts if isinstance(e, ast.Constant)]
    assert keys is not None, "PARCA_KEYS not found in scriptBase.py"
    assert OPTION in keys, f"{OPTION} is not in PARCA_KEYS, so the flag would be dropped silently"


def test_the_option_is_an_int_defaulting_to_none():
    s = src(SCRIPTBASE)
    assert f"'{OPTION}', int, default=None" in s, (
        f"{OPTION} is not declared as an int option defaulting to None")


@pytest.mark.parametrize("rel", [PARCA_TASK, FIT_TASK])
def test_each_firetask_allows_and_forwards_the_option(rel):
    """Both halves are needed: the key list admits it, the call passes it on. Either alone is a silent
    drop."""
    s = src(rel)
    assert f"'{OPTION}'," in s, f"{rel} does not list {OPTION} among its optional params"
    assert f"{OPTION}=self.get('{OPTION}')" in s, f"{rel} lists {OPTION} but never forwards it"


def test_fit_sim_data_reads_the_kwarg_and_passes_the_seed():
    s = src(FIT)
    assert f"kwargs.get('{OPTION}')" in s, f"fit_sim_data_1 never reads {OPTION}"
    assert "seed=seed," in s, "fit_sim_data_1 does not pass seed= to the optimiser"


def test_the_seed_is_recorded_in_the_provenance():
    """The provenance string is written into the three TSV headers and the log. A seeded build that
    does not say so is indistinguishable from an unseeded one after the fact -- the same class of
    defect as the run that could not prove its own configuration."""
    s = src(FIT)
    assert 'seed={"none" if seed is None else seed}' in s, (
        "the EXT-PORT-11 provenance string does not record the seed")


def test_the_provenance_still_cannot_break_its_tsv():
    """Non-vacuity guard on the test above. The provenance goes into a '#' comment line of a TSV
    written with quotechar="'", so a quote or a tab in it stops the line being a comment. The seed
    field is numeric today; the assertion must survive to catch the day it is not."""
    s = src(FIT)
    assert "set(provenance) & set(\"'\\\"\\t\\n\")" in s, (
        "the assertion keeping the provenance free of quote and separator characters is gone")


# ---------------------------------------------------------------------------------------------------
# the manifest must carry the edit forward
# ---------------------------------------------------------------------------------------------------

def test_the_manifest_records_the_patch_on_every_file_it_touched():
    """Without a `cellarium_patch` block, `scripts/build_model_overlay.py` re-harvests the file from
    source on the next rebuild and this change vanishes with a clean exit."""
    if not MANIFEST.is_file():
        pytest.skip("no overlay manifest")
    recs = {r["path"]: r for r in json.loads(io.open(MANIFEST, encoding="utf-8").read())["files"]}
    for rel in PATCHED:
        assert rel in recs, f"{rel} is not in the manifest"
        patch = recs[rel].get("cellarium_patch")
        assert patch, f"{rel} has no cellarium_patch block; the next rebuild would revert it"
        assert patch["verified_by"] == "tests/test_trna_refit_seed.py", (
            f"{rel}'s cellarium_patch does not name this module as its test")
        assert patch["harvested_sha256"] != recs[rel]["overlay_sha256"], (
            f"{rel}: the pre-patch and post-patch hashes are equal, so nothing was recorded as patched")


@pytest.mark.parametrize("rel", PATCHED)
def test_the_manifest_hash_matches_the_file_on_disk(rel):
    """`apply_model_overlay.py` refuses to install a file whose hash disagrees with the manifest, so a
    stale hash here blocks every fresh checkout. Hashed CRLF-normalised, as the manifest declares."""
    if not MANIFEST.is_file():
        pytest.skip("no overlay manifest")
    recs = {r["path"]: r for r in json.loads(io.open(MANIFEST, encoding="utf-8").read())["files"]}
    p = OVERLAY / rel
    if not p.is_file():
        pytest.skip(f"{rel} is not shipped in this overlay")
    body = io.open(p, "rb").read().replace(b"\r\n", b"\n")
    assert hashlib.sha256(body).hexdigest() == recs[rel]["overlay_sha256"], (
        f"{rel}: manifest hash does not match the shipped file")
    assert len(body) == recs[rel]["overlay_bytes"], f"{rel}: manifest byte count is stale"


# ---------------------------------------------------------------------------------------------------
# the seed is a per-BUILD quantity, not a design factor
# ---------------------------------------------------------------------------------------------------

def test_the_seed_is_declared_a_refit_factor():
    """Each seed value needs its own Parca build and therefore its own kb_sha256, so crossing the seed
    as an ordinary factorial column yields a panel that looks runnable and is not. Measured: the name
    matches none of doe._REFIT_HINTS either, so without this declaration it would pass unflagged."""
    from cellarium import doe
    assert OPTION in doe.REFIT_FACTORS, (
        f"{OPTION} is not in doe.REFIT_FACTORS; a design could cross it as a run-time factor")
    assert doe.refit_factors_in({OPTION: [0, 1]}) == [OPTION]
