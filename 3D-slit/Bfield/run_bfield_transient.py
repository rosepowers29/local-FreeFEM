#!/usr/bin/env python3
"""
run_bfield_transient.py -- drives step_3d_slit_transient_bfield.edp through
a full transient run at a given transport-current ratio: reinitializes the
checkpoint/CSV outputs, repeatedly re-invokes FreeFem++, and stops
automatically once the current split has settled back near 50/50, a
runaway/divergence signal appears, or the script's own tEnd is reached --
instead of a human eyeballing transient_3d_slit.csv and deciding by hand.

Ported from electrothermal/run_transient.py (see that track's CLAUDE.md for
the full derivation of every threshold/flag below) once
step_3d_slit_transient_bfield.edp grew the matching -ratio/-outprefix/
-steps-per-invocation/etc. flags. Differences from the electrothermal
version, both deliberate:
  - No --resume support yet -- electrothermal's --resume reconstructs
    deviation/trend state from an existing transient_3d_slit.csv, which
    this workflow could do identically, but it hasn't been ported/verified
    here yet. An interrupted run currently needs re-initializing.
  - No prePulse/runaway_before_pulse status split -- that was added to
    electrothermal AFTER its own I0 fix, as a separate, later feature, and
    was explicitly not ported to this workflow's .edp. "runaway" here
    covers both the heater-triggered and pure-overcurrent cases.

The stop-condition thresholds below are the same first-pass placeholders
electrothermal's docstring already flags -- no Bfield-specific run data has
calibrated them yet. See 3D-slit/Bfield/CLAUDE.md.

Usage:
  python3 run_bfield_transient.py --ratio 0.70
  python3 run_bfield_transient.py --ratio 0.85 --label r0p85 --max-steps 5
"""
import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
INIT_SCRIPT = "init_3d_slit_transient_checkpoint.edp"
STEP_SCRIPT = "step_3d_slit_transient_bfield.edp"
TRANSIENT_CSV = "transient_3d_slit.csv"

# Same set electrothermal's run_transient.py uses -- statuses with no
# trustworthy result at all (crashed, never started, garbage numbers), as
# opposed to a legitimate-if-unwanted terminal outcome (settled/runaway/
# reached_end_*/plateaued_off_parity/max_steps_exceeded).
RETRY_WORTHY_STATUSES = {"crashed", "init_failed", "numerical_divergence", "no_data"}

DEFAULT_RUNAWAY_TMAX = 900.0
DEFAULT_DEVIATION_EPS = 0.01
DEFAULT_RECOVER_EPS = 0.002
DEFAULT_RECOVER_HOLD_TIME = 0.1
# See electrothermal/run_transient.py's identical constant: fracLeft
# returning to ~0.5 can mean BOTH sides went symmetrically resistive in a
# full-tape runaway, not that the quench recovered. 90.0 = Tc, matching
# this repo's REBCO Tc used throughout.
DEFAULT_SETTLE_TMAX_MAX = 90.0
DEFAULT_MAX_STEPS = 500
DEFAULT_TREND_WINDOW = 0.3
DEFAULT_TREND_EPS = 0.001
# Amortizes the mesh-rebuild-per-invocation cost (the mesh is rebuilt from
# scratch on every FreeFEM process launch) across this many physical
# timesteps per invocation instead of just 1 -- see CLAUDE.md. Safe
# regardless of the exact value: the .edp checkpoints after every physical
# step, not once per invocation.
DEFAULT_STEPS_PER_INVOCATION = 20
# 0.0 is a sentinel meaning "use the .edp's original fixed 0.5s ramp
# duration" -- set >0 (target A/s) to derive Tramp = I0Target/ramp_rate.
DEFAULT_RAMP_RATE = 0.0
DEFAULT_RAMP_DT = 0.05
DEFAULT_RAMP_DT_ABOVE_IC = 0.002
DEFAULT_MAX_STEP_RISE = 500.0
DEFAULT_MAX_BISECTIONS = 10
DEFAULT_MAX_JC_FRAC_CHANGE = 0.05


def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_label(ratio):
    # "0.70" -> "r0p70"; avoids dots, which are awkward in tar/rsync/glob
    # patterns for an eventual colleague handoff.
    s = f"{ratio:.4f}".rstrip("0").rstrip(".")
    return "r" + s.replace(".", "p").replace("-", "neg")


