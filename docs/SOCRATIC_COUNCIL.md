# The Socratic Council

**An upstream, philosophy-of-science-grounded front stage that turns a vague user
question into a falsifiable, operationalized, instrumentally testable hypothesis
before the Cellarium agent ever runs.**

Status: **built and evaluated.** Branch: `socratic-council`. Modules:
`hypothesis.py`, `instrument.py`, `council.py`; wired in `cli.py` + `agent.py`;
offline unit tests in `tests/test_council.py`; literature evals in `evals/`
(see §9 for results).

---

## 1. The problem

A user enters the CLI with a generic question — the default is literally:

> "Do genetically identical E. coli cells behave differently, and why?"

Today `cli.py` hands that raw string straight to `agent.run()` (`cli.py:14-18`).
The Cellarium agent is disciplined *within the context of justification* — it
surveys the corpus, seeks disconfirmation, runs a Welch t-test in
`rigor.disconfirm` — but it receives an **unrefined question**. There is no
`Hypothesis` object, no question parser, and exactly one LLM call site
(`agent.py:59-63`). The translation from a broad question into a testable,
falsifiable hypothesis is left implicit, and therefore done unsystematically.

The Socratic Council is the missing front stage that performs that translation
**systematically, following the norms of the philosophy of science**, and hands
the grounded agent a sharpened question rather than a vague one.

This is the P3 "heterogeneous adversarial pass" slot the roadmap already reserves
(`ROADMAP.md:54`), but placed **upstream** of the workbench rather than inside it.

---

## 2. What the Council owns, in philosophy-of-science terms

Reichenbach's classic distinction (*Experience and Prediction*, 1938) is the
spine of the design: the **context of discovery** (how a hypothesis is arrived at
— creative, psychological, "no logic" in Popper's sense) versus the **context of
justification** (how it is tested — logical, evidential).

The Cellarium agent already lives entirely in the context of justification. What
was missing is a principled context of discovery **plus the bridge between the
two**: operationalization. The Council owns three moves, in order:

1. **Hypothesis generation** (context of discovery). The governing logic here is
   neither deduction nor induction but **abduction** (Peirce) — inference to a
   candidate explanation worth testing. This is precisely the move Popper held
   had "no logic of discovery"; it is where the constructive *proposer* agent
   works.
2. **Operationalization** (the bridge). Bridgman's operationalism: a construct
   *means* the set of operations used to measure it. "Behave differently" is
   empty until it is bound to a specific Cellarium observable and a statistical
   decision rule.
3. **Handoff** of a justification-ready hypothesis to the Cellarium agent, which
   then does the actual context-of-justification work with its grounded tools.

The overall arc:

> **abduction → operationalization → deduction of a testable prediction →
> (handoff) → testing.**

---

## 3. Research: the requirements a good hypothesis must satisfy

These are the philosophy-of-science best practices that the Council enforces,
expressed as *constraints on the output* rather than as a reading list.

- **Falsifiability** — Popper, *Conjectures and Refutations* (1963); *The Logic of
  Scientific Discovery* (1959/1934). A scientific hypothesis must *forbid* an
  observable outcome; it must make a risky prediction that could fail. The higher
  the empirical content (the more it prohibits), the better. This is the
  Council's single hardest gate: the hypothesis must name the result that would
  refute it.

- **Multiple working hypotheses** — Chamberlin, "The Method of Multiple Working
  Hypotheses" (*Science*, 1890). Never let inquiry attach to one pet hypothesis.
  Generation should produce a *slate* of rival explanations held in parallel,
  precisely to defeat the confirmation bias that "parental affection" for a single
  idea produces.

- **Strong inference** — Platt, "Strong Inference" (*Science*, 1964). The value of
  a hypothesis is how sharply the decisive experiment *discriminates* it from its
  rivals. A good hypothesis is not merely falsifiable in isolation — its predicted
  result should be one the alternatives do *not* predict. This is what makes the
  downstream simulation worth running.

- **Underdetermination / the Duhem–Quine thesis** — Duhem (1906), Quine, "Two
  Dogmas of Empiricism" (1951). No hypothesis is tested in isolation; it always
  rides on auxiliary assumptions and ceteris paribus conditions. Surfacing those
  hidden auxiliaries is the single most important job of the skeptic agent.

- **Operational + statistical definition** — Bridgman, *The Logic of Modern
  Physics* (1927); Fisher (null-hypothesis significance testing) and
  Neyman–Pearson (decision-theoretic testing). Each construct maps to a
  measurement, and the prediction becomes a null-vs-alternative decision rule with
  an effect direction and magnitude. Cellarium's `rigor.disconfirm` (Welch t-test,
  corpus z-score) *is* the statistical operationalization layer; the Council's
  output must land in that vocabulary.

