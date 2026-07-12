# HF upload ledger — evanniko1/cellarium-corpus (PUBLIC)

Living record of what is on the Hugging Face dataset vs. what is still local-only. **Update this after every
upload batch.** Local raw corpus total: **361 GB** (~187 runs, 138,983 files). Upload rate observed ~4 MB/s
(≈32 Mbps, connection-bound) → full corpus ≈ ~1 day continuous; a curated subset is the plan for the submission.

## ✅ Uploaded (live on the public repo)
| Path | What | Notes |
|---|---|---|
| `README.md` | dataset card | `data/hf/README.md` |
| `data/manifest/vmnik-compact.parquet` | distilled manifest, 238 rows | full queryable corpus; **paths sanitized** (repo-relative, no host leak) 2026-07-12 |
| `runs/cellarium/condition_000001/*.tar.gz` | raw archives (3 seeds) | round-trip validated (download+extract OK) |
| `runs/**/*.tar.gz` | **curated raw subset — 13 designs / 55 runs (~90–100 GB compressed)** | see the list below; task `bls546073`, finished 2026-07-12 (verified against the upload log) |

### Curated raw subset (uploaded) — the value-weighted, load-bearing set
Packed via `scripts/hf_pack_upload.py --designs "<list>"` (one `.tar.gz` per run under `runs/cellarium/<design>/<seed>`).
Verified live design→shard counts: condition_000007 (8), gene_knockout_001594 (6), gene_knockout ×7 @ 4 each
(000644, 001340, 002074, 002078, 002095, 002819, 002835), multi_gene_knockout_227981 (1), ppgpp_conc_000000 (4),
rrna_operon_knockout_000002 (4), wildtype_374656 (4) = **55 runs**.
- **control:** `wildtype_374656`
- **KO landscape:** `gene_knockout_002095` (rpoB, late-crash), `002819` (lysS), `001594` (pfkA, reroute),
  `002074`, `000644` (argS), `002078` (alaS), `001340` (pheS), `002835` (rplB)
- **multi-KO:** `multi_gene_knockout_227981` (pfkA+pfkB)
- **graded:** `ppgpp_conc_000000`, `rrna_operon_knockout_000002`
- **condition:** `condition_000007`

## ⬜ Not uploaded (local-only)
Everything else — the remainder of the 361 GB raw corpus. Full upload deferred: needs a ~1-day resumable push
+ an HF research-storage grant request (datasets@huggingface.co) given the size.
- **`gene_knockout_000058` (dnaN, 4 seeds, all QC=`crashed`)** — was in the curated *plan* but excluded from the
  `bls546073` batch, so it is **not** on the repo. It exists locally; add it in the next batch if a lethal-KO
  exemplar is wanted (the manifest still describes all 4 seeds, so the agent can reason about it either way).

## Caveats
- `CELLARIUM_HF_HAS_RAW` is a **global** flag → once a *partial* subset is up, `data_availability` would claim
  HF-download for *every* run. Fix before flipping it: have `data_availability` check the run's archive actually
  exists on HF (or read this ledger's uploaded list) instead of the global flag.
