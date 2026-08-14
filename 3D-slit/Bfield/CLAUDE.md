# 3D-slit/Bfield/CLAUDE.md — agent notes for this workflow

See `3D-slit/CLAUDE.md` for the track-wide overview (why the split, the
shared/ dependency, mesh region/label reference — applies here too).
This file is deltas/gotchas specific to the B-field workflow.

## Canonical script

`step_3d_slit_transient_bfield.edp` — the only script here, and the only
script in the whole track with the full, current physics: per-x-resolved
electrical model (not single-point), diagnostics export, and
B-field/Kim-model feedback.

## Checkpoint format

`ckpt_3d_slit_transient.txt` (this directory's copy) =
`t, T[], Earr[], ElArr[], ErArr[]` (88054 lines: 1 + 87870 + 3×61). The
E-arrays exist specifically so `computeSelfFieldB`'s lagged design has
real data to read at the top of the next invocation — without them
persisting, B is silently always zero, forever, with no error (this
exact bug has happened before).

- **Never resume this directory's checkpoint with `electrothermal/`'s
  step script, or vice versa** — different format, even though the
  filename is now the same in both directories post-reorg. Re-run
  `init_3d_slit_transient_checkpoint.edp` (this directory's copy) to
  start fresh here.
- Quick sanity check after resuming: `tail -183 ckpt_3d_slit_transient.txt | head`
  should show small E-field-scale numbers, not ~77 (temperature-scale) —
  if it's ~77, you're inside the T array, meaning the E-arrays never
  got appended (old/wrong-format checkpoint).
- This directory currently has **no checkpoint on disk** (the old one
  was stale/mismatched provenance and was moved to `archive/` during the
  reorg) — run the init script first.

## Physics simplification inventory — B-field specific

- **B-field**: self-field only (no external circuit/return path —
  open-conductor approximation, weakest near current leads x=0/Lx,
  strongest near tape midpoint), lagged one full timestep (not
  self-consistent within a timestep), isotropic Kim model
  (`Jc(B,T)=Jc(T)/(1+|B|/B0)`, real REBCO Jc(B) is anisotropic),
  `B0=0.1T` is an unverified placeholder (no search access when set,
  no real Jc(B,T) data on hand).
- **REBCO's own current, when reconstructing K(x) for the self-field
  calc**, uses plain `sigmaSc` not `sigmaScB` — documented, deliberate,
  non-compounding (nothing here is itself persisted across steps).
- Full technical writeup + validation history: `bfield_3d_slit.idp`
  header comments (kept in sync with the actual code — trust the
  comments in that specific file over memory).
- Hastelloy/buffer simplifications are shared with `electrothermal/` —
  see `3D-slit/CLAUDE.md`.

## Running

```bash
cd 3D-slit/Bfield
FreeFem++ -nw init_3d_slit_transient_checkpoint.edp   # once, to (re)initialize
FreeFem++ -nw step_3d_slit_transient_bfield.edp       # repeat to advance; 1 timestep/invocation
```

Outputs land in this directory: `transient_3d_slit.csv`
(`t,I0,Tmax,TmaxLeft,TmaxRight,fracLeft`), `diagnostics_3d_slit.csv`
(voltage taps, RTDs, real Hall-probe `H1`/`H2` B-field values — not the
`-999` sentinel used by the no-B-field workflow), and
`diagnostics_positions_3d_slit.csv` (sensor geometry metadata, rewritten
each invocation).
