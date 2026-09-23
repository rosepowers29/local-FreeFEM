#!/usr/bin/env python3
"""
make_ratios_list.py -- generates the ratio,label,runaway_tmax rows
sweep.sub's `queue ratio,label,runaway_tmax from ratios.txt` reads,
using run_transient.py's own sanitize_label() so Condor job labels
always match what run_transient.py would derive itself. Avoids
hand-typing labels that could silently drift out of sync with the
naming convention used everywhere else in this repo.

Also checks for label collisions before writing anything -- two ratios
that sanitize to the same label would both write to the same Condor
output path and clobber each other, so this is caught here rather than
left as a manual pre-submission check. NOTE: collision checking is only
within a single invocation -- running this twice (see --runaway-tmax
below) and concatenating won't catch a collision across the two runs,
though in practice the two groups you'd use this for are disjoint
ratio ranges by construction.

--runaway-tmax is per-invocation, not per-ratio: different regimes need
different values (see CLAUDE.md's "Runaway threshold for ratio>=1.0
batches" section -- 250 is only justified for ratio>=1.0, NOT for
anything near the 0.912/0.913 recovery boundary), so build ratios.txt by
running this once per regime and appending.

Usage:
  # explicit list (original usage), default runaway_tmax (900)
  python3 make_ratios_list.py 0.5 0.7 0.8 0.9 0.925 0.95 0.99 1.0 1.1 > ratios.txt

  # range: START STOP STEP, STOP inclusive
  python3 make_ratios_list.py --range 0.90 0.95 0.005 > ratios.txt

  # two regimes, two thresholds, one file (note >> on the second call)
  python3 make_ratios_list.py 0.7 0.85 0.912 0.913 0.95 > ratios.txt
  python3 make_ratios_list.py --runaway-tmax 250 1.05 1.36 1.83 1.9 >> ratios.txt
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
    # (e.g. (0.95-0.90)/0.005 landing on 9.999999999998 instead of 10),
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
                        f"ratios need different thresholds, see CLAUDE.md.")
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
