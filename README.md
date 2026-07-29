# HTS Tape Thermal Runaway Simulation (FreeFEM)

## What's in here

**Model code:**
- `hts_mesh_module.idp` — builds the 2D (length x thickness) mesh of the real
  7-layer tape stack (Cu/Ag/REBCO/buffer/Hastelloy/Ag/Cu, 95um total, 20cm long).
  Each layer is its own independent mesh, tagged with a region ID, then glued
  with FreeFEM's `+` operator. Regions: 1=Cu(bot) 2=Ag(bot) 3=Hastelloy
  4=buffer 5=REBCO 6=Ag(top) 7=Cu(top). Labels: 1=bottom face, 2=top face,
  3/4=left/right ends (LN2-cooled, T=77K), 11-16=internal interfaces (unused).
- `hts_materials.idp` — loads all tabulated (T, property) data from `data/`,
  provides linear interpolation, and implements the REBCO conductivity model
  sigma(E,T) exactly matching the COMSOL formulas provided (power-law in
  sigma, E-field regularization via Einit, T-dependent n(T), sigma_max cap,
  sigma_rebco normal-state floor).
- `step1_steady_conduction.edp` — steady-state sanity check: LN2 only at the
  two ends, static hot spot in REBCO, confirms mesh/materials/BCs behave
  sensibly (this is where we found the Cu-face vs. bottom-face thermal
  asymmetry from the Hastelloy substrate's low conductivity).
- `step2_transient_quench.edp` — the main event: transient coupled
  electro-thermal solve. Per-x algebraic current-sharing across the 5
  conducting layers (equipotential assumption across thickness), implicit
  Euler heat equation with semi-implicit (lagged) nonlinear coefficients,
  triggered by a transient local heat pulse in REBCO. Supports
  checkpoint/resume (see below) since each ~5-step chunk takes ~35s.
- `init_checkpoint.edp` — creates the initial checkpoint (t=0, T=77K uniform).
  Run this once before the first `step2_transient_quench.edp` run.
- `export_snapshot.edp` — dumps the current checkpoint's full T(x,y) field
  to `field_snapshot.csv` for external plotting/inspection.

**Data (`data/`):** all your uploaded material property tables, converted to
consistent SI units where needed. Notably `rho_cu.txt` is your real measured
data (scaled from the assumed nano-Ohm-meter units in your upload to Ohm.m);
`rho_cu_raw.txt` and `rho_cu_WFplaceholder.txt` are kept for reference
(raw upload, and my earlier Wiedemann-Franz stand-in, respectively -- not
used by the current model).

**Results from the run so far:**
- `transient_log.csv` — Tmax and total tape voltage (Vtot) vs time, every ms
  from t=0 to t=25ms.
- `field_snapshot.csv` — full spatial T(x,y,region) field at t=25ms (the most
  recent checkpoint), one row per mesh vertex (2826 rows).
- `chart_Tmax_Vtot_vs_time.png` — the time series plotted.
- `chart_field_snapshot_full.png` / `chart_field_snapshot_zoom.png` — the
  spatial temperature field, full tape and zoomed to the disturbance region
  (y-axis is exaggerated ~2000x vs x since the real aspect ratio is
  200mm x 0.095mm).

## How to run it (needs a FreeFEM install, v4.13 tested)

```bash
# one-time setup
FreeFem++ -nw init_checkpoint.edp

# run in chunks (edit nSteps/dt in step2_transient_quench.edp to taste;
# each chunk resumes automatically from data/checkpoint.txt)
FreeFem++ -nw step2_transient_quench.edp
FreeFem++ -nw step2_transient_quench.edp   # run again to continue further
...

# to inspect the current state at any point:
FreeFem++ -nw export_snapshot.edp
```

`checkpoint.txt` (not included here, since it's just a raw restart file) holds
the current time and full temperature DOF vector; delete it and rerun
`init_checkpoint.edp` to start over.

## Known caveats / things to double check

1. **Cu resistivity, 273K/300K points**: your `rho_cu.txt` has a
   non-monotonic jump (31.5 at 273K, dropping to 17.1 at 300K). 17.1 matches
   the textbook room-temperature value for high-purity Cu; 31.5 looks like it
   may be from a different source/purity. Only matters if local T exceeds
   ~200K, which the current runaway trend suggests is possible -- worth
   resolving before trusting quantitative results above that range.
2. **Electro-thermal coupling is lagged one timestep** (semi-implicit /
   Picard-lag), not a fully monolithic Newton solve. Fine for moderate dt but
   not verified against a tighter coupling.
3. **The per-x electrical solve uses a fixed dense-sampling window**
   (+/-2cm around the initial pulse location). If the normal zone
   propagates beyond that window, the electrical solve will silently
   under-resolve it again (this exact bug is what caused the first
   "no voltage rise" result before it was found and fixed).
4. **The pulse magnitude (3e12 W/m^3, 2ms, 2mm-wide) was chosen by
   trial-and-error** to produce interesting behavior, not derived from a
   real disturbance mechanism (AC loss, flux jump, etc.) -- it has not been
   validated against any real MQE estimate for this tape.
5. **Performance**: the per-x current-sharing bisection solve dominates
   runtime (FreeFEM's interpreted-script overhead, not the FE solve itself).
   ~35s per 5 timesteps at current resolution. This is the main lever if you
   want to run further/finer.
