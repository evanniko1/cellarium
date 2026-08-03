# ROUTE1 analysis scripts — preserved copies

These 17 files were rescued from `C:/dev/wcEcoli/out/` (the top level of the wcEcoli output tree,
alongside the run directories) immediately before the ROUTE1 extension simulations were deleted.
They are preserved here because `docs/ROUTE1_CORPUS_RECORD.md` **cites them by name** as the
definitions of the interventions it reports, and the record must not cite files that no longer exist
anywhere reachable.

They are copied **verbatim** — all 17 verified byte-identical to their originals (md5) before the
originals were removed. They are not maintained, not imported by anything in Cellarium, and are not
covered by its tests. They are evidence, not code.

## What defines what

| file | what it defines |
|---|---|
| `_aa_kcat_throttle.py` | the `aa_kcats_fwd` throttle — the intervention behind the `mf*`, `st_f*` and `sk_f*` ladders (`ROUTE1_CORPUS_RECORD.md` §4b, §4c) |
| `_ks_throttle.py` | the kS capacity throttle — the A1 intervention (`a1c_*` vs `a1t_*`, §4a) |
| `_r1s_extract.py`, `_r1s_params.py`, `_r1s_relaparams.npz` | the derived quantities (Φ, D, kmax, `v_real`/`v_law`, reconstructed `rbu_new`/`rbu_old`) extracted over the `mf` ladder into `out/_r1s_npz` (§10) |
| `_starve_families.py`, `_starve_readout.py` | the per-family starvation readout and the total-variation degeneracy guard (§11) |
| `_a1_ctlcheck.sh`, `_a1_readout.py`, `_a1_readout.json` | the A1 control check — asserts `a1c_s*` reproduces the `km3` family baseline, independently reproduced in §6 |
| `_a2_kcat_check.py` | kcat sanity check for the A2 arm |
| `_ab_analysis.py`, `_ab_analysis_off_s1.py`, `ab_analyze.py`, `ab_analyze_off_s2.py`, `ab_analyze_route1.py`, `ab_verify.py` | the ppGpp arm-isolation analysis (`ab_on_*` / `ab_off_*`, §4d) |

## Caveat on uniqueness

Whether these files also exist in the extension repository
(`github.com/evanniko1/wcecoli-extension-tRNA-isoacceptors`) has **not** been checked from this
machine — the `extension` remote was removed and no clone is present here. They were treated as
unique, which is why they were copied rather than dropped.

## What was not preserved here

`out/_r1s_npz` (26 MB, 36 `.npz`) was **retained in place** at `C:/dev/wcEcoli/out/_r1s_npz` rather
than deleted or copied — it is too large for this repository and holds the only per-timestep record
of the `mf` ladder. See `docs/ROUTE1_CORPUS_RECORD.md` §7 "Before deleting".
