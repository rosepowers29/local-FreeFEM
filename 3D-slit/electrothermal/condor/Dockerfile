# Container image for running step_3d_slit_transient_diag.edp on Condor
# execute nodes that don't already have FreeFEM installed.
#
# Built on the OFFICIAL FreeFEM project image (freefem/freefem, Ubuntu
# 22.04-based, FreeFEM v4.12) rather than assembling FreeFEM from apt
# packages ourselves -- tried the apt-based approach from root
# CLAUDE.md's gotcha first (libfreefem++/libfreefem0 on ubuntu:22.04)
# and found Ubuntu's repos only ship library packages, no actual
# FreeFem++ binary. Tried conda-forge next -- no `freefem` package
# exists there either. The official image just works: confirmed by
# actually running the real mesh_report_3d_slit.edp against it (built
# the identical mesh, nv=87870 nt=487200 nbe=26048, matching this
# project's real remote box) and spike_test_getargv.edp (getARGV works
# unchanged on this FreeFEM v4.12 build). No msh3-plugin symlink dance
# needed at all -- 3D mesh support is apparently built into this
# version's core rather than a separate loadable plugin.
#
# Only thing missing from the official image: python3, needed to run
# run_transient.py inside the container.
FROM freefem/freefem:latest
LABEL org.opencontainers.image.source="https://github.com/rosepowers29/local-FreeFEM"

RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
