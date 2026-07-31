"""EXT-PORT-11 REFIT step 4: read the aminoacylation state out of a finished simulation.

Reports the aggregate charged fraction and the WITHIN-FAMILY SPREAD (max - min of the isoacceptor
charged fractions of one amino acid) at several explicitly named depths, because the number moves
materially with depth: there is a monotonic within-generation drift (aggregate 0.8388 at t=10 s ->
0.7845 at end of generation on the shipped constants), so a spread or an aggregate quoted without
its depth is not a measurement.

Depths reported, all AFTER dropping the first `--drop` timesteps (default 10, the initial-state
transient):
  early   mean over the 30 timesteps starting at `--drop`
  t120    mean over the 10 timesteps centred on t = 120 s
  full    mean over EVERY timestep from `--drop` to the end of the generation
  late    mean over the last 30 timesteps

Charged fraction is counts-based, from BulkMolecules: charged / (charged + uncharged) per tRNA,
where the tRNA id lists come from sim_data.process.transcription.{uncharged,charged}_trna_names --
cistron space, 86 entries (see the EXT-PORT-5 note in models/ecoli/listeners/trna_charging.py).
The aggregate is the count-weighted total, which is what an assay of total tRNA measures, not the
unweighted mean of per-isoacceptor fractions.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys

import numpy as np

sys.path.insert(0, os.environ.get('WCECOLI_DIR', '/wcEcoli'))

from wholecell.io.tablereader import TableReader   # noqa: E402


def main(argv=None):
	ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
	ap.add_argument('--simout', required=True, help='.../generation_000000/000000/simOut')
	ap.add_argument('--simdata', required=True, help='the simData.cPickle that sim was run from')
	ap.add_argument('--drop', type=int, default=10, help='timesteps dropped from the start')
	ap.add_argument('--label', default='')
	ap.add_argument('--json-out', default=None)
	a = ap.parse_args(argv)

	with open(a.simdata, 'rb') as f:
		sd = pickle.load(f)
	tr = sd.process.transcription
	uncharged = list(tr.uncharged_trna_names)
	charged = list(tr.charged_trna_names)
	amino_acids = list(sd.molecule_groups.amino_acids)
	aa_from_trna = tr.aa_from_trna

	bm = TableReader(os.path.join(a.simout, 'BulkMolecules'))
	ids = list(bm.readAttribute('objectNames'))
	index = {m: i for i, m in enumerate(ids)}
	counts = bm.readColumn('counts')
	n_t = counts.shape[0]

	main_reader = TableReader(os.path.join(a.simout, 'Main'))
	times = main_reader.readColumn('time')

	U = counts[:, [index[m] for m in uncharged]].astype(float)
	C = counts[:, [index[m] for m in charged]].astype(float)

	if n_t <= a.drop + 30:
		raise SystemExit(f'only {n_t} timesteps; --drop {a.drop} leaves too few to average')

	i120 = int(np.argmin(np.abs(times - 120.0)))
	windows = {
		'early': slice(a.drop, a.drop + 30),
		't120': slice(max(a.drop, i120 - 5), max(a.drop, i120 - 5) + 10),
		'full': slice(a.drop, n_t),
		'late': slice(n_t - 30, n_t),
		}

	result = dict(label=a.label, simout=a.simout, simdata=a.simdata,
		n_timesteps=int(n_t), t_end_s=float(times[-1]), drop=a.drop, depths={})

	print(f'== {a.label or a.simout}')
	print(f'   {n_t} timesteps, t_end = {times[-1]:.0f} s, dropped first {a.drop}')
	for name, window in windows.items():
		Um, Cm = U[window].mean(axis=0), C[window].mean(axis=0)
		total = Um + Cm
		frac = np.divide(Cm, total, out=np.full_like(Cm, np.nan), where=total > 0)
		aggregate = Cm.sum() / (Cm.sum() + Um.sum())

		families = {}
		for i, amino_acid in enumerate(amino_acids):
			selection = np.where(aa_from_trna[i, :])[0]
			if len(selection) < 2:
				continue
			f = frac[selection]
			families[amino_acid] = dict(
				n=int(len(selection)),
				spread=float(np.nanmax(f) - np.nanmin(f)),
				lo=float(np.nanmin(f)), hi=float(np.nanmax(f)),
				mean=float(np.nanmean(f)))
		spreads = {k: v['spread'] for k, v in families.items()}
		result['depths'][name] = dict(
			t_start_s=float(times[window.start]),
			t_end_s=float(times[min(window.stop, n_t) - 1]),
			n_steps=int(min(window.stop, n_t) - window.start),
			aggregate=float(aggregate),
			per_trna_mean=float(np.nanmean(frac)),
			per_trna_min=float(np.nanmin(frac)),
			per_trna_max=float(np.nanmax(frac)),
			max_family_spread=float(max(spreads.values())),
			median_family_spread=float(np.median(list(spreads.values()))),
			families=families,
			)
		d = result['depths'][name]
		top = sorted(spreads.items(), key=lambda kv: -kv[1])[:3]
		print(f'   {name:6s} t=[{d["t_start_s"]:7.1f},{d["t_end_s"]:7.1f}] n={d["n_steps"]:5d}  '
			f'aggregate={aggregate:.4f}  max_family_spread={d["max_family_spread"]:.4f}  '
			f'median={d["median_family_spread"]:.4f}  worst: '
			+ ', '.join(f'{k.replace("[c]","")} {v:.3f}' for k, v in top))

	print('\n   per-family spread at depth "full":')
	fams = result['depths']['full']['families']
	for amino_acid, v in sorted(fams.items(), key=lambda kv: -kv[1]['spread']):
		print(f'     {amino_acid:22s} n={v["n"]:2d} spread={v["spread"]:.4f} '
			f'[{v["lo"]:.4f}, {v["hi"]:.4f}] mean={v["mean"]:.4f}')

	if a.json_out:
		with open(a.json_out, 'w') as f:
			json.dump(result, f, indent=2)
		print(f'\nwrote {a.json_out}')
	return 0


if __name__ == '__main__':
	sys.exit(main())
