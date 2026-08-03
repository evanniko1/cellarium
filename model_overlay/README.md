# `model_overlay/` — finished wcEcoli files, not patches

This directory holds **complete files** that get copied over a clean
[CovertLab/wcEcoli](https://github.com/CovertLab/wcEcoli) checkout. It replaces the anchor-matching
appliers, which could not replay on any committed tree.

```
MANIFEST.json            pinned upstream commit + expected sha256 for every file
files/<wcEcoli path>     the finished files, verbatim, LF line endings   <- what gets copied
cleaned/<wcEcoli path>   SOURCE: working-tree files with the ROUTE1 isoacceptor work reverted
authored/<wcEcoli path>  SOURCE: files written here, because the change exists in no tree
```

`cleaned/` and `authored/` are inputs to `scripts/build_model_overlay.py`, not shipped artifacts;
`harvest()` prefers `authored/`, then `cleaned/`, then the `--source` checkout, and records which one
each body came from in the manifest. The two are kept apart because `cleaned/` carries an implicit
claim — *this is the source tree minus ROUTE1, and its diff against upstream is insertions only* —
that an authored file does not satisfy and must not be read as making.

Do not edit anything under `files/` by hand — `apply_model_overlay.py` verifies each file against the
sha256 in `MANIFEST.json` and refuses to install a file that does not match. Edit the source tree and
re-run `scripts/build_model_overlay.py`.

## Use

```bash
git clone https://github.com/CovertLab/wcEcoli && git -C wcEcoli checkout -b cellarium-pin a4497e17
python scripts/apply_model_overlay.py --wcecoli ./wcEcoli --check   # verify, write nothing
python scripts/apply_model_overlay.py --wcecoli ./wcEcoli
```

The `--check` run is the interesting one. Before writing anything, it hashes each target file and
compares it to the **pinned upstream** hash. If upstream has moved a file we ship, our copy is stale
and might be hiding a real upstream fix — so it stops and names the file rather than overwriting.
`--force` proceeds anyway and prints every file it overwrote.

## Status

**44 files ship, 0 blocked.** Nothing on Cellarium's launch path is withheld.

- The five files the ROUTE1 gate used to block — `polypeptide_elongation.py`, `scriptBase.py`,
  `wholecell/sim/simulation.py` and the two simulation firetasks — ship from de-ROUTE1'd sources in
  `cleaned/`, so `--kinetic-trna-charging` is live on a public clone.
  `scripts/verify_overlay_route1.py` asserts *both* halves: no ROUTE1 markers **and** the kinetic
  classes still present.
- The `cellarium` category (9 files) closes what used to be "category (c)": the four-file multi-KO
  channel (`multi_gene_knockout.py` + `variant_kwargs` through `runSim.py` → `variantSimData.py` →
  `apply_variant.py`), the positional-condition fixes (`ppgpp_conc.py`, `aa_synthesis_ko.py`,
  `rrna_operon_knockout.py`, `tf_activity.py`), and `cloud/docker/runtime/Dockerfile` — without which
  upstream's own image build does not complete on a clean `a4497e17`.
  `scripts/verify_overlay_variants.py` asserts registration in both directions, the channel link by
  link, and runs the shipped variant against a recording stub.

Both verifiers have working negative controls: run either against a bare, un-overlaid checkout and it
exits 1.

Full account, including the four measured defects that retired the old mechanism:
**[`docs/OVERLAY.md`](../docs/OVERLAY.md)**.

## Licence

The `port` category derives from CovertLab/WholeCellEcoliRelease **v3.0.1** (Choi & Covert 2023,
*NAR* 51(12):5911, doi:10.1093/nar/gkad435) under its non-commercial `LICENSE.md`, redistributed with
Prof. Covert's permission. wcEcoli itself is under the Covert Lab academic non-commercial licence —
you accept it by running the model. The `cellarium` and `script-written` categories are Cellarium's
own work; where they *modify* a wcEcoli file they are derivative of it and inherit the same
non-commercial terms.
