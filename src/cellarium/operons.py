"""Should a run be built with operons ON or OFF — and what changes if you switch.

WHY THIS IS A MODULE AND NOT A SENTENCE IN A DOC. The operon option is the single configuration choice
that silently redefines what every other answer in this project MEANS. Under operons ON a
`gene_knockout` is an *operon* knockout; under OFF it is a true single-gene knockout. Same variant,
same flag, same output columns, same "success" — different experiment. We already shipped three wrong
claims because that was recorded in prose nobody queried (`docs/KNOCKOUT_SEMANTICS.md`), so it is
exposed here as data an agent must read before advising.

NOTHING HERE IS INVENTED. Every claim is either (a) traced to a line in the model checkout, (b)
measured — on the corpus, or in the operons-OFF experiment recorded as `BACKLOG.md` OPERONS-3 — or
(c) an open backlog row quoted as OPEN.

THE FIRST DRAFT OF THIS FILE SAID "this project has never run operons OFF". That was false, and it is
recorded here rather than quietly fixed, because it is the failure mode the module exists to prevent:
a plausible sentence written from memory instead of read off the evidence. OPERONS-3 ran it — ParCa
green in 380 s, `probe_relation.py` 0/4309 mismatches, two 120 s sims and a full generation exiting 0.
What is genuinely unestablished is narrower and is stated as such below: no KNOCKOUT has been run
under OFF, and OPERONS-1 (a/b/c) is still open, so the invariants are argued rather than pinned.

THE ADVICE IS ALSO ABOUT NOT SWITCHING. The problem people reach for `--operons off` to solve — "my
knockout deleted the whole operon" — has a cheaper fix that keeps the corpus comparable:
`graded_gene_knockout`, which resolves the gene's own cistron and suppresses EVERY transcription unit
carrying it, exactly as the ParCa's own genotype-perturbation path does. That is a variant choice, not
a knowledge-base rebuild.
"""

from __future__ import annotations

# --------------------------------------------------------------------------------------------------
# HOW THE FLAG IS SET. Traced in the checkout; the citations are file:line against upstream a4497e17
# (unmodified by this overlay — the overlay ships no change to any of them).
# --------------------------------------------------------------------------------------------------
MECHANISM = {
    "where_it_is_set": "runParca.py only — it is a ParCa (knowledge-base build) option, NOT a simulation option",
    "option": "--operons {off,on}",
    "default": "on",
    "code_path": [
        "wholecell/utils/constants.py:7-9 — OPERON_OPTIONS = ('off','on'); DEFAULT_OPERON_OPTION = 'on'",
        "wholecell/utils/scriptBase.py:394-399 — define_parameter_operons() adds --operons",
        "wholecell/utils/scriptBase.py:414,429 — it is added by define_parca_options(), and by nothing else",
        "runscripts/manual/runParca.py:49 — runParca calls define_parca_options; runSim does NOT",
        "wholecell/fireworks/firetasks/parca.py:68 — InitRawDataTask(operons=self.get('operons'))",
        "reconstruction/ecoli/knowledge_base_raw.py:185-186,212,244 — KnowledgeBaseEcoli(operons_on=...)",
    ],
    "not_a_sim_option": (
        "MEASURED: `grep -c operons runscripts/manual/runSim.py` = 0. There is no per-simulation "
        "override. Switching the operon mode means re-running ParCa and producing a DIFFERENT "
        "simData.cPickle, so runs from the two knowledge bases are separate arms — never rows in one "
        "comparison."),
    "recorded_per_row": (
        "Every manifest row carries `operons` and `kb_sha256` (src/cellarium/manifest.py:379), derived "
        "from the kb the run was made against (src/cellarium/provenance.py:71-120). It used to be "
        "filesystem inference; it is now stamped provenance, so a published row is self-describing."),
}

