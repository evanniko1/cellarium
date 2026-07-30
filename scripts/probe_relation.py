"""Fast harness for the EXT-PORT relation methods — seconds-to-minutes, not a 15-minute ParCa.

Runs INSIDE the model image. It reuses the `rawData.cPickle` a ParCa run already produced and builds
`SimulationDataEcoli` only as far as `Relation`, which is where every port failure so far has surfaced. The
full ParCa spends most of its time in `fitSimData_1`'s optimisation, long AFTER the point we care about, so
iterating on the port through full ParCa runs costs ~15 minutes per attempt to learn something that is decided
in the first two.

More importantly it answers the question a green ParCa does NOT answer. `_build_codon_sequences` translates
each monomer's mRNA and compares it to that monomer's protein sequence, but a mismatch only calls
`warnings.warn` — the run continues and stores the value anyway. So "ParCa went green" is compatible with
every protein having received the wrong mRNA. This harness COUNTS the mismatches and fails on them.

    docker run --rm -v C:/dev/wcEcoli/out:/wcEcoli/out -v <this file>:/tmp/probe.py \
        -e PYTHONPATH=/wcEcoli -w /wcEcoli wcecoli-sim:kinetic python /tmp/probe.py

Exit code is 0 only when Relation builds AND no monomer's mRNA disagrees with its protein.
"""

from __future__ import annotations

import pickle
import sys
import warnings

RAW = "/wcEcoli/out/kinetic_parca/kb/rawData.cPickle"

# The monomers whose mRNA provably cannot translate to their curated protein. Allowlisted individually so
# that ANY other mismatch — which would be a port defect — still fails this harness.
KNOWN_MISMATCHES = frozenset({
    # EXT-PORT-10 emptied this allowlist. PHNE-MONOMER was here until EG11283_RNA (phnE1) was typed
    # 'pseudo' in reconstruction/ecoli/flat/rnas.tsv, matching v3.0.1 — EXCLUDED_RNA_TYPES then drops
    # the cistron, the monomer leaves monomer_data, and the mismatch is not excused, it is gone.
    # Deliberately EMPTY rather than deleted: the next monomer whose mRNA stops disagreeing quietly
    # should fail this harness, and an empty frozenset says that on purpose.
    # dinG and ytiC were here too under the transcription-unit-slice route. They are NOT here any more:
    # parsing each cistron from its own gene's coordinates fixes both, which is the measurement that
    # decided between the two routes (3 mismatches -> 1).
})


def main() -> int:
    with open(RAW, "rb") as f:
        raw_data = pickle.load(f)

    from reconstruction.ecoli.simulation_data import SimulationDataEcoli

    sim_data = SimulationDataEcoli()

    # Every warning raised while Relation builds is captured rather than printed, because the ONE that matters
    # ('mRNA sequence does not match the protein') is emitted per-protein and would otherwise scroll past as
    # noise. `simplefilter('always')` defeats the default once-per-location dedup — without it, 4000 wrong
    # proteins report as one warning.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sim_data.initialize(raw_data=raw_data, basal_expression_condition="M9 Glucose minus AAs")

    mismatch = [str(w.message) for w in caught if "does not match the protein" in str(w.message)]
    other = [str(w.message) for w in caught if "does not match the protein" not in str(w.message)]

    rel = sim_data.relation
    n_monomers = len(sim_data.process.translation.monomer_data["id"])
    print(f"Relation built. monomers={n_monomers}")
    for attr in ("codons", "trnas_to_codons", "codons_to_trnas", "codons_to_amino_acids",
                 "residue_weights_by_codon", "amino_acid_to_synthetase", "synthetase_to_k_cat",
                 "trna_codon_pairs"):
        v = getattr(rel, attr, None)
        shape = getattr(v, "shape", None)
        print(f"  {attr}: {'ABSENT' if v is None else (shape if shape is not None else f'len={len(v)}')}")

    seqs = getattr(rel, "_codon_sequences", None)
    print(f"  _codon_sequences: {'ABSENT' if seqs is None else f'len={len(seqs)}'}")

    print(f"\nmRNA/protein mismatches: {len(mismatch)} of {n_monomers}")
    for m in mismatch[:5]:
        print(f"  {m}")
    if len(mismatch) > 5:
        print(f"  ... and {len(mismatch) - 5} more")
    if other:
        print(f"\nother warnings: {len(other)}")
        for m in other[:5]:
            print(f"  {m}")

    # An UNEXPECTED mismatch is the real acceptance criterion, and ParCa exiting 0 is not evidence of one way
    # or the other: the check inside _build_codon_sequences only warns, so a wrong sequence assignment can
    # still produce a green run. Anything outside KNOWN_MISMATCHES is a port defect.
    unexpected = [m for m in mismatch if not any(k in m for k in KNOWN_MISMATCHES)]
    print(f"  of which allowlisted (KNOWN_MISMATCHES): {len(mismatch) - len(unexpected)}")
    if unexpected:
        print(f"\nFAIL: {len(unexpected)} UNEXPECTED mRNA/protein mismatch(es):")
        for m in unexpected[:20]:
            print(f"  {m}")
        return 1
    print(f"\nOK: every monomer's mRNA translates to its protein, except {len(mismatch)} allowlisted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
