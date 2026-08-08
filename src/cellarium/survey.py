"""Deterministic corpus survey — the anti-anchoring primitive.

Anchoring on the first salient run is not fixable by prompting (Lou 2024); the fix is to hand the agent the
WHOLE corpus, pre-computed and ranked by salience, so its (position-biased) attention isn't what decides what
matters. `survey_corpus` reads every run × channel from the manifest and returns, per channel, designs ranked
by |z| across designs (+ % change vs a reference), a cross-channel notable set, and coverage. No LLM, no
cherry-picking: the ranking is arithmetic. Cellwright must consume this before forming a hypothesis (see agent.py).
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict

from . import manifest, stats

# two conventions are present in the corpus: "…·s0" (current) and "… seed0" (older/contributed)
_SEED_SUFFIX = re.compile(r"(·s\d+|\s+seed\d+)$")

MANIFEST_GLOB = "data/manifest/*.parquet"
# host-safe channel names (the worker owns the table/column mapping; we only need the names here)
CHANNELS = ["growth_rate", "ppgpp_conc", "ribosome_conc", "fraction_trna_charged", "rela_conc",
            "dry_mass", "protein_mass", "rna_mass", "cell_mass", "division_rate", "fba_objective"]
DIAGNOSTIC = {"fba_objective"}       # solver diagnostics — queryable, but excluded from the biological ranking
# division_rate (§J viability): mostly 1.0, so a low value is a strong flag — a KO/perturbation that did NOT divide
REFERENCE = ("wildtype", "basal")   # the control designs are compared against


_IDENT_CACHE: dict = {}


def _identity(design_key: str):
    """Cached factors.identity — the honest name for a design. Never raises: a missing cache must degrade to
    "no annotation", not break the survey the whole agent depends on."""
    if design_key not in _IDENT_CACHE:
        try:
            from . import factors
            _IDENT_CACHE[design_key] = factors.identity(design_key)
        except Exception:
            _IDENT_CACHE[design_key] = None
    return _IDENT_CACHE[design_key]


def depth(row: dict) -> int | None:
    """A run's GENERATION DEPTH — which is not a nuisance to average over but part of WHAT WAS MEASURED.

    Two wrong answers were shipped before this one, and both are worth recording because the third only looks
    obvious afterwards.

    Three `wildtype/basal` seed-0 runs disagreed. **First answer: the machine.** Two came from different
    contributors, so the model was declared non-bit-deterministic across environments and the seeds treated as
    clustered by machine. Withdrawn: those runs also differed in `generations`, and at a fixed depth the machine
    ICC is exactly 0.0. **Second answer: cluster on depth instead** — same machinery, new variable, ICC 0.28-0.85.
    Also withdrawn, because the premise was false. The stated mechanism was "a channel mean is taken over the
    whole trajectory, so depth moves it"; `_reader_worker.py:203` is `_dynamics(gs[-1])` — the LAST generation
    only. Measured: `growth_rate == per_generation[-1]` on 91/91 rows, `== mean over generations` on 0/91.

    So depth does not add variance. **It selects which generation you are looking at**: a gens=1 run reports
    generation 0, a gens=7 run reports generation 6. The decisive test — same lineages, compared at a MATCHED
    generation index — collapses the effect to nothing:

        growth @ reported index   gens=1 .000247804 | gens=4 .000222002 | gens=7 .000220008   ICC 0.6795
        growth @ matched  gen 0   gens=1 .000247804 | gens=4 .000251334 | gens=7 .000254435   ICC 0.0000

    Runs of different depth ARE exchangeable, at the same index. A random-effects widening is the wrong
    estimator for a deterministic, recorded, fixed effect — and worse, it widened the interval while leaving the
    MEAN pooled, so `pct_vs_ref` kept dividing by a depth-averaged reference. Six designs flip sign against a
    depth-matched one, `rRNA_KO:2op` from -7.4% to +2.2%.

    The remedy is therefore STRATIFICATION, not correction: compare like with like. This function names the
    stratum. See `_reference_by_depth`.
    """
    g = row.get("generations")
    return int(g) if isinstance(g, (int, float)) else None


def _machine(row: dict) -> str:
    """The contributor a row came from — genuine provenance, worth reporting, and NOT a variance component: at a
    fixed generation index its ICC is zero on every channel. See `depth` for the two withdrawn attempts."""
    m = row.get("contributor") or row.get("machine")
    if m:
        return str(m)
    p = str(row.get("simout_path") or "").replace("\\", "/")
    for prefix in ("/Users/", "/home/"):
        if prefix in p:
            return p.split(prefix, 1)[1].split("/", 1)[0] or "local"
    return "local"


def design_tag(row: dict) -> str:
    """The identity of a DESIGN (the thing all its seeds are replicates of), taken from `label`, NOT from the raw
    `condition` column.

    Why this exists — it is a correctness fix, not a cosmetic one. `manifest._flat_row` persists
    `design.condition` verbatim while `label` gets `manifest._design_tag(design)`. Keying analyses on the raw
    column therefore MERGES designs that are different experiments, and two such merges are live in the current
    265-run corpus:

      * every `timeline` run stores `condition=None`, so an amino-acid UPSHIFT (`0 minimal, 1200
        minimal_plus_amino_acids`) and a DOWNSHIFT (`0 minimal_plus_amino_acids, 1200 minimal`) both key to
        `timeline/None` — and get averaged together as "4 seeds of one design". They are opposite experiments.
      * the propose path writes `condition='basal'` with the genes in `params.target_genes`, so the
        gltX+relA+spoT triple knockout keys to `multi_gene_knockout/basal`, while the generate.py path for the
        same perturbation keys correctly to `KO:pfkA+pfkB`.

    `label` already carries the correct tag, so deriving from it fixes every existing row retroactively — no
    re-index, which matters because re-indexing needs Docker and 117 of the 265 rows have no run directory left.
    """
    lab = str(row.get("label") or "")
    core = _SEED_SUFFIX.sub("", lab)
    if "·" in core:
        return core.split("·", 1)[1]
    # A SECOND labelling convention exists in this corpus — 41 rows read
    # `metabolism_kinetic_objective_weight/minimal|kin_w:1e-7_default seed0`, i.e. slash-and-space rather than
    # the interpunct form. They resolved correctly until now only by luck, because their `condition` column
    # happened to be right; silently falling through to that column is precisely how a gltX knockout came to be
    # filed as a `basal` control. Recognise the form explicitly instead.
    if "/" in core:
        return core.split("/", 1)[1]
    return row.get("condition") or row.get("timeline") or "basal"   # genuinely pre-label rows


def design_key(row: dict) -> str:
    """'perturbation/tag' — the string form used as a design's public identity across the tools."""
    return f'{row.get("perturbation")}/{design_tag(row)}'


