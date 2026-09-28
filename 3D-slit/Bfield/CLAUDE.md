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
- A checkpoint currently on disk here reflects the numerics/I0-fix
  verification runs (see below), not a real physics run — re-run the
  init script for a clean `t=0` start before starting real work.

## Physics simplification inventory — B-field specific

- **B-field**: self-field only (no external circuit/return path —
  open-conductor approximation, weakest near current leads x=0/Lx,
  strongest near tape midpoint), lagged one full timestep (not
  self-consistent within a timestep), isotropic Kim model
  (`Jc(B,T)=Jc(T)/(1+|B|/B0)`, real REBCO Jc(B) is anisotropic).
  `B0=0.04265T` (updated 2026-09-25, from Loic Queval et al 2016
  Supercond. Sci. Technol. 29 024007 — see `bfield_3d_slit.idp`'s
  header) — more than 2x more aggressive suppression than the prior `0.1T`
  placeholder (suppression scales with `1/B0`), so **not yet verified
  with a real run** — see "Isotropic verification before anisotropic
  Kim model" below before trusting downstream results against it.
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
FreeFem++ -nw step_3d_slit_transient_bfield.edp       # repeat to advance; 1 timestep/invocation by default
```

Both scripts now take `-ratio`/`-outprefix`, and the step script also
takes `-steps-per-invocation`/`-ramprate`/`-rampdt`/`-rampdt-aboveic`/
`-maxjcfracchange`/`-maxsteprise`/`-maxbisections`/`-tmaxcutoff` — see
"Ratio/wrapper parameterization" below. All default to this script's
original hardcoded behavior when unflagged. In practice, drive this
through `run_bfield_transient.py` (see "Continuous-solve wrapper" below)
rather than invoking these by hand for a real run.

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
- **Above-Ic Jc-fraction step-growth controller now ported too**
  (`-rampdt-aboveic`/`-maxjcfracchange`, including the `jcRef`-
  normalization fix already applied in electrothermal — see "Ratio/
  wrapper parameterization" below). Previously deliberately left out
  since `I0Target` was hardcoded below Ic; now that `currentRatio` is a
  parameter, it's live.

## Ratio/wrapper parameterization (ported from `electrothermal/`)

`I0Target` is no longer hardcoded to `0.7*IcRebcoActual` — the full set
of flags `electrothermal/step_3d_slit_transient_diag.edp` grew for
`run_transient.py` are now here too, ported verbatim except where noted:

- **`-ratio`** (default `0.7`): `I0Target = ratio * IcRebcoActual`.
- **`-outprefix`** (default `""`): prefixed onto every checkpoint/CSV/
  diagnostics filename, in both `init_3d_slit_transient_checkpoint.edp`
  and the step script — including the `exec("test -s "+outPrefix+...)`
  call, which is a separate literal from the `ofstream fdiag(...)`
  constructor two lines above it and easy to miss when re-templating by
  hand (same gotcha electrothermal's `CLAUDE.md` already flags).
- **`-steps-per-invocation`** (default `1`, replacing the old hardcoded
  `maxStepsThisRun = 1`): physical timesteps per FreeFEM invocation.
  **Checkpoint write moved from once-at-invocation-end to once-per-
  physical-step** as part of this — the old file-bottom write would
  otherwise leave the checkpoint behind the CSV once this exceeds 1,
  causing duplicate/overlapping `t` rows on a future `--resume`. Mirrors
  electrothermal's identical fix; the checkpoint here also carries
  Earr/ElArr/ErArr (this workflow's extra B-field state), not just `t, T`.
- **`-ramprate`/`-rampdt`/`-rampdt-aboveic`/`-maxjcfracchange`**: same
  meaning and defaults as electrothermal (see that track's `CLAUDE.md`
  for the full derivation) — `tCrossIc`/`phaseBounds` (now 5 elements)/
  `dtRaw`/`dtCapped` all ported to match. At the default `ratio=0.7`,
  `tCrossIc==Tramp` exactly and every one of these is a no-op, so
  behavior at the default is byte-for-byte unchanged from before
  parameterization.
- The above-Ic Jc-fraction growth controller (`inAboveIcPhase`, `jcRef`,
  `jcFrac`) is now folded into the same adaptive-bisection `while` loop
  documented above, exactly like electrothermal — `jcRef = JcT(Tcold)`
  (the already-fixed, non-vanishing normalization), not the local
  `jcBefore` that caused electrothermal's original hang near `Tc`.
- **NOT ported**: `run_transient.py`'s Python side (that's the wrapper
  itself, tracked separately below), and the `prePulse`/
  `runaway_before_pulse` status split electrothermal added afterward —
  that was explicitly out of scope for this port; ask before adding it
  here.
- **Verified**: full script parses clean against the real FreeFEM v4.12
  parser with the new flags present. Not yet run at `ratio>1` (no real
  hardware exposure to an above-Ic Bfield run yet, unlike electrothermal's
  `r1p05`/`r1p36` validation) — treat the Jc-growth controller here as
  syntax-correct-by-construction but not yet physically validated the way
  electrothermal's copy has been.

## Anisotropic Kim model infrastructure (built, not yet activated)

Built 2026-09-25, while the isotropic `B0=0.04265` verification jobs
(below) are in flight on the remote Condor pool — deliberately
**additive only**, so nothing here can affect those already-submitted,
already-packaged runs.

Model: `Jc(B,T) = Jc(T) / (1 + sqrt(k²·Bpar² + Bperp²)/B0)^α`, with
`k=0.29515`, `α=0.7`, same source as `B0kim`: Loic Queval et al 2016
Supercond. Sci. Technol. 29 024007.

**Bperp/Bpar coordinate mapping — confirmed explicitly with the user,
not assumed** (getting this backwards would be a silent, plausible-
looking bug, exactly the class this repo's history has been burned by
before — see root `CLAUDE.md`'s region-labeling warning). The formula's
`Bx`/`By` are generic tape-local axes (parallel/perpendicular to the
tape's broad face), not this mesh's literal x/y/z. Current always flows
in the mesh's `x` (tape length), so Biot-Savart from it has NO
x-component by construction — the only two components that ever exist
here are the mesh's `y` (layer-stack/thickness direction = c-axis =
perpendicular to the broad face) and `z` (tape-width direction = ab-plane
= parallel to the broad face). Standard REBCO anisotropy gives the
perpendicular/c-axis component full weight and down-weights the
parallel/ab-plane component by `k<1` — so **`Bperp` = mesh `y`-component
(full weight), `Bpar` = mesh `z`-component (`k`-weighted)**.

What's built, all in `bfield_3d_slit.idp`:
- `computeSelfFieldB` now outputs the component-wise fields
  (`ByLeft`/`ByRight`/`BzLeft`/`BzRight`) alongside the existing `|B|`
  magnitude (`Bleft`/`Bright`), from the same single Biot-Savart pass —
  not a duplicated second pass. The isotropic output is byte-for-byte
  unchanged; every existing isotropic call site keeps working unmodified.
- `JcTBAniso`/`sigmaScBAniso`: the anisotropic Jc/conductivity functions,
  parallel to the existing `JcTB`/`sigmaScB`.
- `ItotFullBAniso`/`solveEFullBAniso`/`ItotHalfBAniso`/`solveEHalfBAniso`:
  the anisotropic current-sharing bisection functions, parallel to the
  existing `ItotFullB`/`solveEFullB`/`ItotHalfB`/`solveEHalfB`, taking
  separate `Bperp`/`Bpar` arguments instead of one `Bmag`.

**Activated 2026-09-28** via a runtime toggle (the second option above,
not a straight swap): `step_3d_slit_transient_bfield.edp` now takes
**`-aniso`** (`getARGV("-aniso", 0)`, default `0` = isotropic, unchanged
behavior when unflagged). All 5 call sites that used to call
`solveEFullB`/`solveEHalfB` unconditionally (the outside-slit per-x loop,
`VLeftTotal`/`VRightTotal`'s two calls each, and the final
`ElArr`/`ErArr` assignment) now branch on `useAniso` via FreeFEM's
ternary operator, calling the `*BAniso` variant with `ByLeft[i]`/
`BzLeft[i]` (or `ByRight`/`BzRight`) in place of `Bleft[i]`/`Bright[i]`
when set. `run_bfield_transient.py` grew a matching `--aniso {0,1}` CLI
flag (forwarded as `-aniso`), and the Condor chain
(`condor/make_ratios_list.py --aniso`, `condor/sweep.sub`'s `aniso`
queue column) can launch an anisotropic confirmation sweep alongside an
isotropic one without label collisions — see `condor/README.md`.

Chose the toggle over a straight swap specifically so the pending
isotropic-vs-anisotropic confirmation comparison (see "Isotropic
verification before anisotropic Kim model" below) stays a clean,
single-variable change, decoupled from the separate self-consistent
(non-lagged) B solve now planned as a follow-on (decided 2026-09-28,
not yet started — see the lagged-coupling oscillation artifact found in
`r1p2`'s Hall-probe data near `Tc`, session history) — the anisotropic
confirmation runs deliberately still use the existing LAGGED coupling,
not a moving target.

**Verified**: `-aniso 0` reproduces this script's exact prior output
(confirmed byte-identical against the pre-toggle baseline), and `-aniso
1` runs a real invocation end-to-end (`Ok: Normal End`) exercising the
`*BAniso` call sites for the first time — see the Docker verification
run in this session's history for the actual numbers. **Still open**:
no real Condor run comparing isotropic vs. anisotropic *outcomes*
(Tmax/fracLeft/H1/H2 over a full transient) has landed yet — that's the
confirmation pair this toggle exists to enable, not something the
syntax/wiring check above establishes on its own.

## Isotropic verification before anisotropic Kim model

Decided 2026-09-25, when a literature-informed `B0` value became
available (see `bfield_3d_slit.idp`): verify the isotropic Kim model
with the corrected `B0=0.04265` FIRST, rather than implementing an
anisotropic Jc(B,θ) model straight away. Two reasons:

- This workflow has never actually been run through a real current-
  sharing/heating scenario — every real FreeFEM invocation so far (see
  the verification notes throughout this file) landed in the ramp's
  zero-source opening steps (`Tmax=77`, `bisections=0`). There is no
  working baseline yet to know the self-field feedback behaves sensibly
  at all, isotropic or not.
- The `B0` change itself is not cosmetic — going from `0.1` to `0.04265`
  is a >2x more aggressive suppression curve (Kim-model suppression
  scales with `1/B0`). Layering an anisotropic model (its own
  literature-sourced angular data, more implementation surface) on top
  of BOTH an unvalidated baseline AND a just-changed suppression scale
  would make a weird result hard to attribute to either change.

**Landed 2026-09-25/26**: two real Condor runs, `r0p7` (ratio=0.7,
`reached_end_deviated`) and `r1p2` (ratio=1.2, `runaway`), both reaching
real nonzero self-field past the ramp's opening steps and producing
physically sane `H1`/`H2` traces (plotted via
`../shared/plot_diagnostics_3d_slit.py`) alongside a real, characterized
lagged-coupling oscillation artifact near `Tc` in `r1p2` — isotropic
verification's goal met. **Next step (now in progress, 2026-09-28)**:
the anisotropic confirmation pair (`-aniso 1`, see "Anisotropic Kim
model infrastructure" above) at the same ratios, still under the
existing lagged coupling — a separate, non-lagged self-consistent B
solve is planned afterward as its own follow-on, not bundled into this
comparison.

## I0 write-lag fix (ported from `electrothermal/`'s "fix write lag issue")

Same bug, same fix, ported from `electrothermal/step_3d_slit_transient_diag.edp`
(found live there as `r1p26`'s CSV showing `I0=0` at its very first row,
`t=tCrossIc`, because that row's `I0w` was `I0ofT(0)` from the ramp's
true start). `I0w` (used in the solve and the electrical/voltage
sub-solve) is deliberately frozen at the step's PRE-increment `t` --
correct, matches the frozen-coefficient convention `kfun`/`rhocpfun`/
`Told` already use. But the logged `I0` column was reusing that same
stale value against the POST-increment `t` printed alongside it (more so
here than in electrothermal, since this workflow's own CSV-write-
ordering fix above already moved the write past `t += dt`). Fixed with
`I0Now = I0ofT(t)`, re-evaluated post-increment purely for logging --
`I0ofT` is a closed-form function of `t` with no solve involved, so
there's no staggered-scheme tradeoff the way there is for
`T`-dependent diagnostics. Only `fout`/`fdiag`'s `I0` column changed;
`I0w` itself (driving the physics) is untouched.

**Verified**: with the checkpoint already at `t=0.05s` from this file's
earlier verification run, ran one more real step to `t=0.10s`. Logged
row: `t=0.1,I0=43.5344,Tmax=77,...`. `43.5344` is exactly double
`I0ofT(0.05)=21.7672` (the stale value the pre-fix code would have
logged against this row, since `I0(t)` is linear during the ramp) --
confirms the fix. Back-calculating from `43.5344=0.2*IcRebcoActual*0.7`
gives `IcRebcoActual~=310.96A`, matching the exact same figure
`electrothermal/CLAUDE.md` independently cites for its own (shared
materials/geometry) ramp-rate work -- a solid cross-check that this
isn't a coincidental-looking wrong number. Also confirmed: `Ok: Normal
End`, no bisections needed (still the quiescent below-Ic ramp), `Tmax`
still `77` throughout as expected this early.

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

## Self-consistent (non-lagged) B<->E Picard solve

Built 2026-09-28, once the isotropic-vs-anisotropic confirmation pair
(above) had landed and a real, characterized artifact was found in
`r1p2`: as `Tmax` approaches `Tc` during the above-`Ic` ramp phase,
`H1`/`H2` genuinely oscillate step-to-step. Mechanism: this step's
(lagged) B suppresses this step's Jc, which shifts this step's E, which
becomes *next* step's lagged B — a one-step-delayed feedback loop that
rings once the loop gain is high enough, worsened by the corrected,
steeper `B0=0.04265` suppression curve.

**`-selfconsistent 1`** replaces the across-timestep lag with a
within-timestep self-consistent (Picard) solve: at the frozen entering
`T`/`I0w`, the self-field + electrical solve block (`computeSelfFieldB`
through the final `ElArr`/`ErArr` assignment) now runs inside a `for`
loop, iterating {compute B from current E} → {re-solve electrical for E
from that B} until E stops changing (or `-maxpicarditer` is hit).
Default `0` (lagged) runs this loop exactly once — today's exact
behavior, byte-identical when unflagged (verified: `I0=21.7672 Tmax=77`
at `t=0.05s`, matching the established baseline).

**New flags** (all `getARGV`, matching this file's existing convention):
`-selfconsistent` (default `0`), `-maxpicarditer` (default `20`),
`-picardtol` (default `1e-3`), `-picardomega` (default `0.5`).

**Deliberately NOT nested inside the `dtTry` bisection loop.** The
self-field/electrical sub-problem depends only on the frozen entering
`T` and `I0w` — neither depends on `dt` at all (`dt` first enters
downstream, in `heatStep`'s own diffusion solve). Retrying this
sub-problem at a smaller `dtTry` would hand it identical inputs and
cannot change whether it has/finds a fixed point — under-relaxation
(`-picardomega`), not `dt`, is the only real lever against
non-convergence here.

**Convergence criterion**: max relative change in `Earr`/`ElArr`/`ErArr`
between iterations (not `Bleft`/`Bright`) — E is what actually feeds
`source`/Joule heating downstream, and is the output of the power-law-
sensitive `sigmaScB` bisection right at the stiff Kim-model knee, so
it's the more conservative gate; B (a spatial Biot-Savart integral)
smooths that stiffness out and would risk declaring convergence early.
Normalized by a **global** `max(maxE_this_iteration, E0)`
(`E0=1.0e-4` V/m, `hts_materials.idp`'s 1 µV/cm criterion) — not a
per-point previous-value denominator, which would blow up at any
x-sample point sitting near zero (common during the ramp).

**Under-relaxation + adaptive backtrack**: `Earr = omega*Earr_new +
(1-omega)*Earr_old` before the next `computeSelfFieldB` call
(`omega=0.5` default — pure Picard, `omega=1`, is exactly the case
suspected to ring in the regime under investigation). If a given
iteration's residual is *larger* than the previous one (diverging —
the literal symptom under investigation), `omega` halves (floor `0.05`)
for the rest of *that step's* loop only, resetting to the flag default
at the start of every new physical step.

**Non-convergence: logs a warning and proceeds, does NOT
`assert(false)`.** A Picard non-convergence at a given `(T, I0w)` is
deterministic (same mesh, same materials) — unlike the node-dependent
UMFPACK issue `condor/sweep.sub`'s `on_exit_hold`/`periodic_release`
retry mechanism (capped at 4 starts, then held indefinitely) was built
for, retrying the identical invocation would fail identically every
time. A hard assert here would burn all 4 retries re-attempting the
same failing step, then silently stall the run under Condor hold with
no further signal. Instead, hitting `-maxpicarditer` without converging
logs a greppable `PICARD-NOT-CONVERGED` line and proceeds with the
best-available under-relaxed E/B state — a bounded, one-step
residual-error degradation, strictly better than an unattended sweep
silently stalling.

**Checkpoint format: unchanged.** `Earr`/`ElArr`/`ErArr` are still
persisted every step, just reinterpreted as "last step's converged E,
used as this step's Picard warm-start initial guess for iteration 0"
rather than "the lagged value directly consumed."

**Composability with `-aniso`**: the Picard loop just re-executes
whichever `useAniso ? solveE*BAniso(...) : solveE*B(...)` branch is
already selected each iteration — `-selfconsistent 1 -aniso 0/1` both
work with no combinatorial special-casing, and `computeSelfFieldB`
always computes both isotropic and anisotropic outputs from one
Biot-Savart pass regardless, so there's no cost asymmetry. Verify the
two rollouts one at a time before combining both in a real sweep, same
discipline already applied to landing `-aniso` itself.

**New diagnostics columns**: `diagnostics_3d_slit.csv` gained
`picardIters`,`picardRelErr`, **always** emitted regardless of
`-selfconsistent` (`picardIters=1`/`picardRelErr=-999` sentinel in
lagged mode, matching this file's own `H1`/`H2`-style `-999`
convention) — the header shape is keyed by file-existence-on-disk per
run/label, not per-invocation flags, so making these columns
conditional on the flag would risk silently corrupting the CSV if a run
were ever re-invoked with a different flag mid-run. `TIMING` cout line
also gained `picardIters=`/`picardOmegaFinal=`; `Bfield=`/`electrical=`
now sum across all Picard iterations in the step, not just one pass.

**Cost**: `computeSelfFieldB` (~13-16s/call under this sandbox's
amd64-emulated Docker) dominates — the per-x electrical solve stays
cheap (~0.02s) regardless of iteration count. So N Picard iterations
cost roughly `N × 13-16s` extra emulated per step, layered before
`heatStep` (~1000-1700s emulated/step, itself highly variable under
Docker resource contention — see below). Real/native hardware is
documented elsewhere in this repo as ~8-15x faster, but `heatStep`'s
own cost shrinks by roughly the same factor, so the *relative*
inflation from Picard iterations in the worst-case (near-`Tc`) window
could be comparable on native hardware to what the emulated numbers
suggest, not smaller — get a real wall-clock read before trusting
`-maxpicarditer 20`'s cost on a full unattended sweep.

**Verified** (Docker, this sandbox): `-selfconsistent 0` (default)
reproduces the exact established baseline (`I0=21.7672 Tmax=77` at
`t=0.05s`, `picardIters=1`, `picardRelErr=-999`) — zero regression to
the unflagged path. `-selfconsistent 1 -aniso 0` runs a real invocation
to `Ok: Normal End` from a fresh checkpoint, correctly threading the
new diagnostics columns (`picardIters=1`, `picardRelErr=0` — this
first step has `I0w<=0` so both `solveEFullB`/`solveEHalfB`
short-circuit to `E=0` identically every iteration, giving an exact
zero residual; this is the same "first-step" edge case already
documented under "Anisotropic Kim model infrastructure" above, not yet
a real test of the iteration actually doing work).

**Not yet verified — the actual point of this feature**: no real run
has yet exercised the Picard loop with genuinely nonzero, non-trivial B
(i.e. several steps into a real ramp), and no run has yet confirmed
`H1`/`H2` stop oscillating in `r1p2`'s near-`Tc` window under
`-selfconsistent 1` — that requires either re-running a ramp from
scratch with the flag set (expensive under this sandbox's emulation;
cheap on the user's native remote install) or restarting from `r1p2`'s
actual on-disk final checkpoint (`t=18.48s`, already deep in runaway,
`Tmax=423K` — a valid stress test of the Picard loop under an extreme
state, but not a reproduction of the specific ringing window, since
checkpoints aren't archived per-step and only the run's final state
survived). **Next step**: run this real comparison on the remote
install, where a full multi-step sequence is actually affordable, before
trusting this feature beyond the smoke-test level above.

## Continuous-solve wrapper (`run_bfield_transient.py`)

Ported from `electrothermal/run_transient.py` now that the step script
takes the matching flags (see "Ratio/wrapper parameterization" above).
Same stop-condition logic (settled/runaway/plateaued/max_steps, same
first-pass-placeholder thresholds, same `DEFAULT_SETTLE_TMAX_MAX=90`
double-check against a symmetric full-tape runaway masquerading as
"settled"). Two deliberate differences from the electrothermal version,
both noted in the script's own docstring:

- **No `--resume` yet.** Electrothermal's version reconstructs deviation/
  trend state from an existing `transient_3d_slit.csv`; this workflow
  could do the identical thing but it hasn't been ported/verified here.
  An interrupted run currently needs re-initializing from scratch.
- **No `prePulse`/`runaway_before_pulse` status split.** That was added
  to electrothermal as a separate, later feature (after the I0 fix) and
  was explicitly out of scope for today's port — `"runaway"` here covers
  both the heater-triggered and pure-overcurrent cases undifferentiated.

**Bug found and fixed during testing** (in this port; the identical
pattern likely exists in `electrothermal/run_transient.py` too, not yet
checked/fixed there — flag before relying on it): `freefem_binary()`
only checked that a resolved candidate was non-`None`, not that it
actually existed/was executable. Passing a bad `--freefem-bin` (or a
stale `FREEFEM_BIN`) passed that check (a bad string is still truthy)
and only failed later inside `subprocess.Popen` with an unhandled
`FileNotFoundError` traceback, not the function's intended clean error
message. Fixed by running `shutil.which()` on whatever candidate wins
regardless of source — it checks existence+executability for an
absolute/relative path too, not just a bare name on `PATH`.

**Verified**: `--help`, the fixed error path (bad `--freefem-bin` now
exits 1 with a clean message, no traceback), and a full `init_failed`
run against a dummy non-zero-exit binary (confirms `status.json`/
`run.log`/exit-code plumbing end-to-end). **Not yet verified**: a real
wrapper-driven run against actual FreeFEM — each physical step here
costs on the order of 15-30 minutes in this sandbox's emulated
(amd64-on-arm64 Docker) environment, several times electrothermal's own
~116.5s/step native figure, and the wrapper's default
`--steps-per-invocation 20` would multiply that further. Test with a
small `--max-steps`/`--steps-per-invocation 1` on the real remote
install before trusting a long unattended run.

Outputs land in this directory: `transient_3d_slit.csv`
(`t,I0,Tmax,TmaxLeft,TmaxRight,fracLeft`), `diagnostics_3d_slit.csv`
(voltage taps, RTDs, real Hall-probe `H1`/`H2` B-field values — not the
`-999` sentinel used by the no-B-field workflow), and
`diagnostics_positions_3d_slit.csv` (sensor geometry metadata, rewritten
each invocation).
