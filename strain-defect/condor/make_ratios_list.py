#!/usr/bin/env python3
"""
make_ratios_list.py -- generates the ratio,label,runaway_tmax rows
sweep.sub's `queue ratio,label,runaway_tmax from ratios.txt` reads, using
run_transient.py's own sanitize_label() so Condor job labels always match
what run_transient.py would derive itself. Adapted from
3D-slit/electrothermal/condor/make_ratios_list.py -- same logic, imports
THIS track's run_transient.py instead.

Also checks for label collisions before writing anything -- two ratios
that sanitize to the same label would both write to the same Condor
output path and clobber each other.

--runaway-tmax: unlike 3D-slit/electrothermal (where 250 is a specifically
CALIBRATED value for ratio>=1.0 heater-triggered quenches on a different
tape/model -- see that track's CLAUDE.md), this track has NO real-run data
yet to calibrate a tighter threshold against. Leave this at the generic
default (900) until you have enough real runs to justify tightening it --
do NOT reuse electrothermal's 250 here, it was calibrated for a physically
different scenario (heater-triggered, slit L/R split) and has no reason to
transfer to a defect-triggered, single-channel quench.

Usage:
  # explicit list (original usage), default runaway_tmax (900)
  python3 make_ratios_list.py 1.0 1.05 1.1 1.15 1.2 > ratios.txt

  # range: START STOP STEP, STOP inclusive
  python3 make_ratios_list.py --range 1.00 1.20 0.02 > ratios.txt
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_transient as rt


def frange_inclusive(start, stop, step, ndigits=6):
    if step <= 0:
        raise ValueError(f"--range step must be positive, got {step}")
    if stop < start:
        raise ValueError(f"--range stop ({stop}) must be >= start ({start})")
    # round() the step count first: (stop-start)/step is prone to float noise
    # (e.g. landing on 9.999999999998 instead of 10), which would otherwise
    # silently drop or add an extra point at the end.
    n = round((stop - start) / step)
    return [round(start + i * step, ndigits) for i in range(n + 1)]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ratios", nargs="*", type=float,
                    help="Explicit ratio list")
    p.add_argument("--range", nargs=3, type=float, metavar=("START", "STOP", "STEP"),
                    help="Generate ratios from START to STOP (inclusive) in "
                         "increments of STEP, instead of listing them individually")
    p.add_argument("--runaway-tmax", type=float, default=rt.DEFAULT_RUNAWAY_TMAX,
                   help=f"runaway_tmax value written for every ratio in THIS "
                        f"invocation (default: {rt.DEFAULT_RUNAWAY_TMAX}) -- see "
                        f"this script's own docstring before tightening it.")
    args = p.parse_args()

    if args.range and args.ratios:
        sys.exit("Pass either explicit ratios or --range, not both")
    if args.range:
        start, stop, step = args.range
        ratios = frange_inclusive(start, stop, step)
    elif args.ratios:
        ratios = args.ratios
    else:
        sys.exit("Provide explicit ratios or --range START STOP STEP")

    ratios = sorted(ratios)
    labels = [rt.sanitize_label(r) for r in ratios]

    seen = {}
    for r, lbl in zip(ratios, labels):
        seen.setdefault(lbl, []).append(r)
    dupes = {lbl: rs for lbl, rs in seen.items() if len(rs) > 1}
    if dupes:
        detail = "; ".join(f"{lbl} <- {rs}" for lbl, rs in dupes.items())
        sys.exit(f"Duplicate labels would collide, aborting without writing "
                 f"anything: {detail}")

    for ratio, label in zip(ratios, labels):
        print(f"{ratio},{label},{args.runaway_tmax}")


if __name__ == "__main__":
    main()
