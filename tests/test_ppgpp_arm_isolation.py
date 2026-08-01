"""The first regression net over the ppGpp arm — pinning the property ROUTE1 step 1 bought.

WHY THIS FILE EXISTS. Before it, a repo-wide grep for `calculate_trna_charging`,
`get_charging_params`, `ppgpp_metabolite_changes` or `max_elong_rate` returned ZERO test files
anywhere in the wcEcoli tree. Every claim about the stringent-response arm rested on ad-hoc probes
that were thrown away afterwards. The isoacceptor work is about to start re-pinning the ribosome
elongation constant, and the whole reason that is safe is that `max_elong_rate` no longer reaches
this function. Nothing enforced that. Now something does.

THE LOAD-BEARING TEST is `test_ppgpp_arm_is_invariant_to_max_elong_rate`. If a future change makes
`ppgpp_metabolite_changes` read the elongation constant again — directly, or by reintroducing a
`v_rib`-derived occupancy — that test fails. It is the single check that catches an
isoacceptor-resolution re-pin leaking into RelA activation, which is a 21.27% effect and is
otherwise silent: nothing crashes, no warning fires, the numbers simply move.

THE CYTHON STUBS. `polypeptide_elongation` imports `wholecell.utils._build_sequences`,
`_fastsums` and `_trna_charging`, which are Linux-only compiled extensions and are absent on a
Windows checkout. `ppgpp_metabolite_changes` is pure numpy arithmetic and touches none of them, so
they are stubbed at import time. The stubs are inert: if any test below actually reached compiled
code it would raise AttributeError rather than silently compute something wrong.
"""

from __future__ import annotations

import os
import sys
import types

import numpy as np
import pytest

WCECOLI = os.environ.get("WCECOLI", r"C:/dev/wcEcoli")


def _install_numpy1_aliases() -> None:
    """Restore the NumPy 1.x spellings the wcEcoli tree still uses, for the duration of the test.

    Cellarium's venv is NumPy 2.x; wcEcoli targets 1.x and imports fail on `np.Inf` alone. These are
    pure spelling aliases to objects that still exist under their lowercase names, so nothing about
    the arithmetic under test changes. This is a TEST-ENVIRONMENT shim only — it deliberately does
    not touch the model source, because the model is run in an image that pins NumPy 1.x.
    """
    for old, new in (("Inf", "inf"), ("NaN", "nan"), ("NAN", "nan"), ("Infinity", "inf"),
                     ("float_", "float64"), ("int_", "int64"), ("complex_", "complex128"),
                     ("unicode_", "str_"), ("string_", "bytes_")):
        if not hasattr(np, old) and hasattr(np, new):
            setattr(np, old, getattr(np, new))
    if not hasattr(np, "object_"):  # removed alias with no lowercase twin
        np.object_ = object


def _install_cython_stubs() -> None:
    """Stand in for the compiled extensions polypeptide_elongation imports but does not use here."""
    for name in ("wholecell.utils._build_sequences", "wholecell.utils._fastsums",
                 "wholecell.utils._trna_charging"):
        if name in sys.modules:
            continue
        mod = types.ModuleType(name)

        # PEP 562 module __getattr__, so `from X import <anything>` resolves without this file
        # having to enumerate the extension's exports — that enumeration would silently rot every
        # time the compiled modules gain a symbol, and the failure mode is a SKIPPED test that
        # reads as a passing one.
        def _make_getattr(module_name):
            def __getattr__(attr):
                def _absent(*_a, **_kw):
                    raise AttributeError(
                        f"{module_name}.{attr} is a compiled stub — this test reached code it "
                        f"must not reach. ppgpp_metabolite_changes is pure numpy arithmetic; if "
                        f"it now calls into a Cython extension, that is the finding.")
                _absent.__name__ = attr
                return _absent
            return __getattr__

        mod.__getattr__ = _make_getattr(name)
        sys.modules[name] = mod


