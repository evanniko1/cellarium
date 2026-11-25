"""BV-R1: protein counts of two-component sensor kinases, corrected for a gap in wcEcoli's MonomerCounts listener.

wcEcoli's `two_component_system.stoich_matrix_monomers()` keeps a complex's subunits only if they are in the
two-component system's own molecule list, which does not contain the sensor monomers. The MonomerCounts listener
therefore removes a phosphorylated sensor complex and adds no protein back. Measured in the shipped knowledge base
(2026-11-25): 7 of 18 complexes drop their monomers, across DcuS, NarX, PhoQ, PhoR and ArcB; the equilibrium (39)
and complexation (1,131) decompositions drop none. The reader adds the dropped subunits back from the bulk counts.

The forced case is the one that exposed it: NarX in nitrate read 0.9 copies (log2 -5.07 against basal) while 21
PHOSPHO-NARX-NITRATE-CPLX each held two NarX monomers."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "cellarium"))

import _reader_agg as A  # noqa: E402

C2M = {"PHOSPHO-NARX-NITRATE-CPLX[i]": {"NARX-MONOMER[i]": 2.0, "Pi[c]": 1.0},
       "PHOSPHO-NARX[i]": {"NARX-MONOMER[i]": 2.0, "Pi[c]": 1.0},
       "PHOSPHO-NARL[c]": {"NARL-MONOMER[c]": 1.0, "Pi[c]": 1.0}}
TCS_MOLECULES = {"PHOSPHO-NARX-NITRATE-CPLX[i]", "PHOSPHO-NARX[i]", "PHOSPHO-NARL[c]", "NARL-MONOMER[c]",
                 "Pi[c]", "NARX-CPLX[i]"}


def test_only_subunits_outside_the_two_component_list_are_reported_dropped():
    dropped = A.tcs_dropped_subunits(C2M, TCS_MOLECULES)
    assert dropped == {"PHOSPHO-NARX-NITRATE-CPLX[i]": {"NARX-MONOMER[i]": 2.0},
                       "PHOSPHO-NARX[i]": {"NARX-MONOMER[i]": 2.0}}     # NarL's monomer is in the list: kept


def test_narx_in_nitrate_gets_its_bound_monomers_back():
    dropped = A.tcs_dropped_subunits(C2M, TCS_MOLECULES)
    monomers = {"NARX-MONOMER[i]": 0.9, "NARL-MONOMER[c]": 40.0}
    bulk = {"PHOSPHO-NARX-NITRATE-CPLX[i]": 21.0, "PHOSPHO-NARX[i]": 0.0}
    corrected, added = A.add_tcs_correction(monomers, bulk, dropped)
    assert corrected["NARX-MONOMER[i]"] == 0.9 + 42.0
    assert corrected["NARL-MONOMER[c]"] == 40.0                      # untouched
    assert added == {"NARX-MONOMER[i]": 42.0}


def test_no_bound_sensor_means_no_change():
    dropped = A.tcs_dropped_subunits(C2M, TCS_MOLECULES)
    monomers = {"NARX-MONOMER[i]": 33.5}
    corrected, added = A.add_tcs_correction(monomers, {}, dropped)
    assert corrected == monomers and added == {}


def test_the_correction_reverses_the_nitrate_artefact():
    # basal: NarX sits in its unphosphorylated dimer, which the listener counts; nitrate: in the bound complex
    import math
    dropped = A.tcs_dropped_subunits(C2M, TCS_MOLECULES)
    basal, _ = A.add_tcs_correction({"NARX-MONOMER[i]": 33.46}, {"PHOSPHO-NARX-NITRATE-CPLX[i]": 0.0}, dropped)
    nitrate, _ = A.add_tcs_correction({"NARX-MONOMER[i]": 0.91}, {"PHOSPHO-NARX-NITRATE-CPLX[i]": 20.97}, dropped)
    before = math.log2(0.91 / 33.46)
    after = math.log2(nitrate["NARX-MONOMER[i]"] / basal["NARX-MONOMER[i]"])
    assert before < -5.0 and 0.3 < after < 0.4


def test_a_subunit_named_in_another_compartment_is_matched_by_its_base_id():
    # measured 2026-11-25: the two-component map names DCUS-MONOMER[i], while the bulk species and MonomerCounts
    # carry DCUS-MONOMER[c]; in succinate all 21 DcuS copies sit in PHOSPHO-DCUS-SUC-CPLX[i] and DcuS read 0
    dropped = {"PHOSPHO-DCUS-SUC-CPLX[i]": {"DCUS-MONOMER[i]": 1.0}}
    aligned = A.align_subunits(dropped, ["DCUS-MONOMER[c]", "NARX-MONOMER[i]"])
    assert aligned == {"PHOSPHO-DCUS-SUC-CPLX[i]": {"DCUS-MONOMER[c]": 1.0}}
    corrected, added = A.add_tcs_correction({"DCUS-MONOMER[c]": 0.007}, {"PHOSPHO-DCUS-SUC-CPLX[i]": 21.0}, aligned)
    assert round(corrected["DCUS-MONOMER[c]"], 3) == 21.007


def test_an_exact_id_is_kept_and_an_ambiguous_base_is_not_guessed():
    dropped = {"C[i]": {"M[i]": 2.0}, "D[i]": {"Q[x]": 1.0}}
    aligned = A.align_subunits(dropped, ["M[i]", "M[c]", "Q[c]", "Q[p]"])
    assert aligned["C[i]"] == {"M[i]": 2.0}                 # exact id present: kept
    assert aligned["D[i]"] == {"Q[x]": 1.0}                 # two candidates for base Q: left as is, not guessed
