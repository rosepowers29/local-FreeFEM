# Condor sweep (electrothermal, CPU-only)

Ratio-level parallelism: one Condor job per current ratio, each running
`run_transient.py` to completion inside a container. This pool's execute
nodes are sandboxed (no shared filesystem with the submit node), so
every job's inputs and outputs are transferred explicitly rather than
assumed reachable via a shared path -- unlike the single-machine
workflow in `../README.md`, this can't just reference repo paths
directly.

**Container + code validated locally (on a Mac, under x86_64 emulation
via Colima); Condor submission itself is not.** I can't run Condor
myself, so `sweep.sub`'s actual submission to a real pool is still
unverified -- but the image and payload have been:
- `Dockerfile`'s first two approaches both failed and were caught before
  being handed off: apt's `libfreefem++`/`libfreefem0` on `ubuntu:22.04`
  turned out to be library-only packages with no actual `FreeFem++`
  binary, and `freefem` doesn't exist as a conda-forge package either.
  Settled on building a thin layer (just `+python3`) on top of the
  **official** `freefem/freefem` Docker Hub image instead.
- Ran the real `mesh_report_3d_slit.edp` inside the built image -- built
  the identical mesh (`nv=87870 nt=487200 nbe=26048`, matching this
  project's real remote box exactly) and exited cleanly.
- Ran `spike_test_getargv.edp` inside the built image -- `getARGV` works
  identically on this image's FreeFEM v4.12.
- Ran the *actual* `make_payload.sh` tarball through `run_transient.py`
  inside the container against `step_3d_slit_transient_diag.edp` for two
  real physics steps -- `t=0.05s I0=21.7672 ... fracLeft=0.5` exactly
  matches real remote-box data from the same ratio/step. Mesh build,
  materials loading, and the `-ramprate`/`-rampdt` params all ran
  without error.
- **Not validated locally**: a full run to completion (would take hours
  even on real hardware, let alone under this Mac's ~14x emulation
  penalty -- stopped intentionally once correctness was established,
  not left to finish), and the actual `condor_submit`/pool-specific
  syntax in `sweep.sub`, which only your pool can validate.

**If you smoke-test on a non-x86_64 Mac like this one again**: pass
`--steps-per-invocation 1` explicitly. The production default is 20
(amortizes the mesh-rebuild cost -- see `../CLAUDE.md`), which is fine
on real hardware but means one `run_transient.py` invocation silently
runs up to 20 physical steps before returning -- at this Mac's ~14x
emulation penalty (~1500-1600s/step instead of ~116.5s), that's hours
for what's meant to be a quick sanity check.

## One-time setup

1. **Build and publish the FreeFEM container image** to GitHub Container
   Registry, tied to this repo (`rosepowers29/local-FreeFEM`).
   ```bash
   # one-time: create a classic PAT with write:packages scope at
   # github.com -> Settings -> Developer settings -> Personal access tokens,
   # then log in (--password-stdin keeps the token out of shell history)
   echo <your-token> | docker login ghcr.io -u rosepowers29 --password-stdin

   docker build -t ghcr.io/rosepowers29/local-freefem-electrothermal:latest .
   docker push ghcr.io/rosepowers29/local-freefem-electrothermal:latest
   # or, if your pool wants a .sif instead of a Docker reference:
   apptainer build image.sif docker://ghcr.io/rosepowers29/local-freefem-electrothermal:latest
   ```
   After the first push, go to the package's GitHub page (Package
   settings -> Change visibility) and make it **public** -- new GHCR
   packages default to private, and Condor execute nodes have no
   registry credentials configured for anonymous pulls. The image itself
   contains only FreeFEM + Ubuntu + Python (no project code or data --
   that's transferred separately via `payload.tar.gz`), so there's no
   real exposure from making it public.
2. **Ask your pool admins** (this is a generic HTCondor design -- I have
   no information about this specific pool's configuration):
   - Which container syntax `sweep.sub` should use -- `universe =
     container` + `container_image =` (current top block), vs `universe
     = docker`, vs vanilla universe + `+SingularityImage`/
     `+SingularityBind`. Swap the top block of `sweep.sub` accordingly.
   - Realistic `request_memory`/`request_disk` for an ~88K-DOF FEM solve
     -- the values in `sweep.sub` are unverified first-pass guesses, not
     measured on this pool.
   - Typical/maximum job walltime. Each ratio takes on the order of
     hours (~90-100 steps x ~116.5s/step PDE solve floor, see
     `../CLAUDE.md`'s profiling section) -- some pools require special
     queueing/walltime flags for jobs this long.
3. `sweep.sub` already points at
   `ghcr.io/rosepowers29/local-freefem-electrothermal:latest` -- update
   it only if you push under a different name/tag.

## Per-sweep steps

```bash
cd 3D-slit/electrothermal/condor
./make_payload.sh                                     # packages payload.tar.gz
python3 make_ratios_list.py 0.9 0.925 0.95             # writes ratio,label pairs
python3 make_ratios_list.py 0.9 0.925 0.95 > ratios.txt
mkdir -p logs
condor_submit sweep.sub
condor_q                                               # watch progress
```

Once every job finishes (`condor_q` shows none running/idle for this
sweep), collect results into the normal `runs/` tree. This is a manual
step, not a Condor `transfer_output_remaps`, because I couldn't verify
that syntax against this pool's actual HTCondor version -- safer to keep
this transparent and debuggable than to gamble on it silently
misplacing output:
```bash
cd ..                                                  # back to electrothermal/
for d in condor/work/runs/*/; do mv "$d" runs/; done
python3 export_sweep_hdf5.py
python3 analyze_sweep_hdf5.py
```

## Known limitations (v1, deliberately simple)

- **No resume-on-preemption.** With `should_transfer_files=YES` and
  `when_to_transfer_output=ON_EXIT`, an evicted job's sandbox (and all
  its progress) is discarded -- Condor restarts it in a fresh sandbox
  with no checkpoint to resume from, wasting whatever compute happened
  before eviction. If preemption turns out to be common on this pool and
  this becomes a real practical cost, the next step would be Condor's
  `ON_EXIT_OR_EVICT` output transfer combined with wiring
  `run_transient.py`'s existing `--resume` support to the evicted
  checkpoint. Not built here -- it adds real complexity and there's no
  evidence yet it's needed for this pool.
- **CPU-only**, per your call: GPU would need a PETSc+CUDA-enabled
  FreeFEM build (unconfirmed whether one exists for this pool) plus more
  solver work with uncertain payoff -- see `../CLAUDE.md`'s `solver=CG`
  results, which didn't beat the CPU default.
- `request_memory`/`request_disk`/the container syntax block are all
  first-pass guesses pending this pool's actual constraints -- see
  setup step 2 above.
- The `--ramp-rate 20 --ramp-dt 999` in `sweep.sub`'s `arguments` line
  is hardcoded for the whole sweep (every job uses the same ramp
  settings) -- edit that line directly if a given sweep needs different
  values; not built as a per-job-configurable field since every sweep so
  far has used one ramp scenario at a time.
