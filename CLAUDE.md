# CLAUDE.md — repo orientation for agents

HTS tape quench/self-field simulation in FreeFEM. Three model tracks:
`2D/`, `3D/`, `3D-slit/` (most active; adds a laser slit + B-field self-field
modeling). Human-facing history/rationale: `PROJECT_CONTEXT_SUMMARY.md`
(root). Per-track usage: `<track>/README.md`. Track-specific agent notes:
`3D-slit/CLAUDE.md` — read it before touching that directory.

## FreeFEM environment gotchas (verified by direct testing, not assumed)

- **No underscores in identifiers containing a letter-then-underscore
  pattern** (`TcuL_x`, `HALL_NOT_MODELED`) — FreeFEM's parser throws a raw
  syntax error. `TcuLx` works, `TcuL_x` doesn't. Always use camelCase for
  any new variable/function name in `.edp`/`.idp` files. This is the
  single most common self-inflicted bug in this repo's history — check
  new identifiers before debugging anything else.
- **No default function arguments** (`func real f(real x, real b=0.0)`
  fails to parse). Need a new function name for a modified signature; a
  shared `.idp` used by multiple scripts can't get an optional new
  parameter without either updating every call site or duplicating the
  function under a new name.
- **msh3 plugin not in the base `freefem++` apt package.** Fix:
  `apt-get install libfreefem++ libfreefem0`, then symlink —
  `mkdir -p /usr/lib/ff++/<ver>/lib && ln -sf /usr/lib/freefem++/*.so /usr/lib/ff++/<ver>/lib/`
  (FreeFEM looks in the second path, plugins install to the first).
- **`ifstream >>` past EOF throws a fatal, unrecoverable error** — it
  does NOT silently leave the target at 0. If a checkpoint file is
  shorter than what a script tries to read, it crashes immediately, it
  doesn't degrade quietly. (Useful for ruling out checkpoint-format
  mismatches as a cause of silent-zero bugs — if it didn't crash, the
  file's format was already consistent with what was read.)
- **Real 3D-slit timesteps cost minutes, not seconds** (~2-4 min/step
  depending on which physics are active). Never iterate on logic
  against the full mesh. Build small synthetic-data standalone tests
  (mock the handful of globals a `.idp` needs, skip mesh-building
  entirely) to validate formulas/logic first — this is the normal
  workflow in this repo's history, not a shortcut.
- **Background processes do not survive across separate tool calls** in
  this sandbox. A long FreeFEM run started with `nohup ... &` in one
  call is gone by the next call. Use one long foreground call with a
  generous timeout instead.
- `pip install <pkg> --break-system-packages` required.

## Testing discipline that has actually caught real bugs here

- **Look at rendered output, not just exit codes.** Matplotlib scripts
  in this repo have shipped with clipped legends, overlapping labels,
  and mis-scaled axes that a clean exit code didn't reveal — only
  viewing the actual image did.
- **A clean run is not proof of correctness.** The most recent example:
  a lagged self-field array that was silently always zero for an
  entire multi-hour run, no crash, no error — only caught by inspecting
  raw checkpoint contents.
- **Verify current/energy conservation directly** when touching the
  electrical model (`assert(relErr<=1e-3)` pattern already used
  throughout) rather than trusting that a bisection converged.
- **When splitting a formula geometrically** (e.g. decomposing one
  aggregate current term into several sheet/layer terms), check the
  decomposition sums back to the original aggregate exactly before
  trusting anything built on top of it.

## Checkpoint files — a recurring source of subtle bugs

Every `step_*.edp` here follows a checkpoint/resume pattern: one process
invocation advances a few timesteps, saves state, exits; re-running the
same command resumes and continues. **The checkpoint's file format
(what gets written, in what order) must match exactly between whichever
`init_*.edp` created it and whichever `step_*.edp` reads it.** Several
real bugs have come from this: an old-format checkpoint paired with a
newer script (crashes per the EOF behavior above, or — if a field
simply doesn't get read/written at all rather than being short — fails
silently with that field stuck at its zero-initialized default forever,
no crash, no error). When adding a new persisted quantity to a
`step_*.edp`, the matching `init_*.edp` needs updating too, and existing
checkpoints need regenerating, not resuming.
