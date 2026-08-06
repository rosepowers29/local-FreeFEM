#!/usr/bin/env python3
"""
plot_diagnostics_3d_slit.py

Plotting macro for the lab-instrumentation-style diagnostics export
(diagnostics_3d_slit.csv + diagnostics_positions_3d_slit.csv) from the 3D
slit transient model. Companion to plot_slit_transient.py (which covers
the core Tmax/TmaxLeft/TmaxRight/fracLeft signal) -- this one covers the
full voltage-tap / RTD diagnostics array.

Produces:
  1. chart_diagnostics_voltages.png     -- all voltage-tap channels, one axes
  2. chart_diagnostics_temperatures.png -- all RTD channels, one axes
  3. chart_diagnostics_lr_comparison.png -- left-minus-right differential
     per matched tap/RTD pair -- the actual quench-detection-style signal
     a real differential voltmeter/RTD-pair readout would show.
  4. anim_diagnostics_voltage.gif / anim_diagnostics_temperature.gif --
     animated 2-strip (left-half / right-half) surface projections.

     IMPORTANT honesty note on the animations: these interpolate ALONG x
     from the discrete sensor positions on each side. There is no
     z-resolution beyond the two representative side locations (z=width/4
     and z=3*width/4), so each half-width strip is rendered as spatially
     UNIFORM in z with a hard step at the slit boundary. This faithfully
     represents the actual information content of a sparse real sensor
     array (which is the whole point of this diagnostics work) -- it is
     NOT the full FEM temperature/voltage field, and should not be read
     as one.

Channel positions are read from the metadata file rather than assumed, so
this keeps working if tap/RTD count or spacing changes later.

Usage:
    python3 plot_diagnostics_3d_slit.py diagnostics_3d_slit.csv
    python3 plot_diagnostics_3d_slit.py diagnostics_3d_slit.csv \\
        --positions diagnostics_positions_3d_slit.csv --outdir results/
    python3 plot_diagnostics_3d_slit.py diagnostics_3d_slit.csv --skip-animation
"""

import argparse
import csv
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.animation import FuncAnimation, PillowWriter


# ---------------------------------------------------------------- loading --

def load_diagnostics_csv(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"No data rows in {path}")
    cols = rows[0].keys()
    data = {c: np.array([float(r[c]) for r in rows]) for c in cols}
    return data


