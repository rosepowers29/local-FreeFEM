#!/usr/bin/env python3
"""
plot_diagnostics_layout_3d_slit.py

Static schematic diagram of the diagnostics board layout on the 3D slit
tape -- a matplotlib recreation of the hand-drawn instrumentation diagram
(voltage taps / RTDs / Hall probes / spot heater), built directly from
diagnostics_positions_3d_slit.csv so it automatically stays in sync if
tap/RTD count, spacing, or count ever changes.

This is a LAYOUT diagram only -- no time-series data involved (see
plot_diagnostics_3d_slit.py for that). Left/right sensor rows are drawn
above/below a stylized tape body for legibility, matching the style of
the original hand-drawn diagram; this is a visual convention, not a
claim about physical z-position (both rows sit on the same physical
tape, at z=width/4 and z=3*width/4 respectively -- see the dashed
centerline for the true slit location).

Two things the position metadata does NOT encode, so they're CLI options
with the current model's values as defaults:
  - the slit's x-extent (--slit-start / --slit-end)
  - which side currently has a real, wired-up heater vs. a reserved-but-
    not-yet-implemented position (--heater-implemented-side). As of this
    writing only the LEFT side has an actual heater in the model; the
    Hall probe positions are symmetric placeholders on both sides.

Usage:
    python3 plot_diagnostics_layout_3d_slit.py diagnostics_positions_3d_slit.csv
    python3 plot_diagnostics_layout_3d_slit.py diagnostics_positions_3d_slit.csv \\
        --outpath layout.png --heater-implemented-side left
"""

import argparse
import csv
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch
from matplotlib.lines import Line2D


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


def channels_of(positions, type_name, side):
    return sorted((p["x_m"] for c, p in positions.items()
                   if p["type"] == type_name and p["side"] == side))


def get_geometry(positions):
    Lx = positions["V_CL_minus"]["x_m"]
    zL = positions["V1_1"]["z_m"]
    zR = positions["V2_1"]["z_m"]
    width = zL + zR
    xHeater = positions.get("H1", {}).get("x_m")
    return Lx, width, xHeater


