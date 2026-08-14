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
