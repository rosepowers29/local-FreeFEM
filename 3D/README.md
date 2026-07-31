# 3D Model (full width, copper shell)

This model resolves the tape in all three dimensions: length (x),
through-thickness (y), and width (z, 12mm). Unlike the 2D model, it
represents the real geometry of the copper stabilizer, which forms a
continuous shell wrapping the **entire perimeter** of the tape's
cross-section (top, bottom, AND both edges) as a single electrical
conductor -- not just top and bottom.

## Geometry

The copper shell is 20 microns thick all the way around. The inner layer
stack (Ag/Hastelloy/buffer/REBCO/Ag) is narrower than the overall 12mm
tape width, sized to fit inside the shell:

| Region | Description | # |
|---|---|---|
| Cu shell | top + bottom + both side edges, one conductor | 1 |
| Ag (bottom) | inner stack only | 2 |
| Hastelloy substrate | inner stack only | 3 |
| Buffer stack | inner stack only | 4 |
| REBCO | inner stack only | 5 |
| Ag (top) | inner stack only | 6 |

**Boundary labels use FreeFEM's native `cube()` mesh convention, which is
DIFFERENT from the 2D model's labeling**: `1` = bottom face (y=0), `2` =
right end (x=Lx, **cooled**), `3` = top face (y=yB7), `4` = left end
(x=0, **cooled**), `5` = one width-edge side face (adiabatic), `6` = the
other width-edge side face (adiabatic). The LN2 bath is applied at labels
`2` and `4` -- note this is a different pair of numbers than the 2D
model's `3`/`4`.

## A real trade-off: mesh resolution vs. compute cost

Evaluating the (temperature-dependent) material properties directly on a
3D mesh is significantly more expensive per element than in 2D, because
FreeFEM's per-element function-call overhead dominates at typical 3D
element counts. The meshes here use deliberately modest resolution
(check `nx`, `ny`, `nz` near the top of `hts_mesh_module_3d.idp`) to keep
each solve/iteration in the tens of seconds rather than minutes. If you
increase resolution, expect roughly linear cost scaling with total
element count. The heater's 2mm-scale footprint is only resolved by a
handful of elements at the current settings -- fine for confirming
qualitative behavior, but worth refining if precise quantitative accuracy
near the heater matters for your purposes.

## Files

**Core modules:**
- `hts_mesh_module_3d.idp` -- builds the 3D mesh (via FreeFEM's `cube()`)
  and defines the region numbering above. Also defines `shellArea`,
  `coreWidth`, and the layer y-boundaries used throughout the other
  scripts.
- `hts_materials.idp` -- identical role to the 2D version: loads material
  property tables and defines the REBCO current-sharing physics.

**Mesh inspection:**
- `mesh_report_3d_shell.edp` (or similarly named mesh-report script) --
  exports the mesh's boundary surface and a cross-sectional slice to CSV
  for visualization.

**Analyses:**
- `step3_3d_shell_steady_verify.edp` -- Picard-iteration steady-state
  solve at a chosen operating current, heater off, checkpointed (uses
  `init_3d_shell_checkpoint.edp`). Confirms baseline stability the same
  way the 2D `step3` script does.
- `export_shell_profile.edp` -- dumps a spatial temperature profile along
  the tape length from the current checkpoint to CSV.
- `step_3d_shell_heater_steady.edp` -- applies the 2mm x 2mm spot heater
  as a CONTINUOUSLY-ON (never switching off) flux on the top face, dead
  center. Useful as a quick stress test but not physically realistic for
  an actual disturbance (see the transient script below for that). Uses
  `init_3d_heater_checkpoint.edp`.
- `step_3d_shell_transient.edp` -- the main 3D scenario: ramps the
  transport current up over time, then applies the 2mm x 2mm / finite-
  duration spot heater (power, duration, and timing configurable near the
  top of the file) dead center on the top face, then continues to observe
  recovery or runaway. Uses `init_3d_transient_checkpoint.edp`. Logs a
  current-conservation diagnostic (see below) alongside temperature.

## How to run

```bash
# 1. Sanity-check the mesh
FreeFem++ -nw mesh_report_3d_shell.edp
# (plot the exported CSVs with your own script, or adapt the 2D plot_mesh.py)

# 2. Steady-state check (edit the operating-current ratio near the top of
#    the file first if you want a different level)
FreeFem++ -nw init_3d_shell_checkpoint.edp
FreeFem++ -nw step3_3d_shell_steady_verify.edp   # run repeatedly to
                                                   # continue iterating

# 3. Main transient scenario (ramp + heater pulse + recovery/runaway)
FreeFem++ -nw init_3d_transient_checkpoint.edp
FreeFem++ -nw step_3d_shell_transient.edp        # run repeatedly to
                                                   # continue; each run
                                                   # advances a small,
                                                   # fixed number of
                                                   # timesteps given the
                                                   # per-step cost
```

Because per-iteration cost is higher here than in the 2D model (see the
resolution trade-off note above), expect to run these analysis scripts
many times in sequence to reach a full result -- this is expected and is
exactly what the checkpoint/resume mechanism is for.

## Current-conservation diagnostic

The per-x electrical solve (`solveE()` in each analysis script) includes
a built-in consistency check: after solving for the local electric field,
it verifies that the resulting total current actually matches the target
transport current, and will halt with an assertion error if the mismatch
ever exceeds 0.1%. `step_3d_shell_transient.edp` additionally logs the
worst-case (maximum, across all sampled x-positions) relative error from
this check at every timestep, as an extra CSV column
(`maxCurrentConservationRelErr`) -- a useful thing to plot alongside
temperature/current if you want independent confirmation that the
electrical solve is behaving well throughout a run.

## Output

Same as the 2D model: plain CSV output plus console progress, no display
required (`-nw` throughout).