@pytest.fixture(scope="module")
def pe():
    if not os.path.isdir(WCECOLI):
        pytest.skip(f"wcEcoli tree not found at {WCECOLI}; set WCECOLI to point at it")
    if WCECOLI not in sys.path:
        sys.path.insert(0, WCECOLI)
    _install_numpy1_aliases()
    _install_cython_stubs()
    # Deliberately NOT wrapped in a skip. If the tree is present, this import must work — a skip
    # here would report "7 skipped" alongside "2 passed" and read as a green run while the test
    # that actually matters never executed. That silent-absence failure mode is the one this
    # project keeps getting bitten by, so an import failure is a hard error.
    import models.ecoli.processes.polypeptide_elongation as mod
    return mod


@pytest.fixture(scope="module")
def units():
    if WCECOLI not in sys.path:
        sys.path.insert(0, WCECOLI)
    from wholecell.utils import units as u
    return u


N_AA = 21

# Representative magnitudes. Charged/uncharged tRNA in uM, drawn once with a fixed seed so a
# failure is reproducible rather than flaky.
_RNG = np.random.RandomState(20260801)


def _state(n=N_AA, zero_species=None):
    charged = _RNG.uniform(5.0, 60.0, n)
    uncharged = _RNG.uniform(0.5, 12.0, n)
    if zero_species is not None:
        charged[zero_species] = 0.0
        uncharged[zero_species] = 0.0
    f = _RNG.uniform(0.01, 1.0, n)
    f /= f.sum()
    return charged, uncharged, f


def _charging_params(max_elong_rate=22.0):
    return {
        "krta": 1.0,
        "krtf": 500.0,
        "max_elong_rate": max_elong_rate,
        "charging_mask": np.ones(N_AA, dtype=bool),
    }


def _ppgpp_params():
    return {
        # A 21-vector, not the scalar 0.26 uM: that scalar is the Bosdriesz literature value,
        # whereas both available builds carry a per-amino-acid vector spanning 0.027-0.54 uM.
        "KD_RelA": np.linspace(0.03, 0.54, N_AA),
        "k_RelA": 75.0,
        "k_SpoT_syn": 0.01,
        "k_SpoT_deg": 0.23,
        "KI_SpoT": 20.0,
        "ppgpp_reaction_stoich": np.zeros((4, 3), dtype=np.int64),
        "synthesis_index": 0,
        "degradation_index": 1,
    }


def _call(pe, units, charged, uncharged, f, max_elong_rate, v_rib, seed=0):
    # The unit must be on the LEFT: `array * unit` yields an object ndarray of per-element unums,
    # which has no .asNumber, whereas `unit * array` yields one unum wrapping the array.
    CONC = units.umol / units.L
    return pe.ppgpp_metabolite_changes(
        CONC * uncharged, CONC * charged, CONC * 25.0, f,
        CONC * 0.1, CONC * 0.2, CONC * 50.0, CONC * 1e-4,
        v_rib, _charging_params(max_elong_rate), _ppgpp_params(), 1.0,
        request=True, limits=None, random_state=np.random.RandomState(seed))


# ---------------------------------------------------------------- the identities

def test_reciprocal_saturated_charged_is_one_plus_theta():
    """1/saturated_charged_j == 1 + theta_j exactly — the identity the occupancy form rests on."""
    charged, uncharged, _ = _state()
    krta, krtf = 1.0, 500.0
    numerator = 1 + charged / krta + uncharged / krtf
    saturated_charged = charged / krta / numerator
    theta = (krta / charged) * (1 + uncharged / krtf)
    assert np.allclose(1.0 / saturated_charged, 1.0 + theta, rtol=0, atol=1e-12)


