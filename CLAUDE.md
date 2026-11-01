# Cellarium — project instructions

## Task tracking → BACKLOG.md
`BACKLOG.md` is the **single authoritative task list**. When any new task, finding, bug, or idea comes up, add it
there — do not create a separate audit/TODO/roadmap doc.

- Place it under the right **class**: A methodology & rigor · B data science · C LLM engineering · D agentic ·
  E design & UX · F infra & hygiene · G scientific capability · H publication.
- Give it an **ID** consistent with its class (audit findings use `M-`/`DS-`/`LLM-`/`AG-`/`D-`/`UX-`/`H-`/`SP-`;
  new items get a class-consistent id), a **priority** (`P1` before publication/open-source · `P2` soon · `P3`
  polish), a **source** tag, and a one-line description.
- **When an item ships, never delete it** — either strike it through in place (`~~**H-1**~~ ✅`) or move it to a
  **Completed** section at the bottom of `BACKLOG.md`, so the record of what's done stays visible.
- `docs/ROADMAP.md` and `docs/DECISIONS.md` are historical/design **reference only** — not task sources.
- Filippo's Council-defect ledger (D1–D6, branch `operationalization-debate`) is a **separate, Filippo-owned**
  workstream — cross-reference it in BACKLOG, never fold it in.

## Reporting rules (each one caught a real error here)

These are not style preferences. Each is written against a specific failure this project actually produced.

- **Report per-family, never aggregate-plus-one-example** — whenever per-item spread is comparable to or larger
  than the effect you are claiming. Show every family (or every seed, gene, condition) or say plainly which you
  are omitting and why; one illustrative example next to a mean is a *selected* example, and the reader cannot
  tell how it was selected. *Evidence:* re-auditing 18 claims with all 20 amino-acid families displayed
  **weakened or failed 14 of them**, and a headline "fix" turned out to be carried **109% by four families**
  while **9 of 20 moved the other way** — the aggregate was positive only because a few families dominated it.

- **Label evidential standing on every claim** — one of **SIMULATED** (came out of a run in the corpus) ·
  **ALGEBRAIC** (derived from run outputs by arithmetic we did) · **CODE-READ** (read off model source) ·
  **LITERATURE** (external source, cited) · **ARGUED** (reasoning, no direct evidence). The label is part of the
  claim, not a footnote; an unlabelled claim reads as SIMULATED to anyone downstream. *Evidence:* a 150-claim
  audit found failures **clustered in the ARGUED ones**, including a flagship result that had to be **withdrawn**.
  The point of the label is to make that cluster visible *before* it ships, not after.

- **A string search is not a dependency proof.** `grep`/absence-of-token establishes only that a name does not
  appear *as text in the files searched*. It does not establish that a quantity has no causal path into a
  computation — dependencies travel through call arguments, intermediate variables, closures, config, and
  precomputed inputs. To claim independence, trace the data flow (or perturb the input and show the output does
  not move); to claim a dependency exists, a hit is suggestive, not sufficient. *Evidence:* "ppGpp appears
  nowhere in `dcdt_jit`, verified by grep, zero hits" was **true as text and false as a dependency claim** —
  ppGpp enters via `max_elong_rate`. The same text-for-dependency conflation broke **two separate conclusions**.
  The text really is absent, and the dependency really is there, three hops up
  (`model_overlay/files/models/ecoli/processes/polypeptide_elongation.py`): `dcdt_jit` takes `max_elong_rate` as
  a parameter (`:1698`) and uses it for `v_rib` (`:1709`); it is assigned from `self.elongation_rate()` (`:1091`);
  and `SteadyStateElongationModel.elongation_rate` derives that rate from `ppgpp_conc` via `elong_rate_by_ppgpp`
  whenever `ppgpp_regulation` is on (`:1028-1034`). Related, and the same error class: never report a failed read
  or an empty grep as an established fact.

