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
       chart_summary_peak_tmax.png     -- peak Tmax (max over the whole
                                           run, not just the final row) vs
                                           ratio -- meant to replace eyeballing
                                           chart_summary_tmax_vs_t.png once a
                                           sweep has too many ratios for
                                           overlaid line plots to stay legible
       chart_summary_peak_voltage.png  -- peak V_CL_minus (total end-to-end
                                           tape voltage) vs ratio
       chart_summary_recovery_margin.png -- time from heater-pulse-end to
                                           Tmax's own turning point vs ratio,
                                           for runs that actually turn over
                                           (skips true runaways -- there's no
                                           turning point to measure)
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

PULSE_START = 0.5   # fallback only -- see detect_pulse_start()
PULSE_DUR = 0.01    # fixed regardless of ramp scenario (tPulseDur in the .edp)
TC = 90.0


def detect_pulse_start(transient, default=PULSE_START):
    # Pulse start == Tramp, which is fixed at 0.5s only when --ramp-rate
    # is unused -- a slow-ramp run (--ramp-rate 20, say) has a different
    # Tramp per ratio (I0Target/ramp_rate), so a hardcoded PULSE_START
    # would shade the wrong region entirely for those runs. Detected
    # directly from the run's own I0(t) plateau instead of assumed, so
    # this stays correct for both the fixed- and variable-ramp scenarios
    # without needing to know which one produced this data.
    t, I0 = transient.get("t"), transient.get("I0")
    if t is None or I0 is None or len(I0) == 0:
        return default
    i0max = np.max(I0)
    if i0max <= 0:
        return default
    idx = int(np.argmax(I0 >= 0.999 * i0max))
    return float(t[idx])

# raw `status` values that need no further interpretation to be meaningful
# on a plot legend -- everything else (reached_end_deviated,
# plateaued_off_parity) means "ran to tEnd still off 50/50" and needs the
# trend classifier to say whether that's asymptotic recovery, a genuine
# new equilibrium, or still getting worse.
OUTCOME_LABELS = {
    "settled": "settled (recovered)",
    "runaway": "runaway",
    "runaway_before_pulse": "runaway (before pulse)",
    "reached_end_no_deviation": "no deviation",
    "crashed": "crashed",
    "init_failed": "init failed",
    "numerical_divergence": "numerical divergence",
    "no_data": "no data",
    "max_steps_exceeded": "max steps exceeded",
}
# Statuses meaning "the process never produced trustworthy physics" --
# e.g. "crashed" was seen for the first time in a 202-ratio batch that
# pushed ratio up to 1.9xIc: two runs (r1p36, r1p83) hit a real numerical
# overflow (Tmax finite but ~1e65-1e228 -- floating-point garbage from an
# unstable solve, not real physics) in the last row(s) written before
# FreeFEM's own exit code went nonzero. That garbage was still sitting in
# the raw transient CSV, so a cross-ratio *time-series* plot (which reads
# the raw arrays directly, unlike outcome_label()) rendered it and blew
# the shared y-axis out to 10^239, flattening every real ratio's curve
# into a flat line near the bottom. Filtered out of cross-ratio summary
# plots entirely -- per-ratio plots still run for these labels, since a
# crashed run's last real rows are legitimate debugging information.
NO_TRUSTWORTHY_PHYSICS = {"crashed", "init_failed", "numerical_divergence", "no_data"}


def has_trustworthy_physics(run):
    return run["status"] not in NO_TRUSTWORTHY_PHYSICS


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
    "runaway (before pulse)": "darkorange",
    "falsely settled (still runaway)": "darkred",
    "falsely recovering (still runaway)": "firebrick",
    "no deviation": "tab:blue",
    "crashed": "black",
    "init failed": "black",
    "numerical divergence": "black",
    "no data": "black",
    "max steps exceeded": "gray",
}

# Real bug (caught by inspecting a "settled" result's own Tmax, ratio=0.91
# in the 20A/s ramp sweep): run_transient.py's settled check used to look
# only at fracLeft, so a symmetric full-tape runaway (both sides going
# resistive together, re-symmetrizing the current split while Tmax climbs
# unchecked) could pass it. Fixed in run_transient.py going forward
# (settle_tmax_max, default 90.0 == Tc) -- this constant lets already-
# collected "settled" results from before that fix get relabeled here too,
# rather than either trusting a known-wrong label or silently discarding
# old data.
SETTLE_TMAX_SAFE = rt.DEFAULT_SETTLE_TMAX_MAX


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


