"""
Synthetic-data standalone test for strain_to_jc.py -- per this repo's
CLAUDE.md testing discipline ("build small synthetic-data standalone tests
... to validate formulas/logic first" before ever touching the expensive
FreeFEM solve). No ANSYS data or FreeFEM install required; run directly:

    python3 test_strain_to_jc_synthetic.py
"""

import os
import shutil
import tempfile

import numpy as np
import pandas as pd

from strain_to_jc import run_pipeline, NOMINAL_EKIN_PARAMS, jc_retention


# Synthetic ANSYS export covers y in [5,75]mm (NOT the full 80mm tape -- this
# is the whole point: exercises the flat-extrapolation policy at both ends)
# and the full x (width) range [0,6]mm, with a Gaussian tensile-strain bump
# centered at a KNOWN defect location so the pipeline's detected defect
# location can be checked against ground truth.
TRUE_DEFECT_Y_MM = 40.0
TRUE_DEFECT_X_MM = 3.5   # off-center in width, not at the centerline
Y_NATIVE = np.linspace(5.0, 75.0, 36)     # ANSYS "y" = FreeFEM x (length)
X_NATIVE = np.linspace(0.0, 6.0, 13)      # ANSYS "x" = FreeFEM z (width)

TAPE_LENGTH_M = 0.080
TAPE_WIDTH_M = 0.006
CORE_WIDTH_M = TAPE_WIDTH_M - 2e-6


def build_synthetic_strain_grid():
    Y, X = np.meshgrid(Y_NATIVE, X_NATIVE, indexing="ij")
    baseline_strain = 0.0005   # mild uniform tensile baseline, inside the
                               # Ekin "plateau" region so jc_retention~1 away
                               # from the defect
    bump = 0.012 * np.exp(-(((Y - TRUE_DEFECT_Y_MM) / 6.0) ** 2
                            + ((X - TRUE_DEFECT_X_MM) / 1.5) ** 2))
    strain_grid = baseline_strain + bump   # a local tensile spike -> locally
                                            # suppressed Jc/Jc0 via jc_retention
    return strain_grid


def write_synthetic_ansys_csvs(strain_grid, out_dir):
    ny, nx = strain_grid.shape
    node_ids, strains, xs, ys = [], [], [], []
    node = 1
    for i in range(ny):
        for j in range(nx):
            node_ids.append(node)
            strains.append(strain_grid[i, j])
            xs.append(X_NATIVE[j])
            ys.append(Y_NATIVE[i])
            node += 1

    strain_csv = os.path.join(out_dir, "strain.csv")
    x_csv = os.path.join(out_dir, "x.csv")
    y_csv = os.path.join(out_dir, "y.csv")

    pd.DataFrame({"Node Number": node_ids, "EPTOX ()": strains}).to_csv(strain_csv, index=False)
    pd.DataFrame({"Node Number": node_ids, "LOCX (mm)": xs}).to_csv(x_csv, sep="\t", index=False)
    pd.DataFrame({"Node Number": node_ids, "LOCY (mm)": ys}).to_csv(y_csv, sep="\t", index=False)
    return strain_csv, x_csv, y_csv


def main():
    tmp_dir = tempfile.mkdtemp(prefix="strain_jc_synthetic_")
    try:
        strain_grid = build_synthetic_strain_grid()
        strain_csv, x_csv, y_csv = write_synthetic_ansys_csvs(strain_grid, tmp_dir)

        result = run_pipeline(
            strain_csv, x_csv, y_csv, out_dir=tmp_dir,
            tape_length_m=TAPE_LENGTH_M, tape_width_m=TAPE_WIDTH_M,
            core_width_m=CORE_WIDTH_M,
            n_x_sample=81, n_z_sample=21,
            node_col="Node Number", strain_col="EPTOX ()",
            x_col="LOCX (mm)", y_col="LOCY (mm)",
            strain_sep=",", x_sep="\t", y_sep="\t",
        )

        # ---- 1. Decomposition consistency ----
        assert result["decomposition_max_rel_err"] < 0.02, (
            f"decomposition consistency check failed: "
            f"{result['decomposition_max_rel_err']:.4f} >= 0.02")
        print(f"[PASS] decomposition consistency: "
              f"max_rel_err={result['decomposition_max_rel_err']:.5f}")

        # ---- 2. Defect location detected near ground truth ----
        defect_x_mm = result["defect_x_m"] * 1e3
        assert abs(defect_x_mm - TRUE_DEFECT_Y_MM) < 3.0, (
            f"defect location off: detected x={defect_x_mm:.2f}mm, "
            f"true y={TRUE_DEFECT_Y_MM}mm")
        print(f"[PASS] defect location: detected x={defect_x_mm:.3f}mm "
              f"(true={TRUE_DEFECT_Y_MM}mm)")

        # ---- 3. Flat-extrapolation policy at both ends of the x-sample grid ----
        x_sample_m = result["x_sample_m"]
        ic_ratio_x = result["ic_ratio_x"]
        below_coverage = x_sample_m < Y_NATIVE[0] * 1e-3
        above_coverage = x_sample_m > Y_NATIVE[-1] * 1e-3
        assert below_coverage.any() and above_coverage.any(), (
            "test setup error: x-sample grid doesn't actually extend past "
            "the synthetic ANSYS coverage range -- can't test extrapolation")
        edge_lo_val = np.interp(Y_NATIVE[0] * 1e-3, x_sample_m, ic_ratio_x)
        edge_hi_val = np.interp(Y_NATIVE[-1] * 1e-3, x_sample_m, ic_ratio_x)
        assert np.allclose(ic_ratio_x[below_coverage], edge_lo_val, atol=1e-6), \
            "flat-extrapolation below coverage range is NOT flat"
        assert np.allclose(ic_ratio_x[above_coverage], edge_hi_val, atol=1e-6), \
            "flat-extrapolation above coverage range is NOT flat"
        print("[PASS] flat-extrapolation policy holds at both ends of coverage")

        # ---- 4. jc_retention sanity: far from the defect, ratio ~1 ----
        far_from_defect = jc_retention(np.array([0.0005]), **NOMINAL_EKIN_PARAMS)[0]
        assert far_from_defect > 0.9, (
            f"baseline strain should be near the Ekin-Weibull plateau "
            f"(ratio~1), got {far_from_defect:.4f}")
        print(f"[PASS] baseline (non-defect) Jc/Jc0 = {far_from_defect:.4f} (near plateau)")

        print("\nAll synthetic pipeline checks passed.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
