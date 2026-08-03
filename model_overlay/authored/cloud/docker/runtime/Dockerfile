# Container image #1: wcm-runtime.
# This Dockerfile builds the runtime environment for the whole cell model.
#
# To build this image locally from the wcEcoli/ project root directory:
#
#     > docker build -f cloud/docker/runtime/Dockerfile -t ${USER}-wcm-runtime .
#
# (To build using the Cloud Build service and store in an Artifact Registry,
# run `cloud/build.sh`.)
#
# Add option `--build-arg from=ABC` to build from a different base image "ABC"
# but DO NOT USE an alpine base since the simulation math comes out different!
# See https://pythonspeed.com/articles/alpine-docker-python/ for more reasons.
ARG from=python:3.11.3
FROM ${from}

RUN echo "alias ls='ls --color=auto'" >> ~/.bashrc \
    && echo "alias ll='ls -l'" >> ~/.bashrc \
    && cp ~/.bashrc /

# Update and install in the same layer so it won't install from old updates.
RUN apt-get update \
    && apt-get install -y swig gfortran llvm cmake nano

# Option `--build-arg COMPILE_BLAS=1` makes this Dockerfile compile OpenBLAS and
# also compile numpy and scipy from source code so they link to this OpenBLAS.
# That can add 2 hours to the build time on Google Cloud Build and it might
# produce more consistent results.
ARG COMPILE_BLAS=0
ENV COMPILE_BLAS="$COMPILE_BLAS"

RUN if [ "${COMPILE_BLAS}" != 0 ]; then \
    (echo "[openblas]" \
    && echo "libraries = openblas" \
    && echo "library_dirs = /usr/lib" \
    && echo "include_dirs = /usr/include") > ~/.numpy-site.cfg; \
    fi

# If COMPILE_BLAS=1 then option `--build-arg NO_AVX2=1` compiles OpenBLAS' to
# not use AVX2 vector instructions:
#
# * NO_AVX2=1 is needed to compile OpenBLAS in Docker-for-Mac due to a Docker
#   bug, but it computes slightly different results.
# * NO_AVX2=0 gets more consistent results and reportedly runs 20-30% faster
#   (although it only saves ~7% in a cell sim). Use this when building in
#   Docker-for-Linux. The built Images seem to run fine on Mac.
#
# Docker-for-Mac bug:
# https://github.com/xianyi/OpenBLAS/issues/2244
# https://github.com/docker/for-mac/issues/4576
# https://github.com/machyve/xhyve/issues/171
ARG NO_AVX2=0
ENV NO_AVX2="$NO_AVX2"

# Install OpenBLAS for numpy, scipy, and Aesara.
ENV OPENBLAS_LABEL=v0.3.27
RUN if [ -f ~/.numpy-site.cfg ]; then \
    (mkdir -p openblas && cd openblas \
    && curl -SL https://github.com/OpenMathLib/OpenBLAS/archive/${OPENBLAS_LABEL}.tar.gz | tar -xz \
    && cd OpenBLAS* \
    && echo "Compiling OpenBLAS ${OPENBLAS_LABEL} with NO_AVX2=${NO_AVX2}" \
    && make "NO_AVX2=${NO_AVX2}" FC=gfortran \
    && make "NO_AVX2=${NO_AVX2}" PREFIX=/usr install) \
    && rm -r openblas; \
    fi

# This gets more consistent results from openblas.
ENV OPENBLAS_NUM_THREADS=1

# CELLARIUM OVERLAY — four added pip lines below, and nothing else in this file is changed.
#
# MEASURED 2026-08-03: upstream's own `cloud/build-containers-locally.sh` FAILS on a clean
# CovertLab/wcEcoli a4497e17 checkout, before any Cellarium code is involved. TWO independent
# dependencies have bit-rotted, and the second only becomes visible once the first is fixed:
#
#   (1) `requirements.txt:79` pins `Equation==1.2.1`, published as an sdist only (no wheel for any
#       Python). Its setup.py calls the 2013-era `ez_setup`, which downloads
#           https://pypi.python.org/packages/source/s/setuptools/setuptools-2.1.zip
#       That legacy PyPI path no longer serves a zip, so `zipfile` gets HTML and raises
#           zipfile.BadZipFile: File is not a zip file
#        -> ERROR: Failed to build 'Equation' when getting requirements to build wheel
#       `Equation` is not optional: `wholecell/utils/enzymeKinetics.py:10` imports it.
#
#   (2) `requirements.txt:98` pins `stochastic-arrow==1.0.0`, whose setup.py imports numpy at build
#       time and declares no build-requires. Under PEP 517 build isolation the build environment
#       cannot see the numpy this Dockerfile installed one line earlier:
#           ModuleNotFoundError: No module named 'numpy'
#        -> ERROR: Failed to build 'stochastic-arrow' when getting requirements to build wheel
#
# THE FIX, and why it is these four lines. `--no-build-isolation` makes each sdist's setup.py use the
# interpreter's ALREADY-INSTALLED packages instead of a fresh isolated build env — which removes the
# dead URL in (1) and makes numpy visible in (2). For (1) that alone is not enough: modern setuptools
# (83.x, measured) cannot build the sdist either, so setuptools is pinned below 66 for exactly that
# one install and restored immediately after.
#
# Installing both BEFORE `-r requirements.txt` means the requirements pass finds them already
# satisfied and skips them, so NOTHING ELSE in requirements.txt loses build isolation. Verified: with
# these four lines the full requirements.txt install exits 0 and the image builds.
#
# Install all the pips within one Docker layer, don't cache the downloads, and
# enable Aesara to write into the data dir it gets when running as a user with
# no home dir. (That happens because DockerTask runs tasks inside the Docker
# container with the uid:gid of the user outside the container to get
# read/write/delete access to the tasks's output files.)
COPY requirements.txt /
RUN (b1="" \
    && if [ -f ~/.numpy-site.cfg ] ; then b1="--no-binary=numpy,scipy"; fi \
    && echo "Installing pips with '$b1'" \
    && pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir numpy==1.26.3 $b1 \
    && pip install --no-cache-dir "setuptools<66" \
    && pip install --no-cache-dir --no-build-isolation Equation==1.2.1 \
    && pip install --no-cache-dir --upgrade setuptools \
    && pip install --no-cache-dir --no-build-isolation stochastic-arrow==1.0.0 \
    && pip install --no-cache-dir -r requirements.txt $b1 \
    && umask 000 && mkdir -p /.aesara)

CMD ["/bin/bash"]
