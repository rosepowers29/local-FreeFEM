# HTS Tape Quench Simulation (FreeFEM)

Electro-thermal finite-element simulation of thermal runaway ("quench")
behavior in a 2G REBCO-coated conductor tape, built in
[FreeFEM](https://freefem.org/). The model couples:

- **Current-sharing electrical physics**: a nonlinear power-law E-J
  relationship for the REBCO layer (with temperature-dependent critical
  current and n-value), in parallel with Ohmic conduction through the
  copper/silver stabilizer.
- **Transient/steady-state heat conduction** through the full multilayer
  tape stack, with temperature-dependent material properties (thermal
  conductivity, heat capacity, resistivity) taken from real measured data.
- **LN2 bath cooling applied only at the two tape ends** (the tape sits in
  a vacuum tube; heat can only escape by conducting along the tape's own
  length to the cooled contacts).

Two parallel model tracks are provided:

- **`2d/`** -- a 2D (length x thickness) cross-section model. Faster to
  run, used for the bulk of the parameter studies (steady-state
  verification, transient quench/recovery scenarios, overcurrent scans,
  minimum-quench-energy studies).
- **`3d/`** -- the full 3D model, adding the tape's width and a continuous
  copper shell that wraps the entire perimeter (top, bottom, and both
  edges, all one electrical conductor). Used to check that the 2D
  simplification holds up, and as the foundation for future width-resolved
  work (e.g. a longitudinal slit down the tape center).

Each subdirectory has its own `README.md` with details specific to that
model. This top-level document covers what's shared between them:
prerequisites, the physical/numerical approach, and general run
procedure.

## Prerequisites

- **FreeFEM**, version 4.13 or later. On Ubuntu/Debian:
  ```bash
  apt-get install freefem++ libfreefem++ libfreefem0
  ```
  The `libfreefem++`/`libfreefem0` packages are needed in addition to the
  base `freefem++` package -- they provide the plugin library (including
  `msh3`, required for the 3D model's mesh generation, and `iovtk` if you
  want to export fields to ParaView).
- If FreeFEM reports it can't find a plugin (`msh3.so` or similar) even
  after installing the above, it may be looking in the wrong directory.
  Check with:
  ```bash
  FreeFem++ -nw -v 0 -e 'load "msh3"' 2>&1 | head
  ```
  and if it fails with a path like `/usr/lib/ff++/<version>/lib/`, but the
  plugins actually live in `/usr/lib/freefem++/`, symlink them:
  ```bash
  mkdir -p /usr/lib/ff++/<version>
  ln -sf /usr/lib/freefem++ /usr/lib/ff++/<version>/lib
  ```
- **Python 3** with `numpy` and `matplotlib`, only needed for the plotting
  scripts (all simulation output is plain CSV; plotting is optional).

## How the scripts are organized

Every model (2D or 3D) follows the same pattern:

1. **A mesh module** (`hts_mesh_module.idp` / `hts_mesh_module_3d.idp`) --
   an FreeFEM "include" file defining the geometry, mesh, and material
   region numbering. Every other script starts with `include
   "hts_mesh_module...idp"`.
2. **A materials module** (`hts_materials.idp`) -- loads the tabulated
   material property data from `data/` and defines the REBCO
   current-sharing physics (critical current vs. temperature, the E-J
   power law, etc).
3. **Analysis scripts** (`step*.edp`) -- each one runs a specific study
   (steady-state check, transient quench scenario, parameter scan, etc).
   See the subdirectory READMEs for what each one does.

### Steady-state solves use Picard iteration, not time-stepping

Several scripts (anything with "steady" in the name) solve for a
steady-state temperature field by repeatedly: (1) solving the nonlinear
current-sharing problem given the current temperature guess, (2) solving
the resulting linear heat equation, (3) updating the temperature guess,
and repeating until converged. This is a fixed-point (Picard) iteration on
a genuinely time-independent problem -- there is no physical clock running
in these scripts, just iteration count. Transient scripts (anything with
"transient" in the name) are different: they march forward in real
physical time with an implicit-Euler scheme.

### Checkpoint/resume

Because a single solve (especially in 3D) can take tens of seconds to
minutes, every iterative or time-marching script saves its current state
to a small checkpoint file after each step and reloads it at the start of
the next run. This means:
- You can safely interrupt and resume any of these scripts.
- **You must run the matching `init_*_checkpoint.edp` script once before
  the first run** of any given analysis, to create a valid starting
  checkpoint (uniform 77K). See each subdirectory's README for which
  init script pairs with which analysis script.
- If you want to start an analysis over from scratch, just re-run its
  `init_*_checkpoint.edp` script to reset the checkpoint file.

## Quick start

```bash
cd 2d/
FreeFem++ -nw mesh_report.edp        # sanity-check the mesh first
python3 plot_mesh.py                 # (optional) visualize it
FreeFem++ -nw init_checkpoint.edp    # create a fresh starting checkpoint
FreeFem++ -nw step3_steady_state_verify.edp   # example: run a steady-state check
```

See `2d/README.md` and `3d/README.md` for the full list of available
analyses and what each one produces.
