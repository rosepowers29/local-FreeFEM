# 2D Model (length x thickness cross-section)

This model resolves the tape's cross-section in its **length (x)** and
**through-thickness (y)** directions, assuming uniformity across the
tape's width. It's the fastest of the two models and is used for the
bulk of the parameter studies.

## Geometry

A 7-layer stack, 95 microns thick total, 20cm long:

| Layer | Thickness | Region # |
|---|---|---|
| Cu stabilizer (bottom) | 20 um | 1 |
| Ag (bottom) | 1.8 um | 2 |
| Hastelloy substrate | 50 um | 3 |
| Buffer stack | 0.2 um | 4 |
| REBCO | 1 um | 5 |
| Ag (top) | 2 um | 6 |
| Cu stabilizer (top) | 20 um | 7 |

Boundary labels: `1` = bottom outer face, `2` = top outer face, `3` =
left end (x=0), `4` = right end (x=Lx). The LN2 bath (77K) is applied only
at labels `3` and `4`; everything else is adiabatic (the tape sits in a
vacuum tube).

## Files

**Core modules** (included by every analysis script):
- `hts_mesh_module.idp` -- builds the mesh and defines the geometry/region
  numbering above.
- `hts_materials.idp` -- loads the tabulated material properties from
  `data/` and defines the REBCO current-sharing physics: critical current
  Jc(T), the n-value, and the power-law E-J relationship (with numerical
  regularization to keep the solver well-behaved near E=0).

**Mesh inspection:**
- `mesh_report.edp` -- prints a geometry/mesh sanity-check report and
  exports the mesh (vertices/triangles/regions) to CSV for plotting.
- `plot_mesh.py` -- renders the mesh (colored by material region) from
  that CSV output; run after `mesh_report.edp`.

**Analyses** (each pairs with its own `init_*_checkpoint.edp`, run once
before first use):
- `step1_steady_conduction.edp` -- a simple steady conduction check with
  a static hot spot in the REBCO layer, useful as a first sanity test of
  the mesh/materials/boundary conditions.
- `step3_steady_state_verify.edp` -- Picard-iteration steady-state solve
  at a chosen operating current (edit `I0w` near the top of the file to
  set it as a multiple of Ic), no heater. Confirms whether the tape
  settles to a stable temperature or diverges.
- `step2_transient_quench.edp` -- the main scenario: ramps the transport
  current up to a target value over time, then applies a 2mm x 2mm spot
  heater (power and duration configurable near the top of the file) on the
  top copper surface at the tape's midpoint, then continues the
  simulation to observe recovery or thermal runaway. Uses
  `init_checkpoint.edp`.
- `step4_overcurrent_scan.edp` -- sweeps operating current (as a multiple
  of Ic, set via `TESTRATIO`) with the heater off, running one current
  level per invocation, to find the baseline current threshold above
  which no stable steady state exists. Uses `init_oc_checkpoint.edp`.
  Append results across multiple ratios to `overcurrent_scan.csv`.
- `make_normal_zone.edp` -- a utility for directly imposing a normal zone
  (a region held above Tc) of a chosen length and temperature onto an
  existing checkpoint, then letting it evolve under transport current
  alone (heater off) via `step2_transient_quench.edp` to see whether it
  grows or shrinks -- the standard way to measure a minimum propagating
  zone (MPZ).
- `export_snapshot.edp` -- dumps the full 2D temperature field from the
  current checkpoint to CSV, for external inspection/plotting.

## How to run

```bash
# 1. Sanity-check the mesh
FreeFem++ -nw mesh_report.edp
python3 plot_mesh.py

# 2. Steady-state check at a chosen operating current (edit I0w in the
#    file first if you want a different current level)
FreeFem++ -nw step3_steady_state_verify.edp

# 3. Main transient scenario (ramp + heater pulse + recovery/runaway)
FreeFem++ -nw init_checkpoint.edp        # once, to start fresh
FreeFem++ -nw step2_transient_quench.edp # run repeatedly to continue
                                          # (it checkpoints and resumes
                                          # automatically; each run
                                          # advances a bounded number of
                                          # timesteps -- check the script
                                          # for maxStepsThisRun)

# 4. Overcurrent threshold scan
FreeFem++ -nw init_oc_checkpoint.edp
FreeFem++ -nw step4_overcurrent_scan.edp # edit TESTRATIO between runs to
                                          # sweep different current levels
```

## Output

Simulation output is plain CSV (temperature/voltage/current time series
or spatial profiles, depending on the script -- see the `ofstream` calls
near the end of each script for exact column definitions) plus console
output showing iteration/timestep progress as it runs. Nothing here
requires a display; all scripts are designed to run with `-nw`
(no-window/headless mode).
