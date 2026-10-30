# strain-defect/CLAUDE.md — agent notes for this track

Single-tape (NO slit, NO heater) electrothermal quench model. The only
quench trigger is a strain-induced Jc defect derived from real ANSYS strain
data via the Ekin-Weibull model. Goal: ramp current to just above the
nominal (undamaged) critical current and compare voltage channels to
explain a lab observation. See `PROJECT_CONTEXT_SUMMARY.md` (root) and the
approved plan this track was built from for the full rationale; this file
is deltas/gotchas specific to this directory, same role as
`3D-slit/CLAUDE.md`/`3D-slit/electrothermal/CLAUDE.md` for their tracks.

## How this differs from every other track in this repo

- **Full LN-bath immersion**: `on(1,2,3,4,5,6, T=Tcold)` in
  `step_strain_tape_transient.edp` — Dirichlet 77K on EVERY boundary face.
  Every other track (`2D/`, `3D/`, `3D-slit/`) only cools the two x-end
  faces (labels 2,4) and leaves top/bottom/sides adiabatic. Do not copy BC
  patterns from those tracks without checking this difference first.
- **No slit, no heater**: single equipotential electrical channel (no L/R
  split), no external disturbance term in the weak form at all (not just
  zeroed — the `int2d(..., qHeaterNow*...)` line doesn't exist here).
- **A new, simpler 5-region layer stack** (down from 6-7 in 3D/3D-slit) —
  see `hts_mesh_module_tape.idp`'s header for the full derivation. No
  bottom Ag, and the bottom/top/side copper are ALL ONE merged conductor
  region (asymmetric thickness: 1µm bottom+sides, 21µm top) rather than a
  separate top-only stabilizer layer, per explicit user direction to
  simplify. REBCO sits close to (not exactly at) the stack's geometric
  center — Hastelloy is fixed at a literal 20µm (matching the merged
  region's historical "upper copper layer" origin) rather than solved for
  exact centering once bottom Ag was removed; this is a known, accepted
  ~4% asymmetry, not a bug.
- **Tape length is 115mm, not 80mm.** Started as an 80mm placeholder;
  resized once the user's real ANSYS strain export (`7turns_6mm_45_30mm`,
  a 7-turn coil's local bend-strain analysis) showed the actual specimen's
  LOCZ (length) axis spans 0-115mm. `nx`/`nxs` were bumped proportionally
  (86/115) so physical resolution didn't silently coarsen when `Lx` grew —
  if `Lx` ever changes again, rescale both the same way.
- **Jc is spatially resolved from real strain data**, not uniform. See
  "Electrical/thermal coupling" below — this is the architecturally new
  piece this track adds on top of the existing patterns.

## Strain → Jc pipeline (`strain_to_jc.py`)

Adapted from `~/Downloads/ic_retention_analysis_new.py` (same Ekin-Weibull
physics, same `load_and_merge`/`build_grid`/`jc_retention`/
`ic_retention_along_length`/`find_global_minimum`, copied in rather than
imported since that file lives outside the repo).

**New on top of the template**: the ANSYS mesh and the FreeFEM `cube()`
mesh are different grids, so an extrapolation step is unavoidable.
Coordinate convention: ANSYS "y" (longitudinal) → FreeFEM "x"; ANSYS "x"
(width) → FreeFEM "z"; mm → meters. **Extrapolation policy is FLAT
(nearest-edge-value hold)**, not linear — implemented by clamping query
coordinates into the ANSYS data's own range before interpolating. Chosen
deliberately: the ANSYS export likely doesn't cover the full 80mm tape, and
linear extrapolation could invent an artificially better/worse Jc/Jc0
outside the measured range and silently relocate the quench trigger.

The pipeline exports **two** tables that MUST be resampled from the same
underlying field onto the **same** FreeFEM x-sample grid (currently 116
points, 0 to `Lx`, matching `step_strain_tape_transient.edp`'s `nxs=115`):
- `strain_jc_icratio_x.txt`: 1D width-averaged Ic/Ic0(x) (reuses
  `ic_retention_along_length` unchanged, then resampled). Loaded but no
  longer load-bearing for the electrical solve (see "Electrical/thermal
  coupling" below) — kept for diagnostic/comparison purposes.
- `strain_jc_grid_xz.txt`: 2D regular-grid Jc/Jc0(x,z), un-averaged. The
  load-bearing table — feeds both the volumetric heating source AND the
  z-resolved electrical solve. `--n-z-sample` (default 33) MUST match
  `step_strain_tape_transient.edp`'s `nzElec` — keeping them equal means the
  electrical solve's own z-sampling isn't coarser than the table it reads.

**Real ANSYS data needs two flags the synthetic test doesn't exercise**,
found by running against the user's actual `7turns_6mm_45_30mm` export:
- `--surface top`/`--surface bottom`: **required**, not inferred, whenever
  the strain file has 2 rows/node (top/bottom shell surface). An earlier
  version silently picked the alphabetically-first surface ("bottom") —
  this disagreed with a "top" result the user already trusted from their
  own prior `ic_retention_analysis_new.py` runs. Now `run_pipeline` raises
  an error rather than guess once more than one surface is present. Which
  surface is physically correct is a modeling question about the ANSYS
  setup (does top/bottom mean the whole composite shell's extreme fibers,
  or specifically the REBCO/substrate layer's own two faces?) that only the
  user can answer — for the `7turns_6mm_45_30mm` data it's "top" (REBCO's
  own faces, confirmed by the user).
- `--coord-precision 3 --drop-incomplete-columns`: needed for quadratic
  shell-element meshes. Found live on this data: "corner" width positions
  (0.5mm spacing) had full length-density (461 points), "midside" width
  positions (0.25mm offsets) had only half (231) — `--drop-incomplete-
  columns` removes those. Separately, the true z=0 edge was fragmented into
  8 near-zero floating-point variants (e.g. `-1.9665e-06`, `5.6572e-08`,
  summing to exactly 461 nodes combined) by ANSYS export noise —
  `--coord-precision 3` collapses them back into one real column. Without
  both flags, `build_grid`'s pivot produces thousands of NaN gaps and
  `find_global_minimum` fails outright (every row NaN) — this is not a
  silent-wrong-answer failure mode, it's a hard crash, but still worth
  recognizing on sight rather than being surprised by it.

Plus `strain_jc_meta.idp` (array-size constants + `defectX`, auto-generated,
**do not hand-edit** — included directly by `hts_materials.idp` before its
table-loading declarations) and `strain_jc_meta.json` (same info, for
Python consumers).

**Validation, built into the pipeline itself, not optional**:
1. Decomposition consistency check — width-integrating the 2D grid over z
   must reproduce the 1D profile at the same x (repo's standard
   "decomposition must sum back to the aggregate" discipline, root
   `CLAUDE.md`). Printed as a WARNING if it fails, not silently ignored.
   Real-data note: an initial run against `7turns_6mm_45_30mm` data failed
   this check (9.4% error) at the default resolution (`--n-z-sample 21`
   against a native 32-column grid); bumping to `--n-z-sample 33` (now the
   default, matching `nzElec` below) plus the quadratic-mesh flags above
   brought it to 0.74% — resampling resolution was the actual cause, not a
   data problem.
2. Defect severity check — compares the pointwise minimum of the 2D grid
   against the width-averaged profile at the defect location. **No longer a
   correctness gate** (see "Electrical/thermal coupling" below) — it's
   informational, describing how locally severe/narrow a defect is. It
   fired loudly on the real `7turns_6mm_45_30mm` data (local min effectively
   0 vs. width-avg 0.356) and that NOTE is accurate: the real defect is a
   genuine width-edge strain concentration (bend-induced, both tape edges,
   up to 9% strain — a known failure mode for tightly-wound coated
   conductor, not a meshing artifact) narrow enough that a width-averaged
   electrical model would have been unconservative. This is WHY the
   electrical model is z-resolved now instead of width-averaged.

**Currently committed data is from the real `7turns_6mm_45_30mm` "top"
surface** (not synthetic placeholder — see the exact command in "Running"
below). `test_strain_to_jc_synthetic.py` remains the no-FreeFEM-needed
correctness check for the pipeline itself; it doesn't touch these files.

Run the synthetic test (no FreeFEM needed) with:
```bash
cd strain-defect
python3 test_strain_to_jc_synthetic.py
```

## Electrical/thermal coupling (z-resolved, not width-averaged)

No slit means genuinely one electrical channel at each x — unlike
`3D-slit/electrothermal`'s coupled two-channel voltage-matching bisection
(which only exists because the slit is a real geometric discontinuity
severing current paths into two separate conductors), nothing here
justifies that kind of extra per-timestep nonlinear solve. That's the key
fact that makes z-resolution cheap here: it's NOT "N independent channels
needing cross-matching," it's one continuous equipotential REBCO sheet
whose local current density varies with z because Jc does — so E(x) is
still a single shared value at each x, and resolving z just means replacing
a width-averaged scalar with a proper integral over z, at that same E.

- **1D per-x electrical bisection** (`solveE`/`Itot` in
  `step_strain_tape_transient.edp`): the REBCO current-sharing term is
  `tSc*E*zIntegralSigmaSc(E, TscZ, jcRzZ, nzElec)` — a trapezoidal integral
  over `nzElec` (33) z-sample points of `sigmaScDefect(E, T(x,z),
  jcRatioOfXZ(x,z))`, not a single width-averaged scalar. `T` and
  `jcRatioOfXZ` are precomputed once per x per timestep into `TscZ`/`jcRzZ`
  arrays (same "snapshot before the bisection loop" optimization
  `3D-slit/electrothermal`'s per-x T precompute already uses) since neither
  depends on the trial `E` being bisected over.
- **Volumetric 3D Joule-heating source term** (`sourceOfDefect`, evaluated
  pointwise over the true FE temperature field) is unchanged by this —
  it already used the full 2D `jcRatioOfXZ(x,z)` field pointwise.
- **Cost**: adds ~33x more `sigmaScDefect` evaluations to the electrical
  sub-solve specifically, but that sub-solve was never the bottleneck —
  `3D-slit/electrothermal/CLAUDE.md`'s own profiling shows `elecSplit`
  (~0.0025s) is ~4 orders of magnitude cheaper than `pdeSolve` (~116s).
  Confirmed in practice: a local Docker smoke test's `totalInvocation` only
  grew from ~208s to ~263s after this change, and most of that difference
  is the 44%-larger mesh (115mm vs 80mm), not the z-integral itself.
- **This replaced an earlier width-averaged hybrid design** (scale `Jc0` by
  `icRatioOfX(x)` in the electrical solve, keep the full 2D field only in
  the heating source) that was planned and smoke-tested first. That design
  was explicitly conditional on `check_defect_severity()` passing; once real
  `7turns_6mm_45_30mm` data showed a severe, width-edge-localized defect
  that check was designed to catch, the electrical model was upgraded
  rather than proceeding with a known-unconservative approximation. If you
  see references to "width-averaged" coupling in older commit history or
  docs, this section supersedes them.

**Verified against a real FreeFEM parser** (FreeFEM has no Homebrew/macOS
package; got it running locally via `colima start` + `docker run
freefem/freefem FreeFem++ -nw ...`, mounting this directory at `/work` —
this is the same `freefem/freefem` Docker image this repo's own history
already used for syntax verification, see `3D-slit/electrothermal/
CLAUDE.md`'s FreeFEM-source-diving section):
1. `mesh_report_strain_tape.edp` — every region-volume and boundary-label-
   area `relErr` came back at machine precision (~1e-12 to 1e-14), both at
   the original 80mm length and re-verified after the 115mm resize. The
   full-immersion BC's `on(1,2,3,4,5,6,...)` label assumption (1/3=y-walls,
   2/4=x-ends, 5/6=z-walls, same as 3D/3D-slit's convention) and
   `sourceOfDefect`'s region dispatch are both confirmed correct for this
   mesh, not assumed.
2. `sourceOfDefect(region, Efun(x), T, x, z)`'s `source = ...` field
   assignment — passing 2 point-dependent coordinate args alongside
   `T`/`region` into one dispatch function calling the 2D `jcRatioOfXZ`
   table lookup — ran clean through `init_strain_tape_checkpoint.edp` +
   chained invocations of `step_strain_tape_transient.edp`, including a
   checkpoint-resume, with the earlier (80mm, width-averaged) design.
3. The z-resolved electrical model (`Itot`/`solveE` taking `TscZ`/`jcRzZ`
   arrays, `zIntegralSigmaSc`) was smoke-tested after the upgrade, at the
   new 115mm length, against the REAL `7turns_6mm_45_30mm` data: `[defect]
   x=0.00875m` printed correctly (matches `strain_jc_meta.idp`'s real
   `defectX`), current-conservation error was exactly 0, diagnostic tap
   positions matched (`0.00675`/`0.01075` = `defectX` ± 2mm, `V_CL_minus` at
   `x=0.115`). "Ok: Normal End", no `[bisect]`/`FATAL` lines.

Each single timestep currently costs **~170-210s wall-clock inside the
Docker container** on this machine (mesh build ~7s, solve dominates) — fine
for a 1-2 step correctness smoke test, but do not attempt a real multi-step
or multi-ratio run here. Per the user's own instruction: anything
time-consuming (a real `run_transient.py` run, a ratio sweep) belongs on
the remote machine; local Docker is for small, fast correctness checks
only (a handful of steps, `--max-steps` capped) before handing a scenario
off to the remote machine for the real run.

## Running

Regenerate the strain tables from real ANSYS data (exact command used for
the currently-committed `7turns_6mm_45_30mm` tables — adjust paths/column
names for different data, but keep `--surface` explicit and check whether
`--coord-precision`/`--drop-incomplete-columns` are needed per the
quadratic-mesh note above):
```bash
cd strain-defect
python3 strain_to_jc.py \
  path/to/EPTOX_file.txt path/to/LOCY_file.txt path/to/LOCZ_file.txt \
  --out-dir . \
  --node-col "Node Number" --strain-col "EPTOX ()" \
  --x-col "LOCY (mm)" --y-col "LOCZ ()" \
  --strain-sep "\t" --x-sep "\t" --y-sep "\t" \
  --coord-precision 3 --drop-incomplete-columns --surface top
```
Then the FreeFEM side:
```bash
FreeFem++ -nw mesh_report_strain_tape.edp          # verify region volumes/
                                                     # boundary areas FIRST
FreeFem++ -nw init_strain_tape_checkpoint.edp       # once
FreeFem++ -nw step_strain_tape_transient.edp        # repeat to advance
# or, for a full automated run:
python3 run_transient.py --ratio 1.05
```

`run_transient.py` is a simplified version of
`3D-slit/electrothermal/run_transient.py` — no fracLeft/deviation/recovery
state machine (nothing to split left/right here), no heater-power flag.
Stops on runaway Tmax, NaN/Inf, `t` stalling, or `--max-steps`. Tmax trend
(`converging`/`plateaued`/`diverging`) is recorded in `status.json` as
informational metadata only — unlike the slit track's fracLeft trend, it
does NOT drive an early-exit decision; no real run data exists yet to
calibrate a threshold against (same "first-pass, not yet calibrated"
caveat this repo already applies elsewhere to unvalidated thresholds).

**For a real run, use Condor** (`condor/README.md`) rather than running
`run_transient.py` directly on whatever machine has FreeFEM — one job per
ratio, modeled on `3D-slit/electrothermal/condor/` but simpler (no
`shared/` dependency, so the payload is a single flat directory). The
Condor job executable itself was validated locally (container build + the
actual `condor_run_ratio.sh` run end-to-end against the real strain data,
see `condor/README.md`'s verification section) — only the real
`condor_submit`/pool-specific resource numbers remain unverified.

## Diagnostics

Only 2 voltage-tap pairs (4 taps total), all on the tape centerline
(z=width/2) — no RTDs, no Hall probes, no B-field:
- `V_defect_up`/`V_defect_down`: straddle the defect location (±`tapOffset`,
  default 2mm, `-tapoffset`), local differential voltage across the defect.
- `V_CL_plus`/`V_CL_minus`: total end-to-end tape voltage (x=0/x=Lx), same
  current-lead-reference concept as `3D-slit/shared/diagnostics_3d_slit.idp`.

`diagnostics_strain_tape.csv` columns: `t,I0,Tmax,V_CL_plus,V_CL_minus,
V_defect_up,V_defect_down`. `transient_strain_tape.csv` additionally tracks
`TmaxAtDefect` (temperature probed directly at the defect's x-location) and
`maxCurrentConservationRelErr` (same built-in consistency check as
`3D/step_3d_shell_transient.edp`).

## Material data (`data/`)

Copied from `3D-slit/shared/data/` (same measured property tables — Cu,
Hastelloy, Buffer, REBCO, Ag; no bottom-Ag-specific table needed since
there's only one Ag layer in this stack). Kept as its own copy, not a
cross-track reference, matching the existing per-track `data/` precedent
(`3D/data/` and `3D-slit/shared/data/` are already two separate copies).
`Jc0` (nominal REBCO critical current density) is unchanged from
3D/3D-slit — it's a material property, not something this geometry change
or the strain defect replaces; the strain map scales it locally, it doesn't
redefine the baseline.
