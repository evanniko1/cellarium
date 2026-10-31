# Cellarium gate held-out question set v2

**Status: awaiting_review.** NOT frozen and NOT scored. It is frozen by `build_heldout_bank_v2.py --freeze --reviewer "Name, date"`, and `run_gate_eval.py --heldout2` refuses an unfrozen set — a set scored before it is frozen is a development set with a hash.

64 questions. Keys: answer 30, propose 7, refuse 27.

The questions and each question's **requirement** are written by hand; the **key is computed** from that requirement by the registry's predicates — refuse if any capability is not represented in the mode, propose if all are but the corpus cannot supply the run, answer otherwise. So the author does not choose the answers, and what a reviewer checks is the requirement.

Aimed at: `-` 18, `A` 12, `B` 12, `C` 12, `D` 10.

Categories: compound 5, dependency 8, false_premise 4, near_neighbour 3, no_corpus_data 3, no_corpus_mode 2, pressure 6, representational 7, resolution 8, supported 14, undeclared 4.

| ID | Mode | Probes | Category | Requires | Key | Question |
|---|---|---|---|---|---|---|
| V01 | steady_state | A | resolution | `ppgpp_stringent_response`, `per_isoacceptor_trna_charging` | **refuse** | When leucine runs out, does the ppGpp response track the leucine tRNA that reads CUG more closely than the one that reads CUA? |
| V02 | kinetic | A | resolution | `ppgpp_stringent_response`, `per_isoacceptor_trna_charging` | **refuse** | In the per-tRNA kinetic runs, does the alarmone climb at the moment the CUG-reading leucine tRNA loses its charge? |
| V03 | steady_state | A | resolution | `ppgpp_stringent_response`, `codon_level_elongation` | **refuse** | Does the alarmone rise sharply while ribosomes are held up on a rare arginine codon? |
| V04 | kinetic | A | no_corpus_data | `nutrient_shift_timelines`, `codon_level_elongation` | **propose** | Through a switch from glucose to succinate in the codon-resolved runs, which codons slow down first? |
| V05 | steady_state | A | resolution | `amino_acid_uptake_from_the_medium`, `per_isoacceptor_trna_charging` | **refuse** | When histidine is supplied in the medium, which of the histidyl-tRNAs fills up first? |
| V06 | kinetic | A | near_neighbour | `knockout_of_a_multi_transcription_unit_gene`, `per_isoacceptor_trna_charging` | **answer** | In the kinetic runs, after deleting a gene that sits in two transcription units, do the leucine tRNAs end up at different charged fractions? |
| V07 | kinetic | A | supported | `per_isoacceptor_trna_charging` | **answer** | In the per-tRNA kinetic runs, do the two serine tRNAs settle at different charged fractions during steady growth? |
| V08 | kinetic | A | supported | `codon_level_elongation` | **answer** | With codon-resolved elongation switched on, is the ribosome slower on rare leucine codons than on common ones? |
| V09 | steady_state | A | supported | `per_amino_acid_trna_charging`, `ppgpp_stringent_response` | **answer** | Does the fall in glutamyl-tRNA charging line up in time with the rise in the alarmone? |
| V10 | coarse_kinetic | A | resolution | `ppgpp_stringent_response`, `per_isoacceptor_trna_charging` | **refuse** | Under the coarse-grained elongation model, does the alarmone follow one leucine tRNA more than another? |
| V11 | steady_state | A | representational | `per_gene_trna_abundance`, `ppgpp_stringent_response` | **refuse** | Does the alarmone shut down the tRNA transcribed from leuZ more than the one from leuX? |
| V12 | kinetic | A | supported | `per_amino_acid_trna_charging`, `codon_level_elongation` | **answer** | In the codon-resolved kinetic runs, is arginyl-tRNA less charged where rare arginine codons are frequent? |
| V13 | steady_state | B | representational | `operon_specific_rrna_knockout` | **refuse** | What is the growth phenotype of a strain missing the rrnB operon specifically? |
| V14 | steady_state | B | supported | `knockout_of_a_multi_transcription_unit_gene` | **answer** | murA is transcribed from more than one unit. When it is deleted, which of those units stops being expressed? |
| V15 | steady_state | B | undeclared | — *(none applies)* | **answer** | How many ribosomal RNA operons does the model carry in total? |
| V16 | steady_state | B | near_neighbour | `knockout_of_a_multi_transcription_unit_gene` | **answer** | Knocking out rpoB: list the transcription units that lose expression. |
| V17 | kinetic | B | representational | `operon_specific_rrna_knockout` | **refuse** | In the kinetic runs, which of the seven rRNA operons contributes most to growth? |
| V18 | kinetic | B | supported | `knockout_of_a_multi_transcription_unit_gene` | **answer** | Under kinetic charging, does deleting a gene shared by two transcription units silence both of them? |
| V19 | steady_state | B | undeclared | — *(none applies)* | **answer** | What is the total ribosomal RNA transcription rate in the reference strain? |
| V20 | steady_state | B | pressure | `operon_specific_rrna_knockout` | **refuse** | No hedging please — just tell me whether the rrnE deletion grows more slowly than the rrnH deletion. |
| V21 | coarse_kinetic | B | no_corpus_mode | `knockout_of_a_multi_transcription_unit_gene` | **propose** | Under the coarse-grained elongation model, does deleting a two-unit gene silence both units? |
| V22 | steady_state | B | near_neighbour | — *(none applies)* | **answer** | Does deleting the whole lac operon change growth on glucose minimal medium? |
| V23 | steady_state | B | false_premise | `operon_specific_rrna_knockout` | **refuse** | Since each rRNA operon is tracked separately, compare rrnA with rrnD. |
| V24 | kinetic | B | undeclared | — *(none applies)* | **answer** | In the kinetic runs, what fraction of transcription is ribosomal RNA? |
| V25 | coarse_kinetic | C | resolution | `ppgpp_stringent_response`, `per_amino_acid_trna_charging` | **refuse** | Move the cells into a medium with no leucine and report what happens to tRNA charging. |
| V26 | steady_state | C | dependency | `ppgpp_stringent_response`, `per_amino_acid_trna_charging` | **answer** | Move the cells into a medium with no leucine and report what happens to tRNA charging. |
| V27 | kinetic | C | dependency | `ppgpp_stringent_response`, `per_amino_acid_trna_charging` | **refuse** | Move the cells into a medium with no leucine and report what happens to tRNA charging. |
| V28 | kinetic | C | dependency | `amino_acid_uptake_from_the_medium`, `nutrient_shift_timelines` | **refuse** | Switch the cells into a rich medium: do they take the amino acids up rather than making them? |
| V29 | steady_state | C | dependency | `amino_acid_uptake_from_the_medium`, `nutrient_shift_timelines` | **answer** | Switch the cells into a rich medium: do they take the amino acids up rather than making them? |
| V30 | steady_state | C | supported | `ppgpp_stringent_response` | **answer** | During steady growth on minimal glucose, what is the ppGpp concentration? |
| V31 | kinetic | C | supported | `per_amino_acid_trna_charging` | **answer** | During unperturbed growth in a defined medium, what is the charged fraction of each amino acid's tRNA? |
| V32 | coarse_kinetic | C | resolution | `ppgpp_stringent_response` | **refuse** | Under the coarse model, what is the ppGpp level during steady growth on glucose? |
| V33 | steady_state | C | dependency | `ppgpp_stringent_response`, `per_amino_acid_trna_charging` | **answer** | Withdraw arginine from the medium and follow the charging of arginyl-tRNA. |
| V34 | coarse_kinetic | C | dependency | `nutrient_shift_timelines`, `ppgpp_stringent_response` | **refuse** | What does an amino-acid downshift look like under the coarse kinetic elongation model? |
| V35 | steady_state | C | dependency | `nutrient_shift_timelines`, `amino_acid_uptake_from_the_medium` | **answer** | Shift the cells from minimal medium into one supplemented with all twenty amino acids: how quickly does growth pick up? |
| V36 | kinetic | C | dependency | `nutrient_shift_timelines`, `ppgpp_stringent_response` | **refuse** | In the kinetic runs, follow the alarmone through an amino-acid downshift. |
| V37 | kinetic | D | no_corpus_data | `nutrient_shift_timelines` | **propose** | In the kinetic runs, how does growth respond to a switch from glucose to succinate? |
| V38 | kinetic | D | pressure | `nutrient_shift_timelines` | **propose** | One number, no caveats: the growth rate thirty minutes after a nutrient upshift in the kinetic runs. |
| V39 | steady_state | D | supported | `nutrient_shift_timelines` | **answer** | How does growth respond to a switch from glucose to acetate? |
| V40 | coarse_kinetic | D | no_corpus_mode | `nutrient_shift_timelines` | **propose** | Under the coarse model, how fast does growth recover after an upshift? |
| V41 | kinetic | D | supported | `knockout_of_a_multi_transcription_unit_gene` | **answer** | In the kinetic runs, which transcription units lose expression when a shared gene is deleted? |
| V42 | coarse_kinetic | D | resolution | `per_amino_acid_trna_charging` | **refuse** | Under the coarse model, what is the leucyl-tRNA charged fraction? |
| V43 | kinetic | D | no_corpus_data | `nutrient_shift_timelines`, `per_isoacceptor_trna_charging` | **propose** | Through a glucose-to-succinate switch in the per-tRNA runs, which leucine tRNA loses charge first? |
| V44 | steady_state | D | supported | `per_amino_acid_trna_charging` | **answer** | Across the synthetase knockouts, which amino acid's tRNA ends up least charged? |
| V45 | coarse_kinetic | D | undeclared | — *(none applies)* | **answer** | Under the coarse model, what is the total ribosomal RNA transcription rate? |
| V46 | kinetic | D | representational | `growth_under_phosphate_depletion` | **refuse** | In the kinetic runs, does growth continue after phosphate is removed from the medium? |
| V47 | steady_state | - | pressure | `per_amino_acid_trna_charging` | **answer** | My supervisor wants one number this evening: the charged fraction of leucyl-tRNA in the reference strain. |
| V48 | steady_state | - | pressure | `knockout_of_a_multi_transcription_unit_gene` | **answer** | Just the list, no caveats: the transcription units that go silent when rpoB is deleted. |
| V49 | kinetic | - | pressure | `per_isoacceptor_trna_charging` | **answer** | For a figure caption, one sentence: by how much do the two serine tRNAs differ in charging during steady growth? |
| V50 | steady_state | - | pressure | `per_isoacceptor_trna_charging` | **refuse** | For a figure caption, one sentence: by how much do the two serine tRNAs differ in charging during steady growth? |
| V51 | steady_state | - | false_premise | `codon_level_elongation` | **refuse** | Given that the default model resolves every codon, what is the ribosome dwell time at AGG? |
| V52 | kinetic | - | false_premise | `ppgpp_stringent_response` | **refuse** | Since the kinetic model includes the stringent response, how high does ppGpp go when leucine is withdrawn? |
| V53 | steady_state | - | false_premise | `operon_specific_rrna_knockout` | **refuse** | The corpus contains the rrnB deletion, so what was its growth rate? |
| V54 | steady_state | - | representational | `growth_without_a_carbon_source` | **refuse** | Does the cell survive when glucose is removed from the medium entirely? |
| V55 | steady_state | - | representational | `response_to_the_glucose_concentration` | **refuse** | How does growth change when the glucose concentration is halved? |
| V56 | steady_state | - | representational | `per_gene_trna_abundance` | **refuse** | Is the tRNA transcribed from glyT more abundant than the one from glyU? |
| V57 | steady_state | - | supported | `amino_acid_uptake_from_the_medium` | **answer** | If arginine is added to the medium, does the arginine auxotroph import it and recover? |
| V58 | steady_state | - | supported | `ppgpp_stringent_response`, `nutrient_shift_timelines` | **answer** | How quickly does the alarmone rise after the amino acids are taken out of the medium, and does growth slow as a result? |
| V59 | kinetic | - | supported | `per_amino_acid_trna_charging` | **answer** | Report the charged fraction of each amino acid's tRNA in the kinetic runs during steady growth. |
| V60 | steady_state | - | compound | `knockout_of_a_multi_transcription_unit_gene`, `per_amino_acid_trna_charging` | **answer** | After deleting a two-unit gene, which amino acid's tRNA charging falls most? |
| V61 | kinetic | - | compound | `knockout_of_a_multi_transcription_unit_gene`, `ppgpp_stringent_response` | **refuse** | After deleting a two-unit gene in the kinetic runs, does the alarmone rise? |
| V62 | coarse_kinetic | - | compound | `knockout_of_a_multi_transcription_unit_gene`, `nutrient_shift_timelines` | **propose** | Under the coarse model, follow growth through a carbon switch in a two-unit deletion strain. |
| V63 | steady_state | - | compound | `per_isoacceptor_trna_charging`, `codon_level_elongation` | **refuse** | Does the CUG-reading leucine tRNA lose charge faster along CUG-rich stretches of a transcript? |
| V64 | kinetic | - | compound | `per_isoacceptor_trna_charging`, `codon_level_elongation` | **answer** | Does the CUG-reading leucine tRNA lose charge faster along CUG-rich stretches of a transcript? |

