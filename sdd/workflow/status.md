# Phase: status

Report the state of the SDD workflow. Read-only — change nothing.

## Steps

1. List non-archived directories in `sdd/changes/`. For each, determine:
   - **Phase**: which of `proposal.md` / `design.md` / `tasks.md` exist.
   - **Progress**: if `tasks.md` exists, count `- [x]` vs `- [ ]` (e.g. `grep -c '^\s*- \[x\]'`).
2. Count capability specs in `sdd/specs/` and recent entries in `sdd/changes/archive/`.
3. If `sdd/roadmap.md` exists, count done vs pending entries and note the next unchecked one.
4. Present a compact table: change · phase · tasks done/total · suggested next phase (design, tasks, run, or archive). Below it, one line for the roadmap: progress and next entry.

If `sdd/` doesn't exist, say so and point to the init phase. If there are no active changes, say so and point to the new phase (suggesting the next roadmap entry if there is one).
