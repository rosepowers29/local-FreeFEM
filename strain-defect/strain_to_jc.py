"""
strain_to_jc.py -- strain-defect Jc/Jc0 pipeline for the single-tape model.

Pipeline:
  1. Load three ANSYS-exported CSVs (node->strain, node->x, node->y) and
     merge on node ID -- IDENTICAL logic to ~/Downloads/ic_retention_analysis_new.py
     (load_and_merge/build_grid), which this is adapted from.
  2. Apply the Ekin-Weibull Jc/Jc0 model pointwise (jc_retention) -- same
     physics, unchanged.
  3. Width-integrate to get a longitudinal Ic/Ic0(y) profile
     (ic_retention_along_length) -- same, unchanged.
  4. EXTRAPOLATE both the raw 2D Jc/Jc0 field and the width-integrated
     profile from the ANSYS grid onto the FreeFEM mesh's own coordinate
     grid (different grids -- this step didn't exist in the ic_retention
     script, which only ever worked in the ANSYS grid's own coordinates).
  5. Export two FreeFEM-readable table files plus a small metadata .idp
     (array sizes + defect location) that `hts_materials.idp` includes.

Coordinate convention: ANSYS "y" (longitudinal) -> FreeFEM "x" (length);
ANSYS "x" (width) -> FreeFEM "z" (width). ANSYS coordinates are assumed to
be in millimeters (matching ic_retention_analysis_new.py's default column
names, e.g. "LOCX (mm)") and are converted to meters here.

Extrapolation policy: FLAT (nearest-edge-value hold), not linear
extrapolation -- chosen specifically because the ANSYS strain export may not
cover the tape's full length/width, and linear extrapolation could invent an
artificially better/worse Jc/Jc0 outside the measured range and silently
relocate the quench trigger. Implemented by clamping query coordinates into
the ANSYS data's own range before interpolating (not by clamping the
interpolated values), which is exactly equivalent to a flat hold beyond the
data's edges.
"""

import json
import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator


# ---------------------------------------------------------------------------
# Ekin-Weibull Jc/Jc0 model -- identical to ic_retention_analysis_new.py
# ---------------------------------------------------------------------------

def jc_retention(eps_L, a, b, eps_max, eps_irrc, eps_irrt, eps_0c, eps_0t, m_c, m_t):
    """Jc/Jc0 vs. longitudinal strain via the Ekin power law x piecewise Weibull."""
    eps_L = np.asarray(eps_L, dtype=float)

    ekin = (1.0 / (1.0 - a * np.abs(eps_max) ** b)) * \
           (1.0 - a * np.abs(eps_L - eps_max) ** b)

    W = np.full_like(eps_L, np.nan)
    mask_c = eps_L < eps_irrc
    mask_mid = (eps_L >= eps_irrc) & (eps_L <= eps_irrt)
    mask_t = eps_L > eps_irrt

    W[mask_c] = np.exp(-((eps_L[mask_c] - eps_irrc) / eps_0c) ** m_c)
    W[mask_mid] = 1.0
    W[mask_t] = np.exp(-((eps_L[mask_t] - eps_irrt) / eps_0t) ** m_t)

    return ekin * W


NOMINAL_EKIN_PARAMS = dict(
    a=1300, b=1.85, eps_max=0.00035, eps_irrc=-0.01, eps_irrt=0.0045,
    eps_0c=-0.007, eps_0t=0.0021, m_c=1.88, m_t=2,
)


# ---------------------------------------------------------------------------
# Data loading / grid construction -- identical to ic_retention_analysis_new.py
# ---------------------------------------------------------------------------

def load_and_merge(strain_csv, x_csv, y_csv,
                    node_col="node", strain_col="strain",
                    x_col="x", y_col="y",
                    strain_sep=",", x_sep="\t", y_sep="\t"):
    df_strain = pd.read_csv(strain_csv, sep=strain_sep)[[node_col, strain_col]]
    df_x = pd.read_csv(x_csv, sep=x_sep)[[node_col, x_col]]
    df_y = pd.read_csv(y_csv, sep=y_sep)[[node_col, y_col]]

    occurrence_idx = df_strain.groupby(node_col).cumcount()
    max_occurrences = occurrence_idx.max() + 1

    if max_occurrences == 1:
        df_strain["surface"] = "single"
    elif max_occurrences == 2:
        surface_labels = {0: "top", 1: "bottom"}
        df_strain["surface"] = occurrence_idx.map(surface_labels)
        print("Detected 2 strain rows per node. Assuming 1st=top, 2nd=bottom "
              "-- verify against your ANSYS export order.")
    else:
        df_strain["surface"] = occurrence_idx.astype(str)
        print(f"Warning: {max_occurrences} strain rows per node (expected 1 "
              f"or 2) -- labeling by occurrence order.")

    merged = df_strain.merge(df_x, on=node_col, how="inner") \
                       .merge(df_y, on=node_col, how="inner")

    if len(merged) != len(df_strain):
        print(f"Warning: merged node count ({len(merged)}) differs from "
              f"strain CSV node count ({len(df_strain)}).")

    return merged.rename(columns={strain_col: "strain", x_col: "x", y_col: "y"})


