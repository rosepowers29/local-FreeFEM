# Container image for running step_3d_slit_transient_diag.edp on Condor
# execute nodes that don't already have FreeFEM installed. UNTESTED --
# nobody has run FreeFEM here (this Dockerfile has never been built or
# run), it's assembled from the apt-based install + msh3-plugin symlink
# fix already verified working on this project's remote box (see root
# CLAUDE.md's "FreeFEM environment gotchas"). Build and smoke-test this
# yourself (e.g. `FreeFem++ -nw ../mesh_report_3d_slit.edp`) before
# trusting it for a real sweep.
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        libfreefem++ libfreefem0 python3 \
    && rm -rf /var/lib/apt/lists/*

# msh3 plugin fix: FreeFEM looks for plugins under /usr/lib/ff++/<version>/lib,
# but the apt package installs them under /usr/lib/freefem++ -- symlink into
# whatever version directory actually exists rather than hardcoding a
# version string (untested which version ubuntu:22.04's apt repo provides).
RUN FF_VER_DIR=$(ls -d /usr/lib/ff++/*/ | head -n1) && \
    mkdir -p "${FF_VER_DIR}lib" && \
    ln -sf /usr/lib/freefem++/*.so "${FF_VER_DIR}lib/"

WORKDIR /work