def _deduped_rows(channels: list[str]) -> list[dict]:
    import duckdb

    con = duckdb.connect()
    last = ""
    # `label` is REQUIRED (not just nice): design identity is derived from it — see design_tag().
    # `generations` is REQUIRED: it is the analysis STRATUM (see `depth`), not decoration — without it every
    # design silently pools runs that measured different generations of a lineage.
    # `contributor` is the real provenance column. A `machine` column was in this list for one commit; it was
    # never written to a single shard, so tier 1 took a Binder Error on EVERY read and fell through to a tier
    # that also lacked `contributor` — leaving provenance guessed from the path, wrongly. Ask for what exists.
    for cols in (["id", "label", "perturbation", "condition", "timeline", "seed", "qc", "reportable", "pathways",
                  "simout_path", "contributor", "generations", *channels],
                 ["id", "label", "perturbation", "condition", "timeline", "seed", "qc", "reportable", "pathways",
                  "simout_path", "generations", *channels],
                 ["label", "perturbation", "condition", "timeline", "seed", "qc", "reportable",
                  "generations", *channels],
                 ["label", "perturbation", "condition", "timeline", "seed", "qc", "reportable", *channels]):
        # `elongation_model` is appended to EVERY tier, not just tier 1, and as an expression rather than a
        # bare name. It cannot Binder-Error (the helper resolves to a literal when no shard carries the column
        # yet), so unlike the `machine` incident recorded above it cannot knock a tier out; and putting it on
        # every tier means a degraded read still says which elongation model each row came from, which is the
        # one field a lower tier must never lose.
        # `kb_sha256` and `operons` join `elongation_model` as the ARM columns (corpus_schema.ARM_KEYS): they
        # decide whether two rows are comparable at all, so a read that omits them cannot refuse a cross-arm
        # pool. Appended to EVERY tier for the same reason the elongation model is — a degraded read must still
        # say which instrument each row came from. COALESCE so a pre-column shard reads '?' rather than NULL,
        # because NULL would silently compare equal to another NULL and merge two unknown arms into one.
        arm_sel = ["COALESCE(\"kb_sha256\", '?') AS kb_sha256", "COALESCE(\"operons\", '?') AS operons"]
        sel = ", ".join([*(f'"{c}"' for c in cols), manifest.elongation_sql(), *arm_sel])
        q = (f"WITH d AS (SELECT * FROM read_parquet('{MANIFEST_GLOB}', union_by_name=true) "
             f"{manifest.DEDUP_QUALIFY}) "
             f"SELECT {sel} FROM d")
        try:
            rows = con.execute(q).fetch_arrow_table().to_pylist()
            return _mark_dropped(rows)
        except Exception as exc:
            last = str(exc)
    con.close()
    return [{"__error__": last}]


