"""ROUTE1 step 1 — rewrite the A-site occupancy at its derived form, removing k_el^max from the ppGpp arm.

WHAT THIS CHANGES. One expression, `ribosome_conc_a_site`, inside `ppgpp_metabolite_changes`
(models/ecoli/processes/polypeptide_elongation.py:1443). Today:

    ribosome_conc_a_site = f * v_rib / (saturated_charged * charging_params['max_elong_rate'])

After:

    a_site_weights          = f / saturated_charged                 # == f_j * (1 + theta_j)
    occupancy_denominator   = sum(finite a_site_weights)            # == D
    ribosome_conc_a_site    = ribosome_conc * a_site_weights / occupancy_denominator

WHY. The quantity this line computes is a renewal-theory occupancy. A ribosome sitting at a codon
that demands tRNA species j waits there for a time proportional to (1 + theta_j), where
theta_j = (K_rta/c_j)(1 + u_j/K_rtf), so the fraction of ribosomes found at such a codon is

    R_j / [R] = f_j * (1 + theta_j) / D,        D = 1 + sum_j f_j * theta_j

k_el^max is ABSENT. It cancels identically — at any resolution, in any state, under any pin. Three
identities carry that, each re-derived independently by two checkers rather than asserted:

  (1) 1/saturated_charged_j == 1 + theta_j EXACTLY. From :1437-1438,
      saturated_charged_j = (c_j/K_rta) / (1 + c_j/K_rta + u_j/K_rtf), whose reciprocal is
      1 + (K_rta/c_j)(1 + u_j/K_rtf). MEASURED max error 6.66e-16 / 8.88e-16 on two independent
      sets of random states. So `f / saturated_charged` IS the occupancy weight vector and its sum
      IS D as computed at :1682.
  (2) Substituting v_rib = k_el^max * [R] / D (read at :1683 and :1708-1709) into the CURRENT
      expression yields exactly [R] * f_j * (1 + theta_j) / D. MEASURED max relative difference
      2.22e-16 / 4.44e-16.
  (3) (1 + theta_j) * saturated_uncharged_j == (K_rta/K_rtf) * (u_j/c_j) EXACTLY (residual 5.4e-20
      / 1.73e-18), so the whole RelA driver reduces to
          RBU_j = [R] * f_j * (K_rta/K_rtf) * (u_j/c_j) / D.

(3) is the decision-relevant one. It shows the RelA driver can be reached by a change of resolution
through EXACTLY TWO doors: the ratio u_j/c_j, and D. Under a 21->86 isoacceptor split at uniform
within-family charged fraction, u_i/c_i is INVARIANT (measured within-family relative sd <= 7.08e-4,
enforced by initial_conditions.py:110 rounding charged_i = total_i * frac_charged_a). So the entire
question of whether the 86-state split perturbs ppGpp reduces to WHICH D sits in that denominator.

WHAT THAT BUYS, CONCRETELY. With the ppGpp arm at 21-amino-acid resolution (the configuration
chosen for this project) and this edit in place, D_86 has NO PATH into the arm at all — not by
convention but by construction: `calculate_trna_charging` returns exactly five values at :1693
(new_fraction_charged, v_rib, total_synthesis, total_import, total_export) and D is not among them,
and `ppgpp_metabolite_changes` is a module-level function called with an explicit argument list at
:1184-1189 and :1260-1265. Once the v_rib term is gone, the arm computes D locally from the
21-aggregated pools it was handed at :1181-1183 / :1247-1250. MEASURED: A-site sum ratio to 1 within
2.2e-16, and EXACT split-invariance at 0.000e+00 — hold the aggregate pools fixed, vary the
within-family split arbitrarily, and the RelA driver does not move.

Without this edit and with an 86-derived v_rib, the same arm reproduces a 1/r factor to 14
significant figures (0.78662030675730 against 1/r = 0.78662031, seed-independent), i.e. a 21.271%
drop in RelA synthesis at t=1. That is the configuration this edit exists to avoid.

MEASURED COST AT 21 RESOLUTION. The new form differs from the running code by a single scalar
Phi = D * effectiveElongationRate / k_el^max, IDENTICAL across all 21 amino acids (within-step
spread across amino acids 4.44e-16, so nothing re-ranks). Phi sits just below 1: median 0.999917
(operons OFF, 88.3% of steps below 1) and 0.999965 (ON, 100.0% below 1), min 0.989171, max 1.002968.
Total RelA synthesis therefore moves +0.009% (OFF) / +0.004% (ON) median, range -0.205% to +1.016%.

    ACCEPTANCE CRITERION: re-run the two distinct SteadyState+ppGpp configs and diff
    GrowthLimits/rela_syn. IF YOU SEE ANYTHING OF ORDER 10% ON THE ON RUN, STOP — the model of this
    change is wrong. Expect the request path (:1184-1189) to be a no-op to ~1e-16 relative but NOT
    bit-identical (the arm receives total_trna_conc*fraction_charged at :1182-1183 while :1682's D
    is built from final_charged_trna_conc), and note that a 1e-16 difference CAN flip a
    stochasticRound boundary at :1469-1470, so isolated whole-count divergences are expected and are
    not a bug. The evolve path (:1260-1265) is NOT a no-op — :1243 supplies realized
    nElongations*counts_to_molar/dt — so ppGpp counts shift at :1272 and trajectories diverge.

IT ALSO FIXES A LIVE DEFECT, independent of any isoacceptor work. Under the current form the
`v_rib == 0` branch sets ribosome_conc_a_site = f * [R], which is the ZERO-WAITING limit applied in
the one regime where waiting is MAXIMAL (total starvation), and it is discontinuous: as v_rib -> 0+
the normal branch sends R_j -> 0, but AT v_rib == 0 it jumps to f_j*[R]. Under the occupancy form
the limit is correct and continuous — as one c_j -> 0 its theta_j -> inf and ribosomes pile onto the
scarcest species, which is exactly the RelA signal. That branch is inherited verbatim from
v3.0.1 (vendor/v301/), not introduced in this tree.

TWO DELIBERATE CHOICES THAT LOOK LIKE OVERSIGHTS. Both were measured, and going the other way is
provably worse:

  * THE `if v_rib == 0` GUARD IS KEPT, not deleted. Deleting it and relying on the continuous limit
    is a legitimate change but a SEPARATE one, and it must not be smuggled in here. Keeping it
    removes two of four known behavioural exceptions at zero cost. In particular an IN-MASK zero
    charged concentration forces numerator_ribosome -> inf at :1682 and hence v_rib -> 0 (via :1683
    and the non-finite zeroing at :1712-1713), so it routes through the guard EXACTLY as today —
    whereas a guard-free occupancy form would silently drop that species from D and inflate every
    other species by 1/(truncated D).

  * THE DENOMINATOR SUMS ALL 21, NOT charging_params['charging_mask']. The masked variant is worse
    by exactly 1/theta_SEL: sum over mask = D_1682 - f_SEL, whereas sum over all 21
    = D_1682 + f_SEL*theta_SEL. MEASURED over 120 real timesteps of kinetic_parca_operons_off:
    all-21 max relative deviation from :1682's D = 1.7215e-06, masked = 6.2198e-06, ratio 3.613
    = 1/theta_SEL (theta_SEL mean 0.2768). The masked form also breaks the sum-to-[R] normalization.

WHAT IS NOT TOUCHED. :1444 (ribosomes_bound_to_uncharged) and the non-finite mask block at
:1446-1451 are left exactly as they are — the mask remains the safety net for out-of-mask zeros.
`v_rib` stays in the signature: it is still read by the retained :1440 guard, and there are three
positional call sites (:1186, :1262, runscripts/debug/charging.py:343). After this edit
charging_params['max_elong_rate'] is read NOWHERE inside this function; its only read was :1443.
That is the property the accompanying test pins.

COST. +2.1 to +4.3 us/call for the sanitized block as written (an earlier +0.74 us figure
benchmarked a bare weights/sum/normalize with no errstate/isfinite/where). Negligible against
solve_ivp BDF at :1668.

    python scripts/route1_occupancy_patch.py --wcecoli C:/dev/wcEcoli [--check]

Idempotent and marker-guarded: applying it to an already-patched tree is a no-op.
"""

