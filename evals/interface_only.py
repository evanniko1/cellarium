"""PX-1: what the representability gate refuses that an interface-level compatibility check would admit.

PRAXIS-VirtualCell (arXiv:2609.29221) checks, before execution, whether a request is compatible with what a model
DECLARES it accepts: species, inputs, perturbations, outputs, feature space. It reads no model source, and nothing in
it asks whether the model's mechanisms compute the requested quantity. Cellarium's gate asks exactly that, from
records read from the simulator's source.

This module defines the interface-level check for wcEcoli as generously as it can be defined, so that the
comparison is not against a straw man, and scores it on the gate's two question banks against the same keys:

  loose   the simulator can be configured with the intervention, and it writes an output for the observable;
  strict  in addition, the request's resolution exists at the interface: the input can name what the question
          names, and an output column carries the granularity it asks for.

The table is read off the registry's own `instead` prose for every capability and mode the registry does NOT
represent, which records what the simulator does there: the columns it broadcasts, zeroes or holds constant. A
column that exists is what an interface check sees; whether it means anything is what it cannot.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cellarium import capability as C  # noqa: E402


@dataclass(frozen=True)
class Interface:
    accepts: bool      # the simulator can be configured with the intervention the question names
    writes: bool       # it writes an output for the observable
    resolves: bool     # the input can name, and an output carries, the resolution the question asks for
    evidence: str

    def admits(self, *, strict: bool) -> bool:
        return self.accepts and self.writes and (self.resolves or not strict)


_REPRESENTED = Interface(True, True, True, "represented: the registry holds this capability in this mode")

_ISO_STEADY = ("86 per-isoacceptor charging columns are written, broadcast from a 20-state solution indexed by amino "
               "acid, so isoacceptors of one amino acid always read the same")
_ISO_COARSE = "86 per-isoacceptor charging columns are written, every one an exact zero"
_CODON = ("an elongation rate is written per amino acid; no per-codon output exists, because codon identity never "
          "reaches the rate in this mode")
_OPERON = ("the rRNA-operon variant takes a COUNT of operons, not an identity, and the seven per-row synthesis "
           "probabilities it writes are re-averaged, so no row ends at zero")
_TRNA_ABUNDANCE = ("86 per-gene tRNA counts are written, derived from about 44 species measurements by dividing each "
                   "by a gene count")
_PHOSPHATE = ("a phosphate-free medium is accepted and growth is written; the phosphate pools never respond, so "
              "PhoR-PhoB is never activated")
_GLUCOSE = ("any glucose concentration is accepted and growth is written; above 1e-5 mM every dose gives the same "
            "cell, because uptake is a binary switch")
_NO_CARBON = ("a glucose-free medium is accepted and growth is written; biomass keeps being made with almost no "
              "carbon taken up")
_AA_COARSE = "86 charging columns are written, all zeros"
_PPGPP = ("ppGpp is written, held at a constant target; the RelA, SpoT and GrowthLimits ppGpp columns read zero")
_UPTAKE = ("an amino-acid supplement is accepted and exchange fluxes are written; the uptake rates stay at their "
           "initial zeros")

UNREPRESENTED: dict[tuple[str, str], Interface] = {
    ("per_isoacceptor_trna_charging", "steady_state"): Interface(True, True, True, _ISO_STEADY),
    ("per_isoacceptor_trna_charging", "coarse_kinetic"): Interface(True, True, True, _ISO_COARSE),
    ("codon_level_elongation", "steady_state"): Interface(True, True, False, _CODON),
    ("codon_level_elongation", "coarse_kinetic"): Interface(True, True, False, _CODON),
    **{("operon_specific_rrna_knockout", m): Interface(True, True, False, _OPERON) for m in C.ELONGATION_MODES},
    **{("per_gene_trna_abundance", m): Interface(True, True, True, _TRNA_ABUNDANCE) for m in C.ELONGATION_MODES},
    **{("growth_under_phosphate_depletion", m): Interface(True, True, True, _PHOSPHATE) for m in C.ELONGATION_MODES},
    **{("response_to_the_glucose_concentration", m): Interface(True, True, True, _GLUCOSE)
       for m in C.ELONGATION_MODES},
    **{("growth_without_a_carbon_source", m): Interface(True, True, True, _NO_CARBON) for m in C.ELONGATION_MODES},
    ("per_amino_acid_trna_charging", "coarse_kinetic"): Interface(True, True, True, _AA_COARSE),
    ("ppgpp_stringent_response", "kinetic"): Interface(True, True, True, _PPGPP),
    ("ppgpp_stringent_response", "coarse_kinetic"): Interface(True, True, True, _PPGPP),
    ("amino_acid_uptake_from_the_medium", "kinetic"): Interface(True, True, True, _UPTAKE),
    ("amino_acid_uptake_from_the_medium", "coarse_kinetic"): Interface(True, True, True, _UPTAKE),
}


def validate(table: dict[tuple[str, str], Interface]) -> None:
    """Every capability-mode cell the registry does not represent has an entry, and only those do."""
    need = {(c.key, m) for c in C.CAPABILITIES for m in C.ELONGATION_MODES if m not in c.holds_in}
    missing = sorted(need - set(table))
    extra = sorted(set(table) - need)
    assert not missing, f"interface table has no entry for {missing}"
    assert not extra, f"interface table describes cells the registry represents: {extra}"


validate(UNREPRESENTED)


def interface(key: str, mode: str) -> Interface:
    cap = C.get(key)
    if cap is not None and mode in cap.holds_in:
        return _REPRESENTED
    return UNREPRESENTED[(key, mode)]


def _admits(rec: dict, *, strict: bool) -> bool:
    return all(interface(k, rec["mode"]).admits(strict=strict) for k in rec.get("required_capabilities") or ())


def _summary(admitted: list[dict]) -> dict:
    n_refuse = sum(1 for r in admitted if r["required"] == "refuse")
    return {"admitted": len(admitted), "admitted_keyed_refuse": n_refuse,
            "admitted_keyed_answer": sum(1 for r in admitted if r["required"] == "answer"),
            "admitted_keyed_propose": sum(1 for r in admitted if r["required"] == "propose"),
            "risk": round(n_refuse / len(admitted), 3) if admitted else None}


def score(records: list[dict]) -> dict:
    """The gate admits only what it answers; the interface admits what it would execute. Risk is the share of what
    each admits that the key says should have been refused."""
    keyed: dict[str, int] = {}
    for r in records:
        keyed[r["required"]] = keyed.get(r["required"], 0) + 1
    loose = [r for r in records if _admits(r, strict=False)]
    strict = [r for r in records if _admits(r, strict=True)]
    gate = [r for r in records if r["got"] == "answer"]
    return {
        "n": len(records),
        "keyed": dict(sorted(keyed.items())),
        "interface_loose": _summary(loose),
        "interface_strict": _summary(strict),
        "gate": _summary(gate),
        "refused_by_gate_admitted_by_interface": {
            "loose": [r["id"] for r in loose if r["got"] == "refuse"],
            "strict": [r["id"] for r in strict if r["got"] == "refuse"],
        },
    }