def _mark_dropped(rows: list[dict]) -> list[dict]:
    """Stamp `_dropped` on tombstoned rows (WELL-1y) rather than removing them: the ranking and comparisons
    exclude `_dropped`, but coverage keeps counting them, so the DB never silently forgets a dropped run. A row
    without `id`/`simout_path` (old shard, fallback projection) can't be keyed and is treated as live."""
    dropped = manifest.dropped_keys()
    if not dropped:
        return rows
    for r in rows:
        if r.get("id") is not None or r.get("simout_path") is not None:
            r["_dropped"] = manifest.dedup_key_py(r) in dropped
    return rows


def analysis_rows() -> tuple[list[dict], list[str]]:
    """THE row source for every comparison tool. One function, so a third copy of the filtering cannot drift.

    Three readers had grown their own: `survey_corpus` filtered on `reportable`, `differential` did not, and
    `rigor.disconfirm` neither filtered nor used `design_key` — it keyed on `perturbation/condition`, which is
    NULL for timelines and 'basal' for propose-path knockouts, the exact drift that once merged two opposite
    nutrient shifts. Consequence: `disconfirm`, the tool whose job is to CHALLENGE a claim, was reporting an
    interval 5.5x narrower than `survey_corpus` for the same cell, over crashed runs, under a key that can
    collide. A disconfirmation tool that is more confident than the thing it checks is worse than no tool.

    Returns `(rows, channels)` with `_pw` (pathways) parsed and non-reportable runs removed.
    """
    import json
    rows = _deduped_rows(CHANNELS)
    if not rows or "__error__" in rows[0]:
        return [], []
    keep = []
    pw_keys: set[str] = set()
    for r in rows:
        if not r.get("reportable") or r.get("_dropped"):
            continue     # crashed -> garbage channels; tombstoned (WELL-1y) -> curated out of every comparison
        try:
            r["_pw"] = json.loads(r.get("pathways") or "{}")
        except Exception:
            r["_pw"] = {}
        pw_keys |= set(r["_pw"])
        keep.append(r)
    return keep, CHANNELS + [f"pw:{k}" for k in sorted(pw_keys)]


def channel_value(row: dict, channel: str):
    """A channel's value, whether it is a summary column or a `pw:<pathway>` fraction. Shared for the same
    reason as `analysis_rows`: three private copies of this existed."""
    return row["_pw"].get(channel[3:]) if channel.startswith("pw:") else row.get(channel)


def _leth_rows() -> list[dict]:
    """Deduped rows with the per-generation QC + trajectory — the columns `lethality` needs and the channel
    surveys deliberately omit (they are large JSON). Separate query so the hot path stays lean."""
    import duckdb
    con = duckdb.connect()
    # `label` is REQUIRED, not decorative: `design_key` derives identity from it, and without it `design_tag`
    # falls through to the nullable `condition` — the exact D3 drift that filed the gltX KO as a `basal` run,
    # so gltX's one reportable seed would be miscounted and gltX would read as fully_hidden when it is not.
    cols = ("label, perturbation, condition, timeline, seed, generations, reportable, qc, "
            "generation_qc, per_generation")
    q = (f"WITH d AS (SELECT * FROM read_parquet('{MANIFEST_GLOB}', union_by_name=true) {manifest.DEDUP_QUALIFY}) "
         f"SELECT id, simout_path, {cols} FROM d")
    try:
        return _mark_dropped(con.execute(q).fetch_arrow_table().to_pylist())
    except Exception as exc:
        return [{"__error__": str(exc)}]
    finally:
        con.close()


def _as_list(v):
    import json
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return v or []