def load_positions(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    pos = {}
    for r in rows:
        z_raw = r["z_m"]
        pos[r["channel"]] = {
            "type": r["type"],
            "side": r["side"],
            "x_m": float(r["x_m"]),
            "z_m": None if z_raw in ("n/a", "") else float(z_raw),
        }
    return pos


def channel_groups(positions, prefix_left, prefix_right):
    """(list of (col, x) sorted by x) for the left/right channel families
    matching e.g. prefixes 'V1_'/'V2_' or 'RTD1_'/'RTD2_'."""
    left = sorted(((c, p["x_m"]) for c, p in positions.items() if c.startswith(prefix_left)),
                  key=lambda cx: cx[1])
    right = sorted(((c, p["x_m"]) for c, p in positions.items() if c.startswith(prefix_right)),
                   key=lambda cx: cx[1])
    return left, right


def get_geometry(positions):
    """Derive Lx, width, and the heater/Hall x-location purely from the
    metadata file (no hardcoded geometry)."""
    Lx = positions["V_CL_minus"]["x_m"]
    zL = positions["V1_1"]["z_m"]   # = width/4
    zR = positions["V2_1"]["z_m"]   # = 3*width/4
    width = zL + zR
    xHeater = positions.get("H1", {}).get("x_m")
    return Lx, width, xHeater


# ------------------------------------------------------------------ plots --

def add_pulse_shading(ax, pulse_start, pulse_end, label=None):
    if pulse_start is not None and pulse_end is not None:
        ax.axvspan(pulse_start, pulse_end, color="red", alpha=0.10, label=label)


def make_multiseries_plot(data, channels_left, channels_right, ylabel, title, outpath,
                           pulse_start, pulse_end, unit_scale=1.0, unit_label=""):
    t = data["t"]
    fig, ax = plt.subplots(figsize=(11, 6))

    cmap_l = plt.get_cmap("Reds")
    cmap_r = plt.get_cmap("Blues")
    nL, nR = len(channels_left), len(channels_right)

    for i, (col, _x) in enumerate(channels_left):
        shade = 0.35 + 0.55 * (i / max(nL - 1, 1))
        ax.plot(t, data[col] * unit_scale, color=cmap_l(shade), linewidth=1.2)
    for i, (col, _x) in enumerate(channels_right):
        shade = 0.35 + 0.55 * (i / max(nR - 1, 1))
        ax.plot(t, data[col] * unit_scale, color=cmap_r(shade), linewidth=1.2)

    add_pulse_shading(ax, pulse_start, pulse_end)

    handles = [
        Line2D([0], [0], color="tab:red", lw=2,
               label=f"Left side ({nL} ch., light=low x $\\rightarrow$ dark=high x)"),
        Line2D([0], [0], color="tab:blue", lw=2,
               label=f"Right side ({nR} ch., light=low x $\\rightarrow$ dark=high x)"),
    ]
    if pulse_start is not None:
        handles.append(Line2D([0], [0], color="red", lw=6, alpha=0.15, label="heater pulse"))
    ax.legend(handles=handles, loc="best", fontsize=9)

    ax.set_xlabel("time [s]")
    ax.set_ylabel(f"{ylabel}{unit_label}")
    ax.set_title(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def make_lr_comparison_plot(data, taps_left, taps_right, rtd_left, rtd_right, outpath,
                             pulse_start, pulse_end, volt_unit_scale=1e6, volt_unit_label=" [\u00b5V]"):
    t = data["t"]
    fig, axes = plt.subplots(2, 1, figsize=(11, 9), sharex=True)
    cmap = plt.get_cmap("viridis")

    n = min(len(taps_left), len(taps_right))
    for i in range(n):
        colL, xL = taps_left[i]
        colR, _xR = taps_right[i]
        diff = (data[colL] - data[colR]) * volt_unit_scale
        axes[0].plot(t, diff, color=cmap(i / max(n - 1, 1)), linewidth=1.2,
                     label=f"tap {i+1} (x~{xL*1000:.0f}mm)")
    axes[0].axhline(0, color="gray", linestyle="--", alpha=0.6)
    add_pulse_shading(axes[0], pulse_start, pulse_end)
    axes[0].set_ylabel(f"V_left $-$ V_right{volt_unit_label}")
    axes[0].set_title("Voltage tap differential (left $-$ right), per matched pair", fontsize=11)
    axes[0].legend(fontsize=7, ncol=2, loc="best")

    m = min(len(rtd_left), len(rtd_right))
    for i in range(m):
        colL, xL = rtd_left[i]
        colR, _xR = rtd_right[i]
        diff = data[colL] - data[colR]
        axes[1].plot(t, diff, color=cmap(i / max(m - 1, 1)), linewidth=1.2,
                     label=f"RTD {i+1} (x~{xL*1000:.0f}mm)")
    axes[1].axhline(0, color="gray", linestyle="--", alpha=0.6)
    add_pulse_shading(axes[1], pulse_start, pulse_end)
    axes[1].set_ylabel("T_left $-$ T_right [K]")
    axes[1].set_xlabel("time [s]")
    axes[1].set_title("RTD temperature differential (left $-$ right), per matched pair", fontsize=11)
    axes[1].legend(fontsize=7, ncol=2, loc="best")

    fig.suptitle("Left vs Right Comparison", fontsize=13)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


# -------------------------------------------------------------- animation --

def build_strip_frame(data, row_idx, channels_left, channels_right, Lx, nx=300):
    """Interpolate each side's channel readings across x at one timestep.
    np.interp edge-holds beyond the sensor span (flat extrapolation) --
    there's no information past the outermost sensor, so this is the
    honest choice rather than implying data that doesn't exist."""
    xs_l = np.array([x for _, x in channels_left])
    xs_r = np.array([x for _, x in channels_right])
    vals_l = np.array([data[c][row_idx] for c, _ in channels_left])
    vals_r = np.array([data[c][row_idx] for c, _ in channels_right])
    xgrid = np.linspace(0, Lx, nx)
    grid_l = np.interp(xgrid, xs_l, vals_l)
    grid_r = np.interp(xgrid, xs_r, vals_r)
    return xgrid, grid_l, grid_r


def make_animation(data, channels_left, channels_right, Lx, width, xHeater,
                    title, cbar_label, outpath, pulse_start, pulse_end,
                    unit_scale=1.0, max_frames=150, fps=12, cmap_name="inferno"):
    n = len(data["t"])
    stride = max(1, n // max_frames)
    frame_idx = list(range(0, n, stride))
    if frame_idx[-1] != n - 1:
        frame_idx.append(n - 1)

    nx = 300
    all_l, all_r = [], []
    for ridx in frame_idx:
        _xg, gl, gr = build_strip_frame(data, ridx, channels_left, channels_right, Lx, nx=nx)
        all_l.append(gl * unit_scale)
        all_r.append(gr * unit_scale)
    all_vals = np.concatenate(all_l + all_r)
    vmin, vmax = float(np.min(all_vals)), float(np.max(all_vals))
    if vmin == vmax:
        vmax = vmin + 1e-9

    fig, ax = plt.subplots(figsize=(10, 3.4))
    # Row 0 = left side (lower z), row 1 = right side (upper z). Nearest-
    # neighbor interpolation is essential here -- imshow's default would
    # smoothly blend the two rows across the full width, which would
    # visually paper over the genuine electrical discontinuity at the slit.
    img = np.vstack([all_l[0], all_r[0]])
    im = ax.imshow(img, extent=[0, Lx * 1000, 0, width * 1000], origin="lower",
                    aspect="auto", cmap=cmap_name, vmin=vmin, vmax=vmax,
                    interpolation="nearest")
    ax.axhline(width * 1000 / 2, color="white", linewidth=1.2, linestyle="--")
    ax.text(Lx * 1000 * 0.01, width * 1000 * 0.22, "LEFT (z=w/4)", color="white",
            fontsize=9, fontweight="bold")
    ax.text(Lx * 1000 * 0.01, width * 1000 * 0.72, "RIGHT (z=3w/4)", color="white",
            fontsize=9, fontweight="bold")
    if xHeater is not None:
        ax.axvline(xHeater * 1000, color="cyan", linewidth=1.0, linestyle=":")
        ax.text(xHeater * 1000, width * 1000 * 0.90, "heater/Hall\nx-loc.",
                color="cyan", fontsize=7, ha="center", va="top")
    ax.set_xlabel("x along tape [mm]")
    ax.set_ylabel("z (width) [mm]")
    cbar = fig.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label(cbar_label)
    time_text = ax.text(0.985, 0.94, "", transform=ax.transAxes, ha="right", va="top", fontsize=10,
                        color="white", bbox=dict(boxstyle="round,pad=0.25", fc="black", alpha=0.55, ec="none"))
    ax.set_title(title, fontsize=12)
    fig.tight_layout()

    def update(frame_i):
        frame_img = np.vstack([all_l[frame_i], all_r[frame_i]])
        im.set_data(frame_img)
        t_now = data["t"][frame_idx[frame_i]]
        in_pulse = pulse_start is not None and pulse_start <= t_now <= pulse_end
        time_text.set_text(f"t = {t_now:.3f} s" + ("   [heater ON]" if in_pulse else ""))
        return [im, time_text]

    anim = FuncAnimation(fig, update, frames=len(frame_idx), blit=False)
    anim.save(outpath, writer=PillowWriter(fps=fps))
    plt.close(fig)


# -------------------------------------------------------------------- cli --

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path", help="Path to diagnostics_3d_slit.csv")
    ap.add_argument("--positions", default=None,
                     help="Path to diagnostics_positions_3d_slit.csv (default: alongside csv_path)")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--pulse-start", type=float, default=0.5, help="Heater pulse start time [s]")
    ap.add_argument("--pulse-dur", type=float, default=0.01, help="Heater pulse duration [s]")
    ap.add_argument("--skip-animation", action="store_true", help="Skip the (slower) animated GIFs")
    ap.add_argument("--max-frames", type=int, default=150, help="Max frames sampled for each animation")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--title", default="", help="Optional title prefix for all figures")
    args = ap.parse_args()

    positions_path = args.positions or os.path.join(
        os.path.dirname(os.path.abspath(args.csv_path)) or ".", "diagnostics_positions_3d_slit.csv")
    if not os.path.exists(positions_path):
        raise SystemExit(f"Could not find positions metadata file at {positions_path}. "
                          f"Pass --positions explicitly.")

    data = load_diagnostics_csv(args.csv_path)
    positions = load_positions(positions_path)
    os.makedirs(args.outdir, exist_ok=True)

    taps_left, taps_right = channel_groups(positions, "V1_", "V2_")
    rtd_left, rtd_right = channel_groups(positions, "RTD1_", "RTD2_")

    pulse_start, pulse_end = args.pulse_start, args.pulse_start + args.pulse_dur
    title_prefix = (args.title + ": ") if args.title else ""

    v_path = os.path.join(args.outdir, "chart_diagnostics_voltages.png")
    make_multiseries_plot(data, taps_left, taps_right, "Voltage tap reading",
                          title_prefix + "All Voltage Taps", v_path,
                          pulse_start, pulse_end, unit_scale=1e6, unit_label=" [\u00b5V]")
    print(f"Wrote {v_path}")

    t_path = os.path.join(args.outdir, "chart_diagnostics_temperatures.png")
    make_multiseries_plot(data, rtd_left, rtd_right, "RTD temperature",
                          title_prefix + "All RTD Sensors", t_path,
                          pulse_start, pulse_end, unit_scale=1.0, unit_label=" [K]")
    print(f"Wrote {t_path}")

    lr_path = os.path.join(args.outdir, "chart_diagnostics_lr_comparison.png")
    make_lr_comparison_plot(data, taps_left, taps_right, rtd_left, rtd_right,
                            lr_path, pulse_start, pulse_end)
    print(f"Wrote {lr_path}")

    if not args.skip_animation:
        Lx, width, xHeater = get_geometry(positions)

        va_path = os.path.join(args.outdir, "anim_diagnostics_voltage.gif")
        make_animation(data, taps_left, taps_right, Lx, width, xHeater,
                       title_prefix + "Voltage Tap Evolution (surface projection)",
                       "Voltage [\u00b5V]", va_path, pulse_start, pulse_end,
                       unit_scale=1e6, max_frames=args.max_frames, fps=args.fps, cmap_name="inferno")
        print(f"Wrote {va_path}")

        ta_path = os.path.join(args.outdir, "anim_diagnostics_temperature.gif")
        make_animation(data, rtd_left, rtd_right, Lx, width, xHeater,
                       title_prefix + "RTD Temperature Evolution (surface projection)",
                       "Temperature [K]", ta_path, pulse_start, pulse_end,
                       unit_scale=1.0, max_frames=args.max_frames, fps=args.fps, cmap_name="magma")
        print(f"Wrote {ta_path}")
    else:
        print("Skipped animations (--skip-animation)")


if __name__ == "__main__":
    main()