def build_grid(df, coord_precision=None, drop_incomplete_columns=False):
    """Pivot (node,x,y,strain) into a structured (y,x) grid. See
    ic_retention_analysis_new.py for the full docstring/rationale -- unchanged."""
    df = df.copy()
    if coord_precision is not None:
        df["x"] = df["x"].round(coord_precision)
        df["y"] = df["y"].round(coord_precision)

    if drop_incomplete_columns:
        counts = df.groupby("x").size()
        full_count = counts.max()
        sparse_x = counts[counts < full_count].index.tolist()
        if sparse_x:
            print(f"Dropping {len(sparse_x)} sparse x-column(s) (likely "
                  f"quadratic-element midside nodes): {sparse_x[:10]}"
                  f"{'...' if len(sparse_x) > 10 else ''}")
            df = df[~df["x"].isin(sparse_x)]

    n_unique_x = df["x"].nunique()
    n_unique_y = df["y"].nunique()
    print(f"Diagnostics: {n_unique_x} unique x (width) values, {n_unique_y} "
          f"unique y (length) values in the native ANSYS grid -- compare "
          f"against --n-z-sample/--n-x-sample to judge whether the FreeFEM "
          f"resampling resolution is coarser than the native data.")

    pivot = df.pivot_table(index="y", columns="x", values="strain")
    x_vals = pivot.columns.to_numpy(dtype=float)
    y_vals = pivot.index.to_numpy(dtype=float)
    strain_grid = pivot.to_numpy(dtype=float)

    n_missing = np.isnan(strain_grid).sum()
    if n_missing > 0:
        print(f"Warning: {n_missing} grid point(s) missing after pivoting -- "
              f"try --coord-precision and/or --drop-incomplete-columns.")

    return x_vals, y_vals, strain_grid


def ic_retention_along_length(x_vals, jc_grid):
    """Width-integrate Jc/Jc0 (trapezoidal) and divide by width -> Ic/Ic0(y)."""
    width = x_vals[-1] - x_vals[0]
    if width <= 0:
        raise ValueError("Width (max(x)-min(x)) must be positive.")
    dx = np.diff(x_vals)
    avg_heights = (jc_grid[:, 1:] + jc_grid[:, :-1]) / 2.0
    integral = np.sum(dx * avg_heights, axis=1)
    return integral / width


def find_global_minimum(y_vals, ic_ratio):
    if np.all(np.isnan(ic_ratio)):
        raise ValueError("Every longitudinal position has NaN Ic/Ic0 -- "
                          "check the 'missing grid point(s)' warning above.")
    idx_min = np.nanargmin(ic_ratio)
    return ic_ratio[idx_min], y_vals[idx_min], idx_min


# ---------------------------------------------------------------------------
# Extrapolation onto the FreeFEM grid (new -- not in ic_retention_analysis_new.py)
# ---------------------------------------------------------------------------

def _clamp(vals, lo, hi):
    return np.clip(vals, lo, hi)


def extrapolate_profile_to_fem_x(y_vals_mm, ic_ratio, x_sample_m):
    """1D flat-extrapolated interpolation of the width-averaged Ic/Ic0(y)
    profile onto FreeFEM's x-sample grid (meters). y_vals_mm is ANSYS's
    longitudinal axis in mm; x_sample_m is FreeFEM's x axis in meters."""
    y_vals_m = y_vals_mm * 1e-3
    order = np.argsort(y_vals_m)
    y_sorted, ic_sorted = y_vals_m[order], ic_ratio[order]
    x_clamped = _clamp(x_sample_m, y_sorted[0], y_sorted[-1])
    return np.interp(x_clamped, y_sorted, ic_sorted)


