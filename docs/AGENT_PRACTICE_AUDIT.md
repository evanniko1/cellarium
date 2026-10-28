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

**Then done, 2026-10-28.** The 39 remaining bare string parameters were not documentation debt after all. Every
one of those names *is* described elsewhere in the surface — `reference` on 7 tools, `target` on 5,
`perturbation` on 4, `design`/`result_id`/`gene`/`condition`/`kind` on 3 each — so the defect was not an
undocumented vocabulary but the same word documented on one tool and bare on the next, with which version the
model saw decided by which tool it happened to reach for. The fix is one glossary keyed by the parameter name
(`tools._PARAM_GLOSSARY`), filling only empty descriptions: 37 sites from the glossary, 2 that write their own.
Bare string parameters: **39 → 0**.

A glossary keyed by a NAME is only safe while every site it reaches means the same thing by that name, and two
do not: `kind` is a species class on `top_movers`/`list_species`/`read_species` and a chart type on `chart`;
`search` is a substring filter here and a search strategy on `generate_designs`. Both of those sites already
wrote their own sentence, so the filler never touched them — but that is luck unless it is checked, so
`conformance.glossary_sites_agree` asserts that the sites one entry reached share an enum. A future bare `kind`
on a chart-like tool now fails the sweep instead of inheriting the wrong sentence.

**And the glossary found a defect of its own.** `read_series`, `read_raw_series` and `scan_series` run their
`result_id` through `_resolve_result`, so a design label works; `list_species` and `read_species` go straight to
the run's simOut path, where a label is simply not found. Nothing in the code recorded that difference. It is now
**declared** in those two tools' descriptions rather than removed, because making the species tools resolve
labels would silently pick a representative seed — the same substitution that drew the wrong seeds on discovery
leg v4.

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
| ~~TRAJECT-Bench's *metrics*~~ | **Built 2026-10-28** — see §5 below. `src/cellarium/trajectory.py` scores a recorded trajectory, `scripts/trajectory_eval.py` runs it, 16 tests |
| ~~pass@k / pass^k (Anthropic evals)~~ | **Built 2026-10-28** in both places it was needed: `score_hypotheses.py` (the Council replicate set) and `trajectory.score_set` (the share of trajectories with no contract fault) |
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
8. **Declared sets** — a closed value set is an enum, no declared value is one its own tool refuses, every
   string parameter says what it means, and one glossary sentence never reaches two sites that disagree.

Families 7 and 8 exist because of this audit. Both found real defects on their first run.

---

## 5. Scoring the trajectory, not the answer

TRAJECT-Bench's point is that a correctness check on the final answer cannot see the agent picking a
plausible-looking wrong tool or filling a parameter it had no basis for. Families 6 and 8 guard those at the
schema level. They say nothing about what the agent actually did on a real question, so `trajectory.py` reads
the recorded traces.

**What it is not.** TRAJECT-Bench compares a trajectory against a GOLD trajectory for the task. There are no
gold trajectories for Cellarium's questions, and writing them now — after reading these traces — would be
drawing the target around the shot. So this is the **reference-free subset**: properties of the trace that are
facts about it, checkable without anyone deciding in advance what the right sequence was.

| measure | what it asks | fault? |
|---|---|---|
| selection validity | every called tool exists in the declared surface | yes |
| argument validity | every call satisfies its own schema: required present, no unknown property, right type, enum respected | yes |
| argument faults | calls the surface refused with `about == "request"` — the agent's fault by the error contract | yes |
| grounding | a corpus handle (design label, result_id, gene) appears in the question or in an EARLIER output. One that appears in neither was invented | yes |
| declared order | a tool whose own description calls itself the FIRST STEP was called first. The declaration is read out of the description, so it predates the trace | yes |
| redundancy | identical (tool, arguments) repeated; retries of a tool that just errored | no — descriptive |

**First run, on the six discovery-leg traces (134 tool calls):** 5 of 6 clean, pass^k = 0.83. No unknown tool,
no schema-invalid call, every handle grounded. The one fault is `v4`, which opened on `list_results` while
`survey_corpus`'s own description says *"FIRST STEP for any results question"* — the same trace whose chart drew
the wrong seeds.

**And the measure that could not be measured.** The first run reported a request-refusal rate of 0.000. Those
traces were recorded on 2026-10-27, a day before `errors.py`: 13 of their calls errored and **none** carries an
`about` field, so the trace cannot say whose fault a refusal was. 0.000 would have been an absence in the trace
format presented as a fact about the agent. The set report is three-valued and says
*"not measurable: 13 of 13 errors carry no `about`"*. Two tests hold that behaviour in place.

Every measure is also tested against a trajectory built to violate exactly that measure — a check that cannot
fail reports 1.00 forever.

**Still not built:** an OpenTelemetry GenAI exporter for `observability.usage_record` (no consumer yet), and
per-tool-call spans (`evidence.record` is the analogue and is opt-in).
