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
`-maxjcfracchange`/`-maxsteprise`/`-maxbisections`/`-tmaxcutoff`/`-aniso`/
`-selfconsistent`/`-maxpicarditer`/`-picardtol`/`-picardomega`/
`-heaterpower` — see "Ratio/wrapper parameterization" below. All default
to this script's original hardcoded behavior when unflagged. In
practice, drive this through `run_bfield_transient.py` (see
"Continuous-solve wrapper" below) rather than invoking these by hand for
a real run.

**`-heaterpower`** (W, default `13.0`): `0.0` disables the heater
entirely, isolating pure above-Ic ramp-driven quench from
heater-triggered quench — e.g. the full sweep's "without heater" pass
(see "Large aniso+self-consistent sweep" below). Doesn't touch
`tPulseStart`/`tPulseEnd`/the pulse-phase fine-dt schedule — a 0-heater
run still gets the same time resolution through that window as a
real-heater run at the same ratio, for a clean comparison.

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

**Cost (superseded by real numbers below — kept for the reasoning, not
the estimate)**: originally assumed `computeSelfFieldB` (~13-16s/call
under Docker emulation) dominates and the per-x electrical solve stays
uniformly cheap (~0.02s) regardless of iteration count, based on
early-ramp (cold, low-current) profiling data. **Wrong** — see the
landed `r1p2-sc` results below: the electrical solve's own per-call cost
is NOT uniform, and near `Tc` it becomes the dominant cost, not
`computeSelfFieldB`. The real number for `-maxpicarditer 20`'s cost on
a full above-`Ic` ramp is O(hours) on native hardware, not the tens of
seconds/step this estimate implied.

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

**Landed 2026-09-29 — `r1p2-sc` (native remote install, interactive
node, `runs/r1p2-sc/`)**: a real from-scratch ramp run at the exact same
parameters as the original lagged `r1p2` (`-ratio 1.2 -ramprate 20.0
-rampdt 999.0 -tmaxcutoff 250.0`), with `-selfconsistent 1`. This is the
actual point of the feature, and it confirms the fix:

- **The oscillation is gone.** `H1`/`H2` move smoothly and monotonically
  through the entire near-`Tc` window (`t=18.09-18.42s`) — no step-to-
  step zigzag anywhere, vs. `r1p2`'s genuine ringing in that exact
  window. See `runs/compare_r1p2/chart_bfield_lag_vs_selfconsistent.png`
  (generated via the new `shared/plot_compare_bfield_runs.py`).
- **The final outcome barely moved**: `r1p2-sc` hits runaway at
  `t=18.4165s, Tmax=421.169K` vs. `r1p2`'s `t=18.48s, Tmax=423.646K` —
  within ~0.3-0.6% of each other, `fracLeft=0.5` in both. The lag was
  producing noisy intermediate diagnostics, not a wrong aggregate
  quench-timing/severity conclusion — reassuring for anything that
  already leaned on the lagged `r1p2` result.
- **Past `t~18.2` (deep runaway, `Tmax` 220K->421K in both), the two
  traces diverge in a notable way**: self-consistent `H1` plateaus at
  ~6.6mT while lagged `H1` keeps declining sharply toward ~4.0mT, even
  though both end at nearly the same `Tmax`. Plausible read (not
  independently verified beyond this observation): self-field mainly
  tracks TOTAL current through the tape's cross-section, which is
  externally driven and roughly independent of which internal layer
  carries it — so it should stay fairly flat as current redistributes
  from REBCO into the resistive stabilizer during runaway, which is
  what the self-consistent trace does. The lagged trace's decline right
  when the state is changing fastest is consistent with its self-field
  diagnostic becoming actively stale (not just noisy) during exactly
  the part of the trajectory you'd most want it to be trustworthy.
