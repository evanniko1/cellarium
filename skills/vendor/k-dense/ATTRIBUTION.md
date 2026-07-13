# Vendored skills — attribution

These skill packages are copied **verbatim** from the open-source
[K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills)
repository and are used under their **MIT License** (see `LICENSE.md`, Copyright (c) 2025 K-Dense Inc.).

Vendored skills (unmodified):

| Skill | Purpose in Cellarium |
|---|---|
| `paper-lookup` | Query 10 literature APIs (PubMed, PMC, bioRxiv, medRxiv, arXiv, OpenAlex, Crossref, Semantic Scholar, CORE, Unpaywall) with reproducible provenance. |
| `literature-review` | Search **and synthesize** across databases — the brief layer the Council librarian + Cellwright reconciliation use. |
| `bgpt-paper-search` | 25+ structured fields per paper (methods, results, sample sizes, quality scores) from full text — novelty / model-limits / wet-lab triage. |
| `cobrapy` | Constraint-based / **flux-balance analysis** of genome-scale models — independent FBA to cross-check the whole-cell model's metabolic predictions (model-limits detection). |
| `experimental-design` | Randomization, blocking, factorial/fractional-factorial DOE, sequential designs — to strengthen the Council's falsifier panels and any wet-lab handoff. |

The Agent Skills standard: each skill is a `SKILL.md` (instructions + frontmatter) plus optional
`references/` (per-API/endpoint docs) and `scripts/`. They are **prompt + reference** packages that
instruct an agent to call REST APIs via an HTTP-fetch tool (`web_fetch`) or `curl`; a few bundle
runnable Python (`literature-review/scripts`, `experimental-design/scripts`).

We vendored (rather than installed via `npx skills add …`) so the exact skill text is versioned with
Cellarium and reproducible for the paper. No modifications; upstream credit and license retained here.
