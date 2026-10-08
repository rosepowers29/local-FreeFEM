#!/usr/bin/env python3
"""
analyze_sweep_hdf5.py -- analysis for a completed run_bfield_transient.py
sweep, reading directly from the sweep.h5 handoff file written by
export_sweep_hdf5.py. Ported from electrothermal/analyze_sweep_hdf5.py --
same cross-ratio summary logic and per-ratio plotting, adapted for this
workflow's own status taxonomy (no prePulse/runaway_before_pulse split;
has the new wall_budget_exceeded status) and with one workflow-specific
addition (peak Picard-iteration-count vs ratio -- electrothermal has no
analog since it has no self-consistent B<->E solve).

Produces:
  1. Cross-ratio summary plots (same set electrothermal's version has,
     plus chart_summary_peak_picard_iters.png and the B-field pair below):
       chart_summary_fracleft_vs_t.png
       chart_summary_tmax_vs_t.png / _log.png / _zoom.png
       chart_summary_final_state.png
       chart_summary_peak_tmax.png
       chart_summary_peak_voltage.png
       chart_summary_peak_segment_voltage.png
       chart_summary_recovery_margin.png
       chart_summary_peak_picard_iters.png  -- NEW: peak picardIters (max
         over the whole run) vs ratio, colored by outcome. Runs with no
         picardIters column (the 4 legacy pre-self-consistent runs: r0p7,
         r0p7-aniso, r1p2, r1p2-aniso) are skipped, not zero-filled.
       chart_summary_peak_bfield.png  -- NEW, Bfield-specific: peak |B|
         (max of |H1|,|H2| over the whole run, the self-field at the
         heater/Hall x-location) vs ratio, colored by outcome.
       chart_summary_bfield_vs_t.png / _log.png  -- NEW, Bfield-specific:
         max(|H1|,|H2|)(t) across ratios, analogous to the Tmax(t)
         summary pair but sourced from the diagnostics group (not
         transient) since H1/H2 live there. Runs with no real B-field
         data (diagnostics missing, or the -999 pre-B-field sentinel)
         are skipped, not zero-filled -- see pds.bfield_is_real().
  2. Per-ratio diagnostic plots, one subdirectory per label, reusing
     ../shared/plot_slit_transient.py and
     ../shared/plot_diagnostics_3d_slit.py directly against HDF5-sourced
     data.

IMPORTANT: a two-population sweep (heater on vs. heater off) is handled
at EXPORT time, not here -- summary plots are ALWAYS built from every
label in the given --h5 file (never --labels-filtered, same gotcha
electrothermal's version documents), so comparing the two populations
means exporting two separate .h5 files (one per population) and running
this script once per file, not passing --labels here.

Usage:
  python3 analyze_sweep_hdf5.py                      # runs/sweep.h5, all labels
  python3 analyze_sweep_hdf5.py --h5 runs/sweep_heater.h5 --summary-only
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
import run_bfield_transient as rt

PULSE_START = 0.5   # fallback only -- see detect_pulse_start()
PULSE_DUR = 0.01    # fixed regardless of ramp scenario (tPulseDur in the .edp)
TC = 90.0


def detect_pulse_start(transient, default=PULSE_START):
    # Pulse start == Tramp, which is fixed at 0.5s only when --ramp-rate
    # is unused -- a slow-ramp run has a different Tramp per ratio, so a
    # hardcoded PULSE_START would shade the wrong region for those runs.
    # Detected directly from the run's own I0(t) plateau instead of
    # assumed. Returns None if no genuine plateau was ever reached (cut
    # off by tmaxcutoff while still ramping) -- callers must handle None.
    t, I0 = transient.get("t"), transient.get("I0")
    if t is None or I0 is None or len(I0) == 0:
        return default
    i0max = np.max(I0)
    if i0max <= 0:
        return default
    idx = int(np.argmax(I0 >= 0.999 * i0max))
    if idx == len(I0) - 1:
        return None
    return float(t[idx])

# raw `status` values that need no further interpretation to be meaningful
# on a plot legend -- everything else (reached_end_deviated,
# plateaued_off_parity) means "ran to tEnd still off 50/50" and needs the
# trend classifier to say whether that's asymptotic recovery, a genuine
# new equilibrium, or still getting worse. No "runaway_before_pulse" here
# (not ported to this workflow -- see CLAUDE.md); "wall_budget_exceeded"
# is new (see run_bfield_transient.py's --max-wall-seconds).
OUTCOME_LABELS = {
    "settled": "settled (recovered)",
    "runaway": "runaway",
    "reached_end_no_deviation": "no deviation",
    "crashed": "crashed",
    "init_failed": "init failed",
    "numerical_divergence": "numerical divergence",
    "no_data": "no data",
    "max_steps_exceeded": "max steps exceeded",
    "wall_budget_exceeded": "wall budget exceeded",
}
# Statuses meaning "the process never produced trustworthy physics" --
# excluded from cross-ratio summary plots (a single garbage float, e.g.
# Tmax~1e228 from a diverged solve, blows out a shared axis and flattens
# every real ratio's curve). Per-ratio plots still run for these labels.
# Deliberately does NOT include wall_budget_exceeded -- that status means
# "stopped early on purpose, physics up to that point is real," not
# "produced garbage," so it stays IN the trustworthy set.
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
    "falsely settled (still runaway)": "darkred",
    "falsely recovering (still runaway)": "firebrick",
    "no deviation": "tab:blue",
    "crashed": "black",
    "init failed": "black",
    "numerical divergence": "black",
    "no data": "black",
    "max steps exceeded": "gray",
    "wall budget exceeded": "slategray",
    # reached_end_no_deviation reclassification (see outcome_label()) --
    # colors mirror the semantically-closest existing bucket: darkred
    # matches "falsely settled/recovering (still runaway)", tab:purple
    # matches "plateaued off-parity", yellowgreen matches "recovering
    # (asymptotic)".
    "falsely no-deviation (still runaway)": "darkred",
    "no deviation (elevated, plateaued)": "tab:purple",
    "no deviation (recovered from heating)": "yellowgreen",
}

# Tc -- lets an already-collected "settled" result whose Tmax never
# actually dropped below Tc get relabeled here even if it predates a fix
# to the live settle-check (see electrothermal/CLAUDE.md's SETTLE_TMAX_SAFE
# for the original incident this guards against).
SETTLE_TMAX_SAFE = rt.DEFAULT_SETTLE_TMAX_MAX


def recompute_trend(t, frac_left, trend_window=rt.DEFAULT_TREND_WINDOW, trend_eps=rt.DEFAULT_TREND_EPS):
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


def recompute_tmax_trend(t, tmax, trend_window=rt.DEFAULT_TREND_WINDOW, trend_eps=rt.DEFAULT_TREND_EPS):
    # classify_trend() only ever looks at |fracLeft-0.5|'s slope by
    # convention, but its slope-sign logic (positive -> "diverging") means
    # exactly the right thing applied to raw Tmax too (still heating up) --
    # reused here rather than reimplemented. See electrothermal/CLAUDE.md
    # for the real bug this catches (a symmetric full-tape runaway can
    # re-symmetrize fracLeft while Tmax keeps climbing unchecked).
    if len(t) < 2:
        return None
    final_t = t[-1]
    mask = (final_t - t) <= trend_window
    buf = list(zip(t[mask], tmax[mask]))
    return rt.classify_trend(buf, trend_eps)


def _reached_end_no_deviation_label(run):
    # "reached_end_no_deviation" (the live classifier in
    # run_bfield_transient.py) is purely a statement about fracLeft --
    # it never deviated past deviation_eps from 0.5 over the whole run.
    # That's expected and UNINFORMATIVE for a no-heater run: nothing ever
    # breaks left/right symmetry there regardless of whether the tape is
    # genuinely quenching, because a symmetric full-tape heating event
    # keeps fracLeft pinned at ~0.5 the entire time. The live classifier's
    # settle/plateau paths are gated on has_deviated, so a perfectly
    # symmetric but very much NOT "nothing happened" run falls through to
    # this same raw status with Tmax in the hundreds of K. Caught here,
    # post-hoc, the same way "falsely settled"/"falsely recovering" catch
    # their own live-classifier blind spots.
    transient = run.get("transient") or {}
    tmax_col = transient.get("Tmax")
    if tmax_col is None or len(tmax_col) == 0:
        return OUTCOME_LABELS["reached_end_no_deviation"]
    peak_tmax = float(np.max(tmax_col))
    if peak_tmax < SETTLE_TMAX_SAFE:
        return OUTCOME_LABELS["reached_end_no_deviation"]
    final_tmax = run.get("final_Tmax", 0.0) or 0.0
    if final_tmax < SETTLE_TMAX_SAFE:
        # Got hot, but cooled back down below Tc by the time the run
        # ended -- a genuine (if unconventionally-detected) recovery.
        return "no deviation (recovered from heating)"
    trend = recompute_tmax_trend(transient["t"], tmax_col)
    if trend == "diverging":
        return "falsely no-deviation (still runaway)"
    # Still elevated at the end, but not clearly still climbing (trend is
    # None/converging/plateaued) -- ambiguous rather than confidently
    # either settled or runaway; flagged, not silently bucketed as fine.
    return "no deviation (elevated, plateaued)"


def outcome_label(run):
    status = run["status"]
    if status == "settled" and run.get("final_Tmax", 0.0) >= SETTLE_TMAX_SAFE:
        return "falsely settled (still runaway)"
    if status == "reached_end_no_deviation":
        return _reached_end_no_deviation_label(run)
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


# Above this many runs, a one-legend-entry-per-ratio legend stops being
# legend-sized and starts covering the plot -- swap to a colorbar past
# this (ratio is already continuously color-mapped via ratio_color, so
# this loses no information). This sweep has ~600-650 runs per
# population, far past this threshold.
MANY_RUNS_LEGEND_CUTOFF = 20


def compute_zoom_xlim(runs, pre_margin=0.5, post_margin=0.5):
    pulse_starts = [p for p in (detect_pulse_start(r["transient"]) for r in runs) if p is not None]
    final_ts = [r["transient"]["t"][-1] for r in runs]
    start = min(pulse_starts) - pre_margin if pulse_starts else 0.0
    return max(0.0, start), max(final_ts) + post_margin


def _transient_xy(col):
    # Builds a get_xy callback for make_summary_timeseries out of a plain
    # transient-CSV column name -- the common case (fracLeft, Tmax).
    def get_xy(r):
        y = r["transient"].get(col)
        if y is None or len(y) == 0:
            return None
        return r["transient"]["t"], y
    return get_xy


def make_summary_timeseries(runs, outpath, get_xy, ylabel, title, log_y=False, xlim=None,
                             axhline=None, skip_note=None):
    # get_xy(r) -> (t_array, y_array) or None to skip that run. Generalized
    # from a fixed transient-column name (use _transient_xy(col) for that
    # case, same behavior as before) so the B-field summary plots can
    # source from r["diagnostics"] instead -- a different column set, and
    # not every run has real B-field data (see skip_note).
    fig, ax = plt.subplots(figsize=(10, 6))
    ratios = [r["ratio"] for r in runs]
    many_runs = len(runs) > MANY_RUNS_LEGEND_CUTOFF
    skipped, plotted = [], []
    for r in sorted(runs, key=lambda r: r["ratio"]):
        xy = get_xy(r)
        if xy is None:
            skipped.append(r["label"])
            continue
        t, y = xy
        color = ratio_color(r["ratio"], ratios)
        label = None if many_runs else f"{r['ratio']:.2f}xIc ({outcome_label(r)})"
        ax.plot(t, y, color=color, linewidth=1.0, alpha=0.6 if many_runs else 1.0, label=label)
        plotted.append(r)
    if skipped:
        note = f" ({skip_note})" if skip_note else ""
        print(f"  {outpath.name}: skipping {len(skipped)} run(s){note}: "
              f"{', '.join(skipped[:10])}{' ...' if len(skipped) > 10 else ''}")
    if axhline is not None:
        ax.axhline(axhline, color="gray", linestyle="--", alpha=0.5)
    pulse_starts = [p for p in (detect_pulse_start(r["transient"]) for r in plotted) if p is not None]
    if pulse_starts and max(pulse_starts) - min(pulse_starts) < 1e-6:
        ax.axvspan(pulse_starts[0], pulse_starts[0] + PULSE_DUR, color="red", alpha=0.08,
                   label="heater pulse")
    elif pulse_starts:
        print(f"  (pulse timing varies by ratio (or never fires for some) in this sweep -- "
              f"not shown as a shared band on {outpath.name})")
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
        axes[0].scatter(r["ratio"], abs(frac - 0.5), color=c, s=25, zorder=3, alpha=0.7)
        axes[1].scatter(r["ratio"], tmax, color=c, s=25, zorder=3, alpha=0.7)
    if skipped:
        print(f"  chart_summary_final_state.png: skipping {len(skipped)} run(s) with no "
              f"final state recorded (status={{{', '.join(sorted({labels[l] for l in skipped}))}}}): "
              f"{', '.join(skipped[:10])}{' ...' if len(skipped) > 10 else ''}")
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
    fig, ax = plt.subplots(figsize=(9, 6))
    labels = {r["label"]: outcome_label(r) for r in runs}
    skipped = []
    for r in sorted(runs, key=lambda r: r["ratio"]):
        val = value_fn(r)
        if val is None:
            skipped.append(r["label"])
            continue
        c = OUTCOME_COLORS.get(labels[r["label"]], "gray")
        ax.scatter(r["ratio"], val, color=c, s=20, zorder=3, alpha=0.7)
    if skipped:
        skipped_outcomes = sorted({labels[l] for l in skipped})
        note = f" ({skip_note})" if skip_note else ""
        print(f"  {outpath.name}: skipping {len(skipped)} run(s){note} "
              f"(status={{{', '.join(skipped_outcomes)}}}): "
              f"{', '.join(skipped[:10])}{' ...' if len(skipped) > 10 else ''}")
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
    def peak_voltage(r):
        diag = r.get("diagnostics")
        if not diag or "V_CL_minus" not in diag or len(diag["V_CL_minus"]) == 0:
            return None
        return float(np.max(diag["V_CL_minus"])) * 1e6
    _scatter_by_outcome(runs, outpath, peak_voltage, r"peak $V_{CL,minus}$ [µV]",
                        "Peak End-to-End Voltage vs Transport Current Ratio",
                        skip_note="no diagnostics group")


def make_peak_segment_voltage_scatter(runs, outpath):
    def peak_segment_voltage(r):
        diag = r.get("diagnostics")
        if not diag or "V1_1" not in diag:
            return None
        v1 = np.stack([diag[f"V1_{i+1}"] for i in range(10)])   # (10, n_t)
        v2 = np.stack([diag[f"V2_{i+1}"] for i in range(10)])
        seg1 = np.diff(v1, axis=0)
        seg2 = np.diff(v2, axis=0)
        return float(max(np.max(seg1), np.max(seg2))) * 1e6
    _scatter_by_outcome(runs, outpath, peak_segment_voltage,
                        "peak single-segment voltage [µV]",
                        "Peak Single-Segment Voltage vs Transport Current Ratio",
                        skip_note="no diagnostics group")


def make_peak_picard_iters_scatter(runs, outpath):
    # Bfield-specific -- no electrothermal analog (no self-consistent B<->E
    # solve there). Peak picardIters across the whole run, not just the
    # final row -- the stiffest point of a trajectory (often mid-run, not
    # at the end) is what actually drove this run's wall-clock cost. Runs
    # predating the self-consistent solve (no picardIters column at all --
    # the 4 legacy labels, see CLAUDE.md) are skipped, not zero-filled,
    # since "0 iterations" would misleadingly read as "converged instantly"
    # rather than "not applicable."
    def peak_picard_iters(r):
        diag = r.get("diagnostics")
        if not diag or "picardIters" not in diag or len(diag["picardIters"]) == 0:
            return None
        return float(np.max(diag["picardIters"]))
    _scatter_by_outcome(runs, outpath, peak_picard_iters, "peak picardIters",
                        "Peak Picard Iteration Count vs Transport Current Ratio\n"
                        "(self-consistent B<->E solve -- see CLAUDE.md)",
                        skip_note="no picardIters column (legacy pre-self-consistent run)")


BFIELD_SKIP_NOTE = "no real B-field data (diagnostics missing or -999 sentinel)"


def _run_has_real_bfield(r):
    diag = r.get("diagnostics")
    return bool(diag) and "H1" in diag and "H2" in diag and len(diag["H1"]) > 0 and pds.bfield_is_real(diag)


def _global_bfield_unit(runs):
    # Same SI-prefix auto-scaling idea as pds.auto_bfield_unit(), but
    # pooled across every run in this summary pass -- a cross-ratio plot
    # needs ONE shared unit, not a per-run choice.
    peaks = [float(np.max(np.maximum(np.abs(r["diagnostics"]["H1"]), np.abs(r["diagnostics"]["H2"]))))
             for r in runs if _run_has_real_bfield(r)]
    if not peaks:
        return 1.0, " [T]"
    peak = max(peaks)
    if peak >= 1.0:
        return 1.0, " [T]"
    if peak >= 1e-3:
        return 1e3, " [mT]"
    if peak >= 1e-6:
        return 1e6, " [µT]"
    return 1e9, " [nT]"


def make_bfield_xy(scale):
    # get_xy callback for make_summary_timeseries: max(|H1|,|H2|)(t), the
    # self-field magnitude at the heater/Hall x-location -- the one B
    # reading common to every run regardless of -aniso (H1/H2 are always
    # the isotropic |B| Hall-probe diagnostic, independent of which Jc(B,T)
    # suppression law the solve itself used -- see bfield_3d_slit.idp).
    def get_xy(r):
        if not _run_has_real_bfield(r):
            return None
        diag = r["diagnostics"]
        return diag["t"], np.maximum(np.abs(diag["H1"]), np.abs(diag["H2"])) * scale
    return get_xy


def make_peak_bfield_scatter(runs, outpath, scale=1.0, unit_label=" [T]"):
    def peak_bfield(r):
        if not _run_has_real_bfield(r):
            return None
        diag = r["diagnostics"]
        return float(np.max(np.maximum(np.abs(diag["H1"]), np.abs(diag["H2"])))) * scale
    _scatter_by_outcome(runs, outpath, peak_bfield, f"peak |B| at heater/Hall location{unit_label}",
                        "Peak Self-Field Magnitude vs Transport Current Ratio",
                        skip_note=BFIELD_SKIP_NOTE)


REVERSAL_MIN_DECLINE_K = 0.5


def detect_tmax_reversal(transient, pulse_end):
    t, tmax = transient.get("t"), transient.get("Tmax")
    if t is None or tmax is None:
        return None
    mask = t >= pulse_end
    if mask.sum() < 3:
        return None
    t_post, tmax_post = t[mask], tmax[mask]
    peak_idx = int(np.argmax(tmax_post))
    if peak_idx == len(tmax_post) - 1:
        return None
    decline = tmax_post[peak_idx] - tmax_post[-1]
    if decline < REVERSAL_MIN_DECLINE_K:
        return None
    return float(t_post[peak_idx] - pulse_end)


def make_recovery_margin_scatter(runs, outpath):
    def margin(r):
        pulse_start = detect_pulse_start(r["transient"])
        if pulse_start is None:
            return None
        return detect_tmax_reversal(r["transient"], pulse_start + PULSE_DUR)
    _scatter_by_outcome(runs, outpath, margin, "pulse-end -> Tmax turnover [s]",
                        "Recovery Time Margin vs Transport Current Ratio\n"
                        "(runs with no post-pulse Tmax turnover excluded)",
                        skip_note="no post-pulse Tmax turnover (true runaway, or cut off while still climbing)")


def per_ratio_plots(run, outdir, with_animation):
    outdir.mkdir(parents=True, exist_ok=True)
    label = run["label"]
    data = run["transient"]
    pulse_start = detect_pulse_start(data)
    pulse_end = pulse_start + PULSE_DUR if pulse_start is not None else None

    pst.make_full_timeline_plot(data, pulse_start, pulse_end, TC,
                                 outdir / "chart_slit_transient_full.png", label)
    if pulse_start is not None:
        pst.make_zoom_plot(data, pulse_start, pulse_end, TC, 0.002, 0.08,
                            outdir / "chart_slit_transient_zoom.png", label)
    else:
        print(f"  [{label}] no pulse detected (still ramping when cut off) -- "
              f"skipping chart_slit_transient_zoom.png")

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
        print(f"  [{label}] H1/H2 still -999 sentinel -- skipping bfield chart")

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
        seg_data, seg_left, seg_right = pds.build_segment_channels(diag, taps_left, taps_right, "V1_", "V2_")
        pds.make_animation(seg_data, seg_left, seg_right, Lx, width, xHeater,
                            f"{label}: Segment Voltage Evolution", "Segment voltage [µV]",
                            outdir / "anim_diagnostics_segment_voltage.gif", pulse_start, pulse_end, unit_scale=1e6)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--h5", default="runs/sweep.h5", help="Path to the sweep HDF5 file (relative to this script)")
    ap.add_argument("--labels", default=None, help="Comma-separated labels (default: every group in the file)")
    ap.add_argument("--outdir", default="runs/analysis", help="Output directory (relative to this script)")
    ap.add_argument("--with-animation", action="store_true",
                     help="Also regenerate the (slow) per-ratio voltage/temperature GIFs")
    ap.add_argument("--summary-only", action="store_true",
                     help="Skip the per-ratio diagnostic subdirectories entirely -- just the "
                          "cross-ratio chart_summary_*.png plots.")
    ap.add_argument("--per-ratio-only", action="store_true",
                     help="Skip the cross-ratio chart_summary_*.png plots entirely -- just the "
                          "per-ratio diagnostic subdirectories. Use this together with --labels "
                          "when spot-checking a handful of runs, or the cross-ratio summaries "
                          "silently get REGENERATED FROM ONLY THOSE LABELS and overwrite the "
                          "full-population versions.")
    args = ap.parse_args()
    if args.summary_only and args.per_ratio_only:
        sys.exit("--summary-only and --per-ratio-only are mutually exclusive")

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

    if args.per_ratio_only:
        print("--per-ratio-only: skipping cross-ratio chart_summary_*.png plots")
    else:
        print("Cross-ratio summary plots...")
        all_runs = load_runs(h5_path, None) if labels else runs
        trustworthy = [r for r in all_runs if has_trustworthy_physics(r)]
        excluded = [r["label"] for r in all_runs if r not in trustworthy]
        if excluded:
            print(f"  excluding {len(excluded)} run(s) with no trustworthy physics "
                  f"(status in {sorted(NO_TRUSTWORTHY_PHYSICS)}): "
                  f"{', '.join(excluded[:10])}{' ...' if len(excluded) > 10 else ''}")
        make_summary_timeseries(trustworthy, outdir / "chart_summary_fracleft_vs_t.png",
                                 _transient_xy("fracLeft"), "Current fraction on heated side",
                                 "fracLeft(t) Across Transport Current Ratios", axhline=0.5)
        make_summary_timeseries(trustworthy, outdir / "chart_summary_tmax_vs_t.png",
                                 _transient_xy("Tmax"), "Tmax [K]",
                                 "Tmax(t) Across Transport Current Ratios")
        make_summary_timeseries(trustworthy, outdir / "chart_summary_tmax_vs_t_log.png",
                                 _transient_xy("Tmax"), "Tmax [K] (log scale)",
                                 "Tmax(t) Across Transport Current Ratios (log scale)", log_y=True)
        zoom_xlim = compute_zoom_xlim(trustworthy)
        make_summary_timeseries(trustworthy, outdir / "chart_summary_tmax_vs_t_zoom.png",
                                 _transient_xy("Tmax"), "Tmax [K]",
                                 "Tmax(t) Across Transport Current Ratios (zoomed)", xlim=zoom_xlim)
        make_final_state_plot(trustworthy, outdir / "chart_summary_final_state.png")
        make_peak_tmax_scatter(trustworthy, outdir / "chart_summary_peak_tmax.png")
        make_peak_voltage_scatter(trustworthy, outdir / "chart_summary_peak_voltage.png")
        make_peak_segment_voltage_scatter(trustworthy, outdir / "chart_summary_peak_segment_voltage.png")
        make_recovery_margin_scatter(trustworthy, outdir / "chart_summary_recovery_margin.png")
        make_peak_picard_iters_scatter(trustworthy, outdir / "chart_summary_peak_picard_iters.png")
        bscale, blabel = _global_bfield_unit(trustworthy)
        make_peak_bfield_scatter(trustworthy, outdir / "chart_summary_peak_bfield.png",
                                  scale=bscale, unit_label=blabel)
        make_summary_timeseries(trustworthy, outdir / "chart_summary_bfield_vs_t.png",
                                 make_bfield_xy(bscale), f"peak |B| at heater/Hall location{blabel}",
                                 "Self-Field Magnitude(t) Across Transport Current Ratios",
                                 skip_note=BFIELD_SKIP_NOTE)
        make_summary_timeseries(trustworthy, outdir / "chart_summary_bfield_vs_t_log.png",
                                 make_bfield_xy(bscale), f"peak |B| at heater/Hall location{blabel} (log scale)",
                                 "Self-Field Magnitude(t) Across Transport Current Ratios (log scale)",
                                 log_y=True, skip_note=BFIELD_SKIP_NOTE)
        print(f"  wrote {outdir}/chart_summary_*.png")

    if args.summary_only:
        print("--summary-only: skipping per-ratio diagnostic subdirectories")
    else:
        print("Per-ratio diagnostic plots...")
        for run in runs:
            print(f"  [{run['label']}]")
            per_ratio_plots(run, outdir / run["label"], args.with_animation)

    print(f"Done. Output under {outdir}/")


if __name__ == "__main__":
    main()
