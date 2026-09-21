#!/usr/bin/env python3
"""
analyze_voltage_diagnostics.py -- exploratory analysis of the voltage-tap
diagnostics as a candidate control parameter for quench detection, reading
the same runs/sweep.h5 handoff file as analyze_sweep_hdf5.py.

Motivation: Tmax isn't directly measurable on a real tape (it needs the
full FEM field); voltage is. If voltage jump magnitude cleanly separates
recovering from runaway ratios independent of the trip *time*, it's usable
as a real-time control signal instead of waiting to see whether Tmax
crosses a threshold.

"Voltage jump" here means max|V_CL_minus(t)| over the run -- the whole-
tape terminal voltage (current-lead to current-lead), i.e. the simplest
signal a real experiment could actually wire up without internal taps.
Use --channel to substitute a specific tap (e.g. V1_10) instead.

Outcome bucketing reuses analyze_sweep_hdf5.outcome_label() -- the
corrected recovering/runaway classification (see that script's CLAUDE.md
history: raw status/trend alone mislabels several ratios in this dataset
as "recovering"/"settled" when Tmax is still climbing).

Produces:
  chart_voltage_jump_recovering.png     -- max voltage jump vs ratio, recovering runs only
  chart_voltage_jump_runaway.png        -- max voltage jump vs ratio, runaway runs only
  chart_voltage_jump_vs_tmax.png        -- max voltage jump vs final Tmax, all runs,
                                            colored by outcome -- tests whether a single
                                            voltage threshold separates the two groups
                                            regardless of ratio/Tmax
  chart_voltage_turn_lead_time_crossings.png / chart_voltage_turn_lead_time.png
                                         -- RECOMMENDED method: no fixed threshold at all --
                                            trips when voltage passes its own post-pulse local
                                            minimum and starts rising again (voltage_turning_
                                            point()). Checked directly: 0/14 recovering runs
                                            ever show this (no known false positives) and it
                                            precedes -- or ties, worst case -- Tmax's own
                                            turning point for every tested runaway run (no
                                            known missed runaways either).
  chart_voltage_lead_time_crossings.png / chart_voltage_lead_time.png
                                         -- fixed---voltage-threshold comparison, kept for
                                            context. Also compared against Tmax's post-pulse
                                            turning point (the real committal point, NOT a
                                            fixed Tmax value -- see tmax_turning_point()), and
                                            restricted to search from voltage's own minimum
                                            onward so the universal heater-pulse voltage bump
                                            (present on every run, safe or not) can't be
                                            mistaken for a genuine trip.
  chart_voltage_leadtime_vs_threshold.png -- the fixed-threshold tradeoff: mean/median lead
                                            time and % of runs caught too late, swept across
                                            --threshold-sweep, against the known highest
                                            voltage jump ever seen on a run that recovered
  chart_voltage_localization.png        -- max adjacent-tap-difference ("segment") voltage
                                            vs its spatial position, for a handful of
                                            representative ratios from both buckets --
                                            tests whether voltage alone localizes the
                                            hot spot to the heater location
  anim_voltage_localization_<label>_<side>.gif -- (opt-in, --animate-label) the same
                                            segment-voltage-vs-x curve for one run,
                                            animated over t instead of collapsed to its max

Usage:
  python3 analyze_voltage_diagnostics.py
  python3 analyze_voltage_diagnostics.py --h5 runs/sweep_granular.h5 --outdir runs/analysis_voltage
  python3 analyze_voltage_diagnostics.py --channel V1_10
  python3 analyze_voltage_diagnostics.py --voltage-threshold 0.01
  python3 analyze_voltage_diagnostics.py --animate-label r0p7 --animate-side V1
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import analyze_sweep_hdf5 as ash

# Bucketing by *physical* outcome (via outcome_label(), not raw status) --
# this is the whole reason the settled/converging mislabeling in
# analyze_sweep_hdf5.py mattered: those bugs would have put runaway runs
# in the "recovering" bucket here too.
RECOVERING_OUTCOMES = {"settled (recovered)", "recovering (asymptotic)", "no deviation"}
RUNAWAY_OUTCOMES = {
    "runaway", "falsely settled (still runaway)", "falsely recovering (still runaway)",
    "diverging (pre-runaway)",
}
# Deliberately excluded, not force-bucketed: "plateaued off-parity" is a
# genuine third physical outcome (new off-center equilibrium), not simply
# recovering or runaway, and crashed/no-data/max-steps-exceeded aren't a
# physical outcome at all. Printed as skipped rather than silently dropped.


_TAP_RE = re.compile(r"^V([12])_(\d+)$")

# Candidate voltage trip point for the lead-time comparison -- chosen well
# inside the ~7mV (max recovering) / 34mV (min runaway, at this dataset's
# finest granularity near the boundary) gap found by the jump-vs-ratio/
# jump-vs-Tmax plots above, not calibrated against any real instrumentation
# noise floor. See make_threshold_sensitivity_plot()/the module docstring
# for why this specific value trades away a lot of real lead time for
# false-positive margin -- lower is NOT free, see RECOVERING_VOLTAGE_FLOOR.
VOLTAGE_TRIP_DEFAULT = 0.05
# Empirically, the highest max-voltage-jump seen among any run that
# actually recovered in this dataset (r0p9034, 6.88mV -- see
# chart_voltage_jump_recovering.png). ANY --voltage-threshold below this
# would false-trip on a run that was genuinely safe. This is itself
# dataset-specific and, per the recovery/runaway-boundary narrowing seen
# when granularity increased earlier in this project, should be expected
# to creep upward (not down) as finer sweeps arrive -- treat as a lower
# bound observed so far, not a hard physical constant.
RECOVERING_VOLTAGE_FLOOR = 0.00688


def first_crossing_time(t, values, threshold):
    mask = np.abs(values) >= threshold
    if not np.any(mask):
        return None
    return float(t[np.argmax(mask)])


def _post_pulse_local_min(t, values, pulse_start, margin):
    # Shared by tmax_turning_point()/voltage_turning_point(): the LOCAL
    # MINIMUM of a post-pulse signal, and whether that minimum is "real"
    # (an interior turning point the signal has already risen back away
    # from) or just the last recorded row (still falling -- i.e. no
    # turning point observed yet, right-censored).
    mask = t > pulse_start + margin
    if not np.any(mask):
        return None, False
    t_post, v_post = t[mask], values[mask]
    idx = int(np.argmin(v_post))
    is_real = idx != len(v_post) - 1
    return float(t_post[idx]), is_real


def tmax_turning_point(run):
    # What "danger" should mean for a lead-time comparison, rethought:
    # a FIXED Tmax value (this used to be TMAX_DANGER_DEFAULT=300K) is
    # the wrong tool entirely. Checked directly: EVERY run at a given
    # ratio -- recovering and runaway alike -- passes through the exact
    # same post-pulse temperature range (peaks ~157.6K from the heater
    # itself, cools back down through 90K into the 80s) because that
    # initial spike is dominated by the fixed-power heater, not by the
    # transport current. r0p9034 (recovers) and r0p9036 (runaway) are
    # numerically identical to 4 significant figures all the way down to
    # ~85K before diverging. So no fixed threshold in that whole range
    # can distinguish fate -- it's not "how hot", it's "does Tmax turn
    # back up after cooling". The actual physical committal point is the
    # LOCAL MINIMUM of Tmax(t) after the pulse: confirmed directly, this
    # sits anywhere from ~85K (right at the boundary, e.g. r0p9036) up to
    # ~1500K+ (extreme overcurrent, where cooling barely gets a foothold
    # before self-heating wins) -- i.e. it moves with the ratio, which is
    # exactly why a fixed value can't stand in for it.
    #
    # Returns (t_turn, is_real). For a genuinely recovering run, Tmax is
    # usually still falling at the last recorded row -- no turning point
    # exists in the observed window, so is_real=False (this function is
    # only meant to be called on the runaway bucket; a False here on a
    # runaway run means its recorded window ended before it turned,
    # i.e. right-censored, not that it's actually safe).
    return _post_pulse_local_min(run["transient"]["t"], run["transient"]["Tmax"],
                                  ash.detect_pulse_start(run["transient"]), margin=0.02)


def voltage_turning_point(run, channel):
    # Same shape of question as tmax_turning_point, but for voltage, and
    # it exposed a real bug in how this script used to define "voltage
    # trip time": EVERY run -- recovering or runaway -- shows the exact
    # same brief voltage bump synchronized with the 10ms heater pulse
    # itself (up to ~7mV even for genuinely safe runs, see
    # RECOVERING_VOLTAGE_FLOOR), then decays. first_crossing_time() at a
    # low threshold was catching THAT universal bump, not a genuine
    # danger signal -- giving a falsely reassuring "0% too late at 5mV"
    # result that would have false-tripped on every run regardless of
    # fate, not just the ones that actually run away. Restricting to the
    # post-pulse LOCAL MINIMUM (mirroring tmax_turning_point) sidesteps
    # this entirely: checked directly, 0 of 14 recovering runs ever show
    # voltage turning back up after that minimum within the recorded
    # window, while every one of 186 tested runaway runs does, and
    # always at or before Tmax's own turning point (min lead ~1 timestep,
    # mean +0.051s). This makes "voltage passed its post-pulse minimum
    # and is rising again" a threshold-free detector with no observed
    # false positives and no observed missed runaway in this dataset --
    # a stronger, more physically justified answer to "find a threshold
    # that always catches a runaway" than any fixed voltage level gave.
    diag = run["diagnostics"]
    return _post_pulse_local_min(diag["t"], np.abs(diag[channel]),
                                  ash.detect_pulse_start(run["transient"]), margin=0.02)


def channel_label(channel):
    # Mathtext subscript instead of the raw underscored column name --
    # "V_CL_minus"/"V1_10" are CSV-header-safe identifiers, not intended
    # as a display label.
    if channel == "V_CL_plus":
        return r"$V_{CL+}$"
    if channel == "V_CL_minus":
        return r"$V_{CL-}$"
    m = _TAP_RE.match(channel)
    if m:
        side, idx = m.groups()
        return rf"$V_{{{side},{idx}}}$"
    return channel


def max_voltage_jump(run, channel):
    diag = run.get("diagnostics")
    if not diag or channel not in diag:
        return None
    return float(np.max(np.abs(diag[channel])))


def bucket_runs(runs, channel):
    recovering, runaway, skipped = [], [], []
    for r in runs:
        label = ash.outcome_label(r)
        jump = max_voltage_jump(r, channel)
        if jump is None:
            skipped.append((r["label"], "no diagnostics/channel data"))
            continue
        r["_voltage_jump"] = jump
        r["_outcome"] = label
        if label in RECOVERING_OUTCOMES:
            recovering.append(r)
        elif label in RUNAWAY_OUTCOMES:
            runaway.append(r)
        else:
            skipped.append((r["label"], label))
    return recovering, runaway, skipped


def make_jump_vs_ratio_plot(runs, outpath, title, color, channel):
    fig, ax = plt.subplots(figsize=(8, 6))
    if not runs:
        ax.text(0.5, 0.5, "no runs in this bucket", ha="center", va="center", transform=ax.transAxes)
    else:
        ratios = [r["ratio"] for r in runs]
        jumps = [r["_voltage_jump"] for r in runs]
        ax.scatter(ratios, jumps, color=color, s=50, zorder=3)
    ax.set_xlabel("transport current ratio (I0 / Ic)")
    ax.set_ylabel(f"max |{channel_label(channel)}| [V]")
    ax.set_title(title, fontsize=13)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def make_jump_vs_tmax_plot(recovering, runaway, outpath, channel):
    fig, ax = plt.subplots(figsize=(9, 6.5))
    for bucket, marker in ((recovering, "o"), (runaway, "^")):
        for r in bucket:
            c = ash.OUTCOME_COLORS.get(r["_outcome"], "gray")
            ax.scatter(r["final_Tmax"], r["_voltage_jump"], color=c, marker=marker, s=55,
                       edgecolors="black", linewidths=0.3, zorder=3)
    ax.set_yscale("log")
    ax.set_xlabel("final Tmax [K]")
    ax.set_ylabel(f"max |{channel_label(channel)}| [V] (log scale)")
    ax.set_title("Voltage Jump vs Final Tmax -- circles=recovering, triangles=runaway", fontsize=12)
    ax.grid(alpha=0.3, which="both")
    # Marker must match whichever bucket (circle=recovering, triangle=
    # runaway) an outcome actually came from -- a fixed marker="o" here
    # previously misrepresented every runaway entry in the legend.
    handles = []
    for bucket, marker in ((recovering, "o"), (runaway, "^")):
        for o in sorted({r["_outcome"] for r in bucket}):
            handles.append(plt.Line2D([0], [0], marker=marker, color="w",
                                       markerfacecolor=ash.OUTCOME_COLORS.get(o, "gray"),
                                       markeredgecolor="black", markeredgewidth=0.3,
                                       markersize=8, label=o))
    ax.legend(handles=handles, loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def compute_turn_lead_times(runaway_runs, channel):
    # The recommended answer to "find a threshold that always catches a
    # runaway": don't use a fixed threshold at all -- use voltage's own
    # post-pulse turning point (see voltage_turning_point()). Checked
    # directly against every run in this dataset: 0/14 recovering runs
    # ever show one (zero known false positives) and every one of 186
    # tested runaway runs shows voltage turning at or before Tmax's own
    # turning point (zero missed runaways, min lead ~1 timestep).
    results, skipped = [], []
    for r in runaway_runs:
        t_tmax_turn, tmax_real = tmax_turning_point(r)
        t_v_turn, v_real = voltage_turning_point(r, channel)
        if not tmax_real or not v_real:
            skipped.append((r["label"], f"tmax_turn_is_real={tmax_real} voltage_turn_is_real={v_real}"))
            continue
        results.append({"label": r["label"], "ratio": r["ratio"], "outcome": r["_outcome"],
                         "t_voltage_trip": t_v_turn, "t_tmax_turn": t_tmax_turn,
                         "lead_time": t_tmax_turn - t_v_turn})
    return results, skipped


def compute_lead_times(runaway_runs, channel, voltage_threshold):
    # Fixed-threshold comparison, kept for context/comparison against
    # compute_turn_lead_times() above (the recommended method). Restricted
    # to searching from voltage's own post-pulse minimum onward -- NOT
    # from t=0 -- because first_crossing_time() from the start of the run
    # catches the universal heater-pulse voltage bump every run shows
    # (recovering or not, up to ~7mV, see RECOVERING_VOLTAGE_FLOOR) rather
    # than genuine renewed buildup. That bug previously made low
    # thresholds look artificially reliable (they were "catching" the
    # harmless pulse bump, not a real danger signal, including on runs
    # that would ultimately recover).
    results, skipped = [], []
    for r in runaway_runs:
        diag = r["diagnostics"]
        t_tmax_turn, tmax_real = tmax_turning_point(r)
        t_v_turn, v_real = voltage_turning_point(r, channel)
        if not tmax_real or not v_real:
            skipped.append((r["label"], f"tmax_turn_is_real={tmax_real} voltage_turn_is_real={v_real}"))
            continue
        mask = diag["t"] >= t_v_turn
        t_v = first_crossing_time(diag["t"][mask], diag[channel][mask], voltage_threshold)
        if t_v is None:
            skipped.append((r["label"], f"never crosses {voltage_threshold} V after its own minimum"))
            continue
        results.append({"label": r["label"], "ratio": r["ratio"], "outcome": r["_outcome"],
                         "t_voltage_trip": t_v, "t_tmax_turn": t_tmax_turn,
                         "lead_time": t_tmax_turn - t_v})
    return results, skipped


def lead_time_vs_threshold(runaway_runs, channel, thresholds):
    # Same post-pulse-minimum restriction as compute_lead_times() above --
    # see that function's comment for why searching from t=0 is wrong.
    turns = {r["label"]: (tmax_turning_point(r), voltage_turning_point(r, channel)) for r in runaway_runs}
    rows = []
    for thresh in thresholds:
        leads = []
        for r in runaway_runs:
            (t_tmax_turn, tmax_real), (t_v_turn, v_real) = turns[r["label"]]
            if not tmax_real or not v_real:
                continue
            diag = r["diagnostics"]
            mask = diag["t"] >= t_v_turn
            t_v = first_crossing_time(diag["t"][mask], diag[channel][mask], thresh)
            if t_v is None:
                continue
            leads.append(t_tmax_turn - t_v)
        if not leads:
            continue
        leads = np.array(leads)
        rows.append({"threshold": thresh, "n": len(leads), "mean": float(leads.mean()),
                     "median": float(np.median(leads)), "negative_frac": float(np.mean(leads < 0))})
    return rows


def make_lead_time_crossings_plot(results, outpath, voltage_event_label, title):
    fig, ax = plt.subplots(figsize=(9, 6))
    results = sorted(results, key=lambda r: r["ratio"])
    ratios = [r["ratio"] for r in results]
    ax.plot(ratios, [r["t_voltage_trip"] for r in results], "o-", color="tab:blue", markersize=4,
             label=voltage_event_label)
    ax.plot(ratios, [r["t_tmax_turn"] for r in results], "o-", color="tab:red", markersize=4,
             label="Tmax's post-pulse turning point (point of no return)")
    ax.set_xlabel("transport current ratio (I0 / Ic)")
    ax.set_ylabel("time [s]")
    ax.set_title(title, fontsize=12)
    ax.legend(loc="best", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def make_lead_time_plot(results, outpath, title):
    fig, ax = plt.subplots(figsize=(8, 6))
    results = sorted(results, key=lambda r: r["ratio"])
    ratios = [r["ratio"] for r in results]
    leads = [r["lead_time"] for r in results]
    ax.axhline(0, color="gray", linestyle="--", alpha=0.6)
    colors = ["tab:red" if l < 0 else "tab:purple" for l in leads]
    ax.scatter(ratios, leads, color=colors, s=45, zorder=3)
    ax.set_xlabel("transport current ratio (I0 / Ic)")
    ax.set_ylabel("lead time [s]  (Tmax turning-point time minus voltage-event time)")
    ax.set_title(f"{title}\nred = too late (voltage event AFTER the point of no return)", fontsize=11)
    ax.grid(alpha=0.3)
    if leads:
        mean_lead = float(np.mean(leads))
        neg_frac = float(np.mean(np.array(leads) < 0))
        ax.text(0.02, 0.02, f"mean lead = {mean_lead:+.3f} s, n = {len(leads)}, "
                f"{neg_frac:.0%} too late", transform=ax.transAxes, fontsize=9, va="bottom")
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def make_threshold_sensitivity_plot(rows, outpath, recovering_floor):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8), sharex=True)
    thresholds = [r["threshold"] for r in rows]
    ax1.axhline(0, color="gray", linestyle="--", alpha=0.6)
    ax1.plot(thresholds, [r["mean"] for r in rows], "o-", color="tab:purple", label="mean lead")
    ax1.plot(thresholds, [r["median"] for r in rows], "o-", color="tab:purple", alpha=0.5,
              label="median lead")
    ax1.set_ylabel("lead time [s]")
    ax1.legend(loc="best", fontsize=8)
    ax1.grid(alpha=0.3)
    ax2.plot(thresholds, [r["negative_frac"] * 100 for r in rows], "o-", color="tab:red")
    ax2.set_ylabel("% of runs too late\n(trip after point of no return)")
    ax2.set_xlabel("voltage trip threshold [V]")
    ax2.grid(alpha=0.3)
    for ax in (ax1, ax2):
        ax.axvline(recovering_floor, color="black", linestyle=":", alpha=0.7)
        ax.text(recovering_floor, ax.get_ylim()[1], " highest jump seen\n on a safe run",
                fontsize=7, ha="left", va="top")
    fig.suptitle("Lead-Time / False-Positive-Margin Tradeoff vs Trip Threshold", fontsize=13)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


# --------------------------------------------------------- localization --

def segment_time_series(run, side_prefix):
    # V{side}_i is CUMULATIVE from V_CL+ (x=0), so it grows monotonically
    # with x regardless of where the actual resistive/hot zone is -- not
    # informative for localization on its own. The adjacent-tap DIFFERENCE
    # recovers the local segment's own resistive drop, which is what
    # actually peaks at the hot-spot location. segment i spans from tap
    # i-1 (or x=0 for i=1) to tap i; x_mid is its midpoint.
    diag = run["diagnostics"]
    positions = run["positions"]
    t = diag["t"]
    prev_v = np.zeros_like(t)
    prev_x = 0.0
    x_mids, channels, seg_series = [], [], []
    for i in range(1, 11):
        ch = f"{side_prefix}{i}"
        if ch not in diag:
            break
        v = diag[ch]
        x = positions[ch]["x_m"]
        seg_series.append(np.abs(v - prev_v))
        x_mids.append((prev_x + x) / 2)
        channels.append(ch)
        prev_v, prev_x = v, x
    return t, np.array(x_mids), channels, np.array(seg_series)  # seg_series: (n_segments, n_t)


def segment_voltages(run, side_prefix):
    t, x_mids, channels, seg_series = segment_time_series(run, side_prefix)
    max_v = np.max(seg_series, axis=1) if seg_series.size else np.array([])
    return [{"channel": ch, "x_mid": x, "max_v": float(mv)} for ch, x, mv in zip(channels, x_mids, max_v)]


def pick_representative_runs(bucket, n):
    if not bucket:
        return []
    ordered = sorted(bucket, key=lambda r: r["ratio"])
    if len(ordered) <= n:
        return ordered
    idx = np.linspace(0, len(ordered) - 1, n).round().astype(int)
    return [ordered[i] for i in sorted(set(idx))]


def make_localization_plot(recovering, runaway, outpath, x_heater, n_per_bucket=3):
    # Coloring by outcome (ash.OUTCOME_COLORS) put nearly every line in a
    # bucket at the *same* color, since a bucket is almost always one
    # outcome label ("recovering (asymptotic)" / "runaway") -- exactly the
    # low-contrast-within-a-bucket problem reported. Colored by index
    # within the picked ratios instead, spread across a visibly distinct
    # slice of a bucket-specific colormap (Greens/Reds), so contrast is
    # maximized regardless of how close together the chosen ratios are.
    fig, ax = plt.subplots(figsize=(9, 6.5))
    for bucket, ls, cmap_name in ((recovering, "-", "Greens"), (runaway, "--", "Reds")):
        picks = pick_representative_runs(bucket, n_per_bucket)
        cmap = plt.get_cmap(cmap_name)
        n = len(picks)
        for i, r in enumerate(picks):
            frac = 0.35 + 0.6 * (i / max(n - 1, 1))
            c = cmap(frac)
            for side_prefix, marker in (("V1_", "o"), ("V2_", "^")):
                segs = segment_voltages(r, side_prefix)
                ax.plot([s["x_mid"] for s in segs], [s["max_v"] for s in segs], ls, marker=marker,
                        color=c, markersize=4, linewidth=1.2, alpha=0.9,
                        label=f"{r['ratio']:.4f}xIc ({side_prefix[:-1]})")
    if x_heater is not None:
        ax.axvline(x_heater, color="black", linestyle=":", alpha=0.6, label="heater location")
    ax.set_yscale("log")
    ax.set_xlabel("segment midpoint x [m]")
    ax.set_ylabel("max |segment voltage| [V] (log scale)")
    ax.set_title("Spatial Localization of Voltage Jump -- solid=recovering, dashed=runaway", fontsize=12)
    ax.grid(alpha=0.3, which="both")
    ax.legend(loc="best", fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)


def make_localization_animation(run, side_prefix, outpath, x_heater, max_frames=150, fps=12):
    # Same curve as make_localization_plot (max |segment voltage| vs x),
    # but animated over t instead of collapsed to a single max -- shows
    # the localization pattern actually building up/decaying rather than
    # just its high-water mark.
    t, x_mids, _channels, seg_series = segment_time_series(run, side_prefix)
    n = len(t)
    stride = max(1, n // max_frames)
    frame_idx = list(range(0, n, stride))
    if frame_idx[-1] != n - 1:
        frame_idx.append(n - 1)

    floor = 1e-12  # log scale can't render exactly 0 (true at t=0 by construction)
    plot_vals = np.clip(seg_series, floor, None)
    vmin, vmax = float(plot_vals.min()), float(plot_vals.max())
    if vmin == vmax:
        vmax = vmin * 10

    pulse_start = ash.detect_pulse_start(run["transient"])
    pulse_end = pulse_start + ash.PULSE_DUR

    fig, ax = plt.subplots(figsize=(8, 6))
    line, = ax.plot(x_mids, plot_vals[:, frame_idx[0]], "o-", color="tab:green", markersize=5, linewidth=1.5)
    if x_heater is not None:
        ax.axvline(x_heater, color="black", linestyle=":", alpha=0.6, label="heater location")
        ax.legend(loc="upper right", fontsize=8)
    ax.set_yscale("log")
    ax.set_ylim(vmin * 0.5, vmax * 2)
    ax.set_xlabel("segment midpoint x [m]")
    ax.set_ylabel(f"|segment voltage| [V] (log scale, side={side_prefix[:-1]})")
    ax.set_title(f"{run['ratio']:.4f}xIc -- Segment Voltage vs x", fontsize=13)
    ax.grid(alpha=0.3, which="both")
    time_text = ax.text(0.02, 0.97, "", transform=ax.transAxes, ha="left", va="top", fontsize=10,
                         bbox=dict(boxstyle="round,pad=0.25", fc="white", alpha=0.7, ec="none"))

    def update(frame_i):
        idx = frame_idx[frame_i]
        line.set_ydata(plot_vals[:, idx])
        t_now = t[idx]
        in_pulse = pulse_start <= t_now <= pulse_end
        time_text.set_text(f"t = {t_now:.4f} s" + ("   [heater ON]" if in_pulse else ""))
        return [line, time_text]

    fig.tight_layout()
    anim = FuncAnimation(fig, update, frames=len(frame_idx), blit=False)
    anim.save(outpath, writer=PillowWriter(fps=fps))
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--h5", default="runs/sweep.h5", help="Path to the sweep HDF5 file (relative to this script)")
    ap.add_argument("--labels", default=None, help="Comma-separated labels (default: every group in the file)")
    ap.add_argument("--outdir", default="runs/analysis_voltage", help="Output directory (relative to this script)")
    ap.add_argument("--channel", default="V_CL_minus",
                     help="Diagnostics column to treat as the voltage signal (default: V_CL_minus, "
                          "the whole-tape terminal voltage -- the signal a real experiment could "
                          "wire up without internal taps). Try V1_10/V2_10 for a single-side tap.")
    ap.add_argument("--voltage-threshold", type=float, default=VOLTAGE_TRIP_DEFAULT,
                     help=f"Candidate trip threshold on --channel for the lead-time comparison "
                          f"(default: {VOLTAGE_TRIP_DEFAULT} V -- see VOLTAGE_TRIP_DEFAULT comment).")
    ap.add_argument("--threshold-sweep", default="0.006,0.007,0.008,0.01,0.02,0.03,0.05,0.1,0.5,1.0",
                     help="Comma-separated voltage thresholds [V] for the lead-time/false-positive "
                          "tradeoff sweep (chart_voltage_leadtime_vs_threshold.png).")
    ap.add_argument("--localization-n", type=int, default=3,
                     help="Number of representative ratios per bucket (recovering/runaway) to overlay "
                          "on the spatial localization plot (default: 3).")
    ap.add_argument("--animate-label", default=None,
                     help="If set, also render an animated GIF of the segment-voltage-vs-x curve "
                          "over time for this run label (e.g. r0p7), instead of just its max.")
    ap.add_argument("--animate-side", default="V1", choices=["V1", "V2"],
                     help="Which side's taps to animate (default: V1 / left).")
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
    runs = ash.load_runs(h5_path, labels)
    if not runs:
        sys.exit("No usable runs found in the HDF5 file")

    recovering, runaway, skipped = bucket_runs(runs, args.channel)
    print(f"recovering: {len(recovering)}  runaway: {len(runaway)}  skipped: {len(skipped)}")
    if skipped:
        print("  skipped (not bucketed as recovering/runaway):")
        for label, reason in skipped:
            print(f"    {label}: {reason}")

    outdir.mkdir(parents=True, exist_ok=True)
    make_jump_vs_ratio_plot(recovering, outdir / "chart_voltage_jump_recovering.png",
                             f"Max Voltage Jump vs Ratio -- Recovering Runs (n={len(recovering)})",
                             "tab:green", args.channel)
    make_jump_vs_ratio_plot(runaway, outdir / "chart_voltage_jump_runaway.png",
                             f"Max Voltage Jump vs Ratio -- Runaway Runs (n={len(runaway)})",
                             "tab:red", args.channel)
    make_jump_vs_tmax_plot(recovering, runaway, outdir / "chart_voltage_jump_vs_tmax.png", args.channel)
    print(f"wrote {outdir}/chart_voltage_jump_*.png")

    # Recommended method: no fixed threshold at all -- trip when voltage
    # passes its own post-pulse minimum and starts rising again. Checked
    # against every recovering run first, since that's the false-positive
    # exposure this whole method depends on.
    recovering_turns = [voltage_turning_point(r, args.channel) for r in recovering]
    n_false_positive = sum(1 for _, is_real in recovering_turns if is_real)
    print(f"turning-point method false-positive check: {n_false_positive}/{len(recovering)} "
          f"recovering runs show voltage turning back up (would be a false trip)")

    turn_results, turn_skipped = compute_turn_lead_times(runaway, args.channel)
    n_turn_late = sum(1 for r in turn_results if r["lead_time"] < 0)
    print(f"turning-point lead-time: {len(turn_results)} runaway runs compared, "
          f"{len(turn_skipped)} right-censored, {n_turn_late} caught too late")
    if turn_results:
        make_lead_time_crossings_plot(
            turn_results, outdir / "chart_voltage_turn_lead_time_crossings.png",
            f"|{channel_label(args.channel)}| post-pulse turning point",
            "Voltage's Own Turning Point vs Actual Committal Point (runaway runs)")
        make_lead_time_plot(turn_results, outdir / "chart_voltage_turn_lead_time.png",
                             "Lead Time: Voltage Turning Point vs Tmax Committal Point (no fixed threshold)")
        print(f"wrote {outdir}/chart_voltage_turn_lead_time*.png (recommended method)")

    # Fixed-threshold comparison, kept for context -- now correctly
    # restricted to search from voltage's own minimum onward (see
    # compute_lead_times' comment for the pulse-transient bug this fixes).
    lead_results, lead_skipped = compute_lead_times(runaway, args.channel, args.voltage_threshold)
    print(f"fixed-threshold lead-time (trip={args.voltage_threshold} V): {len(lead_results)} runaway "
          f"runs compared, {len(lead_skipped)} skipped")
    for label, reason in lead_skipped:
        print(f"    {label}: {reason}")
    if lead_results:
        make_lead_time_crossings_plot(
            lead_results, outdir / "chart_voltage_lead_time_crossings.png",
            f"|{channel_label(args.channel)}| crosses {args.voltage_threshold} V (after its own minimum)",
            f"Fixed-Threshold Voltage Trip vs Actual Committal Point (trip={args.voltage_threshold} V)")
        make_lead_time_plot(lead_results, outdir / "chart_voltage_lead_time.png",
                             f"Fixed-Threshold Voltage Lead Time (trip={args.voltage_threshold} V)")
        n_late = sum(1 for r in lead_results if r["lead_time"] < 0)
        print(f"wrote {outdir}/chart_voltage_lead_time*.png "
              f"({n_late}/{len(lead_results)} runs would trip TOO LATE at {args.voltage_threshold} V)")
    else:
        print("  no runs with both crossings available -- skipping lead-time plots")

    thresholds = sorted(float(x) for x in args.threshold_sweep.split(","))
    sweep_rows = lead_time_vs_threshold(runaway, args.channel, thresholds)
    if sweep_rows:
        make_threshold_sensitivity_plot(sweep_rows, outdir / "chart_voltage_leadtime_vs_threshold.png",
                                         RECOVERING_VOLTAGE_FLOOR)
        print(f"wrote {outdir}/chart_voltage_leadtime_vs_threshold.png -- "
              f"(known safe-run ceiling: {RECOVERING_VOLTAGE_FLOOR*1000:.2f} mV, "
              f"any threshold below that WILL false-trip on a recovering run)")

    x_heater = None
    if runs[0].get("positions"):
        _, _, x_heater = ash.pds.get_geometry(runs[0]["positions"])
    make_localization_plot(recovering, runaway, outdir / "chart_voltage_localization.png",
                            x_heater, n_per_bucket=args.localization_n)
    print(f"wrote {outdir}/chart_voltage_localization.png")

    if args.animate_label:
        match = next((r for r in runs if r["label"] == args.animate_label), None)
        if match is None:
            print(f"  --animate-label {args.animate_label}: not found in this HDF5 file, skipping")
        else:
            anim_path = outdir / f"anim_voltage_localization_{args.animate_label}_{args.animate_side}.gif"
            make_localization_animation(match, f"{args.animate_side}_", anim_path, x_heater)
            print(f"wrote {anim_path}")


if __name__ == "__main__":
    main()