- **No real non-convergence, no runaway bisection behavior**: `run.log`
  has 3 literal hits for the string "PICARD-NOT-CONVERGED", but all 3
  are FreeFEM's own source-line echo from each invocation's startup
  parse trace (`426 :  cout << "PICARD-NOT-CONVERGED...`), not the
  warning actually firing — the Picard loop converged every step.
  `picardIters` peaked at 13 (well under `maxpicarditer=20`);
  `picardRelErr` stayed under `1e-3` throughout. The `[bisect]` heatStep
  dt-halving safety net (pre-existing, unrelated to Picard) genuinely
  fired 8 times as `Tmax` approached `Tc` (`jcFrac` 0.05-0.17), one
  halving each time, same as it does in the lagged runs.
- **Cost was real**: `wall_clock_seconds: 29629.5` (~8.2 hours) for the
  full run on native hardware — 3 invocations, dominated by the
  electrical solve's per-call cost ballooning near `Tc` (its internal
  doubling-guard bisection needs many more brackets once resistivity
  rises and `Jc(T)` shrinks — an existing property of `solveEFullB`/
  `solveEHalfB`, not something the Picard restructuring introduced, but
  only visible once Picard multiplies it by iteration count) combined
  with 8-13 Picard iterations/step in the stiffest window. The original
  cost estimate above (from early-ramp, cold, cheap-electrical profiling
  data) badly undersold this — treat "~15-25 min" as wrong for anything
  that actually reaches the above-`Ic` ramp window; O(hours) is the
  right expectation there. User's assessment: acceptable given a
  parallelized (Condor) workflow.

**Landed 2026-09-29 — `r1p2-aniso-sc`** (same parameters as `r1p2-aniso`,
`-selfconsistent 1 -aniso 1`): the natural follow-up, comparing against
`r1p2-aniso` (lagged, anisotropic). Result is more nuanced than the pure
isotropic comparison above — **two distinct phenomena, only one of which
this feature actually fixes**:

- **Pre-pulse near-`Tc` ringing (the thing this feature targets)**:
  confirmed fixed here too. `H1`/`H2` rise smoothly with no step-to-step
  zigzag through the whole pre-pulse ramp (`t=15.55-18.66s`), same as the
  isotropic case. See
  `runs/compare_r1p2_aniso/chart_bfield_aniso_lag_vs_selfconsistent.png`.
- **Post-heater-pulse transient (anisotropic model only) is NOT a lag
  artifact.** `fracLeft` swings `0.5 -> ~0.37 -> ~0.63 ->` partial
  damping in BOTH the lagged (`r1p2-aniso`: trough `0.363`, peak `0.636`,
  final `0.566`) and self-consistent (`r1p2-aniso-sc`: trough `0.371`,
  peak `0.633`, final `0.525`) runs — nearly the same shape and
  magnitude either way. Every individual step's Picard loop converged
  cleanly throughout this window (`picardRelErr<1e-3`, no
  non-convergence), so this isn't the lagged-coupling ringing this
  feature was built to fix — it looks like genuine current-sharing
  dynamics: the heater's sharp, left-side-only, step-function
  perturbation interacting with the anisotropic model's directionally-
  dependent Jc suppression, which the purely-resistive current-split
  bisection can plausibly overshoot/ring in response to regardless of
  how B is coupled. Self-consistency does damp it SOMEWHAT (final
  `fracLeft` closer to 0.5: `0.525` vs `0.567`), just not dominantly.
- `wall_clock_seconds: 19512.2` (~5.4 hours, 2 invocations) — cheaper
  overall than the isotropic `r1p2-sc` comparison (~8.2 hours, 3
  invocations) despite the anisotropic path doing marginally more work
  per call; likely reflects this trajectory needing fewer total
  physical steps to reach the same `tmaxCutoff`, not a per-call cost
  difference. Not independently confirmed.

**Open question, not yet investigated**: whether the post-pulse
`fracLeft` transient is a genuine, physically-expected response (a
real current-sharing overshoot to a sudden local perturbation) or
reflects some other modeling simplification worth examining (e.g. the
purely-algebraic per-timestep current-split bisection has no notion of
inductance/inertia, so a real circuit would damp an equivalent
perturbation over some L/R time constant this model doesn't
represent). Flagged, not pursued further without explicit direction.

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

## Large aniso+self-consistent sweep (0.7-1.5 Ic, heater on/off)

