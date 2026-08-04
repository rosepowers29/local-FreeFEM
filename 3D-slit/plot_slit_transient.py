#!/usr/bin/env python3
"""
plot_slit_transient.py

Reusable plotting macro for the slit + one-sided-heater transient results
(transient_3d_slit.csv, columns: t, I0, Tmax, TmaxLeft, TmaxRight, fracLeft).

Produces two figures:
  1. Full timeline: current ramp, heated/unheated side temperatures, and
     current-fraction-on-heated-side, all sharing a time axis.
  2. Zoomed view centered on the heater pulse, for a closer look at the
     redistribution dynamics.

Usage:
    python3 plot_slit_transient.py transient_3d_slit.csv
    python3 plot_slit_transient.py transient_3d_slit.csv --outdir results/
    python3 plot_slit_transient.py transient_3d_slit.csv --pulse-start 0.5 --pulse-dur 0.01 --tc 90

If your CSV already has a header row (newer runs write one automatically),
this script detects it; if not, it assumes the standard column order above.
"""

import argparse
import csv
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

EXPECTED_COLS = ["t", "I0", "Tmax", "TmaxLeft", "TmaxRight", "fracLeft"]


def load_csv(path):
    with open(path) as f:
        first_line = f.readline().strip()
    has_header = not first_line.split(",")[0].replace(".", "").replace("-", "").isdigit()

    if has_header:
        rows = list(csv.DictReader(open(path)))
    else:
        rows = list(csv.DictReader(open(path), fieldnames=EXPECTED_COLS))

    data = {col: np.array([float(r[col]) for r in rows]) for col in EXPECTED_COLS}
    return data


def make_full_timeline_plot(data, pulse_start, pulse_end, tc, outpath, title):
    t, I0 = data["t"], data["I0"]
    TmaxLeft, TmaxRight, fracLeft = data["TmaxLeft"], data["TmaxRight"], data["fracLeft"]

    fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)

    axes[0].plot(t, I0, color="tab:purple")
    axes[0].axvspan(pulse_start, pulse_end, color="red", alpha=0.12, label="heater pulse")
    axes[0].set_ylabel("I0 [A]")
    axes[0].legend(loc="lower right", fontsize=9)

    axes[1].plot(t, TmaxLeft, "o-", color="tab:red", markersize=3, label="Heated side (left)")
    axes[1].plot(t, TmaxRight, "s-", color="tab:blue", markersize=3, label="Unheated side (right)")
    if tc is not None:
        axes[1].axhline(tc, color="gray", linestyle="--", alpha=0.5, label="Tc")
    axes[1].axvspan(pulse_start, pulse_end, color="red", alpha=0.12)
    axes[1].set_ylabel("T [K]")
    axes[1].legend(loc="upper right", fontsize=9)

    axes[2].plot(t, fracLeft, "d-", color="tab:green", markersize=3)
    axes[2].axhline(0.5, color="gray", linestyle="--", alpha=0.5, label="symmetric (0.5)")
    axes[2].axvspan(pulse_start, pulse_end, color="red", alpha=0.12)
    axes[2].set_ylabel("Current fraction\non heated side")
    axes[2].set_xlabel("time [s]")
    axes[2].legend(loc="upper left", fontsize=9)

    if title:
        fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def make_zoom_plot(data, pulse_start, pulse_end, tc, pre_margin, post_margin, outpath, title):
    t = data["t"]
    TmaxLeft, TmaxRight, fracLeft = data["TmaxLeft"], data["TmaxRight"], data["fracLeft"]

    mask = (t >= pulse_start - pre_margin) & (t <= pulse_end + post_margin)
    tz = (t[mask] - pulse_start) * 1000  # ms since pulse start

    fig, axes = plt.subplots(2, 1, figsize=(9, 7.5), sharex=True)

    axes[0].plot(tz, TmaxLeft[mask], "o-", color="tab:red", label="Heated side (left)")
    axes[0].plot(tz, TmaxRight[mask], "s-", color="tab:blue", label="Unheated side (right)")
    if tc is not None:
        axes[0].axhline(tc, color="gray", linestyle="--", alpha=0.5, label="Tc")
    axes[0].axvspan(0, (pulse_end - pulse_start) * 1000, color="red", alpha=0.12, label="heater on")
    axes[0].set_ylabel("T [K]")
    axes[0].legend(loc="upper right", fontsize=9)

    axes[1].plot(tz, fracLeft[mask], "d-", color="tab:green")
    axes[1].axhline(0.5, color="gray", linestyle="--", alpha=0.5, label="symmetric (0.5)")
    axes[1].axvspan(0, (pulse_end - pulse_start) * 1000, color="red", alpha=0.12)
    axes[1].set_ylabel("Current fraction\non heated side")
    axes[1].set_xlabel("time since pulse start [ms]")
    axes[1].legend(loc="upper left", fontsize=9)

    if title:
        fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv_path", help="Path to transient_3d_slit.csv")
    p.add_argument("--outdir", default=".", help="Directory to write output PNGs (default: current dir)")
    p.add_argument("--pulse-start", type=float, default=0.5, help="Heater pulse start time [s]")
    p.add_argument("--pulse-dur", type=float, default=0.01, help="Heater pulse duration [s]")
    p.add_argument("--tc", type=float, default=90.0, help="Critical temperature to mark [K] (use 'none' to omit)")
    p.add_argument("--zoom-pre-margin", type=float, default=0.002, help="Time [s] shown before pulse start in the zoom plot")
    p.add_argument("--zoom-post-margin", type=float, default=0.08, help="Time [s] shown after pulse end in the zoom plot")
    p.add_argument("--title", default="", help="Optional title prefix for both figures")
    args = p.parse_args()

    tc = None if str(args.tc).lower() == "none" else args.tc
    pulse_end = args.pulse_start + args.pulse_dur

    data = load_csv(args.csv_path)
    os.makedirs(args.outdir, exist_ok=True)

    full_path = os.path.join(args.outdir, "chart_slit_transient_full.png")
    zoom_path = os.path.join(args.outdir, "chart_slit_transient_zoom.png")

    make_full_timeline_plot(data, args.pulse_start, pulse_end, tc, full_path,
                             args.title or "One-Sided Heater: Full Timeline")
    make_zoom_plot(data, args.pulse_start, pulse_end, tc, args.zoom_pre_margin, args.zoom_post_margin, zoom_path,
                    args.title or "One-Sided Heater: Pulse & Redistribution")

    print(f"Wrote {full_path}")
    print(f"Wrote {zoom_path}")


if __name__ == "__main__":
    main()
