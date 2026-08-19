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
                                final_Tmax, final_fracLeft)
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


def read_csv_columns(csv_path: Path):
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {}
    columns = {}
    for col in rows[0].keys():
        values = [r[col] for r in rows]
        try:
            columns[col] = np.array([float(v) for v in values], dtype="f8")
        except ValueError:
            # Not uniformly numeric (e.g. positions' channel/type/side/notes)
            columns[col] = np.array(values, dtype=h5py.string_dtype(encoding="utf-8"))
    return columns


def write_csv_group(parent_group, subgroup_name, csv_path: Path):
    if not csv_path.exists():
        print(f"  ({csv_path.name} not found, skipping /{subgroup_name})")
        return
    columns = read_csv_columns(csv_path)
    if not columns:
        print(f"  ({csv_path.name} empty, skipping /{subgroup_name})")
        return
    sub = parent_group.create_group(subgroup_name)
    for col, arr in columns.items():
        sub.create_dataset(col, data=arr)


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
            write_csv_group(g, "transient", run_dir / TRANSIENT_CSV)
            write_csv_group(g, "diagnostics", run_dir / DIAGNOSTICS_CSV)
            write_csv_group(g, "positions", run_dir / POSITIONS_CSV)
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
