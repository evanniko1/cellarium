"""SCI-TRNA-3 — the single-amino-acid dropout media, and the envelope trap they exposed.

The synthetase knockouts failed as a charging experiment because deleting an aaRS arrests translation: 4 of 6
were degenerate. Dittmar 2005's actual protocol starves a *growing* cell of ONE amino acid, which is what these
media do. The scientific claim that makes them worth adding is a single number, asserted below: the existing
downshift (`minimal_plus_amino_acids` -> `minimal`) perturbs **30** molecules — 20 amino acids to zero plus 10
base components diluted by the 0.8 L recipe — while each dropout perturbs exactly **1**. Selective charging is
only attributable at n=1 perturbed molecule.

The wcEcoli tests skip without a model checkout (CI has none); the envelope tests always run.
"""

from __future__ import annotations

import functools
import os
import sys

import pytest

WCECOLI = os.environ.get("WCECOLI_PATH", r"C:\dev\wcEcoli")
DROPOUTS = [("leu", "LEU"), ("thr", "THR"), ("arg", "ARG")]


@functools.lru_cache(maxsize=1)
def _media():
    """The model's own media builder, or a skip. Never a hand-rolled reimplementation — the point of this test
    is that WCECOLI builds these correctly, so computing them ourselves would test nothing.

    Cached: constructing `KnowledgeBaseEcoli` parses the entire flat-file corpus and takes minutes, so building
    it once per test turned a fast suite into a slow one. `pytest.skip` raises, and lru_cache does not cache
    exceptions, so the skip path still fires correctly on every call."""
    if not os.path.isdir(os.path.join(WCECOLI, "reconstruction")):
        pytest.skip("no wcEcoli checkout")
    if WCECOLI not in sys.path:
        sys.path.insert(0, WCECOLI)
    try:
        from reconstruction.ecoli.knowledge_base_raw import KnowledgeBaseEcoli
        from wholecell.utils.make_media import Media
    except Exception as e:                                    # unum / compiled extensions absent
        pytest.skip(f"wcEcoli not importable here: {type(e).__name__}")
    raw = KnowledgeBaseEcoli(operons_on=True, remove_rrna_operons=False, remove_rrff=False, stable_rrna=False)
    return Media(raw)


def _diff(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b) if abs(float(b.get(k, 0)) - float(a.get(k, 0))) > 1e-12)


@pytest.mark.parametrize("tag,mol", DROPOUTS)
def test_a_dropout_removes_exactly_one_molecule(tag, mol):
    """THE assertion. If a dropout perturbs anything besides its target amino acid, the experiment cannot
    attribute a charging collapse to that amino acid and the design is worthless."""
    m = _media()
    mid = f"minimal_aa_minus_{tag}"
    assert mid in m.recipes, f"{mid} is not registered in media_recipes.tsv"
    base = m.make_recipe("minimal_plus_amino_acids")
    got = m.make_recipe(mid)
    assert _diff(base, got) == [mol], f"{mid} must perturb ONLY {mol}"
    assert float(got[mol]) == 0.0, f"{mol} must be exactly zero, got {got[mol]}"
    assert float(base[mol]) > 0.0, f"{mol} must be PRESENT in the AA-rich medium, else the dropout is a no-op"
    assert len(got) == len(base), "molecule count must be preserved — removal sets the concentration to 0"


def test_the_dropout_is_a_far_cleaner_perturbation_than_the_existing_downshift():
    """The design justification, pinned as a number. Guards against someone 'simplifying' these recipes back
    into a plain shift to `minimal`, which would silently reintroduce 29 confounded variables."""
    m = _media()
    base = m.make_recipe("minimal_plus_amino_acids")
    n_downshift = len(_diff(base, m.make_recipe("minimal")))
    assert n_downshift >= 20, "sanity: the AA-rich -> minimal downshift should perturb the whole AA set"
    for tag, _mol in DROPOUTS:
        n = len(_diff(base, m.make_recipe(f"minimal_aa_minus_{tag}")))
        assert n == 1 < n_downshift, f"minus_{tag} perturbs {n} molecules vs {n_downshift} for the downshift"


