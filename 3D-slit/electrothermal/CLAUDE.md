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
- **`--resume`**: continues an interrupted run (e.g. a remote-machine
  reboot/maintenance killing a mid-sweep invocation) in place instead of
  reinitializing — skips `reinit_run_dir`/the init script, and
  reconstructs `has_deviated`/the trend buffer/step count from the
  existing `transient_3d_slit.csv` (`load_resume_state`). `recover_since`
  is deliberately NOT reconstructed — if the split was already within
  `recover-eps` right when the process died, resuming just requires
  observing that closeness hold for `recover-hold-time` again rather
  than trusting unrecorded state. `wall_clock_seconds` in `status.json`
  after a resume reflects only time since that resume, not the full run.
  Requires the label's checkpoint to already exist; errors out clearly
  otherwise. **Without `--resume`, re-running a label always
  reinitializes** — safe for a fresh run, destructive to in-progress
  wall-clock investment for an interrupted one, so don't reach for the
  plain (no-flag) form to continue something that got killed mid-run.
- **`-steps-per-invocation` / `--steps-per-invocation`** (default 20):
  physical timesteps advanced per FreeFEM invocation, instead of the
  original hardcoded 1. This exists because every invocation is a brand
  new process, so `hts_mesh_module_3d_slit.idp`'s `cube(100,29,28)`
  mesh (~487K tetrahedra) plus its per-element slit region-labeling pass
  gets rebuilt from scratch on every single call regardless of how many
  physical steps run inside it -- raising this amortizes that one-time
  cost across more steps for free. **This is a first-pass default, not
  yet calibrated against real mesh-vs-solve timing data** -- see the
  profiling instrumentation below; tune it once you have real numbers
  from the target machine.
  - Not the same flag as `--max-steps`, which caps total *invocations*
    for a ratio as an outer safety net -- easy to confuse, deliberately
    different names.
  - `transient_3d_slit.csv`/`diagnostics_3d_slit.csv` still get one row
    per physical timestep regardless of this setting -- no time
    resolution is lost. What changes is `n_steps` in `status.json`:
    once this is >1, `n_steps` counts *invocations*, not physical
    timesteps, so `n_steps` will undercount actual CSV rows by roughly
    this factor. `wall_clock_seconds` is unaffected (still real elapsed
    time).
  - **Checkpoint safety**: the `.edp` now writes
    `ckpt_3d_slit_transient.txt` after *every* physical step, not once
    at the end of the invocation (this was a real correctness fix, not
    just a nice-to-have -- with the old once-per-invocation write, a
    crash/Condor-preemption partway through a multi-step invocation
    would leave the CSV further ahead than the checkpoint, and
    `--resume` would then re-write duplicate/overlapping `t` rows into
    the CSV). Rewriting the checkpoint every step is cheap (a small text
    file); the mesh -- the actual target of this optimization -- is
    still only built once per invocation.
  - **Verification before trusting a long run**: run one small smoke
    test (`--steps-per-invocation 5 --max-steps 2 --label stepstest`)
    and confirm `transient_3d_slit.csv` has the expected ~10 rows with
    monotonically increasing `t` and no duplicates, and that a
    `--resume` after killing it mid-invocation doesn't produce
    duplicate/overlapping `t` rows either. `getARGV`'s `int` overload
    (`getARGV("-steps-per-invocation", 1)`) is assumed to work the same
    way its `real`/`string` overloads were confirmed to on this repo's
    remote install -- not independently verified yet.

## Profiling instrumentation (mesh-rebuild vs. solve cost)

`step_3d_slit_transient_diag.edp` prints `[profile] ...` lines to stdout
(and therefore `run.log`) on every invocation, added specifically to
answer "is the per-invocation mesh rebuild actually worth optimizing" --
CLAUDE.md's own testing discipline is to measure this kind of thing
rather than assume it:
- `[profile] meshBuild=...s materialsLoad=...s` -- once per invocation,
  right after the mesh/materials `include`s. `meshBuild` is the
  `cube()` call plus the slit region-labeling pass in
  `hts_mesh_module_3d_slit.idp`; this is the cost `-steps-per-invocation`
  amortizes.
