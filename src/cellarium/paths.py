"""Where Cellarium's committed, model-derived caches live: `data/cache` in the checkout.

The caches (gene scope, knockout footprints, gene and cistron maps, the variant map, b-numbers) used to be read as
`Path("data/cache/...")`, relative to the working directory. From any other directory each read failed, the
`except` around it returned an empty map, and the empty map was then read as a finding. The isolated option-A
store runs from its own directory so that Cellarium's relative manifest path sees only its rows, and from there
every knockout in the corpus was labelled "INVALID: no_design_possible" (2026-10-27).

The MANIFEST stays relative on purpose (`manifest.MANIFEST_DIR`): choosing the store by working directory is how
an isolated store is made. Caches describe the model, not a store, so they are anchored to the checkout, with the
working directory as the fallback for an installed package run beside a copy of the data.
"""
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2] / "data" / "cache"
CACHE_DIR = _CHECKOUT if _CHECKOUT.is_dir() else Path("data/cache")


def cache(name: str) -> Path:
    """The path of one cache file, e.g. cache("gene_scope.json")."""
    return CACHE_DIR / name
