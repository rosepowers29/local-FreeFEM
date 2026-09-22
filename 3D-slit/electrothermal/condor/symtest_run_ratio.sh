#!/bin/bash
# Condor job executable: A/B test of the heatStep sym=1 experiment
# (routes to CHOLMOD) against today's default (sym=0, routes to UMFPACK)
# for one ratio, one collapsed ramp step -- the exact scenario that blew
# up for r1p474 (see ../CLAUDE.md's "Ramp collapse breaks down above Ic"
# section for the full trail: the source-confirmed root cause, and why
# this couldn't be validated locally under this Mac's ARM64 emulation --
# a real Condor run is the only reliable test).
#
# Both variants run back to back in ONE job so the comparison lands in a
# single streamed .out, not two separate logs to cross-reference by hand.
#
# The baseline (sym=0) pass is EXPECTED to possibly crash/OOM for
# r1p36/r1p83 specifically -- that's the ORIGINAL bug reproducing, not a
# script error. Exit codes are captured and reported rather than
# aborting the job, so the sym=1 pass always runs regardless of how the
# baseline pass went.
#
# Usage (as Condor invokes it): symtest_run_ratio.sh <ratio> <label> [ramp args...]
set -uo pipefail

RATIO="$1"
LABEL="$2"
shift 2
RAMPARGS=("$@")

FF=/usr/freefem/bin/FreeFem++

tar xzf symtest_payload.tar.gz
cd work

run_variant () {
  local variant="$1" script="$2"
  local outdir="runs/${LABEL}_${variant}/"
  mkdir -p "$outdir"
  echo "=== ${variant} ratio=${RATIO} rampargs=${RAMPARGS[*]:-(none)} ==="
  "$FF" -nw init_3d_slit_transient_checkpoint.edp -outprefix "$outdir"
  "$FF" -nw "$script" -ratio "$RATIO" -outprefix "$outdir" \
      -steps-per-invocation 1 -rampdt-aboveic 0.002 -tmaxcutoff 900.0 \
      "${RAMPARGS[@]}"
  local rc=$?
  echo "=== ${variant} ratio=${RATIO} exited rc=${rc} ==="
}

run_variant "baseline" step_3d_slit_transient_diag.edp
run_variant "sym"      step_3d_slit_transient_diag_symtest.edp

echo "=== DONE ratio=${RATIO} label=${LABEL} -- compare the two 'Solve:' min/max lines above (baseline vs sym) ==="