- `[profile] step=N elecSplit=...s pdeSolve=...s` -- once per physical
  step. **`N` resets to 0 at the start of every invocation** (it's the
  `.edp`'s local loop counter, not a global timestep index) -- with
  `-steps-per-invocation 20`, expect `step=0` through `step=19` to
  repeat in every invocation's `run.log` block, not keep climbing.
  `elecSplit` is the per-x current-split bisection (nested bisections
  over ~60 x-samples, non-trivial -- worth measuring separately from the
  FEM solve rather than assuming the PDE solve dominates). `pdeSolve` is
  just the `solve heatStep(...)` call.
- `[profile] totalInvocation=...s` -- once per invocation, wall time
  for the whole process including FreeFEM startup overhead not captured
  by the other three (so `meshBuild + N*(elecSplit+pdeSolve)` will be
  somewhat less than this).

Uses FreeFEM's built-in `clock()` (CPU time, not wall clock -- fine for
comparing relative costs within one invocation, but note it won't
reflect I/O wait or multi-core effects if the underlying solver is
threaded).

**Measured on the real remote install (ratio=0.7, step 0):**
`meshBuild=13.99s`, `materialsLoad=0.0015s`, `elecSplit=0.0027s`,
`pdeSolve=116.5s`. The PDE solve is completely dominant -- ~89% of even
this first step's total (which includes the one-time mesh cost), and
effectively 100% of every later step within a multi-step invocation.
This inverted the original hypothesis: mesh-rebuild amortization
(`-steps-per-invocation`) is real but secondary; **the 87,870-DOF linear
solve inside `solve heatStep(...)` is the actual bottleneck.**

**`solver=CG` experiment -- round 1 result (measured, on the real remote
install, ratio=0.7, step 0): a regression.** The bilinear form
(`rhocpfun*T*w/dt + kfun*grad(T)*grad(w)`) is symmetric positive-definite,
and the statement previously specified no `solver=` at all (generic
default). `solve heatStep(T, w, solver=CG)` gave the *correct* answer
(`Tmax=77 TmaxL=77 TmaxR=77 fracLeft=0.5` at t=0, matching the
pre-change baseline exactly) but was **slower**: `pdeSolve=126.238s` vs.
the `116.5s` baseline, an ~8% regression. FreeFEM's own `GC:` log line
showed why: 10,293 unpreconditioned CG iterations to reach a residual of
`1.47727e-32` -- roughly 26 orders of magnitude past what a FEM solve
actually needs (discretization error alone dwarfs that). That's a
tolerance problem, not necessarily proof CG is a bad fit for this system.

**Round 2 (measured, same machine): `eps=1e-6` had zero effect.**
`solve heatStep(T, w, solver=CG, eps=1e-6)` produced an *identical*
result to round 1 -- same 10,293 iterations, same `1.47727e-32`
residual, same ~125s timing, to the decimal. This falsifies the "just
needs a looser tolerance" theory; either `eps=` isn't controlling
convergence the way assumed for this FreeFEM version/solver
combination, or something else pins this at nearly machine precision
regardless. **Reverted to no `solver=`/`eps=` clause at all** (the
original statement) rather than continue tuning blind without deeper
FreeFEM solver-internals expertise -- two rounds of real remote-machine
time spent for no measured gain is the signal to stop, not keep
guessing.

**Conclusion: the PDE solve (~116.5s/step, unmodified default solver)
is a real, currently-unavoided cost.** If revisited later, the next
things to try would be an explicit preconditioner (the 7 material
regions have coefficients orders of magnitude apart -- e.g. buffer's
placeholder `sigmaBuf=1e-10 S/m` -- which plausibly explains why
unpreconditioned CG needed 10k+ iterations) or a different *direct*
solver (`solver=UMFPACK`/`solver=MUMPS` if available) rather than
another iterative-solver guess. Until then, the validated levers for
wall-clock are `-steps-per-invocation` (saves the ~14s mesh-rebuild cost
per invocation avoided), the ramp-dt coarsening below, and parallelizing
across current ratios (Condor -- see `condor/README.md`) -- all already
understood, unlike solver tuning.

## Ramp rate / ramp-dt (`-ramprate`/`-rampdt`, `--ramp-rate`/`--ramp-dt`) -- validated

