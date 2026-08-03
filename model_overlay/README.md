# `model_overlay/` — finished wcEcoli files, not patches

This directory holds **complete files** that get copied over a clean
[CovertLab/wcEcoli](https://github.com/CovertLab/wcEcoli) checkout. It replaces the anchor-matching
appliers, which could not replay on any committed tree.

```
MANIFEST.json          pinned upstream commit + expected sha256 for every file
files/<wcEcoli path>   the finished files, verbatim, LF line endings
```

Do not edit anything under `files/` by hand — `apply_model_overlay.py` verifies each file against the
sha256 in `MANIFEST.json` and refuses to install a file that does not match. Edit the source tree and
re-run `scripts/build_model_overlay.py`.

## Use

```bash
git clone https://github.com/CovertLab/wcEcoli && git -C wcEcoli checkout a4497e17
python scripts/apply_model_overlay.py --wcecoli ./wcEcoli --check   # verify, write nothing
python scripts/apply_model_overlay.py --wcecoli ./wcEcoli
```

The `--check` run is the interesting one. Before writing anything, it hashes each target file and
compares it to the **pinned upstream** hash. If upstream has moved a file we ship, our copy is stale
and might be hiding a real upstream fix — so it stops and names the file rather than overwriting.
`--force` proceeds anyway and prints every file it overwrote.

## Status

30 files ship. **5 are deliberately withheld** and are named on every run; a checkout built from this
overlay is incomplete until they are resolved. Category (c) — including
`multi_gene_knockout.py`, which is on Cellarium's live launch path — is out of scope here.

Full account, including the four measured defects that retired the old mechanism:
**[`docs/OVERLAY.md`](../docs/OVERLAY.md)**.

## Licence

The `port` category derives from CovertLab/WholeCellEcoliRelease **v3.0.1** (Choi & Covert 2023,
*NAR* 51(12):5911, doi:10.1093/nar/gkad435) under its non-commercial `LICENSE.md`, redistributed with
Prof. Covert's permission. wcEcoli itself is under the Covert Lab academic non-commercial licence —
you accept it by running the model.
