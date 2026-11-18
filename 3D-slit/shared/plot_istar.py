#!/usr/bin/env python3
"""
plot_istar.py -- sanity plots for an I* surrogate sweep (istar_sweep.py output).

Usage (from <track>/condor/):
  python3 ../../shared/plot_istar.py istar_table.csv [--points istar_points.csv] \
      [--out istar_overview.png] [--title "electrothermal"]

Panels (one PNG):
  (a) I*/Ic(T0) vs T0, colored by log10 ramp rate, bars = final bracket
  (b) I*/Ic(T0) vs ramp rate (log x), colored by T0
  (c) I* in amps vs T0, with Ic(T0) for reference (colored by ramp)
  (d) design space (T0, ramp) colored by I*/Ic -- coverage + surface shape
Also <out>_margin.png: absolute margin I*-Ic(T0) in A (right axis: the
equivalent temperature margin, (I*-Ic)/(dIc/dT)) vs T0 and vs ramp, the
normalized margin (I*-Ic)/I*, and the design space colored by margin --
the absolute margin shrinks toward Tc even where I*/Ic grows.
With --points, a further PNG (<out>_points.png) shows every run's
stable/runaway/unknown label in (T0, ratio) space, with the I* estimates
overlaid -- what a classifier-style surrogate would be trained on.

Also prints to stdout: anchor (cid 0) value, overall range, any
unconverged / non-monotone / unknown-bearing rows, and residual outliers
from a simple linear fit I*/Ic ~ T0 + log10(ramp) (|resid| > 2.5 sigma) --
a cheap check for a condition that doesn't follow its neighbors.
"""
import argparse
import csv
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize

TC = 90.0
IC77 = 310.96   # A, Ic at 77 K (JcT linear in T, zero at Tc)


def ic_at(t0):
    return IC77 * (TC - np.asarray(t0, float)) / (TC - 77.0)


def read_csv(path):
    with open(path) as fh:
        return list(csv.DictReader(fh))


def fnum(rows, key):
    return np.array([float(r[key]) if r[key] not in ("", None) else np.nan for r in rows])


def report(rows, t0, ramp, ist, lo, hi):
    print(f"{len(rows)} conditions")
    anc = [i for i, r in enumerate(rows) if int(r["cid"]) == 0]
    if anc:
        i = anc[0]
        print(f"anchor cid 0 (T0={t0[i]:.1f} K, {ramp[i]:.1f} A/s): "
              f"I*/Ic = {ist[i]:.4f}  [{lo[i]:.4f}, {hi[i]:.4f}]  "
              f"(Bfield no-heater ramp20 reference ~1.13-1.14)")
    ok = np.isfinite(ist)
    print(f"I*/Ic range: {np.nanmin(ist):.4f} .. {np.nanmax(ist):.4f}  "
          f"(spread {np.nanmax(ist) - np.nanmin(ist):.4f})")
    for r in rows:
        flags = []
        if r.get("converged") == "0":
            flags.append("NOT converged")
        if r.get("monotone") == "0":
            flags.append("NON-MONOTONE")
        if r.get("n_unknown") not in (None, "", "0"):
            flags.append(f"{r['n_unknown']} unknown")
        if flags:
            print(f"  c{int(r['cid']):03d}: " + ", ".join(flags))
    if ok.sum() >= 5:
        X = np.column_stack([np.ones(ok.sum()), t0[ok], np.log10(ramp[ok])])
        coef, *_ = np.linalg.lstsq(X, ist[ok], rcond=None)
        res = ist[ok] - X @ coef
        sd = res.std(ddof=3) if ok.sum() > 3 else np.nan
        print(f"linear fit: I*/Ic = {coef[0]:.4f} + {coef[1]:+.5f}*T0 "
              f"+ {coef[2]:+.4f}*log10(ramp);  resid sd = {sd:.4f}")
        idx = np.flatnonzero(ok)
        for j, rj in zip(idx, res):
            if sd > 0 and abs(rj) > 2.5 * sd:
                print(f"  OUTLIER c{int(rows[j]['cid']):03d} (T0={t0[j]:.1f}, "
                      f"{ramp[j]:.1f} A/s): resid {rj:+.4f} ({rj / sd:+.1f} sd)")
    return ok


