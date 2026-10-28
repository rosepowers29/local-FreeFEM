#!/usr/bin/env python3
"""
run_transient.py -- drives step_strain_tape_transient.edp through a full
transient run at a given transport-current ratio: reinitializes the
checkpoint/CSV outputs, repeatedly re-invokes FreeFem++ (one or more
timesteps per invocation), and stops once a runaway/divergence signal
appears, the run reaches its own tEnd, or a safety step cap is hit.

Simpler than 3D-slit/electrothermal's run_transient.py: this scenario has
no left/right channel split (no slit), so there's no fracLeft deviation/
recovery/plateau state machine to track -- only a single Tmax trajectory.
No heater either, so no heater-power flag.

Usage:
  python3 run_transient.py --ratio 1.05
  python3 run_transient.py --ratio 1.10 --label r1p10 --max-steps 5
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
INIT_SCRIPT = "init_strain_tape_checkpoint.edp"
STEP_SCRIPT = "step_strain_tape_transient.edp"
TRANSIENT_CSV = "transient_strain_tape.csv"
CHECKPOINT_FILE = "ckpt_strain_tape.txt"

# Same meaning as 3D-slit/electrothermal's RETRY_WORTHY_STATUSES -- statuses
# with no trustworthy physics result at all.
RETRY_WORTHY_STATUSES = {"crashed", "init_failed", "numerical_divergence", "no_data"}

DEFAULT_RUNAWAY_TMAX = 900.0
DEFAULT_MAX_STEPS = 500
DEFAULT_STEPS_PER_INVOCATION = 20
DEFAULT_RAMP_RATE = 0.0
DEFAULT_RAMP_DT = 0.05
DEFAULT_RAMP_DT_ABOVE_IC = 0.002
DEFAULT_MAX_STEP_RISE = 500.0
DEFAULT_MAX_BISECTIONS = 10
DEFAULT_MAX_JC_FRAC_CHANGE = 0.05
DEFAULT_TAP_OFFSET = 2e-3
DEFAULT_POST_RAMP_HOLD = 3.0
DEFAULT_POST_RAMP_DT = 0.01
# Trend window/eps are purely informational here (status.json metadata),
# NOT used to decide when to stop -- unlike 3D-slit/electrothermal's
# fracLeft-based early exit, there's no validated Tmax-trend threshold for
# this scenario yet (no real run data to calibrate against). See CLAUDE.md.
DEFAULT_TREND_WINDOW = 0.3
DEFAULT_TREND_EPS = 0.01


def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_label(ratio):
    s = f"{ratio:.4f}".rstrip("0").rstrip(".")
    return "r" + s.replace(".", "p").replace("-", "neg")


def freefem_binary(freefem_bin=None):
    candidate = freefem_bin or os.environ.get("FREEFEM_BIN") or shutil.which("FreeFem++")
    if candidate is None:
        sys.exit("FreeFem++ not found -- pass --freefem-bin /path/to/FreeFem++, "
                 "set FREEFEM_BIN, or add it to PATH.")
    return candidate


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


def run_freefem(script_name, extra_args, log_fh, freefem_bin=None):
    exe = freefem_binary(freefem_bin)
    cmd = [exe, "-nw", script_name] + extra_args
    header = f"{ts()} $ {' '.join(cmd)}\n"
    print(header, end="", flush=True)
    log_fh.write(header)
    log_fh.flush()
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


def classify_tmax_trend(trend_buffer, trend_eps):
    if len(trend_buffer) < 2:
        return None
    t0, tm0 = trend_buffer[0]
    t1, tm1 = trend_buffer[-1]
    if t1 - t0 <= 0:
        return None
    slope = (tm1 - tm0) / (t1 - t0)
    if abs(slope) < trend_eps:
        return "plateaued"
    return "diverging" if slope > 0 else "converging"


def finalize(status_path, log_fh, label, ratio, status, row, n_steps, start_time, trend=None):
    elapsed = time.monotonic() - start_time
    summary = {
        "label": label,
        "ratio": ratio,
        "status": status,
        "n_steps": n_steps,
        "wall_clock_seconds": round(elapsed, 1),
        "final_t": float(row["t"]) if row else None,
        "final_Tmax": float(row["Tmax"]) if row else None,
        "final_TmaxAtDefect": float(row["TmaxAtDefect"]) if row else None,
        "trend": trend,
    }
    log_fh.write(f"{ts()} FINISHED status={status} n_steps={n_steps} elapsed={elapsed:.1f}s\n")
    status_path.write_text(json.dumps(summary, indent=2))
    print(f"[run_transient] label={label} ratio={ratio} -> {status} "
          f"({n_steps} steps, {elapsed:.1f}s)")
    return summary


def load_resume_state(csv_path, trend_window):
    rows = list(csv.DictReader(csv_path.open()))
    if not rows:
        return 0, None, deque()
    prev_t = float(rows[-1]["t"])
    trend_buffer = deque((float(r["t"]), float(r["Tmax"])) for r in rows)
    while trend_buffer and prev_t - trend_buffer[0][0] > trend_window:
        trend_buffer.popleft()
    return len(rows), prev_t, trend_buffer


def run_one(ratio, label, base_dir="runs", runaway_tmax=DEFAULT_RUNAWAY_TMAX,
            max_steps=DEFAULT_MAX_STEPS, force=False, freefem_bin=None,
            resume=False, steps_per_invocation=DEFAULT_STEPS_PER_INVOCATION,
            ramp_rate=DEFAULT_RAMP_RATE, ramp_dt=DEFAULT_RAMP_DT,
            ramp_dt_above_ic=DEFAULT_RAMP_DT_ABOVE_IC,
            max_step_rise=DEFAULT_MAX_STEP_RISE, max_bisections=DEFAULT_MAX_BISECTIONS,
            max_jc_frac_change=DEFAULT_MAX_JC_FRAC_CHANGE,
            tap_offset=DEFAULT_TAP_OFFSET, post_ramp_hold=DEFAULT_POST_RAMP_HOLD,
            post_ramp_dt=DEFAULT_POST_RAMP_DT,
            trend_window=DEFAULT_TREND_WINDOW, trend_eps=DEFAULT_TREND_EPS):
    run_dir = SCRIPT_DIR / base_dir / label
    out_prefix = f"{base_dir}/{label}/"

    log_path = run_dir / "run.log"
    status_path = run_dir / "status.json"
    csv_path = run_dir / TRANSIENT_CSV

    if resume:
        ckpt_path = run_dir / CHECKPOINT_FILE
        if not ckpt_path.exists():
            sys.exit(f"--resume given but no checkpoint found at {ckpt_path}.")
        n_steps, prev_t, trend_buffer = load_resume_state(csv_path, trend_window)
        print(f"[run_transient] resuming label={label} from t={prev_t}, "
              f"{n_steps} step(s) already recorded")
        log_mode = "a"
    else:
        reinit_run_dir(run_dir, force)
        n_steps, prev_t, trend_buffer = 0, None, deque()
        log_mode = "w"

    start_time = time.monotonic()
    with log_path.open(log_mode) as log_fh:
        log_fh.write(f"{ts()} {'resuming' if resume else 'starting'} "
                      f"ratio={ratio} label={label}\n")

        if not resume:
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
                                            "-maxjcfracchange", str(max_jc_frac_change),
                                            "-tapoffset", str(tap_offset),
                                            "-postramphold", str(post_ramp_hold),
                                            "-postrampdt", str(post_ramp_dt)],
                              log_fh, freefem_bin)
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
            log_fh.write(f"{ts()} step={n_steps} t={t:.6f} Tmax={tmax:.3f}\n")
            log_fh.flush()

            if any(math.isnan(v) or math.isinf(v) for v in (tmax,)):
                return finalize(status_path, log_fh, label, ratio,
                                 "numerical_divergence", row, n_steps, start_time)

            if tmax > runaway_tmax:
                return finalize(status_path, log_fh, label, ratio, "runaway",
                                 row, n_steps, start_time)

            trend_buffer.append((t, tmax))
            while trend_buffer and t - trend_buffer[0][0] > trend_window:
                trend_buffer.popleft()
            trend = classify_tmax_trend(trend_buffer, trend_eps)

            if prev_t is not None and t <= prev_t + 1e-12:
                return finalize(status_path, log_fh, label, ratio,
                                 "reached_end", row, n_steps, start_time, trend)
            prev_t = t

            if n_steps >= max_steps:
                return finalize(status_path, log_fh, label, ratio,
                                 "max_steps_exceeded", row, n_steps, start_time, trend)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ratio", type=float, required=True,
                   help="Transport current ratio (I0Target = ratio * nominal Ic)")
    p.add_argument("--label", default=None)
    p.add_argument("--base-dir", default="runs")
    p.add_argument("--runaway-tmax", type=float, default=DEFAULT_RUNAWAY_TMAX)
    p.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    p.add_argument("--force", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--freefem-bin", default=None)
    p.add_argument("--steps-per-invocation", type=int, default=DEFAULT_STEPS_PER_INVOCATION)
    p.add_argument("--ramp-rate", type=float, default=DEFAULT_RAMP_RATE)
    p.add_argument("--ramp-dt", type=float, default=DEFAULT_RAMP_DT)
    p.add_argument("--ramp-dt-above-ic", type=float, default=DEFAULT_RAMP_DT_ABOVE_IC)
    p.add_argument("--max-step-rise", type=float, default=DEFAULT_MAX_STEP_RISE)
    p.add_argument("--max-bisections", type=int, default=DEFAULT_MAX_BISECTIONS)
    p.add_argument("--max-jc-frac-change", type=float, default=DEFAULT_MAX_JC_FRAC_CHANGE)
    p.add_argument("--tap-offset", type=float, default=DEFAULT_TAP_OFFSET,
                   help="Distance (m) from the defect to each straddling voltage tap")
    p.add_argument("--post-ramp-hold", type=float, default=DEFAULT_POST_RAMP_HOLD,
                   help="Seconds to observe after the ramp completes (no heater pulse "
                        "in this scenario -- this window is where a defect-triggered "
                        "quench, if any, develops)")
    p.add_argument("--post-ramp-dt", type=float, default=DEFAULT_POST_RAMP_DT)
    args = p.parse_args()

    label = args.label or sanitize_label(args.ratio)
    summary = run_one(args.ratio, label, args.base_dir, args.runaway_tmax, args.max_steps,
                       args.force, args.freefem_bin, args.resume, args.steps_per_invocation,
                       args.ramp_rate, args.ramp_dt, args.ramp_dt_above_ic,
                       args.max_step_rise, args.max_bisections, args.max_jc_frac_change,
                       args.tap_offset, args.post_ramp_hold, args.post_ramp_dt)
    if summary["status"] in RETRY_WORTHY_STATUSES:
        sys.exit(1)


if __name__ == "__main__":
    main()
