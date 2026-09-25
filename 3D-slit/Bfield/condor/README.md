# Condor sweep (Bfield, CPU-only)

Ratio-level parallelism: one Condor job per current ratio, each running
`run_bfield_transient.py` to completion inside a container. Ported from
`electrothermal/condor/` now that `step_3d_slit_transient_bfield.edp`
takes the matching `-ratio`/`-outprefix`/etc. flags (see
`../CLAUDE.md`'s "Ratio/wrapper parameterization" and "Continuous-solve
wrapper" sections). Same sandboxed-execute-node design as
`electrothermal/condor/` — see that track's `README.md` for the full
rationale; this file only covers what's different for Bfield.

## What's different from `electrothermal/condor/`

- **Reuses electrothermal's published container image** (same pinned
  digest) rather than building a separate one — see the comment in
  `sweep.sub`. The image is track-agnostic (FreeFEM + Ubuntu + python3
  only, no project code baked in), so there's no reason to duplicate the
  build/push/digest-pinning cycle for identical content. Build your own
  `local-freefem-bfield` image instead if you want per-track naming.
- **`payload.tar.gz` carries one extra file**: `bfield_3d_slit.idp`
  (the Biot-Savart self-field / Kim-model code), alongside the same
  `init_*`/`step_*`/wrapper trio electrothermal's payload has.
- **No `--ramp-rate`/`--ramp-dt` hardcoded in `sweep.sub`'s
  `arguments`** — that slow-ramp scenario was calibrated and validated
  for electrothermal specifically (a collaborator requirement); this
  workflow hasn't validated it at all. Defaults to the `.edp`'s original
  fixed 0.5s ramp.
- **`run_bfield_transient.py` has no `--resume`** (see `../CLAUDE.md`) —
  doesn't matter for Condor's own "no resume-on-preemption" v1 design
  (below), since a fresh sandbox never has anything to resume from
  either way.
- **No `prePulse`/`runaway_before_pulse` status split** — `"runaway"`
  covers both the heater-triggered and pure-overcurrent cases here,
  same as `run_bfield_transient.py` itself (see `../CLAUDE.md`).

## Validated locally (on a Mac, under Docker's x86_64 emulation)

- `make_payload.sh` produces the expected tarball layout: `work/`
  (`init_3d_slit_transient_checkpoint.edp`, `step_3d_slit_transient_bfield.edp`,
  `bfield_3d_slit.idp`, `run_bfield_transient.py`) and `shared/` (mesh/
  materials/diagnostics `.idp`s + `data/`'s 15 material tables) as
  siblings — confirmed via `tar tzf payload.tar.gz`.
- Built the identical container image electrothermal's `Dockerfile`
  produces (`freefem/freefem:latest` + `python3`) and ran the *actual*
  `payload.tar.gz` through `condor_run_ratio.sh` inside it — i.e. the
  exact tar-extract-then-run path a real Condor job takes, not just a
  direct volume-mounted `.edp` invocation. Result: `t=0.05s
  I0=21.7672 Tmax=77 TmaxL=77 TmaxR=77 fracLeft=0.5`, `status:
  "max_steps_exceeded"` (expected — the smoke test deliberately capped
  `--max-steps 1`). `I0=21.7672` **exactly matches the number
  electrothermal's own `condor/README.md` quotes for its identical
  validation** (same ratio, same step, same shared `IcRebcoActual`
  since both tracks use the same material/geometry constants) — a real
  cross-check, not a coincidence.
- **Not validated**: `condor_submit`/pool-specific syntax in `sweep.sub`
  (same caveat electrothermal's own `README.md` carries — I can't run
  Condor myself), and a full run to completion (would take hours even
  on real hardware).

## One-time setup

Same as `electrothermal/condor/README.md`'s "One-time setup" — this
reuses that same published image, so **no separate image build is
needed** unless you want a Bfield-tagged image for clarity (see above).
Ask your pool admins the same questions listed there (container syntax,
`request_memory`/`request_disk`, walltime limits) if you haven't
already for electrothermal — the answers apply here unchanged, it's the
same pool.

## Per-sweep steps

```bash
cd 3D-slit/Bfield/condor
./make_payload.sh                                     # packages payload.tar.gz
python3 make_ratios_list.py 0.7 > ratios.txt           # explicit list
python3 make_ratios_list.py --range 0.60 0.80 0.05 > ratios.txt  # or a range (inclusive stop)
mkdir -p logs
condor_submit sweep.sub
condor_q                                               # watch progress
```

Once every job finishes, collect results into the normal `runs/` tree —
manual, not a Condor `transfer_output_remaps`, same reasoning as
electrothermal (can't verify that syntax against this pool without
access):
```bash
cd ..                                                  # back to Bfield/
for d in condor/work/runs/*/; do mv "$d" runs/; done
```
(Bfield has no `export_sweep_hdf5.py`/`analyze_sweep_hdf5.py` equivalent
yet — those are electrothermal-specific downstream analysis tooling, not
ported here. Inspect `runs/<label>/transient_3d_slit.csv`/
`diagnostics_3d_slit.csv` directly, or use
`../shared/plot_slit_transient.py`/`plot_diagnostics_3d_slit.py`.)

## Auto-retry on RETRY_WORTHY failures

Same policy as `electrothermal/condor/sweep.sub`, same underlying
mechanism (UMFPACK on this project's ill-conditioned material tables —
see `../CLAUDE.md`'s adaptive-bisection section) — `on_exit_hold`/
`periodic_release`, capped at 3 automatic retries. Not independently
confirmed node-heterogeneous for Bfield specifically (electrothermal's
`r1p36`/`r1p83` evidence was electrothermal-specific), but the failure
mode it's guarding against is shared code, not workflow-specific.

## Known limitations (v1, deliberately simple — inherited from electrothermal)

- **No resume-on-preemption** — see `electrothermal/condor/README.md`'s
  identical section; the same tradeoff applies unchanged.
- **CPU-only**, same reasoning as electrothermal.
- `request_memory`/`request_disk`/the container syntax block are
  first-pass guesses **carried over from electrothermal's measurements**,
  not re-measured for Bfield's extra per-step Biot-Savart self-field
  cost — run one job and check actual usage before trusting a big sweep.
- Bfield's own physics-level open items (unvalidated above-Ic Jc-growth
  controller, isotropic-vs-anisotropic Kim model verification) are
  tracked in `../CLAUDE.md`, not here — this file is Condor-mechanics
  only.
