# Slit + One-Sided Heater Transient — Handoff

Everything needed to continue the running simulation locally.

## Setup
- Requires FreeFEM 4.13+ with the `msh3` plugin (see the 3D README for the
  `libfreefem++`/`libfreefem0` install note if `load "msh3"` fails).
- Put all files in one directory, `cd` into it, run everything from there
  (all paths in the scripts are relative to the current directory).

## Current state — resume in progress
`ckpt_3d_slit_transient.txt` and `transient_3d_slit.csv` hold the run
**already in progress**: ramped through t=0.4s (I0=174.1A, still in the
ramp phase, nothing has happened yet — this is expected). Just keep
running the same command to continue from here:

```bash
FreeFem++ -nw step_3d_slit_transient.edp
```

Each invocation advances **one timestep** (`maxStepsThisRun=1` near the
top of the script) and takes roughly **150-230 seconds** on the hardware
this was developed on — adjust `maxStepsThisRun` upward if your machine
is faster and you want fewer, larger invocations. Progress appends to
`transient_3d_slit.csv` (columns: t, I0, Tmax, TmaxLeft, TmaxRight,
fracLeft) and re-saves the checkpoint after every step, so it's always
safe to stop and resume.

## Remaining timeline
- t=0.4 → 0.5: 2 more ramp steps (dt=0.05s) to reach full current
  (I0=217.7A = 0.7×Ic)
- t=0.5 → 0.51: 5 steps (dt=0.002s) through the 13W/10ms heater pulse on
  the left side (z=width/4)
- t=0.51 → 0.59: ~8 steps (dt=0.01s) of recovery/runaway observation

**What to watch for**: whether `fracLeft` (currently 0.5 throughout)
shifts away from 0.5 once the heater turns on and the left side warms —
that's the actual question this whole slit model was built to answer.
`TmaxLeft` vs `TmaxRight` will also show whether the disturbance stays
localized to the heated side or whether both sides heat up together.

## Other included scripts (not currently mid-run, but complete/tested)
- `mesh_report_3d_slit.edp` — mesh/geometry export and verification
- `step3_3d_slit_steady_verify.edp` + `init_3d_slit_checkpoint.edp` — the
  symmetric no-heater baseline check (already run to convergence:
  Tmax=77.8674K, confirmed matching the no-slit case)
- `export_slit_profile.edp` — exports a spatial temperature profile from
  a slit-model checkpoint
- `step_3d_slit_heater_onesided.edp` + `init_3d_slit_heater_checkpoint.edp`
  — a STEADY (always-on, not pulsed) one-sided heater test; found to
  diverge rapidly (matches the established finding that a continuously-on
  13W heater at 0.7×Ic has no stable steady state) — kept for reference,
  superseded by the transient script for actually observing redistribution

## Performance note
Solves here are slower than the no-slit 3D model (~150-230s/step vs
~40-50s), driven by the very fine local z-resolution needed to resolve
the 5um-wide slit. Not a bug — confirmed via isolated testing that this
is a genuinely bigger, more expensive problem, not pathological
ill-conditioning.