# Second instance of the exact same confound that produced the "settled"
# bug (see SETTLE_TMAX_SAFE above): classify_trend() only ever looks at
# |fracLeft-0.5|, so a symmetric full-tape runaway re-symmetrizing the
# current split reads as "converging" (deviation shrinking) even while
# Tmax is still climbing hundreds of K/s. Caught by direct inspection of
# the granular 0.90-0.911 sweep: r0p904-r0p911 all carry
# status=reached_end_deviated / trend=converging (-> "recovering
# (asymptotic)") despite Tmax still rising at ~645-652 K/s at the last
# recorded row -- not remotely recovering. classify_trend() is reused
# here on raw Tmax instead of |fracLeft-0.5|; its slope-sign convention
# (positive slope -> "diverging") happens to mean exactly the right thing
# for Tmax too (still heating up), no change to the function needed.
def recompute_tmax_trend(t, tmax, trend_window=rt.DEFAULT_TREND_WINDOW, trend_eps=rt.DEFAULT_TREND_EPS):
    if len(t) < 2:
        return None
    final_t = t[-1]
    mask = (final_t - t) <= trend_window
    buf = list(zip(t[mask], tmax[mask]))
    return rt.classify_trend(buf, trend_eps)


def outcome_label(run):
    # `status` alone conflates "still off-parity at tEnd" with three very
    # different physical stories (still asymptotically recovering /
    # stuck at a new off-center equilibrium / trending toward runaway) --
    # this resolves that using the trend classifier before it ever reaches
    # a legend, rather than showing the ambiguous raw status string.
    status = run["status"]
    if status == "settled" and run.get("final_Tmax", 0.0) >= SETTLE_TMAX_SAFE:
        return "falsely settled (still runaway)"
    if status in OUTCOME_LABELS:
        return OUTCOME_LABELS[status]
    if status in ("reached_end_deviated", "plateaued_off_parity"):
        trend = effective_trend(run)
        if (trend in ("converging", "plateaued")
                and run.get("final_Tmax", 0.0) >= SETTLE_TMAX_SAFE
                and recompute_tmax_trend(run["transient"]["t"], run["transient"]["Tmax"]) == "diverging"):
            return "falsely recovering (still runaway)"
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


# Above this many runs, a one-legend-entry-per-ratio legend (the original
# design, fine for the 6- and 20-ratio sweeps this was built against)
# stops being legend-sized and starts being large enough to cover the
# entire plot -- confirmed visually on the 108-ratio granular sweep, where
# it rendered as a multi-column block blotting out the whole figure. Past
# this threshold, swap to a colorbar (ratio is already continuously color-
# mapped via ratio_color/plasma, so this loses no information) and skip
# the per-line legend entirely.
MANY_RUNS_LEGEND_CUTOFF = 20


def compute_zoom_xlim(runs, pre_margin=0.5, post_margin=0.5):
    # The flat pre-pulse soak (everything sitting at ~77-80K) can eat most
    # of a fixed-width time axis once ratios span a wide range (pulse start
    # itself varies by ratio once --ramp-rate is used, e.g. 10.9s-23.3s
    # across the 0.7-1.5xIc granular sweep) -- cropping to just before the
    # earliest pulse through just after the latest run's last recorded row
    # stretches the actual rise/fall dynamics across the full plot width
    # instead of squeezing them into a corner. Computed from the data
    # rather than hardcoded so this stays correct for any sweep's actual
    # ramp/pulse timing, not just this one.
    pulse_starts = [detect_pulse_start(r["transient"]) for r in runs]
    final_ts = [r["transient"]["t"][-1] for r in runs]
    return max(0.0, min(pulse_starts) - pre_margin), max(final_ts) + post_margin


