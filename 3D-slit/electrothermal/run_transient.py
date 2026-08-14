#!/usr/bin/env python3
"""
run_transient.py -- drives step_3d_slit_transient_diag.edp through a full
transient run at a given transport-current ratio: reinitializes the
checkpoint/CSV outputs, repeatedly re-invokes FreeFem++ (one timestep per
invocation, matching maxStepsThisRun=1 in the .edp), and stops
automatically once the current split has settled back near 50/50, a
runaway/divergence signal appears, or the script's own tEnd is reached --
instead of a human eyeballing transient_3d_slit.csv and deciding by hand.

The stop-condition thresholds below are first-pass placeholders with no
real run data to calibrate against yet -- see 3D-slit/electrothermal/CLAUDE.md.

Usage:
  python3 run_transient.py --ratio 0.70
  python3 run_transient.py --ratio 0.85 --label r0p85 --max-steps 5
"""
import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
INIT_SCRIPT = "init_3d_slit_transient_checkpoint.edp"
STEP_SCRIPT = "step_3d_slit_transient_diag.edp"
TRANSIENT_CSV = "transient_3d_slit.csv"

DEFAULT_RUNAWAY_TMAX = 900.0
DEFAULT_DEVIATION_EPS = 0.01
DEFAULT_RECOVER_EPS = 0.002
DEFAULT_RECOVER_HOLD_TIME = 0.1
DEFAULT_MAX_STEPS = 500


def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_label(ratio):
    # "0.70" -> "r0p70"; avoids dots, which are awkward in tar/rsync/glob
    # patterns for the eventual colleague handoff.
    s = f"{ratio:.4f}".rstrip("0").rstrip(".")
    return "r" + s.replace(".", "p").replace("-", "neg")


def freefem_binary():
    exe = shutil.which("FreeFem++")
    if exe is None:
        sys.exit("FreeFem++ not found on PATH -- run this where FreeFEM is installed.")
    return exe


def reinit_run_dir(run_dir: Path, force: bool):
    if run_dir.exists():
        if force:
            shutil.rmtree(run_dir)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = run_dir.parent / f"{run_dir.name}.bak.{stamp}"
            run_dir.rename(backup)
            print(f"[run_transient] existing {run_dir} moved aside to {backup}")
    run_dir.mkdir(parents=True, exist_ok=True)


def run_freefem(script_name, extra_args, log_fh):
    exe = freefem_binary()
    cmd = [exe, "-nw", script_name] + extra_args
    log_fh.write(f"{ts()} $ {' '.join(cmd)}\n")
    log_fh.flush()
    result = subprocess.run(cmd, cwd=SCRIPT_DIR, capture_output=True, text=True)
    log_fh.write(result.stdout)
    if result.returncode != 0:
        log_fh.write(result.stderr)
    log_fh.flush()
    return result.returncode


def read_last_row(csv_path: Path):
    if not csv_path.exists():
        return None
    with csv_path.open() as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        return None
    header, last = rows[0], rows[-1]
    return dict(zip(header, last))


def finalize(status_path, log_fh, label, ratio, status, row, n_steps, start_time):
    elapsed = time.monotonic() - start_time
    summary = {
        "label": label,
        "ratio": ratio,
        "status": status,
        "n_steps": n_steps,
        "wall_clock_seconds": round(elapsed, 1),
        "final_t": float(row["t"]) if row else None,
        "final_Tmax": float(row["Tmax"]) if row else None,
        "final_fracLeft": float(row["fracLeft"]) if row else None,
    }
    log_fh.write(f"{ts()} FINISHED status={status} n_steps={n_steps} elapsed={elapsed:.1f}s\n")
    status_path.write_text(json.dumps(summary, indent=2))
    print(f"[run_transient] label={label} ratio={ratio} -> {status} "
          f"({n_steps} steps, {elapsed:.1f}s)")
    return summary


