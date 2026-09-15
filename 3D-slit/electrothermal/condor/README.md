# Condor sweep (electrothermal, CPU-only)

Ratio-level parallelism: one Condor job per current ratio, each running
`run_transient.py` to completion inside a container. This pool's execute
nodes are sandboxed (no shared filesystem with the submit node), so
every job's inputs and outputs are transferred explicitly rather than
assumed reachable via a shared path -- unlike the single-machine
workflow in `../README.md`, this can't just reference repo paths
directly.

**None of this has been run or tested** -- I can't run Docker, Apptainer,
or Condor myself. Build/smoke-test each piece yourself before trusting a
real sweep to it, in the order below.

## One-time setup

1. **Build and publish the FreeFEM container image.** `Dockerfile` here
   uses the apt-based install + msh3-plugin symlink fix already verified
   working on this project's remote box (see root `CLAUDE.md`'s "FreeFEM
   environment gotchas") -- but the Dockerfile itself has never been
   built. Smoke-test it before trusting it:
   ```bash
   docker build -t <your-registry>/<your-image>:<tag> .
   docker run --rm <your-registry>/<your-image>:<tag> FreeFem++ -nw -v 0 -e 'cout << "ok" << endl;'
   docker push <your-registry>/<your-image>:<tag>
   # or, if your pool wants a .sif instead of a Docker reference:
   apptainer build image.sif docker://<your-registry>/<your-image>:<tag>
   ```
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
3. Fill in `container_image` in `sweep.sub` with your actual pushed
   image reference.

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
