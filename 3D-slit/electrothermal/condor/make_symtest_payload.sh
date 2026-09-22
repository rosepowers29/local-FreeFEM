#!/bin/bash
# Like make_payload.sh, but also bundles step_3d_slit_transient_diag_symtest.edp
# (the sym=1 experiment variant) alongside the normal step script, since
# symtest_run_ratio.sh needs to run both for its A/B comparison. See
# ../CLAUDE.md's "Ramp collapse breaks down above Ic" section for what
# this is testing and why.
set -euo pipefail
cd "$(dirname "$0")"

BUILD_DIR=_symtest_payload_build
rm -rf "$BUILD_DIR" symtest_payload.tar.gz
mkdir -p "$BUILD_DIR/work" "$BUILD_DIR/shared/data"

cp ../init_3d_slit_transient_checkpoint.edp \
   ../step_3d_slit_transient_diag.edp \
   ../step_3d_slit_transient_diag_symtest.edp \
   ../run_transient.py \
   "$BUILD_DIR/work/"

cp ../../shared/hts_mesh_module_3d_slit.idp \
   ../../shared/hts_materials.idp \
   ../../shared/diagnostics_3d_slit.idp \
   "$BUILD_DIR/shared/"
cp -r ../../shared/data/. "$BUILD_DIR/shared/data/"

tar czf symtest_payload.tar.gz -C "$BUILD_DIR" work shared
rm -rf "$BUILD_DIR"
echo "wrote $(pwd)/symtest_payload.tar.gz"
