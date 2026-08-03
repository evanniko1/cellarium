#!/bin/bash
# A1 control-arm validation: is the freshly-run control byte-identical to the km3 baseline
# on which ROUTE1-77/79 measured rho? Same kb (km_parca), same image, same seed, same flags.
for s in 0 1 2; do
  a=/wcEcoli/out/a1c_s${s}/wildtype_000000/00000${s}/generation_000000/000000/simOut
  b=/wcEcoli/out/km3_fam_s${s}/wildtype_000000/00000${s}/generation_000000/000000/simOut
  for f in GrowthLimits/fraction_trna_charged Mass/cellMass GrowthLimits/ppgpp_conc; do
    ha=$(md5sum "$a/$f" 2>/dev/null | cut -d' ' -f1)
    hb=$(md5sum "$b/$f" 2>/dev/null | cut -d' ' -f1)
    if [ -z "$ha" ] || [ -z "$hb" ]; then
      echo "seed$s $f COULD NOT READ  a=[$ha] b=[$hb]"
    elif [ "$ha" = "$hb" ]; then
      echo "seed$s $f IDENTICAL $ha"
    else
      echo "seed$s $f DIFFER $ha vs $hb"
    fi
  done
done