Decided 2026-10-02, once the four-way lagged/self-consistent x
isotropic/anisotropic comparison at `ratio=1.2` landed (above): run two
full 801-ratio sweeps (`0.700` to `1.500`, step `0.001`) at
`-aniso 1 -selfconsistent 1` throughout, one with the heater firing
normally and one with `-heaterpower 0.0`, to characterize the full
transport-current-ratio quench-threshold curve under the validated
(self-consistent, anisotropic) physics instead of just the handful of
spot-checked ratios so far.

**This required adding `-heaterpower`** (see above) — the heater had no
on/off toggle before this, so the "without heater" half of the ask
wasn't possible until it was built.

**User explicitly chose full 0.1% granularity across the whole range**
(801 ratios x 2 sweeps = 1602 jobs) over a calibrate-first or tiered-
granularity alternative, after being shown the cost asymmetry already
on record here: self-consistent cost is O(minutes) for ratios that
never approach `Ic`/`Tc`, but O(hours) (5.4-8.2h, see above) for ratios
that enter the above-Ic ramp window — and this track's very first cost
estimate for this feature was off by ~20-30x, so any extrapolation
across the full range is a guess, not a measurement, until real jobs
land.

**Known real risks at this scale** (see `condor/README.md`'s expanded
"Known limitations" for the full version):
- **No resume-on-preemption**: a preempted self-consistent job in the
  above-Ic regime restarts from `t=0` and re-burns its full O(hours)
  cost. At ~800 such ratios per sweep on a shared pool, expect some
  preemptions — this is a real, not hypothetical, cost multiplier here,
  unlike for the one-off comparisons run so far.
- **`request_memory`/`request_disk` are still first-pass guesses**
  carried over from electrothermal, never stress-tested at this job
  count.