# ---------------- the envelope trap, which needs no model checkout ----------------
def test_a_minus_medium_is_not_classified_as_fed_by_what_it_removes():
    """`carbon_source` matched substrings, so `minimal_minus_malate` classified as MALATE-FED — a medium that
    REMOVES a carbon source read as one that supplies it. Latent until these dropouts established
    `minus_<molecule>` as a media naming pattern; it would have refused a valid glucose shift as an
    out-of-envelope carbon switch, or mis-recorded a run's carbon source in provenance."""
    from cellarium import envelope
    assert envelope.carbon_source("minimal_minus_malate") == "glucose"
    assert envelope.carbon_source("minimal_aa_minus_leu") == "glucose"
    # and the real classifications must survive the fix
    assert envelope.carbon_source("minimal_acetate") == "acetate"
    assert envelope.carbon_source("minimal_malate") == "malate"
    assert envelope.carbon_source("minimal_succinate") == "succinate"
    assert envelope.carbon_source("minimal_fumarate") == "fumarate"


@pytest.mark.parametrize("tag,_mol", DROPOUTS)
def test_the_dropout_timeline_is_inside_the_validated_envelope(tag, _mol):
    """These must be runnable as timelines — the whole design is a shift, and an envelope refusal is what
    produced the 38 crashed zero-byte metabolism rows."""
    from cellarium import envelope
    from cellarium.generate import Design
    d = Design(perturbation="timeline",
               timeline=f"0 minimal_plus_amino_acids, 1200 minimal_aa_minus_{tag}")
    v = envelope.check(d)
    assert v.in_envelope, v.reason


def test_the_envelope_still_refuses_a_real_carbon_switch():
    """The companion: loosening the matcher must not have opened the gate it exists to hold."""
    from cellarium import envelope
    from cellarium.generate import Design
    v = envelope.check(Design(perturbation="timeline", timeline="0 minimal, 1200 minimal_acetate"))
    assert not v.in_envelope and "carbon source" in v.reason


def test_the_media_names_fit_the_fixed_width_column():
    """A data-integrity constraint, not style. wcEcoli writes media ids into a NumPy fixed-width column sized
    from the FIRST value of the generation. These runs start in `minimal_plus_amino_acids` (24 chars), so the
    generation containing the shift gets <U25 and anything longer is silently cut.

    Measured on a real smoke run: named `minimal_plus_amino_acids_minus_{leu,thr,arg}` (34 chars), all three
    truncated to the IDENTICAL string `minimal_plus_amino_acids_` — the record showed that *a* shift happened
    but could not distinguish the three arms. That is SCI-QC-1 recurring inside the column SCI-QC-2 adopted as
    its untruncated witness."""
    start = "minimal_plus_amino_acids"
    width = len(start) + 1                      # the observed <U25 for a generation starting in this medium
    names = [f"minimal_aa_minus_{tag}" for tag, _mol in DROPOUTS]
    for n in names:
        assert len(n) <= width, f"{n!r} ({len(n)}) would be truncated in a <U{width} column"
    assert len({n[:width] for n in names}) == len(names), "arms must stay distinguishable after truncation"
    # and the guard that would catch a regression is real
    from cellarium import serialization
    assert hasattr(serialization, "scan_run")


# ---------------- SCI-TRNA-4: the auxotroph arms ----------------
AUXOTROPHS = [("leuB", 1818, "leu"), ("thrC", 2715, "thr"), ("argG", 2042, "arg")]


def _aux_design(sym, idx, aa):
    from cellarium.model import Design
    return Design(perturbation="gene_knockout", condition=f"KO:{sym}", params={"variant_index": idx},
                  timeline=f"0 minimal_plus_amino_acids, 1200 minimal_aa_minus_{aa}")