def lethality(reference: str = "wildtype/basal") -> dict:
    """Surface COLLAPSE — the lethality phenotype every reportable-only view discards, and the user's flagged
    blind spot: we hold sims that divide for a generation or two and then collapse, but they are invisible.

    A run whose late generation collapses is (correctly) marked non-reportable so its garbage last-generation
    channel mean cannot pollute the ranking — `is_reportable` requires EVERY generation to be ok. But the
    collapse itself is DATA: an essential-gene KO that divides on inherited enzyme, mounts a **stringent
    response** (ppGpp up, growth down), then collapses numerically is exactly the lethality signal to test
    against literature (an aminoacyl-tRNA synthetase KO → uncharged tRNA → RelA → ppGpp is textbook) and lab.

    This reads the phenotype back from the per-generation QC verdicts (`generation_qc`) and the per-generation
    growth/ppGpp trajectory (`per_generation`), reporting the PRE-COLLAPSE signature only — never the post-
    collapse garbage. A design invisible to `survey_corpus` because every seed collapses (dapA, rpmE) is visible
    here. It does not gate or rank on channels; it is a first-class viability landscape, depth-matched to the WT
    trajectory so the signature is read at the generation it actually occurred.
    """
    rows = _leth_rows()
    if not rows or "__error__" in rows[0]:
        return {"error": rows[0].get("__error__") if rows else "no rows", "designs": []}

    # WT growth/ppGpp per generation index, so a pre-collapse value is compared at its OWN generation (D7).
    wt_g: dict = defaultdict(list)
    wt_p: dict = defaultdict(list)
    for r in rows:
        if design_key(r) == reference and r.get("reportable"):
            for p in _as_list(r.get("per_generation")):
                if isinstance(p, dict) and p.get("i") is not None:
                    if p.get("growth") is not None:
                        wt_g[int(p["i"])].append(p["growth"])
                    if p.get("ppgpp") is not None:
                        wt_p[int(p["i"])].append(p["ppgpp"])
    wt_growth = {i: statistics.fmean(v) for i, v in wt_g.items() if v}
    wt_ppgpp = {i: statistics.fmean(v) for i, v in wt_p.items() if v}

    by_design: dict = defaultdict(lambda: {"collapse_seeds": 0, "reportable_seeds": 0, "collapse_gens": [],
                                           "verdicts": Counter(), "pre_growth": [], "pre_ppgpp": [], "pre_gen": []})
    for r in rows:
        if r.get("_dropped"):        # tombstoned runs (WELL-1y) are curated out of the lethality view too
            continue
        k = design_key(r)
        gq = _as_list(r.get("generation_qc"))
        if r.get("reportable"):
            by_design[k]["reportable_seeds"] += 1
            continue
        # a collapse: a run that read some generations, the first-bad of which is not generation 0 (i.e. it
        # divided at least once before failing). A gen-0 failure or an empty read is a dead/degenerate run, a
        # different category handled by coverage — this view is specifically the "divided, then collapsed" signal.
        bad = next((i for i, s in enumerate(gq) if s != "ok"), None)
        if bad is None or bad == 0:
            continue
        d = by_design[k]
        d["collapse_seeds"] += 1
        d["collapse_gens"].append(bad)                 # collapses AT generation `bad` (0-indexed)
        d["verdicts"][gq[bad]] += 1
        pg = _as_list(r.get("per_generation"))
        last_ok = next((p for p in pg if isinstance(p, dict) and p.get("i") == bad - 1), None)
        if last_ok:
            d["pre_gen"].append(bad - 1)
            if last_ok.get("growth") is not None:
                d["pre_growth"].append(last_ok["growth"])
            if last_ok.get("ppgpp") is not None:
                d["pre_ppgpp"].append(last_ok["ppgpp"])

    out = []
    for k, d in by_design.items():
        if not d["collapse_seeds"]:
            continue
        pre_i = round(statistics.fmean(d["pre_gen"])) if d["pre_gen"] else None
        g = statistics.fmean(d["pre_growth"]) if d["pre_growth"] else None
        p = statistics.fmean(d["pre_ppgpp"]) if d["pre_ppgpp"] else None
        wg, wp = wt_growth.get(pre_i), wt_ppgpp.get(pre_i)
        # the biological read: at the last good generation, is growth depressed AND ppGpp elevated vs WT? that is
        # the stringent-response signature — reported as a flag, not asserted, so it can be checked not trusted.
        stringent = bool(g is not None and wg and p is not None and wp and g < 0.9 * wg and p > 1.1 * wp)
        ident = _identity(k)
        out.append({
            "design": k,
            "true_label": (ident.get("true_label") if ident and ident.get("label_integrity") != "ok" else None),
            "fully_hidden": d["reportable_seeds"] == 0,   # NO reportable seed — invisible to survey_corpus
            "collapse_seeds": d["collapse_seeds"], "reportable_seeds": d["reportable_seeds"],
            "collapses_at_generation": (Counter(d["collapse_gens"]).most_common(1)[0][0]
                                        if d["collapse_gens"] else None),
            "collapse_qc": dict(d["verdicts"]),
            "pre_collapse": {"generation": pre_i, "growth": (round(g, 6) if g is not None else None),
                             "ppgpp": (round(p, 2) if p is not None else None),
                             "growth_pct_vs_wt": (round(100 * (g - wg) / wg, 1) if (g is not None and wg) else None),
                             "ppgpp_pct_vs_wt": (round(100 * (p - wp) / wp, 1) if (p is not None and wp) else None)},
            "stringent_signature": stringent,
        })
    out.sort(key=lambda e: (not e["fully_hidden"], -e["collapse_seeds"]))
    return {
        "reference": reference,
        "n_designs_collapsing": len(out),
        "n_fully_hidden": sum(1 for e in out if e["fully_hidden"]),
        "designs": out,
        "note": ("Designs that DIVIDE then COLLAPSE at depth — the lethality phenotype the reportable-only "
                 "ranking excludes (a collapsed generation's channel mean is numerical garbage, so the whole run "
                 "is non-reportable). Here the PRE-collapse growth/ppGpp is read at its own generation vs WT: a "
                 "depressed-growth + elevated-ppGpp `stringent_signature` on an essential-gene KO is the textbook "
                 "uncharged-tRNA → RelA → ppGpp response, to be checked against literature/lab, NOT asserted. "
                 "`fully_hidden` designs have zero reportable seeds and are otherwise invisible to survey_corpus."),
    }


