#!/usr/bin/env python3
"""
analyze_sweep_hdf5.py -- analysis for a completed run_transient.py/
sweep_transient.py sweep, reading directly from the sweep.h5 handoff file
written by export_sweep_hdf5.py. Works off the HDF5 file alone -- the
per-run runs/<label>/ CSVs don't need to be present locally.

Produces:
  1. Cross-ratio summary plots (new logic, not in either shared plotter):
       chart_summary_fracleft_vs_t.png -- fracLeft(t) overlaid, all ratios
       chart_summary_tmax_vs_t.png     -- Tmax(t) overlaid, all ratios
       chart_summary_final_state.png   -- final |fracLeft-0.5| and final
                                           Tmax vs ratio, colored by outcome
                                           status -- the settled/runaway
                                           boundary in one picture
  2. Per-ratio diagnostic plots, one subdirectory per label, reusing
     ../shared/plot_slit_transient.py and
     ../shared/plot_diagnostics_3d_slit.py's plotting functions directly
     against HDF5-sourced data (same column dicts those scripts build from
     CSV, just sourced from datasets instead of csv.DictReader).

Usage:
  python3 analyze_sweep_hdf5.py                      # runs/sweep.h5, all labels
  python3 analyze_sweep_hdf5.py --h5 runs/sweep.h5 --labels r0p7,r0p95
  python3 analyze_sweep_hdf5.py --with-animation      # also regenerate the
                                                        # per-ratio GIFs (slow)
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import h5py
except ImportError:
    sys.exit("h5py is required -- pip install h5py --break-system-packages")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / ".." / "shared"))
import plot_slit_transient as pst
import plot_diagnostics_3d_slit as pds
import run_transient as rt

PULSE_START = 0.5
PULSE_DUR = 0.01
TC = 90.0

# raw `status` values that need no further interpretation to be meaningful
# on a plot legend -- everything else (reached_end_deviated,
# plateaued_off_parity) means "ran to tEnd still off 50/50" and needs the
# trend classifier to say whether that's asymptotic recovery, a genuine
# new equilibrium, or still getting worse.
OUTCOME_LABELS = {
    "settled": "settled (recovered)",
    "runaway": "runaway",
    "reached_end_no_deviation": "no deviation",
    "crashed": "crashed",
    "init_failed": "init failed",
    "numerical_divergence": "numerical divergence",
    "no_data": "no data",
    "max_steps_exceeded": "max steps exceeded",
}
TREND_LABELS = {
    "converging": "recovering (asymptotic)",
    "plateaued": "plateaued off-parity",
    "diverging": "diverging (pre-runaway)",
}
OUTCOME_COLORS = {
    "settled (recovered)": "tab:green",
    "recovering (asymptotic)": "yellowgreen",
    "plateaued off-parity": "tab:purple",
    "diverging (pre-runaway)": "tab:orange",
    "runaway": "tab:red",
    "no deviation": "tab:blue",
    "crashed": "black",
    "init failed": "black",
    "numerical divergence": "black",
    "no data": "black",
    "max steps exceeded": "gray",
}


def recompute_trend(t, frac_left, trend_window=rt.DEFAULT_TREND_WINDOW, trend_eps=rt.DEFAULT_TREND_EPS):
    # Same classifier run_transient.py uses live, applied after the fact to
    # the trailing trend-window of a completed run's full time series --
    # needed because the trend classifier was added to the wrapper after
    # some of this sweep's runs already finished, so their status.json
    # never recorded it (see CLAUDE.md).
    if len(t) < 2:
        return None
    final_t = t[-1]
    mask = (final_t - t) <= trend_window
    buf = list(zip(t[mask], np.abs(frac_left[mask] - 0.5)))
    return rt.classify_trend(buf, trend_eps)


def effective_trend(run):
    stored = run.get("trend")
    if stored:
        return stored
    return recompute_trend(run["transient"]["t"], run["transient"]["fracLeft"])


def outcome_label(run):
    # `status` alone conflates "still off-parity at tEnd" with three very
    # different physical stories (still asymptotically recovering /
    # stuck at a new off-center equilibrium / trending toward runaway) --
    # this resolves that using the trend classifier before it ever reaches
    # a legend, rather than showing the ambiguous raw status string.
    status = run["status"]
    if status in OUTCOME_LABELS:
        return OUTCOME_LABELS[status]
    if status in ("reached_end_deviated", "plateaued_off_parity"):
        trend = effective_trend(run)
        return TREND_LABELS.get(trend, status)
    return status


# -------------------------------------------------------------- loading --

def load_columns(h5group):
    out = {}
    for col in h5group.keys():
        ds = h5group[col]
        out[col] = ds.asstr()[:] if ds.dtype.kind == "O" else ds[:]
    return out


def load_positions_from_h5(pos_group):
    channels = pos_group["channel"].asstr()[:]
    types = pos_group["type"].asstr()[:]
    sides = pos_group["side"].asstr()[:]
    x_m = pos_group["x_m"][:]
    z_m = pos_group["z_m"][:]
    return {
        str(ch): {
            "type": str(types[i]),
            "side": str(sides[i]),
            "x_m": float(x_m[i]),
            "z_m": None if np.isnan(z_m[i]) else float(z_m[i]),
        }
        for i, ch in enumerate(channels)
    }


def load_runs(h5_path, labels):
    runs = []
    with h5py.File(h5_path, "r") as hf:
        for label in (labels or sorted(hf.keys())):
            g = hf[label]
            if "transient" not in g:
                print(f"skipping {label}: no transient group")
                continue
            run = {"label": label, **dict(g.attrs.items())}
            run["transient"] = load_columns(g["transient"])
            run["diagnostics"] = load_columns(g["diagnostics"]) if "diagnostics" in g else None
            run["positions"] = load_positions_from_h5(g["positions"]) if "positions" in g else None
            runs.append(run)
    return runs


# ---------------------------------------------------------- cross-ratio --

def ratio_color(ratio, ratios):
    lo, hi = min(ratios), max(ratios)
    frac = 0.0 if hi == lo else (ratio - lo) / (hi - lo)
    return plt.get_cmap("plasma")(0.15 + 0.75 * frac)


def make_summary_timeseries(runs, outpath, col, ylabel, title):
    fig, ax = plt.subplots(figsize=(10, 6))
    ratios = [r["ratio"] for r in runs]
    for r in sorted(runs, key=lambda r: r["ratio"]):
        color = ratio_color(r["ratio"], ratios)
        ax.plot(r["transient"]["t"], r["transient"][col], color=color, linewidth=1.4,
                label=f"{r['ratio']:.2f}xIc ({outcome_label(r)})")
    if col == "fracLeft":
        ax.axhline(0.5, color="gray", linestyle="--", alpha=0.5)
    ax.axvspan(PULSE_START, PULSE_START + PULSE_DUR, color="red", alpha=0.08, label="heater pulse")
    ax.set_xlabel("time [s]")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=13)
    ax.legend(loc="best", fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def make_final_state_plot(runs, outpath):
    fig, axes = plt.subplots(2, 1, figsize=(8, 8), sharex=True)
    labels = {r["label"]: outcome_label(r) for r in runs}
    for r in sorted(runs, key=lambda r: r["ratio"]):
        c = OUTCOME_COLORS.get(labels[r["label"]], "gray")
        axes[0].scatter(r["ratio"], abs(r["final_fracLeft"] - 0.5), color=c, s=70, zorder=3)
        axes[1].scatter(r["ratio"], r["final_Tmax"], color=c, s=70, zorder=3)
    axes[0].set_ylabel("final |fracLeft - 0.5|")
    axes[0].axhline(0, color="gray", linestyle=":", alpha=0.5)
    axes[1].set_ylabel("final Tmax [K]")
    axes[1].set_xlabel("transport current ratio (I0 / Ic)")
    present_outcomes = sorted(set(labels.values()))
    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=OUTCOME_COLORS.get(o, "gray"),
                           markersize=8, label=o) for o in present_outcomes]
    axes[0].legend(handles=handles, loc="best", fontsize=8)
    fig.suptitle("Final State vs Transport Current Ratio", fontsize=13)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


# ------------------------------------------------------------- per-ratio --

def per_ratio_plots(run, outdir, with_animation):
    outdir.mkdir(parents=True, exist_ok=True)
    label = run["label"]
    data = run["transient"]
    pulse_end = PULSE_START + PULSE_DUR

    pst.make_full_timeline_plot(data, PULSE_START, pulse_end, TC,
                                 outdir / "chart_slit_transient_full.png", label)
    pst.make_zoom_plot(data, PULSE_START, pulse_end, TC, 0.002, 0.08,
                        outdir / "chart_slit_transient_zoom.png", label)

    diag, positions = run["diagnostics"], run["positions"]
    if diag is None or positions is None:
        print(f"  [{label}] no diagnostics/positions group -- skipping diagnostics plots")
        return

    taps_left, taps_right = pds.channel_groups(positions, "V1_", "V2_")
    rtd_left, rtd_right = pds.channel_groups(positions, "RTD1_", "RTD2_")

    pds.make_multiseries_plot(diag, taps_left, taps_right, "Voltage tap reading",
                               f"{label}: All Voltage Taps", outdir / "chart_diagnostics_voltages.png",
                               PULSE_START, pulse_end, unit_scale=1e6, unit_label=" [µV]")
    pds.make_multiseries_plot(diag, rtd_left, rtd_right, "RTD temperature",
                               f"{label}: All RTD Sensors", outdir / "chart_diagnostics_temperatures.png",
                               PULSE_START, pulse_end, unit_scale=1.0, unit_label=" [K]")

    has_bfield = pds.bfield_is_real(diag)
    bfield_scale, bfield_label = (1.0, " [T]")
    if has_bfield:
        bfield_scale, bfield_label = pds.auto_bfield_unit(diag)
        _Lx, _width, xHeater = pds.get_geometry(positions)
        pds.make_bfield_plot(diag, outdir / "chart_diagnostics_bfield.png", PULSE_START, pulse_end,
                              bfield_scale, bfield_label, xHeater)
    else:
        print(f"  [{label}] H1/H2 still -999 sentinel -- skipping bfield chart (expected, no-B-field workflow)")

    pds.make_lr_comparison_plot(diag, taps_left, taps_right, rtd_left, rtd_right,
                                 outdir / "chart_diagnostics_lr_comparison.png", PULSE_START, pulse_end,
                                 include_bfield=has_bfield, bfield_unit_scale=bfield_scale,
                                 bfield_unit_label=bfield_label)

    if with_animation:
        Lx, width, xHeater = pds.get_geometry(positions)
        pds.make_animation(diag, taps_left, taps_right, Lx, width, xHeater,
                            f"{label}: Voltage Tap Evolution", "Voltage [µV]",
                            outdir / "anim_diagnostics_voltage.gif", PULSE_START, pulse_end, unit_scale=1e6)
        pds.make_animation(diag, rtd_left, rtd_right, Lx, width, xHeater,
                            f"{label}: RTD Temperature Evolution", "Temperature [K]",
                            outdir / "anim_diagnostics_temperature.gif", PULSE_START, pulse_end, unit_scale=1.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--h5", default="runs/sweep.h5", help="Path to the sweep HDF5 file (relative to this script)")
    ap.add_argument("--labels", default=None, help="Comma-separated labels (default: every group in the file)")
    ap.add_argument("--outdir", default="runs/analysis", help="Output directory (relative to this script)")
    ap.add_argument("--with-animation", action="store_true",
                     help="Also regenerate the (slow) per-ratio voltage/temperature GIFs")
    args = ap.parse_args()

    h5_path = Path(args.h5)
    if not h5_path.is_absolute():
        h5_path = SCRIPT_DIR / h5_path
    outdir = Path(args.outdir)
    if not outdir.is_absolute():
        outdir = SCRIPT_DIR / outdir

    if not h5_path.exists():
        sys.exit(f"{h5_path} not found -- run export_sweep_hdf5.py first, or pass --h5")

    labels = args.labels.split(",") if args.labels else None
    runs = load_runs(h5_path, labels)
    if not runs:
        sys.exit("No usable runs found in the HDF5 file")

    outdir.mkdir(parents=True, exist_ok=True)

    print("Cross-ratio summary plots...")
    make_summary_timeseries(runs, outdir / "chart_summary_fracleft_vs_t.png", "fracLeft",
                             "Current fraction on heated side", "fracLeft(t) Across Transport Current Ratios")
    make_summary_timeseries(runs, outdir / "chart_summary_tmax_vs_t.png", "Tmax",
                             "Tmax [K]", "Tmax(t) Across Transport Current Ratios")
    make_final_state_plot(runs, outdir / "chart_summary_final_state.png")
    print(f"  wrote {outdir}/chart_summary_*.png")

    print("Per-ratio diagnostic plots...")
    for run in runs:
        print(f"  [{run['label']}]")
        per_ratio_plots(run, outdir / run["label"], args.with_animation)

    print(f"Done. Output under {outdir}/")


if __name__ == "__main__":
    main()