def draw_layout(positions, outpath, slit_start, slit_end, heater_side, title):
    Lx, width, xHeater = get_geometry(positions)

    taps_left = channels_of(positions, "voltage_tap", "left")
    taps_right = channels_of(positions, "voltage_tap", "right")
    rtd_left = channels_of(positions, "temperature_rtd", "left")
    rtd_right = channels_of(positions, "temperature_rtd", "right")

    # ---- stylized vertical layout (schematic, not to physical scale) ----
    tape_half_h = 0.6
    row_y = 1.15            # tap/RTD row, offset above/below the tape body
    hall_y = row_y + 0.45    # Hall probe row, further out
    heater_y = hall_y + 0.80 # heater row, furthest out
    tap_w, tap_h = Lx * 0.006, 0.55
    rtd_w, rtd_h = Lx * 0.0012, 0.30
    hall_w, hall_h = Lx * 0.018, 0.16
    heater_w, heater_h = Lx * 0.02, 0.32

    fig, ax = plt.subplots(figsize=(13, 6.2))

    # tape body
    ax.add_patch(Rectangle((0, -tape_half_h), Lx, 2 * tape_half_h,
                           facecolor="#e8935a", edgecolor="#a85f2f", linewidth=1.2, zorder=1))

    # slit
    ax.plot([slit_start, slit_end], [0, 0], color="#bcd7e6", linewidth=1.6, zorder=2)
    ax.annotate("Laser Slit", xy=(slit_start + (slit_end - slit_start) * 0.12, 0.05),
               xytext=(slit_start - Lx * 0.06, tape_half_h + 1.7),
               arrowprops=dict(arrowstyle="->", color="#4a90b8", lw=1.2),
               color="#2f6f8f", fontsize=10, fontweight="bold")

    # current leads
    lead_w = Lx * 0.035
    ax.add_patch(Rectangle((-lead_w, -0.12), lead_w, 0.24, facecolor="#f4d35e",
                           edgecolor="#8a7a1e", zorder=1))
    ax.text(-lead_w * 1.3, 0, "V_CL+", ha="right", va="center", fontsize=9, fontweight="bold")
    ax.add_patch(Rectangle((Lx, -0.12), lead_w, 0.24, facecolor="#f4d35e",
                           edgecolor="#8a7a1e", zorder=1))
    ax.text(Lx + lead_w * 1.3, 0, "V_CL-", ha="left", va="center", fontsize=9, fontweight="bold")

    def draw_row(sign, taps, rtds, hall_x, heater_implemented, row_label):
        y_row = sign * row_y
        # connecting line from tape edge to row (visual only)
        for x in taps:
            ax.plot([x, x], [0, y_row], color="#cccccc", linewidth=0.5, zorder=0)
        # voltage taps
        for x in taps:
            ax.add_patch(Rectangle((x - tap_w / 2, y_row - tap_h / 2), tap_w, tap_h,
                                   facecolor="#f7e017", edgecolor="#9c8a00", zorder=3))
        if taps:
            ax.text(taps[0], y_row + (tap_h / 2 + 0.25) * sign, row_label,
                    ha="left", va="bottom" if sign > 0 else "top", fontsize=9,
                    color="#333333", fontweight="bold")
        # RTDs nested between taps
        for x in rtds:
            ax.add_patch(Rectangle((x - rtd_w / 2, y_row - rtd_h / 2), rtd_w, rtd_h,
                                   facecolor="#7a1f1f", edgecolor="#3d0f0f", zorder=4))
        # Hall probe (reserved, not wired to B-field yet)
        if hall_x is not None:
            y_hall = sign * hall_y
            ax.add_patch(Rectangle((hall_x - hall_w / 2, y_hall - hall_h / 2), hall_w, hall_h,
                                   facecolor="#2e7d32", edgecolor="#1b4d1e", zorder=5))
            ax.text(hall_x, y_hall + 0.20 * sign, f"H_{1 if sign > 0 else 2}",
                    ha="center", va="bottom" if sign > 0 else "top", fontsize=9, color="#1b4d1e")
        # heater (implemented vs reserved)
        if hall_x is not None:
            y_heat = sign * heater_y
            label = f"SP_{1 if sign > 0 else 2} " + ("(implemented)" if heater_implemented else "(reserved)")
            if heater_implemented:
                ax.add_patch(Rectangle((hall_x - heater_w / 2, y_heat - heater_h / 2), heater_w, heater_h,
                                       facecolor="#29b6d8", edgecolor="#0e5c70", zorder=5))
            else:
                ax.add_patch(Rectangle((hall_x - heater_w / 2, y_heat - heater_h / 2), heater_w, heater_h,
                                       facecolor="none", edgecolor="#29b6d8", linestyle="--",
                                       linewidth=1.3, zorder=5))
            ax.text(hall_x, y_heat + 0.30 * sign, label,
                    ha="center", va="bottom" if sign > 0 else "top", fontsize=8, color="#0e5c70")

    draw_row(+1, taps_left, rtd_left, xHeater, heater_side == "left", "V1_1-10  (left, z=w/4)")
    draw_row(-1, taps_right, rtd_right, xHeater, heater_side == "right", "V2_1-10  (right, z=3w/4)")

    # legend
    handles = [
        Rectangle((0, 0), 1, 1, facecolor="#f7e017", edgecolor="#9c8a00", label="Voltage Tap [1 wire]"),
        Rectangle((0, 0), 1, 1, facecolor="#2e7d32", edgecolor="#1b4d1e", label="Hall Probe [4 wire] (reserved, not yet wired)"),
        Rectangle((0, 0), 1, 1, facecolor="#7a1f1f", edgecolor="#3d0f0f", label="PT-1000 RTD [2 wire]"),
        Rectangle((0, 0), 1, 1, facecolor="#29b6d8", edgecolor="#0e5c70", label="Spot Heater [2 wire] (implemented)"),
        Rectangle((0, 0), 1, 1, facecolor="none", edgecolor="#29b6d8", linestyle="--", label="Spot Heater (reserved / not yet implemented)"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.08),
             ncol=3, fontsize=9, frameon=False)

    ax.set_xlim(-Lx * 0.09, Lx * 1.09)
    ax.set_ylim(-heater_y - heater_h / 2 - 1.0, heater_y + heater_h / 2 + 1.6)
    ax.set_yticks([])
    ax.set_xlabel("x along tape [mm]")
    xt = ax.get_xticks()
    ax.set_xticks(xt)
    ax.set_xticklabels([f"{v*1000:.0f}" for v in xt])
    ax.set_xlim(-Lx * 0.09, Lx * 1.09)
    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.set_title(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("positions_csv", help="Path to diagnostics_positions_3d_slit.csv")
    ap.add_argument("--outpath", default="diagnostics_layout.png")
    ap.add_argument("--slit-start", type=float, default=0.010,
                    help="Slit x-start [m] (not in the metadata file, defaults to current model value)")
    ap.add_argument("--slit-end", type=float, default=0.190,
                    help="Slit x-end [m] (not in the metadata file, defaults to current model value)")
    ap.add_argument("--heater-implemented-side", choices=["left", "right"], default="left",
                    help="Which side currently has a real heater wired up (default: left, matching "
                         "step_3d_slit_transient.edp as of this writing)")
    ap.add_argument("--title", default="3D Slit Tape -- Diagnostics Board Layout")
    args = ap.parse_args()

    positions = load_positions(args.positions_csv)
    draw_layout(positions, args.outpath, args.slit_start, args.slit_end,
               args.heater_implemented_side, args.title)
    print(f"Wrote {args.outpath}")


if __name__ == "__main__":
    main()
