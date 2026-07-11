# HF upload ledger — evanniko1/cellarium-corpus (PUBLIC)

Living record of what is on the Hugging Face dataset vs. what is still local-only. **Update this after every
upload batch.** Local raw corpus total: **361 GB** (~187 runs, 138,983 files). Upload rate observed ~4 MB/s
(≈32 Mbps, connection-bound) → full corpus ≈ ~1 day continuous; a curated subset is the plan for the submission.

## ✅ Uploaded (live on the public repo)
| Path | What | Notes |
|---|---|---|
| `README.md` | dataset card | `data/hf/README.md` |
| `data/manifest/vmnik-compact.parquet` | distilled manifest, 238 rows | the full queryable corpus |
| `runs/cellarium/condition_000001/000000.tar.gz` | raw archive | round-trip validated (download+extract OK) |
| `runs/cellarium/condition_000001/000001.tar.gz` | raw archive | |
| `runs/cellarium/condition_000001/000002.tar.gz` | raw archive | |

## 🎯 Planned — curated raw subset (target 100–150 GB)
Selection criteria: the scientifically load-bearing designs (wildtype controls; the machinery-KO landscape
rpoB/dnaN/argS/alaS/pheS/rplB/rpmE/gltX; metabolic/reroute KOs pfkA/tpiA/gltA/fabI/…; representative graded
sweeps ppGpp/rRNA-operon/objective-weight; key conditions). **Exact run list pending the per-design size scan.**
Upload with `scripts/hf_pack_upload.py --designs <list>` (flag to be added).

## ⬜ Not uploaded (local-only)
Everything else — the remainder of the 361 GB raw corpus. Full upload deferred: needs a ~1-day resumable push
+ an HF research-storage grant request (datasets@huggingface.co) given the size.

## Caveats
- `CELLARIUM_HF_HAS_RAW` is a **global** flag → once a *partial* subset is up, `data_availability` would claim
  HF-download for *every* run. Fix before flipping it: have `data_availability` check the run's archive actually
  exists on HF (or read this ledger's uploaded list) instead of the global flag.
