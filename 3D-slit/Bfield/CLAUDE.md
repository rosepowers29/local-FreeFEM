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

## Adaptive bisection / runaway cutoff (ported from `electrothermal/`)

`step_3d_slit_transient_bfield.edp` now carries the same PDE-solve safety
net as `electrothermal/step_3d_slit_transient_diag.edp` — see that
track's `CLAUDE.md` ("Ramp collapse breaks down above Ic" / "Adaptive
step-size bisection") for the full crash history that motivated it. Same
root cause applies here: `heatStep`'s `solve` leaves `solver=`
unspecified, so FreeFEM solves the SPD bilinear form as a general system
via UMFPACK, which can fail on this project's ill-conditioned material
tables in a way found to be node/hardware-dependent, not a deterministic
function of `dt`.

- **`-maxsteprise`** (default `500.0` K) / **`-maxbisections`** (default
  `10`): if a step's `T[].max`/`T[].min` moves further than this from
  `Told` (or produces NaN), the solve is retried at half `dtTry` — up to
  `maxBisections` times, then a hard `assert(false)`. Only `heatStep`
  retries; `Told`/`source`/`qHeaterNow` are computed once per step since
  they don't depend on `dt`.
- **`-tmaxcutoff`** (default `900.0` K): checked in the step loop's own
  `while` condition (`T[].max < tmaxCutoff`), so a run that's already
  genuinely runaway stops immediately rather than grinding through the
  rest of `maxStepsThisRun`.
- **CSV/diagnostic write ordering fixed**: `transient_3d_slit.csv`'s
  `Tmax`/`TmaxLeft`/`TmaxRight` now write *after* the (possibly-bisected)
  solve and *after* `t` advances, not before — the same stale-row bug
  electrothermal found and fixed applied here too (a CSV row's `Tmax`
  was always one physical step behind the checkpoint). Voltage-tap/Hall-
  probe diagnostics are unchanged: they still reflect the electrical
  solve computed from the step's *starting* temperature (the model's
  existing staggered-scheme convention).
- **Deliberately NOT ported**: the above-Ic Jc-fraction step-growth
  controller (`-rampdt-aboveic`/`-maxjcfracchange`, and today's
  `jcRef`-normalization fix in electrothermal). This script's
  `I0Target` is still hardcoded to `0.7*IcRebcoActual` (see near the top
  of the file) — `t` never crosses `Ic`, so that controller has no phase
  to operate in and would be dead code until `currentRatio` becomes a
  parameter here too. Planned alongside the `run_transient.py`-
  equivalent wrapper for this workflow, not before.
- **Verified**: full script parses clean against the real FreeFEM v4.12
  parser (`docker run freefem/freefem`, matching electrothermal's own
  verification method) with no compile errors. A complete real invocation
  against the freshly re-initialized checkpoint ran to `Ok: Normal End`:
  resumed at `t=0, Tmax=77`, advanced one step to `t=0.05s`, and wrote
  `Tmax=77 TmaxLeft=77 TmaxRight=77 fracLeft=0.5 bisections=0` —
  bit-identical to the pre-existing validated baseline at the ramp's
  quiescent start (`I0=0`, no source term yet), confirming the reordered
  CSV write, the bisection loop's non-triggering path, and the
  checkpoint round-trip (E-arrays correctly zero, matching `I0=0`) all
  work. **Not yet verified**: the bisection loop actually triggering and
  recovering from a real blowup (this step had no source term, so
  `blewUp` was never true) — same caveat electrothermal's own initial
  bisection verification carried before real-hardware exposure found
  `r1p36`/`r1p83`/`r1p474`.

Outputs land in this directory: `transient_3d_slit.csv`
(`t,I0,Tmax,TmaxLeft,TmaxRight,fracLeft`), `diagnostics_3d_slit.csv`
(voltage taps, RTDs, real Hall-probe `H1`/`H2` B-field values — not the
`-999` sentinel used by the no-B-field workflow), and
`diagnostics_positions_3d_slit.csv` (sensor geometry metadata, rewritten
each invocation).