# ---- WELL-1x: per-generation reporting (the 1-to-1 and trajectory comparison operations of the D7 contract) ----
# The summary channel is the LAST generation's mean, so the ordinary tools compare designs at whatever depth
# each reached. These read a channel AT a chosen generation instead — the operation that makes a collapsing
# design inspectable (its valid early generations are usable even though the run is non-reportable) and lets two
# designs be compared like-for-like at the same generation.
#
# Only growth + ppGpp are stored per generation (`per_generation`); the full panel per generation needs raw or a
# panel expansion (still owed under WELL-1x). So these functions cover exactly those two channels and say so
# rather than silently returning nothing for the rest.
_PERGEN_KEY = {"growth_rate": "growth", "growth": "growth", "ppgpp_conc": "ppgpp", "ppgpp": "ppgpp"}


def _pergen_channel(channel: str) -> str | None:
    return _PERGEN_KEY.get(channel)


def read_at_generation(design: str, channel: str, generation: int) -> dict:
    """A channel's mean at ONE generation index across a design's seeds — counting only seeds whose that
    generation passed QC. This is what makes a collapsing run's VALID early generations usable: reportability is
    a whole-run verdict, but generation_qc is per-generation, so gen 0/1 of a run that collapses at gen 2 are
    still trustworthy and counted here.
    """
    key = _pergen_channel(channel)
    if not key:
        return {"error": f"'{channel}' is not stored per generation — only growth_rate/ppgpp_conc are "
                         f"(per_generation holds growth+ppGpp). Per-generation values for other channels need "
                         f"raw simOut or the panel expansion (WELL-1x)."}
    rows = _leth_rows()
    if not rows or "__error__" in rows[0]:
        return {"error": rows[0].get("__error__") if rows else "no rows"}
    vals, excluded = [], 0
    for r in rows:
        if design_key(r) != design:
            continue
        gq = _as_list(r.get("generation_qc"))
        pg = _as_list(r.get("per_generation"))
        if generation < len(gq) and gq[generation] == "ok":
            p = next((x for x in pg if isinstance(x, dict) and x.get("i") == generation), None)
            if p and p.get(key) is not None:
                vals.append(p[key])
        elif generation < len(gq):
            excluded += 1                       # this seed reached the generation but it failed QC there
    if not vals:
        return {"design": design, "channel": channel, "generation": generation, "n": 0,
                "note": f"no seed has a QC-ok generation {generation} for '{channel}'"}
    return {"design": design, "channel": channel, "generation": generation,
            "mean": round(statistics.fmean(vals), 6), "n": len(vals),
            "ci95": (round(stats.t95_halfwidth(vals), 6) if len(vals) > 1 else None),
            "n_seeds_failed_qc_here": excluded,
            "note": ("mean over seeds whose generation " f"{generation} passed QC — a collapsing run's valid "
                     "early generations ARE included, its collapsed generation is not.")}


def compare_at_generation(design_a: str, design_b: str, channel: str, generation: int) -> dict:
    """The 1-to-1 generation comparison (D7): design_a vs design_b at the SAME generation index — the operation
    whose confound-free result was measured (ICC→0). No depth mismatch is possible because both sides are read
    at one generation."""
    a = read_at_generation(design_a, channel, generation)
    b = read_at_generation(design_b, channel, generation)
    if "error" in a:
        return a
    if "error" in b:
        return b
    out = {"generation": generation, "channel": channel, "a": a, "b": b}
    if a.get("n") and b.get("n"):
        pct = (100.0 * (a["mean"] - b["mean"]) / b["mean"]) if b["mean"] else None
        out["diff_a_minus_b"] = round(a["mean"] - b["mean"], 6)
        out["pct_a_vs_b"] = round(pct, 1) if pct is not None else None
    out["note"] = (f"{design_a} vs {design_b}, both read AT generation {generation} — a like-for-like comparison "
                   "the depth-stratified survey cannot express for a design that collapses before its modal depth.")
    return out


