# Published agent-engineering practice: what Cellarium applies, and what it does not

2026-10-28. Written because a reference list that is cited but not applied is decoration. Every row below is
either backed by a measurement in this repository or marked as not done.

The honest headline: **of the eight sources consulted on 2026-10-27, four were applied, two were applied only in
part, and two had never been looked at against the code at all.** The two that had not were the ones that found
the most.

---

## 1. What was applied, and the evidence

| Source | What it prescribes | What Cellarium does | Evidence |
|---|---|---|---|
| MCP server-tools spec (2025-06-18) | split a protocol error from a tool execution error; carry the latter inside the result with a structured payload the model can act on | `errors.py`: every error carries `reason` (18 codes), `about`, `next_step`, attached at the dispatch boundary | `conformance.contract_sweep` — 28 refusals, all with a registered reason |
| Anthropic, *Writing effective tools for agents* | errors steer the agent to the right call; paginate/filter/truncate with defaults and say what was dropped | `next_step` + `did_you_mean`; the survey digest and `trim_nested` name their omissions | `budget_sweep` — 4 trims, each naming what it dropped |
| Anthropic, *Demystifying evals for AI agents* | a harness or environment fault must never be scored as a model answer | `about == "environment"` is that rule in machine-readable form | 9 of 28 refusals are `environment`, 7 `corpus` |
| SWE-agent (ACI) | summaries with capped lists that state what was omitted | the survey digest | fault 6, Appendix E |
| TRAJECT-Bench (ICLR 2026) | "similar tool confusion" and "parameter-blind selection" are invisible to final-answer scoring | family 6 (name confusability) and, after this audit, families 8 + ENUM-3/4 | 2,628 pairs measured; 18 enum parameters exercised |

## 2. What this audit found that had been missed

### 2.1 OpenAI's function-calling guidance — **was not applied at all**

The rule is one sentence: *if the values are enumerable, do not use a free-form string*; strict schemas require
`additionalProperties: false` and complete `required`.

Measured before any change:

| | |
|---|---|
| string parameters across the 73 tools | **123** |
| of those carrying an `enum` | **15 (12%)** |
| whose *name* denotes a closed set but carry no enum | **33** |
| `channel` parameters with **no description at all** | **6** |

A model was being asked to pick a member of an eleven-value namespace from an empty description. That is
`parameter-blind selection` by TRAJECT-Bench's name, and it is the shape of three of the day's refusals: a
channel that is not a manifest column, one not stored per generation, one with too few seeds.

**Applied:** thirteen channel parameters now declare the namespace from `instrument.CHANNELS`, the single
declared list — not a per-tool guess, because an enum narrower than reality forbids valid calls silently, which
is the absence failure moved into the schema. Enum count went 15 → 28.

**And the check found a second defect immediately.** `chart` had **no `required` list at all**, while the tool
refuses every call that names no run — the schema told the model an empty call was valid. A one-of-three
requirement cannot be written as `required`, so it is now `anyOf`. This was only visible because the
enum-honesty sweep could not exercise `chart` at all.

**Not done:** 39 string parameters still have no description. That is documentation debt rather than a
correctness bug, and it is recorded here rather than silently left out.

### 2.2 MAST (Cemri et al., ICLR 2026) — **had never been applied to the Council**

MAST is a taxonomy of 14 failure modes of *multi-agent* LLM systems in three categories, from 150 traces with
κ = 0.88. The Council — proposer, skeptic, judge, librarian — is this project's only true multi-agent system,
and it had never been read against the taxonomy.

| MAST mode | Does it apply here | Finding |
|---|---|---|
| FM-1.2 disobey role specification | yes — the skeptic is charted to propose nothing | historical: the skeptic's objections returned as a JSON string and a guard kept only dicts, recording zero (Appendix E, fault 1) |
| FM-2.4 information withholding | yes — the librarian's brief goes to proposer and skeptic, **never the judge** | **deliberate and correct**: the judge assesses falsifiability structure, not agreement with the literature. Declared, not accidental — the distinction MAST exists to draw |
| FM-1.5 unaware of termination conditions | yes | `max_rounds = 4`, plus two exit branches |
| FM-3.1 premature termination | **yes — and this is the finding** | see below |

**The finding.** `README.md` said the judge "converges only when an adequacy rubric *and* a code-level quota of
doubt *both* hold". The Platform Map said "convergence is not eligible until the skeptic has raised, and the
proposer has resolved, a minimum number of distinct substantive objections". The code (`council.py:961`) reads:

```python
if clean and (total_substantive >= quota or consecutive_clean >= 2):
```

