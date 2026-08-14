# 3D-slit — B-field workflow

Full transient laser-slit scenario with self-field/B-field feedback: the
current ramps to 0.7×Ic over 0.5s, a 2mm×2mm / 13W / 10ms spot heater
fires on the LEFT side only (z=width/4), then the run continues for 1.5s
to observe recovery or runaway. Throughout, the Biot-Savart self-field is
computed from the reconstructed current distribution and fed back into
the REBCO critical current via an isotropic Kim model
(`Jc(B,T)=Jc(T)/(1+|B|/B0)`), lagged one timestep. See
`bfield_3d_slit.idp`'s header comments for the full technical writeup and
validation history, and `CLAUDE.md` in this directory for gotchas.

Electrical model: outside the slit's x-range (10-190mm), one
equipotential channel. Within the slit, current splits into two
independent parallel paths (left/right of the slit), matched by equal
voltage drop across the slit's length — a cheap bisection redone every
timestep, no extra 3D solve involved.

## Files

- `step_3d_slit_transient_bfield.edp` — the canonical script; the only
  one in this directory.
- `bfield_3d_slit.idp` — Biot-Savart self-field calc, Kim-model
  B-suppressed conductivity (`sigmaScB`, `JcTB`), the B-aware electrical
  solvers (`solveEFullB`/`solveEHalfB`/`computeSelfFieldB`).
- `init_3d_slit_transient_checkpoint.edp` — (re)initializes
  `ckpt_3d_slit_transient.txt` in this directory to `t=0`, uniform
  `T=77K`, and zeroed E-field arrays.

Both scripts pull shared mesh/material code from `../shared/` — see
`3D-slit/CLAUDE.md`.

## How to run

```bash
cd 3D-slit/Bfield
FreeFem++ -nw init_3d_slit_transient_checkpoint.edp
FreeFem++ -nw step_3d_slit_transient_bfield.edp   # run repeatedly to continue
```

Each invocation advances **one timestep** (`maxStepsThisRun` near the top
of the script) and is expensive (minutes, not seconds — see root
`CLAUDE.md`), so expect to run this many times in sequence. It's always
safe to stop and resume: the checkpoint is only rewritten, atomically,
after a step completes successfully.

## What to watch for

Whether `fracLeft` (the fraction of transport current on the left side of
the slit, 0.5 at the symmetric start) shifts away from 0.5 once the
heater turns on and the left side warms — that's the central question
this model was built to answer. `TmaxLeft` vs. `TmaxRight` (also in
`transient_3d_slit.csv`) show whether the disturbance stays localized to
the heated side or spreads to both.

## Output

Written to this directory, plain CSV, no display required (`-nw`):
- `transient_3d_slit.csv` — `t,I0,Tmax,TmaxLeft,TmaxRight,fracLeft`, one row/timestep
- `diagnostics_3d_slit.csv` — voltage taps, RTDs, and real Hall-probe
  `H1`/`H2` self-field values, one row/timestep
- `diagnostics_positions_3d_slit.csv` — sensor geometry metadata, rewritten each invocation

Plot with `../shared/plot_slit_transient.py transient_3d_slit.csv` and
`../shared/plot_diagnostics_3d_slit.py diagnostics_3d_slit.csv`.
