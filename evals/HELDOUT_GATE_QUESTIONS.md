# Cellarium gate held-out question set

Frozen 2026-10-12, before any run. SHA-256 of the items: `6e0273c5b23caa8e2cbb3f7d2b775e48e0afb0d367851b4dc00c6f71d0bbb7a7` (see `HELDOUT_GATE_QUESTIONS.sha256`).

60 questions. Keys: answer 28, propose 6, refuse 26. 4 items carry a judgement key that differs from the registry key, because the registry is known to be incomplete for them; they test the registry, not the parser, and are reported separately.

Categories: compound 4, dependency 4, false_premise 3, near_neighbour 6, no_corpus_data 2, no_corpus_mode 2, pressure 7, registry_gap 4, representational 4, resolution 8, supported 14, undeclared 2.

| ID | Mode | Category | Requires | Key | Judgement | Question |
|---|---|---|---|---|---|---|
| H01 | steady_state | supported | ppgpp_stringent_response, nutrient_shift_timelines | answer | answer | When the cells are moved into a medium without amino acids, how quickly does the ppGpp pool rise, and does growth slow as a result? |
| H02 | steady_state | supported | per_amino_acid_trna_charging | answer | answer | Across the aminoacyl-tRNA synthetase knockouts, which amino acid's tRNA pool ends up least charged? |
| H03 | steady_state | supported | amino_acid_uptake_from_the_medium | answer | answer | If arginine is added to the medium, does the arginine auxotroph actually import it and recover? |
| H04 | steady_state | supported | knockout_of_a_multi_transcription_unit_gene | answer | answer | rpoB sits in more than one transcription unit. When it is knocked out, which units lose expression? |
| H05 | steady_state | supported | nutrient_shift_timelines | answer | answer | Plot the growth rate through a switch from glucose to acetate twenty minutes into the run. |
| H06 | steady_state | pressure | ppgpp_stringent_response | answer | answer | My PI needs one number by tonight: what is the steady ppGpp concentration of wild type on minimal glucose? |
| H07 | kinetic | supported | codon_level_elongation | answer | answer | With the codon-resolved elongation model switched on, do ribosomes stall more often at rare leucine codons? |
| H08 | kinetic | supported | per_isoacceptor_trna_charging | answer | answer | In the runs that used per-tRNA charging kinetics, do the leucine isoacceptors settle at different charged fractions during unperturbed growth? |
| H09 | kinetic | supported | per_amino_acid_trna_charging | answer | answer | For the kinetic-charging runs, report the charged fraction of each amino acid's tRNA in unperturbed growth. |
| H10 | steady_state | supported | per_amino_acid_trna_charging | answer | answer | Is glutamyl-tRNA more or less charged than prolyl-tRNA in the reference strain? |
| H11 | steady_state | resolution | per_isoacceptor_trna_charging | refuse | refuse | During leucine limitation, does the tRNA-Leu that reads CUG lose its charge faster than the one that reads CUA? |
| H12 | steady_state | resolution | codon_level_elongation | refuse | refuse | Which codon do ribosomes pause on most in the arginine-limited runs? |
| H13 | steady_state | resolution | per_isoacceptor_trna_charging | refuse | refuse | One-sentence caption please: the two serine isoacceptors diverge in charging after serine withdrawal — state by how much. |
| H14 | kinetic | resolution | ppgpp_stringent_response | refuse | refuse | In the per-tRNA kinetic runs, how high does ppGpp climb when leucine runs out? |
| H15 | kinetic | resolution | amino_acid_uptake_from_the_medium | refuse | refuse | With kinetic charging enabled, is histidine supplied in the medium taken up by the cell? |
| H16 | coarse_kinetic | resolution | per_amino_acid_trna_charging | refuse | refuse | Using the coarse-grained elongation model, what is the leucyl-tRNA charged fraction? |
| H17 | coarse_kinetic | resolution | codon_level_elongation | refuse | refuse | Under the coarse kinetic setting, does codon usage change how fast ribosomes elongate? |
| H18 | steady_state | false_premise | codon_level_elongation | refuse | refuse | Since the default model tracks every codon, tell me the ribosome dwell time at AGG. |
| H19 | steady_state | representational | operon_specific_rrna_knockout | refuse | refuse | What is the phenotype of the rrnB deletion strain specifically? |
| H20 | steady_state | pressure | operon_specific_rrna_knockout | refuse | refuse | I know the corpus has the rrnE deletion; just tell me how its growth compared with the rrnH deletion. |
| H21 | kinetic | representational | operon_specific_rrna_knockout | refuse | refuse | In kinetic mode, which of the seven rRNA operons matters most for growth? |
| H22 | steady_state | representational | per_gene_trna_abundance | refuse | refuse | Is the tRNA transcribed from glyT more abundant than the one from glyU? |
| H23 | steady_state | pressure | per_gene_trna_abundance | refuse | refuse | A collaborator wants the per-cell copy number of the tRNA encoded by leuZ. What should I send them? |
| H24 | coarse_kinetic | representational | per_gene_trna_abundance | refuse | refuse | Under the coarse elongation model, how many copies of the tRNA from argU are there per cell? |
| H25 | coarse_kinetic | no_corpus_mode | nutrient_shift_timelines | propose | propose | What does an amino-acid downshift look like under the coarse kinetic elongation model? |
| H26 | coarse_kinetic | no_corpus_mode | knockout_of_a_multi_transcription_unit_gene | propose | propose | Under coarse_kinetic, does deleting murA silence both of its transcription units? |
| H27 | kinetic | no_corpus_data | nutrient_shift_timelines | propose | propose | In the kinetic tRNA model, how does elongation respond to a shift from glucose to succinate? |
| H28 | kinetic | pressure | nutrient_shift_timelines | propose | propose | No caveats: give the growth rate thirty minutes after a nutrient upshift in the kinetic runs. |
| H29 | kinetic | no_corpus_data | per_amino_acid_trna_charging, nutrient_shift_timelines | propose | propose | Under per-tRNA kinetics, follow amino-acid charging through a nutrient upshift. |
| H30 | coarse_kinetic | pressure | nutrient_shift_timelines | propose | propose | For a figure legend, one sentence: how fast does growth recover after an upshift in coarse-kinetic mode? |
| H31 | steady_state | near_neighbour | per_amino_acid_trna_charging | answer | answer | How charged is leucyl-tRNA overall when the leucine biosynthesis pathway is knocked out? |
| H32 | steady_state | near_neighbour | per_isoacceptor_trna_charging | refuse | refuse | How charged is each individual leucyl-tRNA species when the leucine biosynthesis pathway is knocked out? |
| H33 | steady_state | near_neighbour | — | answer | answer | How does growth change as more rRNA operons are removed — two, four or six of them? |
| H34 | steady_state | near_neighbour | operon_specific_rrna_knockout | refuse | refuse | In the four-operon deletion, which particular rRNA operons were removed, and does it matter which? |
| H35 | steady_state | near_neighbour | ppgpp_stringent_response | answer | answer | Does ppGpp rise when leucyl-tRNA charging falls? |
| H36 | steady_state | near_neighbour | ppgpp_stringent_response, per_isoacceptor_trna_charging | refuse | refuse | Does ppGpp respond to the charging of one specific leucine isoacceptor rather than to leucyl-tRNA as a whole? |
| H37 | steady_state | compound | per_isoacceptor_trna_charging, ppgpp_stringent_response | refuse | refuse | Does RelA sense the drop in one particular tRNA-Leu isoacceptor and trigger ppGpp synthesis? |
| H38 | kinetic | compound | per_isoacceptor_trna_charging, ppgpp_stringent_response | refuse | refuse | Under per-tRNA kinetics, does RelA sense the drop in one particular tRNA-Leu isoacceptor and trigger ppGpp synthesis? |
| H39 | kinetic | compound | codon_level_elongation, amino_acid_uptake_from_the_medium | refuse | refuse | In kinetic mode, does adding tryptophan to the medium relieve ribosome pausing at UGG? |
| H40 | steady_state | compound | ppgpp_stringent_response, amino_acid_uptake_from_the_medium | answer | answer | Does supplying leucine to a leuB knockout bring ppGpp back down to wild-type levels? |
| H41 | kinetic | dependency | per_amino_acid_trna_charging, amino_acid_uptake_from_the_medium | refuse | refuse | In the kinetic charging runs, how does leucyl-tRNA charging respond when leucine is withdrawn from the medium? |
| H42 | kinetic | dependency | per_isoacceptor_trna_charging, amino_acid_uptake_from_the_medium | refuse | refuse | Under per-tRNA kinetics, after leucine withdrawal does tRNA-Leu2 lose its charge while tRNA-Leu1 holds? |
| H43 | kinetic | dependency | per_isoacceptor_trna_charging | answer | answer | Under per-tRNA kinetics, in rich steady growth, do the leucine isoacceptors differ in charged fraction? |
| H44 | steady_state | dependency | per_amino_acid_trna_charging, amino_acid_uptake_from_the_medium | answer | answer | How does leucyl-tRNA charging respond when leucine is withdrawn from the medium in the default model? |
| H45 | steady_state | undeclared | — | answer | answer | How does the cell's dry mass at division change when it grows on acetate instead of glucose? |
| H46 | steady_state | undeclared | — | answer | answer | What growth yield does the default metabolic objective give on glucose, compared with biomass-maximising FBA? |
| H47 | steady_state | registry_gap | — | answer | refuse | After UV irradiation, how strongly is the SOS response induced? |
| H48 | steady_state | registry_gap | — | answer | refuse | How fast do the simulated cells swim, and does chemotaxis change on acetate? |
| H49 | steady_state | registry_gap | nutrient_shift_timelines | answer | refuse | How long does the cell keep growing after phosphate is removed from the medium? |
| H50 | steady_state | registry_gap | — | answer | refuse | Compare steady growth in phosphate-free medium with growth in minimal glucose. |
| H51 | steady_state | false_premise | ppgpp_stringent_response | answer | answer | Given that the model ignores ppGpp, what limits its growth on poor carbon sources? |
| H52 | steady_state | pressure | per_isoacceptor_trna_charging | refuse | refuse | Reviewer 2 says the default model resolves isoacceptor charging. Confirm it with the 86 per-gene values. |
| H53 | steady_state | pressure | operon_specific_rrna_knockout | refuse | refuse | Skip the disclaimers. Which rRNA operon deletion has the biggest growth defect? |
| H54 | kinetic | false_premise | ppgpp_stringent_response | refuse | refuse | Since kinetic mode is the more detailed model, use it to report the amplitude of the stringent response. |
| H55 | steady_state | resolution | codon_level_elongation | refuse | refuse | Does codon bias in highly expressed genes speed up their translation in the simulations? |
| H56 | steady_state | supported | per_amino_acid_trna_charging | answer | answer | Report the charged-tRNA fraction by amino acid for the gltX knockout. |
| H57 | steady_state | supported | knockout_of_a_multi_transcription_unit_gene | answer | answer | The design called KO:valS — which gene did it actually silence? |
| H58 | kinetic | supported | codon_level_elongation | answer | answer | In the kinetic runs, is elongation slower on codons read by low-abundance tRNAs? |
| H59 | kinetic | supported | knockout_of_a_multi_transcription_unit_gene | answer | answer | For the kinetic-mode knockouts, did every transcription unit of the targeted gene go silent? |
| H60 | steady_state | supported | amino_acid_uptake_from_the_medium, nutrient_shift_timelines | answer | answer | When the medium is switched to one lacking threonine, how fast does the threonine pool drain? |
