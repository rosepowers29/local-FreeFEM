#!/usr/bin/env python3
"""
reclassify_runaway_prepulse.py -- post-hoc relabels status="runaway" runs
as "runaway_before_pulse" where the heater pulse never actually fired.

This batch predates step_3d_slit_transient_diag.edp's prePulse column (see
CLAUDE.md's "runaway_before_pulse status" section) -- run_transient.py's own
in-process check can only use that column going forward. For runs that
already finished without it, the same fact is still recoverable from
transient_3d_slit.csv alone: I0(t) is I0Target*(t/Tramp) while ramping
(strictly increasing) and exactly I0Target once t>=Tramp==tPulseStart (flat,
bit-identical across rows -- same variable, not recomputed). So comparing a
run's last two recorded I0 values tells us whether the heater had already
had its chance to fire, without needing Ic/Tramp (unknown to Python) at all.

Single-row runaways are left untouched (see SKIPPED_SINGLE_ROW below) and
listed for manual review -- there's no second I0 value to compare against.

Usage:
  python3 reclassify_runaway_prepulse.py            # runs/, apply changes
  python3 reclassify_runaway_prepulse.py --dry-run   # report only
  python3 reclassify_runaway_prepulse.py --base-dir runs2
"""
import argparse
import csv
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TRANSIENT_CSV = "transient_3d_slit.csv"

# Tolerance for "did I0 actually change between the last two rows" -- the
# post-ramp/flat phase re-prints the exact same double every row (not
# recomputed), so real ramp movement is many orders of magnitude larger
# than any float-formatting noise. 1e-6 A is generous slack, not a tuned
# threshold.
I0_FLAT_EPS = 1e-6


def last_two_i0(csv_path: Path):
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    if len(rows) < 2:
        return None
    return float(rows[-2]["I0"]), float(rows[-1]["I0"])


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-dir", default="runs",
                   help="Directory (relative to this script) holding per-run "
                        "subdirectories (default: runs)")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would change without writing anything")
    args = p.parse_args()

    base_dir = SCRIPT_DIR / args.base_dir
    reclassified, left_alone, skipped_single_row = [], [], []

    for status_path in sorted(base_dir.glob("*/status.json")):
        label = status_path.parent.name
        status = json.loads(status_path.read_text())
        if status.get("status") != "runaway":
            continue

        csv_path = status_path.parent / TRANSIENT_CSV
        pair = last_two_i0(csv_path)
        if pair is None:
            skipped_single_row.append(label)
            continue

        i0_prev, i0_last = pair
        still_ramping = (i0_last - i0_prev) > I0_FLAT_EPS
        if still_ramping:
            reclassified.append((label, i0_prev, i0_last))
            if not args.dry_run:
                status["status"] = "runaway_before_pulse"
                status["reclassified_post_hoc"] = True
                status_path.write_text(json.dumps(status, indent=2))
        else:
            left_alone.append(label)

    verb = "Would reclassify" if args.dry_run else "Reclassified"
    print(f"{verb} {len(reclassified)} run(s) runaway -> runaway_before_pulse:")
    for label, i0_prev, i0_last in reclassified:
        print(f"  {label}: I0 {i0_prev:.4g} -> {i0_last:.4g} (still climbing)")
    print(f"Left as runaway (I0 already flat, pulse had started): {len(left_alone)}")
    if skipped_single_row:
        print(f"SKIPPED (single-row CSV, no second I0 to compare -- review by "
              f"hand, likely a ratio<=1 single-jump-ramp case): "
              f"{', '.join(skipped_single_row)}")


if __name__ == "__main__":
    main()
