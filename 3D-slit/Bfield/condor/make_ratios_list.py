#!/usr/bin/env python3
"""
make_ratios_list.py -- generates the ratio,label,runaway_tmax,aniso,
selfconsistent,heaterpower rows sweep.sub's `queue ratio,label,
runaway_tmax,aniso,selfconsistent,heaterpower from ratios.txt` reads,
using run_bfield_transient.py's own sanitize_label() so Condor job
labels always match what run_bfield_transient.py would derive itself.
Ported from electrothermal/condor/make_ratios_list.py -- identical
logic, only the imported module differs.

Also checks for label collisions before writing anything -- two ratios
that sanitize to the same label would both write to the same Condor
output path and clobber each other. --aniso/--selfconsistent/--no-heater
each append a distinct suffix ("-aniso"/"-sc"/"-noheater") onto every
label in THIS invocation, so sweeps over the same ratios under different
flag combinations (the normal way to run a confirmation pair, or a
with-heater/without-heater pair) don't collide with each other -- or
with an existing runs/<label>/ from an earlier sweep.

Usage:
  # explicit list, all defaults (isotropic, lagged, heater on, runaway_tmax 900)
  python3 make_ratios_list.py 0.7 > ratios.txt

  # range: START STOP STEP, STOP inclusive
  python3 make_ratios_list.py --range 0.60 0.80 0.05 > ratios.txt

  # different runaway_tmax for a different regime (append with >>)
  python3 make_ratios_list.py 0.7 0.85 > ratios.txt
  python3 make_ratios_list.py --runaway-tmax 250 1.05 1.36 >> ratios.txt

  # anisotropic confirmation pair for the SAME ratios/runaway_tmax already
  # run isotropic -- labels get a distinct "-aniso" suffix automatically
  python3 make_ratios_list.py --aniso 0.7 > ratios.txt
  python3 make_ratios_list.py --aniso --runaway-tmax 250 1.2 >> ratios.txt

  # full aniso+self-consistent sweep, heater on vs off (two separate files)
  python3 make_ratios_list.py --aniso --selfconsistent --runaway-tmax 250 \\
      --range 0.700 1.500 0.001 > ratios_heater.txt
  python3 make_ratios_list.py --aniso --selfconsistent --no-heater --runaway-tmax 250 \\
      --range 0.700 1.500 0.001 > ratios_noheater.txt
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
    p.add_argument("--aniso", action="store_true",
                   help="Mark every ratio in THIS invocation as anisotropic "
                        "Kim model runs (writes aniso=1, and appends "
                        "'-aniso' to every label so it can't collide with "
                        "an isotropic run of the same ratio). Default: "
                        "isotropic (aniso=0, no label suffix).")
    p.add_argument("--selfconsistent", action="store_true",
                   help="Mark every ratio in THIS invocation as using the "
                        "self-consistent (non-lagged) B<->E Picard solve "
                        "(writes selfconsistent=1, appends '-sc' to every "
                        "label). Default: lagged coupling (selfconsistent=0, "
                        "no label suffix). See Bfield/CLAUDE.md's "
                        "\"Self-consistent (non-lagged) B<->E Picard solve\" "
                        "-- O(hours)/ratio once it enters the above-Ic ramp "
                        "window, not the O(minutes) a lagged run costs there.")
    p.add_argument("--no-heater", action="store_true",
                   help="Disable the heater entirely for every ratio in THIS "
                        "invocation (writes heaterpower=0.0, appends "
                        "'-noheater' to every label) -- isolates pure "
                        "above-Ic ramp-driven quench from heater-triggered "
                        "quench. Default: heater on (heaterpower=13.0, no "
                        "label suffix).")
    p.add_argument("--label-suffix", default="",
                   help="Extra literal string appended to every label in "
                        "THIS invocation, after the --aniso/--selfconsistent/"
                        "--no-heater suffixes -- e.g. '-ramp20' to distinguish "
                        "a resubmitted sweep under a corrected protocol "
                        "(different -ramprate/-rampdt/-pulsedt/-maxpicarditer) "
                        "from an already-landed sweep that used the same "
                        "aniso/selfconsistent/heater flags. Default: none.")
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
    suffix = ("-aniso" if args.aniso else "") + ("-sc" if args.selfconsistent else "") \
             + ("-noheater" if args.no_heater else "") + args.label_suffix
    labels = [rt.sanitize_label(r) + suffix for r in ratios]

    seen = {}
    for r, lbl in zip(ratios, labels):
        seen.setdefault(lbl, []).append(r)
    dupes = {lbl: rs for lbl, rs in seen.items() if len(rs) > 1}
    if dupes:
        detail = "; ".join(f"{lbl} <- {rs}" for lbl, rs in dupes.items())
        sys.exit(f"Duplicate labels would collide, aborting without writing "
                 f"anything: {detail}")

    aniso_val = 1 if args.aniso else 0
    selfconsistent_val = 1 if args.selfconsistent else 0
    heaterpower_val = 0.0 if args.no_heater else rt.DEFAULT_HEATER_POWER
    for ratio, label in zip(ratios, labels):
        print(f"{ratio},{label},{args.runaway_tmax},{aniso_val},{selfconsistent_val},{heaterpower_val}")


if __name__ == "__main__":
    main()