- **The `-heaterpower 0.0` code path has never been run for real** —
  only reasoned about from the diff (see the flag's own comment above).
  `condor/README.md` recommends a small pilot (a handful of
  representative ratios) before committing the full 1602-job
  submission; whether that pilot was actually run before the full
  sweep is not yet recorded here — check `runs/` for pilot-labeled
  results or ask before assuming the full sweep already reflects a
  verified `-heaterpower 0.0` path.

**Status**: infrastructure built (`-heaterpower` flag, 6-column
`ratios.txt` schema, `sweep.sub`/`make_ratios_list.py`/
`run_bfield_transient.py` updated) and documented in
`condor/README.md`. Full sweeps submitted 2026-10-06. Update this
section once they land, with the resulting quench-threshold curve (the
actual research deliverable this sweep exists to produce).

**Major cost-model correction, landed 2026-10-06 (`r0p7-aniso-sc-noheater-pilot`,
`runs/`)** — supersedes the "near-`Tc` electrical blowup" theory above,
which was WRONG. This pilot ran the full scripted duration at `ratio=0.7`
with the heater OFF (`-heaterpower 0.0`) under the real sweep config
(`-aniso 1 -selfconsistent 1`): `Tmax` stayed flat at ~77.00xK the
ENTIRE run (never approached `Ic` or `Tc`, exactly as expected with no
heater at a low ratio) — and it still took `17581.1s` (~4.9 hours) over
100 physical steps.

Grepping every `TIMING` line (not just the tail, which is all prior
investigation had looked at) across the full run: `electrical` averaged
**49.0s/step** and `fieldAssign` averaged **108.5s/step**, both
essentially CONSTANT across all 100 steps regardless of temperature.
Only the very first step of any fresh run is cheap (`I0w=0` short-
circuits `solveEFullB`/`solveEHalfB` to `return 0.0` instantly before
any bisection runs) — which is exactly the sampling bias that produced
every earlier "cheap" data point in this file: every prior measurement
below this line was either a first-step smoke test or a tail-of-run.log
snippet from a run already deep into its trajectory, never a full
per-step accounting.

This reconciles cleanly with `electrothermal`'s long-documented
~116.5s/step native baseline: `fieldAssign+heatSolve+diagnostics` here
(~118s) closely matches that pre-existing, B-field-unrelated cost (same
mesh, same FE field assignment — `electrothermal` pays it too, just
without any B-field/Kim-model work on top), while this workflow adds
`Bfield` (~6s, the Biot-Savart self-field pass) and the Kim-model-aware
electrical solve's internal bisection overhead (~49s, present in BOTH
`solveEFullB`/`solveEHalfB` and their `*BAniso` variants — isotropic vs.
anisotropic doesn't change this) on top of that shared baseline,
landing almost exactly at the observed ~170s/step total.

**Corrected cost model**: a run's total cost scales mainly with **how
many physical timesteps it needs to complete** (set by the ramp/pulse/
post-pulse `dt` schedule, roughly 100 steps for a below-Ic run; likely
more for an above-Ic run needing finer adaptive stepping) at a ~170s/
step baseline, further multiplied on whichever specific steps the
Picard loop needs >1 iteration (observed up to 4-6x on a handful of
steps in this same pilot, at phase-boundary transitions) — NOT by
proximity to `Ic`/`Tc` the way the "Landed 2026-09-29" section above
assumed. Practical upshot: there is no cheap region of the 0.7-1.5
sweep — every ratio, heater on or off, costs multiple hours, because
the ~170s/step floor applies everywhere once real current is flowing.
Confirmed with the user before proceeding at the originally-requested
full 0.1%-granularity, 1602-job scale regardless.

**Not investigated**: whether the ~49s/~108s per-call costs are
reducible (e.g. `solveEFullB`'s doubling-guard search re-bracketing
`Ehi0` from scratch every call rather than warm-starting from a nearby
previous solve; whether this specific remote execute node is unusually
slow vs. pool-typical) — flagged as a real option if sweep cost ever
needs to come down, not pursued here per the user's explicit choice to
proceed at full scale first.

**Incident, 2026-10-07 — pool walltime cap vs. the retry policy.** Once
the (re-split 900/250, see below) sweeps were actually running, several
ratios ran past this Condor pool's own ~20h walltime cap and were
forcibly killed mid-run — almost certainly the ratios sitting right at
the marginal/slow-to-settle quench threshold (classic critical-slowing-
down near a bifurcation), which is informative in its own right, not
just an inconvenience. The real problem: `on_exit_hold`/
`periodic_release` (designed for the node-dependent UMFPACK failure
mode, where retrying on a different node can genuinely help) then
blindly retried these up to 4x — but a walltime timeout is
DETERMINISTIC (the same ratio needs roughly the same wall-clock again),
so this burned up to 4x the pool's own cap for zero benefit before
landing on permanent hold. Same anti-pattern already avoided for Picard
non-convergence (log-and-proceed instead of assert-and-retry); this
needed the same treatment.

**Fixed**: `run_bfield_transient.py` gained `--max-wall-seconds`,
checked at the top of `run_one()`'s invocation loop (before starting
another FreeFEM invocation, not after — an invocation can itself cost
up to `steps_per_invocation x ~170s`, so checking only after would let
the exact kill-by-the-pool scenario this exists to avoid still happen
on the invocation that pushes past budget). Exceeding it returns a new
`"wall_budget_exceeded"` status, deliberately kept OUT of
`RETRY_WORTHY_STATUSES` so `main()` exits 0 — Condor sees a normal
completion, never entering the retry loop. `sweep.sub` now hardcodes
`max_wall_seconds = 64800` (18h, a margin under the observed 20h cap)
as a file-level macro and passes it via `--max-wall-seconds
$(max_wall_seconds)` — a pool-level constant, not a per-ratio sweep
dimension, so (like `request_memory`/`request_disk`) it's hardcoded in
`sweep.sub` rather than a `ratios.txt` column.