Added for a collaborator-requested slow ~20 A/s current ramp (replacing
the original fixed 0.5s ramp duration, which implied 311-616 A/s
depending on ratio). `-ramprate` (A/s, default 0.0 = today's fixed 0.5s
Tramp) derives `Tramp = I0Target/ramprate` instead when set >0.
`-rampdt` (default 0.05, today's exact value) sets the timestep used
only during the ramp phase, independently of `-ramprate`.

**Why `-rampdt` matters once `-ramprate` is used**: at a fixed
0.05s ramp-phase dt, a 20 A/s ramp needs 2.5x-4.3x more ramp-phase steps
than today's ramp (more for higher ratios, since a higher I0Target needs
longer to reach at a fixed rate, computed against the real
`IcRebcoActual~=310.96A` backed out of this repo's sweep data). Every
one of those extra steps costs a full ~116.5s PDE solve.

**Validated on the real remote install (ratio=0.7, ramprate=20 ->
Tramp=10.8836s):** compared `rampDt=1.0s` (~11 steps) against
`rampDt=999` (single step covering the entire ramp). Result: **identical**
at the ramp-end row (t=10.8836): `Tmax=77 TmaxLeft=77 TmaxRight=77
fracLeft=0.5` in both. Rows just after (already into the pulse phase)
differ only at the 4th-5th significant digit (e.g. `fracLeft=0.0383638`
vs `0.038363`) -- floating-point/solver-ordering noise, not a
time-discretization error, since both runs enter the pulse phase from
the exact same uniform-77.0K state. **The entire ramp phase can be
collapsed to a single step regardless of duration -- for currentRatio<=1.**
This fully neutralizes the wall-clock cost of slowing the ramp -- total
steps per ratio returns to roughly the original ~90-100 (1 collapsed ramp
step + the ~90 pulse/post-pulse/late-phase steps, which are unaffected by
ramp rate) instead of scaling with ramp duration. **This validation did
NOT cover currentRatio>1 and turned out not to generalize there -- see
"Ramp collapse breaks down above Ic" below, added after two real crashes.**

**For production runs, `-ramprate`/`--ramp-rate` and `-rampdt`/
`--ramp-dt` do NOT auto-couple** -- they're independent flags. Using
`--ramp-rate 20` without also raising `--ramp-dt` well above the
resulting `Tramp` (e.g. `--ramp-dt 999`, safe per the validation above)
silently pays the full 2.5x-4.3x step-count penalty this section exists
to avoid. Always set both together for the slow-ramp scenario.

- **No output for minutes at a time is normal, not a hang.** Each
  invocation rebuilds the mesh from scratch and solves one timestep —
  minutes, not seconds, per root `CLAUDE.md`. `run_transient.py` streams
  FreeFEM's own stdout/stderr live (to both the console and `run.log`)
  rather than buffering it until the process exits, specifically so a
  slow invocation stays distinguishable from a genuinely stuck one. If
  you see this print nothing at all for several minutes even with the
  streaming fix in place, that's a real problem worth investigating, not
  expected behavior. `--max-steps N` bounds how many timesteps run, not
  how long each one takes — a "5-step smoke test" is still on the order
  of many minutes, not instant.

### Ramp collapse breaks down above Ic

**Real crash, root-caused by reading the raw run.log (not guessed):** a
202-ratio batch reaching up to 1.9xIc produced two `status=crashed` runs
-- `r1p36` (1.36xIc) and `r1p83` (1.83xIc). Both blew up to `Tmax` on the
order of `1e65`-`1e228` (floating-point garbage, not real physics) within
a *single* step, and in both cases that step's `t` jumped from 0 straight
to that ratio's `Tramp` -- i.e. the collapsed ramp step from the
validation above, at the ratio where it stops applying.

**Why (mechanism -- and a real correction, see caveat below)**:
`I0(t) = I0Target*(t/Tramp)` ramps linearly, so for `currentRatio>1`,
`I0(t)` crosses `Ic` at `t = Tramp/currentRatio` -- *during* the ramp,
before the heater pulse ever fires. The original validation only ever
ran at `ratio=0.7`, where `I0(t)` never reaches `Ic` during the ramp at
all, so collapsing that phase into one step is safe: the tape stays
superconducting the whole time, regardless of step size. Above `Ic`,
one huge step (`rampDt=999`-style) asks a single linear solve -- with
coefficients evaluated at the step's *starting* 77K, superconducting
temperature -- to capture a resistive transition that actually happens
partway through. The matrix conditioning collapses (`r1p36`: UMFPACK
out-of-memory; `r1p83`: the resulting garbage temperatures cascade for a
few more steps until a material-property table lookup goes out of
bounds).

**Caveat -- this does NOT scale smoothly with ratio, checked
exhaustively.** The user asked whether this invalidates any other
already-collected data. Checked the ramp-end `Tmax` (the exact row where
both crashes occurred) for all 90 ratio>1 runs in the batch, not just a
sample: **only `r1p36`/`r1p83` show a corrupted value; all 88 others --
including ratios both below and above them (1.35, 1.4, 1.5, 1.7, 1.82,
1.84, 1.9, ...) -- land at exactly `Tmax=77.0`, bit-identical to the
pre-ramp initial condition.** So this is NOT "further above Ic is
progressively less stable" -- if it were, ratios further from 1.0 than
1.36/1.83 should have failed too, and they didn't. It looks more like a
narrow numerical edge case rather than a physically scaling instability.
Practical upshot: the other 88 ratio>1 runs' results stand as collected;
only `r1p36`/`r1p83` need rerunning.

**Root cause, confirmed (supersedes the earlier `elecSplit`-bisection
guess below this line in git history -- that theory turned out wrong,
see the fix section above for `-tmaxcutoff`/`rampDtAboveIc` and the
section below for the actual mechanism).** It is NOT the electrical
model at all. Reproduced directly: a 202-ratio Condor batch (`--ramp-rate
20`, stretching `Tramp` to ~16-23s instead of the original fixed 0.5s)
produced `r1p474` "finishing" in 141.5s while numeric neighbors `r1p470`/
`r1p481` ran 20+ hours and got held on Condor's wall-time limit. Reading
`r1p474`'s raw log: its giant collapsed first step (`I0w=0`, zero current,
zero heat source, pure diffusion from a uniform 77K field, `elecSplit=
0.0025s` -- confirming no electrical bisection was even touched) produced
`min -5.6e119 max 3.7e113` straight out of `solve heatStep`. `r1p470`/
`r1p481` ran the *identical kind* of solve, at their own slightly
different collapsed-`dt` value, and got the correct `77 -> 77`. Same
"isolated input, smooth neighbors fine" signature as `r1p36`/`r1p83`,
now caught with nothing but a linear diffusion solve and zero current
involved -- ruling out `elecSplit` entirely.