def freefem_binary(freefem_bin=None):
    # Resolution order: explicit --freefem-bin flag, then FREEFEM_BIN env
    # var, then PATH. Needed because FreeFEM installs are commonly a
    # from-source/home-directory build on remote/cluster machines.
    #
    # shutil.which() is applied to WHATEVER candidate wins, not just the
    # PATH fallback -- found live while testing this wrapper: passing a
    # bad --freefem-bin (or a stale FREEFEM_BIN) previously passed this
    # function's `is None` check (a bad string is still truthy) and only
    # failed later inside subprocess.Popen with an unhandled
    # FileNotFoundError traceback, not this function's intended clean
    # error message. which() checks existence+executability for an
    # absolute/relative path too, not just a bare name on PATH, so this
    # one call covers all three resolution sources uniformly.
    candidate = freefem_bin or os.environ.get("FREEFEM_BIN") or "FreeFem++"
    resolved = shutil.which(candidate)
    if resolved is None:
        sys.exit(f"FreeFem++ not found or not executable at {candidate!r} -- "
                 f"pass --freefem-bin /path/to/FreeFem++, set FREEFEM_BIN, or "
                 f"add it to PATH.")
    return resolved


def reinit_run_dir(run_dir: Path, force: bool):
    if run_dir.exists():
        if force:
            shutil.rmtree(run_dir)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = run_dir.parent / f"{run_dir.name}.bak.{stamp}"
            run_dir.rename(backup)
            print(f"[run_bfield_transient] existing {run_dir} moved aside to {backup}")
    run_dir.mkdir(parents=True, exist_ok=True)


def run_freefem(script_name, extra_args, log_fh, freefem_bin=None):
    exe = freefem_binary(freefem_bin)
    cmd = [exe, "-nw", script_name] + extra_args
    header = f"{ts()} $ {' '.join(cmd)}\n"
    print(header, end="", flush=True)
    log_fh.write(header)
    log_fh.flush()
    # Stream output live (mesh build + solve costs minutes here, not
    # seconds) instead of buffering until the process exits -- a silent
    # multi-minute wait is indistinguishable from a real hang.
    proc = subprocess.Popen(cmd, cwd=SCRIPT_DIR, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        print(line, end="", flush=True)
        log_fh.write(line)
        log_fh.flush()
    proc.wait()
    return proc.returncode


def read_last_row(csv_path: Path):
    if not csv_path.exists():
        return None
    with csv_path.open() as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        return None
    header, last = rows[0], rows[-1]
    return dict(zip(header, last))


def classify_trend(trend_buffer, trend_eps):
    # trend_buffer holds (t, deviation) pairs spanning the last
    # trend-window seconds. Slope of deviation (not fracLeft directly) so
    # sign is unambiguous regardless of which side the split leans toward.
    if len(trend_buffer) < 2:
        return None
    t0, d0 = trend_buffer[0]
    t1, d1 = trend_buffer[-1]
    if t1 - t0 <= 0:
        return None
    slope = (d1 - d0) / (t1 - t0)
    if abs(slope) < trend_eps:
        return "plateaued"
    return "diverging" if slope > 0 else "converging"


def finalize(status_path, log_fh, label, ratio, status, row, n_steps, start_time,
             trend=None):
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
        "trend": trend,
    }
    log_fh.write(f"{ts()} FINISHED status={status} n_steps={n_steps} elapsed={elapsed:.1f}s\n")
    status_path.write_text(json.dumps(summary, indent=2))
    print(f"[run_bfield_transient] label={label} ratio={ratio} -> {status} "
          f"({n_steps} steps, {elapsed:.1f}s)")
    return summary