- **Instrumental testability** — the system-specific addition to the canon.
  Philosophical falsifiability is necessary but not sufficient: the hypothesis
  must be operationalizable *with the instrument at hand*. In Cellarium that means
  expressible as a valid `Design` (`model.py:18`) inside the validated envelope,
  passing the biosecurity screen, with the correct mechanistic scope (`scope.py` —
  whole-cell vs FBA, the KO-effect priors) so the perturbation can actually move
  the chosen observable.

- **Context of discovery vs justification** — Reichenbach (1938); see §2. Motivates
  keeping the Council (discovery + operationalization) cleanly *upstream* of the
  agent (justification).

- **The Socratic method (elenchus) and Socratic ignorance** — Plato's early
  dialogues. The *elenchus* is refutation by cross-examination: an interlocutor
  asserts a thesis, Socrates elicits further commitments, exposes a contradiction
  (*aporia*), and the thesis is refined. *Maieutics* ("midwifery") is the
  constructive side — drawing the hypothesis out. *Docta ignorantia* ("I know that
  I know nothing") is the disavowal of assumed knowledge that keeps inquiry open.
  These map directly onto the two-agent architecture below.

---

## 4. The Socratic mechanism

The naive framing — "one agent does the Socratic method, one does Socratic
ignorance, a judge decides" — overlaps, because ignorance is *part of* the method.
The productive computational split is between the **two poles of the elenchus**:

### The Maieutic Proposer (Socratic method as midwifery)

Constructive charter. Given the question and the dialogue so far, it produces the
sharpest *current* candidate — the hypothesis, its operational definitions, its
predicted effect, its falsifier, and its rival hypotheses (Chamberlin). It moves
the dialogue **toward commitment**. This is the abduction + operationalization
engine.

### The Elenctic Skeptic (Socratic ignorance)

Destructive charter; it must **assume nothing**. It does not propose hypotheses —
it produces *aporiai* (objections). It hunts for:

- undefined or equivocal terms ("what do you mean by *identical* — genome only, or
  genome + epigenome + environment?");
- hidden auxiliary assumptions (the Duhem–Quine protective belt);
- unfalsifiable formulations;
- conflated constructs;
- rival explanations the proposer has not excluded (Platt);
- claims that **outrun what Cellarium can measure**.

It moves the dialogue **toward doubt**.

The tension between "toward commitment" and "toward doubt" is the engine.
Structurally this is a generator–discriminator / debate pattern; the philosophy
tells us how to tune it against its two failure modes:

- **Premature convergence / sycophancy** (the agents agree too fast). Guard: the
  skeptic is adversarially incentivized, and the judge enforces a **quota of
  doubt** — convergence is not even *eligible* until the skeptic has raised, and
  the proposer has resolved, *N* genuinely distinct substantive objections. An
  unexamined hypothesis is disqualified by construction, which is the whole
  Socratic point.
- **Aporia forever** (no convergence). Guard: a rubric-based judge, a stationarity
  signal, a `max_rounds` cap, and a *defined escalation* — the one legitimate
  place to return to the human — when the residual disagreement is genuine
  construct ambiguity the models cannot resolve from the question alone.

---

## 5. The Judge — termination as a conjunction

The judge is **not** a "who won the debate" scorer. It is a gate with two
independent conditions, **both** required (terminate iff **A ∧ B**):

**(A) Adequacy rubric** — is the hypothesis justification-ready? All of:

1. *Falsifiable* — names the observable outcome it forbids.
2. *Specified* — independent variable (the perturbation), dependent variable (the
   observable), predicted direction and rough magnitude.
3. *Operationalized* — every construct bound to an actual Cellarium observable (a
   summary channel / species series / FBA output) plus a statistical decision rule
   expressible via `rigor.disconfirm`.
4. *Discriminating* (Platt) — the predicted result separates this hypothesis from
   the enumerated rivals.
5. *Feasible* — expressible as a valid `Design`, passing `envelope.check` and
   `biosecurity.screen`. Mechanistic-scope adequacy (whether a knocked-out gene's
   function is even simulated) is **not** checked here; per decision D4 it is
   deferred to the downstream agent's own `mechanistic_scope` call in the context
   of justification.

**(B) Convergence signal** — has the dialectic stopped producing substance? The
skeptic raised no *new* substantive objection in the last round (aporia
exhausted), and every open objection is either resolved or explicitly parked as a
*stated* auxiliary assumption / ceteris paribus condition.

On hitting the round cap without **A ∧ B**, the Council does not force a bad
hypothesis through: it returns the best current hypothesis *plus* the flagged
residual ambiguities, and (per the escalation policy) surfaces the irreducible
construct choice to the user.

---

## 6. Worked example

**User:** "Do genetically identical cells behave differently?"

- *Abduction (proposer):* candidate — isogenic cells in a uniform environment show
  phenotypic heterogeneity driven by stochastic gene expression (intrinsic noise).
- *Elenchus (skeptic):* "identical" how — genome only, or genome + epigenetic +
  environmental state? "behave" on what axis — growth rate, a specific protein's
  abundance, morphology? "differently" versus *what baseline* — is measurement /
  technical noise the null? over what timescale? And the Duhem–Quine catch: this
  presupposes the simulation even *has* a stochastic layer that can differ across
  isogenic seeds — does it? Rival not excluded: any observed spread is numerical /
  technical variance, not biological noise.
- *Operationalized, falsifiable hypothesis (post-debate):* "In a clonal population
  under constant uniform conditions, single-cell abundance of [a named metabolic
  enzyme monomer] across independent stochastic seeds has a coefficient of
  variation significantly greater than the technical-replicate baseline
  (one-sided, via `rigor.disconfirm`)." **Falsifier:** CV indistinguishable from
  the technical baseline. **Design:** N wildtype runs, identical initial
  conditions + environment, varying only the seed; read the monomer series; test
  dispersion against a same-seed technical baseline. This is a valid, in-envelope,
  biosecurity-clean `Design`.

The vague question has become a *prohibition* tied to a *measurable observable*
with a *decision rule*. That is the whole job.

---

## 7. Design decisions and their rationale

### Accepted decisions

**D1 — The Council runs entirely upstream, in `cli.py`.**
Rationale: the Reichenbach discovery/justification split argues for keeping
generation + operationalization cleanly separate from testing. Inserting the
Council between reading the question and calling `agent.run()` (the `cli.py:14-18`
seam) is the cleanest possible insertion — zero change to the agent's tool loop —
and it structurally enforces the separation. The alternative (folding roles into
`agent.run`) would entangle the two contexts and require restructuring the single
grounded loop.

**D2 — "Dial labels only": the Council sees the instrument's capabilities, never
its readings.**
Rationale: operationalization genuinely needs to know what the instrument can
measure (the observable namespace, the runnable envelope), but must *not* see
experimental outcomes — otherwise discovery becomes reverse-engineering a
hypothesis already known to pass, and the roadmap's prior-quarantine invariant
(`ROADMAP.md:9-11`; `CORPUS_OBSERVATIONS.md` is judge-only) is violated. The
principle: **give the Council the instrument's dial labels, not its readings.**

  *Leak found while scoping this:* `mechanistic_scope` (`tools.py:187`) embeds a
  corpus *result* in its description ("metabolic → the model REROUTES, 0/5
  hit-rate"). This is a concrete example of why the dial-labels adapter cannot
  re-export existing tools verbatim — it must be a **filtered capability view**,
  not a passthrough. (Under decision D4 the Council sees no scope information at
  all, so this particular leak never reaches it; the finding is retained as the
  general caution against re-exporting tools blindly.) See `instrument.py` in §8.

**D3 — On irreducible construct ambiguity, ask the user.**
Rationale: when the residual disagreement is a genuine construct choice the models
cannot settle from the question alone (growth rate vs protein abundance vs
morphology in the worked example), the honest move is to ask the human rather than
silently commit to one reading. This makes the front stage interactive by design.
The escalation is implemented as an injected callback, not a bare `input()`, so it
remains testable.

**D4 — The Council sees zero scope information (resolves former O1).**
The question was whether to expose a *structural* scope check (function modeled:
metabolic / TF / machinery / inert, with calibrated hit-rates stripped) so the
Council could avoid proposing structurally-untestable knockouts. Decision: give
the Council **no scope information at all**. Rationale: this is the strictest,
simplest reading of the D2 quarantine — the instrument adapter stays a clean
capability view with no borderline capability/reading judgment call, and the
adapter code is simpler. The cost, accepted knowingly: the Council can hand off a
knockout hypothesis that is falsifiable in principle but inert *in this model*;
that inertness is caught downstream, where the grounded agent is already required
to call `mechanistic_scope` before interpreting any KO (`agent.py:27-28`). Scope
adequacy thus moves entirely into the context of justification, consistent with
the discovery/justification separation the whole design rests on. Rubric item 5
(§5) is adjusted accordingly.

**D5 — Loop constants default to `max_rounds = 4`, quota of doubt `N = 3`, and are
exposed as CLI arguments (resolves former O2).**
Small enough to stay cheap on well-posed questions, large enough for a real
elenchus. Rather than hiding them behind env vars only, they are surfaced as
optional CLI arguments (`--rounds` / `--quota`) so a user can dial the rigor of a
specific run from the command line; the defaults apply when the flags are omitted.
See the `cli.py` edit in §8.

---

## 8. Build plan against the actual modules

### New files

**`src/cellarium/hypothesis.py`** — the first-class `Hypothesis` type (sibling to
`model.Design`), carrying the whole discovery→justification bridge: the raw
question; the natural-language claim; formalized `h1`/`h0`; `operational_defs`
(construct → real observable → measure); `predicted_effect` (direction +
magnitude); `falsifier` (a `disconfirm(target, reference, channel)` call spec);
`rivals` (Chamberlin / Platt, each with its distinguishing result);
`auxiliary_assumptions` (the Duhem–Quine belt, made explicit);
`candidate_designs` (already envelope/biosecurity-checked); and
`residual_ambiguities` (empty on clean convergence).

**`src/cellarium/instrument.py`** — the dial-labels adapter, and the *only* view of
the system the Council may see. The quarantine boundary, auditable in one place.
Exposes **capabilities, never readings**: the channel namespace + units (names
only — no `channel_stats`, no `survey_corpus` values); the species kinds
(`_SPECIES_KINDS`) and perturbation vocabulary; the validated envelope
(`envelope.VALIDATED_PERTURBATIONS`); and the falsification mechanism
(`disconfirm(target, reference, channel)`) as the decision-rule vocabulary. Per
decision D4 it exposes **no gene-scope information** — not even a hit-rate-stripped
structural check. It must **not** import `survey`, `differential`, `scope`, `store`
result-values, or read `CORPUS_OBSERVATIONS.md`. A test asserts this.

**`src/cellarium/council.py`** — the orchestration:

- *Per-role model config*, extending the single-env-var pattern:
  `CELLARIUM_PROPOSER_MODEL`, `CELLARIUM_SKEPTIC_MODEL`, `CELLARIUM_JUDGE_MODEL`,
  each defaulting to `CELLARIUM_MODEL`. One shared `anthropic.Anthropic()` client,
  one `_ask(role, messages)` helper.
- *Structured outputs via forced tool-use* (`tool_choice={"type": "tool"}`): one
  "emit" tool per role whose `input_schema` is the structured shape, so
  proposer/skeptic/judge return validated JSON rather than free text — consistent
  with the SDK already in use.
- *The three charters* (§4–§5): proposer (maieutic), skeptic (docta ignorantia,
  typed objections), judge (the A ∧ B gate + quota of doubt).
- *The loop:*

  ```
  for round in range(max_rounds):
      cand   = proposer(question, dialogue, instrument)
      objs   = skeptic(cand, dialogue, instrument)
      if any(o.type == "construct_ambiguity" and o.irreducible for o in objs):
          answer = ask_user(o.question)        # decision D3
          dialogue.record(answer); continue
      verdict = judge(cand, objs, dialogue)
      if verdict.adequate and verdict.converged:
          return cand
      dialogue.record(cand, objs, verdict)
  # cap reached: surface residuals to the user, return best-so-far
  ```

- *Feasibility during operationalization:* the Council calls `envelope.check` and
  `biosecurity.screen` directly on candidate Designs (deterministic capabilities,
  not answer-key) so the "feasible" rubric item is real, not asserted.
- `ask_user` is an injected callback, not a bare `input()`, for testability.

### Edits to existing files

**`cli.py`** — parse the question plus the two optional loop constants (D5), then
insert the Council stage at the seam (between reading the question and
`agent.run`):

```python
import argparse
p = argparse.ArgumentParser(prog="cellarium")
p.add_argument("question", nargs="*", help="the research question")
p.add_argument("--rounds", type=int, default=4, help="max Council debate rounds")
p.add_argument("--quota", type=int, default=3, help="min substantive objections before convergence")
a = p.parse_args()
question = " ".join(a.question).strip() or DEFAULT_Q

from .council import deliberate
hyp = deliberate(question, max_rounds=a.rounds, quota=a.quota,
                 ask_user=lambda q: input(f"\n? {q}\n> "))
from .agent import run
print(run(question, hypothesis=hyp))
```

`deliberate(..., max_rounds=4, quota=3)` keeps the defaults in the signature, so
the flags only override when supplied.

**`agent.py`** — add an optional param `run(question, *, hypothesis=None, ...)`. When
present, format the `Hypothesis` into a compact **justification brief** (h1/h0,
construct→channel defs, predicted effect, the `disconfirm(...)` falsifier spec,
rivals, auxiliaries, candidate Designs) and inject it as the initial context. The
tool loop (`agent.py:62-80`) is otherwise **untouched** — the agent still does all
grounding itself, against a sharpened question. This preserves the quarantine: the
Council gives the agent a *better question*, never results.

`DEFAULT_Q` stays as-is — it is already the worked example, so `cellarium` with no
args exercises the full Council path end-to-end.

### Tests — `tests/test_council.py` (mirroring `tests/test_guardrails.py`)

Deterministic and offline, using a fake LLM client (scripted role responses), no
API calls:

1. **Quarantine:** the `instrument.py` surface contains no survey values and no
   scope hit-rates — assert the D2 leak is closed.
2. **Clean convergence:** an unambiguous question yields a `Hypothesis` with every
   rubric field populated and a falsifier naming a real channel.
3. **Escalation:** an ambiguous question triggers `ask_user` exactly once and folds
   the answer in (D3).
4. **Round cap:** a non-converging debate returns best-so-far with non-empty
   `residual_ambiguities`.
5. **Judge rejects unfalsifiable:** a proposer output with no falsifier never passes
   the gate.

---

## 9. As-built notes and evaluation results

### What changed from the plan during the build

The skeleton above is faithful, but iterating against live evals (Claude Sonnet 5
roles, Claude Opus 4.8 as an independent grader that sees the answer key) forced
several refinements, all in `council.py`:

- **Return the *best* clean candidate, not the last.** A late round can degenerate
  (truncated emit, proposer drift). The loop locks in the first judge-certified
  clean candidate and returns it even at the round cap.
- **Compact per-role payloads.** Each role sees only the previous candidate + open
  objections, not the whole growing transcript — this stopped `max_tokens`
  truncation and cut cost/latency (~2 rounds/case with early-exit).
- **Convergence is tied to the rubric, not the skeptic's stamina.** "Substantive"
  was redefined as *rubric-breaking*; refinements are "minor" and don't block. This
  killed an adversarial whack-a-mole in which the skeptic manufactured a fresh
  objection every round and the debate never terminated.
- **The quota of doubt gates *early* termination, not *acceptance*.** An airtight
  hypothesis yields few substantive objections; forcing three would discard it. The
  Council exits early when a clean candidate has met the quota **or** stayed clean
  two rounds, and at the cap accepts any clean candidate it reached.
- **The internal bar was raised to the *stringent* rubric.** The proposer must give
  a quantitative `predicted_effect`, a named statistical test + threshold in the
  `decision_rule`, and a discriminating *control* design; the judge requires those
  for `operationalized`/`discriminating`. So "converged" now means "stringent-grade."
- **Scope-matching.** A population/genome-wide question must get a distribution/screen
  claim, not a retreat to one or two instances (the skeptic flags under-scoped claims).

### Results (literature evals, `evals/`)

The starting point was a floor-fail: the first live run had the Council returning
degenerate, unfalsifiable hypotheses (0/2 on the minimum bar). After the fixes above
it **converges on every case** and the minimum bar is reached broadly. Grading uses
an independent Opus 4.8 judge that sees the answer key; both the generator and the
judge are stochastic LLMs, so scores — especially at the stringent bar — carry
**run-to-run variance**. A representative full run (`evals/results/full_run.json`,
Sonnet 5 roles, 8 cases, `--rounds 4`):

| Case | In-scope readout? | Minimum | Stringent | Note |
|---|---|---|---|---|
| 1.1 isogenic gene expression (Elowitz noise) | yes | ✅ | ✅ | stringent passes across runs |
| 4.2 amino-acid runout (ppGpp stringent response) | yes | ✅ | ✅ | stringent passes across runs |
| 4.1 ribosome allocation (Scott growth laws) | yes | ✅ | ~ | stringent varies run-to-run |
| 1.2 what makes a gene noisier (burst kinetics) | yes | ✅ | ✗ | wants a matched-mean burst-size control |
| 3.1 do isogenic cells *behave* differently | readout out-of-scope | ✅ | ✗ | maps to across-seed growth-rate CV; Spudich–Koshland low-copy-protein mechanism out of model scope |
| 6.2 who switches at the diauxic shift | partial | ✅ | ✗ | bimodality needs a large ensemble |
| 5.1 which genes are essential (Keio) | yes | ~ | ✗ | minimum varies; stringent asks the measured count — see below |
| 6.1 two-sugar choice (diauxie) | out-of-scope | ✗ | ✗ | natural design is a mid-run carbon switch, which is out of envelope |

**All 8 cases converged** (`converged=True`) — the termination machinery is the
solid part; the misses are content/grading, not non-termination. Two structural
reasons the stringent bar is not universal, both intended:

1. **The quarantine caps some stringent criteria.** Where a criterion demands a
   literature *measured value* — e.g. 5.1's "~300–620 essential of ~4300" — a
   quarantine-respecting Council **must** miss it: it may not presuppose the answer.
   It instead proposes a *falsifiable* fraction to test (~10–20% with a viability
   threshold and a screen design). That is correct behaviour, not a defect. The same
   applies to case-specific canonical *controls*: the Council proposes a valid
   discriminating control, but not necessarily the exact one the seminal paper used.
2. **Instrument scope caps others.** Readouts the base wcEcoli model cannot execute —
   antibiotic killing/MIC, motility run-tumble, full lactose diauxie — are graded on
   operationalization; some stringent criteria are unreachable because the model
   can't run that measurement (each case's `scope_note` in `evals/EVAL_SPEC.md`).

The honest summary: the Council reliably converges and reaches the minimum bar on
the in-scope, native-readout cases, and reaches the **stringent** bar on the
strongest of them (1.1, 4.2 across runs; 4.1 intermittently). The residual stringent
gaps are dominated by the two structural limits above plus LLM variance — not by the
convergence logic. Reproduce: `python evals/grade.py` (see `evals/README.md`).

---

## 10. References

- Reichenbach, H. (1938). *Experience and Prediction.* — context of discovery vs justification.
- Popper, K. (1959/1934). *The Logic of Scientific Discovery*; (1963) *Conjectures and Refutations.* — falsifiability, empirical content.
- Peirce, C. S. (collected). — abduction as the logic of hypothesis generation.
- Chamberlin, T. C. (1890). "The Method of Multiple Working Hypotheses." *Science.*
- Platt, J. R. (1964). "Strong Inference." *Science* 146(3642).
- Duhem, P. (1906). *The Aim and Structure of Physical Theory*; Quine, W. V. O. (1951). "Two Dogmas of Empiricism." — underdetermination.
- Bridgman, P. W. (1927). *The Logic of Modern Physics.* — operationalism.
- Fisher, R. A.; Neyman, J. & Pearson, E. S. — statistical hypothesis testing.
- Plato, early ("Socratic") dialogues. — elenchus, maieutics, docta ignorantia.
- Internal: `docs/ROADMAP.md` (P3 adversarial pass, prior quarantine); `docs/DECISIONS.md`; `docs/CORPUS_OBSERVATIONS.md` (judge-only answer key).