**Confirmed from FreeFEM's own source** (cloned `FreeFem-sources` tag
`v4.12`, matching the installed version, via `docker run freefem/freefem`
+ `apt`/`git`, per the user's suggestion to go straight to source rather
than keep guessing): `heatStep`'s `solve` statement never passes a `sym=`
flag, and `Data_Sparse_Solver`'s default constructor sets `sym(0)`
(`src/femlib/VirtualSolver.hpp:93`) -- so even though the bilinear form
is genuinely SPD (already established by the `solver=CG` experiment
above), FreeFEM solves it as a **general, non-symmetric** system.
`src/femlib/SparseLinearSolver.hpp:115-122` registers the built-in
solvers by priority:
```cpp
addsolver<SolverGMRES<Z,K>>("GMRES",10, 3);
#ifdef HAVE_LIBUMFPACK
  addsolver<VirtualSolverUMFPACK<Z,K>>("UMFPACK",100, 1); // default "SparseSolver" (general)
  addsolver<VirtualSolverCHOLMOD<Z,K>>("CHOLMOD",99,  2); // default "SparseSolverSym" (symmetric)
#endif
```
UMFPACK (priority 100) wins the general slot every unspecified-`solver=`
call makes; CHOLMOD is registered right alongside it for the symmetric
slot but is never reached, since `sym` defaults false. **This matches
already-observed evidence exactly**: `r1p36`'s original crash literally
printed `"UMFPACK out-of-memory"` -- the solver naming itself in the
log, not an inference. UMFPACK is a **direct sparse LU factorization**,
not iterative -- exactly the class of solver that can either fail loudly
(pathological pivoting/fill-in -> OOM, `r1p36`) or fail silently (a
technically-completed but numerically garbage factorization, `r1p474`)
on an isolated ill-conditioned matrix while succeeding fine on a
near-identical neighbor. This project's own material tables are exactly
the kind of input that produces that ill-conditioning at large collapsed
`dt` (coefficients spanning many orders of magnitude -- e.g. buffer's
placeholder `sigmaBuf=1e-10 S/m`, ~4 orders below even Hastelloy's real
value).

**`sym=1` experiment (CHOLMOD instead of UMFPACK) -- tried, put on the
back burner, not because it's wrong but because it couldn't be
evaluated.** `step_3d_slit_transient_diag_symtest.edp` +
`condor/symtest.sub` A/B-tested `sym=1` against today's default for
`r1p474`/`r1p36`/`r1p83` on the actual Condor pool. Result: **all three
baseline (`sym=0`) passes came back sane this time**, including the two
that originally crashed. Checking the job logs' execute-host identity
explained why: this pool is OSPool/OSG, a nationwide opportunistic grid
-- the original `r1p36`/`r1p83` crashes ran on a Colgate University
node; this retest landed on Clemson's Palmetto cluster, Montana State's
EPYC nodes, and "hellbender," all different machines. **The failure is
node/hardware-dependent, not a deterministic function of ratio or
code** -- UMFPACK's LU pivoting on a borderline-conditioned matrix is
sensitive to floating-point rounding differences between CPU
microarchitectures. That makes a single side-by-side job an inconclusive
test: both variants in one job always run on the same node, so a "good"
node draw makes both look fine regardless of whether `sym=1` actually
helps. Validating `sym=1` for real would need many repeated draws per
ratio to compare failure *rates*, not a single pass/fail -- shelved for
now in favor of the fix below, which doesn't have this problem.