@pytest.mark.parametrize("sym,idx,aa", AUXOTROPHS)
def test_a_knockout_with_a_timeline_still_runs_the_knockout(sym, idx, aa):
    """THE guard. `_variant_type` used to return "wildtype" whenever a timeline was present, which silently
    discarded the genotype: KO:leuB + a leucine dropout emitted `--variant wildtype 1818 1818`, and the
    wildtype variant ignores its index entirely. The media shift would still have worked and the provenance
    would still have said KO:leuB, so the arm would have been a plain wild type wearing a knockout's label —
    the WELL-NOOP-1 pattern, undetectable from the output."""
    from cellarium import runner
    args = runner._variant_args(_aux_design(sym, idx, aa))
    assert args[:2] == ["--variant", "gene_knockout"], f"the knockout was dropped: {args}"
    assert args[2] == str(idx) and args[3] == str(idx)
    assert "--timeline" in args, "the media dropout was dropped"
    assert f"minimal_aa_minus_{aa}" in args[args.index("--timeline") + 1]


def test_a_pure_media_shift_still_runs_on_the_wildtype_variant():
    """The companion: the fix must not break the designs the old rule existed for."""
    from cellarium import runner
    from cellarium.model import Design
    args = runner._variant_args(Design(perturbation="timeline",
                                       timeline="0 minimal_plus_amino_acids, 1200 minimal"))
    assert args[:2] == ["--variant", "wildtype"] and "--timeline" in args


@pytest.mark.parametrize("sym,idx,aa", AUXOTROPHS)
def test_the_auxotroph_arms_are_in_envelope(sym, idx, aa):
    from cellarium import envelope
    v = envelope.check(_aux_design(sym, idx, aa))
    assert v.in_envelope, v.reason


@pytest.mark.parametrize("sym,idx,aa", AUXOTROPHS)
def test_starved_and_unstarved_arms_never_share_an_output_dir(sym, idx, aa):
    """They did, and it destroyed the control. Both carried the same `variant_index` (the gene index the model
    needs), so both resolved to `gene_knockout_<idx>/<seed>`; run concurrently at parallel=6 they overwrote
    each other's generations and provenance, and three of four control seeds died outright. `_variant_index`'s
    content hash exists to prevent exactly this but is short-circuited by an explicit index."""
    from cellarium import runner
    from cellarium.model import Design
    starved = _aux_design(sym, idx, aa)
    unstarved = Design(perturbation="gene_knockout", condition=f"KO:{sym}", params={"variant_index": idx},
                       timeline="0 minimal_plus_amino_acids")
    a = runner._run_subpath(starved, 0, "t")
    b = runner._run_subpath(unstarved, 0, "t")
    assert a != b, f"starved and un-starved share {a} — they will overwrite each other"
    # and the model must still be told the right variant, whatever we call the directory
    assert runner._variant_args(starved)[:2] == ["--variant", "gene_knockout"]


def test_a_plain_knockout_keeps_its_conventional_directory():
    """The fix must not rename every existing run dir — only designs that would otherwise collide."""
    from cellarium import runner
    from cellarium.model import Design
    d = Design(perturbation="gene_knockout", condition="KO:dapA", params={"variant_index": 2776})
    assert runner._run_subpath(d, 0, "t").parent.name == "gene_knockout_002776"


def test_the_unstarved_control_is_held_in_the_rich_medium():
    """A gene_knockout design with NO timeline runs in basal MINIMAL medium. So an auxotroph 'control' without
    an explicit medium is starved by construction — the opposite of a control."""
    from cellarium import generate
    ko = [d for d in generate.auxotroph_starvation_designs() if d.perturbation == "gene_knockout"]
    unstarved = [d for d in ko if d.timeline and "minus_" not in d.timeline]
    assert len(unstarved) == 3, "every arm needs an un-starved control"
    for d in unstarved:
        assert d.timeline.strip() == "0 minimal_plus_amino_acids", d.timeline
