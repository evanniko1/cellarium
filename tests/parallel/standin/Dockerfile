# Lightweight stand-in for the local wcEcoli model image.
# Reproduces ONLY the invocation contract cellarium's runner depends on:
#   WORKDIR /wcEcoli, `python runscripts/manual/{runSim,runParca}.py ...`, output under /wcEcoli/out.
# It runs no biology; it exists to test cellarium's parallel container orchestration.
FROM python:3.11-slim
WORKDIR /wcEcoli
COPY runSim.py   /wcEcoli/runscripts/manual/runSim.py
COPY runParca.py /wcEcoli/runscripts/manual/runParca.py
