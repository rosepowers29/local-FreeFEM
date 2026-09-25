#!/bin/bash
# Condor job executable: runs one current ratio to completion inside the
# job's sandbox. Extracts payload.tar.gz (transferred in separately, see
# sweep.sub) into ./work (Bfield files) and ./shared (siblings, so
# step_3d_slit_transient_bfield.edp's `include "../shared/..."` resolves
# exactly like it does when run locally from 3D-slit/Bfield/). Ported
# from electrothermal/condor/condor_run_ratio.sh -- only change is the
# Python entry point.
#
# --force is used unconditionally: this is always a fresh sandbox (see
# condor/README.md's "no resume-on-preemption" limitation), so there is
# never a stale runs/<label> to protect against -- it's just defensive.
#
# Usage (as Condor invokes it): condor_run_ratio.sh <ratio> <label> [extra run_bfield_transient.py args...]
set -euo pipefail

RATIO="$1"
LABEL="$2"
shift 2

tar xzf payload.tar.gz
cd work
python3 run_bfield_transient.py --ratio "$RATIO" --label "$LABEL" --force "$@"