# --------------------------------------------------------------------------------------------------
# WHAT IT CHANGES. The one structural fact everything else follows from.
# --------------------------------------------------------------------------------------------------
WHAT_CHANGES = {
    "the_one_fact": (
        "`sim_data.process.transcription.rna_data` rows are TRANSCRIPTION UNITS under operons ON "
        "(reconstruction/ecoli/dataclasses/process/transcription.py:497-540 — TUs first, then only the "
        "cistrons no TU covers) and one row per CISTRON under OFF."),
    "measured_shape": "operons ON: 3,276 rna_data rows for 4,724 genes. OFF: rna_data degenerates to cistrons.",
    "downstream": [
        "KNOCKOUTS. `gene_knockout` computes a positional index into rna_data and calls "
        "adjust_final_expression([i],[0]) (reconstruction/ecoli/simulation_data.py:314), which zeroes ONE "
        "ROW. Under ON that row is a whole operon; under OFF it is one gene. docs/KNOCKOUT_SEMANTICS.md "
        "measures the three outcome classes this produces under ON: (1) a real KO that also deletes "
        "operon partners (KO:flgB -> nine flg genes at 0.0 mRNA and 0.0 protein); (2) the named gene is "
        "NOT knocked out (KO:rpoB, mRNA 10.4 vs wildtype 8.4); (3) it silences a gene it is not named "
        "after (KO:rpmJ -> secY to 0.0).",
        "MULTI-GENE KNOCKOUTS inherit the same index space: a k-target multi_gene_knockout can silence "
        "far more than k genes (docs/KNOCKOUT_SEMANTICS.md, the variant table).",
        "THE REDUCED-GENOME POOL. A pool of 4 'genes' measured as deleting 13 (BACKLOG WELL-6o), because "
        "flgB brings eight partners and ymgD brings ymgG. Fixed by reporting n_genes_deleted, not by "
        "switching the flag.",
        "THE tRNA PORT. v3.0.1's kinetic charging code is self-consistent only with operons OFF, where "
        "rna_data degenerates to one row per cistron; this tree runs ON, and that single difference is "
        "behind most of the port's hard problems (BACKLOG EXT-PORT-1C, closed).",
        "THREE UPSTREAM VARIANTS ARE DEFECTIVE ONLY UNDER ON (BACKLOG WELL-6k): aa_synthesis_ko / "
        "aa_synthesis_ko_shift and ppgpp_limitations.adjust_enzymes pass CISTRON-space indices into a "
        "TU-indexed function (wrong TU, or IndexError); mene_params is a silent no-op. Cellarium does not "
        "launch any of them.",
    ],
    "why_upstream_is_like_this": (
        "Not a design choice anyone defended — a datable oversight. Operons were added 2021-09-13 "
        "(69259c06) with the default OFF; gene_knockout.py was last touched 2022-01-15 (7dc26808), "
        "correct for that world; the default flipped to ON 2022-10-10 (cf3d8e50) and the variant was "
        "never revisited. Its parameter is still named `gene_indices`. Git-verified in the wcEcoli "
        "checkout; written up in docs/KNOCKOUT_SEMANTICS.md."),
}

# --------------------------------------------------------------------------------------------------
# THE TRADEOFF. Both columns are things that are recorded; neither is a preference.
# --------------------------------------------------------------------------------------------------
TRADEOFF = {
    "on": {
        "for": [
            "Polycistronic transcription is real biology, and E. coli single-gene knockouts have "
            "documented polar effects — so operon-level dispensability is a legitimate finding, not only "
            "an artefact (docs/KNOCKOUT_SEMANTICS.md, 'What a user may safely conclude').",
            "It is the model's own default (DEFAULT_OPERON_OPTION = 'on') and the configuration the lab "
            "ships and validates against.",
            "It is what the ENTIRE shipped corpus was built with — MEASURED: 322 of 322 manifest rows "
            "carry operons='on'. Any run meant to be compared with a corpus row must match it.",
        ],
        "against": [
            "A design labelled `KO:X` is not reliably a knockout of X. Verified on the corpus: 10 designs "
            "knocked out, 2 NOT knocked out (murA, rpoB), 1 partial (rpmJ, silences secY), 1 unmeasurable, "
            "7 unverified.",
            "Three upstream variants carry index-space defects that only bite under ON (see WHAT_CHANGES).",
            "v3.0.1's ported kinetic-charging code was written for OFF, so the port carries adaptations "
            "that would be no-ops under OFF and are load-bearing here.",
        ],
    },
    "off": {
        "for": [
            "A `gene_knockout` means what its name says — one cistron, one row, no operon partners. It "
            "removes outcome classes (2) and (3) entirely.",
            "It is v3.0.1's native regime, so the ported kinetic model is in the world it was written "
            "for. MEASURED (BACKLOG OPERONS-2): under OFF, v3.0.1's original codon-sequence line is "
            "element-for-element correct (4538/4538) and its tRNA list matches uncharged_trna_names "
            "86-for-86; under ON the same line covers 224/3276 and the tRNA list is 51 vs 86 with an "
            "intersection of 9.",
            "IT RUNS, and it runs clean (BACKLOG OPERONS-3): ParCa green in 380 s, probe_relation.py "
            "0/4309 mismatches, two 120 s sims and a full generation exiting 0, and every operons-ON "
            "adaptation the port carries is an exact no-op or provably equivalent there. That makes it "
            "a good PORT-INVARIANCE REGRESSION FIXTURE.",
            "It is the only clean way to ask 'was that phenotype the gene or the operon?' as a controlled "
            "comparison rather than an argument.",
        ],
        "against": [
            "It discards polycistronic structure, which is real biology — an OFF knockout is a cleaner "
            "experiment about a less realistic organism.",
            "NOT COMPARABLE with anything shipped: it is a different knowledge base with a different "
            "kb_sha256, so its rows are a separate arm and cannot be pooled with the 322 existing ones.",
            "IT IS NOT A VALIDATION REFERENCE, and the measurement says so in the wrong direction "
            "(BACKLOG OPERONS-3, verdict 'keep it, but as a REGRESSION FIXTURE'). Aggregate charging "
            "OFF 0.8416 vs ON 0.8290 moves FURTHER from Choi & Covert's published 0.788; at "
            "protocol-matched full-generation depth the operons main effect is +0.0016 (ON 0.8184 over "
            "2174 steps, OFF 0.8200 over 2126); and it makes the headline within-family spread WORSE "
            "(GLY 0.336 -> 0.405, LEU 0.274 -> 0.358). Two uncontrolled factors each move that number "
            "by more than the whole 0.042 gap it was meant to explain: a monotonic -0.052 "
            "within-generation drift, and a 1.29x aminoacyl-tRNA-synthetase excess in the ParCa initial "
            "state.",
            "The invariants the port relies on are ARGUED under OFF, not PINNED: BACKLOG OPERONS-1 (a) "
            "index-space invariants as tests, (b) each adaptation shown a NO-OP rather than merely "
            "believed to be one, (c) probe_relation.py in CI against BOTH configurations — all still "
            "open.",
        ],
    },
}

