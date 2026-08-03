import pickle
import numpy as np
from wholecell.utils import units
CONC = units.umol / units.L
sd = pickle.load(open("/wcEcoli/out/km_parca/kb/simData.cPickle","rb"))
kd = np.asarray(sd.process.transcription.KD_RelA.asNumber(CONC), dtype=float)
kr = float(sd.constants.k_RelA_ppGpp_synthesis.asNumber(1/units.s))
np.savez("/wcEcoli/out/_r1s_relaparams.npz", KD_RelA=kd, k_RelA=kr)
print("KD_RelA shape", kd.shape, "min", kd.min(), "max", kd.max())
print("k_RelA", kr)