def style(ax):
    ax.grid(True, color="0.88", linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def overview(rows, out, title):
    t0, ramp = fnum(rows, "t0"), fnum(rows, "ramp_rate")
    ist, lo, hi = fnum(rows, "istar_ratio"), fnum(rows, "ratio_lo"), fnum(rows, "ratio_hi")
    istA = fnum(rows, "istar_A")
    ok = report(rows, t0, ramp, ist, lo, hi)
    cids = np.array([int(r["cid"]) for r in rows])

    rnorm = LogNorm(vmin=np.nanmin(ramp), vmax=np.nanmax(ramp))
    tnorm = Normalize(vmin=np.nanmin(t0), vmax=np.nanmax(t0))
    cmap = plt.get_cmap("viridis")
    yerr = np.vstack([ist - lo, hi - ist])

    fig, axs = plt.subplots(2, 2, figsize=(12, 9.5), constrained_layout=True)
    (a, b), (c, d) = axs

    # (a) ratio vs T0
    a.errorbar(t0[ok], ist[ok], yerr=yerr[:, ok], fmt="none", ecolor="0.6",
               elinewidth=1, capsize=2, zorder=1)
    sc = a.scatter(t0[ok], ist[ok], c=ramp[ok], cmap=cmap, norm=rnorm, s=46,
                   edgecolors="white", linewidths=0.8, zorder=2)
    anc = ok & (cids == 0)
    a.scatter(t0[anc], ist[anc], s=170, facecolors="none", edgecolors="black",
              linewidths=1.4, zorder=3, label="anchor (77 K, 20 A/s)")
    a.set_xlabel("T0 (K)")
    a.set_ylabel("I* / Ic(T0)")
    a.set_title("(a) I*/Ic vs bath temperature", loc="left")
    a.legend(loc="best", frameon=False, fontsize=9)
    fig.colorbar(sc, ax=a, label="ramp rate (A/s)")
    style(a)

    # (b) ratio vs ramp
    b.errorbar(ramp[ok], ist[ok], yerr=yerr[:, ok], fmt="none", ecolor="0.6",
               elinewidth=1, capsize=2, zorder=1)
    sc = b.scatter(ramp[ok], ist[ok], c=t0[ok], cmap=cmap, norm=tnorm, s=46,
                   edgecolors="white", linewidths=0.8, zorder=2)
    b.scatter(ramp[anc], ist[anc], s=170, facecolors="none", edgecolors="black",
              linewidths=1.4, zorder=3)
    b.set_xscale("log")
    b.set_xlabel("ramp rate (A/s)")
    b.set_ylabel("I* / Ic(T0)")
    b.set_title("(b) I*/Ic vs ramp rate", loc="left")
    fig.colorbar(sc, ax=b, label="T0 (K)")
    style(b)

    # (c) absolute I* with Ic(T0)
    tt = np.linspace(np.nanmin(t0) - 0.5, np.nanmax(t0) + 0.5, 100)
    c.plot(tt, ic_at(tt), color="0.35", linewidth=2, label="Ic(T0)")
    sc = c.scatter(t0[ok], istA[ok], c=ramp[ok], cmap=cmap, norm=rnorm, s=46,
                   edgecolors="white", linewidths=0.8, zorder=2)
    c.scatter([], [], s=46, color="0.55", label="I* (color = ramp rate)")
    c.set_xlabel("T0 (K)")
    c.set_ylabel("current (A)")
    c.set_title("(c) I* in amps, with Ic(T0)", loc="left")
    c.legend(loc="upper right", frameon=False, fontsize=9)
    fig.colorbar(sc, ax=c, label="ramp rate (A/s)")
    style(c)

    # (d) design space colored by ratio
    sc = d.scatter(t0[ok], ramp[ok], c=ist[ok], cmap=cmap, s=90,
                   edgecolors="white", linewidths=0.8, zorder=2)
    if (~ok).any():
        d.scatter(t0[~ok], ramp[~ok], marker="x", color="black", s=60,
                  label="no I* (unbracketed)")
        d.legend(loc="best", frameon=False, fontsize=9)
    for x, y, cid in zip(t0, ramp, cids):
        d.annotate(f"{cid}", (x, y), xytext=(5, 4), textcoords="offset points",
                   fontsize=7, color="0.35")
    d.set_yscale("log")
    d.set_xlabel("T0 (K)")
    d.set_ylabel("ramp rate (A/s)")
    d.set_title("(d) design points, colored by I*/Ic (labels = cid)", loc="left")
    fig.colorbar(sc, ax=d, label="I* / Ic(T0)")
    style(d)

    if title:
        fig.suptitle(title, fontsize=13)
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


def points_plot(rows, pts, out, title):
    t0 = np.array([float(p["t0"]) for p in pts])
    ratio = np.array([float(p["ratio"]) for p in pts])
    outc = np.array([p["outcome"] for p in pts])
    fig, ax = plt.subplots(figsize=(10, 6.5), constrained_layout=True)
    spec = {"stable": dict(marker="o", color="#2a78b5", label="stable"),
            "runaway": dict(marker="^", color="#c8553d", label="runaway"),
            "unknown": dict(marker="s", color="0.45", label="unknown")}
    for k, kw in spec.items():
        m = outc == k
        if m.any():
            ax.scatter(t0[m], ratio[m], s=18, alpha=0.75, linewidths=0,
                       **{**kw, "label": f"{kw['label']} ({m.sum()})"})
    it0 = fnum(rows, "t0")
    ist = fnum(rows, "istar_ratio")
    ax.scatter(it0, ist, marker="_", s=260, color="black", linewidths=2,
               label="I* estimate", zorder=3)
    ax.axhline(1.0, color="0.4", linewidth=1, linestyle="--", zorder=0)
    ax.set_xlabel("T0 (K)")
    ax.set_ylabel("I / Ic(T0)")
    ax.set_title("Every run by outcome" + (f" -- {title}" if title else ""), loc="left")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
    style(ax)
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


def margin_plot(rows, out, title):
    """Margin of I* above Ic(T0). Absolute margin I*-Ic (A) shrinks toward Tc
    even where I*/Ic grows, since it's (I*/Ic - 1)*Ic(T0) and Ic -> 0 at Tc.
    With JcT linear, it's also a temperature margin: dIc/dT = IC77/(Tc-77)
    A/K, so (I*-Ic)/(dIc/dT) = how far T0 would have to DROP for Ic to reach
    I* (shown as the right-hand axis -- same quantity, unit conversion only).
    Normalized margin (I*-Ic)/I* = 1 - Ic/I* is monotone in I*/Ic, shown for
    completeness; it carries the same trend as the ratio."""
    t0, ramp = fnum(rows, "t0"), fnum(rows, "ramp_rate")
    ist, lo, hi = fnum(rows, "istar_ratio"), fnum(rows, "ratio_lo"), fnum(rows, "ratio_hi")
    ok = np.isfinite(ist)
    ic = ic_at(t0)
    mA = (ist - 1.0) * ic
    mA_err = np.vstack([(ist - lo) * ic, (hi - ist) * ic])
    mN = 1.0 - 1.0 / ist
    dicdt = IC77 / (TC - 77.0)
    cids = np.array([int(r["cid"]) for r in rows])
    anc = ok & (cids == 0)

    print(f"absolute margin I*-Ic: {np.nanmin(mA):.1f} .. {np.nanmax(mA):.1f} A "
          f"(= {np.nanmin(mA) / dicdt:.2f} .. {np.nanmax(mA) / dicdt:.2f} K at "
          f"{dicdt:.2f} A/K); normalized (I*-Ic)/I*: {np.nanmin(mN):.4f} .. {np.nanmax(mN):.4f}")
    if anc.any():
        i = np.flatnonzero(anc)[0]
        print(f"anchor margin: {mA[i]:.1f} A = {mA[i] / dicdt:.2f} K, normalized {mN[i]:.4f}")

    rnorm = LogNorm(vmin=np.nanmin(ramp), vmax=np.nanmax(ramp))
    tnorm = Normalize(vmin=np.nanmin(t0), vmax=np.nanmax(t0))
    cmap = plt.get_cmap("viridis")
    fig, axs = plt.subplots(2, 2, figsize=(12, 9.5), constrained_layout=True)
    (a, b), (c, d) = axs

    def kaxis(ax):
        sec = ax.secondary_yaxis("right", functions=(lambda y: y / dicdt, lambda k: k * dicdt))
        sec.set_ylabel("equivalent temperature margin (K)")

    a.errorbar(t0[ok], mA[ok], yerr=mA_err[:, ok], fmt="none", ecolor="0.6",
               elinewidth=1, capsize=2, zorder=1)
    sc = a.scatter(t0[ok], mA[ok], c=ramp[ok], cmap=cmap, norm=rnorm, s=46,
                   edgecolors="white", linewidths=0.8, zorder=2)
    a.scatter(t0[anc], mA[anc], s=170, facecolors="none", edgecolors="black",
              linewidths=1.4, zorder=3, label="anchor (77 K, 20 A/s)")
    a.set_xlabel("T0 (K)")
    a.set_ylabel("I* - Ic(T0) (A)")
    a.set_title("(a) absolute margin vs bath temperature", loc="left")
    a.legend(loc="best", frameon=False, fontsize=9)
    kaxis(a)
    fig.colorbar(sc, ax=a, label="ramp rate (A/s)", pad=0.02)
    style(a)

    b.errorbar(ramp[ok], mA[ok], yerr=mA_err[:, ok], fmt="none", ecolor="0.6",
               elinewidth=1, capsize=2, zorder=1)
    sc = b.scatter(ramp[ok], mA[ok], c=t0[ok], cmap=cmap, norm=tnorm, s=46,
                   edgecolors="white", linewidths=0.8, zorder=2)
    b.scatter(ramp[anc], mA[anc], s=170, facecolors="none", edgecolors="black",
              linewidths=1.4, zorder=3)
    b.set_xscale("log")
    b.set_xlabel("ramp rate (A/s)")
    b.set_ylabel("I* - Ic(T0) (A)")
    b.set_title("(b) absolute margin vs ramp rate", loc="left")
    kaxis(b)
    fig.colorbar(sc, ax=b, label="T0 (K)", pad=0.02)
    style(b)

    sc = c.scatter(t0[ok], mN[ok], c=ramp[ok], cmap=cmap, norm=rnorm, s=46,
                   edgecolors="white", linewidths=0.8, zorder=2)
    c.scatter(t0[anc], mN[anc], s=170, facecolors="none", edgecolors="black",
              linewidths=1.4, zorder=3)
    c.set_xlabel("T0 (K)")
    c.set_ylabel("(I* - Ic) / I*")
    c.set_title("(c) normalized margin (= 1 - Ic/I*, same trend as I*/Ic)", loc="left")
    fig.colorbar(sc, ax=c, label="ramp rate (A/s)")
    style(c)

    sc = d.scatter(t0[ok], ramp[ok], c=mA[ok], cmap=cmap, s=90,
                   edgecolors="white", linewidths=0.8, zorder=2)
    for x, y, cid in zip(t0, ramp, cids):
        d.annotate(f"{cid}", (x, y), xytext=(5, 4), textcoords="offset points",
                   fontsize=7, color="0.35")
    d.set_yscale("log")
    d.set_xlabel("T0 (K)")
    d.set_ylabel("ramp rate (A/s)")
    d.set_title("(d) design points, colored by I* - Ic (A)", loc="left")
    fig.colorbar(sc, ax=d, label="I* - Ic(T0) (A)")
    style(d)

    if title:
        fig.suptitle(title + " -- margin above Ic(T0)", fontsize=13)
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("table", help="istar_table.csv from `istar_sweep.py istar`")
    p.add_argument("--points", help="istar_points.csv from `istar_sweep.py points`")
    p.add_argument("--out", default="istar_overview.png")
    p.add_argument("--title", default="")
    a = p.parse_args()
    rows = read_csv(a.table)
    overview(rows, a.out, a.title)
    o = Path(a.out)
    margin_plot(rows, str(o.with_name(o.stem + "_margin" + o.suffix)), a.title)
    if a.points:
        points_plot(rows, read_csv(a.points), str(o.with_name(o.stem + "_points" + o.suffix)),
                    a.title)


if __name__ == "__main__":
    main()
