#!/usr/bin/env python3
"""
istar_sweep.py -- drives the I* surrogate-training sweep for EITHER 3D-slit
workflow (Bfield/ or electrothermal/): heater OFF, varying bath temperature
T0 and ramp rate, with the current ratio sampled ADAPTIVELY per (T0, ramp)
condition instead of on a dense fixed grid (the 801-ratio-per-condition
approach used for the single-condition ramp20 sweeps is unaffordable across
many conditions). Track-specific physics flags live in each track's
condor/sweep_istar.sub; this script only produces/reads
`ratio,label,t0,ramp_rate` rows and status.json files, which are identical
across tracks.

I* := the transport-current boundary between stable and runaway, expressed as
I*/Ic(T0) (the -ratio both step scripts take is ALREADY relative to Ic(T0),
see -tzero) and as absolute amps.

Workflow (one Condor submission per round, from <track>/condor/):

  1. conditions -- space-filling (scrambled Sobol) design over
       T0 in [t0-lo, t0-hi] K  x  log10(ramp) in [log10 ramp-lo, log10 ramp-hi]
     plus the (77 K, 20 A/s) anchor. For Bfield it must reproduce the
     ramp20 no-heater sweep's I* ~1.13-1.14 (sanity check on the plumbing).
     Use the SAME conditions.csv for both tracks so their I* are paired.
       python3 ../../shared/istar_sweep.py conditions --n 32 > conditions.csv

  2. round1 -- coarse ratio grid for every condition.
       python3 ../../shared/istar_sweep.py round1 conditions.csv > istar_queue.txt
       ./make_payload.sh && condor_submit sweep_istar.sub

  3. refine -- once a round lands, read every status.json, find each
     condition's bracket (highest stable ratio < lowest runaway ratio) and
     emit new ratios strictly inside it. Repeat until no new jobs.
       python3 ../../shared/istar_sweep.py refine conditions.csv \
           --runs-dir <landed runs dir> > istar_queue.txt

  4. istar -- the per-condition I* table (one surrogate target row each).
       python3 ../../shared/istar_sweep.py istar conditions.csv \
           --runs-dir <landed runs dir> > istar_table.csv

Every individual run is ALSO a labeled training point
(t0, ramp_rate, ratio) -> stable/runaway; `points` dumps that table:
       python3 ../../shared/istar_sweep.py points conditions.csv \
           --runs-dir <landed runs dir> > istar_points.csv

Outcome classification (status.json only, no CSV needed -- cheap enough to
run on the submit node) mirrors analyze_sweep_hdf5.py's outcome_label()
blind-spot handling for no-heater runs: a symmetric full-tape runaway keeps
fracLeft at 0.5 and so can come back as "reached_end_no_deviation" with Tmax
in the hundreds of K -- final_Tmax >= Tc is therefore treated as runaway
regardless of raw status. wall_budget_exceeded / crashed / etc. are UNKNOWN
and never move a bracket edge (they cluster right at the threshold, see
runs/sweep_noheater_ramp20.README.md).
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

TC = 90.0                # hts_materials.idp Tc
JC_REF_SPAN = 40.0        # hts_materials.idp: JcT = Jc0*(Tc-T)/(Tc-50)
# Ic(77K) = 310.96 A -- measured from a real run's logged I0 (Bfield/CLAUDE.md
# "I0 write-lag fix"), cross-checked against electrothermal. JcT is linear
# in T, so Ic(T0) = IC77 * (Tc-T0)/(Tc-77). The .edp also prints
# "[tzero] ... IcRebcoActual=" into run.log as ground truth.
IC77 = 310.96

ANCHOR = (77.0, 20.0)
STABLE_STATUSES = {"settled", "reached_end_no_deviation", "reached_end_deviated",
                   "plateaued_off_parity"}
# electrothermal splits pure-overcurrent runaway (Tmax cutoff hit while still
# ramping) into its own status; for I* both are simply "ran away".
RUNAWAY_STATUSES = {"runaway", "runaway_before_pulse"}


def ic_at(t0):
    return IC77 * (TC - t0) / (TC - 77.0)


def sanitize_label(ratio):
    # Must stay identical to run_bfield_transient.sanitize_label and
    # run_transient.sanitize_label (checked equal when this was written) --
    # Condor labels are generated here, not by the wrappers.
    s = f"{ratio:.4f}".rstrip("0").rstrip(".")
    return "r" + s.replace(".", "p").replace("-", "neg")


def label_for(cid, ratio, suffix):
    return f"is-c{cid:03d}-{sanitize_label(ratio)}{suffix}"


def read_conditions(path):
    with open(path) as fh:
        return [{"cid": int(r["cid"]), "t0": float(r["t0"]), "ramp_rate": float(r["ramp_rate"])}
                for r in csv.DictReader(fh)]


def emit_rows(rows, out):
    seen = set()
    for cid, t0, ramp, ratio, label in rows:
        if label in seen:
            sys.exit(f"label collision: {label}")
        seen.add(label)
        out.write(f"{ratio:.6f},{label},{t0:.4f},{ramp:.4f}\n")


def classify(status):
    """-> 'runaway' | 'stable' | 'unknown'"""
    s = status.get("status")
    tmax = status.get("final_Tmax")
    if s in RUNAWAY_STATUSES:
        return "runaway"
    if tmax is not None and tmax >= TC and s in STABLE_STATUSES | {"max_steps_exceeded"}:
        return "runaway"     # symmetric full-tape quench the live classifier can't see
    if s in STABLE_STATUSES and tmax is not None and tmax < TC:
        return "stable"
    return "unknown"


def load_results(conds, runs_dir, suffix):
    """{cid: [(ratio, outcome, status_dict), ...]} from runs_dir/is-cNNN-*<suffix>/status.json"""
    runs_dir = Path(runs_dir)
    by_cid = {c["cid"]: [] for c in conds}
    for cid in by_cid:
        for p in sorted(runs_dir.glob(f"is-c{cid:03d}-r*{suffix}/status.json")):
            st = json.loads(p.read_text())
            if suffix and not p.parent.name.endswith(suffix):
                continue
            by_cid[cid].append((float(st["ratio"]), classify(st), st))
    for v in by_cid.values():
        v.sort(key=lambda x: x[0])
    return by_cid


def bracket(results):
    """(lo, hi, monotone): lo = highest stable ratio below the lowest runaway
    ratio, hi = lowest runaway. None where no such point exists.
    monotone=False if any stable ratio sits ABOVE a runaway one."""
    run_r = [r for r, o, _ in results if o == "runaway"]
    stab_r = [r for r, o, _ in results if o == "stable"]
    hi = min(run_r) if run_r else None
    lo_cands = [r for r in stab_r if hi is None or r < hi]
    lo = max(lo_cands) if lo_cands else None
    monotone = not (hi is not None and any(r > hi for r in stab_r))
    return lo, hi, monotone


# ----------------------------------------------------------------- commands --

def cmd_conditions(a):
    from scipy.stats import qmc
    m = int(round(math.log2(a.n)))
    if 2 ** m != a.n:
        sys.exit("--n must be a power of 2 (Sobol balance)")
    pts = qmc.Sobol(d=2, scramble=True, seed=a.seed).random_base2(m)
    lr0, lr1 = math.log10(a.ramp_lo), math.log10(a.ramp_hi)
    w = csv.writer(sys.stdout)
    w.writerow(["cid", "t0", "ramp_rate", "ic_t0_A"])
    w.writerow([0, f"{ANCHOR[0]:.4f}", f"{ANCHOR[1]:.4f}", f"{ic_at(ANCHOR[0]):.3f}"])
    for i, (u, v) in enumerate(pts, start=1):
        t0 = a.t0_lo + u * (a.t0_hi - a.t0_lo)
        ramp = 10 ** (lr0 + v * (lr1 - lr0))
        w.writerow([i, f"{t0:.4f}", f"{ramp:.4f}", f"{ic_at(t0):.3f}"])


def cmd_round1(a):
    conds = read_conditions(a.conditions)
    n = a.n_ratios
    ratios = [round(a.lo + i * (a.hi - a.lo) / (n - 1), 6) for i in range(n)]
    rows = []
    for c in conds:
        for r in ratios:
            rows.append((c["cid"], c["t0"], c["ramp_rate"], r,
                         label_for(c["cid"], r, a.label_suffix)))
    emit_rows(rows, sys.stdout)
    # Worst-case above-Ic dwell (drives cost: ~170 s/physical step, see
    # Bfield/CLAUDE.md) -- the low-T0/slow-ramp corner is the risk.
    # Runs past I* run away soon after crossing it, so the dwell that
    # matters is Ic -> ~I*; 1.14 (the measured 77K/20A/s no-heater I*) used
    # as a common yardstick for every condition.
    def dwell(c):
        return 0.14 * ic_at(c["t0"]) / c["ramp_rate"]
    ref = dwell({"t0": ANCHOR[0], "ramp_rate": ANCHOR[1]})
    worst = max(conds, key=dwell)
    print(f"# {len(rows)} jobs; longest Ic->1.14Ic ramp dwell: cid {worst['cid']} "
          f"(T0={worst['t0']:.1f}K, {worst['ramp_rate']:.1f}A/s) = {dwell(worst):.1f}s, "
          f"{dwell(worst) / ref:.1f}x the 77K/20A/s anchor ({ref:.1f}s, which "
          f"took ~10h wall near threshold)", file=sys.stderr)
    slow = [c["cid"] for c in conds if dwell(c) > 2 * ref]
    if slow:
        print(f"# WARNING: {len(slow)} conditions have >2x the anchor's above-Ic dwell "
              f"and may hit the 18h wall budget: cids {slow}", file=sys.stderr)


def cmd_refine(a):
    conds = read_conditions(a.conditions)
    res = load_results(conds, a.runs_dir, a.label_suffix)
    rows, done, report = [], 0, []
    for c in conds:
        cid = c["cid"]
        tried = {round(r, 6) for r, _, _ in res[cid]}
        lo, hi, mono = bracket(res[cid])
        if not res[cid]:
            report.append(f"c{cid:03d}: no results yet -- skipped")
            continue
        if hi is None:            # never ran away: extend upward
            top = max(tried)
            new = [top + a.extend_step * k for k in range(1, a.n_ratios + 1)]
            report.append(f"c{cid:03d}: no runaway <= {top} -- extending up")
        elif lo is None:          # ran away everywhere tried: extend downward
            bot = min(tried)
            new = [bot - a.extend_step * k for k in range(1, a.n_ratios + 1)]
            report.append(f"c{cid:03d}: runaway at all ratios >= {bot} -- extending down")
        elif hi - lo <= a.tol:
            done += 1
            if not mono:
                report.append(f"c{cid:03d}: converged [{lo},{hi}] but NON-MONOTONE -- inspect")
            continue
        else:
            step = (hi - lo) / (a.n_ratios + 1)
            new = [lo + step * k for k in range(1, a.n_ratios + 1)]
            if not mono:
                report.append(f"c{cid:03d}: NON-MONOTONE outcomes, refining lowest flip [{lo},{hi}]")
        for r in new:
            r = round(r, 6)
            if r in tried or r <= 0:
                continue
            rows.append((cid, c["t0"], c["ramp_rate"], r, label_for(cid, r, a.label_suffix)))
    emit_rows(rows, sys.stdout)
    for line in report:
        print("# " + line, file=sys.stderr)
    print(f"# {done}/{len(conds)} conditions converged (bracket <= {a.tol}); "
          f"{len(rows)} new jobs", file=sys.stderr)


def cmd_istar(a):
    conds = read_conditions(a.conditions)
    res = load_results(conds, a.runs_dir, a.label_suffix)
    w = csv.writer(sys.stdout)
    w.writerow(["cid", "t0", "ramp_rate", "ic_t0_A", "ratio_lo", "ratio_hi",
                "istar_ratio", "istar_A", "bracket_width", "n_runs", "n_unknown",
                "monotone", "converged"])
    for c in conds:
        lo, hi, mono = bracket(res[c["cid"]])
        n_unk = sum(1 for _, o, _ in res[c["cid"]] if o == "unknown")
        ic = ic_at(c["t0"])
        if lo is not None and hi is not None:
            mid = 0.5 * (lo + hi)
            row = [f"{lo:.6f}", f"{hi:.6f}", f"{mid:.6f}", f"{mid * ic:.3f}", f"{hi - lo:.6f}"]
        else:
            row = [lo if lo is not None else "", hi if hi is not None else "", "", "", ""]
        conv = lo is not None and hi is not None and (hi - lo) <= a.tol
        w.writerow([c["cid"], c["t0"], c["ramp_rate"], f"{ic:.3f}", *row,
                    len(res[c["cid"]]), n_unk, int(mono), int(conv)])


def cmd_points(a):
    conds = read_conditions(a.conditions)
    res = load_results(conds, a.runs_dir, a.label_suffix)
    w = csv.writer(sys.stdout)
    w.writerow(["cid", "t0", "ramp_rate", "ratio", "current_A", "outcome", "status",
                "final_Tmax", "final_t", "wall_clock_seconds"])
    for c in conds:
        for r, o, st in res[c["cid"]]:
            w.writerow([c["cid"], c["t0"], c["ramp_rate"], r, f"{r * ic_at(c['t0']):.3f}",
                        o, st.get("status"), st.get("final_Tmax"), st.get("final_t"),
                        st.get("wall_clock_seconds")])


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("conditions")
    s.add_argument("--n", type=int, default=32, help="Sobol points (power of 2); +1 anchor")
    s.add_argument("--t0-lo", type=float, default=65.0)
    s.add_argument("--t0-hi", type=float, default=85.0)
    s.add_argument("--ramp-lo", type=float, default=10.0)
    s.add_argument("--ramp-hi", type=float, default=300.0)
    s.add_argument("--seed", type=int, default=20261112)
    s.set_defaults(fn=cmd_conditions)

    for name, fn in (("round1", cmd_round1), ("refine", cmd_refine),
                     ("istar", cmd_istar), ("points", cmd_points)):
        s = sub.add_parser(name)
        s.add_argument("conditions")
        s.add_argument("--label-suffix", default="", help="appended to every label")
        if name != "round1":
            s.add_argument("--runs-dir", required=True,
                           help="directory holding the landed is-cNNN-r*/status.json dirs")
            s.add_argument("--tol", type=float, default=0.005,
                           help="bracket width (in ratio) counted as converged")
        if name in ("round1", "refine"):
            s.add_argument("--n-ratios", type=int, default=21 if name == "round1" else 11)
        if name == "round1":
            s.add_argument("--lo", type=float, default=0.95)
            s.add_argument("--hi", type=float, default=1.45)
        if name == "refine":
            s.add_argument("--extend-step", type=float, default=0.05,
                           help="ratio spacing used when no bracket exists yet")
        s.set_defaults(fn=fn)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