from __future__ import annotations

import argparse
import io
import os
import sys

REL = "models/ecoli/processes/polypeptide_elongation.py"

MARKER = "ROUTE1-21"

# The exact text being replaced. Tab-indented, matching the file. Anchored on the whole if/else so
# that a tree whose guard has already been altered fails loudly rather than being patched blind.
OCC_OLD = (
    "\tif v_rib == 0:\n"
    "\t\tribosome_conc_a_site = f * ribosome_conc\n"
    "\telse:\n"
    "\t\tribosome_conc_a_site = f * v_rib / (saturated_charged * charging_params['max_elong_rate'])\n"
)

OCC_NEW = (
    "\tif v_rib == 0:\n"
    "\t\tribosome_conc_a_site = f * ribosome_conc\n"
    "\telse:\n"
    "\t\t# ROUTE1-21: the A-site occupancy in the form it is derived from, rather than as a\n"
    "\t\t# throughput divided by a rate constant. Since 1/saturated_charged_j == 1 + theta_j\n"
    "\t\t# exactly and v_rib == max_elong_rate * ribosome_conc / D, the old expression equals\n"
    "\t\t# ribosome_conc * f_j * (1 + theta_j) / D with max_elong_rate cancelling identically.\n"
    "\t\t# Writing it that way is not a normalization applied after the fact: it restores the\n"
    "\t\t# renewal-theory occupancy the previous line was an approximation to, and it is exact\n"
    "\t\t# only here -- the old form agreed only when v_rib was the rate law's OWN k*[R]/D at\n"
    # NOTE: line-number citations were REMOVED from this comment on purpose. It went stale twice --
    # once from its own patch shifting the file, and again when the ROUTE1 resolution block was added
    # above get_charging_params. Naming the call sites survives both.
    "\t\t# the same resolution with the same k, which is true on the request path (the v_rib\n"
    "\t\t# computed inside calculate_trna_charging feeds the ppgpp_metabolite_changes call in\n"
    "\t\t# calculateRequest) and FALSE on the evolve path, where evolveState supplies polymerize's\n"
    "\t\t# REALIZED nElongations*counts_to_molar/dt instead. Named rather than cited by line: this\n"
    "\t\t# comment has already been stale twice, once from its own patch and once from the block\n"
    "\t\t# added above get_charging_params.\n"
    "\t\t# Consequence that matters: max_elong_rate is now read nowhere in this\n"
    "\t\t# function, so re-pinning it for an isoacceptor-resolved charging ODE cannot reach the\n"
    "\t\t# ppGpp arm. See scripts/route1_occupancy_patch.py for the measurements.\n"
    "\t\t#\n"
    "\t\t# The sum runs over ALL 21, not charging_params['charging_mask']: masking gives\n"
    "\t\t# D - f_SEL instead of D + f_SEL*theta_SEL, an error larger by 1/theta_SEL (measured\n"
    "\t\t# 3.613x over 120 timesteps), and breaks the sum-to-ribosome_conc normalization.\n"
    "\t\twith np.errstate(divide='ignore', invalid='ignore'):\n"
    "\t\t\ta_site_weights = f / saturated_charged\n"
    "\t\toccupancy_denominator = np.where(\n"
    "\t\t\tnp.isfinite(a_site_weights), a_site_weights, 0.).sum()\n"
    "\t\tribosome_conc_a_site = ribosome_conc * a_site_weights / occupancy_denominator\n"
)

