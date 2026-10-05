#!/usr/bin/env python3
"""
export_sweep_hdf5.py -- converts a completed run_transient.py/sweep_transient.py
sweep (plain-text CSVs under runs/<label>/, one label per transport-current
ratio) into a single HDF5 file for handoff, since FreeFEM itself only writes
plain text and its own HDF5 plugin (iohdf5) is a mesh/field visualization
exporter, not a fit for this tabular time-series data (see CLAUDE.md).

Structure written to the output file:
  /<label>                     group, one per run, attrs = that run's
                                status.json fields (ratio, status, trend,
                                n_steps, wall_clock_seconds, final_t,
                                final_Tmax, final_fracLeft) PLUS `outcome`:
                                the already-reconciled human-readable label
                                (analyze_sweep_hdf5.py's outcome_label()),
                                not just the raw `status` string -- some
                                statuses (e.g. reached_end_deviated) don't
                                mean what they sound like on their own (a
                                handful in this dataset are actually still-
                                diverging runaways that simply ran out of
                                observation time) -- `outcome` is the field
                                a standalone reader of this file (without
                                also re-deriving that logic) should trust.
  /<label>/transient/<col>     one dataset per transient_3d_slit.csv column
  /<label>/diagnostics/<col>   one dataset per diagnostics_3d_slit.csv column
  /<label>/positions/<col>     one dataset per diagnostics_positions_3d_slit.csv
                                column (numeric columns as float64, the rest
                                as UTF-8 strings)

Requires h5py (`pip install h5py --break-system-packages` if needed).

Usage:
  python3 export_sweep_hdf5.py                      # auto-discovers all
                                                      # runs/*/status.json
  python3 export_sweep_hdf5.py --labels r0p5,r0p7
  python3 export_sweep_hdf5.py --out runs/sweep.h5
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import h5py
except ImportError:
    sys.exit("h5py is required -- pip install h5py --break-system-packages")
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
TRANSIENT_CSV = "transient_3d_slit.csv"
DIAGNOSTICS_CSV = "diagnostics_3d_slit.csv"
POSITIONS_CSV = "diagnostics_positions_3d_slit.csv"


def discover_labels(base_dir: Path):
    return sorted(p.parent.name for p in base_dir.glob("*/status.json"))


MISSING_TOKENS = {"", "n/a", "na", "-", "nan"}


def parse_float_or_missing(value):
    # diagnostics_positions_3d_slit.csv writes "n/a" for channels with no
    # discrete z-position (e.g. V_CL_plus/V_CL_minus, current-lead reference
    # taps) -- treat that as NaN rather than letting one placeholder value
    # demote an otherwise-numeric column (e.g. z_m) to strings entirely.
    if value.strip().lower() in MISSING_TOKENS:
        return float("nan")
    return float(value)


def read_csv_columns(csv_path: Path):
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {}
    columns = {}
    for col in rows[0].keys():
        values = [r[col] for r in rows]
        try:
            columns[col] = np.array([parse_float_or_missing(v) for v in values], dtype="f8")
        except ValueError:
            # Genuinely non-numeric (e.g. positions' channel/type/side/notes)
            columns[col] = np.array(values, dtype=h5py.string_dtype(encoding="utf-8"))
    return columns


def write_csv_group(parent_group, subgroup_name, csv_path: Path):
    if not csv_path.exists():
        print(f"  ({csv_path.name} not found, skipping /{subgroup_name})")
        return None
    columns = read_csv_columns(csv_path)
    if not columns:
        print(f"  ({csv_path.name} empty, skipping /{subgroup_name})")
        return None
    sub = parent_group.create_group(subgroup_name)
    for col, arr in columns.items():
        sub.create_dataset(col, data=arr)
    return columns


def compute_outcome(status: dict, transient_columns):
    # The human-readable, already-reconciled outcome label (see
    # analyze_sweep_hdf5.py's outcome_label()) baked directly into the
    # exported file, so a colleague reading sweep.h5 in isolation -- without
    # also replicating analyze_sweep_hdf5.py's reclassification logic --
    # doesn't get misled by the raw `status` attr alone. Concretely: this
    # dataset has runs stored as status="reached_end_deviated" (reads like
    # "still settling, ran out of time") whose own Tmax was still clearly
    # diverging when the run ended -- outcome_label() catches exactly this
    # via recompute_tmax_trend() against the full time series, so this is
    # that same logic, reused rather than reimplemented, just called here
    # at export time instead of analysis time (see CLAUDE.md).
    #
    # Imports analyze_sweep_hdf5 lazily, not at module load, so this
    # script's own dependencies stay light (plain csv/json/h5py/numpy) for
    # anyone who just wants the raw CSV-to-HDF5 conversion -- it pulls in
    # matplotlib and the shared plotting modules only when an outcome
    # actually needs computing.
    import analyze_sweep_hdf5 as ash
    run = {
        "status": status.get("status"),
        "final_Tmax": status.get("final_Tmax"),
        "trend": status.get("trend"),
        "transient": transient_columns or {},
    }
    return ash.outcome_label(run)


def export(labels, base_dir: Path, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(out_path, "w") as hf:
        hf.attrs["created"] = datetime.now(timezone.utc).isoformat()
        hf.attrs["source"] = "3D-slit/electrothermal run_transient.py/sweep_transient.py"
        for label in labels:
            run_dir = base_dir / label
            status_path = run_dir / "status.json"
            if not status_path.exists():
                print(f"skipping {label}: no status.json (run not finished/found)")
                continue
            print(f"writing /{label}")
            status = json.loads(status_path.read_text())
            g = hf.create_group(label)
            for k, v in status.items():
                g.attrs[k] = "" if v is None else v
            transient_columns = write_csv_group(g, "transient", run_dir / TRANSIENT_CSV)
            write_csv_group(g, "diagnostics", run_dir / DIAGNOSTICS_CSV)
            write_csv_group(g, "positions", run_dir / POSITIONS_CSV)
            g.attrs["outcome"] = compute_outcome(status, transient_columns)
    print(f"wrote {out_path}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--labels", default=None,
                   help="Comma-separated run labels to include (default: "
                        "auto-discover every runs/*/status.json)")
    p.add_argument("--base-dir", default="runs",
                   help="Directory (relative to this script) holding per-run "
                        "subdirectories (default: runs)")
    p.add_argument("--out", default="runs/sweep.h5",
                   help="Output HDF5 file path, relative to this script "
                        "(default: runs/sweep.h5)")
    args = p.parse_args()

    base_dir = SCRIPT_DIR / args.base_dir
    labels = args.labels.split(",") if args.labels else discover_labels(base_dir)
    if not labels:
        sys.exit(f"No runs/*/status.json found under {base_dir}")

    export(labels, base_dir, SCRIPT_DIR / args.out)


if __name__ == "__main__":
    main()
