#!/usr/bin/env python3
"""
sweep_transient.py -- runs run_transient.py's driver once per transport-
current ratio in --ratios, each into its own runs/<label>/ directory, and
aggregates every run's status.json into runs/summary.csv.

Usage:
  python3 sweep_transient.py --ratios 0.5,0.6,0.7,0.8,0.9,1.0
  python3 sweep_transient.py --ratios 0.5,0.7,0.9 --max-steps 5   # smoke test
"""
import argparse
import csv
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import run_transient as rt

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_ratios(spec):
    return [float(x) for x in spec.split(",") if x.strip()]


def run_one_job(job):
    return rt.run_one(**job)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ratios", required=True,
                   help="Comma-separated transport current ratios, e.g. 0.5,0.6,0.7")
    p.add_argument("--base-dir", default="runs")
    p.add_argument("--runaway-tmax", type=float, default=rt.DEFAULT_RUNAWAY_TMAX)
    p.add_argument("--deviation-eps", type=float, default=rt.DEFAULT_DEVIATION_EPS)
    p.add_argument("--recover-eps", type=float, default=rt.DEFAULT_RECOVER_EPS)
    p.add_argument("--recover-hold-time", type=float, default=rt.DEFAULT_RECOVER_HOLD_TIME)
    p.add_argument("--max-steps", type=int, default=rt.DEFAULT_MAX_STEPS)
    p.add_argument("--force", action="store_true")
    p.add_argument("--freefem-bin", default=None,
                   help="Path to the FreeFem++ executable (default: $FREEFEM_BIN "
                        "env var, else whatever 'FreeFem++' resolves to on PATH).")
    p.add_argument("--parallel", type=int, default=1,
                   help="Number of ratios to run concurrently (default: 1, "
                        "sequential -- matches today's proven-safe behavior). "
                        "Untested on this repo's target hardware/scheduler; "
                        "verify with a small --max-steps smoke test before "
                        "trusting a full unattended parallel sweep.")
    args = p.parse_args()

    ratios = parse_ratios(args.ratios)
    jobs = [
        dict(ratio=ratio, label=rt.sanitize_label(ratio), base_dir=args.base_dir,
             runaway_tmax=args.runaway_tmax, deviation_eps=args.deviation_eps,
             recover_eps=args.recover_eps, recover_hold_time=args.recover_hold_time,
             max_steps=args.max_steps, force=args.force, freefem_bin=args.freefem_bin)
        for ratio in ratios
    ]

    results = []
    if args.parallel <= 1:
        for job in jobs:
            results.append(run_one_job(job))
    else:
        print(f"[sweep_transient] running {len(jobs)} ratios with up to "
              f"{args.parallel} concurrent -- unverified on target hardware, "
              f"watch the first few completions closely.")
        with ProcessPoolExecutor(max_workers=args.parallel) as pool:
            futures = [pool.submit(run_one_job, job) for job in jobs]
            for fut in as_completed(futures):
                results.append(fut.result())

    summary_path = SCRIPT_DIR / args.base_dir / "summary.csv"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["label", "ratio", "status", "n_steps", "wall_clock_seconds",
                  "final_t", "final_Tmax", "final_fracLeft"]
    with summary_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(results, key=lambda r: r["ratio"]):
            writer.writerow(r)
    print(f"[sweep_transient] wrote {summary_path}")


if __name__ == "__main__":
    main()