`docs/SOCRATIC_COUNCIL.md` D5 states the `or` correctly; the two public documents did not. This is not academic:
**the head-to-head run of 28 October converged through the stability branch, with one substantive objection
against a quota of three.** Anyone reading the README would have believed three were raised and resolved.

Both documents are corrected. The convergence rule itself is **not** changed — changing an instrument after
seeing one run of it is the failure this project exists to avoid — and "does the stability branch terminate too
early?" is now the sharper form of the already-open question of whether the quota helps at all. MAST's own
measured intervention is suggestive: adding a verification step raised ChatDev's task success by 15.6 points.

### 2.3 The pattern neither family 1–6 nor any reference named

Checking the Council's hypothesis for runnability turned up three views that each answered "what can be run"
and all disagreed, while **families 1–6 passed on every one of them**: each answer was complete, deterministic,
correctly shaped and correct in isolation.

| perturbation | corpus rows | envelope (gates launch) | `design_space` (what the agent is told) | `dial_labels` (what the Council sees) |
|---|---|---|---|---|
| `graded_gene_knockout` | 22 | yes | **no** | yes |
| `amino_acid_shift` | — | yes | **no** | yes |
| `new_gene` | — | yes | **no** | yes |
| `metabolism_kinetic_objective_weight` | 24 | **no** | yes | no |
| `metabolism_secretion_penalty` | 18 | **no** | yes | no |

An agent asking what it could run was told a launchable perturbation with 22 corpus rows did not exist — and
was offered two the gate refuses in the same turn. The Council proposed a graded knockdown only because it reads
the other list.

**The near-miss worth recording:** the first fix was going to add the two metabolism levers to the envelope.
`generate.py` documents that arm as **untested**, with whether it belongs in the envelope as open work
(FAIL-2/FAIL-3). The exclusion is deliberate. So the rule is not "make the lists identical" but "a difference
must be declared", and `design_space` now returns them under `not_in_envelope`. Family 7 enforces it.

MAST's name for this family is apt: inter-agent misalignment — the system held the right answer somewhere and
handed a different one to the component that needed it.

The same shape in the channel namespace: `ppgpp_conc`, `rela_conc` and `ribosome_conc` were advertised
unconditionally though none is written under kinetic charging. They now carry `recorded_when`.

## 3. Reviewed and deliberately not adopted now

| Source | Why not, and what it would take |
|---|---|
| OpenTelemetry GenAI semantic conventions (`execute_tool`, `gen_ai.tool.name`, `gen_ai.usage.*`) | `observability.usage_record` is a bespoke per-LLM-call shape whose docstring makes it a contract ("additions must be backward-additive"). The right move is an **exporter** mapping it to the OTel attribute names, not a rename. No consumer exists yet. Note that there is no per-tool-call span: the analogue is `evidence.record`, which is opt-in (`CELLARIUM_EVIDENCE=1`) |
| TRAJECT-Bench's *metrics* (tool selection, argument correctness, dependency/order satisfaction) | family 6 mitigates one failure mode; the trajectory metric itself is an **eval**, not a tool fix. The input it needs already exists — the v1–v6 discovery-leg traces carry every tool call in order — so this is scoring work on data in hand, and belongs with the eval suite |
| pass@k / pass^k (Anthropic evals) | not implemented as a harness metric. It is immediately usable: the five Council replicates are literally a pass^k setup, and the right question of them is how often all five survive the same checks, not how good the best one is |
| AWS AgentCore evaluators, Google ADK `tool_trajectory_avg_score` | evaluator taxonomies that overlap the three rows above; adopting them wholesale would duplicate families 1–8 under other names. Revisit if the trajectory eval gets built |
| StableToolBench | cited for *why* an environment fault must be separable from a result; its harness (caching unstable third-party APIs) does not apply — Cellarium's tools are local and deterministic, which families 3 and 4 already enforce |

## 4. What the conformance sweep now asks

1. **Absence** — an unreadable source answers with an error, never an empty success.
2. **Shape** — valid JSON at any size, and anything dropped is named.
3. **Determinism** — two identical calls agree; reordering rows changes nothing.
4. **Context** — the answer does not depend on the working directory.
5. **Contract** — a refusal names its kind: `reason`, `about`, `next_step`.
6. **Selection** — no two tool names are confusable without each saying when to use the other.
7. **Agreement** — two views of one capability do not disagree, unless the difference is declared.
8. **Declared sets** — a closed value set is an enum, and no declared value is one its own tool refuses.

Families 7 and 8 exist because of this audit. Both found real defects on their first run.
