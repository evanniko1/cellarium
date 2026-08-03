# The model overlay

Cellarium needs a wcEcoli checkout that stock [CovertLab/wcEcoli](https://github.com/CovertLab/wcEcoli)
does not provide. This document records **how that checkout is produced**, **why the previous
mechanism was retired**, and **what is still missing**.

Everything below was measured against upstream commit **`a4497e17`** — the last CovertLab-authored
commit on our fork, materialised read-only with `git archive`.

---

## 1. What changed: patch → overlay

The old mechanism (`scripts/apply_trna_port.py`, `ext_port_10_patch.py`, `ext_port_11_patch.py`,
`apply_model_patches.py`, `apply_model_variants.py`) transformed a checkout by matching **text
anchors** and substituting. The new mechanism ships the **finished files** and copies them.

| | anchor-patching | overlay |
|---|---|---|
| upstream inserts an unrelated line | anchor may still match, or silently match twice | unaffected |
| upstream *changes* an overlaid file | edit applies to changed code, or fails obscurely | **fails loudly, by name** |
| CRLF vs LF checkout | anchors built for one do not match the other | irrelevant — hashing is LF-normalised |
| partial application | possible | impossible: copy or refuse |
| cost | none visible until it breaks | **version pinning**, paid explicitly in `MANIFEST.json` |

The overlay's cost is real: if upstream fixes a bug in a file we ship, our copy is stale and *hides
that fix*. That is precisely what `apply_model_overlay.py` refuses to proceed past, rather than
overwriting silently.

---

## 2. Why the old recipe was retired: it replayed on no committed tree

Run against a stock `a4497e17` checkout, `apply_trna_port.py` aborted **four** separate times. Each
failure is a distinct defect, and none of them was visible from the working copy — which only worked
because it had been hand-patched incrementally over many sessions.

**(1) Every multi-line anchor was unmatchable on a CRLF checkout.**
`_read()` opens in text mode, so Python's universal-newline translation returns **LF**. The code then
rebuilt each anchor as `old.replace("\n", n2)` with `n2 = "\r\n"`, searching a LF string for CRLF
anchors. Measured on `reconstruction/ecoli/dataclasses/process/translation.py` (442 CRLF pairs):
LF anchor present **1** time, CRLF anchor **0**. Result:
`expected exactly one 'monomer_data = np.zeros(', found 0`.
*Fixed* by deleting the 12 `.replace("\n", n2)` sites — the text is already LF, and `_write` still
restores the destination's convention.

**(2) A whole porting step was missing.**
v3.0.1 keeps `codon_sequences_width`, `record_mass`, the 3-arg `elongation_rate`, the 4-arg
`request` and the 8-arg `evolve` on `BaseElongationModel`
(`vendor/v301/models/ecoli/processes/polypeptide_elongation.py:462`). This tree's
`BaseElongationModel` has none of them and **must not** gain them — it still carries the
steady-state arities that the unchanged `calculateRequest`/`evolveState` call. They belong on
`CoarseKineticTrnaChargingModel`, and `apply_trna_port.py` never added them, so
`ext_port_10_patch.py:486` (`"coarse_next_amino_acids"`, anchored on `codon_sequences_width`
returning `elongation_rates`) matched **0** times.
The block existed **only** in the working tree and had never been committed anywhere.
*Fixed* by adding `PE_COARSE_ANCHOR`/`PE_COARSE_NEW` and a `coarse_surface` status key.

**(3) Two copies of one comment drifted apart.**
`apply_trna_port.py` wrote the `codon_read_rate` comment one way; `ext_port_11_patch.py:224`
(`SD_01_OLD`) anchored on a *different* wording of the same two lines. `SD_01` matched **0** times.
This is the exact failure mode `apply_trna_port.py`'s own docstring warns about — *"duplicating their
anchors is how two copies of one recipe drift apart"* — and it happened anyway.
*Fixed* by aligning the emitted wording, with a comment on both sides saying it is load-bearing.

**(4) A status check was order-dependent and false.**
`numpy_aliases_modernised` reported `True` on a clean tree because it is evaluated **before** the
port appends the v3.0.1 code that reintroduces `np.bool`. The modernisation step was therefore
skipped, and the emitted `relation.py` contained `dtype=np.bool` — removed in NumPy 1.24, and the
image runs 1.26.3. This one does not abort; it produces a tree that **imports fine and dies during
ParCa**. Recorded, not fixed: the overlay ships the correct `np.bool_` file, so the defect no longer
reaches a checkout.

After (1)–(3) the recipe runs to completion. That is what made the port harvestable — but see §5: it
still cannot produce the whole port.

---

## 3. How the overlay is built and applied

```
scripts/build_model_overlay.py       # harvest + gate + write model_overlay/ and MANIFEST.json
model_overlay/MANIFEST.json          # pinned upstream commit + every expected sha256
model_overlay/cleaned/<wcEcoli path> # de-ROUTE1'd SOURCES for five port files — see §5a
model_overlay/files/<wcEcoli path>   # the finished files, verbatim, LF
scripts/apply_model_overlay.py       # copy them onto a checkout, verifying first
scripts/verify_overlay_route1.py     # assert the five are ROUTE1-free AND still kinetic
```

`harvest()` reads each file from `model_overlay/cleaned/` when a copy exists there and from
`--source` otherwise. Only the five files of §5a have one. A cleaned copy is a *source*, not a
shipped artifact: it passes through every gate below, and its `upstream_sha256` is still taken
against `--upstream`, so upstream drift still invalidates it. Records harvested this way carry
`"source": "model_overlay/cleaned"` in the manifest.

`build_model_overlay.py` applies three gates, each from a measured defect:

1. **ROUTE1 refusal.** Any file containing the marker `ROUTE1` is refused and recorded as `blocked`.
   It is never silently stripped — see §5a for how the five it used to block were cleared.
2. **Condition ordering.** `condition_defs.tsv` is *rebuilt*, not copied, with the three amino-acid
   dropout rows **appended**. Row order is the condition index space, and Cellarium hardcodes those
   indices. The build asserts the 21-row order against `data/cache/variant_map.json` and dies if they
   disagree.
3. **Variant registration.** `models/ecoli/sim/variants/__init__.py` is *rewritten* to register
   exactly the variant modules the overlay carries. Registration is eager
   (`nameToFunctionMapping = {v: get_function(v) for v in variants}`), so a registered name without a
   module is an `ImportError` on **every** variant run.

`apply_model_overlay.py` hashes what is on disk before writing:

| on-disk state | verdict |
|---|---|
| matches `upstream_sha256` | `REPLACE` — safe |
| matches `overlay_sha256` | `ALREADY` — idempotent no-op |
| matches neither | **`STALE` — stop and name the file** |
| declared new, but present | **`CONFLICT` — stop** |

`--check` writes nothing. `--force` proceeds and prints every file it overwrote.

All hashing is over CRLF-normalised bytes, so a Windows checkout (where `git` applies the repo's eol
attributes and produces CRLF) and a Linux checkout give the same answer. Verified: applying to a
freshly-archived **CRLF** tree reports `0 problems`.

---

## 4. What ships

44 files, 6,090,304 bytes (6.09 MB), in four categories (`model_overlay/MANIFEST.json` is
authoritative; every size below is that file's `overlay_bytes`, decimal MB):

- **`port`** (28) — the v3.0.1 kinetic tRNA-charging port (EXT-PORT 1/10/11) plus EXT-PORT-12
  (UNIFY-2): the elongation-flag split and the RNG determinism fix. Derived from
  CovertLab/WholeCellEcoliRelease v3.0.1 (Choi & Covert 2023, *NAR* 51(12):5911,
  doi:10.1093/nar/gkad435) under its non-commercial `LICENSE.md`, redistributed with Prof. Covert's
  permission.
- **`script-written`** (4) — what `apply_model_patches.py`/`apply_model_variants.py` used to produce:
  `condition_defs.tsv`, `media_recipes.tsv`, `variants/__init__.py`, plus `graded_gene_knockout.py`.
- **`cellarium`** (9) — the model changes Cellarium needs that are *not* part of the v3.0.1 port, and
  every one of them is on the live launch path. Three clusters, detailed in §5c:
  the **multi-KO channel** (`multi_gene_knockout.py` + the `variant_kwargs` route through
  `runSim.py` → `variantSimData.py` → `apply_variant.py`); the **positional-condition fixes**
  (`ppgpp_conc.py`, `aa_synthesis_ko.py`, `rrna_operon_knockout.py`, plus an upstream `AttributeError`
  in `tf_activity.py`); and the **container-build fix** (`cloud/docker/runtime/Dockerfile`).
- **`dependency`** (3) — `MIX0-57-GLC-{20,5,2}mM.tsv`. Not category (b), but the category (b)
  `condition_defs.tsv` rows 1/2/3 (Cellarium's `variant_map` indices 1, 2, 3) are invalid without
  them. 512 bytes each.

**81% of the byte weight is one file.**
`reconstruction/ecoli/flat/optimization/trna_charging_kinetics_solutions.tsv` is 4,938,625 bytes
(4.94 MB) of the 6.06 MB. It is an *optimiser output*, not a hand-authored input, and
`scripts/verify_trna_objective.py` reproduces its rows. It is kept in-tree so that a clone reproduces
the corpus without a refit, but it is the obvious candidate for out-of-band hosting. Everything else
is 43 files totalling 1,151,679 bytes (1.15 MB).

**Not shipped, deliberately:** `wholecell/utils/_trna_charging.cpython-310-x86_64-linux-gnu.so`
(1.47 MB, Linux-only). It is compiled inside the model image by `setup.py`, which the overlay's
`setup.py` registers.

---

## 5. What is still missing — read this before trusting a checkout

> **Status, 2026-08-03: nothing is blocked and nothing on Cellarium's launch path is absent.**
> `apply_model_overlay.py` reports `44 shipped, 0 blocked`. §5a (the five ROUTE1-blocked port files)
> and §5c (the multi-KO channel and the condition/build fixes) are both **cleared**; they are kept
> below because *how* they were cleared is the evidence. What remains genuinely open is listed in
> §5b and at the end of §5c.

### 5a. The five ROUTE1-blocked files — CLEARED

These five were blocked by gate 1 and named on every `apply_model_overlay.py` run. They now ship,
from de-ROUTE1'd copies in `model_overlay/cleaned/`:

| file | ROUTE1 markers (worktree → cleaned) | edits | route |
|---|---|---|---|
| `models/ecoli/processes/polypeptide_elongation.py` | 28 → 0 | 23 | revert + re-derive |
| `wholecell/utils/scriptBase.py` | 5 → 0 | 2 | revert |
| `wholecell/sim/simulation.py` | 3 → 0 | 2 | revert |
| `wholecell/fireworks/firetasks/simulation.py` | 1 → 0 | 2 | revert |
| `wholecell/fireworks/firetasks/simulationDaughter.py` | 1 → 0 | 2 | revert |

"Revert" = delete a ROUTE1-only block that was purely additive. "Re-derive" = restore the exact
upstream `a4497e17` text where ROUTE1 had *rewritten* an existing line — 12 of the 23 edits in
`polypeptide_elongation.py`, including the `ribosome_conc_a_site` occupancy rewrite, the branched
`calculate_trna_charging` call and the `dcdt` state slice. Every edit was applied by anchored
exact-match with a "matched exactly once" assertion; the acceptance proof is that the finished file
diffs against upstream as **insertions only** (the port), with no modified or deleted lines.

The ROUTE1 isoacceptor exploration was deliberately extracted to
`github.com/evanniko1/wcecoli-extension-tRNA-isoacceptors` (`BACKLOG.md:176`); only the port stayed.
Shipping the working-tree files verbatim would have re-imported exactly what was extracted. The
extension repo is **not** a dependency of Cellarium and the cleaning did not use it: each ROUTE1
addition was reverted against upstream `a4497e17` directly.

**What came out** — every marker in the removal brief: `ROUTE1-21`, `ROUTE1 step 2`,
`trna_charging_resolution`, `trna_demand_split`, `dcdt_jit_iso`, `clamp_charging_shared`,
`T2A`/`A2T`/`KMtf_trna`/`n_trna_per_aa`/`trna_charging_mask`, and the occupancy-form rewrite of
`ribosome_conc_a_site` in `ppgpp_metabolite_changes`.

**What stayed** — the kinetic elongation model, which is the whole point:
`KineticTrnaChargingModel`, `CoarseKineticTrnaChargingModel`, `resolve_elongation_flags`, and the
`kinetic_trna_charging` / `coarse_kinetic_elongation` flags on all four allow-lists
(`scriptBase.METADATA_KEYS`, `scriptBase.SIM_KEYS`, and both firetask `optional_params`).
`src/cellarium/capability.py` maps mode `kinetic` → `--kinetic-trna-charging`; that flag was **dead
on a public clone** before this and is live now.

**Verification** — `scripts/verify_overlay_route1.py` checks both halves, because a marker count
alone cannot distinguish "the isoacceptor work was removed" from "the kinetic model was removed
along with it", and the second failure is silent (the flag still parses, the run quietly selects
`SteadyStateElongationModel`). Measured on the shipped sources and on a clean `a4497e17` checkout
with the overlay applied: 0 markers, all five parse, kinetic model present, and the whole overlaid
tree greps to zero `ROUTE1` and zero dangling ROUTE1 identifiers. Against the contaminated working
tree the same script exits 1 — the check has a working negative control.

**Measured on the overlaid clean checkout:** `--kinetic-trna-charging` and
`--coarse-kinetic-elongation` are accepted by the `runSim.py` parser and
`--trna-charging-resolution` / `--trna-demand-split` are rejected; every `SIM_KEYS` and
`METADATA_KEYS` name is defined by the parser (`data.select_keys` does `mapping[key]` with no
default, so a missing one is a `KeyError` on *every* launch); both firetask `optional_params`
lists cover `SIM_KEYS` (Fireworks raises on an unlisted kwarg); and `resolve_elongation_flags`
returns `KineticTrnaChargingModel` / `CoarseKineticTrnaChargingModel` / `SteadyStateElongationModel`
for the three flag combinations.

**~~Still open~~ — CLOSED:** this used to record that `runscripts/manual/runSim.py` was not in the
overlay, with two consequences: it is where `--multi-ko-indices` lives, and it is the *second* call
site of `resolve_elongation_flags` — the one that writes the **resolved** flags into `metadata.json`,
without which a public-clone `--kinetic-trna-charging` run simulates correctly and records
`"trna_charging": true`. It now ships as category `cellarium` (§5c). It carries **0** ROUTE1 markers,
so it needed no surgery, only review of its 134/54 delta against upstream.

Regenerating these files from the recipe would not have worked either, because:

### 5b. EXT-PORT-12 has no applier at all

`apply_trna_port.py` *warns* that EXT-PORT-12 is not applied; there is no `ext_port_12_patch.py`.
Measured on a completed recipe run against clean upstream, 9 of the 20 modified port files reproduce
**byte-identically** from a clean checkout — but the rest carry work no committed script produces:

- `wholecell/sim/simulation.py` — `resolve_elongation_flags()`, the single definition of what the
  elongation flags resolve to (114 non-ROUTE1 changed lines)
- `models/ecoli/listeners/trna_charging.py` — `_kinetic_path` / `next_aa_ribosomes_dropped`
- `wholecell/utils/_trna_charging.pyx` — `srand(seed)` replacing `srand(time(NULL))`
- `models/ecoli/processes/metabolism.py` (49), `listeners/growth_limits.py` (52),
  `sim/initial_conditions.py` (20) — never touched by the recipe at all

The overlay ships the working-tree versions of the ROUTE1-free ones and the `model_overlay/cleaned/`
versions of the five in §5a, which is how all 28 port files ship with nothing blocked.

### 5c. Category (c) — the gap — is now the `cellarium` category, and it is CLOSED

This section used to list what Cellarium needed and the overlay did not carry. All of it now ships as
category **`cellarium`** (9 files). Kept as a section rather than deleted, because *why* each file has
to be here is the part a reader needs.

**The multi-KO channel — four files, and three of the four failure modes are quiet.**
`src/cellarium/runner.py:94` emits `--variant multi_gene_knockout 0 0 --multi-ko-indices <i> <j> …`
on the live launch path. The gene set is **not** the variant index; it travels as a `variant_kwargs`
dict across four files, and each one shipping is load-bearing:

| file | action | what it contributes | if it is missing |
|---|---|---|---|
| `runscripts/manual/runSim.py` | modify | `--multi-ko-indices` + `multi_ko_variant_kwargs()` validation | `unrecognized arguments` at launch |
| `wholecell/fireworks/firetasks/variantSimData.py` | modify | `variant_kwargs` in `optional_params`, passed on | Fireworks raises on the undeclared kwarg, at variant creation |
| `models/ecoli/sim/variants/apply_variant.py` | modify | the `variant_kwargs` parameter, splatted into the variant | `TypeError` inside the firetask |
| `models/ecoli/sim/variants/multi_gene_knockout.py` | **create** | the variant itself | `ImportError` on **every** variant run — registration is eager |

The worst case is none of those: a tree where the flag parses and the gene set is dropped on the way
down runs a **wild type wearing a knockout's label** — the WELL-NOOP-1 pattern already in the backlog.
`scripts/verify_overlay_variants.py` therefore checks the channel link by link rather than checking
that a run completed.

`runSim.py` ships for a **second, independent** reason: it is the other call site of
`resolve_elongation_flags`, the one that writes the **resolved** elongation flags into `metadata.json`.
Without it, a `--kinetic-trna-charging` run on a public clone simulates correctly and records
`"trna_charging": true` — a provenance defect that every corpus row would inherit. It carries **0**
ROUTE1 markers, so it needed no surgery.

**The positional-condition fixes — four files.** Upstream looks conditions up by **row number**:
`condition(sim_data, 2)` for `with_aa`, `ordered_conditions[1]` for rich media,
`sorted(saved_timelines)[28]` for the minimal-to-rich shift. Those literals are correct against
upstream's **5-row** `condition_defs.tsv`. This overlay ships **24 rows** (gate 2), where index 1 is
`glc_20mM` and index 2 is `glc_5mM` — so every one of them now resolves to a *different condition*,
the run completes, and it answers a question nobody asked. `ppgpp_conc.py` and
`rrna_operon_knockout.py` are both in `envelope.VALIDATED_PERTURBATIONS`, i.e. on the live path;
`aa_synthesis_ko.py` is not, and its *other* known defect (cistron indices into a TU-indexed function,
`docs/KNOCKOUT_SEMANTICS.md`) is deliberately **not** fixed here. `tf_activity.py` fixes an upstream
`AttributeError` — it wrote through `sim_data.external_state.environment`, which does not exist.

**The container-build fix — one file, and it is the one that decides whether any of this is
reachable.** Measured 2026-08-03 on a fresh `git clone` of the public repo at `a4497e17`: upstream's
own `cloud/build-containers-locally.sh` **fails**, twice over, before any Cellarium code is involved.
`Equation==1.2.1` (an sdist-only pin, imported by `wholecell/utils/enzymeKinetics.py:10`) runs a
2013-era `ez_setup` that downloads setuptools from a `pypi.python.org` path now serving HTML →
`zipfile.BadZipFile`. Fix that and `stochastic-arrow==1.0.0` fails next: its `setup.py` imports numpy
with no build-requires, so PEP 517 isolation hides the numpy installed one line earlier. The overlay
ships `cloud/docker/runtime/Dockerfile` with **four added `pip` lines and no other change**; the
measurement and the reasoning are in the file's own banner.

That file comes from a third source directory, `model_overlay/authored/`, which `harvest()` checks
before `cleaned/` and before `--source`. `cleaned/` carries an implicit claim — "the source tree minus
ROUTE1, diff against upstream is insertions only" — that an authored file does not satisfy and must
not be read as making. The manifest records `"source": "model_overlay/authored"` per file.

**Verified end to end**, on a fresh public clone (not a `git archive` of the fork): overlay applied
(`31 to replace, 13 to create, 0 problems`, idempotent on re-run), image built with
`cloud/build-containers-locally.sh` (exit 0), and inside the image `import models.ecoli.sim.variants`
succeeds with 29 variants registered — `gene_knockout`, `graded_gene_knockout` and
`multi_gene_knockout` all resolving — `wholecell.utils._trna_charging` imports (the Cython extension
compiled), `resolve_elongation_flags` returns `KineticTrnaChargingModel`, and `runSim.py --help`
lists `--multi-ko-indices`, `--kinetic-trna-charging` and `--coarse-kinetic-elongation`.

**Still not here, and still a gap:** `docker/local/` does not exist upstream and is not shipped. It is
also no longer needed — `cloud/build-containers-locally.sh` is the supported route and is what
`README.md` and `docs/DOCKER_SETUP.md` now tell users to run.

---

## 6. Regenerating the overlay

```bash
# materialise the pinned upstream, read-only
git -C /path/to/wcEcoli archive a4497e17 | tar -x -C /tmp/upstream_a4497e17

python scripts/build_model_overlay.py --source /path/to/wcEcoli --upstream /tmp/upstream_a4497e17
python scripts/build_model_overlay.py --check     # CI: rebuild in memory, diff, write nothing
```

To re-pin against a newer upstream: materialise the new commit, change `UPSTREAM_COMMIT` in
`scripts/build_model_overlay.py`, rebuild, and **review every file whose `upstream_sha256` moved** —
each one is a place where upstream changed code we are shadowing.