def trajectory(design: str, channel: str = "growth_rate") -> dict:
    """The per-generation ARC of a design: mean value + QC status at every generation index, so a collapse is
    VISIBLE as the generation where QC turns bad. This is the lethality-case inspection — `trajectory` on a
    collapsing design shows the good early generations, then the QC verdict at the collapse point."""
    key = _pergen_channel(channel)
    if not key:
        return {"error": f"'{channel}' is not stored per generation — only growth_rate/ppgpp_conc are."}
    rows = _leth_rows()
    if not rows or "__error__" in rows[0]:
        return {"error": rows[0].get("__error__") if rows else "no rows"}
    by_gen_val: dict = defaultdict(list)
    by_gen_qc: dict = defaultdict(Counter)
    n_seeds = 0
    for r in rows:
        if design_key(r) != design:
            continue
        n_seeds += 1
        gq = _as_list(r.get("generation_qc"))
        pg = _as_list(r.get("per_generation"))
        for i, s in enumerate(gq):
            by_gen_qc[i][s] += 1
            if s == "ok":
                p = next((x for x in pg if isinstance(x, dict) and x.get("i") == i), None)
                if p and p.get(key) is not None:
                    by_gen_val[i].append(p[key])
    if not n_seeds:
        return {"design": design, "channel": channel, "error": "no seeds for this design"}
    gens = sorted(by_gen_qc)
    arc = [{"generation": i,
            "mean": (round(statistics.fmean(by_gen_val[i]), 6) if by_gen_val.get(i) else None),
            "n_ok": len(by_gen_val.get(i, [])), "qc": dict(by_gen_qc[i])} for i in gens]
    collapse = next((i for i in gens if any(s != "ok" for s in by_gen_qc[i])), None)
    return {"design": design, "channel": channel, "n_seeds": n_seeds,
            "collapses_at_generation": collapse, "arc": arc,
            "note": ("Per-generation mean (QC-ok seeds only) + the QC verdict spread at each generation. A "
                     "collapse shows as the generation where `qc` stops being all-ok; earlier generations remain "
                     "usable. Only growth/ppGpp are stored per generation.")}