### Adaptive step-size bisection (implemented)

Rather than pick a fixed `dt` cap for the collapsed ramp step (no cap
could be shown safe -- `r1p83` blew up at just `0.273s`, smaller than
the `1.0s` already-validated-elsewhere figure cited earlier in this
file, and the node-heterogeneity finding above means "safe" may not
even be a fixed number at all), `step_3d_slit_transient_diag.edp` now
retries a step at half `dt` whenever the result is physically
implausible, standard adaptive-FEA practice. Mechanism:

- **Detection is a physical bound, not a magic threshold.** All three
  known blowups had `I0w=0` (zero source) at the moment they happened --
  by the diffusion equation's own maximum principle, `T` can't
  legitimately move far from `Told`/`Tcold` in one step with no source
  term. `maxStepRise` (`-maxsteprise`, default `500.0` K) checks
  `T[].max-Told[].max` and `Told[].min-T[].min` against this bound --
  generous enough that a real quench (~650K/s, the fastest observed
  this project, is only ~13K at pulse-phase `dt`) never trips it, but
  catches `1e100+`-scale garbage with enormous margin. NaN is checked
  separately (`T[].max != T[].max`) since a NaN comparison via `>` is
  always false in IEEE-754 and would otherwise never trip the bound,
  same subtlety `run_transient.py`'s own isnan/isinf guard already
  handles.
- **Retry, don't downgrade permanently.** Only the `solve heatStep` call
  is retried at half `dtTry` -- `Told`/`source`/`qHeaterNow` don't
  depend on `dt` so they're computed once. `t` advances by whatever
  `dt` actually got committed (possibly less than requested), and the
  *next* step always tries the full requested `dt` fresh rather than
  permanently coarsening the ramp rate for the rest of the run -- the
  instability looks localized to specific `dt`/hardware combinations,
  not a persistent property of the trajectory.
- **`-maxbisections` (default 10)** caps the halving depth; exceeding it
  is a hard `assert(false)` failure rather than silently grinding at a
  useless `dt` forever -- if halving 10 times doesn't stabilize it,
  that's a different problem than "dt too large."
- **Cost model is the whole point:** a node that succeeds on the first
  (large, fast) attempt pays nothing extra. Only a node that actually
  hits the bad pivot pays for a retry -- strictly better than a fixed
  cap, which taxes every run's step count regardless of whether that
  particular node needed it.
- Threaded through `run_transient.py`/`sweep_transient.py` as
  `--max-step-rise`/`--max-bisections`, mirroring every other `.edp`
  flag's Python CLI convention.

**Bundled fix, same edit:** the CSV/diagnostic print (`fout`/`fdiag`)
used to happen *before* `solve heatStep` ran for that step -- so a CSV
row's `Tmax` was always one physical step stale relative to what the
checkpoint ended up holding, and combined with `-tmaxcutoff` writing
zero new rows once it fires, `run_transient.py` never saw `r1p474`'s
actual diverged `Tmax` at all -- it only saw `t` stall, and returned the
falsely benign `reached_end_no_deviation` instead of catching the
divergence. Fixed by moving the diagnostic/CSV write to after the
(possibly-bisected) solve and after advancing `t`, so both always refer
to the same committed state. Voltage-tap diagnostics (`fdiag`) still
reflect the electrical solve computed from the step's *starting*
temperature (the model's existing staggered-scheme convention,
unchanged) -- only `transient_3d_slit.csv`'s `Tmax`/`fracLeft`, the
columns `run_transient.py` actually classifies on, needed the ordering
fix.

**Verified:** syntax-checked against the real FreeFEM v4.12 parser
(via the local `freefem/freefem` container) -- full script parses
clean, no compile errors, matches the exact echo-back FreeFEM already
produced for the pre-bisection version. Not yet verified against an
actual bisection-triggering blowup on real Condor hardware -- that
needs the same real-node-lottery exposure the `sym=1` test needed and
couldn't get locally.

### Above-Ic phase: adaptive Jc-based step growth (implemented)

