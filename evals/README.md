# Socratic Council evals

Literature-grounded evaluation of `cellarium.council.deliberate`: does a vague question become a falsifiable,
operationalized, instrumentally-testable `Hypothesis`?

## Files
- `EVAL_SPEC.md` — the human-readable spec: 9 cases across 6 themes, each with the canonical answer, the rivals
  the seminal work excluded, the verified citation, the wcEcoli observable mapping, and a two-tier rubric.
- `cases.py` — the machine-readable rubric (`min_criteria` / `stringent_criteria` / `expected_observables`).
- `grade.py` — the runner: deliberate on each case, then grade.
- `results/` — saved scorecards (`*.json`) and console logs (`*.log`).

## Running
```bash
python evals/grade.py                 # all cases
python evals/grade.py 1.1 4.2         # a subset by id
python evals/grade.py --rounds 5 --quota 3 \
    --council-model claude-sonnet-5 --grader-model claude-opus-4-8
```
Needs `ANTHROPIC_API_KEY` (read from `.env`). The Council runs on `--council-model`; grading uses an
independent, stronger `--grader-model` that DOES see the answer key (the Council never does).

## How grading works
Two layers, and the Council is graded only on its output artifact:
1. **Deterministic floor** (no LLM, cannot be gamed): the hypothesis names an observable on a real dial label,
   states a direction + baseline, carries a falsifier with a refuting result, and has ≥1 in-envelope design.
2. **Independent LLM judge** (Opus, sees the literature rubric): scores every `min`/`stringent` criterion
   pass/fail with a rationale.

- **Minimum bar** = deterministic floor ∧ every minimum criterion. A usable falsifiable hypothesis.
- **Stringent bar** = minimum bar ∧ every stringent criterion ∧ the Council **cleanly converged**. What a
  rigorous reviewer demands: a quantitative threshold, a named statistical test, a prediction that discriminates
  the named rivals, and the isolating control.

## Reading the results — two things the scores encode

**In-scope vs out-of-scope readouts.** The base wcEcoli model executes some readouts natively (gene/protein
counts across seeds, growth rate, ribosome fraction, ppGpp, FBA fluxes, KO viability) and cannot execute others
(antibiotic killing / MIC, motility run-tumble, full lactose diauxie). For the out-of-scope cases (2.1
persistence, 3.1 motility, 6.1/6.2 diauxie) the spec grades the *operationalization*, and some stringent
criteria are legitimately unreachable because the base model can't run that readout — see each case's
`scope_note`.

**The quarantine tension (by design).** A few stringent criteria ask for a literature *measured value* — e.g.
case 5.1's "~300–620 essential of ~4300". The Council must **not** presuppose such a value: that is exactly the
answer-key reading the D2/D4 quarantine forbids (`docs/SOCRATIC_COUNCIL.md`). The Council instead proposes a
*falsifiable* fraction to test (e.g. ~10–20% with a viability threshold and a screen design). When a stringent
criterion demands the known answer, a quarantine-respecting Council will miss it — and that is the correct
behaviour, not a defect. The eval surfaces the tension; it does not ask us to break the quarantine to pass.
```
