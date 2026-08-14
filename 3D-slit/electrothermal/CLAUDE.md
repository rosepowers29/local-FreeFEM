# 3D-slit/electrothermal/CLAUDE.md — agent notes for this workflow

See `3D-slit/CLAUDE.md` for the track-wide overview (why the split, the
shared/ dependency, mesh region/label reference — applies here too).
This file is deltas/gotchas specific to the electrothermal (no-B-field)
scripts.

## Which script is canonical

`step_3d_slit_transient_diag.edp` is the canonical no-B-field script:
correct per-x-resolved electrical model, full diagnostics export, just
without the B-field/Kim-model feedback. Use it unless you're specifically
after one of the reference scenarios below.

| Script | Status |
|---|---|
| `step_3d_slit_transient_diag.edp` | **canonical** — correct electrical model, no B-field |
| `step_3d_slit_heater_onesided.edp` | reference/comparison only (steady, always-on heater — different scenario, not a bug; found to diverge rapidly, matching the finding that a continuous 13W heater at 0.7×Ic has no stable steady state) |
| `step3_3d_slit_steady_verify.edp` | symmetric baseline, no heater (already validated to converge, `Tmax=77.8674K`, matching the no-slit case) |
| `export_slit_profile.edp` | exports a spatial temperature profile from a `step3_3d_slit_steady_verify.edp` checkpoint |
| `mesh_report_3d_slit.edp` | pure geometry/mesh export and verification, no physics |

Each has its own `init_*.edp` and its own checkpoint filename — they do
not share state:
- `step_3d_slit_transient_diag.edp` ↔ `init_3d_slit_transient_checkpoint.edp` → `ckpt_3d_slit_transient.txt`
- `step3_3d_slit_steady_verify.edp` ↔ `init_3d_slit_checkpoint.edp` → `ckpt_3d_slit.txt`
- `step_3d_slit_heater_onesided.edp` ↔ `init_3d_slit_heater_checkpoint.edp` → `ckpt_3d_slit_heater.txt`

## Checkpoint format

All three checkpoints in this directory are the plain `t, T[]` format
only (no E-arrays — those only exist in `Bfield/`'s checkpoint).
**Never resume this directory's `ckpt_3d_slit_transient.txt` with
`Bfield/`'s step script, or vice versa** — same filename now exists in
both directories post-reorg, but the format differs. Re-run the matching
`init_*.edp` when in doubt.

This directory currently has **no checkpoints on disk** — the old
transient checkpoint was stale/mismatched provenance and moved to
`archive/`; run the relevant init script first for whichever scenario
you're running.

## Physics simplification inventory

Hastelloy (included, real resistivity) and buffer (excluded, placeholder
conductivity) simplifications are shared with `Bfield/` — see
`3D-slit/CLAUDE.md`. There is no B-field model in this directory at
all — `diagnostics_3d_slit.csv`'s `H1`/`H2` columns are always the
`-999` (`hallNotModeled`) sentinel here, which `plot_diagnostics_3d_slit.py`
checks for to decide whether to render the B-field chart.

## Running

```bash
cd 3D-slit/electrothermal
FreeFem++ -nw init_3d_slit_transient_checkpoint.edp   # once, to (re)initialize
FreeFem++ -nw step_3d_slit_transient_diag.edp         # repeat to advance; 1 timestep/invocation
```

Substitute the matching init/step pair for the `steady_verify` or
`heater_onesided` scenarios instead. Outputs land in this directory:
`transient_3d_slit.csv`, `diagnostics_3d_slit.csv`,
`diagnostics_positions_3d_slit.csv` (same schema as `Bfield/`'s, minus
real B-field values).

## Continuous-solve wrapper (`run_transient.py` / `sweep_transient.py`)

Only `step_3d_slit_transient_diag.edp` and
`init_3d_slit_transient_checkpoint.edp` are wrapper-aware — the
`steady_verify`/`heater_onesided` scenarios still need manual
re-invocation as documented above.

- **`getARGV` is used here for the first time anywhere in this repo**
  (`real currentRatio = getARGV("-ratio", 0.7); string outPrefix =
  getARGV("-outprefix", "");`). Defaults reproduce today's exact
  hardcoded behavior, so plain `FreeFem++ -nw step_3d_slit_transient_diag.edp`
  with no flags is unaffected. **Requires `include "getARGV.idp"`** near
  the top of any file that calls it — confirmed by direct testing:
  `getARGV` doesn't work without it. Both wrapper-aware `.edp` files here
  already have it; if you copy this pattern into a new script, don't
  forget it.
- `outPrefix` is prepended to **every** output/checkpoint filename in
  both files, including `int diagFileCheck = exec("test -s "+outPrefix+
  "diagnostics_3d_slit.csv");` — this line uses the same literal
  filename as the `ofstream fdiag(...)` two lines above it but is easy
  to miss if re-templating by hand, since it's inside a shell `exec()`
  call, not a stream constructor.
- The wrapper's stop-condition thresholds (900K runaway, 0.01 deviation/
  0.002 recovery epsilon on `fracLeft`, 0.1s hold time) are first-pass
  placeholders — nobody has calibrated them against a real `fracLeft`
  trajectory yet. Sanity-check them against real output before trusting
  a long unattended sweep (see the plan's verification checklist).
- The wrapper has **no rate-of-change/plateau fallback** for a run where
  `fracLeft` asymptotes just outside `recover-eps` without fully
  returning to parity — deliberately deferred rather than guessing at a
  second heuristic with no real data. If a real run shows this pattern,
  that's the first extension point.
- "Stopping" means the wrapper simply doesn't launch the next
  invocation — there's no mid-solve signal-based kill, since each
  invocation is already a short, complete process with no internal
  iteration loop to interrupt.
- **`FreeFem++` binary resolution**: `run_transient.py`/`sweep_transient.py`
  don't assume it's on `PATH` — resolution order is `--freefem-bin` flag,
  then `$FREEFEM_BIN` env var, then `PATH`. Needed in practice: a
  from-source/home-directory FreeFEM install on a remote machine is
  common and usually isn't on `PATH`.
