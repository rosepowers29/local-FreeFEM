#!/bin/bash
# Packages the code a single Condor job needs into payload.tar.gz, since
# execute nodes on this pool are sandboxed (no shared filesystem with the
# submit node -- see condor/README.md). Excludes shared/'s plotting
# scripts (not needed for the compute job itself, pure transfer weight
# multiplied by every job in the sweep).
#
# Layout inside the tarball: work/ (electrothermal files, becomes the
# job's cwd) and shared/ as its sibling -- so `include "../shared/..."`
# in step_3d_slit_transient_diag.edp resolves exactly like it does when
# run locally from 3D-slit/electrothermal/.
#
# Optional arg: output tarball name (default payload.tar.gz). Use a distinct
# name (e.g. payload_hold.tar.gz for sweep_noheater_hold.sub) when another
# sweep's jobs are still idle in the queue -- Condor transfers the input
# at job START, so overwriting payload.tar.gz changes what queued jobs run.
set -euo pipefail
cd "$(dirname "$0")"

OUT="${1:-payload.tar.gz}"
BUILD_DIR="_payload_build_${OUT%%.*}"
rm -rf "$BUILD_DIR" "$OUT"
mkdir -p "$BUILD_DIR/work" "$BUILD_DIR/shared/data"

cp ../init_3d_slit_transient_checkpoint.edp \
   ../step_3d_slit_transient_diag.edp \
   ../run_transient.py \
   "$BUILD_DIR/work/"

cp ../../shared/hts_mesh_module_3d_slit.idp \
   ../../shared/hts_materials.idp \
   ../../shared/diagnostics_3d_slit.idp \
   "$BUILD_DIR/shared/"
cp -r ../../shared/data/. "$BUILD_DIR/shared/data/"

tar czf "$OUT" -C "$BUILD_DIR" work shared
rm -rf "$BUILD_DIR"
echo "wrote $(pwd)/$OUT"