**Verified** with a fake fast-exiting `FreeFem++` stub (real
end-to-end exercise of `run_one()`'s control flow, not just a code
read): `--max-wall-seconds 0.5` stopped after 0 steps (budget already
exceeded by the init invocation's own overhead) with status
`wall_budget_exceeded`; `--max-wall-seconds 2.0` ran 7 steps before
stopping; both exited 0. **Not verified**: real behavior against actual
FreeFEM at sweep scale (no reason to expect a difference — the check is
pure Python control flow around the same `run_freefem()` call already
exercised everywhere else in this file).

**Does NOT rescue jobs already stuck in the retry loop** — no
checkpoint-resume exists (`run_bfield_transient.py` still has no
`--resume`, and even if it did, Condor's own retry re-extracts a fresh
`payload.tar.gz` sandbox with no path for a prior attempt's partial
output to feed back in as input). Already-held jobs from the affected
batch need to exhaust their retries (or be `condor_rm`'d) and get
resubmitted fresh once `make_payload.sh` has repackaged this fix — which
is exactly the user's stated plan: let the current batch finish/hold,
then resubmit the timed-out ratios.

**Also corrected during this incident's investigation**: the sweep's
`--runaway-tmax` is no longer a flat `250` across the whole `0.7-1.5`
range. Re-examined and re-split per `make_ratios_list.py`'s own
docstring convention: `900` (loose, "shouldn't get anywhere near this"
default) for `0.700-0.999`, `250` (tight, catch real above-Ic runaway
early) for `1.000-1.500` — a flat `250` risked misclassifying a
benign, still-recovering heater-driven transient at low ratio as
`"runaway"` before it had a chance to settle, corrupting exactly the
quench-threshold curve this sweep exists to produce. (Spot-checked: a
local `ratio=0.7` heater-on smoke test showed `TmaxLeft` peak at
`102.274K` then monotonically decline — safely under either threshold
for that one data point, but the split removes the risk for the rest
of the sub-Ic range rather than relying on a single spot-check.)

## Realistic 20 A/s ramp — the landed sweep ran a different (fast) protocol than intended

**Found 2026-10-08**, while building cross-ratio summary analysis for
the landed sweep (597 heater-on + 650 heater-off runs). The user
expected a ~20 A/s current ramp; the `t`-axis on the summary plots
didn't match.

**Confirmed from the data**:
`runs/r0p7-aniso-sc-noheater-pilot/transient_3d_slit.csv` shows `I0`
climbing from 0 to its 217.672A target over a FIXED `t=0->0.5s` window
— **~435 A/s**, not 20. Because that window is a fixed 0.5s duration
regardless of ratio, the implied rate actually scales *with* ratio
(~435 A/s at ratio=0.7, ~933 A/s at ratio=1.5) rather than being
constant across the sweep.

**Confirmed from the code**: `condor/sweep.sub`'s `arguments` line
never passed `-ramprate`/`-rampdt` at all for this sweep, so every job
silently fell through to `run_bfield_transient.py`'s old `DEFAULT_RAMP_RATE=0.0`
sentinel ("use the `.edp`'s original fixed 0.5s ramp"). This is a gap
in the Condor submit file only — **the `.edp` itself already had
everything needed**, already validated in this exact codebase's
history: `-ramprate 20.0 -rampdt 999.0` is exactly what the earlier
one-off `r1p2`/`r1p2-sc` confirmation runs used (see "Landed
2026-09-29" above), itself ported from `electrothermal/CLAUDE.md`'s
extensively-validated "Ramp rate / ramp-dt -- validated" section (same
20 A/s collaborator-requested rate). The big sweep's automation layer
simply never wired it through.

**User's decision**: keep the already-landed fast-ramp sweep as its own
valid dataset — it is NOT being discarded or rerun-in-place. **The
quench-threshold numbers recorded above (~0.87-0.88xIc heater-on,
~1.16-1.17xIc heater-off) belong to this fast fixed-duration-ramp
scenario specifically** — they should not be read as "the" quench
threshold until the realistic-ramp resubmission below lands and either
confirms or revises them. A slower ramp gives the thermal/current-
sharing system materially more time to respond during ramp-up, which
could shift the threshold in either direction; this is an open
empirical question, not assumed settled by the fast-ramp numbers.

**Fix (implemented)**: `run_bfield_transient.py`'s `DEFAULT_RAMP_RATE`
is now `20.0` and `DEFAULT_RAMP_DT` is now `999.0` (collapses the
sub-`Ic` ramp phase to a single step — validated safe for
`currentRatio<=1` in electrothermal's own ramp-rate validation;
`DEFAULT_RAMP_DT_ABOVE_IC` stays `0.002`, already correct and
unaffected). `condor/sweep.sub` now hardcodes `ramp_rate = 20.0`/
`ramp_dt = 999.0` as explicit file-level macros (same class as
`max_wall_seconds`), passed via `--ramp-rate $(ramp_rate) --ramp-dt
$(ramp_dt)`. No `.edp` changes were needed for this part — see
"Ratio/wrapper parameterization" above for why the existing
`-ramprate`/`-rampdt`/`-rampdt-aboveic` design already handles both the
sub-`Ic` collapse and the above-`Ic` adaptive-growth sub-phase safely.

## Heater-pulse Picard non-convergence — root cause found, independent of ramp rate

Found while investigating the same landed sweep's
`chart_summary_peak_picard_iters.png`, which showed many heater-on runs
pinned at the `-maxpicarditer 20` cap. The user's own hypothesis was
that the (then-undiscovered) ramp-rate bug was also responsible
("sharp transition kinks"). **Checked directly against real landed
diagnostics CSVs, not assumed:**

- `runs/r0p75-aniso-sc/diagnostics_3d_slit.csv` (ratio=0.75, inside a
  ratio bucket where every run hit the cap): `picardIters=1` for the
  entire pre-pulse ramp (expected — ratio<1 never approaches `Ic`, so
  nothing is stiff yet), then **20 for all 4 steps strictly inside
  `[tPulseStart, tPulseEnd]=[0.5, 0.51]`** (`picardRelErr` stuck at
  0.016-0.05, i.e. 16-50x over the `1e-3` tolerance), then immediately
  back to single digits (4,8,7,6...) the instant the pulse ends.
- `runs/r1p22-aniso-sc/diagnostics_3d_slit.csv` (ratio=1.22, just past
  where cap-hitting stops in the ratio-binned breakdown): the SAME
  pulse-window steps only need 8-12 iterations — confirms this is
  ratio-dependent (worst in the marginal/near-threshold band roughly
  0.70-1.20, with the 1.05-1.15 band 100% capped), not a universal
  property of the pulse itself.

**Conclusion: the ramp-rate fix above will NOT by itself fix this.**
`dtRaw()`'s pulse-phase branch (`if (tt < tPulseEnd) return pulseDt;`,
previously a hardcoded `0.002`) is a fixed absolute dt completely
independent of `Tramp`/ramp rate — the heater's abrupt onset within
that fixed window is the actual stiffness, not the ramp leading up to
it. The ramp-rate fix may still help the separate above-`Ic` approach
into the pulse for ratio>1 (a real, different stiff regime the adaptive
`rampDtAboveIc` controller already handles), but the pulse itself needs
its own fix.

**Fix (implemented)**: new `-pulsedt` flag in
`step_3d_slit_transient_bfield.edp` (default `0.002`, today's exact
hardcoded value — unflagged/raw-invocation behavior unchanged),
replacing the literal `0.002` in `dtRaw()`. `run_bfield_transient.py`'s
own defaults: `DEFAULT_PULSE_DT = 0.0005` (4x finer, shrinks the
per-step jump in the abrupt heater-driven transition directly) and
`DEFAULT_MAX_PICARD_ITER` raised `20 -> 40` (headroom for whatever
residual stiffness the finer dt doesn't fully resolve). `condor/sweep.sub`
hardcodes matching `pulse_dt = 0.0005`/`max_picard_iter = 40` macros.

**These two values are starting hypotheses, not confirmed numbers** —
to be validated via a targeted smoke test (one known-100%-capped ratio,
e.g. 1.10, run just past the pulse window) before committing to a full
resubmit. Update this section with the real measured result once that
test lands: does the cap-hitting actually clear, and what's the real
added wall-clock cost for the pulse window at the finer dt (replacing
the untested ~20-step estimate this fix was designed around).

**Status**: both fixes implemented and documented 2026-10-08. Not yet
smoke-tested on real hardware, not yet resubmitted. The already-landed
1247-run fast-ramp sweep stands as its own dataset per the user's
explicit decision above — resubmission under the corrected protocol is
a separate, later batch, not a replacement/overwrite of it.