# The corpus fact the recommendation rests on. Re-measured by `advise()` rather than trusted, because a
# routine action — running one operons-OFF campaign — would make this literal false with nothing raising.
CORPUS_OPERONS_MEASURED_2026_08_03 = {"on": 322}

NOT_ESTABLISHED = [
    "HOW A KNOCKOUT BEHAVES UNDER OFF. The operons-OFF experiment (BACKLOG OPERONS-3) measured the "
    "tRNA-CHARGING axis on wildtype-class runs. No `gene_knockout` has been run under OFF, so the "
    "central claim people reach for the flag to test — 'the phenotype was the operon, not the gene' — "
    "has no measurement behind it in this project. Do not quote one.",
    "WHETHER THE PORT'S ADAPTATIONS ARE NO-OPS UNDER OFF AS A TEST rather than as an argument. "
    "OPERONS-3 reports every one of them as an exact no-op or provably equivalent, and OPERONS-1 (a/b/c) "
    "— the row that would turn that report into CI — is still OPEN. An unpinned invariant is one "
    "refactor away from being false with nothing raising.",
    "WHETHER THE 7 UNVERIFIED CORPUS KNOCKOUTS (argS, alaS, gltX, lysS, pfkA, pheS, rplB) are class-1, "
    "class-2 or class-3 designs. That is an ON-mode gap, and switching the flag would not answer it for "
    "rows that already exist — those runs are done.",
]

# The route that solves the usual motivation WITHOUT a knowledge-base rebuild.
ALTERNATIVE = {
    "variant": "graded_gene_knockout",
    "what_it_does": (
        "Resolves the gene's own CISTRON and suppresses EVERY transcription unit carrying it — the same "
        "construction the ParCa's genotype-perturbation path uses, which wcEcoli's own "
        "docs/misc/operon-structure.md describes as the correct approach and which the variant path does "
        "not use. Verified: murA 1789 copies -> 0 across 2 generations."),
    "what_it_fixes": "outcome classes (2) and (3) — the named gene is guaranteed silenced.",
    "what_it_does_NOT_fix": (
        "class (1). Operon partners still go, because they are on the same transcription units. If the "
        "question genuinely requires the partners to survive, no variant answers it and operons OFF is the "
        "only route — as a separate arm."),
    "cost": "none — same knowledge base, same corpus, one different --variant.",
    "ships": "model_overlay/files/models/ecoli/sim/variants/graded_gene_knockout.py",
}