def make_summary_timeseries(runs, outpath, col, ylabel, title, log_y=False, xlim=None):
    fig, ax = plt.subplots(figsize=(10, 6))
    ratios = [r["ratio"] for r in runs]
    many_runs = len(runs) > MANY_RUNS_LEGEND_CUTOFF
    for r in sorted(runs, key=lambda r: r["ratio"]):
        color = ratio_color(r["ratio"], ratios)
        label = None if many_runs else f"{r['ratio']:.2f}xIc ({outcome_label(r)})"
        ax.plot(r["transient"]["t"], r["transient"][col], color=color, linewidth=1.4,
                label=label)
    if col == "fracLeft":
        ax.axhline(0.5, color="gray", linestyle="--", alpha=0.5)
    # A single shared shaded band only makes sense if every ratio's pulse
    # actually fires at the same time -- true for the fixed-Tramp scenario,
    # false once --ramp-rate varies Tramp (and therefore the pulse time)
    # per ratio. Drawing one band in that case would shade the wrong
    # region for every ratio except whichever's pulse happens to match it.
    pulse_starts = [detect_pulse_start(r["transient"]) for r in runs]
    if max(pulse_starts) - min(pulse_starts) < 1e-6:
        ax.axvspan(pulse_starts[0], pulse_starts[0] + PULSE_DUR, color="red", alpha=0.08,
                   label="heater pulse")
    else:
        print(f"  (pulse timing varies by ratio in this sweep -- not shown as a "
              f"shared band on {outpath.name})")
    ax.set_xlabel("time [s]")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=13)
    if log_y:
        ax.set_yscale("log")
    if xlim:
        ax.set_xlim(xlim)
    if many_runs:
        sm = plt.cm.ScalarMappable(cmap="plasma",
                                    norm=plt.Normalize(vmin=min(ratios), vmax=max(ratios)))
        sm.set_array([])
        fig.colorbar(sm, ax=ax, label="transport current ratio (I0 / Ic)")
    else:
        ax.legend(loc="best", fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def _final_state_values(r):
    # export_sweep_hdf5.py writes a missing status.json field (e.g. a
    # "crashed" run's final_Tmax/final_fracLeft, never recorded because
    # it died before finalize()) as "" -- h5py attrs have no None -- so
    # this can't just be assumed numeric. Returns None if either value
    # isn't usable, rather than letting a bad subtraction crash the whole
    # summary plot over one run's missing data.
    frac, tmax = r.get("final_fracLeft"), r.get("final_Tmax")
    try:
        return float(frac), float(tmax)
    except (TypeError, ValueError):
        return None


def make_final_state_plot(runs, outpath):
    fig, axes = plt.subplots(2, 1, figsize=(8, 8), sharex=True)
    labels = {r["label"]: outcome_label(r) for r in runs}
    skipped = []
    for r in sorted(runs, key=lambda r: r["ratio"]):
        vals = _final_state_values(r)
        if vals is None:
            skipped.append(r["label"])
            continue
        frac, tmax = vals
        c = OUTCOME_COLORS.get(labels[r["label"]], "gray")
        axes[0].scatter(r["ratio"], abs(frac - 0.5), color=c, s=70, zorder=3)
        axes[1].scatter(r["ratio"], tmax, color=c, s=70, zorder=3)
    if skipped:
        print(f"  chart_summary_final_state.png: skipping {len(skipped)} run(s) with no "
              f"final state recorded (status={{{', '.join(sorted({labels[l] for l in skipped}))}}}): "
              f"{', '.join(skipped)}")
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

def _scatter_by_outcome(runs, outpath, value_fn, ylabel, title, skip_note=None):
    # Shared scaffold for the three ratio-vs-scalar scatter plots below --
    # same colored-by-outcome-status convention as make_final_state_plot,
    # just one point per run instead of two. value_fn returns None to skip
    # a run (e.g. no diagnostics group, or no post-pulse turning point);
    # skipped runs are reported by outcome, not silently dropped, matching
    # this file's existing skip-reporting convention (see
    # make_final_state_plot above).
    fig, ax = plt.subplots(figsize=(9, 6))
    labels = {r["label"]: outcome_label(r) for r in runs}
    skipped = []
    for r in sorted(runs, key=lambda r: r["ratio"]):
        val = value_fn(r)
        if val is None:
            skipped.append(r["label"])
            continue
        c = OUTCOME_COLORS.get(labels[r["label"]], "gray")
        ax.scatter(r["ratio"], val, color=c, s=45, zorder=3)
    if skipped:
        skipped_outcomes = sorted({labels[l] for l in skipped})
        note = f" ({skip_note})" if skip_note else ""
        print(f"  {outpath.name}: skipping {len(skipped)} run(s){note} "
              f"(status={{{', '.join(skipped_outcomes)}}}): {', '.join(skipped)}")
    ax.set_xlabel("transport current ratio (I0 / Ic)")
    ax.set_ylabel(ylabel)
    present_outcomes = sorted({v for k, v in labels.items() if k not in skipped})
    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=OUTCOME_COLORS.get(o, "gray"),
                           markersize=8, label=o) for o in present_outcomes]
    if handles:
        ax.legend(handles=handles, loc="best", fontsize=8)
    ax.set_title(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def make_peak_tmax_scatter(runs, outpath):
    def peak_tmax(r):
        tmax = r["transient"].get("Tmax")
        return None if tmax is None or len(tmax) == 0 else float(np.max(tmax))
    _scatter_by_outcome(runs, outpath, peak_tmax, "peak Tmax [K]",
                        "Peak Tmax vs Transport Current Ratio")


def make_peak_voltage_scatter(runs, outpath):
    # V_CL_minus: cumulative end-to-end tape voltage (see
    # diagnostics_3d_slit.idp) -- the single scalar a real quench-detection
    # system would actually watch, as opposed to any one local tap. Raw
    # value is SI volts; *1e6 matches plot_diagnostics_3d_slit.py's own
    # display convention (unit_scale=1e6, " [µV]") for every other
    # voltage chart in this repo.
    def peak_voltage(r):
        diag = r.get("diagnostics")
        if not diag or "V_CL_minus" not in diag or len(diag["V_CL_minus"]) == 0:
            return None
        return float(np.max(diag["V_CL_minus"])) * 1e6
    _scatter_by_outcome(runs, outpath, peak_voltage, "peak V_CL_minus [µV]",
                        "Peak End-to-End Voltage vs Transport Current Ratio",
                        skip_note="no diagnostics group")


# Minimum decline (K) from a post-pulse Tmax peak to the run's last
# recorded value before calling it a genuine reversal, rather than noise
# or a peak that just happens to sit at the very last recorded row (i.e.
# the run was cut off, possibly still climbing, before any real turnover).
REVERSAL_MIN_DECLINE_K = 0.5


def detect_tmax_reversal(transient, pulse_end):
    t, tmax = transient.get("t"), transient.get("Tmax")
    if t is None or tmax is None:
        return None
    mask = t >= pulse_end
    if mask.sum() < 3:   # need at least a peak and a bit of decline after it
        return None
    t_post, tmax_post = t[mask], tmax[mask]
    peak_idx = int(np.argmax(tmax_post))
    if peak_idx == len(tmax_post) - 1:
        return None   # peak is the last recorded row -- still climbing (or cut off), no turnover yet
    decline = tmax_post[peak_idx] - tmax_post[-1]
    if decline < REVERSAL_MIN_DECLINE_K:
        return None
    return float(t_post[peak_idx] - pulse_end)


def make_recovery_margin_scatter(runs, outpath):
    def margin(r):
        pulse_end = detect_pulse_start(r["transient"]) + PULSE_DUR
        return detect_tmax_reversal(r["transient"], pulse_end)
    _scatter_by_outcome(runs, outpath, margin, "pulse-end -> Tmax turnover [s]",
                        "Recovery Time Margin vs Transport Current Ratio\n"
                        "(runs with no post-pulse Tmax turnover excluded)",
                        skip_note="no post-pulse Tmax turnover (true runaway, or cut off while still climbing)")


def per_ratio_plots(run, outdir, with_animation):
    outdir.mkdir(parents=True, exist_ok=True)
    label = run["label"]
    data = run["transient"]
    pulse_start = detect_pulse_start(data)
    pulse_end = pulse_start + PULSE_DUR

    pst.make_full_timeline_plot(data, pulse_start, pulse_end, TC,
                                 outdir / "chart_slit_transient_full.png", label)
    pst.make_zoom_plot(data, pulse_start, pulse_end, TC, 0.002, 0.08,
                        outdir / "chart_slit_transient_zoom.png", label)

    diag, positions = run["diagnostics"], run["positions"]
    if diag is None or positions is None:
        print(f"  [{label}] no diagnostics/positions group -- skipping diagnostics plots")
        return

    taps_left, taps_right = pds.channel_groups(positions, "V1_", "V2_")
    rtd_left, rtd_right = pds.channel_groups(positions, "RTD1_", "RTD2_")

    pds.make_multiseries_plot(diag, taps_left, taps_right, "Voltage tap reading",
                               f"{label}: All Voltage Taps", outdir / "chart_diagnostics_voltages.png",
                               pulse_start, pulse_end, unit_scale=1e6, unit_label=" [µV]")
    pds.make_multiseries_plot(diag, rtd_left, rtd_right, "RTD temperature",
                               f"{label}: All RTD Sensors", outdir / "chart_diagnostics_temperatures.png",
                               pulse_start, pulse_end, unit_scale=1.0, unit_label=" [K]")

    has_bfield = pds.bfield_is_real(diag)
    bfield_scale, bfield_label = (1.0, " [T]")
    if has_bfield:
        bfield_scale, bfield_label = pds.auto_bfield_unit(diag)
        _Lx, _width, xHeater = pds.get_geometry(positions)
        pds.make_bfield_plot(diag, outdir / "chart_diagnostics_bfield.png", pulse_start, pulse_end,
                              bfield_scale, bfield_label, xHeater)
    else:
        print(f"  [{label}] H1/H2 still -999 sentinel -- skipping bfield chart (expected, no-B-field workflow)")

    pds.make_lr_comparison_plot(diag, taps_left, taps_right, rtd_left, rtd_right,
                                 outdir / "chart_diagnostics_lr_comparison.png", pulse_start, pulse_end,
                                 include_bfield=has_bfield, bfield_unit_scale=bfield_scale,
                                 bfield_unit_label=bfield_label)

    if with_animation:
        Lx, width, xHeater = pds.get_geometry(positions)
        pds.make_animation(diag, taps_left, taps_right, Lx, width, xHeater,
                            f"{label}: Voltage Tap Evolution", "Voltage [µV]",
                            outdir / "anim_diagnostics_voltage.gif", pulse_start, pulse_end, unit_scale=1e6)
        pds.make_animation(diag, rtd_left, rtd_right, Lx, width, xHeater,
                            f"{label}: RTD Temperature Evolution", "Temperature [K]",
                            outdir / "anim_diagnostics_temperature.gif", pulse_start, pulse_end, unit_scale=1.0)


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
    trustworthy = [r for r in runs if has_trustworthy_physics(r)]
    excluded = [r["label"] for r in runs if r not in trustworthy]
    if excluded:
        print(f"  excluding {len(excluded)} run(s) with no trustworthy physics "
              f"(status in {sorted(NO_TRUSTWORTHY_PHYSICS)}): {', '.join(excluded)}")
    make_summary_timeseries(trustworthy, outdir / "chart_summary_fracleft_vs_t.png", "fracLeft",
                             "Current fraction on heated side", "fracLeft(t) Across Transport Current Ratios")
    make_summary_timeseries(trustworthy, outdir / "chart_summary_tmax_vs_t.png", "Tmax",
                             "Tmax [K]", "Tmax(t) Across Transport Current Ratios")
    # log-y: recoveries (Tmax drifting a few K around ~80K) and runaways
    # (Tmax climbing hundreds of K/s up past 1000K) sit at wildly different
    # scales -- linear axis on chart_summary_tmax_vs_t.png flattens every
    # recovering ratio into an indistinguishable line near the bottom. Log
    # scale keeps both regimes' shapes visible in the same window.
    make_summary_timeseries(trustworthy, outdir / "chart_summary_tmax_vs_t_log.png", "Tmax",
                             "Tmax [K] (log scale)", "Tmax(t) Across Transport Current Ratios (log scale)",
                             log_y=True)
    zoom_xlim = compute_zoom_xlim(trustworthy)
    make_summary_timeseries(trustworthy, outdir / "chart_summary_tmax_vs_t_zoom.png", "Tmax",
                             "Tmax [K]", "Tmax(t) Across Transport Current Ratios (zoomed)",
                             xlim=zoom_xlim)
    make_final_state_plot(trustworthy, outdir / "chart_summary_final_state.png")
    make_peak_tmax_scatter(trustworthy, outdir / "chart_summary_peak_tmax.png")
    make_peak_voltage_scatter(trustworthy, outdir / "chart_summary_peak_voltage.png")
    make_recovery_margin_scatter(trustworthy, outdir / "chart_summary_recovery_margin.png")
    print(f"  wrote {outdir}/chart_summary_*.png")

    print("Per-ratio diagnostic plots...")
    for run in runs:
        print(f"  [{run['label']}]")
        per_ratio_plots(run, outdir / run["label"], args.with_animation)

    print(f"Done. Output under {outdir}/")


if __name__ == "__main__":
    main()
