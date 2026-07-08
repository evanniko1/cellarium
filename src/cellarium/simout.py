"""Read simOut through the PUBLIC Covert `TableReader`.

This is the clean dependency boundary: Cellarium reads the whole-cell model's own output format using the
model's own reader — no code from the private platform overlay. Requires the wcEcoli model importable
(on PYTHONPATH, or run inside the model's Docker image). Every table/column/attribute name below is the
model's public listener schema (models/ecoli/listeners, wholecell/io).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# Summary channels: (table, column). Scalar-per-timestep signals we aggregate into the manifest.
SUMMARY_CHANNELS: dict[str, tuple[str, str]] = {
    "growth_rate": ("Mass", "instantaneous_growth_rate"),
    "cell_mass": ("Mass", "cellMass"),
    "dry_mass": ("Mass", "dryMass"),
    "protein_mass": ("Mass", "proteinMass"),
    "rna_mass": ("Mass", "rnaMass"),
    "ppgpp_conc": ("GrowthLimits", "ppgpp_conc"),
    "fba_objective": ("FBAResults", "objectiveValue"),
}

# Per-species matrix sources: kind -> (table, column, id_attribute). read_species / list_species use these.
SPECIES_SOURCES: dict[str, tuple[str, str, str]] = {
    "protein": ("MonomerCounts", "monomerCounts", "monomerIds"),
    "mrna": ("RNACounts", "mRNA_cistron_counts", "mRNA_cistron_ids"),
    "metabolite": ("BulkMolecules", "counts", "objectNames"),
    "reaction_flux": ("FBAResults", "reactionFluxes", "reactionIDs"),
    "exchange_flux": ("FBAResults", "externalExchangeFluxes", "externalMoleculeIDs"),
}


def _reader(table_dir: Path):
    from wholecell.io.tablereader import TableReader  # public model dependency (import lazily)

    return TableReader(str(table_dir))


def find_generations(simout_root: Path) -> list[Path]:
    """All per-generation simOut directories under a run root, in generation order."""
    return sorted(p for p in Path(simout_root).rglob("simOut") if p.is_dir())


def read_column(simout_dir: Path, table: str, column: str) -> np.ndarray:
    r = _reader(Path(simout_dir) / table)
    try:
        return np.asarray(r.readColumn(column))
    finally:
        r.close()


def read_attribute(simout_dir: Path, table: str, attr: str):
    r = _reader(Path(simout_dir) / table)
    try:
        return r.readAttribute(attr)
    finally:
        r.close()


def read_time(simout_dir: Path) -> np.ndarray:
    return read_column(simout_dir, "Main", "time").ravel()


def full_chromosome_end(simout_dir: Path) -> int:
    """End-of-generation full_chromosome count (2 = one clean replication round; >2 = over-replicated)."""
    ids = [str(x) for x in read_attribute(simout_dir, "UniqueMoleculeCounts", "uniqueMoleculeIds")]
    col = read_column(simout_dir, "UniqueMoleculeCounts", "uniqueMoleculeCounts")
    return int(col[-1, ids.index("full_chromosome")]) if "full_chromosome" in ids else -1


def read_channel(simout_dir: Path, channel: str) -> np.ndarray:
    table, column = SUMMARY_CHANNELS[channel]
    return read_column(simout_dir, table, column).ravel()


def list_species(kind: str, search: str = "", limit: int = 40) -> list[str]:
    """Resolve a plain-English molecule to real model IDs (grounding). Reads from any recent simOut is not
    needed — callers pass a simOut dir via `species_ids`."""
    raise NotImplementedError("call species_ids(simout_dir, kind, search) with a concrete simOut directory")


def species_ids(simout_dir: Path, kind: str, search: str = "", limit: int = 40) -> list[str]:
    table, _column, id_attr = SPECIES_SOURCES[kind]
    r = _reader(Path(simout_dir) / table)
    try:
        ids = [str(x) for x in r.readAttribute(id_attr)]
    finally:
        r.close()
    s = search.lower()
    hits = [i for i in ids if s in i.lower()] if s else ids
    return hits[:limit]


def read_species(simout_dir: Path, kind: str, species_id: str) -> dict:
    """Time-series of ONE species (any of the model's state variables), via the public reader."""
    table, column, id_attr = SPECIES_SOURCES[kind]
    r = _reader(Path(simout_dir) / table)
    try:
        ids = [str(x) for x in r.readAttribute(id_attr)]
        if species_id not in ids:
            # tolerant match on bare name (compartment tags e.g. [c] stripped)
            cand = [i for i in ids if i.split("[")[0] == species_id.split("[")[0]]
            if not cand:
                return {"error": f"'{species_id}' not found in {kind}.", "n_ids": len(ids)}
            species_id = cand[0]
        col = np.asarray(r.readColumn(column))
        series = col[:, ids.index(species_id)]
    finally:
        r.close()
    t = read_time(simout_dir)
    return {"species_id": species_id, "kind": kind,
            "mean": float(series.mean()), "first": float(series[0]), "last": float(series[-1]),
            "n_points": int(series.size), "grounded_from": f"simOut::{table}/{column}"}