def run_one(ratio, label, base_dir="runs", runaway_tmax=DEFAULT_RUNAWAY_TMAX,
            deviation_eps=DEFAULT_DEVIATION_EPS, recover_eps=DEFAULT_RECOVER_EPS,
            recover_hold_time=DEFAULT_RECOVER_HOLD_TIME, max_steps=DEFAULT_MAX_STEPS,
            force=False):
    run_dir = SCRIPT_DIR / base_dir / label
    reinit_run_dir(run_dir, force)
    # Forward slashes: this is a string handed to FreeFEM's ofstream/ifstream,
    # not a Python path, and this repo's target machine is Linux/remote.
    out_prefix = f"{base_dir}/{label}/"

    log_path = run_dir / "run.log"
    status_path = run_dir / "status.json"
    csv_path = run_dir / TRANSIENT_CSV

    start_time = time.monotonic()
    with log_path.open("w") as log_fh:
        log_fh.write(f"{ts()} starting ratio={ratio} label={label}\n")

        rc = run_freefem(INIT_SCRIPT, ["-outprefix", out_prefix], log_fh)
        if rc != 0:
            return finalize(status_path, log_fh, label, ratio, "init_failed",
                             None, 0, start_time)

        prev_t = None
        has_deviated = False
        recover_since = None
        n_steps = 0

        while True:
            rc = run_freefem(STEP_SCRIPT, ["-ratio", str(ratio), "-outprefix", out_prefix], log_fh)
            n_steps += 1
            if rc != 0:
                return finalize(status_path, log_fh, label, ratio, "crashed",
                                 None, n_steps, start_time)

            row = read_last_row(csv_path)
            if row is None:
                return finalize(status_path, log_fh, label, ratio, "no_data",
                                 None, n_steps, start_time)

            t = float(row["t"])
            tmax = float(row["Tmax"])
            frac_left = float(row["fracLeft"])
            log_fh.write(f"{ts()} step={n_steps} t={t:.6f} Tmax={tmax:.3f} "
                          f"fracLeft={frac_left:.6f}\n")
            log_fh.flush()

            # Checked BEFORE the runaway threshold: NaN/Inf comparisons against
            # a finite threshold are false in Python (and nearly everywhere
            # else), so a diverged-to-NaN run would otherwise never trip the
            # runaway check and would just spin to max_steps writing garbage.
            if any(math.isnan(v) or math.isinf(v) for v in (tmax, frac_left)):
                return finalize(status_path, log_fh, label, ratio,
                                 "numerical_divergence", row, n_steps, start_time)

            if tmax > runaway_tmax:
                return finalize(status_path, log_fh, label, ratio, "runaway",
                                 row, n_steps, start_time)

            deviation = abs(frac_left - 0.5)
            if deviation > deviation_eps:
                has_deviated = True

            if has_deviated and deviation < recover_eps:
                if recover_since is None:
                    recover_since = t
                elif t - recover_since >= recover_hold_time:
                    return finalize(status_path, log_fh, label, ratio, "settled",
                                     row, n_steps, start_time)
            else:
                recover_since = None

            if prev_t is not None and t <= prev_t + 1e-12:
                status = "reached_end_deviated" if has_deviated else "reached_end_no_deviation"
                return finalize(status_path, log_fh, label, ratio, status,
                                 row, n_steps, start_time)
            prev_t = t

            if n_steps >= max_steps:
                return finalize(status_path, log_fh, label, ratio,
                                 "max_steps_exceeded", row, n_steps, start_time)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ratio", type=float, required=True,
                   help="Transport current ratio (I0Target = ratio * Ic)")
    p.add_argument("--label", default=None,
                   help="Run label / subdirectory name under --base-dir "
                        "(default: derived from ratio, e.g. r0p70)")
    p.add_argument("--base-dir", default="runs",
                   help="Directory (relative to this script) holding per-run "
                        "subdirectories (default: runs)")
    p.add_argument("--runaway-tmax", type=float, default=DEFAULT_RUNAWAY_TMAX,
                   help=f"Tmax (K) above which the run is declared runaway "
                        f"(default: {DEFAULT_RUNAWAY_TMAX})")
    p.add_argument("--deviation-eps", type=float, default=DEFAULT_DEVIATION_EPS,
                   help=f"|fracLeft-0.5| beyond which the split counts as "
                        f"having deviated (default: {DEFAULT_DEVIATION_EPS})")
    p.add_argument("--recover-eps", type=float, default=DEFAULT_RECOVER_EPS,
                   help=f"|fracLeft-0.5| below which the split counts as "
                        f"recovered (default: {DEFAULT_RECOVER_EPS})")
    p.add_argument("--recover-hold-time", type=float, default=DEFAULT_RECOVER_HOLD_TIME,
                   help=f"Simulated seconds the split must stay recovered "
                        f"before declaring settled (default: {DEFAULT_RECOVER_HOLD_TIME})")
    p.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS,
                   help=f"Safety cap on invocations for this ratio "
                        f"(default: {DEFAULT_MAX_STEPS})")
    p.add_argument("--force", action="store_true",
                   help="Delete any existing run directory for this label "
                        "instead of moving it aside")
    args = p.parse_args()

    label = args.label or sanitize_label(args.ratio)
    run_one(args.ratio, label, args.base_dir, args.runaway_tmax, args.deviation_eps,
            args.recover_eps, args.recover_hold_time, args.max_steps, args.force)


if __name__ == "__main__":
    main()