def extrapolate_grid_to_fem_xz(x_vals_mm, y_vals_mm, jc_grid, x_sample_m, z_sample_m):
    """2D flat-extrapolated interpolation of the raw Jc/Jc0(y,x) field onto a
    FreeFEM (x,z) regular grid (meters). ANSYS x_vals_mm (width) -> FreeFEM
    z; ANSYS y_vals_mm (length) -> FreeFEM x.

    jc_grid has shape (len(y_vals_mm), len(x_vals_mm)) -- RegularGridInterpolator
    wants strictly increasing axes, so sort defensively even though
    build_grid's pivot_table output should already be sorted.
    """
    y_order = np.argsort(y_vals_mm)
    x_order = np.argsort(x_vals_mm)
    y_sorted = y_vals_mm[y_order] * 1e-3
    x_sorted = x_vals_mm[x_order] * 1e-3
    grid_sorted = jc_grid[np.ix_(y_order, x_order)]

    interp = RegularGridInterpolator((y_sorted, x_sorted), grid_sorted,
                                      method="linear", bounds_error=False,
                                      fill_value=None)

    xq = _clamp(x_sample_m, y_sorted[0], y_sorted[-1])
    zq = _clamp(z_sample_m, x_sorted[0], x_sorted[-1])
    XQ, ZQ = np.meshgrid(xq, zq, indexing="ij")
    pts = np.stack([XQ.ravel(), ZQ.ravel()], axis=-1)
    out = interp(pts).reshape(len(xq), len(zq))
    return out   # shape (len(x_sample_m), len(z_sample_m))


# ---------------------------------------------------------------------------
# Consistency / severity validation
# ---------------------------------------------------------------------------

def check_decomposition_consistency(x_sample_m, z_sample_m, jc_grid_xz, ic_ratio_x,
                                     core_width_m, rtol=1e-2):
    """Width-integrate jc_grid_xz over z at each x and compare against
    ic_ratio_x at the same x -- the two tables feed different physics roles
    (1D electrical solve vs. volumetric heating source) and must not
    silently diverge. Returns (max_rel_err, per_x_rel_err)."""
    dz = np.diff(z_sample_m)
    avg = (jc_grid_xz[:, 1:] + jc_grid_xz[:, :-1]) / 2.0
    integral = np.sum(dz * avg, axis=1)
    width = z_sample_m[-1] - z_sample_m[0]
    ic_from_grid = integral / width
    rel_err = np.abs(ic_from_grid - ic_ratio_x) / np.maximum(np.abs(ic_ratio_x), 1e-12)
    max_err = float(np.nanmax(rel_err))
    if max_err > rtol:
        print(f"WARNING: decomposition consistency check FAILED -- "
              f"max relative error {max_err:.4f} exceeds rtol={rtol}. "
              f"The width-integrated 2D grid does not reproduce the 1D "
              f"profile at the same x -- check resampling resolution "
              f"(nzg) before trusting the model.")
    else:
        print(f"Decomposition consistency check OK: max relative error "
              f"{max_err:.4f} (rtol={rtol}).")
    return max_err, rel_err


def check_defect_severity(x_sample_m, z_sample_m, jc_grid_xz, ic_ratio_x, defect_x_m):
    """At the defect x, compare the pointwise minimum of jc_grid_xz against
    the width-averaged ic_ratio_x -- a descriptive measure of how locally
    severe/narrow the defect is (e.g. a width-edge strain concentration vs.
    a broad, gentle dip). step_strain_tape_transient.edp's electrical solve
    is z-resolved (as of the real-data defect this check first caught being
    this severe), so this is informational, NOT a correctness gate the way
    it was under the earlier width-averaged electrical-solve design --
    still worth looking at, since a very high implied fraction means the
    defect is concentrated in a small z-extent, which is useful context for
    interpreting results even though the solve itself now handles it."""
    ix = int(np.argmin(np.abs(x_sample_m - defect_x_m)))
    local_min = float(np.nanmin(jc_grid_xz[ix, :]))
    width_avg = float(ic_ratio_x[ix])
    implied_fraction = width_avg / max(local_min, 1e-12)
    if implied_fraction > 1.0:
        print(f"NOTE: defect is locally severe at x={x_sample_m[ix]:.4f}m -- "
              f"local min Jc/Jc0={local_min:.4f} vs width-avg Ic/Ic0={width_avg:.4f} "
              f"(implied local current-sharing fraction {implied_fraction:.2f}, >1). "
              f"Informational only -- the electrical model is z-resolved and handles "
              f"this directly; this just describes how narrow/severe the defect is.")
    else:
        print(f"Defect severity: implied local current-sharing fraction "
              f"{implied_fraction:.4f} at x={x_sample_m[ix]:.4f}m (broad/mild defect).")
    return implied_fraction