The bisection mechanism above only guards against catastrophic UMFPACK
blowups (the `maxStepRise=500K` bound) -- it doesn't address the
*separate* wall-time problem from `rampDtAboveIc` being a fixed
absolute dt (`r1p031`'s 20-hour trail: `--ramp-rate 20` stretches the
above-Ic window to several seconds, and a fixed `0.002s` step multiplies
that into hundreds-to-thousands of steps). No fixed replacement cap was
adopted -- picking one blindly is exactly the mistake that caused the
original ramp-collapse crashes, and this project needs the slow ramp
rate for comparability across datasets (collaborator requirement, not
negotiable), while also not wanting to commit to a specific resolution
without justification.

Instead, `rampDtAboveIc` is now a **starting guess that the step loop
mutates directly** (grown or shrunk after every above-Ic step) rather
than a fixed value -- `dtRaw`/`dtCapped` are unchanged, they just read
whatever it currently holds. The accuracy criterion is built around
`JcT(T)` rather than a Kelvin figure: `JcT(T)=Jc0*(Tc-T)/(Tc-50)` is
linear in `T`, so its *fractional* change over a step is `~dT/(Tc-T)` --
at `T~77K`, `Tc=90K`, even a 5K step is a ~38% swing in critical current
density. The nonlinearity here isn't about how fast `I0(t)` itself is
ramping (slow, by design, once `--ramp-rate` is used) -- it's about how
close `T` sits to `Tc`, which the frozen-coefficient solve doesn't see.
`-maxjcfracchange` (default `0.05`) bounds the allowed swing directly:
inside the existing bisection loop, a step that isn't a catastrophe but
moves `JcT(Tmax)` by more than this fraction is retried at half `dt`
(shares the loop/halving mechanics with `maxStepRise`, just a second,
tighter trigger). A step that lands comfortably inside the band (under
half the bound) doubles `rampDtAboveIc` for the next step; otherwise the
next step just carries forward whatever `dt` actually worked. This
naturally keeps steps fine exactly at the Ic-crossing transition (where
`Jc` is genuinely changing fast) and lets them grow everywhere else in
the above-Ic window, without ever having to state a "safe" absolute
number in advance.

**Validated on the real Condor pool: `r1p05` (ratio=1.05) is the clean
success case.** Above-Ic window (`tCrossIc=15.548s` to `Tramp=16.325s`,
`0.777s` span) covered in **9 steps** via clean doubling
(`0.002->0.004->...->0.256`, then a capped partial step landing exactly
on `Tramp`) with zero bisections needed -- `Tmax` barely moved (`77 ->
77.02`) the whole way, comfortably inside the accuracy band throughout.
The old fixed-`0.002s` scheme would have needed ~389 steps for the same
window -- a ~43x reduction, and `--runaway-tmax 250` correctly cut the
tail (`Tmax cutoff 250K reached (Tmax=261.294K)`, classified `runaway`).
Total: 2 Condor invocations, ~1.9 hours wall-clock.

**Real bug found on the same batch: `r1p36` (ratio=1.36) span for 13.3
hours and never reached the pulse at all.** Its own above-Ic window
runs from the SAME `tCrossIc=15.548s` up to `Tramp=21.145s` -- long
enough, and `ratio=1.36` hot enough, that pure overcurrent self-heating
during the ramp (no heater pulse involved at all yet) drove `Tmax`
toward `Tc=90K` before ever reaching `Tramp`. `JcT(T)` is linear and
hits exactly 0 at `Tc` -- and `maxJcFracChange`'s normalization used the
*local* `jcBefore` as the denominator, which -> 0 as `Tmax` -> `Tc`. Any
nonzero step then produces an unboundedly large fractional swing no
matter how small `dt` gets, since the criterion was `|delta Jc| /
(a value approaching zero)`, not `(a value approaching zero) is itself
hard to move accurately`. Confirmed directly in `run.log`: `dt` halved
repeatedly down to `dtTry=3.90625e-06` (`Tmax=89.9365`, still short of
`90`) and kept going -- `t` effectively froze at `t=20.987` (short of
`Tramp=21.145`) while burning the entire 13.3-hour run just inching
through fractions of a Kelvin near `Tc`. `fracLeft` genuinely never
deviated (symmetric heating at this overcurrent, expected), so
`run_transient.py`'s stall detector correctly fired on what it saw --
`t` stalled between invocations -- and correctly labeled it
`reached_end_no_deviation`. The label logic wasn't wrong; the `t`
trajectory it was fed was garbage from the criterion, not the physics.
A full quench through `Tc` is completely legitimate and must be
traversable in finite steps.

