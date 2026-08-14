# 3D-slit/CLAUDE.md — track overview

This track models the laser-slit HTS tape with self-field/B-field
physics. It's split into two independently runnable workflows plus
shared code — read the subdirectory's own `CLAUDE.md` before touching
its scripts.

```
3D-slit/
├── shared/           idp/data/plotting code used by BOTH workflows
├── Bfield/           canonical B-field workflow — see Bfield/CLAUDE.md
├── electrothermal/   canonical + reference electrothermal scripts — see electrothermal/CLAUDE.md
└── archive/          stale scripts, a pre-split checkpoint/CSV, old images
```

## Why the split

Before this reorg, every transient script (`_bfield`, `_diag`, and the
now-archived pre-fix `step_3d_slit_transient.edp`) lived flat in this
directory and read/wrote the **same** checkpoint and CSV filenames
(`ckpt_3d_slit_transient.txt`, `transient_3d_slit.csv`,
`diagnostics_3d_slit.csv`). Nothing stopped one script's run from
clobbering another's state — exactly the checkpoint-format hazard the
root `CLAUDE.md` warns about. Splitting into `Bfield/` and
`electrothermal/` fixes this by directory separation: each workflow now
has its own copy of these filenames, isolated from the other.

**Never copy a checkpoint file between `Bfield/` and `electrothermal/`**
— even though the filenames now match again (one per directory), the
formats are still different (see each subdirectory's `CLAUDE.md`).

## Shared code (`shared/`)

`hts_mesh_module_3d_slit.idp`, `hts_materials.idp`, `diagnostics_3d_slit.idp`,
`data/` (15 material-property tables), and the 3 Python plotting scripts
(`plot_slit_transient.py`, `plot_diagnostics_3d_slit.py`,
`plot_diagnostics_layout_3d_slit.py`) live here because both workflows
depend on them identically. Scripts in `Bfield/`/`electrothermal/`
reach them via `include "../shared/<file>"`; **always invoke `FreeFem++`
from inside the `Bfield/` or `electrothermal/` directory**, not from
`3D-slit/` itself — the relative paths assume that working directory.
The Python plotting scripts take their CSV path as a CLI argument, so
run them the same way, e.g. from within `Bfield/`:
`python3 ../shared/plot_slit_transient.py transient_3d_slit.csv`.

If you edit anything in `shared/`, both workflows are affected — check
both before assuming a fix or change is isolated.

## Region/label quick reference (applies to both workflows)

Mesh regions (`shared/hts_mesh_module_3d_slit.idp`): 1=Cu shell (wraps
all 4 sides, ONE conductor — not separate top/bottom), 2=Ag bottom,
3=Hastelloy, 4=buffer, 5=REBCO, 6=Ag top, 7=slit (vacuum-like).
`cube()`'s boundary labels: 1/3=y-lateral walls, 2/4=x-end faces,
5/6=z-lateral walls — **verify by area, don't assume** (this exact
assumption was wrong once).

Within the slit's x-range (10-190mm), current is split into independent
left (`z<zSlitCenter`, represented at `zLeftRep=width/4`) and right
(`zRightRep=3*width/4`) channels for every conducting layer EXCEPT the
Cu shell's side walls, which sit entirely on one side already and are
never severed by the slit.

## Physics simplification inventory (current state, check before assuming a limitation is still open)

- **Hastelloy**: genuine parallel resistive branch (real measured
  resistivity), included in current-sharing AND Joule heating, across
  ALL tracks (2D/3D/3D-slit), all scripts. Was previously hard-excluded
  everywhere — now fixed everywhere.
- **Buffer**: still excluded. Different, better-justified case than
  Hastelloy was — its conductivity is an assumed placeholder
  (`sigmaBuf=1e-10 S/m`) ~4 orders of magnitude below even Hastelloy's
  real value, not just "high resistance."
- B-field-specific simplifications (self-field-only, lagged, isotropic
  Kim model, etc.) are documented in `Bfield/CLAUDE.md` and in
  `Bfield/bfield_3d_slit.idp`'s header — that workflow only.

## Archive (`archive/`)

Kept for reference/history, not part of either active workflow:
`step_3d_slit_transient.edp` (stale pre-fix single-point electrical
model), `INSTRUCTIONS.md` (old handoff note, predates this split),
`slit_transient_handoff.zip` (old snapshot), and a checkpoint/CSV set
confirmed stale (mismatched provenance — produced by an old version of
the pre-fix script, not either canonical script) plus the images
generated from it.
