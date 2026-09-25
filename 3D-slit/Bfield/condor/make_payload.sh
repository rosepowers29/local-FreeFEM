#!/bin/bash
# Packages the code a single Condor job needs into payload.tar.gz, since
# execute nodes on this pool are sandboxed (no shared filesystem with the
# submit node -- see condor/README.md). Ported from
# electrothermal/condor/make_payload.sh; only real difference is the
# extra bfield_3d_slit.idp file this workflow needs alongside the step
# script (electrothermal has no equivalent -- it has no B-field model).
#
# Layout inside the tarball: work/ (Bfield files, becomes the job's cwd)
# and shared/ as its sibling -- so `include "../shared/..."` in
# step_3d_slit_transient_bfield.edp resolves exactly like it does when
# run locally from 3D-slit/Bfield/.
set -euo pipefail
cd "$(dirname "$0")"

BUILD_DIR=_payload_build
rm -rf "$BUILD_DIR" payload.tar.gz
mkdir -p "$BUILD_DIR/work" "$BUILD_DIR/shared/data"

cp ../init_3d_slit_transient_checkpoint.edp \
   ../step_3d_slit_transient_bfield.edp \
   ../bfield_3d_slit.idp \
   ../run_bfield_transient.py \
   "$BUILD_DIR/work/"

cp ../../shared/hts_mesh_module_3d_slit.idp \
   ../../shared/hts_materials.idp \
   ../../shared/diagnostics_3d_slit.idp \
   "$BUILD_DIR/shared/"
cp -r ../../shared/data/. "$BUILD_DIR/shared/data/"

tar czf payload.tar.gz -C "$BUILD_DIR" work shared
rm -rf "$BUILD_DIR"
echo "wrote $(pwd)/payload.tar.gz"
