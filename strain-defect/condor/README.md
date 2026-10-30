# Condor sweep (strain-defect, CPU-only)

Ratio-level parallelism: one Condor job per current ratio, each running
`run_transient.py` to completion inside a container. Modeled directly on
`3D-slit/electrothermal/condor/` — read that track's README.md too, most
of its caveats (container syntax unverified against your pool, resource
requests are first-pass guesses, no resume-on-preemption) apply here
unchanged. This file covers what's different for this track.

**What's simpler here than electrothermal's setup**: this track has no
`../shared/` dependency — every `include` in `step_strain_tape_transient.edp`
resolves to a same-directory or `data/`-subpath file, so the payload is one
flat `work/` directory, not `work/` + a sibling `shared/`. See
`make_payload.sh`.

**Container + code validated locally** (on an Apple Silicon Mac, via
`colima` + Docker — no native FreeFEM package exists for macOS, see root
`CLAUDE.md`'s environment gotchas). **Condor submission itself is not** —
same limitation as electrothermal's setup, no Condor pool access from this
environment.

- Built `Dockerfile` locally (`docker build`, no `--platform` flag needed
  for this local correctness check — only the real GHCR push needs it, see
  step 1 below) and ran the **actual Condor job executable**
  (`condor_run_ratio.sh`) inside it, exactly as Condor would invoke it:
  extracted `payload.tar.gz`, ran `run_transient.py --ratio 1.05 --label
  condorsmoketest --force --max-steps 1 --steps-per-invocation 1`.
- Confirmed: `[defect] x=0.00875m` (matches the real `7turns_6mm_45_30mm`
  strain data, not a stale/placeholder value), current-conservation error
  exactly 0, `Ok: Normal End`, and `run_transient.py` correctly classified
  the capped run as `max_steps_exceeded` with `status.json` written as
  expected.
- Confirmed the **output path** lands exactly where `sweep.sub`'s
  `transfer_output_files = work/runs/$(label)` expects it —
  `work/runs/condorsmoketest/{status.json,transient_strain_tape.csv,
  diagnostics_strain_tape.csv,diagnostics_positions_strain_tape.csv,
  ckpt_strain_tape.txt,run.log}` all present. (Electrothermal's README
  flags a real gotcha here — `transfer_output_files` returns only the
  basename to the submit directory, so the label itself must make the path
  unique; this track's single `base_dir="runs"` has no second sweep
  variant to collide with, so no `noheater_`-style prefixing is needed.)
- One timestep took **~330s wall-clock inside this local, emulated
  container** (vs. ~260-290s measured directly against `freefem/freefem`
  earlier in this track's development, before the python3 layer / extra
  subprocess wrapper) — consistent with container+subprocess overhead, not
  a sign of anything wrong. **Real Condor execute-node timing is
  completely unmeasured** — unlike electrothermal (which has real remote-
  box data, ~116.5s/step PDE-solve floor), this track has never run
  outside this local, emulated Mac. Don't assume a resemblance between
  local-emulated timing and a real x86_64 execute node's timing in either
  direction until a real job comes back.
- **Not validated**: the actual `condor_submit`/pool-specific syntax in
  `sweep.sub` (only your pool can validate), and a full run to completion
  at any ratio (would take hours even on real hardware).

## One-time setup

1. **Decide whether to reuse electrothermal's published image or build your
   own.** `sweep.sub` currently points at
   `ghcr.io/rosepowers29/local-freefem-electrothermal@sha256:8b39db74c15...`
   — electrothermal's already-published image. The `Dockerfile` in this
   directory is byte-identical (FreeFEM + python3, nothing track-specific
   baked in; all strain-defect code/data travels via `payload.tar.gz`), so
   there is no FUNCTIONAL reason to publish a second, duplicate image.
   Reusing it means skipping straight to step 2. If you'd rather have a
   dedicated image name for this track (e.g. for clarity in your GHCR
   package list), build and push it the same way electrothermal's
   README.md step 1 describes:
   ```bash
   docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
       -t ghcr.io/rosepowers29/local-freefem-strain-defect:latest --push .
   ```
   `--platform linux/amd64` is required regardless of your build
   machine's architecture — Condor execute nodes are x86_64, and
   `freefem/freefem` is amd64-only (see electrothermal's README.md for the
   full story of how this was found and fixed there). Then update
   `container_image` in `sweep.sub` to the new digest (`docker buildx
   imagetools inspect ...`), and make the package public on GHCR (new
   packages default to private; execute nodes have no pull credentials).
2. **Ask your pool admins** the same three questions electrothermal's
   README.md lists: container syntax (`universe = container` vs `docker`
   vs vanilla+Singularity), realistic `request_memory`/`request_disk` for
   this mesh size (~33K DOF at the real 115mm length — smaller than
   electrothermal's ~88K DOF slit mesh, so the request_memory/disk guesses
   below are probably generous, but unmeasured), and typical/maximum job
   walltime (genuinely unknown for this track — see the timing caveat
   above, there's no real-hardware number to extrapolate from yet).
3. **Before your first real sweep**, regenerate the strain tables and
   payload fresh if anything about the strain data, `--surface` choice, or
   resampling resolution has changed since you last ran `strain_to_jc.py`
   — `make_payload.sh` bundles whatever's currently sitting in this
   track's directory, with no staleness check (see that script's header
   comment).

## Per-sweep steps

```bash
cd strain-defect/condor
./make_payload.sh                                        # packages payload.tar.gz
python3 make_ratios_list.py 1.0 1.05 1.1 1.15 1.2 > ratios.txt   # explicit list
python3 make_ratios_list.py --range 1.00 1.20 0.02 > ratios.txt  # or a range (inclusive stop)
mkdir -p logs
condor_submit sweep.sub
condor_q                                                  # watch progress
```

Once every job finishes (`condor_q` shows none running/idle for this
sweep), collect results into the normal `runs/` tree — a manual step, not
a Condor `transfer_output_remaps`, same reasoning as electrothermal
(couldn't verify that syntax against an actual pool, safer to keep this
step transparent):
```bash
cd ..                                                     # back to strain-defect/
for d in condor/work/runs/*/; do mv "$d" runs/; done
```
No `export_sweep_hdf5.py`/`analyze_sweep_hdf5.py` equivalent exists yet for
this track — `transient_strain_tape.csv`/`diagnostics_strain_tape.csv` are
plain per-ratio CSVs for now. Say if you want a cross-ratio summary script
once you have real sweep data to build one against.

## Auto-retry on RETRY_WORTHY failures

Same mechanism and rationale as electrothermal's `sweep.sub` (`run_transient.py`
exits 1 for `crashed`/`init_failed`/`numerical_divergence`/`no_data`;
`on_exit_hold`/`periodic_release` auto-requeues up to 3 times). Carried
over as a reasonable default — this track has no node-heterogeneity
evidence of its own yet (never run on a real pool), unlike electrothermal
where it was built in direct response to an observed, real failure pattern.

## Known limitations (v1, deliberately simple — same as electrothermal)

- **No resume-on-preemption.** An evicted job's sandbox (and progress) is
  discarded; Condor restarts fresh with no checkpoint to resume from.
- **CPU-only.**
- `request_memory`/`request_disk`/the container syntax block, and real
  per-step wall-clock time, are all unmeasured against this pool or any
  real execute-node hardware — see the timing caveat above. This track is
  earlier-stage than electrothermal's Condor setup in this specific
  respect: electrothermal has real remote-box numbers to anchor its
  guesses; this track doesn't yet.
- `--runaway-tmax` in `ratios.txt` defaults to the generic 900 (via
  `make_ratios_list.py`) — do NOT reuse electrothermal's calibrated 250
  for ratio≥1.0 batches; that number was calibrated for a heater-triggered
  quench on a different tape/model and has no reason to transfer to a
  defect-triggered, single-channel scenario with zero real runs behind it
  yet. Revisit once you have real data to calibrate against (same
  discipline electrothermal's CLAUDE.md documents for its own threshold).
- The `--ramp-rate 20 --ramp-dt 999` pairing in `sweep.sub`'s `arguments`
  line is hardcoded for the whole sweep — edit directly if a given sweep
  needs different values.