# The docstring for v_rib, which no longer describes what the parameter is used for.
DOC_OLD = (
    "\t\tv_rib (float): rate of amino acid incorporation at the ribosome,\n"
    "\t\t\tin units of uM/s\n"
)

DOC_NEW = (
    "\t\tv_rib (float): rate of amino acid incorporation at the ribosome,\n"
    "\t\t\tin units of uM/s. ROUTE1-21: this is now read ONLY by the\n"
    "\t\t\t`v_rib == 0` guard below. The A-site occupancy no longer divides\n"
    "\t\t\tby it, so a nonzero v_rib computed at a DIFFERENT tRNA resolution\n"
    "\t\t\tfrom the pools passed above can no longer perturb this function.\n"
)


def _read(path: str) -> tuple[str, str]:
    with io.open(path, encoding="utf-8", newline="") as fh:
        txt = fh.read()
    return txt, ("\r\n" if "\r\n" in txt else "\n")


def _write(path: str, txt: str, nl: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(txt)


def _norm(s: str, nl: str) -> str:
    """Render an LF-authored anchor in the file's own line ending."""
    return s.replace("\n", nl) if nl != "\n" else s


def status(wcecoli: str) -> dict:
    path = os.path.join(wcecoli, REL)
    if not os.path.isfile(path):
        return {"present": False, "occupancy": False, "docstring": False}
    txt, nl = _read(path)
    return {
        "present": True,
        "occupancy": MARKER in txt and _norm(OCC_OLD, nl) not in txt,
        "docstring": "ROUTE1-21: this is now read ONLY by the" in txt,
    }


def run(wcecoli: str, check: bool = False) -> dict:
    st = status(wcecoli)
    if not st["present"]:
        return {"complete": False, "wrote": [], "files": [],
                "why": f"{REL} not found under {wcecoli}"}
    if all(st.values()):
        return {"complete": True, "wrote": [], "files": [], "status": st,
                "why": "already applied"}
    if check:
        return {"complete": False, "wrote": [], "files": [], "status": st,
                "why": "not applied; run without --check"}

    path = os.path.join(wcecoli, REL)
    txt, nl = _read(path)
    wrote: list[str] = []

    if not st["occupancy"]:
        old = _norm(OCC_OLD, nl)
        # Refuse to guess. If the guard or the expression has drifted, a blind replace would
        # either silently do nothing or patch the wrong site.
        if txt.count(old) != 1:
            return {"complete": False, "wrote": wrote, "files": [], "status": st,
                    "why": f"expected exactly 1 occurrence of the ribosome_conc_a_site if/else "
                           f"block in {REL}, found {txt.count(old)} — refusing to guess. The "
                           f"anchor covers the whole `if v_rib == 0:` block, so a tree whose "
                           f"guard already differs will land here rather than be patched blind."}
        txt = txt.replace(old, _norm(OCC_NEW, nl), 1)
        wrote.append(f"{REL}: ribosome_conc_a_site -> renewal-theory occupancy form")

    if not st["docstring"]:
        old = _norm(DOC_OLD, nl)
        if txt.count(old) != 1:
            return {"complete": False, "wrote": wrote, "files": [], "status": st,
                    "why": f"expected exactly 1 v_rib docstring entry in {REL}, found "
                           f"{txt.count(old)}"}
        txt = txt.replace(old, _norm(DOC_NEW, nl), 1)
        wrote.append(f"{REL}: v_rib docstring now says what v_rib is still used for")

    _write(path, txt, nl)
    st2 = status(wcecoli)
    return {"complete": all(st2.values()), "wrote": wrote, "files": [REL], "status": st2}


def revert(wcecoli: str) -> dict:
    """Put the file back exactly as it was, so a CONTROL image can be built from the same tree.

    This exists to make the A/B honest. The first acceptance run compared a rebuilt image against
    baselines produced by an image that could no longer be identified, so it could not isolate this
    change from six unrelated ones also sitting in the tree. Building a control from the SAME tree
    with only this edit reverted removes that confound entirely.

    It is the exact inverse of run(): the same two anchors, applied in reverse, each still required
    to appear exactly once. Reverting a tree that is already reverted is a no-op.

    THE CALLER MUST RE-APPLY. Leaving the tree reverted would silently un-fix the ppGpp arm for every
    later run, so callers must treat revert/build/re-apply as one atomic sequence and VERIFY the
    re-apply, not assume it.
    """
    path = os.path.join(wcecoli, REL)
    if not os.path.isfile(path):
        return {"complete": False, "wrote": [], "why": f"{REL} not found under {wcecoli}"}
    txt, nl = _read(path)
    wrote: list[str] = []

    for label, new, old in (("occupancy", OCC_NEW, OCC_OLD), ("docstring", DOC_NEW, DOC_OLD)):
        cur = _norm(new, nl)
        if cur not in txt:
            continue  # already reverted, or never applied
        if txt.count(cur) != 1:
            return {"complete": False, "wrote": wrote,
                    "why": f"expected exactly 1 {label} block to revert in {REL}, found {txt.count(cur)}"}
        txt = txt.replace(cur, _norm(old, nl), 1)
        wrote.append(f"{REL}: {label} reverted")

    _write(path, txt, nl)
    st = status(wcecoli)
    reverted = not st["occupancy"] and not st["docstring"]
    return {"complete": reverted, "wrote": wrote, "status": st,
            "why": "" if reverted else "revert did not clear both markers"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wcecoli", default=os.environ.get("WCECOLI", "C:/dev/wcEcoli"))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true",
                    help="undo the edit so a CONTROL image can be built from the same tree; "
                         "the caller MUST re-apply afterwards and verify")
    a = ap.parse_args(argv)
    if a.revert:
        r = revert(a.wcecoli)
        for w in r.get("wrote", []):
            print(f"  reverted {w}")
        if r.get("why"):
            print(f"  {r['why']}")
        print(f"status: {r.get('status')}")
        print("REVERTED" if r["complete"] else "REVERT FAILED")
        return 0 if r["complete"] else 1
    r = run(a.wcecoli, check=a.check)
    for w in r.get("wrote", []):
        print(f"  wrote {w}")
    if r.get("why"):
        print(f"  {r['why']}")
    print(f"status: {r.get('status')}")
    print("COMPLETE" if r["complete"] else "NOT COMPLETE")
    return 0 if r["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
