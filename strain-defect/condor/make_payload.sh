#!/bin/bash
# Packages the code a single Condor job needs into payload.tar.gz, since
# execute nodes on this pool are sandboxed (no shared filesystem with the
# submit node -- see condor/README.md).
#
# Simpler than 3D-slit/electrothermal/condor/make_payload.sh: this track
# has NO `../shared/` dependency -- every `include` in
# step_strain_tape_transient.edp is same-directory or a `data/` subpath
# (hts_mesh_module_tape.idp, strain_jc_meta.idp, hts_materials.idp,
# data/*.txt), so the whole payload is just one flat work/ directory, no
# sibling shared/ needed.
#
# IMPORTANT: this bundles whatever strain_jc_meta.idp/strain_jc_icratio_x.txt/
# strain_jc_grid_xz.txt currently sit in this track's directory -- i.e.
# whatever the last `python3 strain_to_jc.py ...` run produced. Re-run that
# BEFORE this script if you've changed the strain data, the --surface
# choice, or resampling resolution since the last payload build. There is
# no staleness check here, same hazard class as this repo's checkpoint-
# format discipline (root CLAUDE.md) applied to a new kind of input file.
set -euo pipefail
cd "$(dirname "$0")"

BUILD_DIR=_payload_build
rm -rf "$BUILD_DIR" payload.tar.gz
mkdir -p "$BUILD_DIR/work/data"

cp ../hts_mesh_module_tape.idp \
   ../hts_materials.idp \
   ../diagnostics_strain_tape.idp \
   ../strain_jc_meta.idp \
   ../strain_jc_icratio_x.txt \
   ../strain_jc_grid_xz.txt \
   ../init_strain_tape_checkpoint.edp \
   ../step_strain_tape_transient.edp \
   ../run_transient.py \
   "$BUILD_DIR/work/"
cp -r ../data/. "$BUILD_DIR/work/data/"

tar czf payload.tar.gz -C "$BUILD_DIR" work
rm -rf "$BUILD_DIR"
echo "wrote $(pwd)/payload.tar.gz"