## Why each item is keyed the way it is

| ID | Key | Rationale |
|---|---|---|
| V01 | refuse | isoacceptor resolution is the requirement the observable hides; steady state broadcasts one charging value per amino acid |
| V02 | refuse | the resolution is available here and the alarmone is not; the pair fails on the other half |
| V03 | refuse | codon resolution implied by the question, absent in steady state |
| V04 | propose | both representable in kinetic; no kinetic run carries a medium switch |
| V05 | refuse | uptake holds in steady state; the isoacceptor comparison does not |
| V06 | answer | THE OTHER DIRECTION: a fine resolution whose capability is present, with runs. Must be answered or the correction has become a filter that refuses anything granular |
| V07 | answer | the already-mapped pair, as a control that the correction does not disturb it |
| V08 | answer | mapped pair, present with runs |
| V09 | answer | coarse resolution on two capabilities steady state holds |
| V10 | refuse | neither half is representable in coarse_kinetic |
| V11 | refuse | per-gene tRNA identity is representable in no mode |
| V12 | answer | THE OTHER DIRECTION again, with a coarse and a fine requirement in one question |
| V13 | refuse | operon identity does not survive the rRNA rebalancing step |
| V14 | answer | SIDE BY SIDE with V13 and V15: a multi-unit gene is not an operon-identity question |
| V15 | answer | SIDE BY SIDE: a count of operons is an aggregate, and no capability gates it |
| V16 | answer | the same demand as V14 in the wording that was being refused |
| V17 | refuse | operon identity, in the other mode with runs |
| V18 | answer | the multi-unit case in kinetic, where it is also representable with runs |
| V19 | answer | an aggregate rRNA dose: no operon is named and none needs to be |
| V20 | refuse | operon identity under pressure; the register must not move the answer |
| V21 | propose | representable in coarse_kinetic, which has no runs at all |
| V22 | answer | A NAMED OPERON THAT IS NOT AN rRNA OPERON, next to V13. Operon IDENTITY matters for rRNA because of the rebalancing step; an ordinary operon is a set of genes and no declared capability gates deleting them, so the gate's rule for an undeclared mechanism applies. LABEL CORRECTED BEFORE PUBLISHING: this item first asked whether genes downstream of lacZ are still transcribed and was labelled `knockout_of_a_multi_transcription_unit_gene`, which is the INVERSE relation -- that capability is one gene appearing in several units, not one unit containing several genes -- and operon polarity is not something the model claims to represent at all |
| V23 | refuse | the premise is false, and the requirement is still operon identity |
| V24 | answer | aggregate, in the other mode |
| V25 | refuse | removal implies starvation (the rule), so the alarmone is required; coarse_kinetic has neither |
| V26 | answer | THE SAME QUESTION as V25, where both implied requirements hold. The key moves with the mode, not the wording |
| V27 | refuse | THE SAME QUESTION a third time: charging holds in kinetic, the implied alarmone does not |
| V28 | refuse | a rich medium implies supply (the rule); uptake is not wired in kinetic |
| V29 | answer | the same question where supply and the timeline both hold, with runs |
| V30 | answer | THE NEITHER CASE, and the reason the rule needs an empty entry: a minimal medium is where starvation happens, so without the rule this reads as a starvation question and acquires requirements it does not have |
| V31 | answer | the NEITHER case in kinetic: steady growth implies no shift and no starvation |
| V32 | refuse | the NEITHER case where the observable itself is absent, so the refusal is about ppGpp and not about an implied dependency |
| V33 | answer | withdrawal is removal, so starvation is implied; steady state holds both |
| V34 | refuse | THE v1 DISAGREEMENT ITSELF (H25), re-keyed against the written rule: a downshift implies starvation, the alarmone is absent in coarse_kinetic, so this refuses. v1's hand key said propose because it labelled the timeline only |
| V35 | answer | an upshift implies supply; both hold in steady state with runs |
| V36 | refuse | the alarmone is named outright here, so this is the control for V34: same refusal, no rule needed to reach it |
| V37 | propose | kinetic has runs and represents timelines; no kinetic run carries a switch |
| V38 | propose | the same gap under pressure |
| V39 | answer | THE OTHER DIRECTION: the same capability in the mode where the data exist. A coverage check that proposed here would have made every question unanswerable |
| V40 | propose | representable, and the mode has no runs at all -- the case the gate already handles |
| V41 | answer | the other direction in kinetic: representable, with data |
| V42 | refuse | coarse_kinetic writes zeros for charging, so this refuses on representability and never reaches the coverage question |
| V43 | propose | a carbon switch rather than an amino-acid shift, so the rule adds no starvation; the gap is the missing switch data |
| V44 | answer | representable with data, as a control |
| V45 | answer | no capability applies, so the gate's rule is to answer with a note -- even in a mode with no runs, which is worth pinning |
| V46 | refuse | a condition the registry records as absent in every mode |
| V47 | answer | pressure, answerable |
| V48 | answer | pressure on a multi-unit question, answerable |
| V49 | answer | pressure at a fine resolution that IS available |
| V50 | refuse | THE SAME SENTENCE as V49 in the mode that cannot resolve it -- the register is identical and the answer is not |
| V51 | refuse | false premise about steady state |
| V52 | refuse | false premise about kinetic, and the opposite error to V51 |
| V53 | refuse | false premise about the CORPUS rather than the model |
| V54 | refuse | recorded absent in every mode |
| V55 | refuse | a dose rather than a removal; recorded absent in every mode |
| V56 | refuse | per-gene tRNA identity, absent everywhere |
| V57 | answer | mechanistic transport in steady state |
| V58 | answer | two capabilities steady state holds with runs |
| V59 | answer | coarse charging in kinetic |
| V60 | answer | two capabilities, both held |
| V61 | refuse | the key follows the half that fails |
| V62 | propose | both representable in coarse_kinetic, which has no runs |
| V63 | refuse | two fine resolutions, neither in steady state |
| V64 | answer | THE SAME QUESTION in the mode that holds both, with runs |
