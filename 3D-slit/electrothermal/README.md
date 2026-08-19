# 3D-slit — electrothermal workflow

The laser-slit tape's electrothermal behavior without B-field feedback:
correct per-x-resolved electrical model (current splits into independent
left/right channels within the slit's x-range, 10-190mm, matched by equal
voltage drop), full diagnostics export, no self-field/Kim-model coupling.
Plus reference/baseline scenarios kept alongside it. See `CLAUDE.md` in
this directory for gotchas and the canonical/reference breakdown.

## Files and scenarios

| Script | Init script | Checkpoint | What it does |
|---|---|---|---|
| `step_3d_slit_transient_diag.edp` | `init_3d_slit_transient_checkpoint.edp` | `ckpt_3d_slit_transient.txt` | **Canonical.** Same scenario as the B-field workflow (0.7×Ic ramp over 0.5s, 2mm×2mm/13W/10ms one-sided heater pulse, then recovery/runaway observation), minus B-field feedback. |
| `step3_3d_slit_steady_verify.edp` | `init_3d_slit_checkpoint.edp` | `ckpt_3d_slit.txt` | Symmetric, no-heater baseline — confirms the slit geometry alone doesn't change steady-state behavior vs. the no-slit case (already validated to converge at `Tmax=77.8674K`). |
| `step_3d_slit_heater_onesided.edp` | `init_3d_slit_heater_checkpoint.edp` | `ckpt_3d_slit_heater.txt` | Reference/comparison only — a STEADY (continuously-on, not pulsed) one-sided heater. Found to diverge rapidly, consistent with there being no stable steady state at a continuous 13W heater load at 0.7×Ic. Not a bug; superseded by the transient script for actually observing current redistribution. |
| `export_slit_profile.edp` | — (reads `ckpt_3d_slit.txt`) | — | Exports a spatial temperature profile from the `steady_verify` checkpoint to CSV. |
| `mesh_report_3d_slit.edp` | — | — | Pure geometry/mesh export and verification (region/boundary CSVs), no physics solve. |

All three step scripts pull shared mesh/material code from `../shared/`
— see `3D-slit/CLAUDE.md`.

## How to run

```bash
cd 3D-slit/electrothermal

# Canonical transient scenario
FreeFem++ -nw init_3d_slit_transient_checkpoint.edp
FreeFem++ -nw step_3d_slit_transient_diag.edp     # run repeatedly to continue

# No-heater baseline
FreeFem++ -nw init_3d_slit_checkpoint.edp
FreeFem++ -nw step3_3d_slit_steady_verify.edp     # run repeatedly to continue

# One-sided steady heater (reference only)
FreeFem++ -nw init_3d_slit_heater_checkpoint.edp
FreeFem++ -nw step_3d_slit_heater_onesided.edp    # run repeatedly to continue

# Mesh sanity check (no checkpoint needed)
FreeFem++ -nw mesh_report_3d_slit.edp
```

Each transient/steady invocation advances a small, fixed number of
timesteps (expensive — minutes, not seconds — see root `CLAUDE.md`), so
expect to run these many times in sequence. It's always safe to stop and
resume: each checkpoint is only rewritten, atomically, after a step
completes successfully.

## Output

Written to this directory, plain CSV, no display required (`-nw`):
- `transient_3d_slit.csv` — `t,I0,Tmax,TmaxLeft,TmaxRight,fracLeft`, one row/timestep (transient script only)
- `diagnostics_3d_slit.csv` — voltage taps, RTDs, `H1`/`H2` always `-999` (B-field not modeled here), one row/timestep (transient script only)
- `diagnostics_positions_3d_slit.csv` — sensor geometry metadata, rewritten each invocation (transient script only)
- `steady_verify_3d_slit.csv` — `x,T_rebco_left,T_rebco_right` spatial profile (from `export_slit_profile.edp`)

Plot with `../shared/plot_slit_transient.py transient_3d_slit.csv` and
`../shared/plot_diagnostics_3d_slit.py diagnostics_3d_slit.csv`.

## Automated continuous-solve wrapper