def run_one(ratio, label, base_dir="runs", runaway_tmax=DEFAULT_RUNAWAY_TMAX,
            deviation_eps=DEFAULT_DEVIATION_EPS, recover_eps=DEFAULT_RECOVER_EPS,
            recover_hold_time=DEFAULT_RECOVER_HOLD_TIME, max_steps=DEFAULT_MAX_STEPS,
            force=False, freefem_bin=None, trend_window=DEFAULT_TREND_WINDOW,
            trend_eps=DEFAULT_TREND_EPS,
            steps_per_invocation=DEFAULT_STEPS_PER_INVOCATION,
            ramp_rate=DEFAULT_RAMP_RATE, ramp_dt=DEFAULT_RAMP_DT,
            ramp_dt_above_ic=DEFAULT_RAMP_DT_ABOVE_IC,
            settle_tmax_max=DEFAULT_SETTLE_TMAX_MAX,
            max_step_rise=DEFAULT_MAX_STEP_RISE,
            max_bisections=DEFAULT_MAX_BISECTIONS,
            max_jc_frac_change=DEFAULT_MAX_JC_FRAC_CHANGE):
    run_dir = SCRIPT_DIR / base_dir / label
    # Forward slashes: this is a string handed to FreeFEM's ofstream/ifstream,
    # not a Python path, and this repo's target machine is Linux/remote.
    out_prefix = f"{base_dir}/{label}/"

    log_path = run_dir / "run.log"
    status_path = run_dir / "status.json"
    csv_path = run_dir / TRANSIENT_CSV

    reinit_run_dir(run_dir, force)
    n_steps, prev_t, has_deviated, trend_buffer = 0, None, False, deque()
    recover_since = None

    start_time = time.monotonic()
    with log_path.open("w") as log_fh:
        log_fh.write(f"{ts()} starting ratio={ratio} label={label}\n")

        rc = run_freefem(INIT_SCRIPT, ["-outprefix", out_prefix], log_fh, freefem_bin)
        if rc != 0:
            return finalize(status_path, log_fh, label, ratio, "init_failed",
                             None, 0, start_time)

        while True:
            rc = run_freefem(STEP_SCRIPT, ["-ratio", str(ratio), "-outprefix", out_prefix,
                                            "-steps-per-invocation", str(steps_per_invocation),
                                            "-ramprate", str(ramp_rate), "-rampdt", str(ramp_dt),
                                            "-rampdt-aboveic", str(ramp_dt_above_ic),
                                            "-tmaxcutoff", str(runaway_tmax),
                                            "-maxsteprise", str(max_step_rise),
                                            "-maxbisections", str(max_bisections),
                                            "-maxjcfracchange", str(max_jc_frac_change)],
                              log_fh, freefem_bin)
            # NOTE: n_steps counts FreeFEM invocations, not physical timesteps,
            # once steps_per_invocation > 1 -- see CLAUDE.md.
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

            # Checked BEFORE the runaway threshold: NaN/Inf comparisons
            # against a finite threshold are false in Python, so a
            # diverged-to-NaN run would otherwise never trip the runaway
            # check and would just spin to max_steps writing garbage.
            if any(math.isnan(v) or math.isinf(v) for v in (tmax, frac_left)):
                return finalize(status_path, log_fh, label, ratio,
                                 "numerical_divergence", row, n_steps, start_time)

            if tmax > runaway_tmax:
                # No prePulse column here (see module docstring) -- unlike
                # electrothermal, this workflow doesn't distinguish a pure
                # overcurrent/ramp-driven runaway from a heater-triggered one.
                return finalize(status_path, log_fh, label, ratio, "runaway",
                                 row, n_steps, start_time)

            deviation = abs(frac_left - 0.5)
            if deviation > deviation_eps:
                has_deviated = True

            # Both deviation AND tmax must be satisfied -- a symmetric
            # full-tape runaway can pass the deviation check alone while
            # very much not being safe. See DEFAULT_SETTLE_TMAX_MAX above.
            if has_deviated and deviation < recover_eps and tmax < settle_tmax_max:
                if recover_since is None:
                    recover_since = t
                elif t - recover_since >= recover_hold_time:
                    return finalize(status_path, log_fh, label, ratio, "settled",
                                     row, n_steps, start_time)
            else:
                recover_since = None

            trend_buffer.append((t, deviation))
            while trend_buffer and t - trend_buffer[0][0] > trend_window:
                trend_buffer.popleft()
            trend = classify_trend(trend_buffer, trend_eps) if has_deviated else None

            if (has_deviated and deviation >= recover_eps and trend == "plateaued"
                    and t - trend_buffer[0][0] >= trend_window):
                return finalize(status_path, log_fh, label, ratio,
                                 "plateaued_off_parity", row, n_steps, start_time, trend)

            if prev_t is not None and t <= prev_t + 1e-12:
                status = "reached_end_deviated" if has_deviated else "reached_end_no_deviation"
                return finalize(status_path, log_fh, label, ratio, status,
                                 row, n_steps, start_time, trend)
            prev_t = t

            if n_steps >= max_steps:
                return finalize(status_path, log_fh, label, ratio,
                                 "max_steps_exceeded", row, n_steps, start_time, trend)


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
    p.add_argument("--settle-tmax-max", type=float, default=DEFAULT_SETTLE_TMAX_MAX,
                   help=f"Tmax (K) must ALSO be below this for a run to be "
                        f"declared settled, not just a recovered current split "
                        f"(default: {DEFAULT_SETTLE_TMAX_MAX}, i.e. Tc)")
    p.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS,
                   help=f"Safety cap on invocations for this ratio "
                        f"(default: {DEFAULT_MAX_STEPS})")
    p.add_argument("--trend-window", type=float, default=DEFAULT_TREND_WINDOW,
                   help=f"Simulated seconds of trailing history used to classify "
                        f"a still-deviated run as converging/plateaued/diverging "
                        f"(default: {DEFAULT_TREND_WINDOW})")
    p.add_argument("--trend-eps", type=float, default=DEFAULT_TREND_EPS,
                   help=f"|d(deviation)/dt| below which the trend counts as "
                        f"plateaued rather than still converging/diverging "
                        f"(default: {DEFAULT_TREND_EPS})")
    p.add_argument("--force", action="store_true",
                   help="Delete any existing run directory for this label "
                        "instead of moving it aside")
    p.add_argument("--freefem-bin", default=None,
                   help="Path to the FreeFem++ executable (default: $FREEFEM_BIN "
                        "env var, else whatever 'FreeFem++' resolves to on PATH).")
    p.add_argument("--steps-per-invocation", type=int, default=DEFAULT_STEPS_PER_INVOCATION,
                   help=f"Physical timesteps advanced per FreeFEM invocation "
                        f"(default: {DEFAULT_STEPS_PER_INVOCATION}). Not the same "
                        f"as --max-steps, which caps total invocations as a "
                        f"safety net. See CLAUDE.md.")
    p.add_argument("--ramp-rate", type=float, default=DEFAULT_RAMP_RATE,
                   help="Target current ramp rate in A/s (default: "
                        f"{DEFAULT_RAMP_RATE}, meaning use the .edp's original "
                        "fixed 0.5s ramp duration). >0 derives the ramp "
                        "duration as I0Target/ramp-rate instead.")
    p.add_argument("--ramp-dt", type=float, default=DEFAULT_RAMP_DT,
                   help=f"Timestep used during the ramp phase specifically "
                        f"(default: {DEFAULT_RAMP_DT}, today's exact value).")
    p.add_argument("--ramp-dt-above-ic", type=float, default=DEFAULT_RAMP_DT_ABOVE_IC,
                   help=f"Starting dt for whatever portion of the ramp already has "
                        f"I0(t) above Ic (default: {DEFAULT_RAMP_DT_ABOVE_IC}) -- "
                        f"only matters once --ratio>1. See CLAUDE.md.")
    p.add_argument("--max-step-rise", type=float, default=DEFAULT_MAX_STEP_RISE,
                   help=f"Max K a single heatStep solve may move Tmax/Tmin from "
                        f"Told before it's retried at half dt (default: "
                        f"{DEFAULT_MAX_STEP_RISE}). See CLAUDE.md.")
    p.add_argument("--max-bisections", type=int, default=DEFAULT_MAX_BISECTIONS,
                   help=f"Max halvings of a step's dt before giving up and failing "
                        f"hard (default: {DEFAULT_MAX_BISECTIONS}).")
    p.add_argument("--max-jc-frac-change", type=float, default=DEFAULT_MAX_JC_FRAC_CHANGE,
                   help=f"Above-Ic adaptive controller's accuracy band (default: "
                        f"{DEFAULT_MAX_JC_FRAC_CHANGE}). See CLAUDE.md.")
    args = p.parse_args()

    label = args.label or sanitize_label(args.ratio)
    summary = run_one(args.ratio, label, args.base_dir, args.runaway_tmax, args.deviation_eps,
            args.recover_eps, args.recover_hold_time, args.max_steps, args.force,
            args.freefem_bin, args.trend_window, args.trend_eps,
            args.steps_per_invocation, args.ramp_rate, args.ramp_dt,
            args.ramp_dt_above_ic, args.settle_tmax_max,
            args.max_step_rise, args.max_bisections, args.max_jc_frac_change)
    if summary["status"] in RETRY_WORTHY_STATUSES:
        sys.exit(1)


if __name__ == "__main__":
    main()