def advise(question: str | None = None, compare_with_corpus: bool = True) -> dict:
    """Operons ON or OFF for a proposed run — with the reasoning, the citations, and the gaps.

    `compare_with_corpus` is the decisive input, not `question`: if the result has to sit beside an
    existing corpus row, the answer is forced (every shipped row is operons ON) and no argument about
    which configuration is *better* can override it. `question` is echoed back and used only to surface
    the knockout-specific guidance, because that is the one topic where the flag changes the MEANING of
    the output rather than its value.

    Returns `recommendation` as a fixed token — `keep_operons_on`, `separate_arm_operons_off`, or
    `use_graded_gene_knockout` — so a caller branches on an enum and not on prose.
    """
    corpus = _measure_corpus()
    q = (question or "").lower()
    # Substring for the multi-character stems; a WORD boundary for `ko`, because as a bare substring it
    # fires on "knock", "koji", "tokyo" and — the one that would actually happen here — the gene symbol
    # `kdpA`. "knock out" is listed separately from "knockout": users write both, and the space is
    # exactly the difference that made this branch silently never fire the first time.
    import re
    knockout_topic = bool(
        any(t in q for t in ("knockout", "knock out", "knock-out", "delete", "deletion", "essential",
                             "dispensab", "reduced genome", "operon"))
        or re.search(r"\bko\b", q))

    if compare_with_corpus:
        token = "keep_operons_on"
        headline = (
            "Keep operons ON. Not because ON is better — because every row you would compare against was "
            "built that way, and an operons-OFF run is a different knowledge base (different kb_sha256), "
            "so it is a separate arm and not a comparable row.")
    else:
        token = "separate_arm_operons_off"
        headline = (
            "Operons OFF is defensible ONLY as a self-contained arm with its own ParCa, its own controls "
            "and its own wildtype — and it is untested in this tree (BACKLOG OPERONS-1 is open). Do not "
            "pool its rows with the shipped corpus.")

    out = {
        "question": question,
        "recommendation": token,
        "headline": headline,
        "how_the_flag_is_set": MECHANISM,
        "what_it_changes": WHAT_CHANGES,
        "tradeoff": TRADEOFF,
        "corpus": corpus,
        "not_established": NOT_ESTABLISHED,
        "cheaper_alternative": ALTERNATIVE,
        "read": ["docs/KNOCKOUT_SEMANTICS.md", "BACKLOG.md OPERONS-1", "BACKLOG.md WELL-6g / WELL-6k / WELL-6o"],
    }
    if knockout_topic:
        out["recommendation"] = ("use_graded_gene_knockout" if compare_with_corpus else token)
        out["knockout_guidance"] = (
            "For a KNOCKOUT question the operon flag is usually the wrong lever. Under operons ON a "
            "`gene_knockout` zeroes one transcription unit, so `KO:X` may leave X expressed (murA, rpoB) "
            "or silence something else (rpmJ -> secY). Use `graded_gene_knockout`, which suppresses every "
            "TU carrying the cistron and guarantees the named gene is silenced, and read the design's "
            "`ko_footprint` before interpreting it. Operon partners still go under either setting — that "
            "is the one thing only operons OFF changes, and no run in this project has done it.")
    return out


def _measure_corpus() -> dict:
    """What the shipped corpus actually says, re-measured. A hardcoded 'all 322 rows are ON' is exactly
    the kind of literal that one campaign falsifies with nothing raising, so the count is read from the
    manifest and the pinned figure is carried alongside as the baseline it is compared to.

    An unreadable manifest reports `verified: False` and says why. It does NOT fall back to the pinned
    number and present it as a measurement."""
    try:
        import glob

        import duckdb

        from . import manifest
        if not glob.glob(str(manifest.MANIFEST_DIR / "*.parquet")):
            raise RuntimeError("no manifest shards to read")
        if "operons" not in manifest.manifest_columns():
            raise RuntimeError(
                "no shard carries an `operons` column — the operon mode was filesystem inference for "
                "rows indexed before manifest.py:379 started stamping it")
        con = duckdb.connect()
        try:
            rows = con.execute(
                f"SELECT operons, COUNT(*) AS n FROM (SELECT * FROM "
                f"read_parquet('{manifest.MANIFEST_DIR}/*.parquet', union_by_name=true) "
                f"{manifest.DEDUP_QUALIFY}) GROUP BY 1 ORDER BY 2 DESC"
            ).fetch_arrow_table().to_pylist()
        finally:
            con.close()
        counts = {(r.get("operons") or "unrecorded"): int(r["n"]) for r in rows}
    except Exception as exc:                                   # noqa: BLE001 — reported, never swallowed
        return {"verified": False,
                "why": f"could not read the manifest ({type(exc).__name__}: {exc})",
                "pinned_baseline": CORPUS_OPERONS_MEASURED_2026_08_03,
                "note": "UNVERIFIED. The pinned baseline is shown for reference and is NOT a measurement "
                        "of the corpus as it stands now."}
    modes = sorted(k for k in counts if k != "unrecorded")
    return {"verified": True, "rows_by_operon_mode": counts,
            "all_one_mode": len(modes) == 1,
            "pinned_baseline": CORPUS_OPERONS_MEASURED_2026_08_03,
            "note": ("Every shipped row is operons ON, so a comparison against the corpus fixes the "
                     "setting." if modes == ["on"] else
                     "The corpus now contains more than one operon mode — rows from different modes are "
                     "different knowledge bases and MUST NOT be pooled. Check `kb_sha256` before "
                     "comparing.")}
