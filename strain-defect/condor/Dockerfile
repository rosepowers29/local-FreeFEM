# Container image for running step_strain_tape_transient.edp on Condor
# execute nodes that don't already have FreeFEM installed.
#
# Byte-identical to 3D-slit/electrothermal/condor/Dockerfile -- this track
# needs nothing track-specific baked into the image (no msh3-plugin dance,
# no extra apt packages beyond python3), so there's no reason to diverge.
# Kept as its own copy rather than a cross-track reference so this
# directory stays self-contained (same reasoning as this track's own
# data/ copy instead of referencing 3D-slit/shared/data/ -- see
# ../CLAUDE.md). You can also just point sweep.sub at the ALREADY-PUBLISHED
# electrothermal image instead of rebuilding -- see README.md.
FROM freefem/freefem:latest
LABEL org.opencontainers.image.source="https://github.com/rosepowers29/local-FreeFEM"

RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