**Fix (implemented):** normalize `jcFrac`'s denominator against a FIXED
reference, `jcRef = JcT(Tcold)` (`Tcold=77K`, always substantial, never
vanishes), instead of the local, transiently-near-zero `jcBefore`.
`jcFrac = abs(JcT(T[].max)-jcBefore)/max(jcRef, 1e-30)` -- same
numerator (still the genuine per-step `Jc` delta), different, well-posed
denominator. Syntax-checked against the real FreeFEM parser; not yet
re-run against `r1p36`'s actual scenario to confirm it now crosses `Tc`
in finite time -- that's the next real test once resubmitted.
`r1p83`/`r1p9` in the same batch were likely stuck in this exact same
spiral when this was found -- check whether they need killing and
rerunning rather than left to keep spinning on the old code.

### Runaway threshold for ratio>=1.0 batches: use --runaway-tmax 250

No code change -- `runaway_tmax` is already a general, existing flag.
Checked directly against the full 202-ratio dataset: **every ratio>=1.0
run that didn't crash ended up `runaway` (89/91); zero ever recovered.**
Separately, across those 89 runaway trajectories, `Tmax` **never
reverses after crossing 200K** (checked at 100/150/200/250/300K -- the
100-150K thresholds still show up to a 62K dip, the universal
pulse-transient bump found earlier this session; 200K+ shows exactly
0.00K of reversal in all 89 cases). The dataset's own recovery/runaway
boundary sits at ratio 0.912/0.913 (adjacent granular steps, zero
overlap) -- comfortably below this batch's floor of 1.0. So for a
ratio>=1.0-only batch specifically, `--runaway-tmax 250` (some margin
above the empirically-clean 200K floor) is a data-grounded way to stop
each run right after it's unambiguously committed, instead of
continuing to the default 900K -- saves the median ~0.42s (up to ~1.0s)
of tail every one of these runs was computing for no classification
benefit. **Do not reuse 250 for a mixed-ratio batch that includes
anything near the 0.912-0.913 boundary** -- recovering/runaway
trajectories are indistinguishable well past 250K near that boundary
(see the voltage/Tmax turning-point work elsewhere in this file); this
number is only justified because every ratio in this batch sits well
above it.

### Condor auto-retry on RETRY_WORTHY failures (implemented, closes out the retry piece of "detect and retry" from the node-heterogeneity discussion)

