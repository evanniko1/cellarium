"""Steps 1 and 2 of re-validating the annotation case: is phnE1 special, and is 91.2 min a floor?

The paper's fourth kind rests on one retyped reconstruction row moving a downstream messenger half-life
228-fold. BACKLOG PARCA-1 records, measured, that 7 of 13 arbitrary single-cistron removals reproduce the
same swing and that 91.2 min is not a fitted value but `min_deg_rates[is_mRNA] = mRNA_cistron_deg_rates.min()`,
a floor derived from one cistron (shoB) whose source row carries a single fragment and StdDev 0. If that
holds at scale, the case is a fitting-procedure defect rather than an annotation error.

STEP 1 -- base rate. Remove one cistron at a time from rnas.tsv, rebuild the parameter fit, and record how
many half-lives move more than tenfold. phnE1 is special only if the rate is low.

STEP 2 -- the floor. Drop shoB under a coverage filter (its source row has one fragment), rebuild, and see
whether fur still moves. If the swing vanishes, the mechanism is an unfiltered single-fragment measurement
propagating into a floor, not an annotation.

Each rebuild is a ParCa run (~7 min, ~114 MB), so the sweep is bounded by wall clock rather than disk.

Run:  python scripts/refit_sweep.py --step 2          # cheap, one rebuild
      python scripts/refit_sweep.py --step 1 --n 24   # the sweep
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IMAGE = os.environ.get("WCECOLI_DOCKER", "wcecoli-sim:kinetic")
OUT = "refit_sweep"
RNAS = "reconstruction/ecoli/flat/rnas.tsv"
# The model tree lives in the image and in the shipped overlay, not in this repo.
SRC = "model_overlay/files/" + RNAS


def _docker(args, out_root, extra_mounts=()):
    cmd = ["docker", "run", "--rm", "-v", "%s:/wcEcoli/out" % os.path.abspath(out_root)]
    for src, dst in extra_mounts:
        cmd += ["-v", "%s:%s" % (os.path.abspath(src), dst)]
    cmd += ["--entrypoint", "sh", IMAGE, "-c", args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def read_half_lives(kb_dir):
    """Half-lives per transcription unit from a fitted sim_data, as {tu_id: minutes}."""
    script = (
        "cd /wcEcoli && python -c \""
        "import pickle,json;"
        "sd=pickle.load(open('/kb/simData.cPickle','rb'));"
        "rna=sd.process.transcription.rna_data;"
        "import numpy as np;"
        "dr=np.asarray(rna['deg_rate'].asNumber() if hasattr(rna['deg_rate'],'asNumber') else rna['deg_rate']);"
        "hl=[(float(np.log(2)/d/60.0) if d>0 else None) for d in dr];"
        "print('HALFLIVES'+json.dumps({str(i):h for i,h in enumerate(hl)})+'END')\"")
    r = _docker(script, ".", [(kb_dir, "/kb")])
    m = r.stdout.find("HALFLIVES")
    if m < 0:
        return None
    return json.loads(r.stdout[m + 9:r.stdout.index("END", m)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, required=True, choices=(1, 2))
    ap.add_argument("--n", type=int, default=24, help="step 1: how many cistrons to sample")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    rows = open(SRC, encoding="utf-8").read().splitlines()
    hdr = next(i for i, l in enumerate(rows) if l.lstrip().startswith('"id"'))
    body = [l for l in rows[hdr + 1:] if l.strip() and not l.startswith("#")]
    print("rnas.tsv: %d data rows" % len(body), flush=True)

    if a.step == 2:
        targets = [l for l in body if l.split("	")[0] == '"G0-10634_RNA"']
        print("step 2: dropping %d shoB row(s)" % len(targets), flush=True)
    else:
        random.seed(a.seed)
        targets = random.sample([l for l in body if l.split("	")[3] == '"mRNA"'], min(a.n, len(body)))
        print("step 1: sampling %d single-cistron removals (seed %d)" % (len(targets), a.seed), flush=True)

    results = []
    for k, row in enumerate(targets, 1):
        rid = row.split("\t")[0].strip('"')
        work = os.path.join(OUT, "pseudo_%s" % rid.replace("/", "_"))
        os.makedirs(work, exist_ok=True)
        # RETYPE, do not delete. Deleting the row breaks referential integrity: genes.tsv still points at the
        # RNA and the build dies in getter_functions.py with a KeyError before any fitting happens. Retyping
        # to "pseudo" is what the phnE1 change actually did -- the cistron leaves the fit, the row stays, and
        # the perturbation matches the one the paper describes.
        cols = row.split("\t")
        assert len(cols) > 3, "unexpected row shape: %r" % row[:80]
        cols[3] = '"pseudo"'
        retyped = "\t".join(cols)
        keep = [(retyped if l == row else l) for l in body]
        assert any("pseudo" in l for l in keep if l.split("\t")[0] == cols[0]), "retype did not take"
        open(os.path.join(work, "rnas.tsv"), "w", encoding="utf-8").write(
            "\n".join(rows[:hdr + 1] + keep) + "\n")
        t0 = time.time()
        r = _docker("cd /wcEcoli && cp /patch/rnas.tsv %s && python runscripts/manual/runParca.py out/kb "
                    "--cpus 4 2>&1 | tail -3" % RNAS, work, [(work, "/patch")])
        ok = os.path.isdir(os.path.join(work, "kb"))
        results.append(dict(id=rid, ok=ok, seconds=round(time.time() - t0, 1),
                            tail=(r.stdout or "")[-200:]))
        print("[%d/%d] %-18s %s %ds" % (k, len(targets), rid, "built" if ok else "FAILED",
                                        results[-1]["seconds"]), flush=True)
    json.dump(results, open(os.path.join(OUT, "step%d.json" % a.step), "w"), indent=1)
    print("wrote %s/step%d.json" % (OUT, a.step))


if __name__ == "__main__":
    main()