# ---------------------------------------------------------------------------
# FreeFEM export
# ---------------------------------------------------------------------------

def export_freefem_tables(out_dir, x_sample_m, z_sample_m, ic_ratio_x, jc_grid_xz,
                           defect_x_m, defect_ic_ratio):
    import os
    n_x = len(x_sample_m)
    n_z = len(z_sample_m)

    icratio_path = os.path.join(out_dir, "strain_jc_icratio_x.txt")
    with open(icratio_path, "w") as f:
        for xv, rv in zip(x_sample_m, ic_ratio_x):
            f.write(f"{xv:.9e} {rv:.9e}\n")

    grid_path = os.path.join(out_dir, "strain_jc_grid_xz.txt")
    with open(grid_path, "w") as f:
        f.write(" ".join(f"{xv:.9e}" for xv in x_sample_m) + "\n")
        f.write(" ".join(f"{zv:.9e}" for zv in z_sample_m) + "\n")
        for i in range(n_x):
            f.write(" ".join(f"{jc_grid_xz[i, j]:.9e}" for j in range(n_z)) + "\n")

    meta_path = os.path.join(out_dir, "strain_jc_meta.idp")
    with open(meta_path, "w") as f:
        f.write("// AUTO-GENERATED by strain_to_jc.py -- do not hand-edit, "
                "will be overwritten on the next run.\n")
        f.write(f"int nIcRatioX = {n_x};\n")
        f.write(f"int nJcGridX = {n_x};\n")
        f.write(f"int nJcGridZ = {n_z};\n")
        f.write(f"real defectX = {defect_x_m:.9e};\n")

    meta_json_path = os.path.join(out_dir, "strain_jc_meta.json")
    with open(meta_json_path, "w") as f:
        json.dump({
            "n_x": n_x, "n_z": n_z,
            "defect_x_m": defect_x_m, "defect_ic_ratio": float(defect_ic_ratio),
        }, f, indent=2)

    return icratio_path, grid_path, meta_path, meta_json_path


# ---------------------------------------------------------------------------
# End-to-end pipeline entry point
# ---------------------------------------------------------------------------

