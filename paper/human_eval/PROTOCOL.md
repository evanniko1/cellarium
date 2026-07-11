# Human evaluation protocol

**Task.** Open `packet.html` in a browser. For each pair (P01, P02, ...) two hypotheses (A, B) are shown for the same question. Decide which is **methodologically sounder** (falsifiability, operationalization onto measurable quantities, rival discrimination, feasibility). Judge the method, not the biology.

**Recording.** Fill one row per pair in a copy of `scoresheet_template.csv`: your choice (A / B / tie) and a 1--5 rigor rating for each. 2--3 independent graders, each scoring all pairs blind to the others.

**Blinding.** You are not told which hypothesis came from which system; A/B order is randomized per pair. The unblinding key (`key.csv`) is held separately and only used after scoring.

**Analysis (done for you).** We compute the rate at which graders prefer the full-Council hypothesis and compare it with the LLM auditor's ranking (inter-rater agreement), plus rigor-rating agreement.