`run_transient.py` previously always exited 0 regardless of the run's
actual status -- `main()` called `run_one()` and discarded the returned
summary entirely. That meant no Condor exit-code policy could ever have
distinguished a crashed run from a settled one; every job looked
"successful" to Condor no matter what happened inside. Fixed: `main()`
now exits 1 for exactly the statuses `analyze_sweep_hdf5.py` already
treats as "no trustworthy physics" (`RETRY_WORTHY_STATUSES = {"crashed",
"init_failed", "numerical_divergence", "no_data"}`, kept manually in
sync with that file's `NO_TRUSTWORTHY_PHYSICS`).

`condor/sweep.sub` now holds a job on that nonzero exit and
auto-releases it after a cooldown (`on_exit_hold`/`periodic_release`,
capped at 3 automatic retries via `NumJobStarts<4`) -- see
`condor/README.md` for the full policy. Justified directly by this
session's own evidence: `r1p36`/`r1p83`'s original crashes did NOT
reproduce when the exact same scenario reran on different execute hosts
across this pool (Colgate -> Clemson/Montana State/hellbender) -- a
RETRY_WORTHY failure is plausibly just an unlucky node draw, not a real
bug, so requeuing is a reasonable default rather than requiring a human
to notice a `crashed` status and resubmit by hand. A run that still
fails after 4 attempts across different node draws is more likely a
real bug than bad luck, and stays held for review rather than retrying
forever.

Not yet measured against a real job on this pool -- same caveat as
every other first-pass Condor resource number in this file.

**At the time of this crash, no Tmax safety check existed anywhere that
could have caught it.** `step_3d_slit_transient_diag.edp`'s own step loop
had no Tmax-based exit at all (only `t>=tEnd`, `step>=maxStepsThisRun`,
`dt<=1e-9`). `run_transient.py`'s `runaway_tmax` check (900K default)
only ran *after* a full invocation returned -- and the explosion already
happened *inside* that one collapsed step, before Python ever got a
chance to look. Lowering that Python-side threshold would not have
prevented either crash. (This gap is now closed -- see `-tmaxcutoff`
below -- but it would not have helped here either, since the blowup
happened within a single step, not across several.)

**Fix (implemented): `rampDtAboveIc` / `-rampdt-aboveic` /
`--ramp-dt-above-ic`** (default `0.002`, matching the pulse phase's
already-validated resolution). `tCrossIc = Tramp/currentRatio` (equals
`Tramp` exactly, i.e. no-op, for `currentRatio<=1`) is now a phase
boundary alongside `Tramp`/`tPulseStart`/`tPulseEnd`/`tEnd` --
`dtCapped()` can no longer step across it, so the above-Ic portion of
the ramp always takes fine steps regardless of how coarse `--ramp-dt`
is set. Below `Ic`, behavior is byte-for-byte unchanged from the
validated ratio<=1 case. **Not yet re-validated against real hardware
output** (no FreeFEM access in this environment) -- before trusting a
big batch at ratio>1 again, smoke-test one ratio known to have crashed
before (e.g. `--ratio 1.36 --ramp-rate 20 --ramp-dt 999 --max-steps 3`)
and confirm it no longer blows up and that ratio<=1 output is unchanged
from a pre-fix run.

### In-invocation Tmax cutoff (`-tmaxcutoff` / `runaway_tmax`)

Separate from the ramp-collapse crash above: once a run is genuinely in
thermal runaway, letting `step_3d_slit_transient_diag.edp` grind through
the rest of its `-steps-per-invocation` batch (default 20) burns real
wall-clock for no reason -- the outcome is already decided the instant
Tmax first exceeds `run_transient.py`'s `runaway_tmax` (900K default),
since that check already forces the run over with no further data
collected. The gap was that the check only ran *between* invocations,
not inside the `.edp`'s own step loop -- an invocation already past
threshold on physical step 3 of 20 still ran steps 4-20 before Python's
next look. Fixed by adding `real tmaxCutoff = getARGV("-tmaxcutoff",
900.0)` and `&& T[].max < tmaxCutoff` to the step loop's own condition;
`run_transient.py` passes `-tmaxcutoff str(runaway_tmax)` so the two
thresholds can't drift apart. Deliberately blind (no trend/turning-point
logic) -- by 900K the outcome needs no further justification to cut,
and no downstream analysis (the voltage/Tmax turning-point work in
`analyze_voltage_diagnostics.py`, which happens far earlier, around
~85K) depends on rows collected past this point anyway.

## Sweep analysis (`analyze_sweep_hdf5.py`)

Reads `runs/sweep.h5` (the `export_sweep_hdf5.py` output) directly --
deliberately doesn't touch `runs/<label>/*.csv` at all, since only the
HDF5 handoff file is guaranteed to exist on a given machine (e.g. after
scp'ing just the final file off the remote box). It imports
`../shared/plot_slit_transient.py` and
`../shared/plot_diagnostics_3d_slit.py` and calls their plotting
functions directly against dicts built from HDF5 datasets -- same
column dicts those scripts build internally from `csv.DictReader`, just
a different loader -- rather than writing the arrays back out to temp
CSVs or duplicating the plotting logic. If either shared script's
plotting function signatures change, update the call sites here too.
The cross-ratio summary plots (fracLeft/Tmax overlaid across ratios,
final settled/runaway boundary) are new logic specific to this script
-- there is no equivalent for single-run CSVs since there's nothing to
compare across.

**`status` alone is not a fit for legend labels.** `reached_end_deviated`
only means "ran to tEnd still off 50/50" -- it conflates three different
physical outcomes (still asymptotically recovering, stuck at a new
off-center equilibrium, or trending toward runaway but hadn't crossed
the threshold yet) that only the trend classifier
(`run_transient.classify_trend`, see above) actually distinguishes.
`outcome_label()` resolves this before anything reaches a plot: it maps
`reached_end_deviated`/`plateaued_off_parity` through the stored `trend`
field to `"recovering (asymptotic)"` / `"plateaued off-parity"` /
`"diverging (pre-runaway)"`. **The trend classifier was added to
`run_transient.py` after several of this sweep's runs (0.5/0.7/0.8/
0.9xIc) had already finished**, so their `status.json` predates the
`trend` field entirely -- `recompute_trend()` reruns the exact same
classifier against the trailing `trend-window` of the full time series
already sitting in the HDF5 file, so old and new runs get consistently
labeled without re-running anything. Confirmed by direct computation:
all four of those runs classify as `converging`. If you add a new
outcome to `run_transient.py`'s state machine, add it to
`OUTCOME_LABELS`/`OUTCOME_COLORS` here too or it'll fall back to
whatever raw string `status` holds.