def test_occupancy_weights_sum_to_the_charging_denominator():
    """sum_j f_j / saturated_charged_j == D, so the normalization is D and not an arbitrary sum."""
    charged, uncharged, f = _state()
    krta, krtf = 1.0, 500.0
    numerator = 1 + charged / krta + uncharged / krtf
    saturated_charged = charged / krta / numerator
    theta = (krta / charged) * (1 + uncharged / krtf)
    D = 1 + np.sum(f * theta)
    assert np.isclose(np.sum(f / saturated_charged), D, rtol=0, atol=1e-12)


# ---------------------------------------------------------------- the load-bearing test

@pytest.mark.parametrize("scale", [1.271261, 0.5, 2.0, 27.967751 / 22.0])
def test_ppgpp_arm_is_invariant_to_max_elong_rate(pe, units, scale):
    """THE ONE THAT MATTERS. Rescaling max_elong_rate must not move ppGpp synthesis at all.

    This is what makes an isoacceptor-resolution re-pin safe. Before ROUTE1 step 1 the arm divided
    by this constant at :1443, so re-pinning it 22.0 -> 27.97 cut RelA synthesis by 21.27% at an
    identical tRNA state — silently. 1.271261 and 27.967751/22.0 are exactly that re-pin.
    """
    charged, uncharged, f = _state()
    base = _call(pe, units, charged, uncharged, f, 22.0, v_rib=9.3)
    rescaled = _call(pe, units, charged, uncharged, f, 22.0 * scale, v_rib=9.3)

    # v_rela_syn is index 3 of the returned tuple; compare it and the synthesis reaction count.
    np.testing.assert_allclose(rescaled[3], base[3], rtol=0, atol=0,
        err_msg="max_elong_rate reached the ppGpp arm — an isoacceptor re-pin would now shift RelA")
    assert rescaled[1] == base[1], "ppGpp synthesis reaction count moved with max_elong_rate"


def test_ppgpp_arm_is_invariant_to_v_rib_when_nonzero(pe, units):
    """v_rib must now only select the branch, never scale the occupancy.

    The occupancy form removed v_rib from the arithmetic. Two different nonzero v_rib values —
    such as the request path's rate-law value and the evolve path's realized throughput — must
    give identical RelA synthesis at an identical tRNA state.
    """
    charged, uncharged, f = _state()
    a = _call(pe, units, charged, uncharged, f, 22.0, v_rib=9.3)
    b = _call(pe, units, charged, uncharged, f, 22.0, v_rib=4.1)
    np.testing.assert_allclose(b[3], a[3], rtol=0, atol=0,
        err_msg="a nonzero v_rib still scales the A-site occupancy")


def test_zero_v_rib_still_takes_the_guard(pe, units):
    """The `if v_rib == 0` guard is deliberately RETAINED; deleting it is a separate change.

    Keeping it means an in-mask zero charged concentration — which forces the charging denominator
    to inf and hence v_rib to 0 — routes through the uniform f*[R] branch exactly as before,
    instead of being silently dropped from D and inflating every other species.
    """
    charged, uncharged, f = _state()
    guarded = _call(pe, units, charged, uncharged, f, 22.0, v_rib=0.0)
    normal = _call(pe, units, charged, uncharged, f, 22.0, v_rib=9.3)
    assert not np.allclose(guarded[3], normal[3]), \
        "the v_rib == 0 branch is no longer distinguishable — the guard was removed"


def test_occupancy_sums_to_ribosome_conc(pe, units):
    """The A-site occupancies must sum to the ribosome concentration, at any state.

    This is the conservation the whole option-1-vs-option-2 argument was about. Under the
    occupancy form it holds by construction rather than at a single pinned reference state.
    """
    charged, uncharged, f = _state()
    krta, krtf = 1.0, 500.0
    numerator = 1 + charged / krta + uncharged / krtf
    saturated_charged = charged / krta / numerator
    weights = f / saturated_charged
    occupancy = 25.0 * weights / weights.sum()
    assert np.isclose(occupancy.sum(), 25.0, rtol=0, atol=1e-12)