`run_transient.py` and `sweep_transient.py` automate the canonical
transient scenario above: no manual re-invocation, automatic
checkpoint/CSV reinitialization at the start of every run, and automatic
stop-condition detection (current split settled back near 50/50, thermal
runaway, or the scenario's own `tEnd` reached) instead of eyeballing
`transient_3d_slit.csv` by hand. See `CLAUDE.md` for the stop-condition
thresholds, their current (unvalidated) status, and the `getARGV`
parameterization these scripts rely on.

```bash
cd 3D-slit/electrothermal

# One current level, to completion -- wrap in nohup/screen/tmux: a single
# ratio can take hours, and an SSH/session drop kills a plain foreground
# invocation with no error and no status.json (this has happened).
nohup python3 run_transient.py --ratio 0.70 > r0p70_console.log 2>&1 &

# Sweep several current levels (colleague-handoff dataset), one
# independent runs/<label>/ directory per level -- same nohup caveat
nohup python3 sweep_transient.py --ratios 0.5,0.6,0.7,0.8,0.9,1.0 \
    > sweep_console.log 2>&1 &
```

**Always background any single-ratio or sweep invocation** (`nohup`,
`screen`, or `tmux`) — a dropped SSH session kills a foreground
`FreeFem++`/`run_transient.py` process outright, with no exception, no
error, and no `status.json`. If a run stops producing new lines in
`run.log` with no corresponding `status.json`, that's the signature to
look for: check `tail run.log` for whether the last line is a clean
`FINISHED status=...` (real stop) or trails off mid-invocation with no
error message (killed externally) — then `--resume` (see `CLAUDE.md`),
backgrounded this time.

If `FreeFem++` isn't on `PATH` (common for a from-source/home-directory
install on a remote machine), point the wrapper at it instead of relying
on shell aliases: `--freefem-bin /path/to/FreeFem++`, or set it once via
`export FREEFEM_BIN=/path/to/FreeFem++`.

Output lands in `runs/<label>/` (label auto-derived from the ratio, e.g.
`r0p70`): the usual checkpoint/CSVs (via `-outprefix`), plus
`run.log` (one line per invocation) and `status.json` (final outcome —
`settled`, `runaway`, `crashed`, `numerical_divergence`,
`reached_end_deviated`/`reached_end_no_deviation`,
`plateaued_off_parity`, or `max_steps_exceeded`, plus a `trend` field —
`converging`/`plateaued`/`diverging`/`null` — for any run that ended
still off-parity). `sweep_transient.py` aggregates every ratio's
`status.json` into `runs/summary.csv`. Re-running a label moves the
existing directory aside (`runs/<label>.bak.<timestamp>/`) rather than
deleting it — pass `--force` to delete instead. `runs/` is gitignored.

## HDF5 handoff export

`export_sweep_hdf5.py` converts a completed sweep's CSVs into a single
HDF5 file for handing off — FreeFEM's own HDF5 support
(`load "iohdf5"`/`savehdf5sol`) is a mesh/field visualization exporter,
not a fit for this tabular time-series data, so this is a Python (h5py)
post-processing step instead. Requires `h5py`
(`pip install h5py --break-system-packages` if not already present).

```bash
cd 3D-slit/electrothermal
python3 export_sweep_hdf5.py                 # auto-discovers every runs/*/status.json
python3 export_sweep_hdf5.py --labels r0p5,r0p7,r0p8,r0p9,r0p95,r0p99
```

Writes `runs/sweep.h5` with one group per label, e.g. `/r0p70`:
- group attributes = that run's `status.json` fields (`ratio`, `status`,
  `trend`, `n_steps`, `wall_clock_seconds`, `final_t`, `final_Tmax`,
  `final_fracLeft`)
- `/r0p70/transient/<column>` — one dataset per `transient_3d_slit.csv` column
- `/r0p70/diagnostics/<column>` — one dataset per `diagnostics_3d_slit.csv` column
- `/r0p70/positions/<column>` — one dataset per
  `diagnostics_positions_3d_slit.csv` column (string columns as
  variable-length UTF-8 — read them back with `.asstr()`, e.g.
  `f['r0p70/positions/channel'].asstr()[:]`, or you'll get raw `bytes`)

A run missing `diagnostics_3d_slit.csv`/positions (shouldn't happen for
this workflow, but e.g. an old run predating that feature) just skips
that subgroup rather than failing the whole export.
