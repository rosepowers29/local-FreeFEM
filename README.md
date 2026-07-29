# HTS Tape Thermal Runaway Simulation (FreeFEM)

## Start here

```bash
FreeFem++ -nw mesh_report.edp   # prints mesh_report.txt, exports mesh_*.csv
python3 plot_mesh.py            # renders mesh_full_by_region.png + 2 zoom levels
```

`mesh_report.txt` is the fastest way to sanity-check the geometry before
trusting anything built on top of it: per-layer thickness/area (computed vs.
expected, should match to floating-point precision), interface vertex counts
(should be exactly nx+1 at every one of the 6 layer interfaces -- this is
the regression check for the mesh-conformity bug described below), and
per-layer mesh aspect ratios.

## IMPORTANT: bugs found and fixed since the last handoff

Three separate bugs were compounding to produce large, completely spurious
heating even at a nominal, well-below-critical-current (0.7*Ic) operating
point that should show essentially zero dissipation. All three are now
fixed and verified: the model now correctly holds at exactly 77.000K,
indefinitely, at 0.7*Ic with no disturbance (see `step3_steady_state_verify.edp`).

1. **`Einit` was set equal to `E0`** in `hts_materials.idp` (both 1e-4 V/m).
   `Einit` is supposed to be a numerical floor that only prevents a literal
   E=0 division-by-zero singularity; it should be many orders of magnitude
   smaller than any physically relevant E-field, not equal to the critical-
   field criterion. As set, it clamped the ENTIRE below-Ic operating regime
   into an artificially resistive state. Fixed: `Einit = 1e-10`.

2. **`sigma_max` (1e16 S/m) was binding at the nominal 0.7*Ic/77K operating
   point.** The true (uncapped) power-law conductivity there is ~2e16 S/m,
   so the "generous numerical ceiling" was silently halving the real
   conductivity, forcing a ~2x-too-large E-field. Fixed: raised to 1e20.

3. **The real bug: the original mesh was not actually conforming at layer
   interfaces.** The original `hts_mesh_module.idp` built each of the 7
   layers as an independently-triangulated mesh (via `buildmesh`) and glued
   them with FreeFEM's `+` operator, assuming shared boundary vertices would
   merge automatically. They didn't: `buildmesh`'s adaptive triangulation
   (bamg) does not guarantee identical point placement between two
   independently-meshed regions even when the shared border is parameterized
   identically, so many interface vertices ended up as near-but-not-exactly
   -coincident duplicates (e.g. x=0.0465001 vs x=0.0465003) that never got
   merged into single shared degrees of freedom. This produced spurious,
   effectively-random decoupled temperature spikes at interface points
   throughout the domain (confirmed via direct inspection: a >2K spike at a
   single node, sandwiched between two neighboring points at 77.00K, with
   the "peak" location not even near mid-length). This was compounded by
   representing material properties (k, Joule source) as continuous P1
   fields built from a discontinuous P0 (per-triangle) region indicator --
   physically wrong regardless of the meshing bug, since real material
   properties ARE discontinuous at these interfaces, and this let REBCO's
   Joule heating leak numerically into the electrically-insulating buffer
   layer (which showed nonzero Joule heating identical to REBCO's, despite
   carrying no current).

   **Fix**: `hts_mesh_module.idp` was rewritten to build the whole 7-layer
   stack as ONE single connected mesh (a stretched-coordinate `square()` +
   `movemesh`, remapping the y-coordinate to place each layer's boundaries
   at the right physical thickness), which makes interface duplication
   structurally impossible. All material-property fields (`source`, `kfun`,
   `rhocpfun`) were switched from `Vh` (P1) to `Ph` (P0) -- the physically
   correct choice for genuinely discontinuous material properties; only
   temperature itself (which must be continuous across a bonded interface)
   stays P1.

   This is also almost certainly why a COMSOL reference model wouldn't show
   this: COMSOL's native mesher builds one conforming mesh for the whole
   geometry rather than stitching independently-triangulated regions
   together after the fact.

## What's in here

**Mesh & materials:**
- `hts_mesh_module.idp` -- builds the single conforming 2D mesh (see above).
  Region IDs: 1=Cu(bot) 2=Ag(bot) 3=Hastelloy 4=Buffer 5=REBCO 6=Ag(top)
  7=Cu(top). Labels: 1=bottom face, 2=top face, 3/4=left/right ends
  (LN2-cooled, T=77K).
- `hts_materials.idp` -- loads all tabulated (T, property) data from `data/`,
  provides linear interpolation, and implements the REBCO conductivity
  sigma(E,T): power-law in sigma (not Jc), E-field regularization via
  `Einit`, T-dependent n(T), `sigma_max` cap, `sigma_rebco` normal-state
  floor. Cu resistivity is your real measured data (note: has an apparent
  non-monotonic anomaly at the 273K/300K points -- see comment in the data
  file; only matters if local T exceeds ~200K).
- `mesh_report.edp` -- entry-point diagnostic described above.
- `plot_mesh.py` -- renders the mesh visualizations from `mesh_report.edp`'s
  CSV output.

**Physics scripts:**
- `step1_steady_conduction.edp` -- steady-state sanity check with a static
  hot spot, LN2 only at the two ends.
- `step2_transient_quench.edp` -- transient coupled electro-thermal solve:
  per-x current-sharing across the 5 conducting layers (equipotential
  assumption across thickness), implicit-Euler heat equation with
  semi-implicit (lagged) nonlinear coefficients, optional transient
  disturbance pulse (currently disabled, `Qpulse0=0`, for steady-state
  verification -- re-enable to explore quench/runaway behavior).
  Supports checkpoint/resume (see below).
