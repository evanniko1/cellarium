"""The ParameterProvenance listener, tested OFFLINE against a stand-in simulation.

WHAT THIS CAN AND CANNOT ESTABLISH, said first so the coverage is not over-read. A wcEcoli listener runs
inside the model container against a real sim_data and a real unique-molecule container. Applying the
overlay to the model checkout is out of scope here — that checkout belongs to a collaborator and this repo
does not write to it — so what is tested is the listener's ARITHMETIC, its index join, and its refusal
behaviour, against fakes shaped like the real objects. What is NOT tested is that a real generation runs
with it registered. That gap is stated in the docstring rather than papered over with a mock that asserts
itself.

The listener is imported from the overlay tree, so these tests fail if the file that ships diverges from the
file that was reasoned about. `wholecell.listeners.listener` does not exist here, so a minimal stand-in is
installed first — the base class contributes `time()`, `simulationStep()` and an `allocate()` hook, none of
which this listener's logic depends on.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
LISTENER = REPO / "model_overlay" / "files" / "models" / "ecoli" / "listeners" / "parameter_provenance.py"
BASELINE = REPO / "data" / "parca" / "deg_rate_baseline.json"


def _install_wholecell_stub():
    """The base class, reduced to what a listener actually inherits."""
    if "wholecell.listeners.listener" in sys.modules:
        return

    class Listener:
        def initialize(self, sim, sim_data):
            pass

        def allocate(self):
            pass

        def time(self):
            return 0.0

        def simulationStep(self):
            return 0

    pkg = types.ModuleType("wholecell")
    sub = types.ModuleType("wholecell.listeners")
    mod = types.ModuleType("wholecell.listeners.listener")
    mod.Listener = Listener
    pkg.listeners = sub
    sub.listener = mod
    sys.modules["wholecell"] = pkg
    sys.modules["wholecell.listeners"] = sub
    sys.modules["wholecell.listeners.listener"] = mod


def _load(index_path: Path):
    """Import the shipped listener with INDEX_PATH pointed at a chosen index."""
    _install_wholecell_stub()
    spec = importlib.util.spec_from_file_location("cellarium_pp_listener", LISTENER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.INDEX_PATH = str(index_path)
    return mod


# --------------------------------------------------------------------------------- stand-ins for the model

class _RNAs:
    def __init__(self, tu_indexes):
        self._tu = np.asarray(tu_indexes)

    def attrs(self, *names):
        n = len(self._tu)
        return self._tu, np.ones(n, dtype=bool), np.ones(n, dtype=bool)


class _Container:
    def __init__(self, tu_indexes):
        self._r = _RNAs(tu_indexes)

    def objectsInCollection(self, name):
        assert name == "RNA"
        return self._r


class _Unique:
    def __init__(self, tu_indexes):
        self.container = _Container(tu_indexes)


class _Sim:
    def __init__(self, tu_indexes):
        self.internal_states = {"UniqueMolecules": _Unique(tu_indexes)}


class _SimData:
    """`rna_data` with the two fields the listener reads, in the real id space."""

    def __init__(self, ids, is_mrna):
        rna_data = {"id": np.array(ids, dtype=object),
                    "is_mRNA": np.asarray(is_mrna, dtype=bool),
                    "is_rRNA": np.zeros(len(ids), dtype=bool)}
        self.process = types.SimpleNamespace(transcription=types.SimpleNamespace(rna_data=rna_data))


@pytest.fixture(scope="module")
def baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _mini_index(tmp_path: Path, floor=(), ceiling=(), imputed=(), kb="deadbeef") -> Path:
    p = tmp_path / "index.json"
    p.write_text(json.dumps({"kb_sha256": kb, "units_not_a_fit": {
        "floor": {u: 1.0 for u in floor},
        "ceiling": {u: 1.0 for u in ceiling},
        "imputed": {u: 1.0 for u in imputed}}}), encoding="utf-8")
    return p


# ------------------------------------------------------------------------------------------- the arithmetic

def test_it_weights_by_COUNTS_not_by_the_static_expression_vector(tmp_path):
    """The whole reason this listener exists. Two cells with the same knowledge base and different mRNA
    populations must report different numbers."""
    ids = ["TU-A[c]", "TU-B[c]", "TU-C[c]"]
    mod = _load(_mini_index(tmp_path, floor=["TU-A[c]"]))
    sd = _SimData(ids, [True, True, True])

    lis = mod.ParameterProvenance()
    lis.initialize(_Sim([0, 0, 0, 1, 2]), sd)       # 3 copies of A, 1 of B, 1 of C
    lis.allocate()
    lis.update()
    assert lis.index_ok == 1
    assert lis.n_mRNA == 5 and lis.n_mRNA_not_a_fit == 3
    assert lis.frac_counts_not_a_fit == pytest.approx(0.6)

    lis2 = mod.ParameterProvenance()
    lis2.initialize(_Sim([0, 1, 1, 1, 2]), sd)      # 1 copy of A now
    lis2.allocate()
    lis2.update()
    assert lis2.frac_counts_not_a_fit == pytest.approx(0.2)


def test_the_classes_are_reported_separately(tmp_path):
    """A bound and a population default are different claims; lumping them loses the distinction."""
    ids = ["TU-A[c]", "TU-B[c]", "TU-C[c]", "TU-D[c]"]
    mod = _load(_mini_index(tmp_path, floor=["TU-A[c]"], ceiling=["TU-B[c]"], imputed=["TU-C[c]"]))
    lis = mod.ParameterProvenance()
    lis.initialize(_Sim([0, 1, 2, 3]), _SimData(ids, [True] * 4))
    lis.allocate()
    lis.update()
    assert lis.frac_counts_on_floor == pytest.approx(0.25)
    assert lis.frac_counts_on_ceiling == pytest.approx(0.25)
    assert lis.frac_counts_imputed == pytest.approx(0.25)
    assert lis.frac_counts_not_a_fit == pytest.approx(0.75)


def test_non_mrna_units_are_excluded(tmp_path):
    ids = ["TU-A[c]", "RRNA-X[c]"]
    mod = _load(_mini_index(tmp_path, floor=["TU-A[c]"]))
    lis = mod.ParameterProvenance()
    lis.initialize(_Sim([0, 1, 1]), _SimData(ids, [True, False]))
    lis.allocate()
    lis.update()
    assert lis.n_mRNA == 1, "an rRNA unit was counted in the mRNA denominator"
    assert lis.frac_counts_not_a_fit == pytest.approx(1.0)


# ------------------------------------------------------------------------------------- fail loud, not clean

def test_a_missing_index_reports_NaN_and_not_zero(tmp_path):
    """0.0% would read as 'nothing rests on a placeholder' — the precise falsehood this listener prevents."""
    mod = _load(tmp_path / "absent.json")
    lis = mod.ParameterProvenance()
    lis.initialize(_Sim([0, 0]), _SimData(["TU-A[c]"], [True]))
    lis.allocate()
    lis.update()
    assert lis.index_ok == 0
    assert np.isnan(lis.frac_counts_not_a_fit)


def test_a_PARTIAL_join_is_refused_outright(tmp_path):
    """An index built against a different knowledge base matches some ids and not others. Reporting the
    fraction from the ones that matched understates the exposure by exactly the ones that did not, silently."""
    mod = _load(_mini_index(tmp_path, floor=["TU-A[c]", "TU-NOT-IN-THIS-KB[c]"]))
    lis = mod.ParameterProvenance()
    lis.initialize(_Sim([0]), _SimData(["TU-A[c]"], [True]))
    lis.allocate()
    lis.update()
    assert lis.n_units_expected == 2 and lis.n_units_matched == 1
    assert lis.index_ok == 0, "a partial join was accepted"
    assert np.isnan(lis.frac_counts_not_a_fit)


def test_a_cell_with_no_mrna_is_undefined_not_zero(tmp_path):
    mod = _load(_mini_index(tmp_path, floor=["TU-A[c]"]))
    lis = mod.ParameterProvenance()
    lis.initialize(_Sim([]), _SimData(["TU-A[c]"], [True]))
    lis.allocate()
    lis.update()
    assert lis.n_mRNA == 0
    assert np.isnan(lis.frac_counts_not_a_fit), "0/0 was published as 0.0"


def test_the_table_attributes_say_what_index_ok_means(tmp_path):
    mod = _load(tmp_path / "absent.json")
    lis = mod.ParameterProvenance()
    lis.initialize(_Sim([0]), _SimData(["TU-A[c]"], [True]))
    lis.allocate()
    written = {}

    class _W:
        def writeAttributes(self, **kw):
            written.update(kw)

    lis.tableCreate(_W())
    assert written["index_ok"] == 0
    assert "refusal to measure" in written["note"]


# ------------------------------------------------------------------------------- against the REAL baseline

def test_the_real_baseline_joins_completely_to_the_real_id_space(baseline):
    """The claim the whole design rests on: the frozen index and rna_data['id'] are the same id space.
    Measured in-container as 854/854; re-checked here against the committed baseline."""
    units = baseline["units_not_a_fit"]
    ids = [u for cls in ("floor", "ceiling", "imputed") for u in units[cls]]
    assert len(ids) == 854
    mod = _load(BASELINE)
    lis = mod.ParameterProvenance()
    lis.initialize(_Sim([0]), _SimData(ids, [True] * len(ids)))
    lis.allocate()
    assert lis.index_ok == 1
    assert lis.n_units_matched == lis.n_units_expected == 854
    assert lis.index_kb_sha256 == baseline["kb_sha256"]


def test_it_is_registered_last_in_the_overlay_simulation():
    """Registered last so it cannot affect an existing column, and imported so the name resolves."""
    sim = (REPO / "model_overlay" / "files" / "models" / "ecoli" / "sim" / "simulation.py"
           ).read_text(encoding="utf-8")
    assert "from models.ecoli.listeners.parameter_provenance import ParameterProvenance" in sim
    block = sim[sim.index("_listenerClasses = ("):]
    block = block[:block.index(")")]
    entries = [ln.strip().rstrip(",") for ln in block.splitlines()
               if ln.strip() and not ln.strip().startswith("#") and "_listenerClasses" not in ln]
    assert entries[-1] == "ParameterProvenance", entries[-3:]


def test_the_manifest_ships_it_and_records_the_patch():
    """A file that is not in the manifest is not applied to the model checkout, and an edit to a harvested
    file with no `cellarium_patch` block is silently reverted by the next overlay rebuild."""
    man = json.loads((REPO / "model_overlay" / "MANIFEST.json").read_text(encoding="utf-8"))
    by_path = {f["path"]: f for f in man["files"]}
    lis = by_path.get("models/ecoli/listeners/parameter_provenance.py")
    assert lis and lis["action"] == "create" and lis["status"] == "ship"
    sim = by_path["models/ecoli/sim/simulation.py"]
    assert sim.get("cellarium_patch"), "the registration would vanish on the next overlay rebuild"
    assert sim["cellarium_patch"]["verified_by"] == "tests/test_parameter_provenance_listener.py"


def test_the_shipped_hashes_match_the_shipped_files():
    """The manifest must describe the files on disk, or `apply_model_overlay.py` ships something else."""
    import hashlib

    man = json.loads((REPO / "model_overlay" / "MANIFEST.json").read_text(encoding="utf-8"))
    for rel in ("models/ecoli/listeners/parameter_provenance.py", "models/ecoli/sim/simulation.py"):
        rec = next(f for f in man["files"] if f["path"] == rel)
        body = (REPO / "model_overlay" / "files" / rel).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(body).hexdigest() == rec["overlay_sha256"], rel