def run_pipeline(strain_csv, x_csv, y_csv, out_dir,
                  tape_length_m, tape_width_m, core_width_m,
                  n_x_sample, n_z_sample,
                  node_col="Node Number", strain_col="EPTOX ()",
                  x_col="LOCX (mm)", y_col="LOCY (mm)",
                  strain_sep="\t", x_sep="\t", y_sep="\t",
                  coord_precision=None, drop_incomplete_columns=False,
                  ekin_params=None, surface=None):
    if ekin_params is None:
        ekin_params = dict(NOMINAL_EKIN_PARAMS)

    df = load_and_merge(strain_csv, x_csv, y_csv, node_col=node_col,
                         strain_col=strain_col, x_col=x_col, y_col=y_col,
                         strain_sep=strain_sep, x_sep=x_sep, y_sep=y_sep)
    surfaces = sorted(df["surface"].unique())
    # Which shell surface (top/bottom) to use is a physically meaningful
    # choice, not a default to guess at -- an earlier version of this
    # pipeline silently picked the alphabetically-first surface ("bottom"),
    # which happened to disagree with a "top" result the user expected
    # elsewhere. Require it explicitly once there's more than one option.
    if len(surfaces) == 1:
        chosen_surface = surfaces[0]
    elif surface is not None:
        if surface not in surfaces:
            raise ValueError(f"--surface {surface!r} not found in this data; "
                              f"available surfaces: {surfaces}")
        chosen_surface = surface
    else:
        raise ValueError(f"Multiple surfaces detected ({surfaces}) and no --surface "
                          f"given. Which shell surface to use is a physically meaningful "
                          f"choice (see strain-defect/CLAUDE.md) -- pass --surface "
                          f"explicitly rather than let this default silently.")
    print(f"Using surface: {chosen_surface}")
    df_surface = df[df["surface"] == chosen_surface]

    x_vals, y_vals, strain_grid = build_grid(
        df_surface, coord_precision=coord_precision,
        drop_incomplete_columns=drop_incomplete_columns)

    jc_grid = jc_retention(strain_grid, **ekin_params)
    ic_ratio_native = ic_retention_along_length(x_vals, jc_grid)
    ic_min, y_at_min_mm, _ = find_global_minimum(y_vals, ic_ratio_native)
    defect_x_m = float(np.clip(y_at_min_mm * 1e-3, 0.0, tape_length_m))
    print(f"Defect: Ic/Ic0_min={ic_min:.6f} at ANSYS y={y_at_min_mm:.4f}mm "
          f"-> FreeFEM x={defect_x_m:.6f}m")

    x_sample_m = np.linspace(0.0, tape_length_m, n_x_sample)
    z_sample_m = np.linspace(0.0, tape_width_m, n_z_sample)

    ic_ratio_x = extrapolate_profile_to_fem_x(y_vals, ic_ratio_native, x_sample_m)
    jc_grid_xz = extrapolate_grid_to_fem_xz(x_vals, y_vals, jc_grid, x_sample_m, z_sample_m)

    max_err, _ = check_decomposition_consistency(
        x_sample_m, z_sample_m, jc_grid_xz, ic_ratio_x, core_width_m)
    check_defect_severity(x_sample_m, z_sample_m, jc_grid_xz, ic_ratio_x, defect_x_m)

    paths = export_freefem_tables(out_dir, x_sample_m, z_sample_m, ic_ratio_x,
                                   jc_grid_xz, defect_x_m, ic_min)
    print("Exported:", *paths, sep="\n  ")
    return dict(x_sample_m=x_sample_m, z_sample_m=z_sample_m,
                ic_ratio_x=ic_ratio_x, jc_grid_xz=jc_grid_xz,
                defect_x_m=defect_x_m, defect_ic_ratio=ic_min,
                decomposition_max_rel_err=max_err)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Strain-defect Jc/Jc0 pipeline: ANSYS strain -> FreeFEM tables.")
    parser.add_argument("strain_csv")
    parser.add_argument("x_csv")
    parser.add_argument("y_csv")
    parser.add_argument("--out-dir", default=".")
    parser.add_argument("--tape-length-m", type=float, default=0.115,
                         help="Must match hts_mesh_module_tape.idp's Lx exactly.")
    parser.add_argument("--tape-width-m", type=float, default=0.006)
    parser.add_argument("--core-width-m", type=float, default=0.006 - 2e-6)
    parser.add_argument("--n-x-sample", type=int, default=116,
                         help="Must match step_strain_tape_transient.edp's nxs+1.")
    parser.add_argument("--n-z-sample", type=int, default=33,
                         help="Must match step_strain_tape_transient.edp's nzElec "
                              "(the electrical solve's own z-resolution) -- keeping "
                              "these equal means the table isn't coarser than what "
                              "the solve reads from it.")

    parser.add_argument("--node-col", default="Node Number")
    parser.add_argument("--strain-col", default="EPTOX ()")
    parser.add_argument("--x-col", default="LOCX (mm)")
    parser.add_argument("--y-col", default="LOCY (mm)")
    parser.add_argument("--strain-sep", default="\t")
    parser.add_argument("--x-sep", default="\t")
    parser.add_argument("--y-sep", default="\t")
    parser.add_argument("--coord-precision", type=int, default=None)
    parser.add_argument("--drop-incomplete-columns", action="store_true")
    parser.add_argument("--surface", default=None,
                         help="Which shell surface to use when the strain export has "
                              "2 rows/node (e.g. 'top'/'bottom'). Required if more than "
                              "one surface is present -- not inferred, see CLAUDE.md.")

    for p, d in NOMINAL_EKIN_PARAMS.items():
        parser.add_argument(f"--{p}", type=float, default=d)

    args = parser.parse_args()
    ekin_params = {p: getattr(args, p) for p in NOMINAL_EKIN_PARAMS}

    run_pipeline(args.strain_csv, args.x_csv, args.y_csv, args.out_dir,
                 args.tape_length_m, args.tape_width_m, args.core_width_m,
                 args.n_x_sample, args.n_z_sample,
                 node_col=args.node_col, strain_col=args.strain_col,
                 x_col=args.x_col, y_col=args.y_col,
                 strain_sep=args.strain_sep, x_sep=args.x_sep, y_sep=args.y_sep,
                 coord_precision=args.coord_precision,
                 drop_incomplete_columns=args.drop_incomplete_columns,
                 ekin_params=ekin_params, surface=args.surface)


if __name__ == "__main__":
    main()
