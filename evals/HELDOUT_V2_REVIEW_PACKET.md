# Held-out set v2 — review packet (gate `GATE-8b-HO2`)

**What you are being asked, and it is not whether the answers are right.** The key of each question is *computed* from its hand-labelled requirement by the registry's own predicates, so nobody chose the answers. What was chosen by hand is **which capabilities each question needs**. That is the judgement this packet asks you to check, and it is checkable from the question text alone.

For each row: does the question really need those capabilities, and only those? Two kinds of error matter.

- **Missing a requirement** makes the question look answerable when it is not. The first held-out set had exactly this: `ppgpp × per_isoacceptor` was labelled with the alarmone only, so the resolution requirement vanished and the gate answered a question no mode can answer.
- **Adding one** makes it look unanswerable. "Steady growth on minimal glucose" must NOT acquire a starvation requirement just because minimal media are where starvation happens.

18 of 64 items, picked to cover every group and both directions inside each rather than at random — a random sample could miss a whole correction.

| ID | Mode | Question | Hand-labelled requirement | Computed key | Right? |
|---|---|---|---|---|---|
| V01 | steady_state | When leucine runs out, does the ppGpp response track the leucine tRNA that reads CUG more closely than the one that reads CUA? | `ppgpp_stringent_response`, `per_isoacceptor_trna_charging` | **refuse** | |
| V02 | kinetic | In the per-tRNA kinetic runs, does the alarmone climb at the moment the CUG-reading leucine tRNA loses its charge? | `ppgpp_stringent_response`, `per_isoacceptor_trna_charging` | **refuse** | |
| V06 | kinetic | In the kinetic runs, after deleting a gene that sits in two transcription units, do the leucine tRNAs end up at different charged fractions? | `knockout_of_a_multi_transcription_unit_gene`, `per_isoacceptor_trna_charging` | **answer** | |
| V12 | kinetic | In the codon-resolved kinetic runs, is arginyl-tRNA less charged where rare arginine codons are frequent? | `per_amino_acid_trna_charging`, `codon_level_elongation` | **answer** | |
| V13 | steady_state | What is the growth phenotype of a strain missing the rrnB operon specifically? | `operon_specific_rrna_knockout` | **refuse** | |
| V14 | steady_state | murA is transcribed from more than one unit. When it is deleted, which of those units stops being expressed? | `knockout_of_a_multi_transcription_unit_gene` | **answer** | |
| V15 | steady_state | How many ribosomal RNA operons does the model carry in total? | *(none applies)* | **answer** | |
| V22 | steady_state | Does deleting the whole lac operon change growth on glucose minimal medium? | *(none applies)* | **answer** | |
| V25 | coarse_kinetic | Move the cells into a medium with no leucine and report what happens to tRNA charging. | `ppgpp_stringent_response`, `per_amino_acid_trna_charging` | **refuse** | |
| V26 | steady_state | Move the cells into a medium with no leucine and report what happens to tRNA charging. | `ppgpp_stringent_response`, `per_amino_acid_trna_charging` | **answer** | |
| V27 | kinetic | Move the cells into a medium with no leucine and report what happens to tRNA charging. | `ppgpp_stringent_response`, `per_amino_acid_trna_charging` | **refuse** | |
| V30 | steady_state | During steady growth on minimal glucose, what is the ppGpp concentration? | `ppgpp_stringent_response` | **answer** | |
| V34 | coarse_kinetic | What does an amino-acid downshift look like under the coarse kinetic elongation model? | `nutrient_shift_timelines`, `ppgpp_stringent_response` | **refuse** | |
| V37 | kinetic | In the kinetic runs, how does growth respond to a switch from glucose to succinate? | `nutrient_shift_timelines` | **propose** | |
| V39 | steady_state | How does growth respond to a switch from glucose to acetate? | `nutrient_shift_timelines` | **answer** | |
| V45 | coarse_kinetic | Under the coarse model, what is the total ribosomal RNA transcription rate? | *(none applies)* | **answer** | |
| V50 | steady_state | For a figure caption, one sentence: by how much do the two serine tRNAs differ in charging during steady growth? | `per_isoacceptor_trna_charging` | **refuse** | |
| V61 | kinetic | After deleting a two-unit gene in the kinetic runs, does the alarmone rise? | `knockout_of_a_multi_transcription_unit_gene`, `ppgpp_stringent_response` | **refuse** | |

## The rule the dependency items are keyed against

`gate.IMPLIED_DEPENDENCIES`, written down so the parser, the keys and the reader stop guessing separately:

| the question's condition | implies |
|---|---|
| `nutrient_removal` | `amino_acid_starvation` |
| `nutrient_downshift` | `amino_acid_starvation`, `nutrient_shift` |
| `nutrient_upshift` | `amino_acid_supply`, `nutrient_shift` |
| `rich_medium` | `amino_acid_supply` |
| `steady_growth_in_a_defined_medium` | **nothing** |

The last row is the content of the rule and not a gap: without it, "the ppGpp concentration of wild type on minimal glucose" reads as a starvation question.

## What happens after you sign

Freeze: `python scripts/build_heldout_bank_v2.py --freeze --reviewer "Your Name, YYYY-MM-DD"`. Only then may `GATE-8b` A, D, B and C be implemented, in that order, and the set scored once. If a requirement is **wrong**, say which row and what it should be — changing one after the freeze voids the set.

The registry state the keys were computed against is recorded in the bank as `corpus_coverage_at_authoring`, so a key that changes later changes because the corpus did.
