#!/usr/bin/env python3
"""
make_ratios_list.py -- generates the ratio,label,runaway_tmax rows
sweep.sub's `queue ratio,label,runaway_tmax from ratios.txt` reads,
using run_bfield_transient.py's own sanitize_label() so Condor job
labels always match what run_bfield_transient.py would derive itself.
Ported from electrothermal/condor/make_ratios_list.py -- identical
logic, only the imported module differs.

Also checks for label collisions before writing anything -- two ratios
that sanitize to the same label would both write to the same Condor
output path and clobber each other.

Usage:
  # explicit list, default runaway_tmax (900)
  python3 make_ratios_list.py 0.7 > ratios.txt

  # range: START STOP STEP, STOP inclusive
  python3 make_ratios_list.py --range 0.60 0.80 0.05 > ratios.txt

  # different runaway_tmax for a different regime (append with >>)
  python3 make_ratios_list.py 0.7 0.85 > ratios.txt
  python3 make_ratios_list.py --runaway-tmax 250 1.05 1.36 >> ratios.txt
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_bfield_transient as rt


def frange_inclusive(start, stop, step, ndigits=6):
    if step <= 0:
        raise ValueError(f"--range step must be positive, got {step}")
    if stop < start:
        raise ValueError(f"--range stop ({stop}) must be >= start ({start})")
    # round() the step count first: (stop-start)/step is prone to float noise,
    # which would otherwise silently drop or add an extra point at the end.
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
                        f"invocation (default: {rt.DEFAULT_RUNAWAY_TMAX}) -- run "
                        f"this script once per regime and append if different "
                        f"ratios need different thresholds.")
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