- **An instrument that has not been made to fail is not evidence.** Before a measurement's output is written
  into a file, a commit message, or a reply, the instrument gets the treatment a test gets here. Four things,
  and the third is the one that is usually skipped:
  **(1) assert the precondition** that makes the measurement meaningful, so an invalid run stops instead of
  returning a well-formed number;
  **(2) state the n and the population** the number is over, in the output itself;
  **(3) run it on one input you know it should PASS and one you know it should FAIL** — a known-good case
  alone is nearly worthless, because a proxy agrees with the quantity it stands in for on exactly the easy
  cases and diverges on the hard one;
  **(4) when no answer is known in advance, use two independent instruments and require them to agree** —
  disagreement is the finding, and one of the two is wrong.
  Prefer a committed test over a scratch script for any number that will be cited, because then
  force-it-to-fail applies by convention rather than by memory; see **Numbers in prose need a driver** below.
  *Evidence:* five failures in one session where the **measurement** was the broken part rather than the
  thing measured, in three distinct kinds. *Proxy:* `returncode == 0` stood in for "can this module import
  cellarium" and reported a module that correctly skips wholesale as a failure — it agreed with the real
  question on 30 of 31 modules, so any single known-good case would have passed it; and secreted carbon was
  compared against the mean of all four uptake fluxes, a quantity ammonium dominates and that has nothing to
  do with carbon. *Truncated domain:* a loop printing only rows that matched hid 3 of 13 and sent "differs on
  ten" into four files; "31 modules fixed" was shipped on a sample of three; and 133 − 89 = 44 counted a
  population that was never checked. *Dead instrument:* `clientWidth` on a hidden browser pane is 0, so every
  element read as overflowing; an md5 taken through a cp1252 console reported two files as differing from
  `HEAD` that `git diff --exit-code` calls identical; and text-level equality on restored files hid a
  whole-file CRLF conversion. In every dead-instrument case the disproof was already in my own output and was
  read past, which is why (1) asserts rather than prints. The existing proxy and truncation rules did not
  prevent any of this: those three were broken on the same day they were being cited.

- **Numbers in prose need a driver.** A quantity stated in a document, a docstring, a commit message or an
  answer-key field must have committed code that recomputes it from its source, and the set of such
  quantities must carry a **completeness assertion** — every entry is recomputed, delegated to a named test,
  or declared unrecomputable with a reason, and a new entry that is none of those fails the suite. Checking
  only the values that exist today is insufficient and demonstrably so. Implemented instances to copy rather
  than reinvent: `tests/test_number_provenance.py`, which re-derives `data/hf/CORPUS_COUNTS.json` from the
  shipped manifest and holds the phrase-anchored document claims that quote it — written 2026-11-01 because
  that driver **did not exist** while the Platform Map had claimed for several versions that "a test fails
  when a document disagrees with it"; `CORPUS_COUNTS` appeared in exactly one file in the tree, the script
  that writes it. Also `DRIVEN_ELSEWHERE` / `HISTORY` in
  `tests/test_capbench_cases.py`; `VERDICT_CLAIMS` and `EXPECTED_VERDICT_KIND` in `tests/test_holdout.py`;
  the prose-count recomputation for `docs/HOLDOUT_PREREGISTRATION.md`; and the `GATED_TOOLS` / `TOTAL_TOOLS`
  ledger in `tests/test_mcp_capability_gate.py`. `tests/test_number_provenance.py` enumerates them and fails
  if one loses its completeness assertion. *Evidence:* an audit of twelve freshly written benchmark cases
  found **53 of their 68 recorded values were recomputed by nothing**. All 44 that could be re-derived
  agreed — so no number was wrong, and nothing would have noticed when one stopped being right. That is
  exactly the state `M2_UNRESOLVED_REQUIREMENT_RATE` was in before it drifted **sixteen points** as a literal
  nobody recomputed.

## Orientation
- Package: `src/cellarium/` — the blind Socratic Council (`council.py`), the grounded Cellwright agent
  (`agent.py`, `tools.py`), the guardrails (`provenance.py`, `biosecurity.py`, `envelope.py`, `rigor.py`).
- App: `apps/server.py` + `apps/web/` (the glass-box SPA). Benchmarks: `evals/`. Corpus docs: `docs/`.
- Git: commit and push directly to `main`.
