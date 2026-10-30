#!/bin/bash
# Condor job executable: runs one current ratio to completion inside the
# job's sandbox. Extracts payload.tar.gz (transferred in separately, see
# sweep.sub) into ./work -- no sibling shared/ needed, this track is
# self-contained (see make_payload.sh).
#
# --force is used unconditionally: this is always a fresh sandbox (see
# condor/README.md's "no resume-on-preemption" limitation), so there is
# never a stale runs/<label> to protect against -- it's just defensive.
#
# Usage (as Condor invokes it): condor_run_ratio.sh <ratio> <label> [extra run_transient.py args...]
set -euo pipefail

RATIO="$1"
LABEL="$2"
shift 2

tar xzf payload.tar.gz
cd work
python3 run_transient.py --ratio "$RATIO" --label "$LABEL" --force "$@"