- `step3_steady_state_verify.edp` -- pure steady-state check via
  Picard iteration (NOT time-stepping -- see note below), no disturbance.
  Confirms 77K holds at 0.7*Ic.
- `init_checkpoint.edp` / `export_snapshot.edp` -- checkpoint utilities for
  `step2`.

**Data (`data/`):** all uploaded material property tables, SI units.

## Note on "steady state" terminology

`step3_steady_state_verify.edp` does NOT time-step. It solves the genuinely
steady (elliptic, no time-derivative) heat equation, iterated via
under-relaxed Picard iteration (relax=0.2, up to 30 iterations) to handle
the nonlinear T-dependence of the material properties. There is no current
ramp -- the full 0.7*Ic target current is applied from iteration 0.
`step2_transient_quench.edp`, by contrast, is a genuine time-marching
transient solve (implicit Euler, fixed dt).

## How to run (needs a FreeFEM install, v4.13 tested)

```bash
# mesh sanity check (do this first)
FreeFem++ -nw mesh_report.edp
python3 plot_mesh.py

# steady-state verification (Picard iteration, no time-stepping)
FreeFem++ -nw step3_steady_state_verify.edp

# transient (time-marching), checkpoint/resume across chunks
FreeFem++ -nw init_checkpoint.edp
FreeFem++ -nw step2_transient_quench.edp   # run repeatedly to continue
FreeFem++ -nw export_snapshot.edp          # dump current field to CSV
```

## Latest scenario: ramped current + surface spot heater (recovery result)

`step2_transient_quench.edp` now implements:
- **Current ramp**: linear, 0 -> 0.7*Ic(77K) over 0.5s, then held constant.
- **Settle window**: 0.05s at full current before the disturbance (confirms
  baseline holds at exactly 77K -- a good regression check for the mesh/
  regularization fixes).
- **Spot heater**: 2mm x 2mm on the top Cu surface (boundary label 2,
  Neumann/imposed-flux BC, NOT volumetric), 13W for 0.01s ->
  q = 13W / 4mm^2 = 3.25e6 W/m^2. NOTE: our model has no width dimension
  (everything is "per unit width"), so this necessarily assumes the flux
  applies uniformly across the full 12mm tape width rather than truly
  localizing to the 2mm x 2mm spot -- this will overestimate the local
  temperature rise relative to a true 3D treatment, since real heat would
  also spread sideways in width. Keep this in mind when comparing
  magnitudes to a full 3D COMSOL run.
- **Recovery window** afterward.
- Phase-dependent timestep (coarse during the ramp, fine during/after the
  pulse), capped so it never overshoots a phase boundary, and a per-
  invocation step cap (`maxStepsThisRun`) so long runs can be safely
  chunked via the existing checkpoint/resume mechanism.

**Result of the first run** (`transient_log.csv`, `chart_full_scenario.png`,
`chart_perlayer_pulse.png`): the disturbance is a clean, non-destructive
recovery, not a runaway. Tmax peaks at 96.5K right at the end of the pulse
(briefly exceeding Tc=90K), then drops sharply the instant the heater turns
off -- back to 79.1K within 3ms, and fully recovered to exactly 77.000K by
~18ms after pulse end. Vtot returns to its exact pre-pulse baseline. Held
flat at 77K for the remainder of the observation window (through t=0.62s;
the full planned window extends to t=0.76s if you want to extend it further
to be extra sure, but the recovery is already unambiguous well before then).
`chart_perlayer_pulse.png` shows the through-thickness thermal lag directly:
Cu-top responds first (heater is on its surface), Ag-top follows, then
REBCO -- exactly the physically expected picture for a surface-mounted
disturbance, as opposed to the old (pre-bug-fix) volumetric REBCO-hosted
pulse used in earlier exploration.

**Per-layer current redistribution** (`chart_current_redistribution.png`):
`step2` now also logs the actual current carried by each of the 5
conducting layers at the heater location (columns `IcuB, IagB, Isc, IagT,
IcuT` -- current per unit width, A/m; `Isc` is REBCO). This confirms the
expected current-sharing physics directly: before the pulse, ~100% of I0
flows through REBCO (Isc=18200 A/m, stabilizer=0). Within 1ms of the heater
turning on, REBCO sheds to essentially zero (Isc=2.2 A/m) as current
redistributes into the stabilizer (Cu-bottom carries the most, ~9620 A/m,
since it's farthest from the heater and stays coolest/lowest-resistivity;
Cu-top carries less, ~6013 A/m, despite being thicker than the Ag layers,
because it's hottest). Current sums to I0 at every timestep (a good
conservation check). Within 3ms of the heater turning off, essentially all
current has flowed back into REBCO.

## Known caveats / still open



1. **Cu resistivity 273K/300K anomaly** (see `data/rho_cu.txt`) -- worth
   resolving before trusting results where local T exceeds ~200K.
2. **Electro-thermal coupling in `step2` is lagged one timestep**
   (semi-implicit / Picard-lag), not a fully monolithic Newton solve.
3. **Performance**: the per-x current-sharing bisection solve dominates
   runtime (FreeFEM's interpreted-script overhead, not the FE solve
   itself).
4. **Only length x thickness is modeled** -- no width dimension. Fine for
   the current uniform-across-width physics, but the planned laser-slit
   geometry (current redistribution across a width-wise cut) will need a
   width-resolved model (2.5D sheet model or full 3D) layered on top of
   this. This also means the current 2mm x 2mm spot heater's flux is
   applied as if uniform across the full tape width -- see the scenario
   note above.