def survey_corpus(channels: list[str] | None = None, top: int = 6) -> dict:
    import json

    base = channels or CHANNELS
    rows = _deduped_rows(base)
    if rows and "__error__" in rows[0]:
        return {"error": f"corpus query failed: {rows[0]['__error__']}"}
    if not rows:
        return {"error": "corpus is empty — generate a campaign first (see docs/GENERATE.md)."}

    # expand the per-pathway proteome fractions into first-class channels (pw:<pathway>)
    pw_keys: set[str] = set()
    for r in rows:
        try:
            r["_pw"] = json.loads(r.get("pathways") or "{}")
        except Exception:
            r["_pw"] = {}
        pw_keys |= set(r["_pw"])
    all_channels = base + [f"pw:{k}" for k in sorted(pw_keys)]

    def val(r: dict, ch: str):
        return r["_pw"].get(ch[3:]) if ch.startswith("pw:") else r.get(ch)

    # G1 (audit re-analysis): rank only REPORTABLE runs — a crashed/degenerate run's channel values are garbage
    # (e.g. gltX post-crash growth ranked z=+5.05). Non-reportable runs stay in `coverage` below, just not ranked.
    by_design: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("reportable") and not r.get("_dropped"):   # tombstoned runs are excluded from ranking (WELL-1y)
            by_design[(r["perturbation"], design_tag(r))].append(r)

    # STRATIFY ON DEPTH, do not correct for it. A channel is the LAST generation's time-mean
    # (`_reader_worker.py:203`), so depth selects WHICH generation is reported, and pooling depths compares
    # generation 0 of one run with generation 6 of another. At a matched index the effect is zero (see `depth`),
    # so the fix is to compare like with like rather than to widen an interval around a mixed mean.
    #
    # Each design is summarised at ONE depth — the one with the most reportable seeds — and compared against the
    # reference AT THAT SAME DEPTH. Nothing is lost: measured on this corpus, every design has a depth-matched
    # reference available (the reference itself spans 1/4/7) and only 4 designs span more than one depth.
    def _modal_depth(rs: list[dict], ch: str) -> int | None:
        c = Counter(depth(r) for r in rs if val(r, ch) is not None)
        return max(c, key=lambda d: (c[d], -(d if d is not None else 1 << 30))) if c else None

    def dmean_ci(rs: list[dict], ch: str, at_depth: int | None = None):
        """Mean + plain 95% t interval over the seeds at ONE depth. Returns (mean, ci, n, info) where `info`
        records the stratum and what was set aside, so a reader can see the analysis was not run over everything."""
        d = at_depth if at_depth is not None else _modal_depth(rs, ch)
        here = [val(r, ch) for r in rs if val(r, ch) is not None and depth(r) == d]
        other = sum(1 for r in rs if val(r, ch) is not None and depth(r) != d)
        if not here:
            return None, None, 0, None
        info = {"generations": d, "n_at_depth": len(here), "n_other_depths": other}
        return statistics.fmean(here), stats.t95_halfwidth(here), len(here), info

    # The reference, per depth. This is the fix that actually moves numbers: `pct_vs_ref` used to divide by a
    # wildtype mean pooled over depths 1/4/7, which is a BIASED denominator — six designs flip sign against a
    # depth-matched one (rRNA_KO:2op -7.4% -> +2.2%).
    def _reference_by_depth(ch: str) -> dict:
        rs = by_design.get(REFERENCE) or []
        out: dict = defaultdict(list)
        for r in rs:
            v = val(r, ch)
            if v is not None:
                out[depth(r)].append(v)
        return {d: statistics.fmean(v) for d, v in out.items()}

    stats_by_design = {d: {ch: dmean_ci(rs, ch) for ch in all_channels} for d, rs in by_design.items()}
    ref_by_depth = {ch: _reference_by_depth(ch) for ch in all_channels}
    means = {d: {ch: v[0] for ch, v in chs.items()} for d, chs in stats_by_design.items()}
    ref = means.get(REFERENCE)

    by_channel: dict[str, dict] = {}
    notable: list[dict] = []
    for ch in all_channels:
        refs = ref_by_depth.get(ch) or {}
        ref_v = (ref or {}).get(ch)          # the reference's own modal-depth mean, for display
        entries = []
        for d, m in means.items():
            v = m.get(ch)
            if v is None:
                continue
            _mn, ci, n, _st = stats_by_design[d][ch]
            gens = (_st or {}).get("generations")
            # DEPTH-MATCHED denominator. The pooled one was biased, not merely imprecise.
            rv = refs.get(gens)
            pct = (100.0 * (v - rv) / rv) if (rv not in (None, 0)) else None
            key = f"{d[0]}/{d[1]}"
            e = {"design": key, "mean": round(v, 6),
                 "ci95": (round(ci, 6) if ci is not None else None), "n": n,
                 "generations": gens,
                 "pct_vs_ref": (round(pct, 1) if pct is not None else None)}
            if rv is None:
                e["pct_vs_ref_note"] = (f"no reference run at generations={gens}; a pooled comparison would be "
                                        f"biased (the channel is the LAST generation's mean), so none is given")
            if _st and _st.get("n_other_depths"):
                # Not a caveat on the number — a statement about what the number is OVER.
                e["depth_note"] = (f"summarised at generations={gens} (n={_st['n_at_depth']}); "
                                   f"{_st['n_other_depths']} further seed(s) ran to a different depth and measure "
                                   f"a different generation, so they are not pooled in")
            # A design's NAME can be wrong (KO:rpoB silences nothing; KO:flgB deletes nine genes). survey_corpus
            # is the mandatory first read, so the honest name travels with the number rather than being
            # discoverable only if the agent thinks to ask. Only attached when it differs — keeps the payload small.
            ident = _identity(key)
            if ident and ident.get("label_integrity") != "ok":
                e["true_label"] = ident["true_label"]
                e["label_integrity"] = ident["label_integrity"]
            entries.append(e)
        if len(entries) < 2:
            by_channel[ch] = {"reference": ref_v, "ranked": entries}
            continue
        # z WITHIN the depth stratum. Ranking designs measured at generation 0 against designs measured at
        # generation 3 on one pooled spread would put the generation drift into the salience score itself.
        for gens in {e.get("generations") for e in entries}:
            grp = [e for e in entries if e.get("generations") == gens]
            vs = [e["mean"] for e in grp]
            mu, sd = statistics.fmean(vs), (statistics.pstdev(vs) or 1e-12)
            for e in grp:
                e["z"] = round((e["mean"] - mu) / sd, 2) if len(grp) > 1 else 0.0
                e["z_scope"] = f"vs {len(grp)} design(s) at generations={gens}"
        entries.sort(key=lambda e: abs(e["z"]), reverse=True)
        # INFORMATIVE truncation (same convention as top_movers' "k of N significant dropped"). This tool exists
        # to stop the agent anchoring on whatever it happened to look at first — so silently showing 6 of N
        # designs and saying nothing would reintroduce the exact bias it was built to remove.
        by_channel[ch] = {"reference": (round(ref_v, 6) if ref_v is not None else None),
                          "n_designs_with_data": len(entries), "n_shown": min(top, len(entries)),
                          "n_dropped": max(0, len(entries) - top),
                          "ranked": entries[:top]}
        if ch not in DIAGNOSTIC:  # keep solver diagnostics out of the biological notable ranking
            notable += [{"channel": ch, **e} for e in entries if abs(e["z"]) >= 2.0]

    notable.sort(key=lambda e: abs(e.get("z", 0)), reverse=True)
    # What `coverage` must NOT do is let an agent read `n_designs` and believe it has seen the corpus. Three
    # things were invisible before: designs excluded from ranking entirely (n_designs counted only the survivors),
    # designs whose mean rests on FEWER seeds than were run because some crashed, and — per channel, above — how
    # many ranked designs were truncated away.
    seeds_by_design: dict[str, list] = defaultdict(list)
    for r in rows:
        seeds_by_design[design_key(r)].append(bool(r.get("reportable")))
    partial = sorted(k for k, v in seeds_by_design.items() if 0 < sum(v) < len(v))
    excluded = sorted(k for k, v in seeds_by_design.items() if not any(v))
    # TOMBSTONED runs (WELL-1y): excluded from ranking above, but coverage KEEPS them — the DB never silently
    # forgets a dropped run. Reported here so a shrunk corpus is explained, not just smaller.
    dropped_meta = manifest.dropped_keys()
    dropped_here = [r for r in rows if r.get("_dropped")]
    # THE DEPTH STRATA, disclosed at corpus level rather than only per entry. Per-entry notes ride along with a
    # design's row, but the ranking truncates to the top |z| and `wildtype/basal` sits at z=0 BY CONSTRUCTION
    # (it is the reference), so the design whose stratification matters most is structurally unable to appear.
    depths_by_design: dict[str, set] = defaultdict(set)
    for r in rows:
        if r.get("reportable"):
            depths_by_design[design_key(r)].add(depth(r))
    mixed = {k: sorted(v, key=lambda x: (x is None, x)) for k, v in depths_by_design.items() if len(v) > 1}
    strata = Counter(d for v in depths_by_design.values() for d in v)
    coverage = {
        "n_designs_ranked": len(by_design),          # what the ranking is actually computed over
        "n_designs_in_corpus": len(seeds_by_design),  # ...out of this many
        "n_designs_excluded": len(excluded),          # every seed non-reportable -> absent from every ranking
        "n_designs": len(by_design),                  # kept: existing callers read this (== n_designs_ranked)
        "n_runs": len(rows),
        "reference_present": ref is not None,
        "qc": dict(Counter(r["qc"] for r in rows)),
        "non_reportable_designs": excluded,
        # a mean over 3 of 4 seeds is not wrong, but the agent must know the replicate count shrank
        "designs_with_partial_seeds": {k: f"{sum(v)}/{len(v)} seeds usable"
                                       for k, v in seeds_by_design.items() if 0 < sum(v) < len(v)},
        "designs_spanning_generation_depths": {k: f"generations {v}" for k, v in sorted(mixed.items())},
        "n_runs_dropped": len(dropped_here),          # tombstoned (WELL-1y) — kept here, excluded from ranking
        "dropped_runs": ([{"design": design_key(r), "id": r.get("id"),
                           "reason": (dropped_meta.get(manifest.dedup_key_py(r)) or {}).get("reason")}
                          for r in dropped_here] if dropped_here else []),
        "generation_strata": {f"generations={d}": n for d, n in sorted(strata.items(),
                                                                       key=lambda kv: (kv[0] is None, kv[0]))},
        "note": (f"{len(by_design)} of {len(seeds_by_design)} designs are ranked; {len(excluded)} are excluded "
                 f"(every seed non-reportable) and {len(partial)} rest on a reduced seed count. Per channel, "
                 f"`n_dropped` says how many ranked designs are not shown. "
                 f"EVERY figure is STRATIFIED BY GENERATION DEPTH: a channel is the LAST generation's time-mean, "
                 f"so a run to 1 generation reports generation 0 and a run to 7 reports generation 6. Each design "
                 f"is summarised at its best-covered depth and compared to the reference AT THAT DEPTH; `z` ranks "
                 f"within the depth stratum. Depths present: "
                 f"{', '.join(f'{d}({n} designs)' for d, n in sorted(strata.items(), key=lambda kv: (kv[0] is None, kv[0])))}."
                 + (f" {len(mixed)} design(s) have seeds at more than one depth "
                    f"({', '.join(sorted(mixed))}); those seeds measure different generations and are NOT pooled "
                    f"— each entry's `depth_note` says how many were set aside."
                    if mixed else "")),
    }
    # LETHALITY, surfaced in the mandatory first read (the flagged blind spot): designs that divide then
    # collapse are excluded from the ranking above because a collapsed generation's channel mean is garbage —
    # but the collapse is a phenotype, not noise. A compact pointer here; the full pre-collapse signature is in
    # `lethality()` / the `lethality_landscape` tool. Kept compact so the hot path stays small.
    leth = lethality()
    leth_summary = {
        "n_designs_collapsing": leth.get("n_designs_collapsing", 0),
        "n_fully_hidden": leth.get("n_fully_hidden", 0),   # zero reportable seeds -> invisible to the ranking above
        "collapsing_designs": [
            {"design": e["design"], "collapses_at_generation": e["collapses_at_generation"],
             "fully_hidden": e["fully_hidden"], "stringent_signature": e["stringent_signature"]}
            for e in leth.get("designs", [])],
        "note": ("Designs that DIVIDE then COLLAPSE at depth — a lethality phenotype, NOT in the ranking above "
                 "(a collapsed generation's channel mean is numerical garbage). `n_fully_hidden` have zero "
                 "reportable seeds and are otherwise invisible. Call `lethality_landscape` for the pre-collapse "
                 "growth/ppGpp signature vs the depth-matched WT — a signal to CHECK against literature, not assert."),
    }
    return {
        "coverage": coverage,
        "lethality": leth_summary,
        "notable": notable[:12],            # biggest effects across ALL channels, ranked by |z|
        "by_channel": by_channel,
        "note": ("Deterministic full-corpus survey ranked by computed salience (|z| across designs). "
                 "Consume this BEFORE forming a hypothesis; do not anchor on any single run or on prior "
                 "conversation. Then drill in with read_series / read_species and seek disconfirming evidence. "
                 "See `lethality` for designs that collapse at depth — excluded from the ranking but real."),
    }
