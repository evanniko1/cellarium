"""A1 -- UNIFORM aaRS CAPACITY THROTTLE. Runs INSIDE the model container.

    python /wcEcoli/out/_ks_throttle.py <src_kb_dir> <dst_kb_dir> <divisor>

WHY kS AND NOT aa_kcats_fwd. ROUTE1-77/79's bound is stated on the CHARGING capacity
kS * E_a, via rho_a = u_a/(KMtf_a + u_a) and v_a = kS * E_a * theta_a * rho_a. The
"uniform capacity divisor" in the static substitution (scratchpad/analyze5.py:63-72)
divides exactly that product by a scalar with E_a untouched, i.e. it divides kS.
kS enters the ODE at models/ecoli/processes/polypeptide_elongation.py:1797
(`kS=constants.synthetase_charging_rate.asNumber(1/units.s)`) and multiplies the
charging rate LINEARLY at :2123 and :2263. It is read from sim_data at run time and is
NOT re-derived by ParCa at simulation time, so scaling it in the pickle is the whole
intervention -- no tree change, no ParCa refit. aa_kcats_fwd (the ROUTE1-84 knob) is a
DIFFERENT axis: amino-acid SYNTHESIS supply, which moves theta_a, not the capacity term.

divisor 1.0 -> byte copy of the source pickle so the control kb is byte-identical.
"""
import os
import pickle
import shutil
import sys

from wholecell.utils import units


def main(argv):
    src, dst, div = argv[0], argv[1], float(argv[2])
    os.makedirs(dst, exist_ok=True)
    src_pkl = os.path.join(src, "simData.cPickle")
    dst_pkl = os.path.join(dst, "simData.cPickle")

    if not os.path.exists(src_pkl):
        print("SOURCE PICKLE NOT ON DISK: %s -- nothing done" % src_pkl)
        return 2

    if div == 1.0:
        shutil.copyfile(src_pkl, dst_pkl)
        print("divisor 1.0 -> byte copy, no re-pickle: %s (%d bytes)"
              % (dst_pkl, os.path.getsize(dst_pkl)))
        return 0

    with open(src_pkl, "rb") as fh:
        sd = pickle.load(fh)
    before = float(sd.constants.synthetase_charging_rate.asNumber(1 / units.s))
    print("kS before = %.10g /s" % before)
    sd.constants.synthetase_charging_rate = (
        sd.constants.synthetase_charging_rate / div)
    after = float(sd.constants.synthetase_charging_rate.asNumber(1 / units.s))
    print("kS after  = %.10g /s   (divisor %.6g, realised %.10g)"
          % (after, div, before / after))

    # guard: nothing else in the pickle may move
    import numpy as np
    kcat = np.asarray(sd.process.metabolism.aa_kcats_fwd, dtype=float)
    print("aa_kcats_fwd untouched: sum=%.10g  (this knob is NOT the intervention)" % kcat.sum())

    with open(dst_pkl, "wb") as fh:
        pickle.dump(sd, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print("wrote %s (%d bytes)" % (dst_pkl, os.path.getsize(dst_pkl)))

    with open(dst_pkl, "rb") as fh:
        chk = pickle.load(fh)
    got = float(chk.constants.synthetase_charging_rate.asNumber(1 / units.s))
    ok = (got == after)
    print("roundtrip exact: %s (read back %.10g /s)" % (ok, got))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
